"""
Store scope — the establishment dropdown, and the Tableau de bord limited to
what each account may see.

Run:
    cd api && python3 tests/test_store_scope.py
"""
import asyncio
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    import auth
    from fastapi import HTTPException
    from models import TokenData
    from features import store_scope as S
    from features import team_access as T
    from features import dashboard_home as DH

    db = server.db
    for m in (S, T, DH):
        m.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class Req:
        """The bits of a request the scope reads."""
        def __init__(self, store=None):
            self.headers = {S.HEADER: store} if store else {}
            self.query_params = {}

    def as_(email, role):
        return TokenData(email=email, role=role, tenant_id="t1")

    def guard(token, roles, partial_ok=False):
        try:
            asyncio.get_event_loop().run_until_complete(auth.require_role(roles, partial_ok=partial_ok)(token_data=token))
            return 200
        except HTTPException as e:
            return e.status_code

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "name": "Le Corner Café", "monthly_revenue_goal": 1000.0, "branches": [
        {"id": "tours", "name": "Tours"}, {"id": "blois", "name": "Blois"}, {"id": "orleans", "name": "Orléans"}]})
    db.users.insert_many([
        {"email": "owner@c.fr", "role": "business_owner", "tenant_id": "t1"},
        {"email": "ali@c.fr", "role": "administrateur", "tenant_id": "t1", "branch_ids": ["tours", "blois"], "active": True},
        {"email": "sara@c.fr", "role": "manager", "tenant_id": "t1", "branch_ids": ["blois"], "active": True},
    ])
    OWNER, ALI, SARA = as_("owner@c.fr", "business_owner"), as_("ali@c.fr", "administrateur"), as_("sara@c.fr", "manager")

    # clients: c1 Tours, c2 Blois, c3 Orléans, c4 signed up at Blois (no visit yet)
    db.customers.insert_many([
        {"id": "c1", "tenant_id": "t1", "name": "Ana", "visits": 6, "created_at": now - dt.timedelta(days=90), "last_visit_date": now},
        {"id": "c2", "tenant_id": "t1", "name": "Ben", "visits": 2, "created_at": now - dt.timedelta(days=90), "last_visit_date": now},
        {"id": "c3", "tenant_id": "t1", "name": "Cleo", "visits": 3, "created_at": now - dt.timedelta(days=90), "last_visit_date": now},
        {"id": "c4", "tenant_id": "t1", "name": "Dan", "visits": 0, "branch_id": "blois", "created_at": now - dt.timedelta(days=2)},
    ])
    db.visits.insert_many([
        {"id": "v1", "tenant_id": "t1", "customer_id": "c1", "branch_id": "tours", "amount_paid": 10.0, "visit_time": now - dt.timedelta(days=1)},
        {"id": "v2", "tenant_id": "t1", "customer_id": "c2", "branch_id": "blois", "amount_paid": 20.0, "visit_time": now - dt.timedelta(days=1)},
        {"id": "v3", "tenant_id": "t1", "customer_id": "c3", "branch_id": "orleans", "amount_paid": 40.0, "visit_time": now - dt.timedelta(days=1)},
        {"id": "v4", "tenant_id": "t1", "customer_id": "c3", "branch_id": None, "amount_paid": 5.0, "visit_time": now - dt.timedelta(days=1)},
    ])
    db.campaigns.insert_one({"id": "k1", "tenant_id": "t1", "name": "Promo", "sent_at": now - dt.timedelta(days=3),
                             "recipient_ids": ["c1", "c2", "c3"], "attributed_visit_customer_ids": ["c2", "c3"]})

    print("\nLe menu des établissements")
    check("the owner, on 'all', sees the whole shop (no filter)", S.resolve(OWNER, Req()).ids is None)
    check("the owner can pick any establishment", S.resolve(OWNER, Req("orleans")).ids == ["orleans"])
    check("an administrateur, by default, sees all of its own", S.resolve(ALI, Req()).ids == ["tours", "blois"])
    check("'all' means all of ITS establishments", S.resolve(ALI, Req("all")).ids == ["tours", "blois"])
    check("it can pick one of them", S.resolve(ALI, Req("blois")).ids == ["blois"])
    check("asking for one it does not manage never widens — it falls back to its own",
          S.resolve(ALI, Req("orleans")).ids == ["tours", "blois"])
    check("a manager is on its establishment whatever the menu says",
          S.resolve(SARA, Req("tours")).ids == ["blois"] and S.resolve(SARA, Req()).ids == ["blois"])
    check("clients of an establishment: who visited it or signed up there",
          S.customer_ids(S.resolve(SARA, Req())) == {"c2", "c4"})

    print("\nLe Tableau de bord, limité")
    def dash(tok, store=None):
        return DH.overview(request=Req(store), days=30, token_data=tok)
    cards = lambda d: {c["key"]: c["value"] for c in d["cards"]}
    d = dash(OWNER)
    check("owner / all: every visit, the untagged one included (75 €)", cards(d)["revenue"] == 75.0)
    check("and every client", cards(d)["clients"] == 4)
    d = dash(OWNER, "orleans")
    check("owner / Orléans: Orléans only (40 €, 1 client)", cards(d)["revenue"] == 40.0 and cards(d)["clients"] == 1)
    d = dash(ALI)
    check("administrateur: Tours + Blois only (30 €)", cards(d)["revenue"] == 30.0)
    check("its clients only (Ana, Ben, Dan)", cards(d)["clients"] == 3)
    check("a campaign counts only the recipients from its establishments",
          d["campaigns"]["touched"] == 2 and d["campaigns"]["sales"] == 1)
    d = dash(SARA, "orleans")
    check("manager: Blois only, even when asking for Orléans (20 €)", cards(d)["revenue"] == 20.0)
    check("the page says which establishments it shows", d["scope"]["label"] == "Blois")

    print("\nL'objectif du mois, par établissement")
    check("on 'all' it is the shop's goal", dash(OWNER)["goal"]["target"] == 1000.0)
    check("an establishment without its own goal shows none", dash(OWNER, "tours")["goal"]["is_set"] is False)
    DH.set_goal(DH.Goal(monthly_revenue_goal=300.0), request=Req("tours"), token_data=OWNER)
    DH.set_goal(DH.Goal(monthly_revenue_goal=200.0), request=Req("blois"), token_data=ALI)
    check("the owner sets Tours' goal, the administrateur Blois'",
          dash(OWNER, "tours")["goal"]["target"] == 300.0 and dash(SARA)["goal"]["target"] == 200.0)
    check("the administrateur's own set adds them up", dash(ALI)["goal"]["target"] == 500.0)
    check("the shop's goal is untouched", dash(OWNER)["goal"]["target"] == 1000.0)
    try:
        DH.set_goal(DH.Goal(monthly_revenue_goal=9.0), request=Req("orleans"), token_data=ALI)
        refused = False
    except HTTPException:
        refused = True
    check("not for an establishment it does not manage", refused)
    check("a manager cannot change a goal", dash(SARA)["goal"]["can_edit"] is False)

    print("\nQui entre")
    check("the Tableau de bord opens to an administrateur", guard(ALI, DH.READERS, partial_ok=True) == 200)
    check("and to a manager covering part of the shop", guard(SARA, DH.READERS, partial_ok=True) == 200)
    check("pages not brought over yet stay closed to them", guard(SARA, ["business_owner", "manager"]) == 403)

    print("\nLe scan reste dans son établissement")
    db.customers.update_one({"id": "c1"}, {"$set": {"barcode_id": "FT-SCOPE01"}})
    db.users.insert_one({"email": "old.staff@c.fr", "role": "staff", "tenant_id": "t1", "active": True})
    def scanned_branch(tok, branch):
        before = set(db.visits.distinct("id"))
        server.scan_visit(req=server.ScanRequest(barcode_id="FT-SCOPE01", amount_paid=4.0, branch_id=branch), token_data=tok)
        new = [v for v in db.visits.find({"customer_id": "c1"}) if v.get("id") not in before]
        return new[-1].get("branch_id") if new else "none"
    check("a manager's scan is tagged with its establishment, whatever the picker said",
          scanned_branch(SARA, "tours") == "blois")
    check("an administrateur may tag one of its own", scanned_branch(ALI, "tours") == "tours")
    try:
        scanned_branch(ALI, "orleans")
        refused = False
    except HTTPException:
        refused = True
    check("but not another shop's, when it has several to choose from", refused)
    # (an untagged scan falls back to the client's home establishment, as before)
    check("an older employé covering the whole shop scans as before, nothing forced",
          scanned_branch(as_("old.staff@c.fr", "staff"), None) == db.customers.find_one({"id": "c1"}).get("branch_id"))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
