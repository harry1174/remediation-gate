from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from pydantic import ValidationError

from .config import Settings
from .devin import DevinClient
from .github import GitHubClient
from .models import DevinVerdict
from .policy import load_knowledge, load_playbook
from .prompts import build_prompt
from .store import Store


log = logging.getLogger("orchestrator")


class Orchestrator:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self.devin = DevinClient(settings)
        self.github = GitHubClient(settings)
        self.playbook_id: str | None = None
        self.knowledge_id: str | None = None
        self._stop = threading.Event()

    def sync_policy(self) -> tuple[str, str]:
        self.playbook_id, self.knowledge_id = self.devin.sync_policy(
            load_playbook(), load_knowledge()
        )
        self.store.log(
            None,
            "policy_synced",
            {"playbook_id": self.playbook_id, "knowledge_id": self.knowledge_id},
        )
        return self.playbook_id, self.knowledge_id

    def enqueue(
        self,
        *,
        repo: str,
        issue_number: int,
        issue_url: str,
        issue_title: str,
        issue_body: str,
        issue_class: str,
        severity: str,
        source: str,
        delivery_id: str | None,
    ) -> bool:
        return self.store.claim_task(
            {
                "id": f"{repo.lower()}#{issue_number}",
                "repo": repo,
                "issue_number": issue_number,
                "issue_url": issue_url,
                "issue_title": issue_title,
                "issue_body": issue_body,
                "issue_class": issue_class,
                "severity": severity,
                "source": source,
                "delivery_id": delivery_id,
            }
        )

    def dispatch(self) -> int:
        started = 0
        for task in self.store.by_state("queued"):
            if self.store.active_count() >= self.settings.max_concurrent_sessions:
                break
            spent = self.store.acus_dispatched_since(time.time() - 86400)
            if self.settings.daily_acu_budget - spent < self.settings.max_acu_per_task:
                self.store.log(task["id"], "budget_throttled", {"spent": spent})
                break
            if not self.playbook_id or not self.knowledge_id:
                self.store.update(
                    task["id"],
                    state="failed",
                    failure_reason="remediation policy was not synced",
                )
                continue
            if not self.store.begin_dispatch(task["id"]):
                continue
            try:
                self._create_session(task)
                started += 1
            except Exception as exc:  # noqa: BLE001
                log.exception("session creation failed for %s", task["id"])
                attempts = task["attempts"] + 1
                self.store.update(
                    task["id"],
                    state="queued" if attempts < 3 else "failed",
                    failure_reason=f"session creation failed: {exc}"[:500],
                )
        return started

    def _create_session(self, task: dict[str, Any]) -> None:
        assert self.playbook_id and self.knowledge_id
        session = self.devin.create_session(
            prompt=build_prompt(task, playbook_attached=True),
            title=f"Remediate {task['repo']}#{task['issue_number']}",
            tags=[
                "remediation-gate",
                f"issue:{task['issue_number']}",
                f"class:{task['issue_class']}",
                f"severity:{task['severity']}",
            ],
            repo=task["repo"],
            playbook_id=self.playbook_id,
            knowledge_id=self.knowledge_id,
        )
        if not session.get("session_id") or not session.get("url"):
            raise ValueError("Devin returned no session ID or URL")
        self.store.update(
            task["id"],
            state="dispatched",
            session_id=session["session_id"],
            session_url=session["url"],
            playbook_id=self.playbook_id,
            knowledge_id=self.knowledge_id,
            dispatched_at=time.time(),
            failure_reason=None,
        )
        self.github.comment(
            task["issue_number"],
            f"Devin session started: {session['url']}\n\n"
            f"ACU cap: `{self.settings.max_acu_per_task}`. "
            "The issue will only be marked successful after verification passes.",
        )

    def reconcile(self) -> None:
        for task in self.store.by_state("dispatched", "running"):
            try:
                self._reconcile_session(task)
            except Exception as exc:  # noqa: BLE001
                log.exception("session reconciliation failed for %s", task["id"])
                self.store.log(task["id"], "reconcile_error", str(exc))
        for task in self.store.by_state("agent_verified_pr"):
            try:
                self._reconcile_checks(task)
            except Exception as exc:  # noqa: BLE001
                log.warning("check reconciliation failed for %s: %s", task["id"], exc)
        for task in self.store.by_state("verified_pr"):
            try:
                self._reconcile_pr(task)
            except Exception as exc:  # noqa: BLE001
                log.warning("PR reconciliation failed for %s: %s", task["id"], exc)

    def _reconcile_session(self, task: dict[str, Any]) -> None:
        session = self.devin.get_session(task["session_id"])
        self.store.update(task["id"], acus=session["acus_consumed"])

        if time.time() - task["dispatched_at"] > self.settings.session_timeout_minutes * 60:
            self.store.update(
                task["id"],
                state="timed_out",
                failure_reason=f"no terminal state after {self.settings.session_timeout_minutes} minutes",
            )
            self.github.add_labels(task["issue_number"], ["devin:needs-human"])
            return

        if session["status"] == "running" and task["state"] != "running":
            self.store.update(task["id"], state="running")
        if session["status"] not in {"exit", "error", "suspended"}:
            return

        raw_verdict = session.get("structured_output")
        if not raw_verdict:
            self.store.update(
                task["id"],
                state="failed",
                failure_reason=f"session ended as {session['status']} without structured output",
            )
            return
        try:
            verdict = DevinVerdict.model_validate(raw_verdict)
        except ValidationError as exc:
            self.store.update(
                task["id"],
                state="failed",
                failure_reason=f"invalid structured output: {exc}"[:500],
                verdict=json.dumps(raw_verdict)[:10000],
            )
            return
        self.apply_verdict(task, session, verdict)

    def apply_verdict(
        self, task: dict[str, Any], session: dict[str, Any], verdict: DevinVerdict
    ) -> None:
        pr_url = verdict.pr_url or session.get("pr_url")
        serialized = verdict.model_dump_json()
        verified = (
            verdict.outcome == "remediated"
            and bool(pr_url)
            and verdict.verification.all_passed
            and bool(verdict.verification.commands_run)
            and str(pr_url).startswith(f"https://github.com/{task['repo']}/pull/")
        )
        if verified:
            # Devin's verdict is a claim, not proof. The task waits in
            # agent_verified_pr until the repository's own checks agree.
            gated = self.settings.require_ci_checks
            self.store.update(
                task["id"],
                state="agent_verified_pr" if gated else "verified_pr",
                verification_passed=1,
                checks_passed=0 if gated else 1,
                checks_conclusion=None if gated else "not required",
                verdict=serialized,
                pr_url=pr_url,
                pr_state="open",
                pr_opened_at=time.time(),
                acus=session["acus_consumed"],
                failure_reason=None,
            )
            if gated:
                self.github.comment(
                    task["issue_number"],
                    f"Devin opened {pr_url} and reported passing verification.\n\n"
                    f"**Agent evidence:** {verdict.verification.evidence}\n"
                    f"**Risk:** {verdict.risk}\n\n"
                    "Holding until the repository's own checks confirm it. This issue "
                    "is not marked verified on the agent's word alone.",
                )
            else:
                self.github.add_labels(task["issue_number"], ["devin:verified-pr"])
                self.github.comment(
                    task["issue_number"],
                    f"Verified pull request opened: {pr_url}\n\n"
                    f"**Evidence:** {verdict.verification.evidence}\n\n"
                    f"**Risk:** {verdict.risk}\n\n"
                    "_CI confirmation is disabled (`REQUIRE_CI_CHECKS=false`), so this "
                    "rests on the agent's self-report._",
                )
            return

        if verdict.outcome == "no_change_needed":
            state = "no_change_needed"
            reason = verdict.summary
        elif verdict.outcome == "blocked":
            state = "blocked"
            reason = verdict.blocked_reason or verdict.summary
        else:
            state = "failed_verification"
            reason = "Devin proposed a remediation, but required verification did not pass"
        self.store.update(
            task["id"],
            state=state,
            verification_passed=0,
            verdict=serialized,
            pr_url=pr_url,
            acus=session["acus_consumed"],
            failure_reason=reason[:500],
        )
        self.github.add_labels(task["issue_number"], ["devin:needs-human"])
        self.github.comment(
            task["issue_number"],
            f"Devin stopped without a verified change.\n\n**Outcome:** `{state}`\n**Reason:** {reason}",
        )

    def _reconcile_checks(self, task: dict[str, Any]) -> None:
        """Promote to verified_pr only when the repository's own CI agrees.

        This is the gate that separates "the agent says the commands passed" from
        "the checks that govern every human pull request in this repository
        passed". The difference between the two is the honest defect rate of the
        Playbook, and it is reported on the dashboard.
        """
        checks = self.github.pr_checks(task["pr_url"])
        conclusion = checks["conclusion"]
        self.store.update(task["id"], checks_conclusion=conclusion)

        if conclusion == "success":
            # Stamped separately from pr_opened_at: the honest cycle time is
            # trigger to CI-confirmed, not trigger to the agent's assertion.
            self.store.update(
                task["id"],
                state="verified_pr",
                checks_passed=1,
                checks_confirmed_at=time.time(),
            )
            self.github.add_labels(task["issue_number"], ["devin:verified-pr"])
            self.github.comment(
                task["issue_number"],
                f"CI confirmed the change on `{checks['head_sha']}`. "
                f"{task['pr_url']} is verified and ready for review.",
            )
            return

        if conclusion == "failure":
            failing = ", ".join(checks["failing"]) or "unnamed check"
            self.store.update(
                task["id"],
                state="failed_verification",
                checks_passed=0,
                failure_reason=f"CI checks failed after the agent reported success: {failing}"[:500],
            )
            self.github.add_labels(task["issue_number"], ["devin:needs-human"])
            self.github.comment(
                task["issue_number"],
                f"Devin reported passing verification, but the repository's checks "
                f"disagree on `{checks['head_sha']}`.\n\n**Failing:** {failing}\n\n"
                f"{task['pr_url']} is left open for a human. This counts as a "
                "failure, not a success.",
            )
            return

        # Still pending, or the head commit has no checks at all. Both are fine
        # for a while and neither is fine forever.
        opened_at = task["pr_opened_at"] or time.time()
        if time.time() - opened_at <= self.settings.checks_grace_minutes * 60:
            return

        if conclusion == "none":
            state, reason = (
                "blocked",
                "no CI checks reported on the pull request head commit, so the "
                "agent's verification could not be independently confirmed",
            )
        else:
            state, reason = (
                "timed_out",
                f"CI checks did not complete within {self.settings.checks_grace_minutes} minutes",
            )
        self.store.update(task["id"], state=state, checks_passed=0, failure_reason=reason)
        self.github.add_labels(task["issue_number"], ["devin:needs-human"])
        self.github.comment(
            task["issue_number"],
            f"Could not independently confirm {task['pr_url']}.\n\n**Reason:** {reason}",
        )

    def _reconcile_pr(self, task: dict[str, Any]) -> None:
        state = self.github.pr_state(task["pr_url"])
        if state == "merged":
            now = time.time()
            self.store.update(
                task["id"], state="merged", pr_state="merged", merged_at=now
            )
        elif state == "closed":
            self.store.update(
                task["id"],
                state="failed",
                pr_state="closed",
                failure_reason="verified PR was closed without merging",
            )

    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self.dispatch()
                self.reconcile()
            except Exception:  # noqa: BLE001
                log.exception("control loop failed")
            self._stop.wait(self.settings.poll_interval_seconds)

    def start_background(self) -> None:
        threading.Thread(target=self.run_forever, daemon=True, name="remediation-loop").start()

    def stop(self) -> None:
        self._stop.set()
