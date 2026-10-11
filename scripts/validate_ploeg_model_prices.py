#!/usr/bin/env python3

"""Fail when a model a Ploeg Team, Ask or operator policy uses has no pinned price.

LiteLLM prices a model from its own built-in list unless the config pins
`model_info` with per-token costs. That list lags new models, and a model it
does not know is recorded at US$0, which breaks Ploeg's budgets and every
cost-per-Work-Item comparison (Unfold epic VIK-2026). Every model the Ploeg
HelmRelease references therefore needs `input_cost_per_token` and
`output_cost_per_token` in the LiteLLM config.

Text-only on purpose (no YAML dependency), like the other validators here.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLOEG = Path("kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml")
LITELLM = Path("kubernetes/apps/ai/litellm/app/litellm-config.configmap.yaml")

RE_PROXY_MODEL = re.compile(r"^\s*model:\s*litellm_proxy/(?P<name>[A-Za-z0-9._-]+)")
RE_MODELS_KEY = re.compile(r"^(?P<indent>\s*)models:\s*$")
RE_LIST_ITEM = re.compile(r"^(?P<indent>\s*)-\s*(?P<name>[A-Za-z0-9._/-]+)\s*(#.*)?$")
RE_MODEL_NAME = re.compile(r"^\s*-\s*model_name:\s*(?P<name>[A-Za-z0-9._-]+)\s*$")


def ploeg_models(text: str) -> set[str]:
    """Models named by `model: litellm_proxy/<name>` or listed under a `models:` key."""
    found: set[str] = set()
    lines = text.splitlines()
    for index, line in enumerate(lines):
        proxy = RE_PROXY_MODEL.match(line)
        if proxy:
            found.add(proxy.group("name"))
            continue
        key = RE_MODELS_KEY.match(line)
        if not key:
            continue
        for item in lines[index + 1:]:
            listed = RE_LIST_ITEM.match(item)
            if not listed or len(listed.group("indent")) < len(key.group("indent")):
                break
            found.add(listed.group("name").removeprefix("litellm_proxy/"))
    return found


def priced_models(text: str) -> dict[str, bool]:
    """Each `model_name` in the LiteLLM config, and whether its block pins input and output prices."""
    blocks: dict[str, bool] = {}
    current = None
    body: list[str] = []
    for line in text.splitlines() + ["  - model_name: __end__"]:
        named = RE_MODEL_NAME.match(line)
        if named:
            if current is not None:
                joined = "\n".join(body)
                blocks[current] = "input_cost_per_token:" in joined and "output_cost_per_token:" in joined
            current, body = named.group("name"), []
        elif current is not None:
            body.append(line)
    blocks.pop("__end__", None)
    return blocks


def problems(ploeg_text: str, litellm_text: str) -> list[str]:
    priced = priced_models(litellm_text)
    out = []
    for model in sorted(ploeg_models(ploeg_text)):
        if model not in priced:
            out.append(f"{model}: used by Ploeg but not defined in {LITELLM}")
        elif not priced[model]:
            out.append(f"{model}: used by Ploeg but has no input_cost_per_token/output_cost_per_token in {LITELLM}")
    return out


def self_test() -> None:
    ploeg = """
    executor:
      teams:
        - name: bronze
          model: litellm_proxy/priced-a
          roles:
            - name: reviewer
              model: litellm_proxy/priced-b
      workerAuth:
        additionalLLMPolicies:
          - team: bronze
            role: ask
            models:
              - unpriced-c
            ttl: 2m
    """
    litellm = """
      - model_name: priced-a
        model_info:
          input_cost_per_token: 0.1
          output_cost_per_token: 0.2
      - model_name: priced-b
        model_info:
          input_cost_per_token: 0.1
          output_cost_per_token: 0.2
      - model_name: unpriced-c
        litellm_params:
          model: x
    """
    assert ploeg_models(ploeg) == {"priced-a", "priced-b", "unpriced-c"}, ploeg_models(ploeg)
    assert problems(ploeg, litellm) == [f"unpriced-c: used by Ploeg but has no input_cost_per_token/output_cost_per_token in {LITELLM}"]
    assert problems(ploeg.replace("unpriced-c", "missing-d"), litellm) == [f"missing-d: used by Ploeg but not defined in {LITELLM}"]
    assert problems(ploeg.replace("unpriced-c", "priced-a"), litellm) == []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("validate_ploeg_model_prices: self-test passed")
        return 0
    root = Path(args.root)
    found = problems((root / PLOEG).read_text(), (root / LITELLM).read_text())
    if found:
        print("Models Ploeg uses without a pinned price:", file=sys.stderr)
        for line in found:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"validate_ploeg_model_prices: every model Ploeg uses has a pinned price ({len(ploeg_models((root / PLOEG).read_text()))} models)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
