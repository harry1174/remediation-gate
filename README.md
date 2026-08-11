# Remediation Gate

[![test](https://github.com/harry1174/remediation-gate/actions/workflows/test.yml/badge.svg)](https://github.com/harry1174/remediation-gate/actions/workflows/test.yml)

An event-driven control plane that turns an approved Apache Superset issue into
a verified pull request using Devin as the engineer doing the work.

**Two issues, two Devin sessions, two CI-verified pull requests, both merged, in
a median of 13.6 minutes for $3.00 total.** No pull request was edited by hand,
and none was counted as verified on the agent's own say-so.

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

## What actually happened

Two issues in a fork of Apache Superset, each triggered by a human adding
`devin:autofix`. Neither pull request was edited by hand.

| | Issue #2 — `is_host_up` | Issue #1 — YAML loader |
|---|---|---|
| Issue | [#2](https://github.com/harry1174/superset/issues/2) reliability / medium | [#1](https://github.com/harry1174/superset/issues/1) hardening / low |
| Devin session | [`9eb71c32`](https://app.devin.ai/sessions/9eb71c32f7df4daa9b825e939c16517f) | [`77978d24`](https://app.devin.ai/sessions/77978d245aaf4c2ea64be6d9be726dfe) |
| Pull request | [#4](https://github.com/harry1174/superset/pull/4) | [#5](https://github.com/harry1174/superset/pull/5) |
| CI | lint + targeted tests, green | lint + targeted tests, green |
| Trigger → CI-verified | 15.6 min | 11.6 min |
| Cost | $1.67 | $1.33 |
| Outcome | **merged** | **merged** |

```
triggered 2  →  session 2  →  agent says verified 2  →  CI confirms 2  →  merged 2
```

Median trigger to CI-verified: **11.6 minutes**. Terminal CI contradictions —
final agent claims still disputed by CI after the recovery window: **0 of 3**.
Autonomous CI recoveries: **1**.
Handed back to a human: **0**. A third issue was correctly **refused**. Total
cost across all four runs: **$5.72**, or **$2.86 per merged pull request** —
counting the refusal and the self-repair against merged output rather than
excluding them.

The refusal was the cheapest run at $0.97, which inverts the usual economics of
automation: normally the failure mode is the expensive one, because it wastes
compute *and* produces something a human has to read and reject. The
self-repairing run was the dearest at $1.75, and bought a diff better than
master.

Rates are withheld below five resolved tasks, so these stay as counts — two
results do not make a percentage.

**Corroboration.** Devin's own analytics, which this project can only read,
reports 2 sessions created via API, 2 pull requests created and 2 merged over
the same window, and zero sessions started by a human. Every other figure here
comes from a SQLite database this project owns; that one does not.

**The rejection path has been exercised, by fault injection.** Both real pull
requests passed first time, so `failed_verification` had never executed outside
a unit test. [PR #6](https://github.com/harry1174/superset/pull/6) was written
**by hand** — no Devin session was involved — to add `# noqa: F401` and silence
a linter, the shortcut every issue contract forbids. It was paired with a
**synthetic verdict** claiming `all_passed: true`, standing in for an agent that
overclaims.

Everything downstream of that claim is real: `ruff check` went green, the
added-suppression step failed, and the orchestrator fetched the head SHA, read
the real check-runs, refused to promote the task, and recorded it as an
overclaim. Run against a scratch database, so the figures above are untouched.

To be explicit about what this is and is not evidence of: it demonstrates that
this service's rejection path works against real GitHub data. It says nothing
about whether Devin overclaims — across two real remediations, it did not.

**And it repairs its own red builds, unprompted.**
[Issue #8](https://github.com/harry1174/superset/issues/8) — a regex accepting
`"1 day laterago"` as valid — produced [PR #11](https://github.com/harry1174/superset/pull/11).
Its first commit carried a pre-existing `# noqa: E501` forward onto the line it
was editing, and the verification lane rejected it. About two minutes later Devin
pushed a second commit splitting the regex across three lines so the suppression
was no longer needed at all, and CI went green. Nobody asked it to: it watches
its own pull requests independently of session state.

The result is better than master, which had carried that suppression before any
of this started. It also exposed a race here: failing a task the instant a check
goes red would have terminalised work the agent was actively repairing, and
terminal states are never revisited. A red build is now held for a settling
window, and a new head commit resets it.

**And it can refuse.** [Issue #7](https://github.com/harry1174/superset/issues/7)
asks whether a `# noqa: S603` can be removed from `is_host_up`. It cannot — the
rule fires on the `subprocess` call itself, and every escape route is a stated
non-goal. Devin returned **`blocked`** in 3.6 minutes without opening a pull
request, having read `requirements/development.txt` to find the pinned ruff
version rather than assuming it, and named the exact constraint that blocked it.

That refusal also caught a defect here: this project's verification lane
installed ruff 0.16.2 while the repository pins 0.9.7, so it had been
adjudicating pull requests against a different linter than the repository uses.
Now pinned to match.

A codemod cannot decline. That is the clearest evidence in this pilot that the
work between an issue and an outcome needs judgement, not transformation.

**On cost.** Devin reports `acus_consumed: 0.0` on this account — from the
session object, `/consumption/daily`, and `/consumption/daily/sessions/{id}`
alike, because it bills in credits. The dashboard therefore withholds
ACU-derived cost rather than publishing a zero. The $3.00 is a measured balance
delta, which is a better figure anyway.

The deterministic demo adapter exists only so the orchestration can be evaluated
without credentials. It is marked `Demo — no ACUs spent`, and its session and PR
links are not evidence of anything.

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

## The decisions the brief didn't make for you

"Build an event-driven automation that remediates issues" leaves every operating
question open. Those questions are the actual design work, so they are answered
explicitly rather than left implicit in the code.

| Question | Decision | Where it lives |
|---|---|---|
| What authorizes spending money? | A human adding `devin:autofix` to a triaged issue. It reuses an approval step every team already has, so nobody learns a new one. | `main.py` webhook filter |
| What is a duplicate? | One task per `repo#issue`, claimed with `INSERT OR IGNORE`. A redelivered webhook, a label removed and re-added, and an overlapping scan all collapse to one session. | `store.claim_task` |
| How much can one task spend? | A per-session ACU cap plus a daily budget, checked at admission rather than after the fact. The label is the authorization; the caps are its blast radius. | `orchestrator.dispatch` |
| What counts as done? | Not a PR URL. Not the agent's word. Every completed check-run on the PR head must pass. | `_reconcile_checks` |
| Who decides if the fix is even right? | Devin. It is instructed to return `no_change_needed` if the finding doesn't reproduce, and `blocked` if the safe fix needs a product decision. | Playbook `## Specifications` |
| When does it stop? | Session timeout, CI grace window, and a cap on dispatch retries. Every path terminates. | `Settings`, `TERMINAL_STATES` |
| What is ambiguous work turned into? | A contract with observed problem, reproduction, scope, acceptance criteria, verification commands and non-goals. The non-goals are what keep diffs reviewable. | `issues/findings.json` |
| What if the policy is wrong? | It's a Devin Playbook, edited in the web app by the customer's tech lead — not a redeploy of this service. | `policy.py` |

The state machine is the residue of those decisions:

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

## What the live runs taught us

Two things surfaced against a real agent that no amount of mock testing would
have found, and both sharpened the design rather than patching around it.

**Instructing an agent is not the same as controlling it.** Both sessions
produced a valid structured verdict, opened a pull request — and then parked in
`waiting_for_user` instead of exiting. `structured_output_required` does not make
a session terminate. The obvious fix was policy: Playbook step 9 was amended to
say *end the session after returning the verdict*. The next run parked anyway.

Policy successfully governed everything Devin *produced* — the diff, the
regression tests, removing rather than relocating a lint suppression, respecting
every non-goal. It did not change when the session ended. What fixed it was the
orchestrator acting on a verdict the moment one exists, regardless of what the
session does next. That gap is the entire argument for a control plane.

**Silent degradation is worse than failure.** A missing `Issues: write`
permission produced a 403 on every status comment in the first run. The
pipeline correctly survived it — the remediation completed and the pull request
landed, because Devin pushes through its own integration rather than this
service's token. But the only trace was a log line nobody was reading, and the
issue went through an entire remediation with no visible sign of the automation.
Failed writes still never fail a remediation; they now surface in `/healthz`, and
`make preflight` probes the permission by writing a comment and deleting it,
which is the only honest check available for a fine-grained token.

## Production extensions

- Route `blocked` tasks to the owning team rather than a generic label.
- Replace SQLite with Postgres and a worker queue for multiple repositories.
- Reconcile the crash window after remote session creation by searching Devin
  sessions using the task tag before retrying.
- Track reviewer-requested changes and report merge-without-rework rate.
- Add scanner adapters only after finding-level fingerprinting is implemented.
