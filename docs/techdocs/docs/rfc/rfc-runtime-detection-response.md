# RFC: Runtime detection & response — reinstate deliberately or retire honestly

> Status: **Accepted** · Date: 2026-07-02, decided 2026-10-18 · Part of the [decision-landscape gap register](../adr/landscape.md)
> · Decision: [ADR-0072 — Tetragon alone watches agent pods](../adr/adr-0072-tetragon-watches-agent-pods.md)
>
> **Outcome (2026-10-18).** The investigation found no surviving evidence that names a cause: the
> suspension came in an unrelated commit during the 06-18 Longhorn incident, and metrics, logs and
> the Talos OOM ledger from June are gone. It did find six properties of the June configuration
> that could make the agents worsen memory pressure (both agents on the 12 GiB control-plane nodes,
> unreserved 1 GiB bursts, `system-node-critical` priority with its -997 OOM score and preemption,
> tolerate-everything, unscoped cluster-wide telemetry, requests far below use under the Talos OOM
> controller). ADR-0072 removes all six: Tetragon only, on the worker pool, scoped to the agent
> namespaces, memory request equal to limit, no PriorityClass, observe stage first. Falco is
> deleted. Detection routing (proposal step 4) is decided there too; the response tier (in-kernel
> `Sigkill`) stays open.

> **TL;DR.** The cluster ran **two** overlapping eBPF runtime-security agents — Falco *and*
> Tetragon — until both were disabled on 2026-06-19 ("repeated cluster outages were attributed to
> these runtime-security agents") by commenting them out of the security kustomization. Nothing
> since has decided whether they return, which one, under what stability gates, or what happens
> when one fires. The [security-hardening RFC](rfc-security-hardening.md) names detect→respond a
> future ADR; this RFC is that work: run the root-cause investigation the suspension skipped, pick
> **one** detector, gate its return, and give detections somewhere to go.

## Why

Verified state (2026-07-02): `kubernetes/apps/security/kustomization.yaml` carries
`# - ./falco/ks.yaml` / `# - ./tetragon/ks.yaml` with the outage note; with `prune: true` both
were fully uninstalled. The manifests remain — Falco 8.0.5 (modern_ebpf, custom homelab exception
rules, ServiceMonitor; **no** falcosidekick/talon) and Tetragon 1.7.0 (process/cred tracking,
secret-redaction filters, stdout export).

> **Re-verified 2026-08-04, unchanged.** `kubernetes/apps/security/kustomization.yaml` still
> carries both lines commented out; `kubectl -n security get ds,deploy` returns neither agent.
> Note one trap for anyone checking this quickly: the `tracingpolicies.cilium.io` CRD **still
> exists** (created 2026-05-27) because Helm uninstall does not remove CRDs, so
> `kubectl get tracingpolicies -A` returns `0` rather than an error — which reads like "Tetragon
> is installed and configured with nothing" instead of "Tetragon is gone". Check the DaemonSet,
> not the CRD.
>
> The [attack-path RFC](rfc-attack-path-analysis.md) raises this RFC's priority: with no detector
> installed, any privilege-escalation chain that exists in the waiver set executes unobserved,
> which is why that RFC proposes finding such chains *statically* in the meantime.

Three problems, in order:

1. **The suspension was a mitigation, not a diagnosis.** "Attributed to" is doing heavy lifting:
   which agent, which mechanism (CPU? memory? eBPF probe overhead on the 12 GiB soyos? the
   2026-06-18 Longhorn IM-cpu detonation happened the day before)? Without the root cause, any
   reinstatement is a coin flip, and *not* reinstating forfeits runtime detection on a cluster
   whose hardening posture is otherwise enforce-grade.
2. **Two agents was one too many all along.** Falco (rule-based syscall detection, mature
   rulesets) and Tetragon (Cilium-native observation *and* in-kernel enforcement) overlap heavily
   on detection. Running both doubled the eBPF/agent tax on the cluster's scarcest resource —
   soyo RAM — for largely duplicated signal. No record says why both existed.
3. **Detection had no consumer.** Falco shipped alerts to logs; no falcosidekick, no route into
   the alerting planes — which themselves deliver nowhere
   ([alert-delivery RFC](rfc-alert-delivery.md)). A detector nobody hears is cost without control.

## Proposal

Sequenced *after* alert delivery exists — detection without delivery is theater.

1. **Investigate before reinstating** (prerequisite, not an ADR): from the incident window,
   establish what actually destabilized — per-agent resource profiles on the soyos, correlation
   with the 06-18/06-19 storage incidents. If the agents were bystanders wrongly blamed, that
   matters as much as if they weren't.
2. **Pick one detector** (new ADR). The weighing as it stands:
   - **Tetragon** — already Cilium-house-aligned, lighter agent, enforcement-capable
     (`TracingPolicy` can kill a process in-kernel — a real respond primitive), but younger
     rulesets and DIY alert routing.
   - **Falco** — the mature ruleset and ecosystem (sidekick → any channel; talon for response),
     but a second eBPF stack beside Cilium's and historically the heavier suspect here.
   - **Neither** — legitimate: this is defense-in-depth on an already enforce-heavy,
     single-operator cluster; if the RAM/stability price outbids the marginal detection value,
     record *that* and delete the manifests instead of carrying dead YAML.
   Leaning: Tetragon, pending the investigation's verdict on who caused the outages.
3. **Gate the return like Pyroscope's** ([ADR-0037](../adr/adr-0037-reenable-pyroscope-worker-pool.md)
   is the template): explicit resource requests/limits sized for the soyos (or a worker-only
   DaemonSet if node coverage can be traded), Guaranteed QoS, a canary window with defined
   abort-criteria (etcd health, node memory pressure), one isolated revertible commit.
4. **Wire detect → deliver → respond** (new ADR): events route into the alerting stack
   (severity-mapped per [alerting-principles](../general/alerting-principles.md)); start
   observe-only, and only after a quiet baseline decide the response tier (alert-only vs
   auto-kill via Tetragon enforcement/Falco talon — the enforce-not-observe posture eventually
   applies here too, per the security-hardening thesis).

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| [0072](../adr/adr-0072-tetragon-watches-agent-pods.md) | accepted | One runtime detector: Tetragon, scoped to agent pods on the worker pool; Falco removed |
| [0072](../adr/adr-0072-tetragon-watches-agent-pods.md) | accepted | Reinstatement gates and resource envelope: request equal to limit, no PriorityClass, staged observe then alert |
| [0072](../adr/adr-0072-tetragon-watches-agent-pods.md) | accepted | Detection routing: VictoriaLogs, `vmalert-runtime`, Alertmanager, ntfy |
| candidate | — | Response tier (alert only vs in-kernel `Sigkill`), after the alert stage has run |

## Out of scope

- Admission-time policy — Kyverno ([RFC](rfc-kyverno-audit-enforce-hardening.md)).
- Vulnerability scanning at rest — trivy-operator (live and unaffected).
- Network-layer policy — [ADR-0006](../adr/adr-0006-default-deny-network-policies.md).

## References

- [security-platform doc](../general/security-platform.md) ·
  [RFC: security hardening](rfc-security-hardening.md) (posture map row "detect→respond")
- Incidents: [2026-06-18 Longhorn IM-cpu detonation](../incidents/2026-06-18-longhorn-im-cpu-rolling-detonation.md)
  — the neighbouring event the investigation must untangle
