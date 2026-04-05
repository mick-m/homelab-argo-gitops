# homelab-argo-gitops

GitOps repository for the Sunnyside homelab Kubernetes cluster, managed by ArgoCD.

## Architecture

| Layer | Repo | Purpose |
|-------|------|---------|
| Day 0 | `homelab-ansible-bootstrap` | K3s, MetalLB, cert-manager, Traefik, ArgoCD |
| Day 1+ | `homelab-argo-gitops` (this repo) | Application manifests, managed by ArgoCD |

## Repository Structure

```
homelab-argo-gitops/
├── base/                          # Canonical Kustomize bases per namespace/service
│   ├── utilities/                 # homepage, it-tools, open-webui, etc.
│   ├── media/                     # plex, sonarr, radarr, bazarr, etc.
│   ├── productivity/              # freshrss, mealie, nextcloud, paperless, searxng
│   ├── infra/                     # guacamole, uptime-kuma, netalertx
│   └── monitoring/                # kube-prometheus-stack (Helm values)
├── envs/
│   ├── staging/                   # Overlay: :latest tags, auto-sync
│   │   ├── kustomization.yaml
│   │   └── patches/
│   └── prod/                      # Overlay: pinned images, manual sync
│       ├── kustomization.yaml
│       └── patches/
└── argocd/
    ├── staging/
    │   └── apps.yaml              # ArgoCD ApplicationSet for staging
    └── prod/
        └── apps.yaml              # ArgoCD ApplicationSet for prod
```

## How It Works

### Base Manifests (`base/`)

Each service has its own directory containing:
- `deployment.yaml` - Workload definition
- `service.yaml` - ClusterIP service
- `ingress.yaml` - Traefik ingress with TLS via cert-manager
- `pvc.yaml` - PersistentVolumeClaims (where applicable)
- `configmap.yaml` - ConfigMaps (where applicable)
- `kustomization.yaml` - Kustomize resource list

Base manifests use `sunnyside.home` domain and represent the canonical service definitions.

### Environment Overlays (`envs/`)

- **staging**: References base, uses `:latest` image tags. ArgoCD auto-syncs changes.
- **prod**: References base, pins specific image versions. ArgoCD requires manual sync (deliberate promotion).

### ArgoCD Applications (`argocd/`)

Uses the **App-of-Apps** pattern with `ApplicationSet`:
- One ArgoCD Application per namespace per environment
- Staging: `syncPolicy.automated` enabled (auto-deploy on git push)
- Prod: No automated sync (Mick promotes deliberately via ArgoCD UI or CLI)

## Environments

| Environment | Image Policy | Sync Policy | Cluster |
|-------------|-------------|-------------|---------|
| staging | `:latest` | Auto-sync | Future staging cluster |
| prod | Pinned versions | Manual sync | k3s-prod (192.168.1.173) |

## Namespaces

| Namespace | Services |
|-----------|----------|
| `utilities` | homepage, it-tools, open-webui, openspeedtest, stirling-pdf, thirteenft |
| `media` | plex, sonarr, radarr, bazarr, prowlarr, qbittorrent, seerr, tautulli, tunarr, metube, flaresolverr |
| `productivity` | freshrss, mealie, searxng, nextcloud (+db), paperless (+db) |
| `infra` | guacamole (+db), uptime-kuma, netalertx |
| `monitoring` | kube-prometheus-stack (Helm) |

## How To: Add a New Service

1. Create `base/<namespace>/<service>/` with `deployment.yaml`, `service.yaml`, `ingress.yaml`, and `kustomization.yaml`
2. Add the service directory to `base/<namespace>/kustomization.yaml`
3. No changes needed in `envs/` -- Kustomize overlays inherit from base automatically
4. Commit and push. ArgoCD picks it up on next sync (auto for staging, manual for prod)

## How To: Promote from Staging to Prod

1. Test the service in staging (auto-deployed with `:latest`)
2. Check the running image digest: `kubectl get deploy <name> -n <ns> -o jsonpath='{.spec.template.spec.containers[0].image}'`
3. If needed, add a pinned image patch in `envs/prod/patches/<service>.yaml`
4. Commit and push
5. In ArgoCD UI, click **Sync** on the prod application (or `argocd app sync prod-<namespace>`)

## How To: Override a Value for One Environment

Create a patch file in `envs/<env>/patches/` and reference it in the environment's `kustomization.yaml`:

```yaml
# envs/prod/patches/homepage-replicas.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: homepage
  namespace: utilities
spec:
  replicas: 2
```

## Secrets

Secrets are NOT stored in this repo. They must be created manually or via Sealed Secrets/External Secrets:

- `vpn-credentials` (media namespace) - VPN provider credentials for gluetun/qbittorrent
- Database passwords are currently inline in deployment envs (migrate to Secrets as a future improvement)

## Infrastructure Details

- **Domain**: `sunnyside.home`
- **Ingress**: Traefik via MetalLB on `192.168.1.180`
- **TLS**: cert-manager with `stepca-acme` ClusterIssuer
- **NFS**: TrueNAS at `192.168.1.202`
- **Storage Classes**: `nfs-client` (NFS provisioner), `local-path` (Rancher local-path)
