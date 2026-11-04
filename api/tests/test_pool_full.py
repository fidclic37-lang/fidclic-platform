"""
A full connection pool must only fail the request that waited too long.

pymongo 4.6.1 treats « waited too long for a connection » like a network error:
it clears the WHOLE pool and marks the database unknown, so every other request
of that instance fails too and all the connections are opened again (load run,
2026-11-04: 50 tills at once, 8 such timeouts, 32 pool clearings, 1 338 failed
check-outs). A real network error must still clear the pool.

Run: cd api && /usr/local/bin/python3 tests/test_pool_full.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pymongo import errors as E
from pymongo.topology import Topology, _ErrorContext

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


class Monitor:
    def cancel_check(self):
        pass


class Server:
    resets = 0
    _monitor = Monitor()

    def reset(self, service_id=None):
        Server.resets += 1


class Settings:
    load_balanced = True          # no topology description to update in this stub


def stub():
    t = Topology.__new__(Topology)
    t._servers = {("h", 1): Server()}
    t._settings = Settings()
    t._is_stale_error = lambda address, ctx: False
    return t


def hit(error):
    Server.resets = 0
    ctx = _ErrorContext(error, 21, 0, True, "svc")
    Topology._handle_error(stub(), ("h", 1), ctx)
    return Server.resets


def main():
    from services import mongo_pool

    check("before the guard, pymongo clears the pool on a full queue", hit(E.WaitQueueTimeoutError("full")) == 1)
    mongo_pool.install()
    check("a request that waited too long clears nothing", hit(E.WaitQueueTimeoutError("full")) == 0)
    check("a real network error still clears the pool", hit(E.AutoReconnect("gone")) == 1)
    check("a socket timeout is left to pymongo: nothing cleared", hit(E.NetworkTimeout("slow")) == 0)
    mongo_pool.install()
    check("installed twice: same behaviour", hit(E.WaitQueueTimeoutError("full")) == 0 and hit(E.AutoReconnect("gone")) == 1)

    os.environ.setdefault("JWT_SECRET", "test-pool-full")
    os.environ.setdefault("DISABLE_SEED", "1")
    import mongomock
    import pymongo
    pymongo.MongoClient = mongomock.MongoClient
    Topology._handle_error = mongo_pool._ORIGINAL
    mongo_pool._ORIGINAL = None
    import server  # noqa: F401
    check("the app installs it at start-up", hit(E.WaitQueueTimeoutError("full")) == 0)

    print("\nA scan does not lose its visit because the pool was full")
    from models import TokenData
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    db = server.db
    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "C", "is_active": True, "plan": "vip", "subscription_status": "active"})
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10})
    TD = TokenData(email="o@x.fr", role="business_owner", tenant_id="t1")
    Coll = mongomock.collection.Collection
    original = Coll.insert_one
    tries = {"n": 0, "fail": 0}

    def flaky(self, doc, *a, **k):
        if self.name == "visits":
            tries["n"] += 1
            if tries["n"] <= tries["fail"]:
                raise E.WaitQueueTimeoutError("full")
        return original(self, doc, *a, **k)
    Coll.insert_one = flaky

    def scan_with(fail, cid):
        tries.update(n=0, fail=fail)
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "barcode_id": f"FT-{cid}", "name": "L", "visits": 0, "points": 0})
        r = server.scan_visit(server.ScanRequest(barcode_id=f"FT-{cid}", amount_paid=5), TD)
        return r, db.visits.count_documents({"customer_id": cid})

    r, n = scan_with(0, "A1")
    check("a normal scan writes one visit, once", n == 1 and tries["n"] == 1 and r["visits"] == 1)
    r, n = scan_with(1, "A2")
    check("full once: tried again, one visit", n == 1 and tries["n"] == 2)
    r, n = scan_with(2, "A3")
    check("full twice: tried again, one visit", n == 1 and tries["n"] == 3)
    r, n = scan_with(9, "A4")
    check("still full: it stops at 3 tries, the till gets its answer", n == 0 and tries["n"] == 3 and r["visits"] == 1)
    Coll.insert_one = original

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
