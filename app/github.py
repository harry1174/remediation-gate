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


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


class GitHubClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
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
            log.warning("could not comment on issue %s: %s", issue_number, exc)

    def add_labels(self, issue_number: int, labels: list[str]) -> None:
        if self.settings.demo_mode:
            return
        try:
            response = self._http.post(
                self._url(f"/issues/{issue_number}/labels"), json={"labels": labels}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("could not label issue %s: %s", issue_number, exc)

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

    def pr_state(self, pr_url: str) -> str | None:
        if self.settings.demo_mode:
            first_seen = self._mock_pr_seen.setdefault(pr_url, time.time())
            return "merged" if time.time() - first_seen >= 8 else "open"

        parsed = urlparse(pr_url)
        parts = parsed.path.strip("/").split("/")
        if parsed.netloc != "github.com" or len(parts) != 4 or parts[2] != "pull":
            log.warning("ignoring malformed PR URL: %s", pr_url)
            return None
        repo = f"{parts[0]}/{parts[1]}"
        if repo.lower() != self.settings.github_repo.lower():
            log.warning("ignoring PR outside configured repository: %s", pr_url)
            return None
        response = self._http.get(self._url(f"/pulls/{parts[3]}"))
        response.raise_for_status()
        payload = response.json()
        return "merged" if payload.get("merged_at") else payload.get("state")
