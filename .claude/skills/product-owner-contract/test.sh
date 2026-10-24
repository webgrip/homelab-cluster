#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

LINT = Path("../product-owner/scripts/ticket_lint.py").resolve()
failures = []

goldens = sorted(Path("teams").glob("*/assets/golden-tickets.md"))
if not goldens:
    failures.append("no teams/*/assets/golden-tickets.md found")

for path in goldens:
    text = path.read_text()
    titles = re.findall(r"^Title:\s+(.+)$", text, re.M)
    blocks = re.findall(r"```markdown\n(.*?)\n```\n", text, re.S)
    if not blocks:
        failures.append(f"{path}: no markdown ticket blocks")
    if len(titles) != len(blocks):
        failures.append(f"{path}: {len(titles)} titles for {len(blocks)} tickets")
    for n, (title, block) in enumerate(zip(titles, blocks), 1):
        proc = subprocess.run([sys.executable, str(LINT), "-", "--json", "--gate", "ready",
                               "--title", title], input=block, capture_output=True, text=True)
        if proc.returncode not in (0, 1):
            sys.exit(f"ticket_lint crashed: {proc.stderr}")
        result = json.loads(proc.stdout)
        flagged = [c["criterion"] for c in result["checks"] if c["status"] in ("FAIL", "WARN")]
        if not result["passes"] or flagged:
            failures.append(f"{path} ticket {n}: {flagged}")

for team in sorted(Path("teams").iterdir()):
    for link in re.findall(r"\]\(([^)#]+)\)", (team / "board.md").read_text()):
        if not link.startswith("http") and not (team / link).exists():
            failures.append(f"{team}/board.md: broken link {link}")

if failures:
    print("product-owner-contract: FAIL")
    for f in failures:
        print(f"  {f}")
    sys.exit(1)
print(f"product-owner-contract: OK — {len(goldens)} team golden-ticket file(s) pass ready")
PY
