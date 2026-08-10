from __future__ import annotations

import statistics
import time
from collections import Counter
from typing import Any

from .config import Settings
from .store import Store, TERMINAL_STATES


def snapshot(store: Store, settings: Settings) -> dict[str, Any]:
    tasks = store.all_tasks(1000)
    now = time.time()
    verified = [task for task in tasks if task["verification_passed"] and task["pr_opened_at"]]
    merged = [task for task in tasks if task["state"] == "merged"]
    active = [
        task
        for task in tasks
        if task["state"] in {"dispatching", "dispatched", "running"}
    ]
    unsuccessful = [
        task
        for task in tasks
        if task["state"] in TERMINAL_STATES and task["state"] != "merged"
    ]
    resolved = len(verified) + len(unsuccessful)
    total_acus = sum(float(task["acus"]) for task in tasks)
    merged_acus = sum(float(task["acus"]) for task in merged)
    lead_times = [
        (task["pr_opened_at"] - task["created_at"]) / 60 for task in verified
    ]
    failure_taxonomy = Counter(_failure_bucket(task) for task in unsuccessful)
    budget = settings.daily_acu_budget
    spent_today = store.acus_dispatched_since(now - 86400)
    hours_returned = len(merged) * settings.engineer_hours_per_merged_pr
    devin_cost = total_acus * settings.acu_unit_cost_usd
    assumed_value = hours_returned * settings.engineer_hourly_cost_usd

    return {
        "generated_at": now,
        "mode": "demo" if settings.demo_mode else "live",
        "repo": settings.github_repo,
        "policy": {
            "playbook": "Remediate a triaged issue",
            "knowledge": "Apache Superset repository conventions",
        },
        "funnel": [
            {"stage": "triggered", "count": len(tasks)},
            {"stage": "session", "count": sum(bool(task["session_id"]) for task in tasks)},
            {"stage": "verified_pr", "count": len(verified)},
            {"stage": "merged", "count": len(merged)},
        ],
        "headline": {
            "active": len(active),
            "verified_prs": len(verified),
            "merged_prs": len(merged),
            "needs_human": len(unsuccessful),
            "success_rate": round(len(verified) / resolved * 100, 1) if resolved else 0,
            "median_minutes_to_pr": round(statistics.median(lead_times), 1)
            if lead_times
            else None,
            "total_acus": round(total_acus, 2),
            "acus_per_verified_pr": round(
                sum(float(task["acus"]) for task in verified) / len(verified), 2
            )
            if verified
            else None,
            "cost_per_merged_pr_usd": round(devin_cost / len(merged), 2)
            if merged
            else None,
            "merged_acus": round(merged_acus, 2),
            "budget_used_pct": round(min(spent_today / budget, 1) * 100, 1)
            if budget > 0
            else 0,
            "assumed_hours_returned": round(hours_returned, 1),
            "assumed_net_value_usd": round(assumed_value - devin_cost, 2),
        },
        "failure_taxonomy": dict(failure_taxonomy),
        "tasks": [_task_view(task, now) for task in tasks],
        "events": store.recent_events(60),
        "assumptions": {
            "acu_unit_cost_usd": settings.acu_unit_cost_usd,
            "engineer_hours_per_merged_pr": settings.engineer_hours_per_merged_pr,
            "engineer_hourly_cost_usd": settings.engineer_hourly_cost_usd,
        },
    }


def _failure_bucket(task: dict[str, Any]) -> str:
    if task["state"] == "failed_verification":
        return "verification failed"
    if task["state"] == "timed_out":
        return "timed out"
    if task["state"] == "blocked":
        return "needs engineering decision"
    if task["state"] == "no_change_needed":
        return "not reproducible"
    return "infrastructure or review"


def _task_view(task: dict[str, Any], now: float) -> dict[str, Any]:
    end = task["merged_at"] or task["pr_opened_at"] or task["completed_at"] or now
    return {
        "id": task["id"],
        "issue_number": task["issue_number"],
        "issue_url": task["issue_url"],
        "title": task["issue_title"],
        "class": task["issue_class"],
        "severity": task["severity"],
        "state": task["state"],
        "session_url": task["session_url"],
        "pr_url": task["pr_url"],
        "verification_passed": bool(task["verification_passed"]),
        "acus": round(float(task["acus"]), 2),
        "elapsed_minutes": round((end - task["created_at"]) / 60, 1),
        "failure_reason": task["failure_reason"],
    }
