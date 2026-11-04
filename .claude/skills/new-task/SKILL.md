---
name: new-task
description: Turn a plain-language request (bug or change on the FidClic platform) into a testable task spec in docs/tasks and hand back the /goal line that runs it. Use when the user invokes /new-task or describes platform work they want done by a loop.
argument-hint: <what is wrong or what you want, in your own words>
---

The user described this work: $ARGUMENTS

Turn it into a contract a loop can finish without asking for more prompts.

1. Read `docs/product.md`, `docs/architecture.md` and `docs/verification.md`.
2. Find the relevant code with targeted searches. For a bug, reproduce it locally if
   that takes a few minutes. Never reproduce against production or a preview.
3. Create `docs/tasks/<short-slug>.md` from `docs/tasks/_TEMPLATE.md`. Fill every section:
   - Acceptance criteria must be observable. Rewrite vague wording until a test could
     check it, and include the empty, error, permission and other-store cases.
   - Out of scope names what a helpful engineer would be tempted to change.
   - The human test is in plain Hinglish, for a non-developer, on the local server.
   - The repository is public: no customer data, passwords, keys or merchant details.
4. Ask only what the code cannot answer and the user must own: product behaviour,
   wording, money, what customers receive. Use one AskUserQuestion with concrete options.
   If nothing needs asking, do not ask. Record the answers in the spec.
5. If the request is really several independent tasks, make one spec each and say so.
6. If it is not measurable, such as pure visual taste, say so and propose the closest
   measurable version. Do not start a loop on a vague goal.
7. Show the user a short summary in Hinglish: what will change, what will not, and how
   it will be judged. Then give this line to paste, with the slug filled in:

```text
/goal Follow the run-task skill for docs/tasks/<slug>.md. Done only when the transcript shows the final run-task report: every acceptance criterion marked PASS with its evidence, the subagent findings resolved or reported, the pull request's api and e2e checks passed, and scripts/merge_gate.py's verdict printed and acted on (merged on AUTO; on REVIEW, the reason and human test given to the user and not merged). Also done if a Stop and ask condition in the spec is reported to the user. Never edit the spec's acceptance criteria, delete or skip tests, or push to main. Stop after 30 turns with a status report.
```

Do not start the work yourself in this skill.
