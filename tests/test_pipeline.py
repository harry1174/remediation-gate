from __future__ import annotations

import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.metrics import snapshot
from app.models import DevinVerdict
from app.orchestrator import Orchestrator
from app.policy import load_playbook
from app.store import Store


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "demo_mode": True,
        "github_repo": "harry1174/superset",
        "github_webhook_secret": "test-secret",
        "db_path": str(tmp_path / "tasks.db"),
        "poll_interval_seconds": 1,
        "background_enabled": False,
        "sync_policy_on_boot": True,
    }
    values.update(overrides)
    return Settings(**values)


def _payload(repo: str = "harry1174/superset", issue_number: int = 42) -> dict:
    return {
        "action": "labeled",
        "label": {"name": "devin:autofix"},
        "repository": {"full_name": repo},
        "issue": {
            "number": issue_number,
            "title": "Handle missing ping executable",
            "body": "Acceptance criteria: return false and add a regression test.",
            "html_url": f"https://github.com/{repo}/issues/{issue_number}",
            "labels": [
                {"name": "devin:autofix"},
                {"name": "reliability"},
                {"name": "medium"},
            ],
        },
    }


def _signed(payload: dict, secret: str = "test-secret") -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {
        "Content-Type": "application/json",
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": "delivery-1",
        "X-Hub-Signature-256": f"sha256={signature}",
    }


def _enqueue(orchestrator: Orchestrator, issue_number: int = 42) -> str:
    orchestrator.enqueue(
        repo="harry1174/superset",
        issue_number=issue_number,
        issue_url=f"https://github.com/harry1174/superset/issues/{issue_number}",
        issue_title="Test issue",
        issue_body="Acceptance criteria: fix it and run pytest.",
        issue_class="reliability",
        severity="medium",
        source="test",
        delivery_id="delivery-1",
    )
    return f"harry1174/superset#{issue_number}"


def test_rejects_unsigned_webhook(tmp_path):
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/webhooks/github", json=_payload())
    assert response.status_code == 401


def test_rejects_unconfigured_repository(tmp_path):
    app = create_app(_settings(tmp_path))
    raw, headers = _signed(_payload(repo="attacker/superset"))
    with TestClient(app) as client:
        response = client.post("/webhooks/github", content=raw, headers=headers)
    assert response.status_code == 403


def test_duplicate_issue_never_creates_two_tasks(tmp_path):
    app = create_app(_settings(tmp_path))
    raw, headers = _signed(_payload())
    with TestClient(app) as client:
        first = client.post("/webhooks/github", content=raw, headers=headers)
        second = client.post("/webhooks/github", content=raw, headers=headers)
    assert first.json() == {"queued": True, "duplicate": False}
    assert second.json() == {"queued": False, "duplicate": True}
    assert len(app.state.store.all_tasks()) == 1


def test_playbook_macro_matches_v3_contract():
    assert load_playbook()["macro"] == "!remediate_issue"


def test_unverified_pr_is_not_reported_as_success(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.db_path)
    orchestrator = Orchestrator(settings, store)
    task_id = _enqueue(orchestrator)
    task = store.get(task_id)
    verdict = DevinVerdict.model_validate(
        {
            "outcome": "remediated",
            "summary": "Changed code but tests failed",
            "pr_url": "https://github.com/harry1174/superset/pull/9",
            "verification": {
                "commands_run": ["pytest tests/unit_tests/test_network.py -q"],
                "all_passed": False,
                "evidence": "1 failed",
            },
        }
    )
    orchestrator.apply_verdict(
        task, {"acus_consumed": 3.2, "pr_url": verdict.pr_url}, verdict
    )
    metrics = snapshot(store, settings)
    assert store.get(task_id)["state"] == "failed_verification"
    assert metrics["headline"]["verified_prs"] == 0
    assert metrics["headline"]["cost_per_merged_pr_usd"] is None


def test_merged_only_economics(tmp_path):
    settings, store, orchestrator, task_id = _claimed_task(tmp_path)
    orchestrator.github.pr_checks = lambda url: {
        "conclusion": "success",
        "failing": [],
        "head_sha": "abc123",
    }
    orchestrator.reconcile()

    before_merge = snapshot(store, settings)["headline"]
    assert before_merge["verified_prs"] == 1
    assert before_merge["cost_per_merged_pr_usd"] is None

    store.update(task_id, state="merged", pr_state="merged", merged_at=time.time())
    after_merge = snapshot(store, settings)["headline"]
    assert after_merge["merged_prs"] == 1
    assert after_merge["cost_per_merged_pr_usd"] == 9.0
    assert after_merge["assumed_hours_returned"] == 2.5


def _remediated(pr_number: int) -> DevinVerdict:
    return DevinVerdict.model_validate(
        {
            "outcome": "remediated",
            "summary": "Fixed",
            "pr_url": f"https://github.com/harry1174/superset/pull/{pr_number}",
            "verification": {
                "commands_run": ["pytest tests/unit_tests/utils/test_network.py -q"],
                "all_passed": True,
                "evidence": "14 passed",
            },
        }
    )


def _claimed_task(tmp_path, **overrides):
    """Drive one task to the point where Devin has claimed a verified PR."""
    settings = _settings(tmp_path, **overrides)
    store = Store(settings.db_path)
    orchestrator = Orchestrator(settings, store)
    task_id = _enqueue(orchestrator)
    verdict = _remediated(12)
    orchestrator.apply_verdict(
        store.get(task_id), {"acus_consumed": 4.0, "pr_url": verdict.pr_url}, verdict
    )
    return settings, store, orchestrator, task_id


def test_agent_claim_alone_does_not_reach_verified(tmp_path):
    """The whole point of the gate: Devin saying so is not evidence."""
    settings, store, _, task_id = _claimed_task(tmp_path)
    assert store.get(task_id)["state"] == "agent_verified_pr"
    headline = snapshot(store, settings)["headline"]
    assert headline["agent_claimed_prs"] == 1
    assert headline["verified_prs"] == 0


def test_ci_success_promotes_to_verified(tmp_path):
    settings, store, orchestrator, task_id = _claimed_task(tmp_path)
    orchestrator.github.pr_checks = lambda url: {
        "conclusion": "success",
        "failing": [],
        "head_sha": "abc123",
    }
    orchestrator.reconcile()
    assert store.get(task_id)["state"] == "verified_pr"
    assert snapshot(store, settings)["headline"]["verified_prs"] == 1


def test_ci_failure_after_agent_claims_success_is_a_failure(tmp_path):
    """An overclaim must never be counted as a shipped fix."""
    settings, store, orchestrator, task_id = _claimed_task(tmp_path)
    orchestrator.github.pr_checks = lambda url: {
        "conclusion": "failure",
        "failing": ["remediation-verify / lint"],
        "head_sha": "abc123",
    }
    orchestrator.reconcile()
    task = store.get(task_id)
    assert task["state"] == "failed_verification"
    assert task["checks_passed"] == 0
    headline = snapshot(store, settings)["headline"]
    assert headline["verified_prs"] == 0
    assert headline["agent_overclaims"] == 1
    assert headline["ci_adjudicated"] == 1
    taxonomy = snapshot(store, settings)["failure_taxonomy"]
    assert taxonomy == {"CI contradicted the agent": 1}


def test_pending_checks_hold_the_task_without_failing_it(tmp_path):
    settings, store, orchestrator, task_id = _claimed_task(tmp_path)
    orchestrator.github.pr_checks = lambda url: {
        "conclusion": "pending",
        "failing": [],
        "head_sha": "abc123",
    }
    orchestrator.reconcile()
    assert store.get(task_id)["state"] == "agent_verified_pr"
    assert snapshot(store, settings)["headline"]["needs_human"] == 0


def test_gate_can_be_disabled_and_says_so(tmp_path):
    """With no CI available, be explicit that verified means self-reported."""
    settings, store, _, task_id = _claimed_task(tmp_path, require_ci_checks=False)
    assert store.get(task_id)["state"] == "verified_pr"
    headline = snapshot(store, settings)["headline"]
    assert headline["verified_prs"] == 1
    assert headline["ci_confirmation"] == "disabled"


def test_verified_pr_closed_without_merging_is_counted_once_as_a_failure(tmp_path):
    """A closed PR must leave the verified funnel.

    `verification_passed` and `pr_opened_at` both persist after the PR is closed,
    so without the pr_state check the task lands in `verified` and in
    `unsuccessful` at the same time and is counted twice in the denominator.
    """
    settings, store, orchestrator, task_id = _claimed_task(tmp_path)
    orchestrator.github.pr_checks = lambda url: {
        "conclusion": "success",
        "failing": [],
        "head_sha": "abc123",
    }
    orchestrator.reconcile()
    assert snapshot(store, settings)["headline"]["verified_prs"] == 1

    store.update(
        task_id,
        state="failed",
        pr_state="closed",
        failure_reason="verified PR was closed without merging",
    )
    headline = snapshot(store, settings)["headline"]
    assert headline["verified_prs"] == 0
    assert headline["needs_human"] == 1
    assert headline["resolved"] == 1


def test_rate_is_withheld_until_the_sample_supports_one(tmp_path):
    """Two tasks do not make a percentage. Report counts instead."""
    settings = _settings(tmp_path)
    store = Store(settings.db_path)
    orchestrator = Orchestrator(settings, store)
    for number in (1, 2):
        task_id = _enqueue(orchestrator, number)
        store.update(task_id, state="blocked", failure_reason="needs a decision")
    headline = snapshot(store, settings)["headline"]
    assert headline["success_rate"] is None
    assert headline["resolved"] == 2


def test_budget_blocks_new_session(tmp_path):
    settings = _settings(tmp_path, daily_acu_budget=10, max_acu_per_task=5)
    store = Store(settings.db_path)
    orchestrator = Orchestrator(settings, store)
    first_id = _enqueue(orchestrator, 1)
    store.update(
        first_id,
        state="merged",
        acus=10,
        dispatched_at=time.time(),
        merged_at=time.time(),
    )
    _enqueue(orchestrator, 2)
    orchestrator.playbook_id = "playbook-test"
    orchestrator.knowledge_id = "note-test"
    assert orchestrator.dispatch() == 0
    assert store.get("harry1174/superset#2")["state"] == "queued"
