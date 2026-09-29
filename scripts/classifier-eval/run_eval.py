import argparse
import json
import os
import statistics
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import board_state as bs
import metrics as m

EFFORT_LEVELS = [
    "Small: a change to one manifest or file in one app, following a pattern that already exists in the repo; the diff is reviewable in minutes",
    "Medium: several files or one new component, following an existing recipe end to end, delivered as one pull request",
    "Large: a new app, a migration, a cross-namespace or cross-repository change, or anything that needs more than one pull request",
]
TIME_LEVELS = [
    "Finishes within one working session, with no waiting on a rollout, a soak period, a person or another ticket",
    "Needs a reconcile-and-observe cycle, a soak of about a day, or one handoff to the owner",
    "Needs several soak periods or waits, a staged rollout, or an external dependency",
]
UNCERTAINTY_LEVELS = [
    "The approach is written in the ticket and has been done in this repository before",
    "The approach is known, but one fact must first be checked against live state or upstream",
    "The approach is unknown or disputed, the root cause is not established, or nothing like it exists yet; a spike is needed first",
]
SIZING_QUESTIONS = {
    "effort": {"type": "score", "instructions": "How much work is this ticket?", "criteria": EFFORT_LEVELS},
    "time": {"type": "score", "instructions": "How much wall-clock waiting does finishing this ticket involve?", "criteria": TIME_LEVELS},
    "uncertainty": {"type": "score", "instructions": "How well understood is the way to do this ticket?", "criteria": UNCERTAINTY_LEVELS},
}
READY_QUESTION = {
    "ready": {
        "type": "noul",
        "instructions": "Is this ticket ready to be worked on: does it state a problem backed by evidence, give checkable acceptance criteria, and name how to verify the result?",
        "criteria": {
            "true": "Ready: a problem with evidence, checkable acceptance criteria and a verification step",
            "false": "Not ready: a rough idea, or missing acceptance criteria or a verification step",
        },
    }
}
SST5_LEVELS = ["Very negative review", "Negative review", "Neutral or mixed review", "Positive review", "Very positive review"]
OBVIOUS_NOUL = [
    ("The deploy finished and every health check is green.", "Did the deploy succeed?", True),
    ("The build failed with exit code 1 after the tests crashed.", "Did the build succeed?", False),
    ("Please cancel my subscription immediately, I want a refund.", "Does the customer want to cancel?", True),
    ("Thanks, the fix works perfectly, you can close this.", "Is the customer reporting a new problem?", False),
]
OBVIOUS_CHOICE = [
    ("My card was charged twice for the same invoice.", {"billing": "Payments, invoices, refunds", "technical": "Bugs, outages, errors", "sales": "Pricing, upgrades, new accounts"}, "billing"),
    ("The app crashes with a null pointer error when I open settings.", {"billing": "Payments, invoices, refunds", "technical": "Bugs, outages, errors", "sales": "Pricing, upgrades, new accounts"}, "technical"),
    ("Do you offer a discount if we buy 200 seats?", {"billing": "Payments, invoices, refunds", "technical": "Bugs, outages, errors", "sales": "Pricing, upgrades, new accounts"}, "sales"),
]


def ask(base_url, model, state, questions, timeout=120):
    body = json.dumps({"model": model, "state": state, "questions": questions}).encode()
    request = urllib.request.Request(base_url + "/v1/systemone", data=body, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return payload, time.perf_counter() - started


def argmax_level(answer):
    probabilities = answer["probabilities"]
    return max(range(len(probabilities)), key=lambda i: probabilities[str(i)] if str(i) in probabilities else probabilities[i])


def level_probabilities(answer):
    probabilities = answer["probabilities"]
    if isinstance(probabilities, dict):
        return [probabilities[k] for k in sorted(probabilities, key=lambda k: int(k))]
    return list(probabilities)


def harness_check(base_url, model):
    failures = []
    for state, question, expected in OBVIOUS_NOUL:
        payload, _ = ask(base_url, model, state, {"q": {"type": "noul", "instructions": question}})
        p_true = payload["answers"]["q"]["noul"]
        if (p_true >= 0.5) != expected:
            failures.append(f"noul {question!r} p_true={p_true:.2f} expected {expected}")
    for state, options, expected in OBVIOUS_CHOICE:
        payload, _ = ask(base_url, model, state, {"q": {"type": "choice", "instructions": "Which team should handle this?", "criteria": options}})
        choice = payload["answers"]["q"]["choice"]
        if choice != expected:
            failures.append(f"choice {state!r} -> {choice} expected {expected}")
    return failures


def sst5_check(base_url, model, samples):
    from datasets import load_dataset

    rows = load_dataset("SetFit/sst5", split="test").shuffle(seed=7).select(range(samples))
    truth, pred = [], []
    for row in rows:
        payload, _ = ask(base_url, model, row["text"], {"s": {"type": "score", "instructions": "What is the sentiment of this movie review?", "criteria": SST5_LEVELS}})
        truth.append(int(row["label"]))
        pred.append(argmax_level(payload["answers"]["s"]))
    return m.accuracy(truth, pred), Counter(pred)


def run_parallel(base_url, model, items, questions, workers):
    def one(record):
        payload, seconds = ask(base_url, model, bs.ticket_state(record), questions)
        return record, payload, seconds

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, items))


def sizing_report(results, axis):
    rows = [(bs.axis_level(r["labels"], axis), p["answers"][axis]) for r, p, _ in results]
    rows = [(t, a) for t, a in rows if t is not None]
    truth = [t for t, _ in rows]
    pred = [argmax_level(a) for _, a in rows]
    confidence = [a.get("confidence", 0.0) for _, a in rows]
    baseline_level = m.majority(truth)
    baseline = [baseline_level] * len(truth)
    diff, low, high = m.paired_bootstrap_mae_difference(truth, pred, baseline, 3)
    return {
        "n": len(truth),
        "truth_distribution": dict(Counter(truth)),
        "pred_distribution": dict(Counter(pred)),
        "accuracy": round(m.accuracy(truth, pred), 3),
        "baseline_accuracy": round(m.accuracy(truth, baseline), 3),
        "macro_mae": round(m.macro_mae(truth, pred, 3), 3),
        "baseline_macro_mae": round(m.macro_mae(truth, baseline, 3), 3),
        "mae_minus_baseline": [round(diff, 3), round(low, 3), round(high, 3)],
        "extreme_swap_rate": round(m.extreme_swap_rate(truth, pred, 3), 3),
        "linear_weighted_kappa": round(m.linear_weighted_kappa(truth, pred, 3), 3),
        "confusion": m.confusion(truth, pred, 3),
        "agreement_by_confidence_tercile": m.agreement_by_confidence_tercile(truth, pred, confidence),
    }


def theme_questions(records, minimum):
    counts = Counter(bs.theme_of(r["labels"]) for r in records)
    options = sorted(t for t, c in counts.items() if t and c >= minimum)
    criteria = {t: "Work about " + t.split("/", 1)[1].replace("-", " ") for t in options}
    return options, {"theme": {"type": "choice", "instructions": "Which theme does this ticket belong to?", "criteria": criteria}}


def theme_report(results, options):
    truth, pred, top3 = [], [], []
    for record, payload, _ in results:
        theme = bs.theme_of(record["labels"])
        answer = payload["answers"]["theme"]
        truth.append(theme)
        pred.append(answer["choice"])
        ranked = sorted(answer["probabilities"], key=lambda k: answer["probabilities"][k], reverse=True)[:3]
        top3.append(theme in ranked)
    baseline = m.majority(truth)
    return {
        "n": len(truth),
        "options": len(options),
        "accuracy": round(m.accuracy(truth, pred), 3),
        "top3_accuracy": round(sum(top3) / len(top3), 3),
        "baseline_accuracy": round(m.accuracy(truth, [baseline] * len(truth)), 3),
        "baseline_theme": baseline,
    }


def ready_report(results):
    truth = [1 if "ready" in r["labels"] else 0 for r, _, _ in results]
    probability = [p["answers"]["ready"]["noul"] for _, p, _ in results]
    pred = [1 if x >= 0.5 else 0 for x in probability]
    positives = [x for x, t in zip(probability, truth) if t == 1]
    negatives = [x for x, t in zip(probability, truth) if t == 0]
    auc = sum((a > b) + 0.5 * (a == b) for a in positives for b in negatives) / (len(positives) * len(negatives))
    recall_ready = sum(1 for t, p in zip(truth, pred) if t == p == 1) / max(1, sum(truth))
    recall_refine = sum(1 for t, p in zip(truth, pred) if t == p == 0) / max(1, len(truth) - sum(truth))
    return {
        "n": len(truth),
        "accuracy_at_0.5": round(m.accuracy(truth, pred), 3),
        "balanced_accuracy": round((recall_ready + recall_refine) / 2, 3),
        "auc": round(auc, 3),
        "brier": round(m.brier_binary(truth, probability), 3),
        "baseline_accuracy": round(max(sum(truth), len(truth) - sum(truth)) / len(truth), 3),
        "mean_p_ready_on_ready": round(statistics.mean(positives), 3),
        "mean_p_ready_on_refine": round(statistics.mean(negatives), 3),
    }


def server_rss_mib():
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                if b"laya-serve" not in handle.read():
                    continue
            with open(f"/proc/{pid}/status") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) // 1024
        except OSError:
            continue
    return None


def latency_run(base_url, model, records, questions, count):
    seconds = []
    for record in records[:count]:
        _, elapsed = ask(base_url, model, bs.ticket_state(record), questions)
        seconds.append(elapsed)
    seconds.sort()
    return {"requests": len(seconds), "questions_per_request": len(questions), "p50_s": round(seconds[len(seconds) // 2], 3), "p95_s": round(seconds[int(len(seconds) * 0.95) - 1], 3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--models", default="english,typed-decisions")
    parser.add_argument("--data", default="data")
    parser.add_argument("--out", default="results")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--sst5", type=int, default=300)
    parser.add_argument("--stage", default="all", choices=["harness", "board", "all"])
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    print(m.self_test(), flush=True)

    report = {"server_rss_mib_start": server_rss_mib()}
    for model in args.models.split(","):
        section = report.setdefault(model, {})
        failures = harness_check(args.base_url, model)
        section["obvious_cases_failed"] = failures
        print(model, "obvious-case failures:", failures, flush=True)
        if args.sst5:
            accuracy, distribution = sst5_check(args.base_url, model, args.sst5)
            section["sst5"] = {"n": args.sst5, "accuracy": round(accuracy, 3), "model_card_claim": 0.372, "pred_distribution": dict(distribution)}
            print(model, "SST-5", section["sst5"], flush=True)
        if args.stage == "harness":
            continue

        closed = [r for r in bs.load_jsonl(os.path.join(args.data, "closed.jsonl")) if not bs.is_epic(r)]
        sized = [r for r in closed if any(bs.axis_level(r["labels"], a) is not None for a in bs.AXES)]
        sizing = run_parallel(args.base_url, model, sized, SIZING_QUESTIONS, args.workers)
        section["sizing"] = {axis: sizing_report(sizing, axis) for axis in bs.AXES}
        print(model, "sizing", json.dumps(section["sizing"]), flush=True)

        options, questions = theme_questions(closed, minimum=3)
        themed = [r for r in closed if bs.theme_of(r["labels"]) in options]
        theme_results = run_parallel(args.base_url, model, themed, questions, args.workers)
        section["theme"] = theme_report(theme_results, options)
        print(model, "theme", section["theme"], flush=True)

        open_set = [r for r in bs.load_jsonl(os.path.join(args.data, "open_ready_vs_refine.jsonl")) if not bs.is_epic(r)]
        ready_results = run_parallel(args.base_url, model, open_set, READY_QUESTION, args.workers)
        section["ready"] = ready_report(ready_results)
        print(model, "ready", section["ready"], flush=True)

        section["latency_sizing_sequential"] = latency_run(args.base_url, model, sized, SIZING_QUESTIONS, 30)
        print(model, "latency", section["latency_sizing_sequential"], flush=True)

        with open(os.path.join(args.out, f"predictions-{model}.jsonl"), "w") as handle:
            for record, payload, seconds in sizing + theme_results + ready_results:
                handle.write(json.dumps({"id": record["id"], "answers": payload["answers"], "model": payload.get("model"), "seconds": round(seconds, 3)}) + "\n")

    report["server_rss_mib_end"] = server_rss_mib()
    with open(os.path.join(args.out, "report.json"), "w") as handle:
        json.dump(report, handle, indent=2)
    print("REPORT WRITTEN", flush=True)


if __name__ == "__main__":
    main()
