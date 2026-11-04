#!/usr/bin/env python3
"""May this pull request reach production without a person looking at it?

main deploys to the live merchants and GitHub enforces nothing on it, so this
is the only brake when a loop runs unattended. The rules are written out in
docs/loop/merge-policy.md; keep the two together.

    python3 scripts/merge_gate.py 123

Prints the verdict and why. Exit code: 0 AUTO, 2 REVIEW, 1 BLOCKED.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

AUTO, REVIEW, BLOCKED = "AUTO", "REVIEW", "BLOCKED"

REPO = "fidclic37-lang/fidclic-platform"
REQUIRED_CHECKS = ("api", "e2e")
MAX_CODE_LINES = 400
MAX_CODE_FILES = 15

# A check in any other state is still running or went wrong.
CHECK_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}

# Files never merged without a person, and why.
SENSITIVE_PATHS = (
    (r"api/features/(agent_)?billing|api/features/invoices|api/features/fec|api/features/facture|einvoic|facturation",
     "money or accounting"),
    (r"api/auth\.py|api/features/(auth_reset|oauth|role_perms)", "login or permissions"),
    (r"wallet", "the customer's Wallet card"),
    (r"api/features/cron\.py|^vercel\.json$", "scheduled jobs or production routing"),
    (r"api/services/sms\.py", "messages sent to customers"),
    (r"^package(-lock)?\.json$|requirements[^/]*\.txt$", "a dependency"),
    (r"^\.github/|^scripts/merge_gate\.py$|^scripts/run_api_tests\.py$|test_merge_gate\.py$"
     r"|^\.claude/settings[^/]*\.json$|^docs/loop/merge-policy\.md$", "the rules that guard merging"),
    (r"(^|/)\.env", "environment configuration"),
    (r"^public/sw\.js$", "the service worker every phone runs"),
    (r"^src/|^public/|^index\.html$|^tailwind\.config", "something people see (test it by hand)"),
)

# Lines that change what a file does to data or money, wherever they appear.
RISKY_LINES = (
    (r"\.(delete_many|drop|update_many)\(", "a bulk database write"),
    (r"(?i)password|jwt_|secret|api_key|(access|refresh|auth)_token", "a secret or credential"),
    (r"(?i)stripe|amount_cents|\bprice\b|\bvat\b|\btva\b", "money"),
)

SKIPPED_TEST = re.compile(r"\b(test|describe|it)\.(skip|only|fixme)\b|@pytest\.mark\.skip")


def _is_test(path: str) -> bool:
    return path.startswith(("api/tests/", "e2e/"))


def _is_documentation(path: str) -> bool:
    return path.endswith(".md") or path.startswith(".claude/")


def _changed_lines(patch: str) -> list[str]:
    return [l for l in (patch or "").splitlines()
            if l[:1] in "+-" and not l.startswith(("+++", "---"))]


def _blockers(files: list[dict], checks: list[dict], pr: dict) -> list[str]:
    why = []
    if pr.get("baseRefName") != "main":
        why.append(f"it targets {pr.get('baseRefName')}, not main")
    if pr.get("isDraft"):
        why.append("it is a draft")
    if pr.get("mergeable") != "MERGEABLE":
        why.append(f"GitHub says mergeable={pr.get('mergeable')}")
    if not files:
        why.append("it changes no files")
    states = {c["name"]: c["state"] for c in checks}
    for name in REQUIRED_CHECKS:
        if states.get(name) != "SUCCESS":
            why.append(f"required check {name} is {states.get(name, 'missing')}")
    for name, state in states.items():
        if name not in REQUIRED_CHECKS and state not in CHECK_OK:
            why.append(f"check {name} is {state}")
    labels = {l["name"] for l in pr.get("labels") or []}
    if "ai" in labels and states.get("golden") != "SUCCESS":
        why.append(f"label ai needs the golden set, which is {states.get('golden', 'missing')}")
    return why


def _review_reasons(files: list[dict], pr: dict) -> list[str]:
    why = []
    if "needs-review" in {l["name"] for l in pr.get("labels") or []}:
        why.append("someone put the needs-review label on it")

    code_lines = code_files = 0
    for f in files:
        path, patch = f["path"], f.get("patch") or ""
        for pattern, what in SENSITIVE_PATHS:
            if re.search(pattern, path):
                why.append(f"{path} touches {what}")
                break
        if _is_test(path):
            if f.get("status") == "removed":
                why.append(f"{path}: a test was deleted")
            elif f.get("deletions", 0) > f.get("additions", 0):
                why.append(f"{path}: the test got smaller")
            if any(l.startswith("+") and SKIPPED_TEST.search(l) for l in _changed_lines(patch)):
                why.append(f"{path}: a test was skipped or isolated")
            continue
        if _is_documentation(path):
            continue
        code_files += 1
        code_lines += f.get("additions", 0) + f.get("deletions", 0)
        for pattern, what in RISKY_LINES:
            if any(re.search(pattern, l) for l in _changed_lines(patch)):
                why.append(f"{path} changes {what}")

    if code_lines > MAX_CODE_LINES:
        why.append(f"{code_lines} changed lines of code (limit {MAX_CODE_LINES})")
    if code_files > MAX_CODE_FILES:
        why.append(f"{code_files} code files (limit {MAX_CODE_FILES})")
    return why


def decide(files: list[dict], checks: list[dict], pr: dict) -> tuple[str, list[str]]:
    """files: path, additions, deletions, status, patch. checks: name, state.
    pr: baseRefName, isDraft, mergeable, labels."""
    blockers = _blockers(files, checks, pr)
    if blockers:
        return BLOCKED, blockers
    reasons = _review_reasons(files, pr)
    if reasons:
        return REVIEW, reasons
    return AUTO, ["required checks passed and nothing here needs a person"]


def _gh(*args: str):
    return json.loads(subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    number = sys.argv[1]
    pr = _gh("pr", "view", number, "-R", REPO, "--json",
             "baseRefName,isDraft,mergeable,labels,statusCheckRollup")
    files = _gh("api", "--paginate", "--slurp", f"repos/{REPO}/pulls/{number}/files")
    files = [{"path": f["filename"], "additions": f["additions"], "deletions": f["deletions"],
              "status": f["status"], "patch": f.get("patch", "")} for page in files for f in page]
    checks = []
    for c in pr.get("statusCheckRollup") or []:
        if c.get("__typename") == "StatusContext":
            checks.append({"name": c["context"], "state": c["state"]})
        else:
            state = c.get("conclusion") or c.get("status") or "PENDING"
            checks.append({"name": c["name"], "state": state.upper()})
    verdict, why = decide(files, checks, pr)
    print(verdict)
    for line in why:
        print(f"  - {line}")
    return {AUTO: 0, REVIEW: 2, BLOCKED: 1}[verdict]


if __name__ == "__main__":
    sys.exit(main())
