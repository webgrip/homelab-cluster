# add-app reference — verified manifest skeletons

Contents: [§1 ks.yaml](#1-ksyaml) · [§2 kustomizations](#2-kustomizations) ·
[§3 chart (OCIRepository + HelmRelease)](#3-chart) · [§4 HTTPRoute](#4-httproute) ·
[§5 ExternalSecret](#5-externalsecret) · [§6 validate](#6-validate)

Placeholders: `<ns>` namespace, `<app>` app name, `<port>` service port. Shapes mirror the live
tree as of 2026-07-03; schema headers give editor validation.

## 1. ks.yaml

`kubernetes/apps/<ns>/<app>/ks.yaml` — never declare `decryption:` or remediation here (root injects).

```yaml
---
# yaml-language-server: $schema=https://k8s-schemas.bjw-s.dev/kustomize.toolkit.fluxcd.io/kustomization_v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: <app>
spec:
  dependsOn:                      # pick from the menu in SKILL.md; drop if none
    - name: external-secrets-stores
      namespace: security
  interval: 1h
  path: ./kubernetes/apps/<ns>/<app>/app
  postBuild:
    substituteFrom:
      - kind: Secret
        name: cluster-secrets     # provides ${SECRET_DOMAIN} etc.
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: <ns>
  wait: false
```

## 2. Kustomizations

`kubernetes/apps/<ns>/kustomization.yaml` (namespace level):

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./namespace.yaml
  - ./<app>/ks.yaml
```

`kubernetes/apps/<ns>/<app>/app/kustomization.yaml` (resources + components):

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./ocirepository.yaml
  - ./helmrelease.yaml
  - ./httproute.yaml
  - ./<app>-secret.externalsecret.yaml
components:                       # catalog in SKILL.md; paths are relative
  - ../../../../components/placement/worker-pool
```

## 3. Chart

`ocirepository.yaml` — always via the Harbor proxy, tag **and** digest pinned
(`./scripts/update-oci-digests.sh` maintains digests; CI's `verify-oci-digests.sh` checks drift):

```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: <app>
spec:
  interval: 1h
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  url: oci://harbor.webgrip.dev/ghcr/bjw-s-labs/helm/app-template
  ref:
    tag: <chart-version>
    digest: sha256:<digest>
```

`helmrelease.yaml` — bjw-s app-template shape (third-party charts: same header, chart-specific values):

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: <app>
spec:
  chartRef:
    kind: OCIRepository
    name: <app>
  interval: 30m
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
      remediateLastFailure: true
  values:
    controllers:
      <app>:
        annotations:
          reloader.stakater.com/auto: "true"   # restart on ESO secret rotation
        pod:
          nodeSelector:
            node.webgrip.io/pool: worker       # ADR-0028; or use the worker-pool component
          securityContext:
            runAsNonRoot: true
            runAsUser: 1000
            runAsGroup: 1000
            fsGroup: 1000
            fsGroupChangePolicy: OnRootMismatch
        containers:
          app:
            image:
              repository: <image>
              tag: <tag>
            envFrom:
              - secretRef:
                  name: <app>-secret
            resources:
              requests: {cpu: 10m, memory: 128Mi}
              limits: {memory: 512Mi}
            probes:
              liveness: {enabled: true}
              readiness: {enabled: true}
    service:
      app:
        controller: <app>
        ports:
          http:
            port: <port>
    persistence:                                # only if stateful
      data:
        accessMode: ReadWriteOnce
        size: 5Gi
        storageClass: longhorn                  # default SC (ADR-0029); table → longhorn skill
        globalMounts:
          - path: /data
```

Single-attach RWO + one replica? Add `strategy: Recreate` on the controller (rolling update
deadlocks on Multi-Attach — workload-placement skill).

## 4. HTTPRoute

`httproute.yaml` — LAN default. Public exposure = `name: envoy-external` (deliberate choice;
everything else identical):

```yaml
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: <app>
  namespace: <ns>
  annotations:
    external-dns.alpha.kubernetes.io/exclude: "true"
    monitoring.webgrip.io/synthetic-check: k6-ingress-canary
spec:
  hostnames:
    - <app>.${SECRET_DOMAIN}
  parentRefs:
    - name: envoy-internal
      namespace: network
      sectionName: https
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: <app>
          namespace: <ns>
          port: <port>
```

Editing note: the Edit/Write validate hook false-positives on `${SECRET_DOMAIN}` in hostnames
(kubeconform pre-substitution) — make hostname-bearing edits via Bash/sed;
`run-flux-local-test.sh` is the real gate (flux-validate skill).

## 5. ExternalSecret

`<app>-secret.externalsecret.yaml` — minimal shape; stores, generators, and push/migration
recipes live in the `external-secrets` skill:

```yaml
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <app>-secret
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: openbao
  target:
    name: <app>-secret
  dataFrom:
    - extract:
        key: <app>            # OpenBao KV v2 path (mount `secret` implied by the store)
```

## 6. Validate

```bash
./scripts/update-oci-digests.sh          # after adding/bumping an OCIRepository
./scripts/run-flux-local-test.sh         # full render gate (also runs in CI)
./scripts/check-docs-links.sh "$(pwd)"   # if you documented the app
```
