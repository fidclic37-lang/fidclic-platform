# Merge policy

`main` deploys to the live merchants, and GitHub does not enforce any rule on it.
`scripts/merge_gate.py` decides what may merge without a person. Its tests are in
`api/tests/test_merge_gate.py`. Change the three together.

```bash
python3 scripts/merge_gate.py 123
```

## Verdicts

| Verdict | Exit | Meaning | What happens |
|---|---|---|---|
| AUTO | 0 | Checks passed and nothing needs a person | Merge |
| REVIEW | 2 | Checks passed, but a person should look | Tell the user why, with the human test. Merge only after they say yes for this pull request |
| BLOCKED | 1 | Not ready | Fix it and run the gate again |

## BLOCKED

- `api` or `e2e` did not pass. Skipped or missing counts as not passed.
- Any other check failed or is still running.
- The `ai` label is present and `golden` did not pass.
- It is a draft, has conflicts, does not target `main`, or changes no files.

## REVIEW

- Money or accounting: billing, invoices, FEC, e-invoicing.
- Login and permissions.
- The Wallet card, and the service worker.
- Scheduled jobs, `vercel.json`, and messages sent to customers.
- A new or changed dependency, or environment configuration.
- The merge rules themselves: CI, this policy, the gate, `.claude/settings.json`.
- Anything people see: `src/`, `public/`, `index.html`. These need a human test.
- A test deleted, shrunk, skipped or isolated with `.only`.
- Changed lines with bulk database writes, credentials or money.
- More than 400 changed lines of code, or more than 15 code files. Tests and docs do not count.
- The `needs-review` label.

## What the script cannot see

Even on AUTO, add the `needs-review` label if any of these is true:

- It makes a product decision the task did not state.
- It changes wording, a price, a rule or a default that a merchant or customer would notice.
- A subagent reported a HIGH finding that is still open.
- It changes how existing data is read or migrated.
- Anything in the run felt uncertain.

## After a merge

Confirm the production deployment for the merge commit succeeded. If it failed,
tell the user straight away. Do not make further production changes to repair it
without asking.
