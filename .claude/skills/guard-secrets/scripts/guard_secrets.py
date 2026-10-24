#!/usr/bin/env python3
"""PreToolUse hook (Claude Code twin of opencode/plugins/guard-secrets.js).

Hard-blocks plaintext-secret leaks before an Edit/Write/MultiEdit runs:
  1. never create decrypted secret artifacts (*.decrypted*, *decrypted~*)
  2. a *.sops.yaml / *.sops.yml write must contain SOPS ciphertext (ENC[)
  3. best-effort plaintext-secret scan via gitleaks (warns and continues when absent)

Blocking = exit 2 with a reason on stderr (Claude Code's deny contract, the
analogue of the opencode plugin's throw). Any other error path exits 0
(fail-open — a same-machine convenience guard, not a security boundary; MR
review is that). Content is taken from whichever field the tool provides
(Write: content; Edit: new_string; MultiEdit: each edit's new_string).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

DECRYPTED = ("decrypted",)


def deny(msg: str) -> None:
    print(f"BLOCKED: {msg}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return  # fail-open on malformed input
    ti = event.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("path") or ""
    if not path:
        return
    base = os.path.basename(path)

    # gather content across Write / Edit / MultiEdit shapes
    parts = []
    if ti.get("content"):
        parts.append(ti["content"])
    if ti.get("new_string"):
        parts.append(ti["new_string"])
    for edit in ti.get("edits") or []:
        if edit.get("new_string"):
            parts.append(edit["new_string"])
    content = "\n".join(parts)

    # 1) never create decrypted secret artifacts
    if "decrypted" in base:
        deny(f"refusing to write a decrypted secret artifact ({base}). Secrets live only in *.sops.yaml.")

    # 2) a SOPS file must contain ciphertext, never plaintext
    if base.endswith((".sops.yaml", ".sops.yml")) and content and "ENC[" not in content:
        deny(f"{base} is a SOPS file but the content isn't encrypted. Edit plaintext elsewhere, then 'sops --encrypt'.")

    # 3) best-effort gitleaks scan (warn, never block, when absent)
    if content and not shutil.which("gitleaks"):
        print("guard-secrets: gitleaks not on PATH; plaintext scan skipped. Pin it in .mise.toml.", file=sys.stderr)
    if content and shutil.which("gitleaks"):
        tmp = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
                fh.write(content)
                tmp = fh.name
            scan = subprocess.run(
                ["gitleaks", "detect", "--no-banner", "--no-git", "--redact", "-s", tmp],
                capture_output=True,
            )
            if scan.returncode == 1:
                deny(f"gitleaks flagged a likely plaintext secret in {base}. Use a SOPS secret + Helm value wiring (existingSecret/envFromSecret).")
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


if __name__ == "__main__":
    main()
