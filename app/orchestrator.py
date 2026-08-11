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
from .store import Store, TERMINAL_STATES


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
            started_today = self.store.sessions_dispatched_since(time.time() - 86400)
            if started_today >= self.settings.max_sessions_per_day:
                self.store.log(
                    task["id"], "budget_throttled", {"sessions_today": started_today}
                )
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
            devin_mode=self.settings.devin_mode,
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
        self._close_finished_sessions()

    def _close_finished_sessions(self) -> None:
        """Terminate sessions whose task has finished.

        Observed across three live runs: Devin produces its verdict and then
        parks in `waiting_for_user` rather than exiting, so every completed task
        left a session open indefinitely. Once a task is terminal there is
        nothing left to ask, and leaving an agent parked is leaving a process
        idling on someone's account.

        Deliberately not done at `agent_verified_pr`: CI has not adjudicated yet
        there, and terminating is irreversible — it would foreclose ever sending
        a failure back to the session that produced it.
        """
        for state in TERMINAL_STATES:
            for task in self.store.by_state(state):
                if not task["session_id"]:
                    continue
                if self.store.has_event(task["id"], "session_terminated"):
                    continue
                try:
                    final = self.devin.terminate_session(task["session_id"])
                    self.store.log(
                        task["id"],
                        "session_terminated",
                        {"acus": final.get("acus_consumed"), "after": state},
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("could not close session for %s: %s", task["id"], exc)
                    self.store.log(task["id"], "session_terminated", f"failed: {exc}")

    def _reconcile_session(self, task: dict[str, Any]) -> None:
        session = self.devin.get_session(task["session_id"])
        self.store.update(task["id"], acus=session["acus_consumed"])

        if time.time() - task["dispatched_at"] > self.settings.session_timeout_minutes * 60:
            self._give_up(
                task,
                "timed_out",
                f"no terminal state after {self.settings.session_timeout_minutes} minutes",
            )
            return

        if session["status"] == "running" and task["state"] != "running":
            self.store.update(task["id"], state="running")

        # A verdict is actionable the moment it exists, whether or not the
        # session has formally exited. Observed live: Devin finished the work,
        # opened the pull request, emitted valid structured output, and then
        # parked in `waiting_for_user` rather than exiting. Gating on session
        # status first stranded a finished task until the timeout.
        raw_verdict = session.get("structured_output")

        if not raw_verdict:
            # No verdict yet. Now status_detail matters: it separates "stuck
            # waiting on a person" from "stopped because the account is out of
            # money", which otherwise look identical from here.
            if self._handle_status_detail(task, session):
                return
            if session["status"] not in {"exit", "error", "suspended"}:
                return
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

    # Suspensions that mean "the account cannot pay", not "the work failed".
    # Worth their own bucket: no amount of Playbook editing fixes them.
    BILLING_DETAILS = {
        "out_of_credits",
        "out_of_quota",
        "no_quota_allocation",
        "payment_declined",
        "usage_limit_exceeded",
        "org_usage_limit_exceeded",
        "user_usage_limit_exceeded",
        "total_session_limit_exceeded",
    }
    # Recoverable by a human, so the task stays alive and the timeout is the
    # backstop. Auto-resuming would spend ACUs nobody authorised, and the whole
    # premise here is that a human authorises spend.
    AWAITING_HUMAN_DETAILS = {"waiting_for_user", "waiting_for_approval", "inactivity"}

    def _handle_status_detail(
        self, task: dict[str, Any], session: dict[str, Any]
    ) -> bool:
        """Return True when the caller should stop processing this task."""
        detail = session.get("status_detail")
        if not detail:
            return False

        if detail in self.BILLING_DETAILS:
            self._give_up(task, "failed", f"Devin stopped on billing or quota: {detail}")
            return True

        if detail in self.AWAITING_HUMAN_DETAILS:
            kind = f"awaiting_human:{detail}"
            if not self.store.has_event(task["id"], kind):
                self.store.log(task["id"], kind, session.get("url"))
                self.github.comment(
                    task["issue_number"],
                    f"Devin is paused and needs a person: `{detail}`.\n\n"
                    f"Open the session to unblock it: {session.get('url')}\n\n"
                    "The task is still alive and will resume as soon as you act. "
                    "It is not auto-resumed, because resuming spends ACUs and "
                    "spending is a human decision here.",
                )
            return True
        return False

    def _give_up(self, task: dict[str, Any], state: str, reason: str) -> None:
        """Terminate the remote session, then record the local outcome.

        A control plane that abandons a task without stopping the agent is
        leaving a process running on someone else's budget. The API returns the
        final ACU count on termination, which is more trustworthy than whatever
        the last poll happened to see.
        """
        acus = task["acus"]
        try:
            final = self.devin.terminate_session(task["session_id"])
            acus = float(final.get("acus_consumed") or acus)
            self.store.log(task["id"], "session_terminated", {"acus": acus})
        except Exception as exc:  # noqa: BLE001
            log.warning("could not terminate session for %s: %s", task["id"], exc)
            self.store.log(task["id"], "terminate_failed", str(exc))
        self.store.update(
            task["id"], state=state, failure_reason=reason[:500], acus=acus
        )
        self.github.add_labels(task["issue_number"], ["devin:needs-human"])
        self.github.comment(
            task["issue_number"],
            f"Stopped and terminated the Devin session.\n\n**Reason:** {reason}",
        )

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
            return self._handle_failing_checks(task, checks)

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

    def _handle_failing_checks(
        self, task: dict[str, Any], checks: dict[str, Any]
    ) -> None:
        """Let the agent fix its own red build before calling the task failed.

        Observed live on issue #8: the first commit carried a lint suppression
        forward, CI went red, and Devin pushed a corrected commit about two
        minutes later without anyone asking. Devin watches its own pull requests
        independently of session state.

        Failing the task the instant a check goes red would have terminalised
        work the agent was actively repairing — and terminal states here are
        never revisited. So a red build is given a settling window, and a new
        head commit resets it, because a new commit means the agent is still
        working.
        """
        head = checks["head_sha"]
        failing = ", ".join(checks["failing"]) or "unnamed check"
        now = time.time()

        if task["checks_failed_sha"] != head:
            # First failure on this commit. Record it and say so, but wait.
            self.store.update(
                task["id"], checks_failed_sha=head, checks_failed_at=now
            )
            self.store.log(task["id"], "ci_failed_awaiting_agent", {"sha": head})
            self.github.comment(
                task["issue_number"],
                f"CI is red on `{head[:8]}`: **{failing}**.\n\n"
                f"Holding {task['pr_url']} for "
                f"{self.settings.checks_settle_minutes} minutes in case the agent "
                "pushes a correction — it watches its own pull requests. If the "
                "commit does not change, this becomes a failed verification.",
            )
            return

        if now - (task["checks_failed_at"] or now) < self.settings.checks_settle_minutes * 60:
            return

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
            f"still disagree on `{head}` after "
            f"{self.settings.checks_settle_minutes} minutes.\n\n"
            f"**Failing:** {failing}\n\n{task['pr_url']} is left open for a human. "
            "This counts as a failure, not a success.",
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
