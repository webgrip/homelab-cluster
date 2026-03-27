# Runbook: Talos add node (maintenance mode)

This runbook is a short index entry for adding a new node that boots into Talos maintenance mode.

- Full tutorial: [docs/techdocs/docs/talos-add-workstation-node.md](../talos-add-workstation-node.md)

If you are seeing `x509: certificate signed by unknown authority`, the key rule is that maintenance mode requires `--insecure` on the **subcommand** and usually `--endpoints <ip>` to talk directly to the node.
