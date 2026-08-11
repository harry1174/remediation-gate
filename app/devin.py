from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

from .config import Settings
from .models import DevinVerdict


class DevinClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._http = httpx.Client(
            timeout=60,
            headers={
                "Authorization": f"Bearer {settings.devin_api_key}",
                "Content-Type": "application/json",
            },
        )
        self._mock_sessions: dict[str, dict[str, Any]] = {}

    def sync_policy(
        self, playbook: dict[str, str], knowledge: dict[str, str]
    ) -> tuple[str, str]:
        if self.settings.demo_mode:
            return "playbook-demo-remediate", "note-demo-superset"

        playbooks_url = f"{self.settings.devin_org_url}/playbooks"
        existing_playbooks = self._items(self._get(playbooks_url))
        existing = next(
            (item for item in existing_playbooks if item.get("title") == playbook["title"]),
            None,
        )
        if existing:
            playbook_id = existing["playbook_id"]
            self._put(f"{playbooks_url}/{playbook_id}", playbook)
        else:
            playbook_id = self._post(playbooks_url, playbook)["playbook_id"]

        knowledge_url = f"{self.settings.devin_org_url}/knowledge/notes"
        existing_notes = self._items(self._get(knowledge_url))
        existing_note = next(
            (item for item in existing_notes if item.get("name") == knowledge["name"]),
            None,
        )
        if existing_note:
            knowledge_id = existing_note["note_id"]
            self._put(f"{knowledge_url}/{knowledge_id}", knowledge)
        else:
            knowledge_id = self._post(knowledge_url, knowledge)["note_id"]
        return playbook_id, knowledge_id

    def create_session(
        self,
        *,
        prompt: str,
        title: str,
        tags: list[str],
        repo: str,
        playbook_id: str,
        knowledge_id: str,
    ) -> dict[str, Any]:
        if self.settings.demo_mode:
            return self._create_mock_session(prompt, title, tags, repo)

        payload = {
            "prompt": prompt,
            "title": title,
            "tags": tags,
            "repos": [f"https://github.com/{repo}"],
            "playbook_id": playbook_id,
            "knowledge_ids": [knowledge_id],
            "max_acu_limit": self.settings.max_acu_per_task,
            "devin_mode": self.settings.devin_mode,
            "structured_output_required": True,
            "structured_output_schema": DevinVerdict.model_json_schema(),
        }
        response = self._post(f"{self.settings.devin_org_url}/sessions", payload)
        return self._normalise(response)

    def org_corroboration(
        self, since: float, playbook_id: str | None = None
    ) -> dict[str, Any]:
        """Devin's own count of what this automation did.

        The dashboard's numbers come from a database this project controls.
        These come from Devin's analytics, which it does not.

        Filtered by playbook so the comparison is attributable rather than
        merely plausible. Without it the query returns every API-originated
        session in the organisation — nine in this account against four from
        this service — which happens to be harmless in an isolated org and
        wrong in a shared one. A bogus playbook id returns 404, so the filter
        is demonstrably applied rather than silently ignored.

        ACU consumption is deliberately absent: it reports 0.0 on accounts billed
        in credits, and a zero that means "not measured" is worse than no number.
        """
        if self.settings.demo_mode:
            return {"available": False, "reason": "demo mode"}
        params: dict[str, Any] = {
            "time_after": int(since),
            "time_before": int(time.time()) + 86400,
        }
        if playbook_id:
            params["playbook_id"] = playbook_id
        try:
            sessions = self._http.get(
                f"{self.settings.devin_org_url}/metrics/sessions",
                params=params,
                timeout=20,
            )
            prs = self._http.get(
                f"{self.settings.devin_org_url}/metrics/prs", params=params, timeout=20
            )
            sessions.raise_for_status()
            prs.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "reason": str(exc)[:200]}
        by_origin = sessions.json().get("sessions_created_by_origin", {})
        pr_data = prs.json()
        return {
            "available": True,
            "scoped_to_playbook": bool(playbook_id),
            "api_sessions": by_origin.get("api", 0),
            "human_sessions": sum(
                count for origin, count in by_origin.items() if origin != "api"
            ),
            "prs_created": pr_data.get("prs_created_count", 0),
            "prs_merged": pr_data.get("prs_merged_count", 0),
        }

    def terminate_session(self, session_id: str) -> dict[str, Any]:
        """Stop a session this control plane has given up on.

        Termination is irreversible, so it is only called once a task has hit a
        terminal state locally. `archive=true` keeps the transcript readable as
        evidence. The response carries the final ACU count, which is more
        trustworthy than the last figure polling happened to observe.
        """
        if self.settings.demo_mode:
            session = self._mock_sessions.get(session_id, {})
            return {"acus_consumed": float(session.get("acus", 0)), "status": "exit"}
        response = self._http.delete(
            f"{self.settings.devin_org_url}/sessions/{session_id}",
            params={"archive": "true"},
        )
        response.raise_for_status()
        return self._normalise(response.json())

    def get_session(self, session_id: str) -> dict[str, Any]:
        if self.settings.demo_mode:
            return self._get_mock_session(session_id)
        payload = self._get(f"{self.settings.devin_org_url}/sessions/{session_id}")
        return self._normalise(payload)

    def _get(self, url: str) -> dict[str, Any]:
        response = self._http.get(url)
        response.raise_for_status()
        return response.json()

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._http.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def _put(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._http.put(url, json=payload)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        return payload.get("items", []) if isinstance(payload, dict) else []

    @staticmethod
    def _normalise(payload: dict[str, Any]) -> dict[str, Any]:
        pull_requests = payload.get("pull_requests") or []
        pr_url = pull_requests[0].get("pr_url") if pull_requests else None
        return {
            "session_id": payload.get("session_id"),
            "url": payload.get("url"),
            "status": payload.get("status", "running"),
            "status_detail": payload.get("status_detail"),
            "acus_consumed": float(payload.get("acus_consumed") or 0),
            "structured_output": payload.get("structured_output"),
            "pr_url": pr_url,
        }

    def _create_mock_session(
        self, prompt: str, title: str, tags: list[str], repo: str
    ) -> dict[str, Any]:
        digest = hashlib.sha256(f"{title}\n{prompt}".encode()).hexdigest()[:12]
        session_id = f"devin-demo-{digest}"
        self._mock_sessions[session_id] = {
            "created_at": time.time(),
            "repo": repo,
            "title": title,
            "tags": tags,
            "acus": round(2.5 + int(digest[:2], 16) / 100, 2),
            "pr_number": 1000 + int(digest[-3:], 16) % 800,
        }
        return {
            "session_id": session_id,
            "url": f"https://app.devin.ai/sessions/{session_id}",
            "status": "running",
            "status_detail": "working",
            "acus_consumed": 0.0,
            "structured_output": None,
            "pr_url": None,
        }

    def _get_mock_session(self, session_id: str) -> dict[str, Any]:
        session = self._mock_sessions[session_id]
        elapsed = time.time() - session["created_at"]
        finished = elapsed >= 4
        pr_url = (
            f"https://github.com/{session['repo']}/pull/{session['pr_number']}"
            if finished
            else None
        )
        verdict = None
        if finished:
            verdict = {
                "outcome": "remediated",
                "summary": f"Demo remediation completed for {session['title']}.",
                "pr_url": pr_url,
                "files_changed": ["superset/target.py", "tests/unit_tests/test_target.py"],
                "verification": {
                    "commands_run": ["pytest tests/unit_tests/test_target.py -q"],
                    "all_passed": True,
                    "evidence": "12 passed in 1.4s (deterministic demo adapter)",
                },
                "risk": "low",
                "blocked_reason": "",
                "human_review_notes": "Demo mode: replace this with a live session before submission.",
            }
        progress = min(elapsed / 4, 1)
        return {
            "session_id": session_id,
            "url": f"https://app.devin.ai/sessions/{session_id}",
            "status": "exit" if finished else "running",
            "status_detail": "finished" if finished else "working",
            "acus_consumed": round(session["acus"] * progress, 2),
            "structured_output": verdict,
            "pr_url": pr_url,
        }
