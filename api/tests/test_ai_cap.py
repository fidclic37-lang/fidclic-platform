"""
The platform's daily AI cap grows with the shops (user, 2026-11-04): active
shops × 2 €, never under 20 € nor over 200 € a day; each shop at most 2 € a
day whatever the cap; the super admin may change each number or fix the cap
by hand (0 still stops every call).

Run: cd api && /usr/local/bin/python3 tests/test_ai_cap.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-ai-cap")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ["ANTHROPIC_API_KEY"] = "test-key"
for _k in ("LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "NVIDIA_API_KEY"):
    os.environ.pop(_k, None)
passed = failed = 0
UTC = dt.timezone.utc


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
    import auth
    import httpx
    from features import ai_meter as AM, platform_access as PA
    from services import llm, mailer

    db = server.db
    mailer.send = lambda *a, **k: {"sent": True}
    clock = [dt.datetime(2026, 11, 10, 9, 0, tzinfo=UTC)]
    AM._now = lambda: clock[0]
    AM._send = lambda url, headers, body, timeout: (200, {"content": [{"type": "text", "text": "Bonjour à vous"}],
                                                          "usage": {"input_tokens": 100, "output_tokens": 50}})

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.users.insert_many([{"email": "boss@fidclic.com", "role": "super_admin", "active": True},
                          {"email": "read@fidclic.com", "role": "fidclic_team", "platform_role": "ai_read", "active": True}])
    db.platform_roles.insert_one({"id": "ai_read", "name": "IA lecture", "perms": {"ai": {"view": True, "edit": False}}})
    BOSS = {"Authorization": "Bearer " + auth.create_access_token({"sub": "boss@fidclic.com", "role": "super_admin", "tenant_id": None})}
    READER = {"Authorization": "Bearer " + auth.create_access_token({"sub": "read@fidclic.com", "role": "fidclic_team", "tenant_id": None})}

    def shops(n_active, n_trial=0, extra=()):
        db.tenants.delete_many({})
        rows = [{"id": f"a{i}", "name": f"A{i}", "plan": "gold", "subscription_status": "active", "is_active": True} for i in range(n_active)]
        rows += [{"id": f"t{i}", "name": f"T{i}", "plan": "vip", "subscription_status": "trialing", "is_active": True,
                  "trial_ends_at": clock[0] + dt.timedelta(days=10)} for i in range(n_trial)]
        if rows or extra:
            db.tenants.insert_many(rows + list(extra))
        AM._ACTIVE.clear()

    def reset(**settings):
        for c in ("ai_calls", "ai_spend", "ai_cache", "ai_blocks", "ai_rate", "platform_alerts"):
            db[c].delete_many({})
        db.platform_settings.delete_many({"key": "ai_meter"})
        if settings:
            db.platform_settings.insert_one({"key": "ai_meter", **settings})
        AM._ACTIVE.clear()

    print("Le plafond suit les commerces")
    reset()
    shops(0)
    check("no shop: the floor, 20 €", AM.global_cap() == 20.0, AM.global_cap())
    shops(5)
    check("5 shops × 2 € = 10 € → still the floor, 20 €", AM.global_cap() == 20.0)
    shops(10)
    check("10 shops → 20 €", AM.global_cap() == 20.0)
    shops(11)
    check("11 shops → 22 €", AM.global_cap() == 22.0)
    shops(30, 15)
    check("30 paying + 15 on trial → 90 €", AM.global_cap() == 90.0, AM.global_cap())
    shops(100, 1)
    check("101 shops → the ceiling, 200 €", AM.global_cap() == 200.0)
    shops(12, 0, [{"id": "r", "subscription_status": "active", "is_active": True, "resiliated_at": clock[0]},
                  {"id": "u", "subscription_status": "past_due", "is_active": True},
                  {"id": "s", "subscription_status": "active", "is_active": True, "suspended_at": clock[0]},
                  {"id": "x", "subscription_status": "active", "is_active": False},
                  {"id": "e", "subscription_status": "trialing", "is_active": True, "trial_ends_at": clock[0] - dt.timedelta(days=1)},
                  {"id": "c", "subscription_status": "canceled", "is_active": True}])
    check("résiliés, unpaid, suspended, switched off, expired trials and cancelled ones do not count", AM.active_shops() == 12, AM.active_shops())

    print("Compté une fois toutes les 10 minutes")
    shops(20)
    check("20 shops → 40 €", AM.global_cap() == 40.0)
    db.tenants.insert_many([{"id": f"n{i}", "subscription_status": "active", "is_active": True} for i in range(10)])
    check("10 new shops: same cap within 10 minutes", AM.global_cap() == 40.0)
    clock[0] += dt.timedelta(minutes=11)
    check("…counted after 10 minutes", AM.global_cap() == 60.0, AM.global_cap())
    clock[0] = dt.datetime(2026, 11, 10, 9, 0, tzinfo=UTC)

    print("Un commerce : 2 € par jour, quel que soit le plafond")
    reset()
    shops(100)
    check("the shop's day limit is 2 €", AM._shop_day_cap() == 2.0)
    db.ai_spend.insert_one({"_id": AM.key_day("a1"), "eur": 1.999})
    with AM.scope(tenant_id="a1", feature="support"):
        check("past 2 € today: this shop is refused", llm.complete("s", "u") is None and AM.blocked_reason() == "shop_day")
    with AM.scope(tenant_id="a2", feature="support"):
        check("…another shop answers", llm.complete("s", "u") == "Bonjour à vous")
    reset(shop_day_eur=0.5)
    check("the super admin's number is used", AM._shop_day_cap() == 0.5)
    reset(cap_mode="fixed", global_day_eur=1.0)
    check("never more than the platform's cap itself", AM._shop_day_cap() == 1.0)

    print("Le plafond tient")
    reset()
    shops(10)
    db.ai_spend.insert_one({"_id": AM.key_day(None), "eur": 19.999})
    with AM.scope(tenant_id="a1", feature="support"):
        check("the platform's day full: refused, « global »", llm.complete("s", "u") is None and AM.blocked_reason() == "global")
    check("the alert names the cap in force", "20.00 €" in (db.platform_alerts.find_one({"kind": "ai_global"}) or {}).get("text", ""),
          db.platform_alerts.find_one({"kind": "ai_global"}))
    shops(50)
    with AM.scope(tenant_id="a1", feature="support"):
        check("more shops, a higher cap: answers again", llm.complete("s", "u") == "Bonjour à vous")

    print("Le super admin")
    reset(cap_mode="fixed", global_day_eur=0)
    shops(50)
    with AM.scope(tenant_id="a1", feature="support"):
        check("fixed at 0: every call stopped (the emergency switch)", llm.complete("s", "u") is None and AM.blocked_reason() == "global")
    reset(cap_mode="fixed", global_day_eur=35)
    check("fixed: his number, whatever the shops", AM.global_cap() == 35.0)
    reset(per_shop_eur=3, cap_min_eur=10, cap_max_eur=100)
    shops(20)
    check("his numbers in auto: 20 × 3 = 60 €", AM.global_cap() == 60.0)
    shops(40)
    check("…up to his ceiling", AM.global_cap() == 100.0)
    shops(1)
    check("…down to his floor", AM.global_cap() == 10.0)
    reset()
    shops(30)
    d = http("GET", "/api/admin/ai/costs", BOSS).json()
    check("the page says: auto, 30 shops, 60 €", d["summary"]["global_day_eur"] == 60.0 and d["summary"]["active_shops"] == 30
          and d["settings"]["cap_mode"] == "auto", d["summary"])
    check("…and the numbers behind it", {"per_shop_eur": 2.0, "cap_min_eur": 20.0, "cap_max_eur": 200.0, "shop_day_eur": 2.0}.items() <= d["settings"].items(),
          d["settings"])
    r = http("PUT", "/api/admin/ai/costs/settings", BOSS, json={"cap_mode": "fixed", "global_day_eur": 50})
    check("switch to fixed, 50 €", r.status_code == 200 and AM.global_cap() == 50.0, r.text[:200])
    check("audited", db.audit_logs.find_one({"action": "ai_meter.settings", "meta.cap_mode": "fixed"}))
    r = http("PUT", "/api/admin/ai/costs/settings", BOSS, json={"cap_mode": "auto", "per_shop_eur": 4, "cap_min_eur": 30, "cap_max_eur": 300, "shop_day_eur": 3})
    check("back to auto with his numbers", r.status_code == 200 and AM.global_cap() == 120.0 and AM._shop_day_cap() == 3.0, (r.text[:200], AM.global_cap()))
    for bad in ({"cap_mode": "maybe"}, {"per_shop_eur": -1}, {"cap_min_eur": 50, "cap_max_eur": 40}, {"cap_max_eur": 5000},
                {"shop_day_eur": -2}, {"cap_min_eur": {"$gt": 0}}):
        r = http("PUT", "/api/admin/ai/costs/settings", BOSS, json=bad)
        check(f"refused: {bad}", r.status_code == 422, r.status_code)
    r = http("PUT", "/api/admin/ai/costs/settings", BOSS, json={"cap_min_eur": 500})
    check("a floor above the ceiling already saved is refused", r.status_code == 422, (r.status_code, r.text[:200]))
    PA._cache.clear()
    r = http("PUT", "/api/admin/ai/costs/settings", READER, json={"cap_mode": "fixed", "global_day_eur": 0})
    check("a team member with « Voir » only cannot change it", r.status_code == 403 and AM.global_cap() == 120.0)
    check("nobody: refused", http("PUT", "/api/admin/ai/costs/settings", {}, json={"cap_mode": "fixed"}).status_code in (401, 403))

    print()
    print(f"{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
