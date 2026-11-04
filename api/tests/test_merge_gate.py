"""The merge gate: which pull requests may reach production without a human.

main deploys to the live merchants and GitHub does not enforce anything on it,
so this decision is the only brake when a loop runs unattended. Pure function,
no network: scripts/merge_gate.py feeds it what `gh` returns.

Run: cd api && python3 tests/test_merge_gate.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from merge_gate import AUTO, BLOCKED, REVIEW, decide  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name} {detail}")


GREEN = [
    {"name": "api", "state": "SUCCESS"},
    {"name": "e2e", "state": "SUCCESS"},
    {"name": "golden", "state": "SKIPPED"},
    {"name": "Vercel", "state": "SUCCESS"},
]
PR = {"baseRefName": "main", "isDraft": False, "mergeable": "MERGEABLE", "labels": []}


def f(path, add=5, rem=1, status="modified", patch="+x = 1\n-x = 2"):
    return {"path": path, "additions": add, "deletions": rem, "status": status, "patch": patch}


def run(files, checks=GREEN, pr=None):
    return decide(files, checks, {**PR, **(pr or {})})


print("merge gate: a safe change")
v, why = run([f("api/features/visits.py"), f("api/tests/test_visits.py", 20, 0)])
check("a small backend fix with green checks merges alone", v == AUTO, why)
v, _ = run([f("docs/loop/README.md", 300, 0)])
check("docs alone merge, whatever their size", v == AUTO)
v, _ = run([f(".claude/agents/reviewer.md", 300, 0)])
check("an agent definition merges alone", v == AUTO)

print("merge gate: checks")
for name in ("api", "e2e"):
    v, why = run([f("api/features/visits.py")], [c for c in GREEN if c["name"] != name])
    check(f"{name} missing blocks", v == BLOCKED and name in " ".join(why), why)
v, why = run([f("api/features/visits.py")], [])
check("no checks at all blocks", v == BLOCKED, why)
for state in ("FAILURE", "PENDING", "IN_PROGRESS", "CANCELLED", "TIMED_OUT"):
    v, _ = run([f("api/features/visits.py")],
               [{"name": "api", "state": state}, {"name": "e2e", "state": "SUCCESS"}])
    check(f"api {state} blocks", v == BLOCKED)
v, _ = run([f("api/features/visits.py")],
           [{"name": "api", "state": "SKIPPED"}, {"name": "e2e", "state": "SUCCESS"}])
check("a skipped api job is not a pass", v == BLOCKED)
v, _ = run([f("api/features/visits.py")], GREEN + [{"name": "lint", "state": "FAILURE"}])
check("any other failed check blocks too", v == BLOCKED)
v, _ = run([f("api/features/visits.py")], GREEN, {"labels": [{"name": "ai"}]})
check("the ai label needs the golden set to have passed", v == BLOCKED)
ok = [c for c in GREEN if c["name"] != "golden"] + [{"name": "golden", "state": "SUCCESS"}]
v, _ = run([f("api/features/visits.py")], ok, {"labels": [{"name": "ai"}]})
check("ai label with golden passed goes through", v == AUTO)

print("merge gate: the pull request itself")
for field, value, label in (("isDraft", True, "a draft"),
                            ("mergeable", "CONFLICTING", "a conflict"),
                            ("mergeable", "UNKNOWN", "unknown mergeability"),
                            ("baseRefName", "develop", "another base branch")):
    v, _ = run([f("api/features/visits.py")], GREEN, {field: value})
    check(f"{label} blocks", v == BLOCKED)
v, _ = run([])
check("a pull request with no files is not merged", v == BLOCKED)

print("merge gate: what a person must look at")
SENSITIVE = [
    "api/features/billing.py", "api/features/agent_billing.py", "api/features/invoices.py",
    "api/features/fec.py", "api/features/facture_watchdog.py",
    "api/auth.py", "api/features/auth_reset.py", "api/features/oauth.py",
    "api/features/role_perms.py",
    "api/features/wallet_passes.py", "api/features/push_wallet.py",
    "api/features/google_wallet_callbacks.py", "api/features/wallet_identities.py",
    "api/features/cron.py", "api/services/sms.py", "vercel.json",
    "package.json", "package-lock.json", "api/requirements.txt",
    ".github/workflows/customer-journey.yml", "scripts/merge_gate.py",
    "api/tests/test_merge_gate.py", ".claude/settings.json",
    "docs/loop/merge-policy.md", "scripts/run_api_tests.py",
    ".env.example", "public/sw.js",
]
for path in SENSITIVE:
    v, why = run([f(path)])
    check(f"{path} asks a person", v == REVIEW, (v, why))
for path in ("src/pages/DashboardPage.jsx", "src/components/Card.jsx", "src/index.css", "index.html"):
    v, why = run([f(path)])
    check(f"a visible change ({path}) asks a person", v == REVIEW, (v, why))
v, why = run([f("api/features/visits.py"), f("api/features/billing.py")])
check("one sensitive file among safe ones is enough", v == REVIEW and "billing" in " ".join(why), why)

print("merge gate: tests must not be weakened")
v, _ = run([f("api/tests/test_visits.py", 0, 40, status="removed")])
check("a deleted API test asks a person", v == REVIEW)
v, _ = run([f("e2e/caisse.spec.js", 0, 40, status="removed")])
check("a deleted browser test asks a person", v == REVIEW)
v, _ = run([f("api/tests/test_visits.py", 2, 30)])
check("a test that mostly shrinks asks a person", v == REVIEW)
v, _ = run([f("api/tests/test_visits.py", 30, 2)])
check("a test that grows merges", v == AUTO)
v, _ = run([f("e2e/caisse.spec.js", 3, 1, patch="+test.skip('pays', async () => {})")])
check("a newly skipped browser test asks a person", v == REVIEW)
v, _ = run([f("e2e/caisse.spec.js", 3, 1, patch="+test.only('pays', async () => {})")])
check("a stray test.only asks a person", v == REVIEW)

print("merge gate: risky content in an ordinary file")
for line in ("+db.visits.delete_many({})", "-db.customers.drop()", "+ db.rewards.update_many({}, {'$set': {'x': 1}})",
             "+amount_cents = 500", "+password = 'x'", "+JWT_SECRET = 'x'", "+stripe.Charge.create()",
             "+def get_api_key(): pass"):
    v, why = run([f("api/features/visits.py", patch=line)])
    check(f"« {line} » asks a person", v == REVIEW, (v, why))
v, _ = run([f("api/server.py", patch="+logger.info('scan')")])
check("an ordinary line in server.py merges", v == AUTO)
v, why = run([f("api/features/copilot.py", patch="+token_count = usage.total_tokens")])
check("counting AI tokens is not a credential", v == AUTO, why)
for line in ("+access_token = 'x'", "+refresh_token = 'x'"):
    v, why = run([f("api/features/visits.py", patch=line)])
    check(f"« {line} » asks a person", v == REVIEW, (v, why))

print("merge gate: size")
v, _ = run([f("api/features/visits.py", 401, 0)])
check("over 400 changed lines of code asks a person", v == REVIEW)
v, _ = run([f("api/features/visits.py", 400, 0)])
check("exactly 400 lines merges", v == AUTO)
v, _ = run([f("api/features/visits.py", 100, 0), f("api/tests/test_visits.py", 3000, 0)])
check("tests don't count towards the size", v == AUTO)
v, _ = run([f(f"api/features/m{i}.py") for i in range(16)])
check("over 15 code files asks a person", v == REVIEW)
v, _ = run([f(f"api/features/m{i}.py") for i in range(15)])
check("exactly 15 code files merges", v == AUTO)

print("merge gate: a person can always ask")
v, _ = run([f("docs/x.md")], GREEN, {"labels": [{"name": "needs-review"}]})
check("the needs-review label stops the merge", v == REVIEW)

print("merge gate: blocked beats review")
v, _ = run([f("api/features/billing.py")], [])
check("no checks on a sensitive file is blocked, not review", v == BLOCKED)
v, why = run([f("api/features/visits.py")])
check("the answer always gives a reason", bool(why))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
