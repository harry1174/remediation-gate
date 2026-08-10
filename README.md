# Remediation Gate

[![test](https://github.com/harry1174/remediation-gate/actions/workflows/test.yml/badge.svg)](https://github.com/harry1174/remediation-gate/actions/workflows/test.yml)

An event-driven control plane that turns an approved Apache Superset issue into
a verified pull request using Devin as the engineer doing the work.

The workflow is deliberately narrow: a GitHub label is the approval boundary,
one Devin Playbook is the remediation policy, one Knowledge note carries
repository conventions, and only a typed verdict with passing verification can
advance to `pr_open`.

```text
GitHub issue labeled devin:autofix
  -> signed webhook + repository allowlist
  -> idempotent SQLite task
  -> concurrency and ACU admission policy
  -> Devin session + Playbook + Knowledge + structured output
  -> verified PR or explicit handoff
  -> merge tracking and leadership metrics
```

## What is real

- Superset fork: https://github.com/harry1174/superset
- Findings are pinned to fork commit `916c50284b8ca90d698172db01168c47ffec1e22`.
- The issue contracts name exact files, reproductions, verification commands,
  and non-goals.
- Devin v3 requests attach a Playbook, Knowledge note, repository, ACU cap,
  tags, and a JSON Schema.
- GitHub HMAC verification, repository allowlisting, task idempotency, and the
  verification gate are exercised by tests.

The deterministic demo adapter is only for evaluating the orchestration without
credentials. It is visibly marked `Demo - no ACUs spent`; its session and PR
links are not evidence of live remediation. Replace the links below after the
live run:

- Security issue: https://github.com/harry1174/superset/issues/1
- Reliability issue: https://github.com/harry1174/superset/issues/2
- Live Devin sessions: pending credentials
- Verified PRs: pending credentials

## Run the deterministic demo

No credentials are required.

```bash
cp .env.example .env
make demo
open http://localhost:8000
```

`make demo` waits for the container to report healthy before replaying the
webhooks, so it is safe to run from a cold start. The equivalent long form is:

```bash
docker compose up --build -d --wait
docker compose exec remediation-gate python scripts/demo.py --duplicate
```

The tasks progress from queued to session, verified PR, and merged in roughly
15 seconds. The duplicate delivery returns `duplicate: true` and does not create
a second task.

```bash
make test
make down
```

## Run live

### 1. Create one Devin service user

Use one organization-scoped v3 service-user key (`cog_...`) with permissions to
use, view, and manage organization sessions, plus manage organization Playbooks
and Knowledge. The same key is used for every Devin endpoint; Playbooks do not
need separate API keys.

### 2. Configure environment

```bash
cp .env.example .env
```

Set:

```dotenv
DEMO_MODE=false
DEVIN_API_KEY=cog_...
DEVIN_ORG_ID=org-...
GITHUB_TOKEN=github_pat_...
GITHUB_REPO=harry1174/superset
GITHUB_WEBHOOK_SECRET=<openssl rand -hex 32>
```

The GitHub token needs repository metadata read, issues read/write, and pull
requests read. Devin's GitHub integration must separately be allowed to access
`harry1174/superset` so the agent can clone and push branches.

### 3. Sync policy and seed issues

```bash
set -a; source .env; set +a
make policy
make seed
```

`make seed` intentionally omits `devin:autofix`. Add the label during the demo;
that action is the explicit authorization to spend ACUs.

### 4. Expose the webhook

Start the application and expose port 8000 using a tunnel. Configure a GitHub
Issues webhook at `/webhooks/github` with the same secret. Subscribe only to
Issues events.

```bash
make up
# ngrok http 8000
```

Add `devin:autofix` to one seeded issue. The application comments with the
session URL, polls Devin to a terminal state, validates the structured output,
and comments again only after verification passes.

## State and success model

```text
queued -> dispatching -> dispatched -> running -> pr_open -> merged
                                      |
                                      +-> blocked
                                      +-> no_change_needed
                                      +-> failed_verification
                                      +-> failed / timed_out
```

A URL is not success. `pr_open` requires all of the following:

- `outcome` is `remediated`;
- the PR belongs to the configured fork;
- at least one verification command was recorded;
- `verification.all_passed` is true;
- the verdict satisfies the Pydantic/JSON Schema contract.

The dashboard reports cost per merged PR only after a merge. Value estimates are
labeled assumptions. Failed verification can retain a PR URL for review, but it
never enters the verified funnel.

## Project layout

```text
app/
  main.py          signed GitHub ingress and HTTP reporting
  orchestrator.py  admission, session lifecycle, verdict gate, PR tracking
  devin.py         Devin v3 and deterministic demo adapters
  github.py        GitHub API and HMAC boundary
  store.py         SQLite task state and event journal
  metrics.py       verified and merged-only operating metrics
playbooks/         durable remediation procedure
knowledge/         standing Superset repository conventions
issues/            reproducible issue contracts
scripts/           policy sync, issue seeding, signed demo replay
tests/             security, idempotency, budget, and metric invariants
```

## Why Devin is the core primitive

The application never edits source code. It controls authorization, policy,
spend, state, and evidence. Devin performs the work that a scanner or codemod
cannot reliably do: inspect a large unfamiliar repository, reproduce a finding,
choose the smallest safe change, add a regression test, iterate on failures,
open a pull request, or refuse the task when the contract is unsafe.

## Production extensions

- Route `blocked` tasks to the owning team rather than a generic label.
- Replace SQLite with Postgres and a worker queue for multiple repositories.
- Reconcile the crash window after remote session creation by searching Devin
  sessions using the task tag before retrying.
- Track reviewer-requested changes and report merge-without-rework rate.
- Add scanner adapters only after finding-level fingerprinting is implemented.
