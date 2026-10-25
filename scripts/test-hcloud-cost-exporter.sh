#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
script="$repo_root/kubernetes/apps/observability/hcloud-cost-exporter/app/hcloud_cost_exporter.py"
suite="$repo_root/scripts/test_hcloud_cost_exporter.py"
python="${PYTHON:-python3}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "==> unmutated exporter must pass"
EXPORTER_SCRIPT="$script" "$python" "$suite" 2>"$work/clean.log" || { cat "$work/clean.log" >&2; exit 1; }

mutate() {
  name="$1"
  find="$2"
  replace="$3"
  test_name="$4"
  copy="$work/$name.py"
  "$python" - "$script" "$copy" "$find" "$replace" <<'PY'
import sys
source, target, find, replace = sys.argv[1:]
text = open(source).read()
if find not in text:
    sys.exit(f"mutation anchor not found: {find!r}")
open(target, "w").write(text.replace(find, replace, 1))
PY
  if EXPORTER_SCRIPT="$copy" "$python" "$suite" "$test_name" >"$work/$name.log" 2>&1; then
    echo "MUTATION SURVIVED: $name ($test_name passed against the mutant)" >&2
    exit 1
  fi
  echo "killed: $name by $test_name"
}

mutate no-monthly-cap \
  "return min(hours * hourly_eur, monthly_cap_eur)" \
  "return hours * hourly_eur" \
  BillingModelTest.test_monthly_price_caps_a_full_month
mutate floor-instead-of-started-hours \
  "return math.ceil((end - start) / SECONDS_PER_HOUR)" \
  "return math.floor((end - start) / SECONDS_PER_HOUR)" \
  BillingModelTest.test_partial_hours_bill_as_started_hours
mutate bill-from-creation-not-month-start \
  "return max(created, month_start(now))" \
  "return created" \
  BillingModelTest.test_resource_from_last_month_bills_from_the_first_of_this_month
mutate gross-instead-of-net \
  'return float(price["net"])' \
  'return float(price["gross"]) * 1.21' \
  InventoryTest.test_server_price_follows_its_location
mutate ignore-location \
  'if entry.get("location") == location:' \
  'if True:' \
  InventoryTest.test_server_price_follows_its_location
mutate ip-without-server-role \
  'role=own_labels.get("role") or server_labels.get("role") or "none",' \
  'role=own_labels.get("role") or "none",' \
  InventoryTest.test_primary_ipv4_inherits_its_server_role_and_free_ipv6_is_skipped
mutate single-page \
  'page = (body.get("meta") or {}).get("pagination", {}).get("next_page")' \
  'page = None' \
  HetznerClientTest.test_list_follows_every_page
mutate rejected-token-reads-as-transient \
  "if error.code in UNAUTHORIZED_STATUSES:" \
  "if False:" \
  HetznerClientTest.test_rejected_token_raises_unauthorized
mutate rejection-keeps-stale-inventory \
  '            except Unauthorized as error:
                snapshot.resources = []' \
  '            except Unauthorized as error:
                pass' \
  ExporterTest.test_rejected_token_reports_unauthorized_and_drops_stale_resources

echo "all mutations killed"
