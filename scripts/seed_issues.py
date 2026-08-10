#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.github import GitHubClient


FINDINGS = Path(__file__).parents[1] / "issues" / "findings.json"
LABELS = {
    "devin:autofix": "4A57A8",
    "devin:verified-pr": "168466",
    "devin:needs-human": "B33A3A",
    "security": "B33A3A",
    "reliability": "B56B18",
    "high": "D73A4A",
    "medium": "E3A21A",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trigger",
        action="store_true",
        help="also add devin:autofix; omit this before recording the label trigger",
    )
    args = parser.parse_args()
    if settings.demo_mode:
        raise SystemExit("Set DEMO_MODE=false and configure GITHUB_TOKEN before seeding")

    client = GitHubClient(settings)
    client.ensure_labels(LABELS)
    findings = json.loads(FINDINGS.read_text(encoding="utf-8"))
    for finding in findings:
        labels = [finding["class"], finding["severity"]]
        if args.trigger:
            labels.append(settings.trigger_label)
        issue = client.create_issue(finding["title"], finding["body"], labels)
        print(f"#{issue['number']} {issue['html_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
