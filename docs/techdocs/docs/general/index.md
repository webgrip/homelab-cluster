# General documentation

Architecture and reference docs — what the platform *is*. Procedures live in
[runbooks](../runbooks/index.md), decisions in [ADRs](../adr/index.md), designs in
[RFCs](../rfc/index.md).

- **Cluster foundation** — [Talos cluster reference](talos-cluster.md) (nodes, hardware, wiring),
  [add a workstation node](talos-add-workstation-node.md), [worktrees & concurrent-writer
  discipline](worktrees.md).
- **Apps & inventory** — [applications](applications.md) (canonical endpoint/app inventory),
  [adding applications](adding-applications.md) (pointer to the skills that own the recipe).
- **Observability** — [platform overview](observability.md), [alerting
  principles](alerting-principles.md), [engineering-experience program](engineering-experience-program.md).
- **Security & supply chain** — [security platform](security-platform.md),
  [supply-chain overview](supply-chain-overview.md) / [pipeline](supply-chain-pipeline.md)
  (canonical) / [CVE triage ledger](supply-chain-cve-triage.md).
- **Data** — [database backup tiers](database-backup-tiers.md), [dynamic DB credentials
  explained](dynamic-db-credentials-explained.md).
- **Forge & automation** — [Forgejo](forgejo.md), [Forgejo Actions engine
  quirks](forgejo-actions-engine.md), [Renovate](renovate.md), [ARC runners](arc-runners.md).
- **Planning** — [roadmap](roadmap.md) (living backlog, kept at 100 open items).
- **Games** — [Project Zomboid](zomboid.md) (currently disabled).
