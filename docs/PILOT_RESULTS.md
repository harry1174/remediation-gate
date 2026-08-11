# Pilot results

Everything here is filled in from a real run. Empty cells stay empty rather than
being estimated — an unfilled row is a fact about what was not measured.

## Deriving the ACU rate

Devin publishes no per-ACU price, so it is measured rather than quoted. Record
the account balance immediately before and after a session; the API reports the
ACUs that session consumed.

```
rate = (balance_before - balance_after) / acus_consumed
```

Until that is done, `ACU_UNIT_COST_USD` is a placeholder and the dashboard says
so in as many words. Once measured, set the value and
`ACU_UNIT_COST_VERIFIED=true` in `.env`, and the caveat disappears.

| | |
|---|---|
| Balance before run 1 | $28.35 |
| Balance after run 1 | $26.68 |
| Balance after run 2 | $25.35 |
| ACUs consumed (from API) | 0.0 — **not reported on this account** |
| **Derived $/ACU** | n/a — not reported. Measured cost: **$1.67** run 1, **$1.33** run 2, **$3.00 total for two verified PRs** |

## Per-issue evidence

Both issues were triggered by a human adding `devin:autofix`. Neither PR was
edited by hand.

| | Issue #2 — `is_host_up` | Issue #1 — YAML loader |
|---|---|---|
| Issue | [#2](https://github.com/harry1174/superset/issues/2) | [#1](https://github.com/harry1174/superset/issues/1) |
| Class / severity | reliability / medium | hardening / low |
| Devin session | [`9eb71c32`](https://app.devin.ai/sessions/9eb71c32f7df4daa9b825e939c16517f) | [`77978d24`](https://app.devin.ai/sessions/77978d245aaf4c2ea64be6d9be726dfe) |
| Pull request | [#4](https://github.com/harry1174/superset/pull/4) | [#5](https://github.com/harry1174/superset/pull/5) |
| CI result | lint 56s + tests 1m43s, both green | lint 56s + tests 1m44s, both green |
| Trigger → CI-verified | 15.6 min | **11.6 min** |
| CI green first attempt | yes | yes |
| Agent overclaim | no | no |
| Suppressions added | none | none |
| Outcome | **merged** | **verified_pr** |
| Human intervention | one nudge to emit the verdict | **none** |

Aggregate: 2 triggered, 2 sessions, 2 agent-claimed PRs, 2 CI-verified, 1 merged,
0 overclaims, 0 handed back. Median trigger to CI-verified: **13.6 min**.

Rates are withheld below five resolved tasks, so these stay as counts.

### Corroboration

Devin's own analytics, which this project can only read, reports **2 sessions
created via API, 2 pull requests created, 1 merged** over the same window — and
zero sessions started by a human. That is independent of the SQLite database
every other figure here comes from.

## Human time

Self-timed by the author of the system, n=1. Recorded because a cost model with
no human-side measurement is circular; kept off the dashboard because one
self-timed observation by an interested party is not a KPI.

| | Issue #2 | Issue #1 |
|---|---|---|
| Triage / writing the contract | | |
| Reviewing the PR | | |
| Merging | | |

## Fault injection

Evidence that the CI gate rejects rather than rubber-stamps. A deliberately
failing pull request, adjudicated by the same code path as a real one.

| | |
|---|---|
| PR URL | [#6](https://github.com/harry1174/superset/pull/6) — closed unmerged |
| What it does | adds `# noqa: F401` to silence an unused import |
| `ruff check` | **passes** — the suppression works |
| Failing check | `lint changed files`, on the added-suppression step |
| Task state after adjudication | `failed_verification` |
| Reason recorded | "CI checks failed after the agent reported success: lint changed files" |
| Counted as an agent overclaim | **yes** — 1/1, bucket `CI contradicted the agent` |

Run against a scratch database so the pilot figures above are untouched, and
hand-written rather than agent-produced — the purpose is to exercise the gate,
not to fake a session.

Both real pull requests passed CI first time, so without this the gate had only
ever been observed accepting. The failure mode chosen is the meaningful one: the
linter was silenced rather than satisfied, `ruff check` went green, and the gate
caught the silencing.

## What this pilot does not show

- Throughput. Two issues support no rate.
- Reduced vulnerabilities, incidents or regressions. None were measured.
- Reviewer rework. Both pull requests were reviewed by their own author.
- Generalisation. One repository, one playbook, one issue class each.

## What the runs taught us

Two failure modes surfaced live that no amount of mock testing would have found.

**`structured_output_required` does not make a session exit.** Both runs ended
with Devin producing a valid verdict and then parking in `waiting_for_user`.
Reconciliation originally checked session status before looking for a verdict, so
run one sat with finished, merge-ready work behind a state machine waiting for an
exit that never came.

Instructing the agent did not fix it. Playbook step 9 was amended to say end the
session after returning the verdict; run two parked anyway. Policy successfully
governs what Devin *produces* — the diff, the tests, the refusal to add a
replacement suppression — but did not change when the session terminates. The
orchestrator acting on a verdict the moment one exists is what fixed it.

That gap is the argument for the control plane: instructing an agent is not the
same as controlling it.

**A permission gap degraded silently.** A 403 on the status comment produced a
log warning nobody was watching, and run one completed with no visible trace of
the automation on the issue. Failed writes still never fail a remediation, but
they now surface in `/healthz`, and preflight probes `Issues: write` by posting a
comment and deleting it — the only honest check, since fine-grained tokens expose
no permission introspection.
