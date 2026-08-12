from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import Settings


log = logging.getLogger("github")

REMEDIATION_CONTRACT_SECTIONS = (
    "## observed problem",
    "## scope",
    "## acceptance criteria",
    "## verification",
    "## non-goals",
)


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


class GitHubClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Writes that failed on permissions. A status comment failing must not
        # kill a remediation, but it must not vanish into a log line either:
        # the first live run lost every issue comment to a 403 and the only
        # trace was a warning nobody was watching.
        self.degraded: list[str] = []
        self._http = httpx.Client(
            timeout=30,
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        self._mock_pr_seen: dict[str, float] = {}
        self._mock_issue_number = 0

    def _url(self, path: str) -> str:
        return f"{self.settings.github_api}/repos/{self.settings.github_repo}{path}"

    def comment(self, issue_number: int, body: str) -> None:
        if self.settings.demo_mode:
            return
        try:
            response = self._http.post(
                self._url(f"/issues/{issue_number}/comments"), json={"body": body}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self._degrade("comment", issue_number, exc)

    def add_labels(self, issue_number: int, labels: list[str]) -> None:
        if self.settings.demo_mode:
            return
        try:
            response = self._http.post(
                self._url(f"/issues/{issue_number}/labels"), json={"labels": labels}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self._degrade("label", issue_number, exc)

    def _degrade(self, action: str, issue_number: int, exc: Exception) -> None:
        """Record a failed write loudly without failing the remediation."""
        note = f"{action} on issue {issue_number} failed: {exc}"[:300]
        log.warning("DEGRADED: %s", note)
        if note not in self.degraded:
            self.degraded.append(note)

    def ensure_labels(self, labels: dict[str, str]) -> None:
        if self.settings.demo_mode:
            return
        for name, color in labels.items():
            response = self._http.post(
                self._url("/labels"), json={"name": name, "color": color}
            )
            if response.status_code not in {201, 422}:
                response.raise_for_status()

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict[str, Any]:
        if self.settings.demo_mode:
            self._mock_issue_number += 1
            return {
                "number": self._mock_issue_number,
                "html_url": f"https://github.com/{self.settings.github_repo}/issues/{self._mock_issue_number}",
            }
        response = self._http.post(
            self._url("/issues"), json={"title": title, "body": body, "labels": labels}
        )
        response.raise_for_status()
        return response.json()

    def pilot_issue_cohort(
        self, approved_issue_numbers: set[int] | None = None
    ) -> dict[str, Any]:
        """Return the source-backed issue population upstream of automation.

        A task only reaches the local ledger after a person applies the trigger
        label, so the ledger cannot describe unapproved demand. GitHub owns that
        population. An issue is included when its body carries the complete
        remediation contract; approval is reported separately as the trigger
        label that authorizes a Devin session and its spend.
        """
        if self.settings.demo_mode:
            return {
                "available": False,
                "reason": "GitHub backlog is not queried in demo mode",
            }

        issues: list[dict[str, Any]] = []
        approval_history = approved_issue_numbers or set()
        try:
            for page in range(1, 11):
                response = self._http.get(
                    self._url("/issues"),
                    params={"state": "all", "per_page": 100, "page": page},
                )
                response.raise_for_status()
                batch = response.json()
                if not isinstance(batch, list):
                    raise ValueError("GitHub issues response was not a list")
                issues.extend(batch)
                if len(batch) < 100:
                    break
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("could not read pilot issue cohort: %s", exc)
            return {"available": False, "reason": str(exc)[:300]}

        cohort = []
        trigger = self.settings.trigger_label.lower()
        for issue in issues:
            if issue.get("pull_request"):
                continue
            body = str(issue.get("body") or "").lower()
            if not all(section in body for section in REMEDIATION_CONTRACT_SECTIONS):
                continue
            labels = {
                str(label.get("name", "")).lower()
                for label in issue.get("labels", [])
                if isinstance(label, dict)
            }
            number = int(issue["number"])
            cohort.append(
                {
                    "number": number,
                    "title": str(issue.get("title") or ""),
                    "url": str(issue.get("html_url") or ""),
                    "state": str(issue.get("state") or "unknown"),
                    # The current label is the GitHub approval signal. The
                    # ledger preserves that decision if the label is removed
                    # after a session has already been authorized.
                    "approved": trigger in labels or number in approval_history,
                }
            )

        cohort.sort(key=lambda issue: issue["number"])
        approved = sum(issue["approved"] for issue in cohort)
        open_issues = sum(issue["state"] == "open" for issue in cohort)
        return {
            "available": True,
            "source": "GitHub Issues API + remediation ledger",
            "scope": "all issues with a complete remediation contract",
            "approval_definition": (
                f"current {self.settings.trigger_label} label or accepted label webhook"
            ),
            "identified": len(cohort),
            "approved": approved,
            "awaiting_approval": len(cohort) - approved,
            "open": open_issues,
            "open_awaiting_approval": sum(
                issue["state"] == "open" and not issue["approved"]
                for issue in cohort
            ),
            "issues": cohort,
        }

    def _pr_number(self, pr_url: str) -> str | None:
        """Extract the PR number, refusing anything outside the configured repo."""
        parsed = urlparse(pr_url)
        parts = parsed.path.strip("/").split("/")
        if parsed.netloc != "github.com" or len(parts) != 4 or parts[2] != "pull":
            log.warning("ignoring malformed PR URL: %s", pr_url)
            return None
        if f"{parts[0]}/{parts[1]}".lower() != self.settings.github_repo.lower():
            log.warning("ignoring PR outside configured repository: %s", pr_url)
            return None
        return parts[3]

    def pr_state(self, pr_url: str) -> str | None:
        if self.settings.demo_mode:
            first_seen = self._mock_pr_seen.setdefault(pr_url, time.time())
            return "merged" if time.time() - first_seen >= 6 else "open"

        number = self._pr_number(pr_url)
        if number is None:
            return None
        response = self._http.get(self._url(f"/pulls/{number}"))
        response.raise_for_status()
        payload = response.json()
        return "merged" if payload.get("merged_at") else payload.get("state")

    def pr_checks(self, pr_url: str) -> dict[str, Any]:
        """Independent verification: what the repository's own CI says.

        Returns ``{"conclusion": ..., "failing": [...], "head_sha": ...}`` where
        conclusion is one of:

          none      the head commit has no check runs at all
          pending   at least one check run has not completed
          success   every completed check run passed or was neutral/skipped
          failure   at least one check run failed
        """
        if self.settings.demo_mode:
            first_seen = self._mock_pr_seen.setdefault(pr_url, time.time())
            elapsed = time.time() - first_seen
            return {
                "conclusion": "success" if elapsed >= 3 else "pending",
                "failing": [],
                "head_sha": "demo-head-sha",
            }

        number = self._pr_number(pr_url)
        if number is None:
            return {"conclusion": "none", "failing": [], "head_sha": None}

        pull = self._http.get(self._url(f"/pulls/{number}"))
        pull.raise_for_status()
        head_sha = pull.json().get("head", {}).get("sha")
        if not head_sha:
            return {"conclusion": "none", "failing": [], "head_sha": None}

        runs = self._http.get(
            self._url(f"/commits/{head_sha}/check-runs"), params={"per_page": 100}
        )
        runs.raise_for_status()
        allowed = {
            slug.strip()
            for slug in self.settings.gating_check_apps.split(",")
            if slug.strip()
        }
        check_runs = [
            run
            for run in runs.json().get("check_runs", [])
            if not allowed or (run.get("app") or {}).get("slug") in allowed
        ]
        if not check_runs:
            return {"conclusion": "none", "failing": [], "head_sha": head_sha}

        if any(run.get("status") != "completed" for run in check_runs):
            return {"conclusion": "pending", "failing": [], "head_sha": head_sha}

        # neutral and skipped are not failures; anything else that is not a pass is.
        failing = [
            run.get("name", "unnamed check")
            for run in check_runs
            if run.get("conclusion") not in {"success", "neutral", "skipped"}
        ]
        return {
            "conclusion": "failure" if failing else "success",
            "failing": failing,
            "head_sha": head_sha,
        }
