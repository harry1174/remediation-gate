# Remediation Gate

[![test](https://github.com/harry1174/remediation-gate/actions/workflows/test.yml/badge.svg)](https://github.com/harry1174/remediation-gate/actions/workflows/test.yml)

An event-driven control plane that turns an approved Apache Superset issue into
a verified pull request using Devin as the engineer doing the work.

The workflow is deliberately narrow: a GitHub label is the approval boundary,
one Devin Playbook is the remediation policy, one Knowledge note carries
repository conventions, and a pull request is only counted as verified once the
repository's own CI agrees with the agent.

```text
GitHub issue labeled devin:autofix
  -> signed webhook + repository allowlist
  -> idempotent SQLite task
  -> concurrency and ACU admission policy
  -> Devin session + Playbook + Knowledge + structured output
  -> agent claims a verified PR
  -> repository check-runs confirm it, or contradict it
  -> merge tracking and leadership metrics
```

## The agent's claim is not the evidence

Devin returns a typed verdict including `verification.all_passed`. That is a
claim about commands it says it ran. Accepting it as proof would make "verified
PR" mean "the agent graded its own homework", which is the first thing a
skeptical reviewer will test.

So the gate has two halves. A task stops at `agent_verified_pr` on the verdict
alone. It is promoted to `verified_pr` only when the `remediation-verify`
check-run on the fork is green. If CI contradicts the agent, the task becomes
`failed_verification`, the issue is handed back with `devin:needs-human`, and it
is counted in its own failure bucket.

The gap between the two is reported on the dashboard as **agent overclaims**.
That number is the honest defect rate of the Playbook, and it is the only way to
tell whether editing the Playbook actually improved anything. Sessions are
disposable; the Playbook is the asset that accumulates value, and this is how you
measure it.

`remediation-verify` is a purpose-built fast lane, not Superset's full CI: it
runs only the commands the issue contract's `## Verification` section names,
against only the files the pull request touched, and it fails a PR that adds a
lint suppression or ships without a regression test. The fork's 45 inherited
upstream workflows are disabled, so the check-run the orchestrator polls is
unambiguous. This is the lane a team would give an agent — say so, rather than
implying the agent cleared Apache's entire build.

## What is real

- Superset fork: https://github.com/harry1174/superset
- Findings are pinned to fork commit `916c50284b8ca90d698172db01168c47ffec1e22`.
- The issue contracts name exact files, reproductions, verification commands,
  and non-goals.
- Devin v3 requests attach a Playbook, Knowledge note, repository, ACU cap,
  tags, and a JSON Schema.
- GitHub HMAC verification, repository allowlisting, task idempotency, the
  verification gate, and the CI gate are exercised by tests.

The deterministic demo adapter is only for evaluating the orchestration without
credentials. It is visibly marked `Demo - no ACUs spent`; its session and PR
links are not evidence of live remediation.

- Hardening issue: https://github.com/harry1174/superset/issues/1
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

The GitHub token needs repository metadata read, issues read/write, pull
requests read, and **checks read** — the CI gate reads the check-runs on the
pull request head commit, and without that permission every verified pull
request stalls waiting for a confirmation it cannot see. Devin's GitHub
integration must separately be allowed to access `harry1174/superset` so the
agent can clone and push branches.

The fork's 45 inherited upstream workflows are disabled so that
`remediation-verify` is the only check-run on an agent's pull request. If you
fork afresh, disable them (Actions tab, or
`PUT /repos/{owner}/{repo}/actions/workflows/{id}/disable`) before the first
run, or the gate will be adjudicating Apache's CI rather than yours.

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
queued -> dispatching -> dispatched -> running -> agent_verified_pr -> verified_pr -> merged
                                      |                     |
                                      |                     +-> failed_verification  (CI disagreed)
                                      |                     +-> blocked              (no checks reported)
                                      |                     +-> timed_out            (checks never finished)
                                      +-> blocked
                                      +-> no_change_needed
                                      +-> failed_verification
                                      +-> failed / timed_out
```

A URL is not success, and neither is the agent's word. Reaching
`agent_verified_pr` requires all of the following:

- `outcome` is `remediated`;
- the PR belongs to the configured fork;
- at least one verification command was recorded;
- `verification.all_passed` is true;
- the verdict satisfies the Pydantic/JSON Schema contract.

Reaching `verified_pr` requires one more thing that the agent does not control:
every completed check-run on the PR head commit passed. A pull request that
fails this step keeps its URL for review but is counted as a failure, never as a
partial win — an automation that opens plausible pull requests nobody trusts
moves the cost from writing the fix to reviewing a fix you disbelieve.

The dashboard reports cost per merged PR only after a merge, withholds rates
until at least five tasks have resolved, and labels every value estimate as an
assumption.

## Business impact

The problem is capacity allocation, not capability. Low- and medium-severity
remediation work accumulates because each item needs reproduction, repository
navigation, implementation, testing and PR preparation — and almost never
justifies interrupting roadmap work. Remediation Gate converts policy-approved
issues into independently verified pull requests while engineers keep control of
both ends: which issues are eligible, and what gets merged.

The dashboard is split into two panels that are never mixed.

**Measured** — observed from this pipeline, no modelling:

| | |
|---|---|
| Trigger to CI-verified | wall-clock from label to green check-run, reported beside the agent's own claim time so the gap is visible |
| Cost per merged PR | every attempted session's spend, including failures, over merged output |
| Agent overclaims | how often the agent said verified and CI disagreed |
| Blocked / failed / needs-human | with a failure taxonomy |

Agent overclaim rate is the one to watch. It is the only *measured* quality
number here, it answers the question a VP actually asks first — how do I know
these pull requests are not garbage — and it is the Playbook's defect rate, so it
is the number you drive down by editing a document.

**Modeled** — arithmetic on inputs nobody measured, shown as a conservative /
base / upside band rather than a point estimate, because the uncertainty lives
entirely in the human baseline and pretending otherwise invites an argument
about a number that was never observed.

Deliberately not claimed: reduced vulnerabilities, incidents, or regressions.
This pilot measures none of them. Throughput is the proposed mechanism, not an
observed result — two issues support no throughput statement.

Language that survives scrutiny:

> In this pilot, Remediation Gate converted **X** policy-approved issues into
> **Y** CI-verified pull requests, of which **Z** were merged. Median trigger to
> CI-verified time was **N** minutes and total usage was **A** ACUs. Those are
> observed. The capacity and dollar figures are configurable planning scenarios,
> not savings we have banked.

Two honesty notes for anyone reproducing this. The ACU unit cost is a
placeholder — it is not a public figure, so confirm it against your own account
before quoting any dollar amount. And human-touch minutes, where recorded, are a
single self-timed observation by the author of the system, which is why they sit
in the evidence table rather than on the dashboard.

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
