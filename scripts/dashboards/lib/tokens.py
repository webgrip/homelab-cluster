from __future__ import annotations

PROM = {"type": "prometheus", "uid": "prometheus"}
LOGS = {"type": "victoriametrics-logs-datasource", "uid": "victorialogs"}
ALERTMANAGER_API = {"type": "yesoreyeram-infinity-datasource", "uid": "alertmanager-api"}

NEUTRAL = "#898781"
AMBER = "#e69f00"
VERMILLION = "#d55e00"
GREEN = "#009e73"
SKY = "#56b4e9"
KIOSK = (NEUTRAL, AMBER, VERMILLION, GREEN, SKY)

CAT = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
BLUE = CAT[0]


def steps(*pairs):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in pairs]}


def kiosk_steps(*pairs):
    for colour, value in pairs:
        if colour not in KIOSK:
            raise ValueError(f"{colour} is not a kiosk colour token")
        if value is None:
            raise ValueError("the base step is always NEUTRAL; pass only the steps above it")
    return steps((NEUTRAL, None), *pairs)


def alarm_at(amber=None, vermillion=None):
    pairs = []
    if amber is not None:
        pairs.append((AMBER, amber))
    if vermillion is not None:
        pairs.append((VERMILLION, vermillion))
    return kiosk_steps(*pairs)


def low_is_bad(vermillion_below, amber_below=None):
    pairs = [(VERMILLION, -1e18)]
    if amber_below is not None:
        pairs.append((AMBER, vermillion_below))
        pairs.append((NEUTRAL, amber_below))
    else:
        pairs.append((NEUTRAL, vermillion_below))
    return steps((NEUTRAL, None), *pairs)


def target_met(target, *, higher_is_better=True, miss=AMBER):
    if higher_is_better:
        return kiosk_steps((miss, 0), (GREEN, target))
    return kiosk_steps((GREEN, 0), (miss, target))
