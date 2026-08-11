# Five-minute Loom

Audience: a VP of Engineering and the senior ICs who will pick holes in it.

One sentence to land: **Devin does the engineering; the platform refuses to call
it done until something other than Devin agrees.**

Tabs, in this order, open before recording: the two fork issues · the dashboard ·
Devin session `77978d24` · the Playbook in the Devin web app · PR #5 with its
checks · the closed fault-injection PR #6 · `app/prompts.py`.

The run has already happened. Do not try to produce a live remediation on camera
— it takes ten minutes. Trigger a label live, show the task appear, then cut to
the completed work. Say you are doing that.

---

## 0:00–0:40 — What

Open on the two issues.

> Every org has a queue of work that is individually small, collectively
> enormous, and permanently outranked by roadmap items. A bare except, a missing
> regression test, a lint rule someone suppressed in 2021. It doesn't get done
> because each item costs a senior engineer a context switch, and the reward for
> doing one is that four hundred remain.

> This turns an approved issue into a pull request nobody had to schedule. The
> label is the approval, and adding it is what authorizes the spend.

Then the result, immediately — do not save it for the end:

> Two issues, two Devin sessions, two CI-verified pull requests, both merged.
> Median thirteen and a half minutes. Three dollars.

## 0:40–1:40 — How: the contract and the policy

Open the issue body.

> The brief said "remediate issues". It didn't say what an issue is. So eligible
> means a contract: observed problem, reproduction, scope, acceptance criteria,
> exact verification commands, and non-goals. The non-goals are where I say what
> *not* to fix, and they're why these diffs are four files instead of forty.

Mention the reclassification without being asked:

> One of these started as a security finding. I checked Superset's own threat
> model — the only caller is an operator-run CLI, so it crosses no privilege
> boundary, and their SECURITY.md says never to file vulnerabilities as public
> issues. I relabelled it hardening, dropped the severity, and removed the proof
> of concept. It's still worth fixing. It isn't a vulnerability.

Then `app/prompts.py` on screen.

> Thirteen lines. Everything reusable lives in a Devin Playbook, because
> remediation policy is what a customer argues about — what counts as verified,
> whether a major version bump is allowed. As a Playbook their tech lead edits it
> in Devin's web app. In my Python, every policy change is a pull request against
> my service and a deploy.

## 1:40–2:30 — How: Devin working

Open session `77978d24`. Show it exploring, editing, running the targeted test.

Be exact about the division of labour:

> My contract names the file and the failing condition. What Devin does is
> explore a repository it has never seen, confirm the finding is real before
> touching anything, write a regression test that fails against the unfixed code,
> run verification, and open a reviewable PR.

Never say Devin diagnosed the bug — the contract named it, that's checkable in
thirty seconds, and the honest version is strong enough. Then show the diff:

> It replaced the loader, and it *removed* the suppression rather than moving it,
> which the contract required. It added no new suppressions. That's policy
> working.

## 2:30–3:30 — Why Devin, and the trust boundary

The section that decides the outcome.

> The obvious objection is that this is a script with an LLM in it. The
> orchestrator contains no code generation at all — it handles authorization,
> spend, state and evidence. Everything between "issue" and "pull request" needs
> something that can explore, judge, implement, run tests, read failures, and
> refuse.

Now the gate. Show the funnel: *agent says verified 2 → CI confirms 2*.

> Devin returns a typed verdict saying its verification passed. I don't accept
> it. That's a claim about commands it says it ran. The task waits at
> `agent_verified_pr` until the repository's own CI agrees.

Then PR #6 — the moment that can't be staged:

> Both real PRs passed first time, which would leave "zero overclaims" resting on
> my word. So I wrote one by hand that silences a linter with a noqa — the
> shortcut every contract forbids. Ruff goes green. The gate fails it anyway, on
> the step that watches for the silencing, and the task lands in
> `failed_verification` counted as an overclaim.

If asked about Devin Review: it runs on these PRs, and it's deliberately excluded
from the gate. One Devin agent approving another Devin agent's work is not
independent confirmation.

## 3:30–4:20 — What the runs taught us, and business impact

Lead with the finding, not the numbers. It's the most senior thing you'll say.

> Both sessions produced a verdict, opened a PR, and then parked waiting for a
> human instead of exiting. I tried to fix it in policy — I told the Playbook to
> end the session. The next run parked anyway. Policy governs what the agent
> *produces*; it did not change when the session *terminates*. What fixed it was
> the orchestrator acting on a verdict the moment one exists.

> Instructing an agent is not the same as controlling it. That gap is what the
> control plane is for.

Then the dashboard, measured panel only:

> Two triggered, two sessions, two CI-verified, two merged, zero handed back.
> Median thirteen point six minutes. Three dollars, measured from the account
> balance — Devin reports zero ACUs on this plan, so the dashboard withholds
> ACU-derived cost rather than printing a zero.

Scroll to the modeled panel and name it:

> Planning scenarios, not savings. The uncertainty is entirely in what this would
> have cost a human, so it's a range. And rates are withheld below five resolved
> tasks — two results don't make a percentage.

> Not claiming: fewer vulnerabilities, fewer incidents, higher throughput. This
> pilot measures none of them.

## 4:20–5:00 — When

> First engagement: point it at the scanner findings they already ignore, one
> playbook, one repository, until the overclaim rate is boring. Then A/B two
> versions of the playbook and let merge rate pick the winner — sessions are
> disposable, the playbook is the asset that accumulates value.

> After that: feed CI failures back into the same session so Devin repairs its
> own red builds; ownership-based escalation instead of a generic label;
> review-rework rate as the quality metric; Postgres and a worker pool for
> multiple repositories.

---

## Rehearsal checklist

- [ ] Restart the tunnel and update the webhook URL — quick-tunnel hostnames
      change on every reconnect, and it has already died once mid-session
- [ ] `make preflight` — 12 pass, 0 blocking
- [ ] Dashboard shows the live run, not demo data
- [ ] Numbers written down: 2 / 2 / 2 / 2, 13.6 min, $3.00, 0 overclaims of 2
- [ ] Fault-injection PR #6 open in a tab, closed state is fine
- [ ] Do not call the hardening issue a security finding
- [ ] Do not say Devin diagnosed anything
