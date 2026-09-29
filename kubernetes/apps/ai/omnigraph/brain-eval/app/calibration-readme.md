# Calibration

The answer judge is trusted only while it agrees with your own grades on at least 80% of judgements. Answer runs write up to ten answers to `calibration/pending/`, one JSON file each.

To grade one:

1. Open the file and read `question`, `key_facts`, `answer` and `tool_outputs`.
2. Fill `grade`:
   - `key_facts_present`: one `true` or `false` per key fact, in order: does the answer state it?
   - `faithful`: `true` when every claim in the answer is supported by the tool outputs.
   - `abstained`: `true` when the answer says it found nothing or declines to answer.
3. Move the file from `calibration/pending/` to `calibration/`.

Every answer run re-judges the graded files and publishes the agreement. Below 80% with ten grades, switch the judge to `claude-sonnet-5`.
