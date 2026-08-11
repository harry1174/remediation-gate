from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, "") or default)


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, "") or default)


@dataclass
class Settings:
    demo_mode: bool = field(default_factory=lambda: _bool("DEMO_MODE", True))

    devin_api_key: str = field(default_factory=lambda: os.getenv("DEVIN_API_KEY", ""))
    devin_org_id: str = field(default_factory=lambda: os.getenv("DEVIN_ORG_ID", ""))
    devin_base_url: str = field(
        default_factory=lambda: os.getenv("DEVIN_BASE_URL", "https://api.devin.ai")
    )

    github_token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    github_repo: str = field(
        default_factory=lambda: os.getenv("GITHUB_REPO", "harry1174/superset")
    )
    github_api: str = field(
        default_factory=lambda: os.getenv("GITHUB_API", "https://api.github.com")
    )
    github_webhook_secret: str = field(
        default_factory=lambda: os.getenv("GITHUB_WEBHOOK_SECRET", "demo-secret")
    )
    trigger_label: str = field(
        default_factory=lambda: os.getenv("TRIGGER_LABEL", "devin:autofix")
    )

    max_acu_per_task: int = field(default_factory=lambda: _int("MAX_ACU_PER_TASK", 10))
    max_concurrent_sessions: int = field(
        default_factory=lambda: _int("MAX_CONCURRENT_SESSIONS", 2)
    )
    daily_acu_budget: int = field(default_factory=lambda: _int("DAILY_ACU_BUDGET", 40))
    poll_interval_seconds: int = field(
        default_factory=lambda: _int("POLL_INTERVAL_SECONDS", 10)
    )
    session_timeout_minutes: int = field(
        default_factory=lambda: _int("SESSION_TIMEOUT_MINUTES", 45)
    )
    sync_policy_on_boot: bool = field(
        default_factory=lambda: _bool("SYNC_POLICY_ON_BOOT", True)
    )
    background_enabled: bool = True

    # Devin's verdict is a claim; the repository's own checks are the evidence.
    # With this off, a task is promoted on the agent's self-report alone and the
    # dashboard says so.
    # Pinned rather than inherited from the organization default, so behaviour
    # and unit economics cannot change outside this application. Recorded per
    # task so a cost figure can be reproduced later.
    devin_mode: str = field(default_factory=lambda: os.getenv("DEVIN_MODE", "normal"))

    require_ci_checks: bool = field(
        default_factory=lambda: _bool("REQUIRE_CI_CHECKS", True)
    )
    # Which apps' check-runs are allowed to satisfy the gate. Restricted to the
    # repository's own CI on purpose: Devin Review also comments on these pull
    # requests, and one Devin agent approving another Devin agent's work is not
    # the independent confirmation this gate exists to obtain. It happens to
    # post a commit status rather than a check-run today, so it is excluded
    # either way — this makes that deliberate instead of lucky.
    gating_check_apps: str = field(
        default_factory=lambda: os.getenv("GATING_CHECK_APPS", "github-actions")
    )
    checks_grace_minutes: int = field(
        default_factory=lambda: _int("CHECKS_GRACE_MINUTES", 15)
    )

    acu_unit_cost_usd: float = field(
        default_factory=lambda: _float("ACU_UNIT_COST_USD", 2.25)
    )
    # Devin publishes no per-ACU price, so the default above is a placeholder.
    # Until someone measures it against a real account balance, every dollar
    # figure derived from it says so on the dashboard.
    acu_unit_cost_verified: bool = field(
        default_factory=lambda: _bool("ACU_UNIT_COST_VERIFIED", False)
    )
    # What the same remediation would cost a human end to end: reproduce,
    # navigate the repo, implement, test, raise the PR. Nobody knows this
    # number precisely, so it is carried as a range and every figure derived
    # from it is reported as a planning scenario rather than a saving.
    baseline_human_hours_low: float = field(
        default_factory=lambda: _float("BASELINE_HUMAN_HOURS_LOW", 1.0)
    )
    engineer_hours_per_merged_pr: float = field(
        default_factory=lambda: _float("ENGINEER_HOURS_PER_MERGED_PR", 2.5)
    )
    baseline_human_hours_high: float = field(
        default_factory=lambda: _float("BASELINE_HUMAN_HOURS_HIGH", 4.0)
    )
    engineer_hourly_cost_usd: float = field(
        default_factory=lambda: _float("ENGINEER_HOURLY_COST_USD", 110)
    )
    db_path: str = field(
        default_factory=lambda: os.getenv("DB_PATH", "data/remediation.db")
    )

    def validate(self) -> None:
        if self.demo_mode:
            return
        missing = [
            name
            for name, value in {
                "DEVIN_API_KEY": self.devin_api_key,
                "DEVIN_ORG_ID": self.devin_org_id,
                "GITHUB_TOKEN": self.github_token,
                "GITHUB_WEBHOOK_SECRET": self.github_webhook_secret,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"live mode requires: {', '.join(missing)}")

    @property
    def devin_org_url(self) -> str:
        return f"{self.devin_base_url}/v3/organizations/{self.devin_org_id}"


settings = Settings()
