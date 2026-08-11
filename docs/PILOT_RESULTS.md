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
| Balance after run 1 | |
| ACUs consumed (from API) | |
| **Derived $/ACU** | |

## Per-issue evidence

| | Issue #2 — `is_host_up` | Issue #1 — YAML loader |
|---|---|---|
| Issue URL | https://github.com/harry1174/superset/issues/2 | https://github.com/harry1174/superset/issues/1 |
| Class / severity | reliability / medium | hardening / low |
| Triggered at | | |
| Devin session URL | | |
| Agent claimed a PR at | | |
| PR URL | | |
| CI run URL | | |
| CI confirmed at | | |
| Merged at | | |
| ACUs consumed | | |
| Trigger → CI-verified (min) | | |
| CI green first attempt | | |
| Outcome | | |

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
| PR URL | |
| Failing check | |
| Task state after adjudication | |
| Counted as an agent overclaim | |

## What this pilot does not show

- Throughput. Two issues support no rate.
- Reduced vulnerabilities, incidents or regressions. None were measured.
- Reviewer rework. Both pull requests were reviewed by their own author.
- Generalisation. One repository, one playbook, one issue class each.
