*[ADR]: Architecture Decision Record — one defensible decision per numbered file under adr/
*[RFC]: Request For Comments — a design exploration under rfc/; spawns ADRs for its decisions
*[ESO]: External Secrets Operator — syncs secrets between OpenBao and Kubernetes
*[SOPS]: Secrets OPerationS — the legacy encrypted-in-git secret path; only a minimal floor remains
*[OIDC]: OpenID Connect — the SSO protocol Authentik speaks to apps
*[CNPG]: CloudNativePG — the PostgreSQL operator running every database here
*[PSA]: Pod Security Admission — Kubernetes' built-in pod security standards enforcement
*[PITR]: Point-In-Time Recovery — restoring a database to an exact moment from WAL
*[WAL]: Write-Ahead Log — PostgreSQL's append-only change stream, shipped to S3 for backups
*[RWO]: ReadWriteOnce — a volume mountable read-write by a single node at a time
*[RWX]: ReadWriteMany — a volume mountable read-write by many nodes simultaneously
*[DinD]: Docker-in-Docker — the daemon CI job containers run on
*[SSRF]: Server-Side Request Forgery — why scrapers block private-IP destinations by default
*[MCP]: Model Context Protocol — how agents reach tools like the docs search server
*[DR]: Disaster Recovery — surviving the loss of the cluster, not just a pod
*[SLO]: Service Level Objective — the reliability target an alert defends
*[KEDA]: Kubernetes Event-Driven Autoscaling — scales the CI runners from queue depth
*[VIP]: Virtual IP — the floating address in front of the control plane (10.0.0.25)
*[HR]: HelmRelease — Flux's CRD describing a Helm chart installation
*[ks]: Kustomization — Flux's unit of reconciliation; ks.yaml wires an app into the tree
*[LB]: LoadBalancer — a Service type handing out a LAN IP via the cluster's address pool
*[TLS]: Transport Layer Security — certificate-based transport encryption
