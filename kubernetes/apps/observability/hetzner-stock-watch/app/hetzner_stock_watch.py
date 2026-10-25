import json
import os
import sys
import time
import urllib.request

SITE = "https://www.hetzner.com"
PRODUCTS = os.environ.get("PRODUCTS", "ex44,ax41").split(",")
DATACENTERS = os.environ.get("DATACENTERS", "FSN1,NBG1,HEL1").split(",")
METRICS_URL = os.environ["METRICS_URL"]
USER_AGENT = "webgrip-homelab hetzner-stock-watch (read-only, hourly)"


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def product_ids(config):
    ids = set()
    for variation in config.get("Variations", {}).get("Items", []):
        for key in (variation.get("ProductID"), (variation.get("Limited") or {}).get("ProductID")):
            if key and key.startswith("ROBOT_"):
                ids.add(key.removeprefix("ROBOT_"))
    return ids


def label(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def main():
    lines = []
    resolved = 0
    availability = fetch_json(f"{SITE}/_resources/app/data/app/live_data_upfront.json")
    if not isinstance(availability, dict) or not availability:
        raise SystemExit("live_data_upfront.json is no longer a map of product ids to datacenters")
    for product in PRODUCTS:
        try:
            config = fetch_json(f"{SITE}/dedicated-rootserver/{product}/configurator/getServerConfig/")
        except Exception as error:
            print(f"{product}: configurator unreadable: {error}", file=sys.stderr)
            continue
        ids = product_ids(config)
        if not ids:
            print(f"{product}: configurator names no product id", file=sys.stderr)
            continue
        resolved += 1
        name = config.get("Name", product.upper())
        for datacenter in DATACENTERS:
            orderable = any(datacenter in availability.get(product_id, []) for product_id in ids)
            lines.append(f'hetzner_dedicated_orderable{{product="{label(name)}",datacenter="{label(datacenter)}"}} {int(orderable)}')
            print(f"{name} in {datacenter}: {'orderable' if orderable else 'not orderable'} (product ids {', '.join(sorted(ids))})")
    lines.append(f"hetzner_stock_watch_products_resolved {resolved}")
    lines.append(f"hetzner_stock_watch_products_watched {len(PRODUCTS)}")
    if resolved == len(PRODUCTS):
        lines.append(f"hetzner_stock_watch_last_success_timestamp_seconds {int(time.time())}")
    body = ("\n".join(lines) + "\n").encode()
    request = urllib.request.Request(METRICS_URL, data=body, method="POST", headers={"Content-Type": "text/plain"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in (200, 204):
            raise SystemExit(f"vmagent answered HTTP {response.status}")
    if resolved != len(PRODUCTS):
        raise SystemExit(f"read {resolved} of {len(PRODUCTS)} configurators")


if __name__ == "__main__":
    main()
