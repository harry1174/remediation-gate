# Five-minute Loom

Audience: a VP of Engineering and the senior ICs who will pick holes in it.
One sentence to land: **Devin does the engineering; the platform refuses to call
it done until something other than Devin agrees.**

Tabs open in this order, before recording: the two fork issues · the dashboard ·
the Devin session · the Playbook in the Devin web app · the PR with its checks ·
`app/prompts.py`.

---

## 0:00–0:45 — What

Open on the two issues in the fork.

> Every engineering org has a queue of work that is individually small,
> collectively enormous, and permanently outranked by roadmap items. Not
> difficult work — a bare except, a missing regression test, a suppressed lint
> rule. It doesn't get done because each item costs a senior engineer a context
> switch, and the reward for doing one is that four hundred remain.

> This turns an approved issue into a pull request nobody had to schedule. The
> label *is* the approval. Adding it authorizes the spend.

Do not oversell the findings. One is a hardening item, deliberately reclassified
down from "security/high" after checking Superset's own threat model — say so.
It's a judgment call the assessor can verify, and volunteering it buys more
credibility than the inflated version would have.

## 0:45–1:45 — How, part one: the trigger and the contract

Add `devin:autofix` live. Show the task appear on the dashboard.

Then open the issue body — this is the part worth dwelling on.

> The brief said "remediate issues". It didn't say what an issue is. So an
> eligible issue is a contract: observed problem, reproduction, scope,
> acceptance criteria, exact verification commands, and non-goals. The non-goals
> are what keep the diff reviewable — they're where I tell it what *not* to fix.

Then show `app/prompts.py` on screen.

> Thirteen lines. Everything reusable moved into a Devin Playbook, because
> remediation policy is the thing a customer argues about — what counts as
> verified, whether a major version bump is allowed. As a Playbook their tech
> lead edits it in Devin's web app and the next session picks it up. If it lived
> in my Python, every policy change would be a pull request against my service.

## 1:45–2:45 — How, part two: Devin working

Open the real session. Show it navigating the repository, editing, running the
targeted test, iterating.

Be precise about what Devin did and didn't do:

> To be clear about what's mine and what's Devin's: my issue contract names the
> file and the failing condition. What Devin does is explore a repository it has
> never seen, confirm the finding is real before touching anything, write a
> regression test that fails against the unfixed code, run verification, iterate
> when it fails, and open a reviewable PR.

Never say Devin "diagnosed" the bug. The contract named it, that's checkable in
thirty seconds, and the honest version is strong enough.

## 2:45–3:45 — Why Devin, and the trust boundary

This is the section that decides the outcome.

> The obvious objection is that this is a script with an LLM in it. Here's the
> answer: the orchestrator contains no code generation at all. It handles
> authorization, spend, state and evidence. Everything between "issue" and "pull
> request" needs an agent that can explore, judge, implement, run tests, read
> failures and try again — and refuse.

Then the gate. Show a task at `agent_verified_pr`.

> Devin returns a typed verdict saying its verification passed. I don't accept
> it. That's a claim about commands it says it ran. The task waits here until
> the repository's own CI agrees, and only then becomes `verified_pr`.

Show the fault-injection PR being rejected — CI red, task flips to
`failed_verification`, issue labelled `devin:needs-human`, overclaim count
increments.

> When they disagree, that's an agent overclaim, and it's counted. That number
> is the defect rate of my Playbook — which means it's a number I improve by
> editing a document, not by redeploying software.

## 3:45–4:30 — Business impact

Dashboard, measured panel only.

> Observed: N issues, N sessions, N CI-verified PRs, N merged. Median trigger to
> CI-confirmed, X minutes. Total spend, Y ACUs.

Then scroll to the modeled panel and name it as such.

> These are planning scenarios, not savings. The uncertainty is entirely in what
> the same work would have cost a human, so it's a range, not a number. And rates
> are withheld below five resolved tasks — two results don't make a percentage.

> What I'm not claiming: fewer vulnerabilities, fewer incidents, higher
> throughput. This pilot measures none of those.

## 4:30–5:00 — When

> First engagement: point it at the scanner findings they already ignore, and
> run one playbook against one repository until the overclaim rate is boring.
> Then A/B two versions of the playbook and let merge rate pick the winner —
> sessions are disposable, the playbook is the asset that accumulates value.
> After that: ownership-based escalation instead of a generic label, review-rework
> rate as the quality metric, and Postgres with a real worker pool for multi-repo.

---

## Rehearsal checklist

- [ ] Restart the tunnel and update the webhook URL — quick-tunnel hostnames change
- [ ] Database wiped of demo tasks; dashboard shows only live results
- [ ] `MAX_CONCURRENT_SESSIONS=1` so one thing happens at a time on screen
- [ ] Fault-injection PR prepared but not yet adjudicated
- [ ] Real ACU numbers written down — never read them off a stale tab
- [ ] Know which story you're telling if Devin returned `blocked`: that's the
      refusal path working, not a failed demo
