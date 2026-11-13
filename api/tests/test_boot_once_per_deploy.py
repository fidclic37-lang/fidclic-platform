"""
A cold start no longer re-runs every seed and migration (2026-11-12 outage:
while MongoDB was saturated, each NEW Vercel instance asked it 15+ questions
— platform roles, CRM templates, team task types, old migrations — before
serving anyone, right when there was no room left).

Now the FIRST instance of a deployment runs them (idempotent, as before) and
writes the deployment's build id in platform_settings; every other instance
of the same deployment reads that ONE marker and skips them all. Locally and
in tests there is no build id, so everything runs as it always did.

Run: cd api && python3 -u tests/test_boot_once_per_deploy.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-boot-once")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ.pop("VERCEL_GIT_COMMIT_SHA", None)
os.environ.pop("VERCEL_DEPLOYMENT_ID", None)

passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail!r}"))


class Counter:
    """Counts every non-index call per collection, with the method."""

    def __init__(self, db):
        self.db = db
        self.calls = []
        self._installed = []

    def __enter__(self):
        Collection = type(self.db.platform_settings)
        for name in ("find_one", "find", "count_documents", "insert_one", "insert_many",
                     "update_one", "update_many", "delete_many", "distinct", "find_one_and_update"):
            real = getattr(Collection, name, None)
            if real is None:
                continue

            def wrap(real, name):
                def inner(coll, *a, **k):
                    self.calls.append((name, coll.name))
                    return real(coll, *a, **k)
                return inner
            self._installed.append((Collection, name, real))
            setattr(Collection, name, wrap(real, name))
        return self

    def __exit__(self, *a):
        for Collection, name, real in self._installed:
            setattr(Collection, name, real)

    def of(self, coll):
        return [c for c in self.calls if c[1] == coll]


def main():
    import server
    from services import boot_marker as BM
    from features import platform_access as PA, team_tasks as TT, crm_email as CE
    from features import support_center as SC, onboarding as OB, push_wallet as PW, journal_stats as JS

    db = server.db
    BUILD = "build-abc123"

    # ------------------------------------------------------------------ the marker itself
    print("Le marqueur")
    check("the per-instance pool is 3 connections (166 instances before M0's 500)",
          server.MONGO_CLIENT_OPTIONS["maxPoolSize"] == 3, server.MONGO_CLIENT_OPTIONS["maxPoolSize"])
    check("no build id (local, tests): never « seeded », nothing skipped", BM.seeded(db) is False)
    os.environ["VERCEL_GIT_COMMIT_SHA"] = BUILD
    BM.forget()
    check("a fresh deployment: not seeded yet", BM.seeded(db) is False)
    BM.mark(db)
    BM.forget()
    with Counter(db) as c:
        check("the next instance reads ONE marker…", BM.seeded(db) is True)
        ones = [x for x in c.calls if x[0] == "find_one"]          # mongomock's find_one calls find inside
        check("…and only one", ones == [("find_one", "platform_settings")], c.calls)
        BM.seeded(db)
        check("…then answers from memory, zero reads", [x for x in c.calls if x[0] == "find_one"] == ones, c.calls)
    os.environ["VERCEL_GIT_COMMIT_SHA"] = "build-NEW"
    BM.forget()
    check("a NEW deployment seeds again", BM.seeded(db) is False)
    os.environ["VERCEL_GIT_COMMIT_SHA"] = BUILD
    BM.forget()

    # ------------------------------------------------------------------ every seed site skips
    print("\nCe que chaque module saute quand le déploiement est déjà amorcé")
    sites = [
        ("platform_access (team roles)", lambda: PA.init(db), ("platform_roles",)),
        ("team_tasks (types, priorities, fonctions)", lambda: TT.init(db),
         ("team_task_types", "team_task_priorities", "team_fonctions")),
        ("crm_email (templates)", lambda: CE.init(db), ("crm_email_templates",)),
        ("journal_stats (backfill)", lambda: JS.init(db), ("brain_predictions",)),
        ("push_wallet (scenario clean-up)", lambda: PW.init(db), ("push_scenarios", "push_scenario_overrides")),
        ("support_center (migration)", lambda: SC.init(db), ("support_tickets", "support_messages")),
        ("onboarding (sector rewards sweep)", lambda: OB.init(db), ("card_templates",)),
    ]
    for label, run, colls in sites:
        with Counter(db) as c:
            run()
            touched = [x for coll in colls for x in c.of(coll)]
            check(f"{label}: zero reads or writes", not touched, touched[:4])
    from features import merchant_api as MA, automations as AUX, join_link as JL
    for label, run, colls in [
        ("merchant_api (phone tails backfill)", lambda: MA.backfill_phone_tails() if False else MA.init(db), ("customers",)),
        ("automations (old birthday switches)", lambda: AUX.honour_at_start(), ("automation_meta", "automations")),
        ("join_link (inline signup images)", lambda: JL.init(db), ("tenants", "signup_images")),
    ]:
        with Counter(db) as c:
            run()
            touched = [x for coll in colls for x in c.of(coll)]
            check(f"{label}: zero reads or writes", not touched, touched[:4])
    with Counter(db) as c:
        server._media_migrate_once()
        check("server start migration « media migrate »: zero work", not c.calls, c.calls[:4])
    with Counter(db) as c:
        BM.mark(db)
        check("mark() on an already-seeded instance writes nothing", not c.calls, c.calls)
    for fn, coll, label in [(server._points_split_once, "customers", "points split"),
                            (server._drop_student_flag_once, "customers", "étudiant flag"),
                            (server._cache_purge_once, "img_cache", "image cache purge")]:
        with Counter(db) as c:
            fn()
            check(f"server start migration « {label} »: zero work", not c.of(coll) and not c.of("platform_settings"),
                  c.calls[:4])

    # ------------------------------------------------------------------ the first instance still seeds
    print("\nLa première instance du déploiement amorce tout, comme avant")
    os.environ["VERCEL_GIT_COMMIT_SHA"] = "build-fresh"
    BM.forget()
    db.platform_roles.delete_many({})
    with Counter(db) as c:
        PA.init(db)
        check("roles seeded on a fresh deployment", db.platform_roles.count_documents({}) >= 5, len(c.calls))
    db.team_task_types.delete_many({})
    TT.init(db)
    check("team task types seeded on a fresh deployment", db.team_task_types.count_documents({}) > 0)
    os.environ.pop("VERCEL_GIT_COMMIT_SHA", None)
    BM.forget()
    db.platform_roles.delete_many({})
    PA.init(db)
    check("locally (no build id) the seeds always run", db.platform_roles.count_documents({}) >= 5)

    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
