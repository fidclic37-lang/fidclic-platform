"""
Store scope — the establishment dropdown, and the Tableau de bord limited to
what each account may see.

Run:
    cd api && python3 tests/test_store_scope.py
"""
import asyncio
import json
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
    from features import clients_page as CP
    from features import campaigns_page as KP
    from features import analyses as AN
    from features import insights_page as IP
    from features import segmentation as SG
    from features import activity_history as AH
    from features import geolocation as GEO
    from features import referrals as RF
    from features import copilot as CO

    db = server.db
    for m in (S, T, DH, CP, KP, AN, IP, SG, AH, GEO, RF, CO):
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

    print("\nLa page Clients, limitée")
    total = lambda tok, store=None: CP.overview(request=Req(store), token_data=tok)["cards"][0]["value"]
    names = lambda tok, store=None: sorted(r["name"] for r in CP.list_page(request=Req(store), token_data=tok)["rows"])
    check("owner / all: every client", total(OWNER) == 4)
    check("owner / Orléans: Orléans' client", names(OWNER, "orleans") == ["Cleo"])
    check("administrateur: its establishments' clients only", names(ALI) == ["Ana", "Ben", "Dan"])
    # (Ana has a Blois visit by now — the manager's scan above)
    check("manager: Blois' clients only, whatever it asks", names(SARA, "orleans") == ["Ana", "Ben", "Dan"])
    check("the id list follows the same scope (what 'Contacter' writes to)",
          sorted(CP.list_ids(request=Req(), token_data=SARA)["ids"]) == ["c1", "c2", "c4"])
    check("so does the CSV export", "Cleo" not in CP.export_clients(request=Req(), token_data=ALI).body.decode("utf-8"))
    check("the Clients page opens to them", guard(SARA, CP.READERS, partial_ok=True) == 200)

    print("\nContacter un groupe")
    out = server.send_campaign_to_group({"customer_ids": ["c2", "c3"], "name": "Hello", "content": "Bonjour"},
                                        request=Req(), token_data=SARA)
    check("a manager's campaign reaches only its establishment's clients", out["recipient_ids"] == ["c2"])
    check("and records for which establishments it was sent",
          db.campaigns.find_one({"id": out["id"]})["store_ids"] == ["blois"])
    try:
        server.send_campaign_to_group({"customer_ids": ["c3"], "content": "x"}, request=Req(), token_data=SARA)
        refused = False
    except HTTPException:
        refused = True
    check("nobody from another establishment → refused, nothing sent", refused)
    out = server.send_campaign_to_group({"customer_ids": ["c1", "c3"], "content": "x"}, request=Req(), token_data=OWNER)
    check("the owner, on 'all', reaches anyone", sorted(out["recipient_ids"]) == ["c1", "c3"])

    print("\nFiltres enregistrés")
    seg = server.create_saved_segment(server.SavedSegmentRequest(name="Mes fidèles", filters={}), token_data=SARA)
    check("a manager may save its own filter", seg["created_by"] == "sara@c.fr")
    try:
        server.delete_saved_segment(seg["id"], token_data=ALI)
        other_deleted = True
    except HTTPException:
        other_deleted = False
    check("another account cannot delete it", other_deleted is False)
    check("its author can", server.delete_saved_segment(seg["id"], token_data=SARA)["status"] == "ok")

    print("\nLa page Campagnes, limitée")
    pg = KP.page(request=Req(), token_data=SARA)
    seg = {x["key"]: x["count"] for x in pg["segments"]}
    check("'Tous mes clients' counts the manager's establishment only", seg["all"] == 3)
    mine_recent = [r for r in pg["recent"] if r["name"] == "Promo"]
    check("an owner's campaign shows only the recipients from its establishment",
          mine_recent and mine_recent[0]["audience_count"] == 2)
    check("the owner still sees the whole campaign",
          [r for r in KP.page(request=Req(), token_data=OWNER)["recent"] if r["name"] == "Promo"][0]["audience_count"] == 3)
    out = KP.compose(KP.Compose(title="Café offert", message="Venez !", segment="all", draft=True),
                     request=Req(), token_data=SARA)
    doc = db.campaigns.find_one({"id": out["id"]})
    check("a manager's campaign goes to its establishment's clients", sorted(doc["recipient_ids"]) == ["c1", "c2", "c4"])
    check("and records its establishment and sender", doc["store_ids"] == ["blois"] and doc["sent_by"] == "sara@c.fr")
    out = KP.compose(KP.Compose(title="x", message="y", customer_ids=["c2", "c3"], draft=True), request=Req(), token_data=SARA)
    check("hand-picked clients from another establishment are dropped",
          db.campaigns.find_one({"id": out["id"]})["recipient_ids"] == ["c2"])
    try:
        KP.compose(KP.Compose(title="x", message="y", customer_ids=["c3"]), request=Req(), token_data=SARA)
        refused = False
    except HTTPException:
        refused = True
    check("none of its own → refused, nothing sent", refused)
    check("the administrateur reaches Tours + Blois",
          sorted(db.campaigns.find_one({"id": KP.compose(KP.Compose(title="a", message="b", draft=True),
                                                         request=Req(), token_data=ALI)["id"]})["recipient_ids"]) == ["c1", "c2", "c4"])
    check("Campagnes opens to them", guard(SARA, KP.SENDERS, partial_ok=True) == 200)

    print("\nLa page Analyses, limitée")
    strip = lambda tok, tab="vue", store=None: {x["key"]: x["value"] for x in
                                                 AN.analyses(request=Req(store), tab=tab, days=30, token_data=tok)["data"]["strip"]}
    own = strip(OWNER)
    blois = strip(SARA, store="orleans")
    check("owner / all and manager / Blois differ", own != blois)
    check("the manager's revenue is Blois' tills only (whatever it asks)",
          AN.Reader("t1", 30, S.resolve(SARA, Req("orleans"))).visits()
          and all(v.get("amount_paid") in (20.0, 4.0) for v in AN.Reader("t1", 30, S.resolve(SARA, Req())).visits()))
    check("its clients are Blois' clients", sorted(c["id"] for c in AN.Reader("t1", 30, S.resolve(SARA, Req())).customers()) == ["c1", "c2", "c4"])
    check("a campaign counts only Blois' recipients",
          all(set(c["recipient_ids"]) <= {"c1", "c2", "c4"} for c in AN.Reader("t1", 30, S.resolve(SARA, Req())).campaigns()))
    check("the CSV export follows the scope", "text/csv" in AN.export_analyses(request=Req(), days=30, token_data=SARA).media_type)
    check("Analyses opens to them", guard(SARA, AN.READERS, partial_ok=True) == 200)
    tabs_ok = True
    for key in AN.BUILDERS:
        try:
            AN.analyses(request=Req(), tab=key, days=30, token_data=SARA)
        except Exception as e:  # noqa: BLE001
            print("   tab failed:", key, e)
            tabs_ok = False
    check("every tab builds for a manager", tabs_ok)

    print("\nLa page Insights, limitée")
    shop_sara = IP.Shop("t1", now, S.resolve(SARA, Req("orleans")))
    check("its read of the shop is Blois' clients only", sorted(c["id"] for c in shop_sara.people) == ["c1", "c2", "c4"])
    check("and Blois' tills only", all(v.get("amount_paid") in (20.0, 4.0) for v in shop_sara.visits))
    check("the goal is Blois' own", IP.page(request=Req(), token_data=SARA)["goal"]["target"] == 200.0)
    check("the owner's page still reads the whole shop",
          len(IP.Shop("t1", now, S.resolve(OWNER, Req())).people) == 4 and IP.page(request=Req(), token_data=OWNER)["goal"]["target"] == 1000.0)
    db.segments.insert_one({"id": "sg1", "tenant_id": "t1", "name": "Tous", "rules": [], "created_at": now})
    try:
        tpl = IP.template("seg:sg1", request=Req(), token_data=SARA)
        seg_ok = set(tpl["audience"]["ids"]) <= {"c1", "c2", "c4"}
    except HTTPException as e:
        seg_ok = e.status_code in (403, 404)
    check("a segment's members, messaged from a manager, never include another establishment's", seg_ok)
    check("Insights opens to them", guard(SARA, IP.READERS, partial_ok=True) == 200)
    check("a campaign sent for Tours does not mark a recommendation used for Blois",
          (db.campaigns.insert_one({"id": "kt", "tenant_id": "t1", "template": "a_risque", "status": "sent",
                                    "sent_at": now, "store_ids": ["tours"]}),
           "a_risque" not in IP.used_templates("t1", now, scope=S.resolve(SARA, Req())))[1]
          and "a_risque" in IP.used_templates("t1", now, scope=S.resolve(ALI, Req())))

    print("\nLa page Segmentation, limitée")
    pg = SG.page(request=Req(), token_data=SARA)
    check("'Clients total' is the manager's establishment", pg["total_clients"] == 3)
    check("every segment counts its clients only", all(x["count"] <= 3 for x in pg["segments"]))
    check("the goal is Blois' own", pg["goal"]["target"] == 200.0)
    check("the preview counts its clients only", SG.preview(SG.Preview(rules=[]), request=Req(), token_data=SARA)["total"] == 3)
    mine_seg = SG.create(SG.SegmentIn(name="Blois fidèles", rules=[]), request=Req(), token_data=SARA)
    check("a manager creates a segment, counted on its establishment", mine_seg["count"] == 3 and mine_seg["created_by"] == "sara@c.fr")
    check("its members are its establishment's clients",
          sorted(SG.members(mine_seg["id"], request=Req(), token_data=SARA)["ids"]) == ["c1", "c2", "c4"])
    check("the owner, on 'all', sees everyone in the same segment",
          len(SG.members(mine_seg["id"], request=Req(), token_data=OWNER)["ids"]) == 4)
    try:
        SG.remove(mine_seg["id"], token_data=ALI)
        other = True
    except HTTPException:
        other = False
    check("another account cannot delete it", other is False)
    check("the owner can", SG.remove(mine_seg["id"], token_data=OWNER)["deleted"] is True)
    check("Segmentation opens to them", guard(SARA, SG.READERS, partial_ok=True) == 200)

    print("\nL'Historique, limité")
    db.audit_log.insert_one({"tenant_id": "t1", "action": "card.settings.updated", "at": now.isoformat(), "after": {"logo_url": 1}})
    feed = AH.activity(request=Req(), date_from=None, date_to=None, tab="all", action=None, customer=None,
                       page=1, per_page=100, token_data=SARA)
    check("a manager's feed holds only its establishment's clients",
          all(r["customer_id"] in (None, "c1", "c2", "c4") for r in feed["rows"]))
    check("no scan from another establishment's till",
          feed["counts"].get("scan", 0) == db.visits.count_documents({"tenant_id": "t1", "branch_id": "blois"}))
    check("changes to the card (the whole shop's) are not in it", feed["counts"].get("card_update", 0) == 0)
    owner_feed = AH.activity(request=Req(), date_from=None, date_to=None, tab="all", action=None, customer=None,
                             page=1, per_page=100, token_data=OWNER)
    check("the owner's feed has every scan and the card change",
          owner_feed["counts"].get("scan", 0) == db.visits.count_documents({"tenant_id": "t1"})
          and owner_feed["counts"].get("card_update", 0) >= 1)
    check("the figures follow too", {c["key"]: c["value"] for c in AH.stats(request=Req(), date_from=None, date_to=None,
                                                                             token_data=SARA)["cards"]}["scan"]
          == feed["counts"].get("scan", 0))
    check("Historique opens to them", guard(SARA, AH.READERS, partial_ok=True) == 200)

    print("\nLa Géolocalisation, limitée")
    db.tenants.update_one({"id": "t1"}, {"$set": {"lat": 47.39, "lng": 0.69,
                                                  "branches": [{"id": "tours", "name": "Tours", "latitude": 47.39, "longitude": 0.69},
                                                               {"id": "blois", "name": "Blois", "latitude": 47.59, "longitude": 1.33},
                                                               {"id": "orleans", "name": "Orléans"}]}})
    for cid, lat in (("c1", 47.40), ("c2", 47.60), ("c3", 47.90), ("c4", 47.58)):
        db.customers.update_one({"id": cid}, {"$set": {"latitude": lat, "longitude": 1.0}})
    g = GEO.catchment(date_from=None, date_to=None, mode="car", scope="regional", request=Req(), token_data=SARA)
    check("the manager's map is centred on its establishment", round(g["shop"]["lat"], 2) == 47.59)
    check("and counts its clients only", g["clients_total"] <= 3)
    check("the owner's map is the shop's", round(GEO.catchment(date_from=None, date_to=None, mode="car", scope="regional",
                                                               request=Req(), token_data=OWNER)["shop"]["lat"], 2) == 47.39)
    check("Géolocalisation opens to them", guard(SARA, GEO.READERS, partial_ok=True) == 200)

    print("\nLe Parrainage, limité")
    db.referral_redemptions.insert_many([
        {"tenant_id": "t1", "referrer_customer_id": "c1", "referee_customer_id": "c2", "created_at": now, "referrer_points": 10},
        {"tenant_id": "t1", "referrer_customer_id": "c1", "referee_customer_id": "c3", "created_at": now, "referrer_points": 10},
    ])
    rf = lambda tok: {c["key"]: c["value"] for c in RF.overview(date_from=None, date_to=None, request=Req(), token_data=tok)["cards"]}
    check("a manager counts the parrainages that brought clients to its establishment", rf(SARA)["referrals"] == 1)
    check("the owner counts all of them", rf(OWNER)["referrals"] == 2)
    check("Parrainage opens to them", guard(SARA, RF.READERS, partial_ok=True) == 200)

    print("\nFidClic IA, limité")
    from services import llm
    seen = {}
    llm._force_complete = lambda sys_, user: (seen.__setitem__("prompt", user), "ok")[1]
    co = CO.page(horizon=30, days=30, request=Req(), token_data=SARA)
    acts = {c["key"]: c["value"] for c in co["activity"]["cards"]}
    check("a manager's activity is its establishment's tills", acts["visits"] == db.visits.count_documents(
        {"tenant_id": "t1", "branch_id": "blois", "visit_time": {"$gte": now - dt.timedelta(days=30)}}))
    owner_co = CO.page(horizon=30, days=30, request=Req(), token_data=OWNER)
    check("the owner's is the whole shop's", {c["key"]: c["value"] for c in owner_co["activity"]["cards"]}["visits"]
          == db.visits.count_documents({"tenant_id": "t1", "visit_time": {"$gte": now - dt.timedelta(days=30)}}))
    check("the 7-day plan is not offered to a manager", co["plan"]["available"] is False and co["plan"]["steps"] == [])
    check("the owner has it on the whole shop", owner_co["plan"]["available"] is True)
    check("… and not on a single establishment",
          CO.page(request=Req("tours"), token_data=OWNER)["plan"]["available"] is False)
    check("ideas that change the shop's settings are the owner's",
          all(r["kind"] != "setup" for r in co["recommendations"]["all"]))
    check("the page says which establishments it reads", co["scope"]["label"] == "Blois")
    CO.chat(CO.ChatIn(message="Analyser mes derniers résultats"), request=Req(), token_data=SARA)
    facts = json.loads(seen["prompt"].split("(JSON) :\n", 1)[1].split("\n\nQuestion", 1)[0])
    check("the chat is grounded on its establishment's clients only", facts["clients_total"] == 3
          and facts["etablissements"] == "Blois")
    check("each account keeps its own conversation",
          len(CO.chat_history(token_data=SARA)["messages"]) == 2 and CO.chat_history(token_data=OWNER)["messages"] == [])
    shown = [r["key"] for r in co["recommendations"]["all"]]
    if shown:
        CO.feedback(shown[0], CO.Feedback(kind="not_relevant"), request=Req(), token_data=SARA)
        check("a manager's 'pas pertinent' hides it for Blois only",
              shown[0] not in [r["key"] for r in CO.page(request=Req(), token_data=SARA)["recommendations"]["all"]]
              and CO._feedback("t1", now, S.ALL)[0] == set())
    CO.feedback("relance_inactifs", CO.Feedback(kind="later"), request=Req("tours"), token_data=OWNER)
    check("the owner's holds everywhere, even given on one establishment",
          "relance_inactifs" in CO._feedback("t1", now, "blois")[0])
    check("FidClic IA opens to them", guard(SARA, CO.READERS, partial_ok=True) == 200)
    check("Autopilot and the plan stay the owner's",
          guard(SARA, ["business_owner"]) == 403 and guard(ALI, ["business_owner"]) == 403)

    print("\nLa cloche")
    today = now.date().isoformat()
    db.copilot_plans.update_one({"tenant_id": "t1"}, {"$set": {"start": today, "autopilot": True,
                                 "steps": [{"id": "st1", "key": "relance_inactifs", "kind": "campaign", "offset": 0,
                                            "campaign_id": "kd"}]}}, upsert=True)
    db.campaigns.insert_one({"id": "kd", "tenant_id": "t1", "status": "draft", "targeted_count": 3})
    bell = lambda tok, store=None: server.get_proactive_alerts_multi_store(request=Req(store), token_data=tok)
    b_sara, b_ali, b_owner = bell(SARA), bell(ALI), bell(OWNER)
    check("a manager's bell covers its establishment only", b_sara["branches_covered"] == 1
          and all(a["branch_id"] == "blois" for a in b_sara["alerts"]))
    check("an administrateur's, its own", b_ali["branches_covered"] == 2
          and all(a["branch_id"] in ("tours", "blois") for a in b_ali["alerts"]))
    check("the owner's, every establishment", b_owner["branches_covered"] == 3)
    check("with one chosen in the menu, that one", bell(OWNER, "orleans")["branches_covered"] == 1)
    cop = lambda b: sum(1 for a in b["alerts"] if a["id"].startswith("copilot:"))
    check("FidClic IA's prepared step is said once, to the owner on the whole shop",
          cop(b_owner) == 1 and cop(b_sara) == 0 and cop(b_ali) == 0 and cop(bell(OWNER, "tours")) == 0)
    one = server.get_proactive_alerts(request=Req(), token_data=SARA)
    check("the single-shop alerts read its clients only", all(a["id"] != "copilot:st1" for a in one["alerts"]))
    check("asking for another establishment's alerts never widens",
          S.resolve(SARA, None, requested="tours").ids == ["blois"])
    check("the bell opens to them", guard(SARA, server.ALERT_READERS, partial_ok=True) == 200)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
