"""
The old « étudiant » flag leaves the database (user, 2026-10-30: « purana data
mein se etudiant waala info bas hatao, baaki ka data intact rkho »).

Only `is_student` is removed from each client; every other field stays as it
was. Once, at start-up, marked in platform_settings with how many clients it
touched; a second start does nothing.

Run: cd api && python3 tests/test_drop_student_flag.py
"""
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server

    db = server.db
    passed = failed = 0

    def check(label, cond, detail=None):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail}"))

    db.platform_settings.delete_many({"key": "drop_is_student"})
    db.customers.delete_many({})
    at = dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc)
    base = {"tenant_id": "t1", "phone": "0611223344", "visits": 7, "points": 40, "tier": "silver",
            "birthday": "02-11", "postal_code": "37000", "acquisition_source": "instagram", "created_at": at}
    db.customers.insert_many([
        {**base, "id": "a", "name": "Ana", "is_student": True},
        {**base, "id": "b", "name": "Ben", "is_student": False},
        {**base, "id": "c", "name": "Cléo"},                         # never had it
        {**base, "id": "d", "name": "Dan", "tenant_id": "t2", "is_student": True},
    ])
    before = {c["id"]: {k: v for k, v in c.items() if k not in ("_id", "is_student")}
              for c in db.customers.find({})}

    print("\nUne fois")
    server._drop_student_flag_once()
    after = {c["id"]: c for c in db.customers.find({}, {"_id": 0})}
    check("no client keeps « is_student », in every shop", all("is_student" not in c for c in after.values()))
    check("every other field is exactly as it was",
          all({k: v for k, v in after[i].items()} == before[i] for i in before), after)
    check("no client added or removed", set(after) == {"a", "b", "c", "d"})
    mark = db.platform_settings.find_one({"key": "drop_is_student"}) or {}
    check("marked done, with how many clients it touched (3)", mark.get("value") == "v1" and mark.get("customers") == 3, mark)

    print("\nPas deux fois")
    db.customers.update_one({"id": "c"}, {"$set": {"is_student": True}})   # a write from somewhere else
    server._drop_student_flag_once()
    check("a second start does nothing (marked)", db.customers.find_one({"id": "c"}).get("is_student") is True
          and (db.platform_settings.find_one({"key": "drop_is_student"}) or {}).get("customers") == 3)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
