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
    settings = _settings(tmp_path)
    store = Store(settings.db_path)
    orchestrator = Orchestrator(settings, store)
    task_id = _enqueue(orchestrator)
    task = store.get(task_id)
    verdict = DevinVerdict.model_validate(
        {
            "outcome": "remediated",
            "summary": "Fixed",
            "pr_url": "https://github.com/harry1174/superset/pull/10",
            "verification": {
                "commands_run": ["pytest tests/unit_tests/test_network.py -q"],
                "all_passed": True,
                "evidence": "14 passed",
            },
        }
    )
    orchestrator.apply_verdict(
        task, {"acus_consumed": 4.0, "pr_url": verdict.pr_url}, verdict
    )
    before_merge = snapshot(store, settings)["headline"]
    assert before_merge["verified_prs"] == 1
    assert before_merge["cost_per_merged_pr_usd"] is None

    store.update(task_id, state="merged", pr_state="merged", merged_at=time.time())
    after_merge = snapshot(store, settings)["headline"]
    assert after_merge["merged_prs"] == 1
    assert after_merge["cost_per_merged_pr_usd"] == 9.0
    assert after_merge["assumed_hours_returned"] == 2.5


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
