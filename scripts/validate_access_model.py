#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0.2"]
# ///
"""Cross-file rules for the access model. Shape rules live in the JSON Schemas."""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

import yaml

RECERT_DAYS = 365
EXPIRY_WARN_DAYS = 30
SCOPABLE_PLANES = ("kubernetes", "harbor", "envoy")


def load(model: pathlib.Path, name: str, key: str) -> dict | list:
    return yaml.safe_load((model / f"{name}.yaml").read_text())[key]


def as_date(value: object) -> dt.date:
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))


def scopable(capability: dict) -> bool:
    projections = capability.get("projects") or {}
    return any(projections.get(plane, {}).get("scopable") for plane in SCOPABLE_PLANES)


def grantable(capability: dict) -> bool:
    return not capability.get("derived")


class Findings:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def check_capabilities(capabilities: dict, findings: Findings) -> None:
    for name, cap in capabilities.items():
        for other in cap.get("supersedes", []):
            if other not in capabilities:
                findings.error(f"capability {name}: supersedes unknown capability {other}")
        for edge in cap.get("escalates_to", []):
            if edge["capability"] not in capabilities:
                findings.error(f"capability {name}: escalates to unknown capability {edge['capability']}")
        if cap.get("derived") and cap.get("projects"):
            findings.error(f"capability {name}: derived capabilities may not project onto anything")
        if cap.get("break_glass") and cap["risk"] == "critical" and "alert" not in cap:
            findings.warn(f"capability {name}: critical break-glass without an alert")
    for name, cap in capabilities.items():
        seen, frontier = set(), list(cap.get("supersedes", []))
        while frontier:
            current = frontier.pop()
            if current == name:
                findings.error(f"capability {name}: supersession cycle")
                break
            if current in seen or current not in capabilities:
                continue
            seen.add(current)
            frontier.extend(capabilities[current].get("supersedes", []))


def check_grant(where: str, grant: dict, capabilities: dict, from_role: bool, human_role: bool, findings: Findings) -> None:
    name = grant["capability"]
    cap = capabilities.get(name)
    if cap is None:
        findings.error(f"{where}: unknown capability {name}")
        return
    if not grantable(cap):
        findings.error(f"{where}: {name} is derived and cannot be granted")
    scope = grant.get("scope")
    if scopable(cap) and scope is None:
        findings.error(f"{where}: {name} is scopable and needs scope: project or scope: cluster")
    if not scopable(cap) and scope is not None:
        kube = (cap.get("projects") or {}).get("kubernetes")
        if not (kube and kube.get("scopable") is False and scope == "cluster"):
            findings.error(f"{where}: {name} takes no scope")
    if from_role and human_role and scope == "cluster":
        findings.error(f"{where}: a role may not confer cluster scope; make it a dated grant on the person")
    if grant.get("project") and scope != "project":
        findings.error(f"{where}: project set without scope: project")


def check_roles(roles: dict, capabilities: dict, findings: Findings) -> None:
    for name, role in roles.items():
        for grant in role["grants"]:
            check_grant(f"role {name}", grant, capabilities, True, role.get("human", True), findings)


def check_projects(projects: dict, emails: set[str], today: dt.date, findings: Findings) -> None:
    owned: dict[str, str] = {}
    for name, project in projects.items():
        if project["owner"] not in emails:
            findings.error(f"project {name}: owner {project['owner']} is not in people.yaml")
        reviewed = as_date(project["reviewed"])
        if (today - reviewed).days > RECERT_DAYS:
            findings.error(f"project {name}: reviewed {project['reviewed']}, older than {RECERT_DAYS} days")
        for ns in project["namespaces"]:
            if ns in owned:
                findings.error(f"namespace {ns}: owned by both {owned[ns]} and {name}")
            owned[ns] = name


def check_people(people: list, roles: dict, capabilities: dict, projects: dict, today: dt.date, findings: Findings) -> None:
    ids = [p["id"] for p in people]
    for duplicate in {i for i in ids if ids.count(i) > 1}:
        findings.error(f"person {duplicate}: id used more than once")
    for field in ("email", "username", "forge"):
        values = [p[field] for p in people if p.get(field)]
        for duplicate in {v for v in values if values.count(v) > 1}:
            findings.error(f"{field} {duplicate}: used by more than one principal")
    by_id = {p["id"]: p for p in people}
    for person in people:
        where = f"person {person['id']}"
        role = roles.get(person["role"])
        if role is None:
            findings.error(f"{where}: unknown role {person['role']}")
            continue
        is_human = person["kind"] != "machine"
        if role.get("human", True) != is_human:
            findings.error(f"{where}: role {person['role']} is for {'humans' if role.get('human', True) else 'machines'}")
        if not is_human:
            continue
        for project in person["projects"]:
            if project not in projects:
                findings.error(f"{where}: unknown project {project}")
        reviewed = as_date(person["reviewed"])
        if (today - reviewed).days > RECERT_DAYS:
            findings.error(f"{where}: reviewed {person['reviewed']}, older than {RECERT_DAYS} days")
        for delegate in person.get("delegates_to", []):
            target = by_id.get(delegate)
            if target is None or target["role"] != "agent":
                findings.error(f"{where}: delegates to {delegate}, which is not an agent in people.yaml")
        for grant in person["grants"]:
            check_grant(f"{where} grant {grant['capability']}", grant, capabilities, False, True, findings)
            cap = capabilities.get(grant["capability"], {})
            if grant.get("project") and grant["project"] not in projects:
                findings.error(f"{where}: grant names unknown project {grant['project']}")
            if grant["until"] == "none":
                if not cap.get("break_glass"):
                    findings.error(f"{where}: until: none is only allowed on a break-glass capability")
                continue
            until = as_date(grant["until"])
            if until < today:
                findings.warn(f"{where}: grant {grant['capability']} expired {grant['until']} and renders nothing")
            elif (until - today).days <= EXPIRY_WARN_DAYS:
                findings.warn(f"{where}: grant {grant['capability']} expires {grant['until']}")


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    model = root / "kubernetes" / "apps" / "security" / "access-plane" / "model"
    today = dt.date.today()
    capabilities = load(model, "capabilities", "capabilities")
    roles = load(model, "roles", "roles")
    projects = load(model, "projects", "projects")
    people = load(model, "people", "people")
    findings = Findings()
    emails = {p["email"] for p in people if p.get("email")}
    check_capabilities(capabilities, findings)
    check_roles(roles, capabilities, findings)
    check_projects(projects, emails, today, findings)
    check_people(people, roles, capabilities, projects, today, findings)
    for message in findings.warnings:
        print(f"warning: {message}")
    for message in findings.errors:
        print(f"error: {message}")
    humans = sum(1 for p in people if p["kind"] != "machine")
    print(f"validate-access-model: {len(capabilities)} capabilities, {len(roles)} roles, {len(projects)} projects, {humans} humans, {len(people) - humans} machines, {len(findings.errors)} errors, {len(findings.warnings)} warnings")
    return 1 if findings.errors else 0


if __name__ == "__main__":
    sys.exit(main())
