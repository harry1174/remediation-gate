---
title: Remediate a triaged engineering issue
macro: !remediate_issue
---

## Purpose

Turn one approved, reproducible engineering issue into the smallest verified pull
request that resolves its acceptance criteria. A pull request without evidence is
not a successful outcome.

## Procedure

1. Read the issue contract and inspect the referenced code and nearby tests.
2. Reproduce the behavior or independently confirm the static finding before editing.
3. If the issue does not reproduce on the fork's current `master`, return
   `no_change_needed` with evidence and do not open a pull request.
4. Create a branch from `master` and implement the smallest complete correction.
5. Add or update a regression test that would fail before the correction whenever
   the issue contract requests one.
6. Run the issue's targeted verification command. Run focused formatting or linting
   for changed files. Do not claim a command ran unless it actually ran.
7. Review the diff for unrelated changes, generated files, and accidental formatting.
8. Open a pull request against the repository in the issue contract. Include
   `Closes #<issue-number>`, the root cause, the change, and exact verification output.
9. Return the required structured output, then end the session. Do not stop and
   wait for further instruction after the verdict: the verdict *is* the handoff,
   and a session parked awaiting a reply blocks the pipeline that is watching it.

## Specifications

- `outcome=remediated` requires a pull request URL and at least one successful
  verification command.
- `verification.all_passed` is true only when every required command completed
  successfully after the final code change.
- Use `risk=medium` or `risk=high` when behavior, compatibility, or security
  assumptions need focused reviewer attention; open those pull requests as drafts.
- Use `blocked` when the safe correction requires a product decision, unavailable
  credentials, a major redesign, or changes outside the issue's stated scope.
- Record pre-existing test failures separately from failures caused by the change.

## Forbidden actions

- Never push directly to `master` and never force-push.
- Do not change CI, release tooling, license headers, or unrelated dependencies.
- Do not suppress a security or lint rule merely to make verification green.
- Do not edit more than eight files. Return `blocked` if the correct change exceeds
  that boundary.
- Do not open a speculative pull request when the finding is not reproducible.
- Do not fabricate command output, test counts, ACU usage, or review evidence.
