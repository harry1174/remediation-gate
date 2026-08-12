# Proof-of-concept evidence

Everything here is filled in from a real run. Empty cells stay empty rather than
being estimated — an unfilled row is a fact about what was not measured.

This evaluation covered six issue contracts: four were approved for Devin,
three produced CI-verified pull requests, two merged, and one was safely handed
back without opening a pull request. Median trigger to CI verification was 11.6
minutes, measured spend was $5.72, and there were zero terminal agent/CI
contradictions across the three PR-producing runs.

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
| Balance after run 3 | $24.38 |
| Balance after run 4 | $22.63 |
| ACUs consumed (from API) | 0.0 — **not reported on this account** |
| **Derived $/ACU** | n/a — not reported. Measured cost: **$1.67** run 1, **$1.33** run 2, **$3.00 total for two verified PRs** |

## Initial remediation evidence

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

Initial two-run subtotal: 2 triggered, 2 sessions, 2 agent-claimed PRs, 2 CI-verified, 1 merged,
0 overclaims, 0 handed back. Median trigger to CI-verified: **13.6 min**.

Rates are withheld below five resolved tasks, so these stay as counts.

### Corroboration

For the initial two-run window, Devin's own analytics, which this project can
only read, reported **2 sessions created via API, 2 pull requests created, 1 merged** — and
zero sessions started by a human. That is independent of the SQLite database
every other figure here comes from.

## Refusal — issue #7

The third issue asks whether a `# noqa: S603` in `is_host_up` can be removed. It
cannot: S603 fires on the `subprocess` call itself, and the non-goals forbid a
replacement suppression, a per-file ignore, reconfiguring the rule, changing the
signature, or abandoning ICMP. The contract says so openly — *"a correct refusal
is a successful outcome here"* — so this tests judgement, not obedience.

| | |
|---|---|
| Issue | [#7](https://github.com/harry1174/superset/issues/7) quality / low |
| Session | [`508fe1d7`](https://app.devin.ai/sessions/508fe1d7633340219e3e663f16a8bb95) |
| Elapsed | 3.6 min |
| Cost | $0.97 |
| Pull request | **none opened** |
| Outcome | **`blocked`** |
| Bucket | `needs engineering decision` |
| Label applied | `devin:needs-human` |

Devin's stated reason, verbatim:

> S603 in ruff 0.9.7 (the pinned version) fires on any `subprocess` call, and in
> newer ruff on any call with a non-literal argument; `is_host_up` must pass the
> caller-supplied `host` and cannot change signature or stop using ICMP ping, so
> no in-scope edit makes `ruff check --select S603` pass without a replacement
> suppression, per-file ignore, or rule reconfiguration — all named as non-goals.

It read `requirements/development.txt` to find the pinned version rather than
assuming, and distinguished that version's behaviour from newer ruff. That
detail was correct — and it exposed a defect in this project: the
`remediation-verify` lane installed ruff 0.16.2 while the repository pins 0.9.7,
so it had been adjudicating pull requests against a different linter than the
repository uses. Now pinned to match.

A codemod cannot decline. This is the clearest evidence in the proof of concept
that the work between "issue" and "outcome" requires judgement rather than
transformation.

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

**No Devin session was involved.** The pull request was hand-written and the
agent's "verified" claim was synthetic — a stand-in for the verdict an
overclaiming agent would return. Everything downstream is real: the CI failure,
the check-run poll, the state transition, the taxonomy bucket.

This is evidence that the rejection path works against real GitHub data. It is
not evidence about Devin's behaviour; across three real PR-producing
remediations there were zero terminal overclaims. Run against a scratch database so the evaluation figures are
untouched.

Two real pull requests passed CI first time. A third initially failed the
verification lane and Devin corrected it without another human prompt. The
synthetic fault injection remains useful because it proves the terminal rejection
path when an agent claim and repository CI never reconcile.

## What this proof of concept does not show

- Throughput. Four resolved issues support no defensible rate.
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

## Cost by outcome

| Outcome | Time | Cost |
|---|---|---|
| Remediation, merged (#2) | 15.6 min | $1.67 |
| Remediation, merged (#1) | 11.6 min | $1.33 |
| Correct refusal (#7) | 3.6 min | $0.97 |
| Remediation + self-repair (#8) | 11.6 min | $1.75 |
| | **Total** | **$5.72** |

**$2.86 per merged pull request** on two merges, counting the refusal and the
self-repair against merged output rather than excluding them. Merging the
verified third pull request takes it to $1.91.

Two things worth reading off that table.

**The refusal is the cheapest outcome**, which inverts the usual economics of
automation. Normally the failure mode is the expensive one: wasted compute plus a
speculative pull request somebody has to read and reject. Here a correct decline
cost 58% of a success and consumed no review time at all.

**Self-repair is the most expensive, and worth it.** Issue #8 cost $1.75 against
a $0.97–$1.67 range for everything else, because the agent pushed a second commit
after CI rejected the first. That extra ~$0.30 bought a diff that is better than
what was on master, since it removed a suppression that had been there before any
of this started. Cheap relative to a reviewer noticing the same thing a day
later, or not noticing.

Variance across four quite different tasks was low — $0.97 to $1.75 — which makes
a scoped remediation on a repository this size roughly a **$1.50 unit** for
planning purposes.

Sessions parked in `waiting_for_user` after producing a verdict in all three
runs, including after the Playbook was amended to tell them not to. The
orchestrator now terminates a session once its task reaches a terminal state,
which closed all three.

## A note on the recovery counter

`autonomous_ci_recoveries` is derived from the event journal: a task held after
CI went red that later reached a verified state. The settling-window
instrumentation that writes that event was added *after* issue #8 ran, so its
entry was recorded retrospectively, and says so in the journal detail.

The underlying fact is externally checkable rather than asserted:
[run 31504513261](https://github.com/harry1174/superset/actions/runs/31504513261)
failed on `58d5ece7`, and
[run 31504703530](https://github.com/harry1174/superset/actions/runs/31504703530)
passed on `74845320` after Devin pushed a corrected commit. Every later run
records the event as it happens.
