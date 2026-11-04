---
name: merge-gate
description: Decide whether a FidClic pull request merges to main (production) by itself or goes to the user, then act on the verdict. Use before any merge to main, or when the user asks whether a pull request can be merged.
argument-hint: <pull request number>
---

`main` goes straight to the live merchants. Read `docs/loop/merge-policy.md`, then for
pull request $ARGUMENTS run:

```bash
python3 scripts/merge_gate.py $ARGUMENTS
```

If `gh` fails with a TLS error inside the sandbox, run it again outside the sandbox.

**BLOCKED:** fix what it names and run it again. Do not merge.

**REVIEW:** do not merge. Tell the user in plain Hinglish why it needs them, what the
risk is, the human test steps, and the pull request link. Merge only when the user says
yes for this pull request in chat. Run the gate again first, and only proceed if it does
not say BLOCKED.

**AUTO:** go through "What the script cannot see" in the policy. If any item applies, add
the `needs-review` label and treat it as REVIEW. Otherwise:

```bash
gh pr merge $ARGUMENTS --merge -R fidclic37-lang/fidclic-platform
```

After merging, confirm the production deployment for the merge commit succeeded and tell
the user what went live. Never delete a branch or worktree that holds unmerged work.
Never change a test, the gate or the policy to turn a verdict into AUTO.
