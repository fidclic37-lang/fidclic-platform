"""
The plan's line about clients says what is limited (QA F30, 2026-10-11):
Abonnement read « 15 000 cartes clients » above « Cartes de fidélité créées
165 / 4 000 » and « Clients actifs 165 / 15 000 » — two different limits, one
of them named after the other. The 15 000 is the ACTIVE clients'.

Run: cd api && /usr/local/bin/python3 tests/test_plan_bullets_wording.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from features.plan_limits import plan_bullets  # noqa: E402

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


lines = plan_bullets({"max_customers": 15000, "push_per_month": 0})
check(f"« 15 000 clients actifs » ({lines[2]})", "15 000 clients actifs" in lines)
check("no « cartes clients » for that limit", not any("cartes clients" in x for x in lines))
check(f"no limit: « Clients actifs illimités » ({plan_bullets({})[2]})", "Clients actifs illimités" in plan_bullets({}))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
