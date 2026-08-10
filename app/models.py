from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands_run: list[str] = Field(default_factory=list)
    all_passed: bool
    evidence: str = Field(default="", max_length=2000)


class DevinVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["remediated", "no_change_needed", "blocked"]
    summary: str = Field(max_length=1200)
    pr_url: str | None = None
    files_changed: list[str] = Field(default_factory=list)
    verification: Verification
    risk: Literal["low", "medium", "high"] = "medium"
    blocked_reason: str = Field(default="", max_length=800)
    human_review_notes: str = Field(default="", max_length=1200)
