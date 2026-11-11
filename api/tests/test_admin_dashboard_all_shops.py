"""
Super admin › Dashboard (user, 2026-11-11): « CA total pr click kiya toh bas
2 shops aa rhi jabki aur shops ka bhi usme contribution hai ». The total
counts every visit of every shop; its list must show EVERY shop — deleted,
suspended, résiliée, trial over — or the list does not add up to the figure.

And a new figure beside it: Impact FidClic — what FidClic brought (the same
CA FidClic each owner sees), its total and its breakdown by shop, every shop
included too.

Run: cd api && python3 -u tests/test_admin_dashboard_all_shops.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-dashboard-all-shops")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail!r}"))


def main():
    import server
    import auth
    import httpx
    from features import admin_dashboard as D, visit_days as VD

    db = server.db
    NOW = dt.datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
    D._now = lambda: NOW
    VD._now = lambda: NOW

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    at = lambda *a: dt.datetime(*a, tzinfo=UTC)          # noqa: E731
    shops = {
        "rt": {"name": "ROYAL TRIM", "subscription_status": "trialing", "trial_ends_at": at(2026, 10, 30)},   # trial over
        "gs": {"name": "Green Smoke", "subscription_status": "active"},
        "del": {"name": "Supprimé SARL", "subscription_status": "active", "is_active": False},             # deleted
        "sus": {"name": "Suspendu & Co", "subscription_status": "active", "suspended_at": at(2026, 11, 1)},
        "res": {"name": "Résilié Bar", "subscription_status": "active", "resiliated_at": at(2026, 11, 5)},
        "zero": {"name": "Sans visite", "subscription_status": "active"},
    }
    for tid, t in shops.items():
        db.tenants.insert_one({"id": tid, "slug": tid, "plan": "vip", "is_active": True, "created_at": at(2026, 9, 1), **t})
        db.users.insert_one({"email": f"own@{tid}.fr", "role": "business_owner", "tenant_id": tid})
    db.users.insert_one({"email": "admin@fidclic.com", "role": "super_admin", "tenant_id": None})
    A = {"Authorization": "Bearer " + auth.create_access_token({"sub": "admin@fidclic.com", "role": "super_admin"})}

    amounts = {"rt": [40, 25.5], "gs": [10], "del": [30], "sus": [12], "res": [8]}
    n = 0
    for tid, xs in amounts.items():
        for i, x in enumerate(xs):
            n += 1
            cid = f"{tid}-c{i}"
            db.customers.insert_one({"id": cid, "tenant_id": tid, "name": f"Client {n}", "created_at": at(2026, 10, 20)})
            db.visits.insert_one({"id": f"v{n}", "tenant_id": tid, "customer_id": cid, "amount_paid": x,
                                  "visit_time": at(2026, 11, 3 + i, 11, 0)})
    # filleuls: every visit of a client who joined through a parrain is FidClic's
    for tid, cid in (("rt", "rt-c0"), ("del", "del-c0"), ("gs", "gs-c0")):
        db.referral_redemptions.insert_one({"tenant_id": tid, "referee_customer_id": cid, "referrer_customer_id": "p",
                                            "created_at": at(2026, 10, 20)})
    Q = {"from": "2026-10-12", "to": "2026-11-11"}

    # ------------------------------------------------------------------ CA
    print("CA total : toutes les boutiques")
    dash = http("GET", "/api/admin/dashboard", headers=A, params=Q).json()
    K = {k["key"]: k for k in dash["kpis"]}
    total = K["ca"]["value"]
    check("the CA figure counts every shop's visits (125.5 €)", abs(total - 125.5) < 0.01, total)
    r = http("GET", "/api/admin/dashboard/list/ca", headers=A, params=Q)
    rows = {x["id"]: x for x in r.json()["rows"]}
    check("its list shows EVERY shop — trial over, deleted, suspended, résiliée, none missing",
          set(rows) == set(shops), sorted(rows))
    check("…the list adds up to the figure", abs(sum(x["metric"] for x in rows.values()) - total) < 0.01,
          sum(x["metric"] for x in rows.values()))
    check("…each shop with its own CA", rows["rt"]["metric"] == 65.5 and rows["del"]["metric"] == 30 and rows["zero"]["metric"] == 0,
          {k: v["metric"] for k, v in rows.items()})
    check("…highest first", [x["id"] for x in r.json()["rows"]][:2] == ["rt", "del"], [x["id"] for x in r.json()["rows"]])
    check("…a deleted shop says so", rows["del"].get("deleted") is True and rows["gs"].get("deleted") is False, rows["del"])
    check("…its situation is still told (résilié, suspended)",
          rows["res"]["standing"] == "resilie" and rows["sus"]["standing"] == "impaye" and rows["rt"]["standing"] == "non_converti",
          {k: v["standing"] for k, v in rows.items()})
    rev = dash.get("revenue") or {}
    check("« Répartition du chiffre d'affaires » counts the deleted shop too (= the total)",
          abs((rev.get("total") or 0) - total) < 0.01, rev)

    # ------------------------------------------------------------------ Impact FidClic
    print("\nImpact FidClic : total + par boutique")
    imp = K.get("impact")
    check("a figure « impact » is on the dashboard", imp is not None, list(K))
    own = {}
    for tid in shops:
        own[tid] = VD.span_many(tid, None, [(at(2026, 10, 12) - dt.timedelta(hours=2), at(2026, 11, 11, 23, 0))])[0].impact()["revenue"]
    expect = round(sum(own.values()), 2)
    check("…its total is the sum of what each owner reads as CA FidClic", imp and abs(imp["value"] - expect) < 0.01,
          (imp and imp["value"], expect, own))
    check("…the filleuls' visits are in it (rt 40 + del 30 + gs 10 = 80 €)", imp and abs(imp["value"] - 80) < 0.01, imp and imp["value"])
    check("…with a delta and a curve like the other figures", imp and "delta" in imp and isinstance(imp.get("series"), list)
          and len(imp["series"]) == len(K["ca"]["series"]), imp)
    r = http("GET", "/api/admin/dashboard/list/impact", headers=A, params=Q)
    check("the « impact » list opens", r.status_code == 200, r.text[:200])
    j = r.json()
    rows = {x["id"]: x for x in j.get("rows") or []}
    check("…every shop in it, deleted / suspended / résiliée too", set(rows) == set(shops), sorted(rows))
    check("…each shop's CA FidClic", rows.get("rt", {}).get("metric") == 40 and rows.get("del", {}).get("metric") == 30
          and rows.get("sus", {}).get("metric") == 0, {k: v.get("metric") for k, v in rows.items()})
    check("…adds up to the figure", imp and abs(sum(x["metric"] for x in rows.values()) - imp["value"]) < 0.01)
    check("…says its period and what the number is", j.get("metric_label") == "CA FidClic" and j.get("period", {}).get("from") == "2026-10-12", j.get("metric_label"))
    check("…the visits FidClic brought, per shop", rows.get("rt", {}).get("visits") == 1, rows.get("rt"))

    # ------------------------------------------------------------------ the other lists unchanged
    print("\nLes autres listes ne changent pas")
    com = {x["id"] for x in http("GET", "/api/admin/dashboard/list/commerces", headers=A, params=Q).json()["rows"]}
    check("« Commerces » still = trial + paying only (no deleted, no résilié)", "del" not in com and "res" not in com and "gs" in com, sorted(com))

    # ------------------------------------------------------------------ rights
    print("\nDroits")
    O = {"Authorization": "Bearer " + auth.create_access_token({"sub": "own@gs.fr", "role": "business_owner", "tenant_id": "gs"})}
    check("a business owner cannot open the impact list (403)", http("GET", "/api/admin/dashboard/list/impact", headers=O).status_code == 403)
    check("an unknown list → 404", http("GET", "/api/admin/dashboard/list/nope", headers=A).status_code == 404)

    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
