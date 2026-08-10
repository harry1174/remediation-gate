from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK_PATH = ROOT / "playbooks" / "remediate-issue.devin.md"
KNOWLEDGE_PATH = ROOT / "knowledge" / "superset.md"


def _frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        raise ValueError(f"missing frontmatter: {path}")
    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            metadata[key.strip()] = value.strip()
    return metadata, match.group(2).strip()


def load_playbook() -> dict[str, str]:
    metadata, body = _frontmatter(PLAYBOOK_PATH)
    macro = metadata.get("macro", "")
    if not re.fullmatch(r"![A-Za-z0-9_-]+", macro):
        raise ValueError("Playbook macro must start with ! and contain only letters, digits, _ or -")
    return {"title": metadata["title"], "macro": macro, "body": body}


def load_knowledge() -> dict[str, str]:
    metadata, body = _frontmatter(KNOWLEDGE_PATH)
    return {
        "name": metadata["name"],
        "trigger": metadata["trigger"],
        "body": body,
    }
