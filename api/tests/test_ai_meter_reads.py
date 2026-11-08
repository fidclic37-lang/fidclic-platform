"""
One AI call read the meter's settings 12 times, the shop 3 times and its last
14 days twice (load probe of #447, 33 database calls per AI call on an Atlas M0
of 100 a second). Within one call each is now read once; between two calls
nothing is kept, so a change by the super admin counts on the very next call.

Run: cd api && /usr/local/bin/python3 tests/test_ai_meter_reads.py
"""
import collections
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-meter-reads")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ["ANTHROPIC_API_KEY"] = "test-key"
for _k in ("LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "NVIDIA_API_KEY"):
    os.environ.pop(_k, None)
passed = failed = 0


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", str(show)[:400])
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    from features import ai_meter as AM
    from services import llm

    db = server.db
    AM._send = lambda u, h, b, t: (200, {"content": [{"type": "text", "text": "Bonjour à vous"}], "usage": {"input_tokens": 100, "output_tokens": 50}})
    db.tenants.insert_one({"id": "s1", "name": "Shop", "plan": "gold", "subscription_status": "active", "is_active": True})
    ops = collections.Counter()

    class Spy:
        def __init__(self, c, n):
            self.c, self.n = c, n

        def __getattr__(self, a):
            f = getattr(self.c, a)
            if a in ("find_one", "find", "update_one", "insert_one", "count_documents", "aggregate", "find_one_and_update"):
                def w(*x, **k):
                    ops[self.n] += 1
                    return f(*x, **k)
                return w
            return f

    class Db:
        def __getattr__(self, n):
            return Spy(getattr(db, n), n)

    def one_call(text="u"):
        ops.clear()
        AM._db = Db()
        try:
            with AM.scope(tenant_id="s1", feature="support"):
                out = llm.complete("s", text)
        finally:
            AM._db = db
        return out

    one_call("warm")
    out = one_call()
    check("the call still answers", out == "Bonjour à vous")
    check("the settings: read once", ops["platform_settings"] == 1, dict(ops))
    check("the shop: read once", ops["tenants"] == 1, dict(ops))
    check("…in all, at most 20 database calls (33 before)", sum(ops.values()) <= 20, (sum(ops.values()), dict(ops)))

    print("Rien n'est gardé d'un appel à l'autre")
    db.platform_settings.update_one({"key": "ai_meter"}, {"$set": {"global_day_eur": 0, "cap_mode": "fixed"}}, upsert=True)
    check("a change written between two calls counts on the next one", one_call("x") is None)
    db.platform_settings.delete_many({"key": "ai_meter"})
    check("…and back", one_call("y") == "Bonjour à vous")
    db.tenants.update_one({"id": "s1"}, {"$set": {"ai_budget_eur": 0.0}})
    check("a shop budget set to 0 counts on the next call", one_call("z") is None)
    db.tenants.update_one({"id": "s1"}, {"$unset": {"ai_budget_eur": ""}})
    check("outside a call, settings() reads the database", AM.settings()["global_day_eur"] == 20.0
          and (db.platform_settings.update_one({"key": "ai_meter"}, {"$set": {"usd_eur": 0.5}}, upsert=True) and AM.settings()["usd_eur"] == 0.5))

    print("Une erreur dans l'appel ne laisse rien derrière")
    AM._send = lambda u, h, b, t: (_ for _ in ()).throw(RuntimeError("down"))
    with AM.scope(tenant_id="s1", feature="support"):
        llm.complete("s", "err")
    db.platform_settings.update_one({"key": "ai_meter"}, {"$set": {"usd_eur": 0.7}}, upsert=True)
    check("after a failed call, settings are fresh again", AM.settings()["usd_eur"] == 0.7)

    print("Coûts IA : la page de 300 commerces")
    import asyncio
    import auth
    import datetime as dt
    import httpx
    AM._send = lambda u, h, b, t: (200, {"content": [{"type": "text", "text": "Bonjour à vous"}], "usage": {"input_tokens": 100, "output_tokens": 50}})
    db.platform_settings.delete_many({"key": "ai_meter"})
    db.tenants.insert_many([{"id": f"p{i}", "name": f"P{i}", "plan": ("silver", "gold", "vip")[i % 3], "is_active": True,
                             "subscription_status": "trialing" if i % 7 == 0 else "active",
                             **({"ai_budget_eur": 40.0} if i % 11 == 0 else {})} for i in range(300)])
    now = AM._now()
    docs = []
    for i in range(0, 300, 2):
        docs.append({"_id": AM.key_month(f"p{i}"), "eur": (i % 9) * 0.7, **({"full": {"500": 0.2}} if i % 13 == 0 else {})})
        docs.append({"_id": AM.key_day(f"p{i}"), "eur": (i % 5) * 0.1})
        for d in range(1, 15, 4):
            docs.append({"_id": AM.key_day(f"p{i}", now - dt.timedelta(days=d)), "eur": 0.01 * d})
    db.ai_spend.insert_many(docs)
    expected = {f"p{i}": AM.state(f"p{i}") for i in range(300)}
    db.users.insert_one({"email": "boss@fidclic.com", "role": "super_admin", "active": True})
    BOSS = {"Authorization": "Bearer " + auth.create_access_token({"sub": "boss@fidclic.com", "role": "super_admin", "tenant_id": None})}

    def get(url):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(url, headers=BOSS)
        return asyncio.get_event_loop().run_until_complete(run())
    ops.clear()
    AM._db = Db()
    try:
        d = get("/api/admin/ai/costs").json()
    finally:
        AM._db = db
    rows = {r["tenant_id"]: r for r in d["shops"]}
    check("every shop's figures are the same as one by one", all(
        rows[t]["month_eur"] == round(e["month_eur"], 2) and rows[t]["pct"] == e["pct"]
        and rows[t]["state"] == (e["blocked"] or ("near" if e["pct"] >= 80 else "ok")) for t, e in expected.items()),
          [(t, rows[t], e) for t, e in expected.items() if rows[t]["pct"] != e["pct"]][:2])
    check("…at most 15 database calls for 300 shops", sum(ops.values()) <= 15, (sum(ops.values()), dict(ops)))
    check("after the page, a call reads fresh again", one_call("after-page") == "Bonjour à vous" and ops["platform_settings"] == 1)

    print()
    print(f"{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
