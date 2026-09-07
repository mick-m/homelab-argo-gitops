# AGENTS.md — homelab-argo-gitops

Day-1+ GitOps repo for the Sunnyside homelab. ArgoCD renders Kustomize overlays
from this repo onto two single-node K3s clusters. Day-0 cluster build lives in the
sibling repo `homelab-ansible-bootstrap` (which has its own AGENTS.md).

Human-facing docs are in [README.md](README.md). This file covers what an agent
needs to change things safely.

## The one thing to understand first

Two branches, two clusters, two different render paths:

| Env | Branch | ArgoCD path it renders | Sync |
|---|---|---|---|
| staging (192.168.1.251) | `main` | `envs/staging/<ns>` | auto (prune + selfHeal) |
| prod (192.168.1.173) | `prod` | **`base/<ns>`** | manual |

Prod renders `base/` *directly* — see [argocd/prod/apps.yaml](argocd/prod/apps.yaml).
`envs/prod/` only holds the monitoring overlay and sealed secrets. Consequences:

- **`base/` is production.** An edit to `base/` is a prod change staged on `main`;
  it ships the moment someone fast-forwards `prod` and syncs.
- Staging is `base/` + hostname patches. `envs/staging/<ns>/kustomization.yaml`
  rewrites every Ingress host to the `staging-` prefix.
- `envs/prod/kustomization.yaml` and `envs/staging/kustomization.yaml` (the two
  root-level ones listing all five namespaces) are **vestigial** — nothing renders
  them. Don't add to them expecting an effect.

Merging to `main` deploys to staging by itself. Reaching prod needs two deliberate
steps: fast-forward the `prod` branch (Actions → *Promote to Prod*, or
`git checkout prod && git merge main --ff-only && git push`), then
`argocd app sync -l env=prod`. Never commit directly on `prod`; it must stay a
fast-forward of `main`.

## Layout

```
base/<namespace>/<service>/     # canonical manifests = prod
  deployment.yaml service.yaml ingress.yaml pvc.yaml kustomization.yaml
base/<namespace>/kustomization.yaml     # lists the service dirs
base/monitoring/                # Helm values + ingress + exporters/
envs/staging/<namespace>/       # base + staging- hostname patches
envs/<env>/monitoring/          # per-env Helm values, ingress, sealed-secrets
argocd/<env>/apps.yaml          # ApplicationSet (Kustomize apps) + monitoring Application
```

Namespaces: `utilities`, `media`, `productivity`, `infra`, `monitoring`.

## Adding a service — the full checklist

Missing step 3 is the classic failure: staging and prod both claim the bare
hostname, and two clusters fight over one cert/DNS name.

1. `base/<ns>/<service>/` with `deployment.yaml`, `service.yaml`, `ingress.yaml`,
   `pvc.yaml` (if stateful) and a `kustomization.yaml` listing them.
2. Add the directory to `base/<ns>/kustomization.yaml`.
3. **Add an Ingress host patch to `envs/staging/<ns>/kustomization.yaml`** —
   host, `tls[0].hosts[0]`, and `tls[0].secretName`, all prefixed `staging-`.
4. Add a tile to `base/utilities/homepage/config/services.yaml` **and** the staging
   copy `envs/staging/utilities/homepage-config/services.yaml` (they are separate
   files; the staging one uses `staging-` URLs).
5. Verify the render (below), then commit to `main`.
6. Out-of-repo: DNS A record for the new hostname (both `svc.` and `staging-svc.`).

## Manifest conventions

Copy [base/media/sonarr/](base/media/sonarr/) as the reference shape.

- Every object sets `metadata.namespace` explicitly and carries
  `app.kubernetes.io/name: <service>` + `app.kubernetes.io/part-of: homelab`.
  The Deployment selector matches on `app.kubernetes.io/name` only.
- Service is `ClusterIP`, `port: 80` → `targetPort: <container port>`. Ingress
  always points at port 80, so the container port never leaks into the Ingress.
- Ingress: `ingressClassName: traefik`, annotation
  `cert-manager.io/cluster-issuer: stepca-acme`, TLS secret named `<service>-tls`.
- `TZ: Europe/Dublin` everywhere; `PUID`/`PGID` `"1000"` on linuxserver images.
- Resource requests *and* limits on every container — these are small nodes and
  staging has been OOM-killed before.
- Liveness + readiness probes (tcpSocket is the norm for the *arr stack).
- Config PVCs: `storageClassName: nfs-client`, RWO, a few Gi. Bulk media is
  mounted as inline `nfs:` volumes from `192.168.1.202`, not PVCs.
- Multi-workload apps get one file per Deployment in the same directory
  (`deployment-db.yaml`, `deployment-worker.yaml`, …) — see
  [base/utilities/firecrawl/](base/utilities/firecrawl/).

## Traps

**JSON6902 patches index into arrays by position.** Staging patches contain paths
like `/spec/template/spec/containers/1/env/9/value`
([envs/staging/productivity/kustomization.yaml](envs/staging/productivity/kustomization.yaml)
patches Nextcloud this way, and the homepage Deployment patch uses `env/1`).
Reordering or inserting an env var in a `base/` Deployment silently re-points the
staging patch at the wrong key — it does not error. After touching env lists in
`base/`, re-render the staging overlay and diff the patched fields.

**Homepage config rides on the ConfigMap hash.** The Deployment mounts
`services.yaml`/`settings.yaml` with `subPath`, and Kubernetes never propagates
ConfigMap edits into a subPath mount. `configMapGenerator` gives the ConfigMap a
content-hash suffix, so an edit changes the name, changes the volume reference,
and rolls the pod. Never set `disableNameSuffixHash`, and keep the staging
override as `behavior: replace` (not a new generator). See
[base/utilities/homepage/kustomization.yaml](base/utilities/homepage/kustomization.yaml).
The prod tiles are `base/utilities/homepage/config/services.yaml`; staging has its own
copy at `envs/staging/utilities/homepage-config/services.yaml`. Edit both.

**SealedSecrets are per-cluster.** Each cluster has its own key, so a secret must
be sealed twice — once into `envs/staging/<ns>/sealed-secrets/`, once into
`envs/prod/<ns>/sealed-secrets/`. Never copy a sealed file between environments.
Today only `monitoring` has any. `vpn-credentials` (media) and the inline DB
passwords in Deployment envs are *not* sealed yet — don't treat a plaintext
password in a `base/` Deployment as a bug you should silently "fix" by inventing
a secret; it changes the rollout.

**Monitoring is Helm, not Kustomize.** `kube-prometheus-stack` is a multi-source
ArgoCD Application: chart from the Prometheus community repo, values from
`$values/base/monitoring/values.yaml` (prod) or
`$values/envs/staging/monitoring/values.yaml` (staging), plus a Kustomize path for
ingress/exporters/sealed-secrets. Prod sets `skipCrds: true`; staging does not.
Staging values are deliberately smaller (2Gi retention, trimmed dashboards) — do
not sync the two files. Grafana's Service name differs per env
(`prod-monitoring-grafana` vs `staging-monitoring-grafana`), which is why the
ingress is duplicated rather than patched.

**Don't `kubectl apply` to the clusters to "fix" something.** Staging self-heals
and will revert you; prod does not self-heal and will silently drift from git.
Change the manifest.

## Verify before committing

```bash
for d in envs/staging/utilities envs/staging/media envs/staging/productivity envs/staging/infra envs/staging/monitoring base/utilities base/media base/productivity base/infra envs/prod/monitoring; do echo "--- $d"; kubectl kustomize "$d" >/dev/null || echo "FAILED: $d"; done
```

Both the staging path and the corresponding `base/` path must build — prod renders
`base/` directly, so a `base/` build failure breaks prod even if staging is fine.

To inspect what actually changed in a rendered overlay:

```bash
kubectl kustomize envs/staging/utilities | grep -A3 'host:'
```

Cluster state (kubeconfig contexts exist for both clusters):

```bash
kubectl -n argocd get applications
```

## Renovate

[renovate.json](renovate.json) scans Mondays 08:00 Europe/Dublin against `main`.
Patch/digest bumps of container images auto-merge (→ straight to staging); Helm
updates are grouped; major bumps of `postgres`/`redis` are disabled because they
need a manual DB migration. Most images are `:latest`, so Renovate pins them to
digests. Don't hand-pin an image tag without checking whether Renovate already
manages it.

Three managers are configured, and the distinction matters:

- `kubernetes` — image tags in every `*.yaml`. This is what most PRs come from.
- `helm-values` — images referenced inside `base/monitoring/values.yaml` and the
  staging copy. Enabled by default; no config needed.
- `argocd` — the Helm chart pins inside `argocd/*/apps.yaml`
  (`spec.sources[].chart` + `targetRevision`). **This manager ships disabled** —
  it has no default file patterns — so without the explicit block in
  `renovate.json` those pins are invisible and drift silently. They did: the
  `kube-prometheus-stack` pin sat 8 majors behind before this was noticed.

Chart bumps never auto-merge. A chart carries CRDs and a values schema, and prod
runs `skipCrds: true`, so its CRDs are applied by hand — an unattended chart merge
would leave the operator and its CRDs at different versions. Before taking a chart
PR, render both values files against the new version:

```bash
helm template kps prometheus-community/kube-prometheus-stack --version <new> \
  -f base/monitoring/values.yaml --namespace monitoring --skip-crds >/dev/null
```

Note that editing `argocd/*/apps.yaml` changes nothing on a cluster by itself —
those manifests are applied by hand (see the Ansible repo's AGENTS.md). A chart
bump here is staged until someone runs `kubectl apply -f argocd/<env>/apps.yaml`.

## Commits

Conventional Commits, imperative, lowercase subject: `feat:`, `fix:`, `docs:`,
`chore:`. Scope only where it clarifies (`chore(renovate): …`). PRs against `main`.
