#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path

import httpx


FINDINGS = Path(__file__).parents[1] / "issues" / "findings.json"


def _payload(number: int, finding: dict[str, str], repo: str, trigger: str) -> dict:
    return {
        "action": "labeled",
        "label": {"name": trigger},
        "repository": {"full_name": repo},
        "issue": {
            "number": number,
            "title": finding["title"],
            "body": finding["body"],
            "html_url": f"https://github.com/{repo}/issues/{number}",
            "labels": [
                {"name": trigger},
                {"name": finding["class"]},
                {"name": finding["severity"]},
            ],
        },
    }


def _post(api: str, secret: str, payload: dict) -> httpx.Response:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return httpx.post(
        f"{api}/webhooks/github",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-Hub-Signature-256": f"sha256={signature}",
        },
        timeout=30,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=os.getenv("API_URL", "http://localhost:8000"))
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPO", "harry1174/superset"))
    parser.add_argument("--secret", default=os.getenv("GITHUB_WEBHOOK_SECRET", "demo-secret"))
    parser.add_argument("--trigger", default=os.getenv("TRIGGER_LABEL", "devin:autofix"))
    parser.add_argument("--duplicate", action="store_true")
    args = parser.parse_args()

    findings = json.loads(FINDINGS.read_text(encoding="utf-8"))
    for number, finding in enumerate(findings, start=1):
        payload = _payload(number, finding, args.repo, args.trigger)
        response = _post(args.api, args.secret, payload)
        response.raise_for_status()
        print(f"#{number} {finding['title']} -> {response.json()}")
        time.sleep(0.5)
    if args.duplicate:
        response = _post(args.api, args.secret, _payload(1, findings[0], args.repo, args.trigger))
        response.raise_for_status()
        print(f"duplicate #1 -> {response.json()}")
    print(f"Dashboard: {args.api}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
