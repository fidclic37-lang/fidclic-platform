---
name: run-task
description: Execute a docs/tasks spec end to end on the FidClic platform - failing test, fix, subagent inspection, pull request, CI, merge gate. Use when a /goal or the user says to follow run-task for a spec.
argument-hint: <docs/tasks/slug.md>
---

Run the task in $ARGUMENTS. Each turn, continue from where the evidence says you are,
and show command output in the transcript: the goal evaluator only reads the conversation.

## 1. Set up

- Never work on `main`. If this checkout is not already an isolated worktree, enter one.
- Create a branch named for the task. Confirm the base is current `origin/main`.
- Read the spec and `docs/verification.md`. Run the narrow checks once to record the baseline.

## 2. Build

- Reproduce the problem, then write the failing test and show it failing.
- Make the smallest change that satisfies the spec. Stay inside In scope.
- Run the narrow checks until they pass. Commit in small steps with messages that explain why.

## 3. Inspect

Start fresh subagents with the spec path and `git diff origin/main...HEAD`. Give them
the code, not your conclusion. Run them in parallel when they do not share a browser.

| Always | When |
|---|---|
| `reviewer`, `bug-hunter`, `error-handling-auditor` | Every code change |
| `security-auditor` | It touches an endpoint, login, rights, customer data or money |
| `browser-tester` | It changes a screen or a customer journey |
| `load-tester` | It is a new feature, or changes a scan, a send or a heavy page |
| `improver` | Once, after the others are clean |

- HIGH and MEDIUM findings inside the spec: write a failing test, fix, and inspect again.
- Security and load findings: report them and do not fix them, unless the spec says to.
  A HIGH security finding means adding the `needs-review` label.
- Findings outside the spec: list them in the report for the user. Do not fix them here.
- `improver` suggestions: apply only behaviour-preserving ones that make this diff simpler.

## 4. Stop and ask

Stop, say what you found and what you need, when a Stop and ask condition in the spec is
hit. That includes the same failure surviving three different attempts. Do not guess a
product decision, weaken a test, or edit the acceptance criteria to get through.

## 5. Pull request

Run `python3 scripts/run_api_tests.py <relevant name>` and the relevant browser tests,
then push and open a pull request against `main`. The body has:

- What changed and why, for someone who has not read the code.
- Each acceptance criterion with PASS and its evidence.
- **Human test** copied from the spec.
- Findings still open.

Add the `ai` label if it changes AI prompts, models or answers.

The repository is public. For a security fix, describe what the code now does in commits
and the pull request, not how to attack it. Give exploit steps and pentest findings to the
user in chat only, and never put open findings in the repository.

## 6. CI

Wait for checks without burning turns. In the Claude app, use the PR status tools. In a
terminal, run `gh pr checks <n> --watch` as a background command. On failure, read the
log, fix the cause, push, and wait again. CI takes about 30 minutes.

## 7. Merge gate

Follow the `merge-gate` skill.

## 8. Final report

In Hinglish, plain points, in this order: what was built, tests with counts, pentest
findings, load findings, what to fix next, and the merge outcome. If the user needs to
test by hand, end with the exact steps.
