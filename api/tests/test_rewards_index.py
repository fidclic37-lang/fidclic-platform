"""
Every scan and every hand-over asks `rewards_earned` « what is waiting for this
client? ». With no index, MongoDB read the whole collection each time: at
100 000 rows a hand-over took about 100 ms more, and a burst of tills kept the
database busy (load run, 2026-11-04). The index that answers it must exist.

Run: cd api && /usr/local/bin/python3 tests/test_rewards_index.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import features.loyalty_card as LC

    db = mongomock.MongoClient().db
    LC.init(db)
    keys = [v["key"] for v in db.rewards_earned.index_information().values()]
    check("the waiting rewards of a client are indexed: client, status, oldest first",
          [("customer_id", 1), ("status", 1), ("earned_at", 1)] in keys)
    LC.init(db)
    check("starting again changes nothing", len(db.rewards_earned.index_information()) == len(keys))
    check("the index is not unique: a client can have several waiting", not any(
        v.get("unique") for k, v in db.rewards_earned.index_information().items() if k != "_id_"))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
