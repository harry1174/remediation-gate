from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .config import Settings, settings as default_settings
from .github import verify_signature
from .metrics import snapshot
from .orchestrator import Orchestrator
from .store import Store


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("api")
DASHBOARD = Path(__file__).parent / "templates" / "dashboard.html"


def _classify(issue: dict[str, Any], trigger_label: str) -> tuple[str, str]:
    labels = {
        str(label.get("name", "")).lower()
        for label in issue.get("labels", [])
        if isinstance(label, dict)
    }
    labels.discard(trigger_label.lower())
    issue_class = next(
        (name for name in ("security", "reliability", "dependency", "quality", "test") if name in labels),
        "quality",
    )
    severity = next(
        (name for name in ("critical", "high", "medium", "low") if name in labels),
        "medium",
    )
    return issue_class, severity


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or default_settings
    active_settings.validate()
    store = Store(active_settings.db_path)
    orchestrator = Orchestrator(active_settings, store)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if active_settings.sync_policy_on_boot:
            try:
                orchestrator.sync_policy()
            except Exception:  # noqa: BLE001
                log.exception("policy sync failed; queued work will not dispatch")
        if active_settings.background_enabled:
            orchestrator.start_background()
        yield
        orchestrator.stop()

    app = FastAPI(title="Remediation Gate", version="1.0.0", lifespan=lifespan)
    app.state.settings = active_settings
    app.state.store = store
    app.state.orchestrator = orchestrator

    @app.post("/webhooks/github")
    async def github_webhook(
        request: Request,
        x_hub_signature_256: str | None = Header(default=None),
        x_github_event: str | None = Header(default=None),
        x_github_delivery: str | None = Header(default=None),
    ) -> JSONResponse:
        raw = await request.body()
        if not verify_signature(
            active_settings.github_webhook_secret, raw, x_hub_signature_256
        ):
            return JSONResponse({"error": "invalid signature"}, status_code=401)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        if x_github_event != "issues" or payload.get("action") != "labeled":
            return JSONResponse({"ignored": "unsupported event"})
        if str(payload.get("label", {}).get("name", "")).lower() != active_settings.trigger_label.lower():
            return JSONResponse({"ignored": "different label"})

        repo = str(payload.get("repository", {}).get("full_name", ""))
        if repo.lower() != active_settings.github_repo.lower():
            return JSONResponse({"error": "repository not allowed"}, status_code=403)
        issue = payload.get("issue") or {}
        if not issue.get("number") or not issue.get("title") or not issue.get("html_url"):
            return JSONResponse({"error": "incomplete issue payload"}, status_code=422)

        issue_class, severity = _classify(issue, active_settings.trigger_label)
        claimed = orchestrator.enqueue(
            repo=repo,
            issue_number=int(issue["number"]),
            issue_url=str(issue["html_url"]),
            issue_title=str(issue["title"]),
            issue_body=str(issue.get("body") or issue["title"]),
            issue_class=issue_class,
            severity=severity,
            source="github_webhook",
            delivery_id=x_github_delivery,
        )
        return JSONResponse({"queued": claimed, "duplicate": not claimed})

    @app.get("/api/metrics")
    def metrics() -> JSONResponse:
        return JSONResponse(snapshot(store, active_settings))

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "demo" if active_settings.demo_mode else "live",
            "policy_ready": bool(orchestrator.playbook_id and orchestrator.knowledge_id),
            "active_tasks": store.active_count(),
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> HTMLResponse:
        return HTMLResponse(DASHBOARD.read_text(encoding="utf-8"))

    return app


app = create_app()
