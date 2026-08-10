# Five-minute Loom outline

## 0:00-0:40 - What

Show the two real issues in the Superset fork. Explain that the workflow targets
small, approved maintenance tasks that are easy to understand but expensive to
schedule because each creates an engineering context switch.

## 0:40-1:35 - Trigger and control plane

Add `devin:autofix` to one issue. Show it enter the dashboard once. Point out
webhook authentication, repository allowlisting, idempotency, concurrency, and
the per-session ACU cap.

## 1:35-2:45 - Devin as the primitive

Open the Playbook, Knowledge note, and the real Devin session. Explain the split:
the issue is the unique contract, Knowledge is stable repository context, and
the Playbook is customer-owned remediation policy. Show Devin inspecting code,
running the targeted test, iterating, and opening the PR.

## 2:45-3:35 - Verification and failure behavior

Show the structured output schema and `apply_verdict`. Emphasize that a PR URL
with failed tests is classified as `failed_verification`, not success. Mention
`blocked` and `no_change_needed` as intentional outcomes.

## 3:35-4:20 - Business evidence

Show the live funnel and task evidence. State actual ACUs and elapsed time. Cost
per merged PR remains blank until a merge. Clearly identify the displayed hourly
value assumptions as assumptions.

## 4:20-5:00 - Why and when

Explain why a scanner, codemod, or autocomplete cannot independently navigate
Superset, make a scoped judgment, run and repair tests, open a PR, and refuse bad
work. Next steps are reviewer-rework metrics, ownership routing, more repositories,
and scanner ingestion with stable finding fingerprints.
