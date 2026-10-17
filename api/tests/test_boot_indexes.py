"""
Cold starts (2026-10-17): 17 s, 13.5 s of it the first start of each
deployment asking Atlas for ~150 indexes. Indexes are now created only when
their set changes, in the background on Vercel.

Run: cd api && /usr/local/bin/python3 tests/test_boot_indexes.py
"""
import os
import sys
import threading
import time
import types

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
    import features._loader as L

    db = mongomock.MongoClient().db
    Collection = type(db.platform_settings)
    built = []
    OURS = ("visits", "customers")          # other modules' indexes (commune cache…) are left aside

    def ours():
        return [b for b in built if (b[0] if isinstance(b, tuple) else b) in OURS]
    Collection.create_index = lambda self, keys, *a, **k: built.append((self.name, repr(keys), k.get("unique")))
    spec = {"unique": True}
    mod = types.ModuleType("features._fake_idx")

    def init(db):
        db.visits.create_index([("tenant_id", 1)], **spec)
        db.customers.create_index("barcode_id")
    mod.init = init
    sys.modules["features._fake_idx"] = mod
    L.MODULES = ["features._fake_idx"]

    class App:
        def include_router(self, r):
            pass

    def boot(commit):
        os.environ["VERCEL_GIT_COMMIT_SHA"] = commit
        t0 = time.perf_counter()
        L.register_all(App(), db)
        took = time.perf_counter() - t0
        for th in threading.enumerate():
            if th.name == "fidclic-indexes":
                th.join(5)
        return took

    boot("aaa")
    check(f"first deployment: the 2 indexes are created ({len(ours())})", len(ours()) == 2)
    marker = db.platform_settings.find_one({"key": L.INDEX_MARKER})
    check("…and their fingerprint is kept", marker and str(marker["value"]).startswith("idx-"))

    built.clear()
    boot("bbb")
    check("next deployment, same indexes: none asked again", ours() == [])

    built.clear()
    spec["unique"] = False
    boot("ccc")
    check("an index changed: the set is created again", len(ours()) == 2)

    # the build runs beside the start, never in it
    built.clear()
    slow = threading.Event()

    def slow_index(self, keys, *a, **k):
        slow.wait(2)
        built.append(self.name)
    Collection.create_index = slow_index
    spec["unique"] = True
    os.environ["VERCEL_GIT_COMMIT_SHA"] = "ddd"
    t0 = time.perf_counter()
    L.register_all(App(), db)
    took = time.perf_counter() - t0
    check(f"the start does not wait for the indexes ({took:.2f} s)", took < 0.5)
    slow.set()
    for th in threading.enumerate():
        if th.name == "fidclic-indexes":
            th.join(5)
    check("…they are built just after", len(ours()) == 2)

    del os.environ["VERCEL_GIT_COMMIT_SHA"]
    built.clear()
    Collection.create_index = lambda self, keys, *a, **k: built.append(self.name)
    L.register_all(App(), db)
    check("outside Vercel (local, tests): created at once, as asked", ours() == ["visits", "customers"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
