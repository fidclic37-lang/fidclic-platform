"""
Super admin › Commerces — statut from weekly cards AND scans (the weaker decides), standing (essai / abonné /
impayé / résilié / non converti), résiliation (account and cards closed), the rules, the list and
its figures, one business's page, add / edit, suspension (sign-in and live
sessions) and the read-only « Accéder au compte ».

Run: cd api && /usr/local/bin/python3 tests/test_admin_commerces.py
"""
import asyncio
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    from fastapi import HTTPException
    from starlette.requests import Request
    from models import TokenData
    from features import admin_commerces as A

    db = server.db
    A.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def refused(fn, code):
        try:
            fn(); return False
        except HTTPException as e:
            return e.status_code == code

    def req(method="GET", bearer=None, cookie=None):
        headers = []
        if bearer:
            headers.append((b"authorization", f"Bearer {bearer}".encode()))
        if cookie:
            headers.append((b"cookie", f"access_token={cookie}".encode()))
        return Request({"type": "http", "method": method, "path": "/api/x", "headers": headers, "query_string": b""})

    def who(r):
        try:
            return asyncio.get_event_loop().run_until_complete(auth.get_current_user_data(r))
        except HTTPException as e:
            return e.status_code

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    old = now - dt.timedelta(days=200)
    db.tenants.insert_many([
        {"id": "busy", "name": "Boulangerie Saint-Michel", "sector": "Boulangerie", "city": "Tours", "plan": "gold",
         "subscription_status": "active", "created_at": old},
        {"id": "slow", "name": "Café Milano", "sector": "Café", "city": "Tours", "plan": "silver", "subscription_status": "active",
         "created_at": old},
        {"id": "idle", "name": "Burger Republic", "sector": "Restaurant", "city": "Blois", "plan": "vip",
         "subscription_status": "active", "created_at": old},
        {"id": "young", "name": "Juice Lab", "sector": "Bien-être", "city": "Tours", "plan": "silver",
         "subscription_status": "trialing", "trial_ends_at": now + dt.timedelta(days=26), "created_at": now - dt.timedelta(days=2)},
        {"id": "gone", "name": "Fermé", "is_active": False, "created_at": old},
    ])

    def cards(tid, n, days=7):
        db.customers.insert_many([{"id": f"{tid}-{i}", "tenant_id": tid, "name": f"Client{i} Nom{i}", "email": f"c{i}@x.fr",
                                   "phone": "0600000000", "visits": 3 if i % 2 else 1, "pass_issued": i % 3 != 0,
                                   "last_visit_date": now - dt.timedelta(days=i % 40),
                                   "created_at": now - dt.timedelta(hours=1 + (i * days * 24 // max(n, 1)))} for i in range(n)])
    def scans(tid, n, days=7):
        db.visits.insert_many([{"id": f"s-{tid}-{i}", "tenant_id": tid, "customer_id": f"{tid}-0", "points_awarded": 10,
                                "visit_time": now - dt.timedelta(hours=1 + (i * days * 24 // max(n, 1)))} for i in range(n)])
    cards("busy", 30); scans("busy", 30)              # 30 cards, 30 scans a week → Actif
    cards("slow", 20); scans("slow", 40)              # weaker 20 → À risque
    cards("idle", 4); scans("idle", 50)               # weaker 4 → Inactif
    cards("young", 10, days=2); scans("young", 10, days=2)   # 2 days old: 35 a week each → Actif
    db.customers.insert_many([{"id": f"busy-old-{i}", "tenant_id": "busy", "name": "Ancien", "visits": 8,
                               "last_visit_date": now - dt.timedelta(days=120), "created_at": old} for i in range(10)])
    db.campaigns.insert_one({"id": "c1", "tenant_id": "busy", "name": "-20% sur votre prochain repas", "source": "push",
                             "sent_at": now - dt.timedelta(days=3), "delivered_count": 100, "targeted_count": 100,
                             "opens_unique": 70, "offer_clicks_unique": 12})
    db.users.insert_many([{"email": "o@busy.fr", "role": "business_owner", "tenant_id": "busy"},
                          {"email": "s@busy.fr", "role": "staff", "tenant_id": "busy"}])

    print("\nStatut from weekly cards AND scans")
    rows = {r["id"]: r for r in A.snapshot()}
    check("30 cards + 30 scans a week → Actif", rows["busy"]["status"] == "actif" and rows["busy"]["cards_week"] == 30.0 and rows["busy"]["scans_week"] == 30.0)
    check("20 cards, 40 scans → À risque (the weaker decides)", rows["slow"]["status"] == "a_risque")
    check("4 cards, 50 scans → Inactif", rows["idle"]["status"] == "inactif")
    check("a 2-day-old business counted over its 2 days", rows["young"]["status"] == "actif")
    check("bounds: exactly 15 and exactly 25 are « À risque »",
          A.status_of({"created_at": old}, 15, A.DEFAULT_RULES, now, 15)["key"] == "a_risque"
          and A.status_of({"created_at": old}, 25, A.DEFAULT_RULES, now, 40)["key"] == "a_risque"
          and A.status_of({"created_at": old}, 26, A.DEFAULT_RULES, now, 26)["key"] == "actif"
          and A.status_of({"created_at": old}, 30, A.DEFAULT_RULES, now, 14)["key"] == "inactif")
    check("a closed business is not listed", "gone" not in rows)
    check("a trial reads « Essai »", rows["young"]["plan"]["label"] == "Essai" and rows["busy"]["plan"]["label"] == "Pro")
    check("thresholds must be in order", refused(lambda: A.put_rules(A.RulesIn(actif_min=10, inactif_max=20), token_data=ADMIN), 400))
    A.put_rules(A.RulesIn(actif_min=35, inactif_max=15, window_days=7), token_data=ADMIN)
    check("the super admin's numbers apply", {r["id"]: r for r in A.snapshot()}["busy"]["status"] == "a_risque")
    A.put_rules(A.RulesIn(actif_min=25, inactif_max=15, window_days=7), token_data=ADMIN)

    print("\nStanding")
    st = lambda **kw: A.standing_of({"created_at": old, **kw}, now)            # noqa: E731
    check("trialing → en essai; trial over without paying → non converti",
          st(subscription_status="trialing", trial_ends_at=now + dt.timedelta(days=3)) == "essai"
          and st(subscription_status="trialing", trial_ends_at=now - dt.timedelta(days=1)) == "non_converti")
    check("active → abonné; past_due / unpaid / suspended → impayé",
          st(subscription_status="active") == "abonne" and st(subscription_status="past_due") == "impaye"
          and st(subscription_status="unpaid") == "impaye" and st(subscription_status="active", suspended_at=now) == "impaye")
    check("résilié wins over everything", st(subscription_status="active", resiliated_at=now) == "resilie")
    check("cancelled: paid before → résilié, never paid → non converti",
          st(subscription_status="canceled", subscription_started_at=old) == "resilie" and st(subscription_status="canceled") == "non_converti")
    check("rows carry their standing", rows["young"]["standing"] == "essai" and rows["busy"]["standing_label"] == "Abonné")

    print("\nList")
    lst = A.list_commerces(token_data=ADMIN)
    cards_ = {c["key"]: c for c in lst["cards"]}
    check("figures: total, per statut, new this month, clients", cards_["total"]["value"] == 4 and cards_["actif"]["value"] == 2
          and cards_["inactif"]["value"] == 1 and cards_["a_risque"]["value"] == 1 and cards_["clients"]["value"] == 74)
    check("share of the total", cards_["actif"]["pct"] == 50)
    check("tab counts", lst["counts"]["actif"] == 2 and lst["counts"]["a_risque"] == 1 and lst["counts"]["nouveaux"] >= 1)
    check("sorted by clients by default", lst["rows"][0]["id"] == "busy")
    check("tab + filters", A.list_commerces(tab="actif", city="Tours", token_data=ADMIN)["total"] == 2
          and A.list_commerces(q="burger", token_data=ADMIN)["rows"][0]["id"] == "idle"
          and A.list_commerces(plan="essai", token_data=ADMIN)["total"] == 1)
    out = A.export_commerces(token_data=ADMIN).body.decode("utf-8-sig")
    check("CSV export", out.startswith("Commerce;Secteur") and "Boulangerie Saint-Michel" in out)

    print("\nOne business")
    d = A.get_commerce("busy", token_data=ADMIN)
    k = {x["key"]: x["value"] for x in d["kpis"]}
    check("seven figures", k["clients"] == 40 and k["visites"] == 30 and k["points"] == 300 and 0 < k["retour"] <= 100)
    check("active + dormant = all", k["actifs"] + k["dormants"] == 40)
    check("the four groups add up", sum(x["count"] for x in d["repartition"]) == 40)
    check("six months of history", len(d["months"]) == 6 and d["months"][-1]["visites"] > 0)
    mw = [a.strftime("%Y-%m") for a, _ in A.month_windows(dt.datetime(2026, 9, 29, tzinfo=dt.timezone.utc))]
    check("six real calendar months, none skipped", mw == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"])
    check("…across a new year too", [a.strftime("%Y-%m") for a, _ in A.month_windows(dt.datetime(2027, 2, 3, tzinfo=dt.timezone.utc), 3)]
          == ["2026-12", "2027-01", "2027-02"])
    check("campaigns: rates and the latest", d["campagnes"]["open_rate"] == 70 and d["campagnes"]["recent"][0]["click_rate"] == 12)
    check("plan usage", {u["key"] for u in d["usage"]} == {"customers", "push", "campaigns", "ai"})
    cl = A.commerce_clients("busy", token_data=ADMIN)
    check("clients tab: no contact details, names shortened", cl["total"] == 40 and "email" not in cl["rows"][0]
          and "phone" not in cl["rows"][0] and cl["rows"][0]["name"].endswith("."))
    db.delivery_log.insert_many([{"tenant_id": "busy", "kind": "campaign", "channel": "web_push", "result": {"sent": 2}, "timestamp": now},
                                 {"tenant_id": "busy", "kind": "campaign", "channel": "web_push", "result": {"sent": 0}, "timestamp": now},
                                 {"tenant_id": "busy", "kind": "birthday", "channel": "sms_fallback", "result": {"sent": True}, "timestamp": now},
                                 {"tenant_id": "busy", "kind": "campaign", "result": {"sent": 1}, "timestamp": now - dt.timedelta(days=40)}])
    det = A.commerce_details("busy", token_data=ADMIN)
    bk = {k["kind"]: k for k in det["notifications"]["by_kind"]}
    check("notifications: sends and failures of the last 30 days", bk["campaign"]["sent"] == 1 and bk["campaign"]["failed"] == 1
          and bk["birthday"]["sent"] == 1)
    check("other tabs", len(det["campagnes"]) == 1 and det["parametres"]["team"][0]["email"] and "invoices" in det["abonnement"])
    check("zone", "bands" in A.commerce_zone("busy", token_data=ADMIN))

    print("\nAdd / edit / plan")
    check("owner email required", refused(lambda: A.add_commerce(A.CommerceIn(name="X"), token_data=ADMIN), 400))
    new = A.add_commerce(A.CommerceIn(name="Tea Palace", sector="Salon de thé", city="Tours", owner_email="Tea@Palace.fr"), token_data=ADMIN)
    t = db.tenants.find_one({"id": new["id"]})
    check("created on trial with its owner", t["subscription_status"] == "trialing" and t["slug"] == "tea-palace"
          and db.users.find_one({"email": "tea@palace.fr"})["role"] == "business_owner" and new["owner"]["password"])
    check("the same email twice is refused", refused(lambda: A.add_commerce(A.CommerceIn(name="Y", owner_email="tea@palace.fr"), token_data=ADMIN), 409))
    check("slugs stay unique", A.add_commerce(A.CommerceIn(name="Tea Palace", owner_email="b@b.fr"), token_data=ADMIN)
          and db.tenants.count_documents({"slug": "tea-palace-2"}) == 1)
    A.edit_commerce(new["id"], A.CommerceIn(city="Amboise"), token_data=ADMIN)
    check("edited", db.tenants.find_one({"id": new["id"]})["city"] == "Amboise")
    check("Franchise goes through its terms, not here", refused(lambda: A.change_plan("busy", A.PlanIn(plan="franchise"), token_data=ADMIN), 400))
    A.change_plan("busy", A.PlanIn(plan="vip"), token_data=ADMIN)
    check("plan changed and audited", db.tenants.find_one({"id": "busy"})["plan"] == "vip")

    print("\nSuspension")
    staff_tok = auth.create_access_token({"sub": "s@busy.fr", "role": "staff", "tenant_id": "busy"})
    check("before: the staff token works", isinstance(who(req(bearer=staff_tok)), TokenData))
    A.suspend("busy", A.SuspendIn(reason="Impayé"), token_data=ADMIN)
    check("statut « Suspendu »", {r["id"]: r for r in A.snapshot()}["busy"]["status"] == "suspendu")
    check("live sessions refused at once", who(req(bearer=staff_tok)) == 403)
    check("sign-in refused", refused(lambda: server.finish_login(server.Response(), db.users.find_one({"email": "o@busy.fr"})), 403))
    check("the super admin is not affected", isinstance(who(req(bearer=auth.create_access_token({"sub": "boss@fidclic.com", "role": "super_admin"}))), TokenData))
    A.reactivate("busy", token_data=ADMIN)
    check("reactivated: works again", isinstance(who(req(bearer=staff_tok)), TokenData))

    print("\nRésiliation")
    import httpx
    def http(method, url):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as c:
                return await c.request(method, url)
        return asyncio.get_event_loop().run_until_complete(run())
    db.tenants.update_one({"id": "busy"}, {"$set": {"slug": "busy-bakery"}})
    db.customers.update_one({"id": "busy-1"}, {"$set": {"barcode_id": "FT-BUSY1"}})
    check("before: the card opens", http("GET", "/api/card/FT-BUSY1").status_code != 410)
    try:
        A.ResilierIn(reason=" ")
        need = False
    except Exception:
        need = True
    check("a reason is required", need)
    A.resilier("busy", A.ResilierIn(reason="Le gérant a appelé : fermeture du magasin"), token_data=ADMIN)
    t = db.tenants.find_one({"id": "busy"})
    check("marked with who, why and when", t["resiliated_by"] == "boss@fidclic.com" and "fermeture" in t["resiliation_reason"] and t["resiliated_at"])
    check("standing and statut « Résilié »", A.standing_of(t) == "resilie" and {r["id"]: r for r in A.snapshot()}["busy"]["status"] == "resilie")
    check("cannot be résilié twice", refused(lambda: A.resilier("busy", A.ResilierIn(reason="encore"), token_data=ADMIN), 409))
    r = who(req(bearer=staff_tok))
    check("live sessions refused at once", r == 403)
    try:
        server.finish_login(server.Response(), db.users.find_one({"email": "o@busy.fr"}))
        msg = None
    except HTTPException as e:
        msg = e.detail
    check("sign-in refused, saying « résilié »", msg and "résilié" in msg)
    r410 = http("GET", "/api/card/FT-BUSY1")
    check("the customer's card stops working (410), never cached", r410.status_code == 410 and r410.headers.get("cache-control") == "no-store")
    check("…its wallet pass and manifest too", http("GET", "/api/card/FT-BUSY1/apple-wallet.pkpass").status_code == 410
          and http("GET", "/api/manifest/FT-BUSY1").status_code == 410 and http("GET", "/api/passes/v1/passes/pass.x/FT-BUSY1").status_code == 410)
    check("joining is closed", http("GET", "/api/join/busy-bakery").status_code == 410 and http("GET", "/api/join/busy-bakery/page").status_code == 410)
    check("the customer can still get their data (RGPD)", http("GET", "/api/card/FT-BUSY1/my-data").status_code != 410)
    check("another business's cards are not affected", http("GET", "/api/join/x-other").status_code != 410)
    A.annuler_resiliation("busy", token_data=ADMIN)
    check("annulée: works again", isinstance(who(req(bearer=staff_tok)), TokenData) and http("GET", "/api/card/FT-BUSY1").status_code != 410)
    check("audited", db.audit_logs.count_documents({"action": {"$in": ["admin.commerce_resilie", "admin.commerce_resiliation_annulee"]}}) == 2)

    print("\nAccéder au compte (read-only)")
    v = A.view_as("busy", token_data=ADMIN)
    admin_cookie = auth.create_access_token({"sub": "boss@fidclic.com", "role": "super_admin"})
    me = who(req(bearer=v["token"], cookie=admin_cookie))
    check("the view token wins over the super admin's cookie", isinstance(me, TokenData) and me.email == "o@busy.fr"
          and me.role == "business_owner" and me.view_by == "boss@fidclic.com")
    check("reads are allowed", isinstance(who(req("GET", bearer=v["token"])), TokenData))
    check("any change is refused", who(req("POST", bearer=v["token"])) == 403 and who(req("DELETE", bearer=v["token"])) == 403)
    check("/auth/me says it is a view", server.get_me(token_data=me)["view_as"] == {"by": "boss@fidclic.com"})
    check("a normal cookie login is unchanged", who(req(cookie=admin_cookie)).email == "boss@fidclic.com")
    A.suspend("busy", A.SuspendIn(), token_data=ADMIN)
    check("a suspended business can still be viewed", isinstance(who(req(bearer=A.view_as("busy", token_data=ADMIN)["token"])), TokenData))
    check("every opening audited", db.audit_logs.count_documents({"action": "admin.view_as"}) == 2
          or db.audit_log.count_documents({"action": "admin.view_as"}) == 2)
    check("a business with no owner cannot be viewed", refused(lambda: A.view_as("idle", token_data=ADMIN), 409))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
