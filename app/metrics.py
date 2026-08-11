from __future__ import annotations

import statistics
import time
from collections import Counter
from typing import Any

from .config import Settings
from .store import Store, TERMINAL_STATES


# A rate over a handful of tasks is noise dressed as a measurement. Below this
# many resolved tasks the dashboard reports counts instead.
MIN_SAMPLE_FOR_RATE = 5


def snapshot(store: Store, settings: Settings) -> dict[str, Any]:
    tasks = store.all_tasks(1000)
    now = time.time()
    # A PR that was verified and then closed without merging is not a success.
    # Without the pr_state check it would count in `verified` *and* in
    # `unsuccessful`, landing on both sides of the `resolved` denominator.
    open_prs = [
        task for task in tasks if task["pr_opened_at"] and task["pr_state"] != "closed"
    ]
    # The agent's own claim, and the repository's independent confirmation of it.
    # Reporting both is what makes the gap measurable.
    agent_claimed = [task for task in open_prs if task["verification_passed"]]
    verified = [task for task in open_prs if task["checks_passed"]]
    adjudicated = [
        task
        for task in agent_claimed
        if task["checks_conclusion"] in {"success", "failure"}
    ]
    overclaimed = [
        task for task in adjudicated if task["checks_conclusion"] == "failure"
    ]
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
    # Two different cycle times. The first is when the agent asserted a PR; the
    # second is when the repository's CI agreed. Only the second is worth
    # quoting, because only the second is independent of the thing being sold.
    claim_times = [
        (task["pr_opened_at"] - task["created_at"]) / 60 for task in agent_claimed
    ]
    verified_times = [
        (task["checks_confirmed_at"] - task["created_at"]) / 60
        for task in verified
        if task["checks_confirmed_at"]
    ]
    failure_taxonomy = Counter(_failure_bucket(task) for task in unsuccessful)
    budget = settings.daily_acu_budget
    spent_today = store.acus_dispatched_since(now - 86400)
    # Spend counts every attempt, including the ones that failed. Dividing only
    # the successful sessions by the merged count would flatter the number.
    #
    # Devin does not report ACU consumption on every plan — an account billed in
    # credits returns 0.0 from both the session object and the consumption API.
    # Reporting "$0.00 per merged PR" off that would be worse than reporting
    # nothing, so cost is withheld and the reason is stated.
    dispatched = [task for task in tasks if task["session_id"]]
    acus_reported = total_acus > 0 or not dispatched
    if acus_reported:
        devin_cost = total_acus * settings.acu_unit_cost_usd
        cost_basis = "acus_reported"
    elif settings.pilot_measured_cost_usd > 0:
        # No ACUs to derive from, but the spend was observed directly from the
        # account balance. Labelled as such: it is entered by a human, not
        # measured by this service.
        devin_cost = settings.pilot_measured_cost_usd
        cost_basis = "measured from account balance"
    else:
        devin_cost = None
        cost_basis = "unavailable: Devin reported no ACU consumption for this account"

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
            {"stage": "agent_pr", "count": len(agent_claimed)},
            {"stage": "verified_pr", "count": len(verified)},
            {"stage": "merged", "count": len(merged)},
        ],
        "headline": {
            "active": len(active),
            "agent_claimed_prs": len(agent_claimed),
            "verified_prs": len(verified),
            # How often the agent said "verified" and CI disagreed. This is the
            # Playbook's defect rate, and the only honest way to know whether
            # editing the Playbook made things better.
            "ci_adjudicated": len(adjudicated),
            "agent_overclaims": len(overclaimed),
            "ci_confirmation": "required" if settings.require_ci_checks else "disabled",
            "merged_prs": len(merged),
            "needs_human": len(unsuccessful),
            "resolved": resolved,
            "success_rate": round(len(verified) / resolved * 100, 1)
            if resolved >= MIN_SAMPLE_FOR_RATE
            else None,
            "median_minutes_to_agent_pr": round(statistics.median(claim_times), 1)
            if claim_times
            else None,
            "median_minutes_to_verified": round(statistics.median(verified_times), 1)
            if verified_times
            else None,
            "total_acus": round(total_acus, 2),
            "acus_per_verified_pr": round(
                sum(float(task["acus"]) for task in verified) / len(verified), 2
            )
            if verified
            else None,
            "cost_per_merged_pr_usd": round(devin_cost / len(merged), 2)
            if merged and devin_cost is not None
            else None,
            "cost_basis": cost_basis,
            "merged_acus": round(merged_acus, 2),
            "budget_used_pct": round(min(spent_today / budget, 1) * 100, 1)
            if budget > 0
            else 0,
            "total_execution_cost_usd": round(devin_cost, 2)
            if devin_cost is not None
            else None,
        },
        # Deliberately separated from `headline`. Everything above is an
        # observation. Everything here is arithmetic on top of numbers nobody
        # measured, shown as a low/base/high band so it reads as a planning
        # scenario rather than a saving that has already been banked.
        "modeled": _scenarios(len(merged), devin_cost or 0.0, settings),
        "failure_taxonomy": dict(failure_taxonomy),
        "tasks": [_task_view(task, now) for task in tasks],
        "events": store.recent_events(60),
        "assumptions": {
            "acu_unit_cost_usd": settings.acu_unit_cost_usd,
            "acu_unit_cost_verified": settings.acu_unit_cost_verified,
            "engineer_hourly_cost_usd": settings.engineer_hourly_cost_usd,
            "baseline_human_hours": [
                settings.baseline_human_hours_low,
                settings.engineer_hours_per_merged_pr,
                settings.baseline_human_hours_high,
            ],
        },
    }


def _scenarios(
    merged_count: int, execution_cost_usd: float, settings: Settings
) -> dict[str, Any]:
    """Capacity and value modelled across a low/base/high baseline band.

    A single point estimate invites an argument about the point. A band invites
    a conversation about the range, which is the conversation worth having — and
    it makes explicit that the uncertainty lives in the human baseline, not in
    the measured ACU spend.
    """
    bands = {
        "conservative": settings.baseline_human_hours_low,
        "base": settings.engineer_hours_per_merged_pr,
        "upside": settings.baseline_human_hours_high,
    }
    out: dict[str, Any] = {}
    for name, hours in bands.items():
        capacity = merged_count * hours
        out[name] = {
            "baseline_hours_per_remediation": hours,
            "modeled_capacity_returned_hours": round(capacity, 1),
            "modeled_net_value_usd": round(
                capacity * settings.engineer_hourly_cost_usd - execution_cost_usd, 2
            ),
        }
    return out


def _failure_bucket(task: dict[str, Any]) -> str:
    reason = (task["failure_reason"] or "").lower()
    if "billing or quota" in reason:
        # Not a remediation failure at all, and not fixable by editing policy.
        return "billing or quota"
    if task["state"] == "failed_verification":
        # Two different failures wear the same state: the agent admitted its
        # commands failed, or the agent claimed success and CI disagreed. The
        # second one is a Playbook defect and needs its own bucket.
        if task["checks_conclusion"] == "failure":
            return "CI contradicted the agent"
        return "agent reported verification failure"
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
        "checks_passed": bool(task["checks_passed"]),
        "checks_conclusion": task["checks_conclusion"],
        "minutes_to_verified": round(
            (task["checks_confirmed_at"] - task["created_at"]) / 60, 1
        )
        if task["checks_confirmed_at"]
        else None,
        "acus": round(float(task["acus"]), 2),
        "elapsed_minutes": round((end - task["created_at"]) / 60, 1),
        "failure_reason": task["failure_reason"],
    }
