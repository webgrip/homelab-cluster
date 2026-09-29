import random
from collections import Counter


def accuracy(truth, pred):
    return sum(t == p for t, p in zip(truth, pred)) / len(truth)


def macro_mae(truth, pred, levels):
    per_level = []
    for level in range(levels):
        errors = [abs(t - p) for t, p in zip(truth, pred) if t == level]
        if errors:
            per_level.append(sum(errors) / len(errors))
    return sum(per_level) / len(per_level)


def extreme_swap_rate(truth, pred, levels):
    top = levels - 1
    swaps = sum(1 for t, p in zip(truth, pred) if {t, p} == {0, top})
    return swaps / len(truth)


def linear_weighted_kappa(truth, pred, levels):
    n = len(truth)
    observed = [[0] * levels for _ in range(levels)]
    for t, p in zip(truth, pred):
        observed[t][p] += 1
    row = [sum(observed[i]) for i in range(levels)]
    col = [sum(observed[i][j] for i in range(levels)) for j in range(levels)]
    weight = lambda i, j: abs(i - j) / (levels - 1)
    disagreement_observed = sum(weight(i, j) * observed[i][j] for i in range(levels) for j in range(levels)) / n
    disagreement_expected = sum(weight(i, j) * row[i] * col[j] for i in range(levels) for j in range(levels)) / (n * n)
    if disagreement_expected == 0:
        return float("nan")
    return 1 - disagreement_observed / disagreement_expected


def confusion(truth, pred, levels):
    matrix = [[0] * levels for _ in range(levels)]
    for t, p in zip(truth, pred):
        matrix[t][p] += 1
    return matrix


def majority(values):
    return Counter(values).most_common(1)[0][0]


def paired_bootstrap_mae_difference(truth, pred_a, pred_b, levels, rounds=2000, seed=7):
    rng = random.Random(seed)
    n = len(truth)
    differences = []
    for _ in range(rounds):
        sample = [rng.randrange(n) for _ in range(n)]
        t = [truth[i] for i in sample]
        if len(set(t)) < 2:
            continue
        a = macro_mae(t, [pred_a[i] for i in sample], levels)
        b = macro_mae(t, [pred_b[i] for i in sample], levels)
        differences.append(a - b)
    differences.sort()
    low = differences[int(0.025 * len(differences))]
    high = differences[int(0.975 * len(differences)) - 1]
    return macro_mae(truth, pred_a, levels) - macro_mae(truth, pred_b, levels), low, high


def brier_binary(truth, probability):
    return sum((p - t) ** 2 for t, p in zip(truth, probability)) / len(truth)


def agreement_by_confidence_tercile(truth, pred, confidence):
    order = sorted(range(len(truth)), key=lambda i: confidence[i])
    third = len(order) // 3
    buckets = [order[:third], order[third:2 * third], order[2 * third:]]
    return [
        (round(min(confidence[i] for i in b), 3), round(max(confidence[i] for i in b), 3), sum(truth[i] == pred[i] for i in b) / len(b), len(b))
        for b in buckets if b
    ]


def self_test():
    truth = [0, 1, 2, 1, 0, 2, 1, 1]
    assert accuracy(truth, truth) == 1.0
    assert macro_mae(truth, truth, 3) == 0.0
    assert linear_weighted_kappa(truth, truth, 3) == 1.0
    assert extreme_swap_rate(truth, [2 - t for t in truth], 3) == 0.5
    always_middle = [1] * len(truth)
    assert macro_mae(truth, always_middle, 3) == (1 + 0 + 1) / 3
    assert abs(linear_weighted_kappa(truth, always_middle, 3)) < 1e-9
    inverted = [2 - t for t in truth]
    assert linear_weighted_kappa(truth, inverted, 3) < 0
    diff, low, high = paired_bootstrap_mae_difference(truth * 10, truth * 10, always_middle * 10, 3)
    assert diff < 0 and high < 0
    assert brier_binary([1, 0], [1.0, 0.0]) == 0.0 and brier_binary([1, 0], [0.0, 1.0]) == 1.0
    return "metrics self-test passed"


if __name__ == "__main__":
    print(self_test())
