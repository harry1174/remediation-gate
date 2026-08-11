#!/usr/bin/env python3
"""Readiness check. Read-only, spends no ACUs.

A Devin session against a repository the size of Superset costs real money and
takes real time, and the most common way to waste both is an environment problem
that was knowable in advance: the agent cannot reach the fork, the Playbook never
synced, the verification workflow is not the only check-run, or the account has
no credit left.

Run this immediately before triggering. Every check is a GET.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.policy import load_knowledge, load_playbook  # noqa: E402

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))


def devin(path: str) -> httpx.Response:
    return httpx.get(
        f"{settings.devin_org_url}{path}",
        headers={"Authorization": f"Bearer {settings.devin_api_key}"},
        timeout=30,
    )


def github(path: str) -> httpx.Response:
    return httpx.get(
        f"{settings.github_api}/repos/{settings.github_repo}{path}",
        headers={
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=30,
    )


def check_devin() -> None:
    try:
        response = devin("/sessions?limit=1")
    except Exception as exc:  # noqa: BLE001
        record(FAIL, "Devin API reachable", str(exc))
        return
    if response.status_code != 200:
        record(FAIL, "Devin API reachable", f"HTTP {response.status_code}")
        return
    record(PASS, "Devin API reachable", f"org {settings.devin_org_id}")

    integrations = devin("/integrations")
    if integrations.status_code == 200:
        installed = [
            item["name"]
            for item in integrations.json().get("integrations", [])
            if item.get("is_installed")
        ]
        if "github" in installed:
            record(PASS, "Devin GitHub integration", "installed org-wide")
        else:
            record(FAIL, "Devin GitHub integration", "not installed")
    record(
        WARN,
        "Devin can reach this specific fork",
        "no API exposes per-repo access; confirm the fork appears in the repo "
        "picker in the Devin web app",
    )

    playbook = load_playbook()["title"]
    remote = devin("/playbooks")
    titles = [item.get("title") for item in remote.json().get("items", [])]
    record(
        PASS if playbook in titles else FAIL,
        "Playbook synced",
        playbook if playbook in titles else "run `make policy`",
    )

    note = load_knowledge()["name"]
    notes = devin("/knowledge/notes")
    names = [item.get("name") for item in notes.json().get("items", [])]
    record(
        PASS if note in names else FAIL,
        "Knowledge note synced",
        note if note in names else "run `make policy`",
    )

    record(
        WARN,
        "ACU balance",
        "the API reports consumption, not remaining quota — confirm headroom in "
        f"the Devin web app. Cap is {settings.max_acu_per_task}/task, "
        f"{settings.daily_acu_budget}/day",
    )


def check_github() -> None:
    repo = github("")
    if repo.status_code != 200:
        record(FAIL, "Fork reachable", f"HTTP {repo.status_code}")
        return
    data = repo.json()
    record(PASS, "Fork reachable", settings.github_repo)
    record(
        PASS if data.get("default_branch") == "master" else FAIL,
        "Default branch is master",
        str(data.get("default_branch")),
    )

    # The gate reads check-runs; without this permission every verified PR
    # stalls waiting on a confirmation it cannot see.
    checks = github(f"/commits/{data.get('default_branch')}/check-runs")
    record(
        PASS if checks.status_code == 200 else FAIL,
        "Token has Checks: read",
        "ok" if checks.status_code == 200 else f"HTTP {checks.status_code}",
    )

    workflows = httpx.get(
        f"{settings.github_api}/repos/{settings.github_repo}/actions/workflows",
        headers={"Authorization": f"Bearer {settings.github_token}"},
        params={"per_page": 100},
        timeout=30,
    )
    if workflows.status_code == 200:
        active = [
            item["name"]
            for item in workflows.json().get("workflows", [])
            if item.get("state") == "active"
        ]
        ok = active == ["remediation-verify"]
        record(
            PASS if ok else FAIL,
            "Only the verification lane is active",
            ", ".join(active) if active else "none",
        )
    else:
        record(WARN, "Workflow states", f"HTTP {workflows.status_code}")

    hooks = httpx.get(
        f"{settings.github_api}/repos/{settings.github_repo}/hooks",
        headers={"Authorization": f"Bearer {settings.github_token}"},
        timeout=30,
    )
    if hooks.status_code == 200:
        live = [h for h in hooks.json() if h.get("active")]
        record(
            PASS if live else FAIL,
            "Issues webhook configured",
            live[0]["config"]["url"] if live else "create it in repo settings",
        )
    else:
        record(
            WARN,
            "Issues webhook configured",
            "token cannot read hooks; confirm in repo settings",
        )

    issues = github("/issues?state=open&per_page=20")
    if issues.status_code == 200:
        triggered = [
            i["number"]
            for i in issues.json()
            if any(
                lbl["name"].lower() == settings.trigger_label.lower()
                for lbl in i.get("labels", [])
            )
        ]
        record(
            PASS if not triggered else WARN,
            "No issue is pre-triggered",
            "clean" if not triggered else f"already labelled: {triggered}",
        )


def check_local() -> None:
    record(
        PASS if not settings.demo_mode else FAIL,
        "Service in live mode",
        "live" if not settings.demo_mode else "DEMO_MODE is still true",
    )
    record(
        PASS if settings.require_ci_checks else WARN,
        "CI gate enabled",
        "required" if settings.require_ci_checks else "self-reported only",
    )
    record(PASS, "Devin mode pinned", settings.devin_mode)


def main() -> int:
    if settings.demo_mode:
        print("DEMO_MODE is true — set it false before a live run.\n")
    check_local()
    check_devin()
    check_github()

    width = max(len(name) for _, name, _ in results)
    print()
    for status, name, detail in results:
        print(f"  [{status}] {name.ljust(width)}  {detail}")
    failures = [r for r in results if r[0] == FAIL]
    warnings = [r for r in results if r[0] == WARN]
    print(
        f"\n{len(results) - len(failures) - len(warnings)} passed, "
        f"{len(warnings)} to confirm manually, {len(failures)} blocking\n"
    )
    if failures:
        print("Do not trigger until the blocking checks pass.")
        return 1
    print("Clear to trigger. Add the trigger label to one issue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
