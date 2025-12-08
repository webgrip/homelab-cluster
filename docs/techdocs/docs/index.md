# Homelab Platform Docs

Welcome to the TechDocs space for the Flux-managed homelab cluster. Every page in this section is sourced from the live manifests and `talosctl`/`kubectl` output so it reflects what is actually running rather than historic notes.

## Scope

- Talos cluster layout, versions, health checks, and etcd membership
- GitOps + networking components as defined under `kubernetes/apps/*`
- Operational references for SOPS, Flux, and bootstrap scripts
- Live runtime inventory (pods + services) captured directly from the cluster

Regenerate this documentation any time cluster state changes: capture fresh `talosctl` output, update the tables, and commit alongside the manifests so Backstage stays trustworthy.
