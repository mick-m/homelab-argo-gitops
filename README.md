# homelab-argo-gitops

GitOps repository for the Sunnyside homelab Kubernetes clusters, managed by ArgoCD.

## Architecture

| Layer | Repo | Platform | Purpose |
|-------|------|----------|---------|
| Day 0 | `homelab-ansible-bootstrap` | GitHub | K3s, MetalLB, cert-manager, Traefik, ArgoCD |
| Day 1+ | `homelab-argo-gitops` (this repo) | GitHub | Application manifests, managed by ArgoCD |
| OS Updates | `homelab-os-updates` | [GitLab](https://gitlab.sunnyside.home/root/homelab-os-updates/) | Ubuntu package updates on K3s VMs |

## Repository Structure

```
homelab-argo-gitops/
├── base/                          # Canonical Kustomize bases per namespace/service
│   ├── utilities/                 # homepage, it-tools, open-webui, firecrawl, etc.
│   ├── media/                     # plex, sonarr, radarr, bazarr, etc.
│   ├── productivity/              # freshrss, mealie, nextcloud, paperless, searxng
│   ├── infra/                     # guacamole, uptime-kuma, netalertx
│   └── monitoring/                # kube-prometheus-stack (Helm values)
├── envs/
│   ├── staging/                   # Overlay per namespace: staging- hostname patches
│   │   ├── utilities/             # (+ homepage-config/ — staging dashboard)
│   │   ├── media/
│   │   ├── productivity/
│   │   ├── infra/
│   │   └── monitoring/            # staging Helm values, ingress, sealed-secrets/
│   └── prod/                      # Prod renders base/ directly — only monitoring
│       └── monitoring/            # prod ingress + exporters + sealed-secrets/
├── argocd/
│   ├── staging/
│   │   └── apps.yaml              # ArgoCD ApplicationSet (tracks main branch)
│   └── prod/
│       └── apps.yaml              # ArgoCD ApplicationSet (tracks prod branch)
└── .github/workflows/
    └── promote-to-prod.yml        # Manual workflow to fast-forward prod to main
```

## Environments

| Environment | Branch | Renders | Sync Policy | Cluster |
|-------------|--------|---------|-------------|---------|
| staging | `main` | `envs/staging/<ns>` | Auto-sync (prune + self-heal) | k3s-staging (192.168.1.251) |
| prod | `prod` | `base/<ns>` | Manual sync | k3s-prod (192.168.1.173) |

Note that **prod renders `base/` directly** — there is no per-namespace prod overlay.
`base/` is production; the staging overlay is base plus `staging-` hostname patches.

Staging auto-syncs from `main` — merging a PR deploys it.

Prod tracks the `prod` branch but has **no** `automated` sync policy. Fast-forwarding the branch only stages the change: ArgoCD notices it and marks the `prod-*` Applications `OutOfSync`, then waits. Deploying is a deliberate second step. Promotion is therefore two gates — which commits reach the `prod` branch, and when you sync them.

## Namespaces

| Namespace | Services |
|-----------|----------|
| `utilities` | homepage, it-tools, open-webui, openspeedtest, stirling-pdf, firecrawl |
| `media` | plex, sonarr, radarr, bazarr, prowlarr, qbittorrent, seerr, tautulli, tunarr, metube, flaresolverr |
| `productivity` | freshrss, mealie, searxng, nextcloud (+db), paperless (+db) |
| `infra` | guacamole (+db), uptime-kuma, netalertx |
| `monitoring` | kube-prometheus-stack (Helm), graphite-exporter (TrueNAS metrics) |

## Monitoring

Monitoring uses the `kube-prometheus-stack` Helm chart with additional dashboards:

- **TrueNAS** — Overview, disk insights, and temperatures (via graphite-exporter)
- **macOS Node Exporter** — For the Mac workstation (gnetId 15797)
- **Grafana admin credentials** — Stored as SealedSecrets per cluster

## How To: Promote from Staging to Prod

Promotion is branch-based. Staging tracks `main`, prod tracks `prod`. It takes two steps — moving the branch, then syncing ArgoCD.

### Step 1 — Fast-forward the `prod` branch

**Option A: GitHub Actions (recommended)**

Run the [Promote to Prod](../../actions/workflows/promote-to-prod.yml) workflow from the Actions tab. This fast-forwards the `prod` branch to match `main`.

**Option B: Command line**

```bash
git checkout prod
git merge main --ff-only
git push origin prod
```

### Step 2 — Sync the prod Applications

Prod is manual-sync, so nothing deploys until you sync it. Either click **Sync** on each `OutOfSync` app in the ArgoCD UI, or from the CLI:

```bash
# Sync everything labelled env=prod (prod-utilities, prod-media,
# prod-productivity, prod-infra, prod-monitoring)
argocd app sync -l env=prod

# Or one namespace at a time
argocd app sync prod-media
```

Prod also has no `selfHeal`, so manual `kubectl` changes on the prod cluster will *not* be reverted automatically — they persist until the next sync.

## Dependency Updates (Renovate)

[Renovate](https://github.com/renovatebot/renovate) scans this repo weekly (Monday 8am, Europe/Dublin) for:

- Outdated container image tags
- Helm chart version updates

Renovate opens PRs against `main`. Merging a PR auto-deploys to staging. When verified, promote to prod using the workflow above.

Configuration: [`renovate.json`](renovate.json)

## Weekly Update Workflow

1. **Monday 7am** — [GitLab pipeline](https://gitlab.sunnyside.home/root/homelab-os-updates/-/pipelines) auto-updates staging OS
2. **Monday 8am** — Renovate opens PRs for container/Helm updates
3. **During the week** — Review staging
4. **When ready** — Merge Renovate PRs, then:
   - Run [Promote to Prod](../../actions/workflows/promote-to-prod.yml) on GitHub Actions
   - Sync the `prod-*` apps in ArgoCD (`argocd app sync -l env=prod`) — prod is manual-sync
   - Click play on `update-prod` in the [GitLab pipeline](https://gitlab.sunnyside.home/root/homelab-os-updates/-/pipelines)

## How To: Add a New Service

1. Create `base/<namespace>/<service>/` with `deployment.yaml`, `service.yaml`, `ingress.yaml`, and `kustomization.yaml`
2. Add the service directory to `base/<namespace>/kustomization.yaml`
3. Add an Ingress host patch to `envs/staging/<namespace>/kustomization.yaml` — rewrite
   `host`, `tls[0].hosts[0]` and `tls[0].secretName` to the `staging-` prefix. **Don't skip
   this**: without it staging inherits the bare hostname from base and both clusters claim
   the same name.
4. Add the service to the Homepage dashboard in *both* config files —
   `base/utilities/homepage/config/services.yaml` (prod URLs) and
   `envs/staging/utilities/homepage-config/services.yaml` (staging URLs)
5. Check the render before committing:
   `kubectl kustomize base/<namespace>` and `kubectl kustomize envs/staging/<namespace>`
6. Commit and push to `main`. Staging auto-syncs; prod needs a promote + sync
7. Add a DNS A record and `/etc/hosts` entry for both hostnames

## How To: Override a Value for One Environment

Staging patches live in `envs/staging/<namespace>/kustomization.yaml` — either inline (as the
existing hostname patches are) or as a separate file referenced from `patches:`. Prod has no
per-namespace overlay, so a prod-only value has to be the value in `base/`.

```yaml
# envs/staging/<namespace>/my-service-patch.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-service
  namespace: utilities
spec:
  replicas: 2
```

## Secrets

Secrets are managed with [SealedSecrets](https://sealed-secrets.netlify.app/). Each cluster has its own encryption key, so secrets must be sealed per environment.

Sealed secret files live in `envs/<env>/<namespace>/sealed-secrets/` — today only
`monitoring` has any (`envs/staging/monitoring/sealed-secrets/` and
`envs/prod/monitoring/sealed-secrets/`). The same secret must be sealed twice, once per
cluster; a sealed file is never portable between environments.

Other secrets not yet migrated to SealedSecrets:
- `vpn-credentials` (media namespace) — VPN provider credentials for gluetun/qbittorrent
- Database passwords — currently inline in deployment envs

## Infrastructure Details

- **Domain**: `sunnyside.home`
- **Ingress**: Traefik via MetalLB on `192.168.1.180`
- **TLS**: cert-manager with `stepca-acme` ClusterIssuer
- **NFS**: TrueNAS at `192.168.1.202`
- **Storage Classes**: `nfs-client` (NFS provisioner), `local-path` (Rancher local-path)
