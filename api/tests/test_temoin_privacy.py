"""
The groupe témoin stays anonymous to the shop (audit 2026-10-26, P26: the
old GET /api/owner/campaigns returned the whole campaign, its holdout_ids
with it). User decisions:
    · 2026-10-25: counts only (« 85 envoyés · 15 témoin »), never who
    · 2026-10-26: the campaign's name list shows everyone it TARGETED — the
      clients messaged and the témoin, mixed, sorted by name, no mark — so
      the témoin cannot be found by crossing the list with the client list

Every owner / manager GET route is walked after sends with a témoin (the
composer, the Clients page « Contacter (N) »), and none may carry the
témoin's ids as such.

Run: cd api && /usr/local/bin/python3 tests/test_temoin_privacy.py
"""
import asyncio
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-temoin-privacy")
os.environ.setdefault("DISABLE_SEED", "1")
UTC = dt.timezone.utc
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail}"))


def main():
    import server
    import auth
    import httpx
    import features.wallet_passes as WP
    import features.push_subscriptions as PS

    db = server.db
    server.dispatch_to_customer = lambda tid, cust, title, body, kind="campaign", url=None: {"sent": True}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    now = dt.datetime.now(UTC).replace(microsecond=0)
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "sector": "cafe", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps"})
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
                          {"email": "m@x.fr", "role": "manager", "tenant_id": "t1", "active": True}])
    tok = lambda e, r: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": "t1"})}  # noqa: E731
    H, MGR = tok("o@x.fr", "business_owner"), tok("m@x.fr", "manager")
    for i in range(60):
        db.customers.insert_one({"id": f"c{i:02d}", "tenant_id": "t1", "name": f"Client {60 - i:02d}", "visits": 2,
                                 "created_at": now - dt.timedelta(days=200), "barcode_id": f"B{i}",
                                 "last_visit_date": now - dt.timedelta(days=100)})

    # sends with a témoin, by every way the shop has
    r = http("POST", "/api/owner/campaigns/compose", headers=H,
             json={"title": "Une attention", "message": "Bonjour {prénom}", "audience": {"mode": "all"}})
    camp = db.campaigns.find_one({"id": r.json()["id"]}, {"_id": 0})
    held = set(camp.get("holdout_ids") or [])
    check(f"the composer's send has a témoin ({len(held)} of 60)", r.status_code == 200 and len(held) >= 7, r.text[:200])
    g = http("POST", "/api/owner/campaigns/send-to-group", headers=H,
             json={"customer_ids": [f"c{i:02d}" for i in range(40)], "title": "Groupe", "content": "Bonjour"})
    grp = db.campaigns.find_one({"id": (g.json() or {}).get("id")}, {"_id": 0}) or {}
    held_g = set(grp.get("holdout_ids") or [])
    check(f"« Contacter (N) » has its témoin too ({g.status_code}, {len(held_g)})", g.status_code == 200 and held_g, g.text[:200])
    secrets = held | held_g

    # ── 1. no route hands the témoin's ids out ──────────────────────────────────
    print("Toutes les routes GET du commerçant")
    fills = {"campaign_id": camp["id"], "cid": camp["id"], "id": camp["id"], "customer_id": sorted(held)[0],
             "slug": "cafe", "tenant_slug": "cafe"}
    skip = re.compile(r"/api/(admin|cron|super|public|auth|stripe|webhook|wallet/v1|passes)|/ws|oauth|/export|download|\.csv|/pdf|/qr")
    walked, leaks, errors = 0, [], []
    for route in server.app.routes:
        path = getattr(route, "path", "")
        if "GET" not in (getattr(route, "methods", None) or set()) or not path.startswith("/api/") or skip.search(path):
            continue
        names = re.findall(r"{(\w+)(?::[^}]*)?}", path)
        if any(n not in fills for n in names):
            continue
        url = re.sub(r"{(\w+)(?::[^}]*)?}", lambda m: str(fills[m.group(1)]), path)
        for who, h in (("owner", H), ("manager", MGR)):
            try:
                res = http("GET", url, headers=h)
            except Exception as exc:                               # a crash is not a leak; noted
                errors.append(f"{url} {type(exc).__name__}")
                continue
            walked += 1
            body = res.text
            if "holdout_ids" in body:
                leaks.append(f"{who} {url}: holdout_ids")
                continue
            try:
                data = res.json()
            except ValueError:
                continue

            def lists(x):
                if isinstance(x, list):
                    yield x
                    for y in x:
                        yield from lists(y)
                elif isinstance(x, dict):
                    for y in x.values():
                        yield from lists(y)
            for lst in lists(data):
                ids = {v for v in lst if isinstance(v, str)}
                if ids and (ids == held or ids == held_g):
                    leaks.append(f"{who} {url}: a list of exactly the témoin")
    check(f"walked {walked} owner / manager GET calls", walked > 80, errors[:5])
    check("none hands out the témoin as such", not leaks, leaks[:8])

    # ── 2. the old campaign list ───────────────────────────────────────────────
    print("L'ancienne liste des campagnes")
    rows = http("GET", "/api/owner/campaigns", headers=H).json()
    mine = next((c for c in rows if c.get("id") == camp["id"]), None)
    check("still lists the campaign, with its performance", mine and "performance" in mine)
    check("…without its témoin", mine and "holdout_ids" not in mine)
    for body in ({}, {"name": "Renommée"}):
        r = http("PUT", f"/api/owner/campaigns/{camp['id']}", headers=H, json=body)
        check(f"the old edit route answers without the témoin ({body or 'nothing to change'}: {r.status_code})",
              "holdout_ids" not in r.text, r.text[:160])

    # ── 3. the campaign's detail: everyone targeted, mixed ─────────────────────
    print("Le détail de la campagne")
    d = http("GET", f"/api/owner/campaigns/{camp['id']}/detail", headers=H).json()
    shown = [p["id"] for p in d.get("recipients_list") or []]
    targeted = set(camp["recipient_ids"]) | held
    check(f"the name list holds everyone targeted ({len(shown)} shown + {d.get('recipients_more')} more = {len(targeted)})",
          set(shown) <= targeted and len(shown) + int(d.get("recipients_more") or 0) == len(targeted)
          and held & set(shown), d.get("recipients_list") and len(d["recipients_list"]))
    from features.campaigns_page import _fold
    names = [p["name"] for p in d["recipients_list"]]
    check("…sorted by name: where a client sits says nothing", names == sorted(names, key=_fold))
    check("…the French way: « Élodie » with the E's", sorted(["Zoé", "Élodie", "Emma"], key=_fold) == ["Élodie", "Emma", "Zoé"])
    check("…and no mark tells who got it", all(set(p) == {"id", "name", "barcode_id"} for p in d["recipients_list"]),
          d["recipients_list"][:2])
    check("the list says what it is: « clients ciblés », with the témoin's count", d.get("recipients_targeted") is True
          and d["stats"]["temoin"]["counts"] == {"sent": len(camp["recipient_ids"]), "temoin": len(held)})
    big = http("GET", f"/api/owner/campaigns/{grp['id']}/detail", headers=H).json()
    check("the « Contacter » send: the same", set(p["id"] for p in big["recipients_list"]) & held_g
          and big.get("recipients_targeted") is True)
    small = http("POST", "/api/owner/campaigns/compose", headers=H,
                 json={"title": "Pour vous", "message": "Bonjour", "customer_ids": ["c01"], "template": "client"}).json()
    one = http("GET", f"/api/owner/campaigns/{small['id']}/detail", headers=H).json()
    check("a send without témoin: just who got it", [p["id"] for p in one["recipients_list"]] == ["c01"]
          and not one.get("recipients_targeted"))

    # ── 4. the old tracking (Analyses chart) ───────────────────────────────────
    print("Le suivi (graphique Analyses)")
    t = http("GET", f"/api/owner/campaigns/{camp['id']}/tracking", headers=H).json()
    ids = [p["customer_id"] for p in t.get("recipients") or []]
    check(f"lists everyone targeted ({len(ids)})", set(ids) == targeted, len(ids))
    tn = [p["customer_name"] for p in t["recipients"]]
    check("…sorted by name", tn == sorted(tn, key=_fold))
    check("…its rates still count those who got it",
          t["delivered_count"] == len(camp["recipient_ids"]) or t.get("targeted_count") == len(camp["recipient_ids"]), t)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
