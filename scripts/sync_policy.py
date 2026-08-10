#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.devin import DevinClient
from app.policy import load_knowledge, load_playbook


def main() -> int:
    settings.validate()
    playbook = load_playbook()
    knowledge = load_knowledge()
    playbook_id, knowledge_id = DevinClient(settings).sync_policy(playbook, knowledge)
    mode = "demo adapter" if settings.demo_mode else "Devin v3"
    print(f"Synced through {mode}")
    print(f"Playbook: {playbook_id}")
    print(f"Knowledge: {knowledge_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
