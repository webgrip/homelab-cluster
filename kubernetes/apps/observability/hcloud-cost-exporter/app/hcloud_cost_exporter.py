#!/usr/bin/env python3
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOURS_PER_MONTH_FOR_PER_GB_PRICES = 730
SECONDS_PER_HOUR = 3600
UNAUTHORIZED_STATUSES = (401, 403)


@dataclass(frozen=True)
class Resource:
    kind: str
    resource_id: str
    name: str
    role: str
    cluster: str
    location: str
    resource_type: str
    created: float
    hourly_eur: float
    monthly_cap_eur: float


@dataclass
class Snapshot:
    resources: list = field(default_factory=list)
    token_configured: bool = False
    api_authorized: bool = False
    refresh_ok: bool = False
    last_success: float = 0.0
    refresh_duration: float = 0.0
    refresh_failures: int = 0


def month_start(now: float) -> float:
    moment = datetime.fromtimestamp(now, tz=timezone.utc)
    return datetime(moment.year, moment.month, 1, tzinfo=timezone.utc).timestamp()


def next_month_start(now: float) -> float:
    moment = datetime.fromtimestamp(now, tz=timezone.utc)
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    return datetime(year, month, 1, tzinfo=timezone.utc).timestamp()


def billing_start(created: float, now: float) -> float:
    return max(created, month_start(now))


def started_hours(start: float, end: float) -> int:
    if end <= start:
        return 0
    return math.ceil((end - start) / SECONDS_PER_HOUR)


def capped_cost(hours: int, hourly_eur: float, monthly_cap_eur: float) -> float:
    return min(hours * hourly_eur, monthly_cap_eur)


def billable_hours_so_far(resource: Resource, now: float) -> int:
    return started_hours(billing_start(resource.created, now), now)


def month_to_date_eur(resource: Resource, now: float) -> float:
    return capped_cost(billable_hours_so_far(resource, now), resource.hourly_eur, resource.monthly_cap_eur)


def projected_month_eur(resource: Resource, now: float) -> float:
    hours = started_hours(billing_start(resource.created, now), next_month_start(now))
    return capped_cost(hours, resource.hourly_eur, resource.monthly_cap_eur)


def parse_time(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def net(price: dict) -> float:
    return float(price["net"])


def price_for_location(prices: list, location: str) -> dict:
    for entry in prices:
        if entry.get("location") == location:
            return entry
    raise LookupError(f"no price for location {location}")


def per_gb_resource_prices(size_gb: float, price_per_gb_month: float) -> tuple:
    monthly = size_gb * price_per_gb_month
    return monthly / HOURS_PER_MONTH_FOR_PER_GB_PRICES, monthly


def label(labels: dict, key: str, fallback: str = "") -> str:
    return (labels or {}).get(key, fallback)


def servers_to_resources(servers: list, backup_percentage: float) -> list:
    resources = []
    for server in servers:
        location = server["datacenter"]["location"]["name"]
        server_type = server["server_type"]
        price = price_for_location(server_type["prices"], location)
        common = dict(
            resource_id=str(server["id"]),
            name=server["name"],
            role=label(server.get("labels"), "role", "none"),
            cluster=label(server.get("labels"), "cluster"),
            location=location,
            resource_type=server_type["name"],
            created=parse_time(server["created"]),
        )
        resources.append(Resource(kind="server", hourly_eur=net(price["price_hourly"]),
                                  monthly_cap_eur=net(price["price_monthly"]), **common))
        if server.get("backup_window"):
            share = backup_percentage / 100
            resources.append(Resource(kind="server_backup", hourly_eur=net(price["price_hourly"]) * share,
                                      monthly_cap_eur=net(price["price_monthly"]) * share, **common))
    return resources


def primary_ips_to_resources(primary_ips: list, servers: list, pricing: dict) -> list:
    servers_by_id = {server["id"]: server for server in servers}
    prices_by_type = {entry["type"]: entry["prices"] for entry in pricing.get("primary_ips", [])}
    resources = []
    for primary_ip in primary_ips:
        location = primary_ip["datacenter"]["location"]["name"]
        type_prices = prices_by_type.get(primary_ip["type"])
        if not type_prices:
            continue
        price = price_for_location(type_prices, location)
        hourly, monthly = net(price["price_hourly"]), net(price["price_monthly"])
        if monthly == 0:
            continue
        assignee = servers_by_id.get(primary_ip.get("assignee_id")) or {}
        own_labels = primary_ip.get("labels") or {}
        server_labels = assignee.get("labels") or {}
        resources.append(Resource(
            kind="primary_ip",
            resource_id=str(primary_ip["id"]),
            name=primary_ip.get("name") or primary_ip["ip"],
            role=own_labels.get("role") or server_labels.get("role") or "none",
            cluster=own_labels.get("cluster") or server_labels.get("cluster", ""),
            location=location,
            resource_type=primary_ip["type"],
            created=parse_time(primary_ip["created"]),
            hourly_eur=hourly,
            monthly_cap_eur=monthly,
        ))
    return resources


def images_to_resources(images: list, pricing: dict) -> list:
    per_gb = net(pricing["image"]["price_per_gb_month"])
    resources = []
    for image in images:
        if image.get("type") not in ("snapshot", "backup"):
            continue
        hourly, monthly = per_gb_resource_prices(float(image.get("image_size") or 0), per_gb)
        resources.append(Resource(
            kind=image["type"],
            resource_id=str(image["id"]),
            name=image.get("description") or str(image["id"]),
            role=label(image.get("labels"), "role", "image"),
            cluster=label(image.get("labels"), "cluster"),
            location="",
            resource_type=image["type"],
            created=parse_time(image["created"]),
            hourly_eur=hourly,
            monthly_cap_eur=monthly,
        ))
    return resources


def volumes_to_resources(volumes: list, pricing: dict) -> list:
    per_gb = net(pricing["volume"]["price_per_gb_month"])
    resources = []
    for volume in volumes:
        hourly, monthly = per_gb_resource_prices(float(volume["size"]), per_gb)
        resources.append(Resource(
            kind="volume",
            resource_id=str(volume["id"]),
            name=volume["name"],
            role=label(volume.get("labels"), "role", "none"),
            cluster=label(volume.get("labels"), "cluster"),
            location=volume["location"]["name"],
            resource_type="volume",
            created=parse_time(volume["created"]),
            hourly_eur=hourly,
            monthly_cap_eur=monthly,
        ))
    return resources


def load_balancers_to_resources(load_balancers: list) -> list:
    resources = []
    for balancer in load_balancers:
        location = balancer["location"]["name"]
        balancer_type = balancer["load_balancer_type"]
        price = price_for_location(balancer_type["prices"], location)
        resources.append(Resource(
            kind="load_balancer",
            resource_id=str(balancer["id"]),
            name=balancer["name"],
            role=label(balancer.get("labels"), "role", "none"),
            cluster=label(balancer.get("labels"), "cluster"),
            location=location,
            resource_type=balancer_type["name"],
            created=parse_time(balancer["created"]),
            hourly_eur=net(price["price_hourly"]),
            monthly_cap_eur=net(price["price_monthly"]),
        ))
    return resources


def floating_ips_to_resources(floating_ips: list, pricing: dict) -> list:
    prices_by_type = {entry["type"]: entry["prices"] for entry in pricing.get("floating_ips", [])}
    resources = []
    for floating_ip in floating_ips:
        location = floating_ip["home_location"]["name"]
        price = price_for_location(prices_by_type.get(floating_ip["type"], []), location)
        monthly = net(price["price_monthly"])
        hourly = net(price["price_hourly"]) if "price_hourly" in price else monthly / HOURS_PER_MONTH_FOR_PER_GB_PRICES
        resources.append(Resource(
            kind="floating_ip",
            resource_id=str(floating_ip["id"]),
            name=floating_ip.get("name") or floating_ip["ip"],
            role=label(floating_ip.get("labels"), "role", "none"),
            cluster=label(floating_ip.get("labels"), "cluster"),
            location=location,
            resource_type=floating_ip["type"],
            created=parse_time(floating_ip["created"]),
            hourly_eur=hourly,
            monthly_cap_eur=monthly,
        ))
    return resources


def inventory_to_resources(inventory: dict) -> list:
    pricing = inventory["pricing"]
    backup_percentage = float(pricing.get("server_backup", {}).get("percentage", "20"))
    return (servers_to_resources(inventory["servers"], backup_percentage)
            + primary_ips_to_resources(inventory["primary_ips"], inventory["servers"], pricing)
            + images_to_resources(inventory["images"], pricing)
            + volumes_to_resources(inventory["volumes"], pricing)
            + load_balancers_to_resources(inventory["load_balancers"])
            + floating_ips_to_resources(inventory["floating_ips"], pricing))


class Unauthorized(Exception):
    pass


class HetznerClient:
    def __init__(self, base_url: str, token: str, timeout: int):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def get(self, path: str) -> dict:
        request = urllib.request.Request(f"{self.base_url}{path}",
                                         headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in UNAUTHORIZED_STATUSES:
                raise Unauthorized(f"{path} returned {error.code}") from error
            raise

    def list_all(self, path: str, key: str) -> list:
        items, page = [], 1
        separator = "&" if "?" in path else "?"
        while page:
            body = self.get(f"{path}{separator}page={page}&per_page=50")
            items.extend(body.get(key, []))
            page = (body.get("meta") or {}).get("pagination", {}).get("next_page")
        return items

    def inventory(self) -> dict:
        return {
            "pricing": self.get("/pricing")["pricing"],
            "servers": self.list_all("/servers", "servers"),
            "primary_ips": self.list_all("/primary_ips", "primary_ips"),
            "images": self.list_all("/images?type=snapshot", "images") + self.list_all("/images?type=backup", "images"),
            "volumes": self.list_all("/volumes", "volumes"),
            "load_balancers": self.list_all("/load_balancers", "load_balancers"),
            "floating_ips": self.list_all("/floating_ips", "floating_ips"),
        }


def escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def render_labels(pairs: dict) -> str:
    return "{" + ",".join(f'{key}="{escape(value)}"' for key, value in pairs.items()) + "}"


def resource_labels(project: str, resource: Resource) -> dict:
    return {
        "project": project,
        "kind": resource.kind,
        "id": resource.resource_id,
        "name": resource.name,
        "role": resource.role,
        "cluster": resource.cluster,
        "location": resource.location,
        "type": resource.resource_type,
    }


RESOURCE_SERIES = (
    ("hcloud_cost_resource_hourly_eur", "Net hourly list price of the resource in EUR.",
     lambda resource, now: resource.hourly_eur),
    ("hcloud_cost_resource_monthly_cap_eur", "Net monthly cap of the resource in EUR; Hetzner never bills more per month.",
     lambda resource, now: resource.monthly_cap_eur),
    ("hcloud_cost_resource_created_timestamp_seconds", "Creation time of the resource.",
     lambda resource, now: resource.created),
    ("hcloud_cost_resource_billable_hours", "Started hours billed this calendar month (UTC).",
     billable_hours_so_far),
    ("hcloud_cost_resource_month_to_date_eur", "Net cost this calendar month: started hours times hourly price, capped at the monthly price.",
     month_to_date_eur),
    ("hcloud_cost_resource_projected_month_eur", "Net cost by month end if the resource lives until then.",
     projected_month_eur),
)


def render(snapshot: Snapshot, project: str, now: float) -> str:
    project_labels = render_labels({"project": project})
    lines = [
        "# HELP hcloud_cost_token_configured 1 when an API token is mounted.",
        "# TYPE hcloud_cost_token_configured gauge",
        f"hcloud_cost_token_configured{project_labels} {int(snapshot.token_configured)}",
        "# HELP hcloud_cost_api_authorized 0 when the Hetzner API rejected the token.",
        "# TYPE hcloud_cost_api_authorized gauge",
        f"hcloud_cost_api_authorized{project_labels} {int(snapshot.api_authorized)}",
        "# HELP hcloud_cost_refresh_success 1 when the last inventory refresh succeeded.",
        "# TYPE hcloud_cost_refresh_success gauge",
        f"hcloud_cost_refresh_success{project_labels} {int(snapshot.refresh_ok)}",
        "# HELP hcloud_cost_last_success_timestamp_seconds Time of the last successful refresh.",
        "# TYPE hcloud_cost_last_success_timestamp_seconds gauge",
        f"hcloud_cost_last_success_timestamp_seconds{project_labels} {snapshot.last_success}",
        "# HELP hcloud_cost_refresh_duration_seconds Duration of the last refresh.",
        "# TYPE hcloud_cost_refresh_duration_seconds gauge",
        f"hcloud_cost_refresh_duration_seconds{project_labels} {snapshot.refresh_duration}",
        "# HELP hcloud_cost_refresh_failures_total Failed refreshes since start.",
        "# TYPE hcloud_cost_refresh_failures_total counter",
        f"hcloud_cost_refresh_failures_total{project_labels} {snapshot.refresh_failures}",
        "# HELP hcloud_cost_month_start_timestamp_seconds Start of the billed calendar month (UTC).",
        "# TYPE hcloud_cost_month_start_timestamp_seconds gauge",
        f"hcloud_cost_month_start_timestamp_seconds{project_labels} {month_start(now)}",
    ]
    for metric, help_text, value in RESOURCE_SERIES:
        lines.append(f"# HELP {metric} {help_text}")
        lines.append(f"# TYPE {metric} gauge")
        for resource in snapshot.resources:
            lines.append(f"{metric}{render_labels(resource_labels(project, resource))} {value(resource, now)}")
    return "\n".join(lines) + "\n"


class Exporter:
    def __init__(self, client_factory, token_path: str, project: str):
        self.client_factory = client_factory
        self.token_path = token_path
        self.project = project
        self.snapshot = Snapshot()
        self.lock = threading.Lock()

    def read_token(self) -> str:
        try:
            with open(self.token_path, encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            return ""

    def refresh(self) -> None:
        started = time.time()
        token = self.read_token()
        with self.lock:
            previous = self.snapshot
        snapshot = Snapshot(resources=previous.resources, last_success=previous.last_success,
                            refresh_failures=previous.refresh_failures, token_configured=bool(token))
        if not token:
            snapshot.resources = []
            snapshot.refresh_failures += 1
            log("no Hetzner token mounted; waiting for the secret to be seeded")
        else:
            try:
                snapshot.resources = inventory_to_resources(self.client_factory(token).inventory())
                snapshot.api_authorized = True
                snapshot.refresh_ok = True
                snapshot.last_success = time.time()
            except Unauthorized as error:
                snapshot.resources = []
                snapshot.refresh_failures += 1
                log(f"Hetzner API rejected the token: {error}")
            except Exception as error:
                snapshot.api_authorized = previous.api_authorized
                snapshot.refresh_failures += 1
                log(f"refresh failed: {type(error).__name__}: {error}")
        snapshot.refresh_duration = time.time() - started
        with self.lock:
            self.snapshot = snapshot

    def metrics(self) -> str:
        with self.lock:
            snapshot = self.snapshot
        return render(snapshot, self.project, time.time())


def log(message: str) -> None:
    print(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "msg": message}), file=sys.stderr, flush=True)


def handler_for(exporter: Exporter):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/metrics", "/healthz"):
                self.send_response(404)
                self.end_headers()
                return
            body = (exporter.metrics() if self.path == "/metrics" else "ok\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    return Handler


def refresh_forever(exporter: Exporter, interval: int) -> None:
    while True:
        exporter.refresh()
        time.sleep(interval)


def main() -> None:
    base_url = os.environ.get("HCLOUD_API_URL", "https://api.hetzner.cloud/v1")
    timeout = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "20"))
    exporter = Exporter(lambda token: HetznerClient(base_url, token, timeout),
                        os.environ.get("HCLOUD_TOKEN_FILE", "/var/run/hcloud/HCLOUD_TOKEN"),
                        os.environ.get("HCLOUD_PROJECT", "unfold"))
    interval = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "300"))
    threading.Thread(target=refresh_forever, args=(exporter, interval), daemon=True).start()
    port = int(os.environ.get("LISTEN_PORT", "9801"))
    ThreadingHTTPServer(("", port), handler_for(exporter)).serve_forever()


if __name__ == "__main__":
    main()
