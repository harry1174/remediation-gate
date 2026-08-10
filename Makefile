.PHONY: help up down demo test policy seed logs

help:
	@echo "make up      Build and start the service"
	@echo "make demo    Replay the two signed issue-label webhooks"
	@echo "make test    Run the focused test suite in Docker"
	@echo "make policy  Sync the Playbook and Knowledge note to Devin"
	@echo "make seed    Create the two real issues in the Superset fork"

up:
	docker compose up --build -d
	@echo "dashboard: http://localhost:8000"

down:
	docker compose down

demo: up
	docker compose exec -T remediation-gate python scripts/demo.py

test:
	docker compose run --rm --entrypoint "" remediation-gate python -m pytest tests -q

policy:
	docker compose run --rm --entrypoint "" remediation-gate python scripts/sync_policy.py

seed:
	docker compose run --rm --entrypoint "" remediation-gate python scripts/seed_issues.py

logs:
	docker compose logs -f remediation-gate
