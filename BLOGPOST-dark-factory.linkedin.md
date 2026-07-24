# LinkedIn native post — dark factory (v3, thesis-led)

~2,000 chars (limit 3,000; optimal 1,500–2,500). Hook fits the ~210-char fold. No link in the
body; add the Substack link as a comment (or edit) after initial distribution. No Unicode
bold. Post the same week as the HN submission, not the same morning.

---

My Kubernetes cluster scheduled an AI agent this morning, the same way it schedules a CI job.

The agent worked a Kanban ticket for 20 minutes, opened a pull request, and a second agent
rejected it for skipping the TypeScript gate.

Total inference cost: $0.046. Every cent of it in a ledger I can query.

Three things about this matter more than the PR itself:

1. Scheduling AI agents turned out to be a solved problem. No agent platform, no
orchestration SaaS. KEDA saw a queued job and scaled a pod from zero, exactly as it does for
CI. The agent is just a workload with a budget.

2. The entire platform is open source and self-hosted: the board (Vikunja), the forge
(Forgejo), the autoscaler (KEDA), the inference proxy (LiteLLM), the vault (OpenBao), the
dashboards (Grafana + VictoriaMetrics). The only rented thing is the model API behind the
proxy, and that's one line of config.

3. The cost is structural, not luck. Idle factory: $0 (scale-from-zero, nothing warm).
Working factory: cents per ticket on the cheap-model tier. Misbehaving factory: capped three
ways (per-run budget keys, a 2-run concurrency ceiling, provider day-caps). Failed runs
spend exactly $0.00, because a run that can't mint its key can't spend.

And the part that makes unattended operation thinkable: the runs mint their own keys and
delete them on the way out, yet observability still sees everything. Revoked keys get
reconstructed from the immutable spend ledger. I'm not trusting the factory, I'm auditing it.

The builder is never the judge: author and reviewer are separate bot accounts, and the forge
won't let an account approve its own PR. Merging stays human.

Peers report $150 overnight agent sessions on hosted stacks. Different workloads, but three
orders of magnitude is not a workload difference. It's a structure difference.

What would you need to see before letting an unattended agent open PRs against your repos?

(Full write-up, including everything that broke on the way, in the comments.)

#platformengineering #kubernetes #aiagents #gitops #opensource
