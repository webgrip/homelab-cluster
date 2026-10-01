# Calibration

The answer judge is trusted only while it agrees with your own grades on at least 80% of judgements. Answer and gate runs write up to ten answers to `calibration/pending/`, one JSON file each.

To grade one in the Forgejo web UI:

1. Open `ryangr0/brain-eval`, folder `calibration/pending/`, and click a file, for example `c07-b0.json`.
2. Read `question`, `key_facts`, `answer` and `tool_outputs`.
3. Click the pencil (**Edit file**) and fill `grade`:
   - `key_facts_present`: one `true` or `false` per key fact, in order: does the answer state it?
   - `faithful`: `true` when every claim in the answer is supported by the tool outputs.
   - `abstained`: `true` when the answer says it found nothing or declines to answer.
4. In the file path box above the editor, put the cursor at the start of the file name and press Backspace once, so the path reads `calibration/c07-b0.json` instead of `calibration/pending/c07-b0.json`. That moves the file.
5. **Commit changes** directly to `main`.

Every answer run re-judges the graded files and publishes the agreement. Below 80% with ten grades, switch the judge to the next cheapest model of another family: `fireworks-glm-5p3-flash`, then `fireworks-qwen3-plus` (never an Anthropic model or DeepSeek's own API; the answer model is MiniMax and the question drafter is gpt-oss).

The eval jobs rewrite this file from `kubernetes/apps/ai/omnigraph/brain-eval/app/calibration-readme.md` in `webgrip/homelab-cluster`; change it there.
