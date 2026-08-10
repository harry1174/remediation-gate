from __future__ import annotations

from typing import Any


def build_prompt(task: dict[str, Any], playbook_attached: bool) -> str:
    fallback = "" if playbook_attached else """
No Playbook was attached. Stop and return `blocked`; remediation policy is unavailable.
"""
    return f"""Remediate the approved GitHub issue below in Apache Superset.

Repository: https://github.com/{task['repo']}
Issue: {task['issue_url']}
Class: {task['issue_class']}
Severity: {task['severity']}

Issue contract:
{task['issue_body'].strip()}

Follow the attached Playbook and Knowledge note. Work from `master`, satisfy the
issue acceptance criteria, run the issue's targeted verification, and open the
pull request against `{task['repo']}` with `Closes #{task['issue_number']}`.
Return the required structured verdict when finished.{fallback}"""
