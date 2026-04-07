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
│   ├── utilities/                 # homepage, it-tools, open-webui, marreta, etc.
│   ├── media/                     # plex, sonarr, radarr, bazarr, etc.
│   ├── productivity/              # freshrss, mealie, nextcloud, paperless, searxng
│   ├── infra/                     # guacamole, uptime-kuma, netalertx
│   └── monitoring/                # kube-prometheus-stack (Helm values)
├── envs/
│   ├── staging/                   # Overlay: staging-specific patches
│   │   ├── kustomization.yaml
│   │   └── sealed-secrets/
│   └── prod/                      # Overlay: prod-specific patches
│       ├── kustomization.yaml
│       └── sealed-secrets/
├── argocd/
│   ├── staging/
│   │   └── apps.yaml              # ArgoCD ApplicationSet (tracks main branch)
│   └── prod/
│       └── apps.yaml              # ArgoCD ApplicationSet (tracks prod branch)
└── .github/workflows/
    └── promote-to-prod.yml        # Manual workflow to fast-forward prod to main
```

## Environments

| Environment | Branch | Sync Policy | Cluster |
|-------------|--------|-------------|---------|
| staging | `main` | Auto-sync | k3s-staging (192.168.1.251) |
| prod | `prod` | Auto-sync | k3s-prod (192.168.1.173) |

Both environments auto-sync from their respective branches. Promotion is controlled by which branch ArgoCD tracks, not by disabling sync.

## Namespaces

| Namespace | Services |
|-----------|----------|
| `utilities` | homepage, it-tools, open-webui, openspeedtest, stirling-pdf, marreta |
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

Promotion is branch-based. Staging tracks `main`, prod tracks `prod`.

**Option 1: GitHub Actions (recommended)**

Run the [Promote to Prod](../../actions/workflows/promote-to-prod.yml) workflow from the Actions tab. This fast-forwards the `prod` branch to match `main`.

**Option 2: Command line**

```bash
git checkout prod
git merge main --ff-only
git push origin prod
```

ArgoCD on prod auto-syncs from the `prod` branch.

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
   - Click play on `update-prod` in the [GitLab pipeline](https://gitlab.sunnyside.home/root/homelab-os-updates/-/pipelines)

## How To: Add a New Service

1. Create `base/<namespace>/<service>/` with `deployment.yaml`, `service.yaml`, `ingress.yaml`, and `kustomization.yaml`
2. Add the service directory to `base/<namespace>/kustomization.yaml`
3. No changes needed in `envs/` — Kustomize overlays inherit from base automatically
4. Commit and push. ArgoCD picks it up on next sync
5. Add the service to the Homepage dashboard config in `base/utilities/homepage/configmap.yaml`
6. Add a DNS A record and `/etc/hosts` entry for the new service

## How To: Override a Value for One Environment

Create a patch file in `envs/<env>/` and reference it in the environment's `kustomization.yaml`:

```yaml
# envs/staging/my-service-patch.yaml
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

Sealed secret files live in `envs/<env>/<namespace>/sealed-secrets/`.

Other secrets not yet migrated to SealedSecrets:
- `vpn-credentials` (media namespace) — VPN provider credentials for gluetun/qbittorrent
- Database passwords — currently inline in deployment envs

## Infrastructure Details

- **Domain**: `sunnyside.home`
- **Ingress**: Traefik via MetalLB on `192.168.1.180`
- **TLS**: cert-manager with `stepca-acme` ClusterIssuer
- **NFS**: TrueNAS at `192.168.1.202`
- **Storage Classes**: `nfs-client` (NFS provisioner), `local-path` (Rancher local-path)
