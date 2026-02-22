# Runbook: Kubernetes upgrade (via Talos)

This upgrades Kubernetes using Talos’ Kubernetes upgrade workflow (control plane).

## Choose the target version

Kubernetes is pinned in `talos/talenv.yaml`:

- `kubernetesVersion: vX.Y.Z`

If you want “latest patch in the current minor”, check Kubernetes patch releases and select the newest `1.34.x`.

## Update the pin

- Edit `talos/talenv.yaml` and set:
  - `kubernetesVersion: vX.Y.Z`

## Run the upgrade

- `mise exec -- task talos:upgrade-k8s`

## Verify

- `mise exec -- kubectl get nodes -o wide`
- `mise exec -- talosctl health --endpoints <any-node-ip> --nodes <same-node-ip>`

## Troubleshooting

- If the API goes briefly unavailable during component restarts, wait 1–2 minutes and re-run the health check.
- If nodes become `NotReady`, inspect kubelet on the impacted node:
  - `mise exec -- talosctl service kubelet status --nodes <node-ip>`
  - `mise exec -- talosctl logs kubelet --nodes <node-ip> | tail -n 200`
