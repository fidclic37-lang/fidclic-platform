"""
FidClic IA « a repéré » (user, 2026-10-25): habitués en retard, pas revenus
après la 1ère visite (replaces « venus une seule fois »: from the shop's
rhythm × 1.5 or the owner's « bientôt perdu » if sooner, until the owner's
« dormant »), viennent moins souvent — on the Tableau de bord, in the bell
from 3 clients, as Clients chips, in Insights, with the composer pre-filled
and {produit_habituel}.

Run: cd api && /usr/local/bin/python3 tests/test_brain_detectors.py
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
os.environ.setdefault("JWT_SECRET", "test-secret-detectors")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", show)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import brain_detectors as BD
    from features import client_brain as CB
    from features import clients_page as CP
    from features import customer_rules as R

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(UTC).replace(microsecond=0)
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café", "sector": "cafe", "plan": "vip",
         "subscription_status": "active", "is_active": True},
        {"id": "t2", "slug": "strict", "name": "Strict", "sector": "cafe", "plan": "vip",
         "subscription_status": "active", "is_active": True},
    ])
    db.card_templates.insert_many([{"tenant_id": "t1", "programme": "stamps"}, {"tenant_id": "t2", "programme": "stamps"}])
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
                          {"email": "s@x.fr", "role": "staff", "tenant_id": "t1", "active": True}])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H = tok("o@x.fr", "business_owner")

    def client(cid, days_ago, tid="t1", items=None, amount=5.0):
        days_ago = list(days_ago)
        for d in days_ago:
            db.visits.insert_one({"tenant_id": tid, "customer_id": cid, "amount_paid": amount,
                                  "visit_time": now - dt.timedelta(days=d, hours=2),
                                  "items": [{"name": i} for i in (items or [])]})
        # no deleted_at at all, as a client who signed up (the bell reads « $exists: False »)
        db.customers.insert_one({"id": cid, "tenant_id": tid, "name": cid.capitalize(), "visits": len(days_ago),
                                 "created_at": now - dt.timedelta(days=(max(days_ago) if days_ago else 0) + 1),
                                 "last_visit_date": (now - dt.timedelta(days=min(days_ago), hours=2)) if days_ago else None,
                                 "total_amount_paid": amount * len(days_ago)})

    print("La fenêtre « 1ère visite »")
    w = BD.second_visit_window("t1", fresh=True)
    check("café: from 1.5 × its 7-day rhythm (10.5 days), to the owner's dormant (90)",
          w["start"] == 10.5 and w["end"] == 90 and w["by"] == "rythme" and not w["empty"], w)
    rules = R.load("t2")
    next(r for r in rules if r["key"] == "bientot_perdu")["conditions"][0]["value"] = 4
    next(r for r in rules if r["key"] == "dormant")["conditions"][0]["value"] = 8
    db.customer_status_config.update_one({"tenant_id": "t2"}, {"$set": {"tenant_id": "t2", "rules": rules}}, upsert=True)
    w2 = BD.second_visit_window("t2", fresh=True)
    check("a strict owner (bientôt perdu 4, dormant 8) wins: 4 → 8 days",
          w2["start"] == 4 and w2["end"] == 8 and w2["by"] == "boutique", w2)
    next(r for r in rules if r["key"] == "bientot_perdu")["conditions"][0]["value"] = 20
    db.customer_status_config.update_one({"tenant_id": "t2"}, {"$set": {"rules": rules}})
    w3 = BD.second_visit_window("t2", fresh=True)
    check("dormant (8) before the brain's start (10.5): empty, and said", w3["empty"])

    print("Les trois listes")
    client("new5", [5])                                       # too soon for a café
    client("new20", [20], items=["Cappuccino"])               # due back: in the list
    client("new120", [120])                                   # past dormant: the dormant list's business
    for i in range(3):
        client(f"late{i}", [18, 21, 24, 27], items=["Cappuccino", "Croissant"])   # every 3 days, 18 days silent
    client("slow", [60, 57, 54, 51, 48, 45, 40, 35, 25, 14, 4], items=["Thé"])    # gaps 3 → 10
    client("fine", [2, 5, 8, 11], items=["Cappuccino"])
    client("strict6", [6], tid="t2")
    CB.ensure("t1")
    CB.ensure("t2")
    people = BD.people("t1")
    found = {d["key"]: d for d in BD.detect("t1", people, now)}
    check("pas revenus après la 1ère visite: only the 20-day one", found["one_timers"]["ids"] == ["new20"], found["one_timers"])
    check("habitués en retard: the three late regulars", sorted(found["en_retard"]["ids"]) == ["late0", "late1", "late2"],
          found["en_retard"])
    check("viennent moins souvent: the slowing regular", found["moins_souvent"]["ids"] == ["slow"], found["moins_souvent"])
    check("each says why, with numbers", "jours de retard" in found["en_retard"]["why"]
          and "10 jours" in found["one_timers"]["why"] and "90" in found["one_timers"]["why"])
    check("bell from 3 clients only", found["en_retard"]["bell"] and not found["one_timers"]["bell"])
    db.customer_status_config.update_one({"tenant_id": "t2"}, {"$set": {"rules": R.load("t2")}})
    next(r for r in rules if r["key"] == "bientot_perdu")["conditions"][0]["value"] = 4
    db.customer_status_config.update_one({"tenant_id": "t2"}, {"$set": {"rules": rules}})
    BD.second_visit_window("t2", fresh=True)
    check("the strict owner's 6-day client is due (4 → 8)", CP.is_one_timer(
        db.customers.find_one({"id": "strict6"}, {"_id": 0}), now))

    print("Tableau de bord")
    r = http("GET", "/api/owner/brain/detectors", headers=H)
    d = {x["key"]: x for x in r.json()["detectors"]}
    check("the card's three lines, without the ids", r.status_code == 200 and d["en_retard"]["count"] == 3
          and "ids" not in d["en_retard"] and d["en_retard"]["template"] == "ia:en_retard")
    check("staff: refused", http("GET", "/api/owner/brain/detectors", headers=tok("s@x.fr", "staff")).status_code == 403)

    print("Clients")
    ov = http("GET", "/api/owner/clients/overview", headers=H).json()
    chips = {s["key"]: s["count"] for s in ov["segments"]}
    check("three chips with their counts", chips.get("en_retard") == 3 and chips.get("one_timers") == 1
          and chips.get("moins_souvent") == 1, chips)
    lst = http("GET", "/api/owner/clients/list", headers=H, params={"segment": "en_retard"}).json()
    check("a chip opens its clients", sorted(x["id"] for x in lst["rows"]) == ["late0", "late1", "late2"], lst.get("rows"))

    print("Cloche")
    al = {a["id"].split(":")[0] if isinstance(a.get("id"), str) else a.get("id"): a
          for a in http("GET", "/api/owner/insights/alerts", headers=H, params={"with_copilot": False}).json()["alerts"]}
    keys = " ".join(str(a.get("id")) + " " + str(a.get("title")) for a in al.values())
    check("« habitués en retard » rings (3)", "habitués sont en retard" in keys, keys)
    check("one client after a 1st visit: no bell", "1ère visite" not in keys)
    check("the old « venus qu'une fois » is gone", "venus qu'une fois" not in keys)

    print("Préparer le message")
    t = http("GET", "/api/owner/insights/templates/ia:en_retard", headers=H).json()
    check("the composer gets the list and words naming each one's product",
          sorted(t["audience"]["ids"]) == ["late0", "late1", "late2"] and "{produit_habituel}" in t["message"])
    c = db.customers.find_one({"id": "late0"})
    check("{produit_habituel} → « votre Cappuccino »",
          server.render_template("pour {produit_habituel}", c) == "pour votre Cappuccino")
    check("… « votre prochaine visite » when nothing stands out",
          server.render_template("pour {produit_habituel}", db.customers.find_one({"id": "new120"}))
          == "pour votre prochaine visite")

    print("Insights")
    recos = http("GET", "/api/owner/insights/page", headers=H).json()
    flat = str(recos)
    check("a recommendation for the late regulars, with its composer", "ia:en_retard" in flat)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
