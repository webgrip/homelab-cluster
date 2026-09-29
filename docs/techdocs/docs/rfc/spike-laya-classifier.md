# Spike: Laya as a self-hosted classifier

> Date: 2026-09-29 · Ticket: [VIK-1446](https://vikunja.webgrip.dev/tasks/1446) · Parent RFC:
> [ticket sizing with Jev](rfc-jev-ticket-sizing.md) · Harness: `scripts/classifier-eval/`

> **Verdict.** Zero-shot Laya is **rejected for sizing** and **rejected for yes/no readiness**:
> agreement with our labels is at chance on every sizing axis, and readiness is a coin flip.
> It **works for picking a theme**: 72–79 % correct against a 44 % baseline, with the right
> theme in its top three about 90 % of the time. So the in-cluster path is open for Choice
> questions over named options (VIK-1448), and closed for Score and yes/no until fine-tuned
> on our own labels. The private-data tickets that need yes/no judgements (VIK-1456, VIK-1457)
> stay gated on VIK-1411.

## What ran

- `laya` 0.3.22 (`laya-serve`, Apache-2.0), checkpoints `english` and `typed-decisions` at
  revision `55cf4c4e`, CPU only, 16 threads, on the owner's workstation (Ryzen 9 7950X), bound to
  `127.0.0.1`. Ticket text never left the machine. No cluster change was made.
- Requests use the Jev API shape (`POST /v1/systemone`), so the same harness runs against Jev
  once VIK-1414 wires the vendor key. **The Jev comparison is still open.**
- Questions: the RFC §5.1 draft rubric, zero-shot (level descriptions only, no examples); the
  theme as a Choice over the 8 themes with at least 3 closed tickets; readiness as a yes/no.
- State: title, board and description with the header badge and every sizing token removed,
  so the answer cannot be read back from the text.

## Harness check (must pass before anything else counts)

| Check | english | typed-decisions |
| --- | --- | --- |
| 7 obvious cases (yes/no and 3-way choice) | 7/7 | 7/7 |
| SST-5 sentiment, 300 test items (card claims 0.372) | 0.350 | 0.427 |

The card's own number reproduces within sampling noise, so the harness works. The metric code
has a self-test that must pass (perfect predictions) and must fail (inverted, constant).

## Board results

Data: 105 closed tickets from Homelab Roadmap, Dark Factory and Ploeg. **CI/CD (project 9) is
missing**: the export's list call was denied by the session's permission check. Of those, 78
carry an effort label and only 27 carry time and uncertainty. Labels are human refinement
labels, not actuals (RFC §6.1 question 1 is VIK-1412).

| Axis (n) | Model | Accuracy | Majority baseline | Linear weighted kappa | Predictions |
| --- | --- | --- | --- | --- | --- |
| effort (78) | english | 0.31 | 0.60 | −0.01 | M 73, L 5 |
| effort (78) | typed-decisions | 0.14 | 0.60 | 0.02 | L 58, M 20 |
| time (27) | english | 0.22 | 0.59 | 0.05 | weeks 18 |
| time (27) | typed-decisions | 0.22 | 0.59 | 0.02 | weeks 17 |
| uncertainty (27) | english | 0.44 | 0.48 | 0.00 | med 27 |
| uncertainty (27) | typed-decisions | 0.48 | 0.48 | 0.12 | med 26 |

Confidence carries no signal: exact agreement does not rise from the lowest to the highest
confidence tercile on any axis (gate G1d fails).

| Question | Model | Result | Baseline |
| --- | --- | --- | --- |
| Theme, 8 options (n = 68) | english | 0.72 top-1, 0.91 top-3 | 0.44 |
| Theme, 8 options (n = 68) | typed-decisions | 0.79 top-1, 0.90 top-3 | 0.44 |
| Ready vs needs-refinement (n = 99) | english | AUC 0.52 | 0.50 |
| Ready vs needs-refinement (n = 99) | typed-decisions | AUC 0.57 | 0.50 |

The readiness set is confounded: every `needs-refinement` ticket in it comes from one July batch
(IDs 2–53) in one format. A model could separate the groups by age and style without judging
readiness, and Laya still did not.

## Cost to run

| | english | typed-decisions |
| --- | --- | --- |
| Latency, 3 questions per request, sequential, p50 / p95 | 1.36 s / 1.44 s | 1.90 s / 3.16 s |
| Resident memory, both checkpoints loaded | ~3.8 GB | (shared) |

A worker-pool Deployment would need about 4 GiB of memory and several cores to match this.
Nothing was deployed, because only Choice passed.

## Finding for the RFC gates

Gate **G1a** (macro-MAE below "always M", interval excluding zero) would have **passed** the
English checkpoint on effort, which answered M for 73 of 78 tickets. Macro-MAE rewards a
constant middle guess over a constant majority guess. G1a must also require linear weighted
kappa above zero with its interval excluding zero, and the baseline set must include "always
middle" as well as "always majority".

## What would change the verdict

- Fine-tuning `typed-decisions` on our labels. The card reports 0.72 on Score after tuning on
  2,000 decisions. We have 78 effort labels. Revisit when VIK-1412's export passes ~500
  labelled tickets.
- Rubric examples per level (VIK-1413). This run was zero-shot with descriptions only.
- The same harness against Jev (after VIK-1414): if Jev is also at chance here, the problem is
  the task or the labels, not the model.

## Reproduce

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/bin/python "laya[serve]==0.3.22" datasets
LAYA_HOST=127.0.0.1 LAYA_DEVICE=cpu LAYA_PRELOAD=1 LAYA_MODELS=english,typed-decisions LAYA_THREADS=16 .venv/bin/laya-serve &
cd scripts/classifier-eval && ../../.venv/bin/python run_eval.py --data <export dir> --out results
```

The ticket export (`closed.jsonl`, `open_ready_vs_refine.jsonl`) is not committed; it holds
ticket text and is rebuilt from the board.
