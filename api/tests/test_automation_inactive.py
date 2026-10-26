"""
Client inactif — from the user's mockups (2026-10-11): the five inactivity
tiles, a send date + hour inside a plage horaire, the Ciblage's new filters
(fréquence d'achat passée, programme de fidélité, origine, dernière offre) and
exclusions (contactés récemment, offre active), a daily limit spread over the
plage, the {offre} / {lien} variables, and the editor's right panels built
from real data only (audience now and a month ago, répartition, impact from
this shop's or its sector's measured relances — never made up).

Edge cases first: a refusal writes nothing, a client who comes back while
waiting gets nothing, an old automation keeps sending.

Run: cd api && /usr/local/bin/python3 tests/test_automation_inactive.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-automation-inactive")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    from features import temoin as _T
    _T.enabled = lambda tid: False    # groupe témoin: its own test (test_temoin); here every relance counts
    import auth
    import httpx
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import automations as AU

    db = server.db
    pushed = []

    def fake_dispatch(tid, cust, title, body, kind="campaign", url=None):
        pushed.append({"cid": cust.get("id"), "title": title, "body": body, "kind": kind, "url": url})
        return {"sent": True, "channel": "push"}
    server.dispatch_to_customer = fake_dispatch
    WP.notify_customer = lambda cid, message=None, google_notify=None: {}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    ago = lambda d: now - dt.timedelta(days=d)  # noqa: E731
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café Lumière", "plan": "vip", "subscription_status": "active",
         "is_active": True, "sector": "cafe"},
        {"id": "t2", "slug": "rival", "name": "Rival", "plan": "vip", "subscription_status": "active",
         "is_active": True, "sector": "cafe"},
    ])
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "m@x.fr", "role": "manager", "tenant_id": "t1"},
                          {"email": "s@x.fr", "role": "staff", "tenant_id": "t1"},
                          {"email": "r@x.fr", "role": "business_owner", "tenant_id": "t2"}])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, MGR, STAFF, H2 = tok("o@x.fr", "business_owner"), tok("m@x.fr", "manager"), tok("s@x.fr", "staff"), \
        tok("r@x.fr", "business_owner", "t2")
    db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 10, "reward_description": "Un café offert"})

    def person(cid, name, tid="t1", **kw):
        doc = {"id": cid, "tenant_id": tid, "name": name, "barcode_id": f"FT-{cid.upper()}", "points": 0, "visits": 3,
               "tier": "bronze", "created_at": ago(400), "last_visit_date": ago(2), **kw}
        db.customers.insert_one(doc)
        return doc
    # inactive since 100 / 95 / 70 / 40 days; active; a never-came client signed 200 days ago
    person("a", "Alice Martin", gender="F", birth_date="1995-03-03", visits=12, total_amount_paid=240, tier="gold",
           acquisition_source="instagram", last_visit_date=ago(100), created_at=ago(220))
    person("b", "Bruno Roy", gender="M", birth_date="1970-05-05", visits=2, total_amount_paid=20, tier="bronze",
           acquisition_source="qr_store", last_visit_date=ago(95))
    person("c", "Chloé Dubois", gender="F", birth_date="2001-01-01", visits=6, total_amount_paid=90, tier="silver",
           acquisition_source="insta", last_visit_date=ago(70))         # an alias: read as instagram
    person("d", "Driss Kader", visits=1, total_amount_paid=0, acquisition_source=None, last_visit_date=ago(40))
    person("e", "Emma Petit", visits=8, last_visit_date=ago(3))
    person("f", "Félix Noir", visits=0, last_visit_date=None, created_at=ago(200))
    person("z", "Rival client", tid="t2", last_visit_date=ago(300))
    # visits on record (the « month ago » count reads them)
    for cid, days in (("a", 100), ("b", 95), ("c", 70), ("d", 40), ("e", 3), ("e", 50)):
        db.visits.insert_one({"tenant_id": "t1", "customer_id": cid, "visit_time": ago(days), "amount_paid": 10})

    print("\n1. Ce que l'assistant accepte — et refuse sans rien écrire")
    base = {"scenario": "inactive", "name": "Clients inactifs", "status": "active",
            "trigger": {"days": 90, "repeat": "once"},
            "message": {"title": "Vous nous manquez {prénom} !",
                        "body": "{jours_absence} jours déjà ! {offre} chez {nom_commerce} : {lien}"},
            "targeting": {"mode": "filtered", "filters": {}, "exclusions": {"recent_contact": False, "active_offer": False}},
            "schedule": {"days": "specific", "weekdays": [0, 1, 2, 3, 4, 5, 6], "hour": "14:00", "window": True,
                         "window_from": "11:00", "window_to": "20:00", "daily_limit": 200,
                         "valid_from": now.date().isoformat()}}
    http("GET", "/api/owner/automations")                  # the shop's first visit sets its automations up
    count0 = db.automations.count_documents({"tenant_id": "t1"})

    def with_(patch):
        out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
        for k, v in patch.items():
            out[k] = {**out[k], **v} if isinstance(v, dict) and isinstance(out.get(k), dict) else v
        return out

    def bad(patch, why):
        r = http("POST", "/api/owner/automations", json=with_(patch))
        check(f"refused: {why} ({(r.json().get('detail') or '')[:70]})", r.status_code == 400)
    bad({"schedule": {"hour": "09:00"}}, "the hour outside the plage horaire")
    bad({"schedule": {"hour": "20:00"}}, "the hour at the plage's very end")
    bad({"schedule": {"window_from": "18:00", "window_to": "11:00"}}, "a plage that ends before it starts")
    bad({"schedule": {"daily_limit": -3}}, "a negative daily limit")
    bad({"schedule": {"daily_limit": 100001}}, "a daily limit over 100 000")
    bad({"schedule": {"daily_limit": "beaucoup"}}, "a daily limit that is not a number")
    bad({"trigger": {"days": 3}}, "an inactivity under 7 days")
    bad({"trigger": {"days": 400}}, "an inactivity over 365 days")
    bad({"targeting": {"mode": "filtered", "filters": {"past_freq": ["tous les jours"]}}}, "an unknown fréquence")
    bad({"targeting": {"mode": "filtered", "filters": {"tiers": ["diamant"]}}}, "an unknown statut")
    bad({"targeting": {"mode": "filtered", "filters": {"origin": ["pigeon"]}}}, "an unknown origine")
    bad({"targeting": {"mode": "filtered", "filters": {"last_offer": ["hier"]}}}, "an unknown dernière offre")
    bad({"schedule": {"days": "specific", "weekdays": []}}, "no day ticked")
    check("nothing was written by the refusals", db.automations.count_documents({"tenant_id": "t1"}) == count0)
    r = http("POST", "/api/owner/automations", json=with_({"schedule": {"hour": "11:00"}}), headers=STAFF)
    check("a staff member cannot create one", r.status_code == 403)

    r = http("POST", "/api/owner/automations", json=with_({"schedule": {"smart": True, "hour": "07:00"}}))
    check("with « Automatique — meilleur moment » the hour is the shop's, not checked against the plage", r.status_code == 200)
    db.automations.delete_one({"id": r.json()["id"]})
    r = http("POST", "/api/owner/automations", json=with_({"schedule": {"daily_limit": 0}}))
    check("a limit of 0 = no limit", r.status_code == 200 and db.automations.find_one({"id": r.json()["id"]})["schedule"]["daily_limit"] is None)
    db.automations.delete_one({"id": r.json()["id"]})
    r = http("POST", "/api/owner/automations", json=with_({"schedule": {"hour": "11:00"},
                                                          "targeting": {"mode": "all", "filters": {"tiers": ["gold"]},
                                                                        "exclusions": {"recent_contact": True}}}))
    row = db.automations.find_one({"id": r.json()["id"]})
    check("« all » keeps no filter but keeps the exclusions",
          r.status_code == 200 and row["targeting"]["filters"]["tiers"] == [] and row["targeting"]["exclusions"]["recent_contact"] is True)
    db.automations.delete_one({"id": row["id"]})

    r = http("POST", "/api/owner/automations", json=base)
    check("the mockup's automation is created", r.status_code == 200)
    aid = r.json()["id"]
    saved = db.automations.find_one({"id": aid})
    check("its hour, plage and daily limit are kept",
          saved["schedule"]["hour"] == "14:00" and saved["schedule"]["window"] is True
          and (saved["schedule"]["window_from"], saved["schedule"]["window_to"]) == ("11:00", "20:00")
          and saved["schedule"]["daily_limit"] == 200)
    page = http("GET", "/api/owner/automations").json()
    view = next(x for x in page["rows"] if x["id"] == aid)
    check("every day ticked is « Tous les jours »", saved["schedule"]["days"] == "all")
    check("the list says it: days, hour, plage and limit",
          view["schedule_text"] == "Tous les jours · 14:00 · entre 11:00 et 20:00 · 200 max/jour · à partir du "
          + dt.date.fromisoformat(base["schedule"]["valid_from"]).strftime("%d/%m/%Y"))
    inactive_meta = next(x for x in page["scenarios"] if x["key"] == "inactive")
    check("the chips' variables include {offre} and {lien}",
          {"offre", "lien", "jours_absence"} <= set(inactive_meta["variables"]))
    db.automations.delete_one({"id": aid})

    print("\n2. Le ciblage : les nouveaux filtres")
    at = now

    def who(filters=None, exclusions=None, mode="filtered", days=None):
        row = {"id": "x", "scenario": "inactive", "targeting": {"mode": mode, "filters": filters or {},
                                                                "exclusions": exclusions or {}}}
        ids = {c["id"] for c in db.customers.find({"tenant_id": "t1"}, {"_id": 0}) if AU.matches("t1", row, c, at, {})}
        return ids
    check("no filter = everyone", who() == {"a", "b", "c", "d", "e", "f"})
    check("visits per month: 12 visits over 120 days = 3 a month",
          round(AU.visits_per_month(db.customers.find_one({"id": "a"}), at), 1) == 3.0)
    check("« 3 à 4 visites / mois » finds Alice", "a" in who({"past_freq": ["3-4"]}) and "b" not in who({"past_freq": ["3-4"]}))
    check("a client who never came has no fréquence", "f" not in who({"past_freq": ["<1"]}))
    check("« Programme de fidélité »: Or", who({"tiers": ["gold"]}) == {"a"})
    check("Or or Argent (OR inside a group)", who({"tiers": ["gold", "silver"]}) == {"a", "c"})
    check("« Origine »: Instagram, the « insta » alias included", who({"origin": ["instagram"]}) == {"a", "c"})
    check("« Non renseigné » = no source", {"d", "e", "f"} <= who({"origin": ["none"]}) and "a" not in who({"origin": ["none"]}))
    check("groups narrow each other (AND): Instagram and Or", who({"origin": ["instagram"], "tiers": ["gold"]}) == {"a"})
    check("« mode all » ignores the filters", who({"tiers": ["gold"]}, mode="all") == {"a", "b", "c", "d", "e", "f"})
    # offers: a live one to Bruno, an old one (60 days, over) to Chloé
    db.campaigns.insert_many([
        {"id": "o-live", "tenant_id": "t1", "kind": "offre", "status": "sent", "sent_at": ago(2), "name": "-20 %",
         "recipient_ids": ["b"]},
        {"id": "o-old", "tenant_id": "t1", "kind": "offre", "status": "sent", "sent_at": ago(60), "name": "Ancienne",
         "recipient_ids": ["c"]},
        {"id": "news", "tenant_id": "t1", "kind": "nouveaute", "status": "sent", "sent_at": ago(1), "name": "Nouveau menu",
         "recipient_ids": ["a"]},
    ])
    check("« Dernière offre reçue » < 30 jours", who({"last_offer": ["<30"]}) == {"b"})
    check("« > 30 jours »", who({"last_offer": [">30"]}) == {"c"})
    check("« Aucune offre reçue » (a nouveauté is not an offer)", who({"last_offer": ["none"]}) == {"a", "d", "e", "f"})
    check("exclusion « offre active »: Bruno's offer still runs", who(exclusions={"active_offer": True}) == {"a", "c", "d", "e", "f"})
    db.push_notifications.insert_one({"tenant_id": "t1", "customer_id": "d", "type": "automation", "title": "Bonjour",
                                      "sent_at": ago(10), "automatic": True})
    db.push_notifications.insert_one({"tenant_id": "t1", "customer_id": "e", "type": "automation", "title": "Bonjour",
                                      "sent_at": ago(45), "automatic": True})
    recent = who(exclusions={"recent_contact": True})
    check("exclusion « contactés récemment »: a message 10 days ago, the news 1 day ago — out",
          "d" not in recent and "a" not in recent)
    check("…a message 45 days ago is not « récemment »", "e" in recent)
    check("exclusions also apply with « Tous mes clients » (mode all)", "d" not in who(mode="all", exclusions={"recent_contact": True}))

    print("\n3. Qui est dû, dans quel ordre")
    row = AU.new_doc("t1", "inactive", status="active", trigger={"days": 60, "repeat": "once"})
    db.automations.insert_one(dict(row))
    due = [c["id"] for c in AU._inactive_due("t1", row, at)]
    check("inactive 60+ days: Chloé (70), Bruno (95), Alice (100), Félix (never came, 200) — most recently lapsed first",
          due == ["c", "b", "a", "f"])
    db.automation_queue.insert_one({"id": "q0", "tenant_id": "t1", "automation_id": row["id"], "customer_id": "b",
                                    "due_at": at + dt.timedelta(hours=2), "ctx": {}, "created_at": at})
    check("a client already waiting in today's spread is not picked twice",
          "b" not in [c["id"] for c in AU._inactive_due("t1", row, at)])
    db.automation_queue.delete_many({})
    db.automation_log.insert_one({"id": "l0", "tenant_id": "t1", "automation_id": row["id"], "customer_id": "c",
                                  "sent_at": ago(5), "status": "sent"})
    check("once per absence: told 5 days ago and not back since — not again",
          "c" not in [x["id"] for x in AU._inactive_due("t1", row, at)])
    db.automations.update_one({"id": row["id"]}, {"$set": {"trigger.repeat": "every", "trigger.every_days": 7}})
    row2 = db.automations.find_one({"id": row["id"]}, {"_id": 0})
    check("relance every 7 days: not yet after 5 days", "c" not in [x["id"] for x in AU._inactive_due("t1", row2, at)])
    check("…and again after 8", "c" in [x["id"] for x in AU._inactive_due("t1", row2, at + dt.timedelta(days=3))])
    db.automations.delete_one({"id": row["id"]})
    db.automation_log.delete_many({})

    print("\n4. Limite par jour et étalement sur la plage")
    pushed.clear()
    paris_today = AU._paris(now).date()
    run_at = AU._from_paris(paris_today, 14, 5)            # just after the hour
    auto = AU.new_doc("t1", "inactive", status="active", trigger={"days": 60, "repeat": "once"},
                      message={"title": "Vous nous manquez {prénom}", "body": "{jours_absence} jours ! {offre} — {lien}"},
                      schedule={"days": "all", "hour": "14:00", "window": True, "window_from": "11:00",
                                "window_to": "20:00", "daily_limit": 2})
    db.automations.insert_one(dict(auto))
    s1 = AU.run_due(run_at, source="daily")
    sent_ids = [p["cid"] for p in pushed]
    check("without the 15-minute tick: the limit's 2 go now, the rest wait for tomorrow",
          s1["time_sent"] == 2 and sent_ids == ["c", "b"] and not db.automation_queue.find_one({"automation_id": auto["id"]}))
    body = pushed[0]["body"]
    check("{jours_absence}, {offre} and {lien} are filled",
          body.startswith("70 jours") and "-20 %" in body and "/c/" in body or ("70 jours" in body and "FT-C" in body))
    check("the run happens once a day", AU.run_due(run_at + dt.timedelta(minutes=30), source="daily")["time_sent"] == 0)
    pushed.clear()
    s2 = AU.run_due(run_at + dt.timedelta(days=1), source="daily")
    check("the next day: the next 2 (Alice, Félix), the first two not told again",
          [p["cid"] for p in pushed] == ["a", "f"])
    db.automations.delete_one({"id": auto["id"]})
    db.automation_log.delete_many({})
    db.push_notifications.delete_many({"type": "push_wallet"})

    pushed.clear()
    auto = AU.new_doc("t1", "inactive", status="active", trigger={"days": 60, "repeat": "once"},
                      schedule={"days": "all", "hour": "14:00", "window": True, "window_from": "11:00",
                                "window_to": "20:00", "daily_limit": 3})
    db.automations.insert_one(dict(auto))
    s3 = AU.run_due(run_at, source="tick")
    q = sorted(db.automation_queue.find({"automation_id": auto["id"]}, {"_id": 0}), key=lambda x: x["due_at"])
    end = AU._from_paris(paris_today, 20, 0)
    check("with the tick: the first goes now, the next two wait, spread over the plage",
          s3["time_sent"] == 1 and len(q) == 2 and all(run_at < AU._aware(x["due_at"]) < end for x in q))
    check("…evenly (about a third of the plage apart)",
          abs((AU._aware(q[1]["due_at"]) - AU._aware(q[0]["due_at"])) - (end - run_at) / 3) < dt.timedelta(minutes=1))
    # Bruno (2nd in line) comes back before his turn
    waiting = q[0]["customer_id"]
    db.customers.update_one({"id": waiting}, {"$set": {"last_visit_date": run_at + dt.timedelta(minutes=10)}})
    pushed.clear()
    AU.run_due(AU._aware(q[1]["due_at"]) + dt.timedelta(minutes=1), source="tick")
    check("a client who came back while waiting gets nothing; the other one gets it",
          waiting not in [p["cid"] for p in pushed] and q[1]["customer_id"] in [p["cid"] for p in pushed])
    db.customers.update_one({"id": waiting}, {"$set": {"last_visit_date": ago(95) if waiting == "b" else ago(100)}})
    db.automations.delete_one({"id": auto["id"]})
    db.automation_queue.delete_many({})
    db.automation_log.delete_many({})

    pushed.clear()
    legacy = AU.new_doc("t1", "inactive", status="active", trigger={"days": 60})     # before the mockups
    legacy["schedule"] = {**legacy["schedule"], "hour": "10:00", "window": False}
    legacy["targeting"]["mode"] = "all"
    db.automations.insert_one(dict(legacy))
    AU.run_due(AU._from_paris(paris_today, 10, 1), source="tick")
    check("an automation saved before the mockups keeps sending (no plage, no limit)", len(pushed) == 4)
    db.automations.delete_one({"id": legacy["id"]})
    db.automation_log.delete_many({})

    print("\n5. Les panneaux de droite : de vraies données")
    tg = {"mode": "filtered", "filters": {}, "exclusions": {}}
    r = http("POST", "/api/owner/automations/preview", json={"scenario": "inactive", "targeting": tg, "trigger": {"days": 60}})
    ins = r.json().get("inactive") or {}
    check("audience: 4 clients inactive 60+ days, none left out", r.status_code == 200 and ins.get("count") == 4
          and ins.get("lapsed") == 4 and ins.get("excluded") == 0)
    check("the other shop's client never counts", "z" not in str(ins))
    r = http("POST", "/api/owner/automations/preview",
             json={"scenario": "inactive", "targeting": {**tg, "filters": {"tiers": ["gold"]}}, "trigger": {"days": 60}})
    ins2 = r.json()["inactive"]
    check("a filter: 1 kept, 3 inactive left out (the donut)", ins2["count"] == 1 and ins2["excluded"] == 3)
    # a month ago: Alice (last before then: 100 d), Bruno (95 d), Félix (never came, joined 200 d) —
    # Chloé's 70 days were only 40 then, Driss and Emma came 40 / 50 days ago
    check("a month ago: who was inactive 60+ days then, from the visits on record", ins["month_ago"] == 3 and ins["delta"] == 33)
    ages = {x["key"]: x["pct"] for x in ins["breakdown"]["age"]}
    check("répartition by age, over the clients whose age is known (Félix's is not)",
          ages["18-25"] == 33 and ages["26-35"] == 33 and ages["50+"] == 33 and ages["36-50"] == 0)
    ch = {x["key"]: x["n"] for x in ins["breakdown"]["channel"]}
    check("canal d'acquisition: sur place 1, en ligne 2 (Instagram), autres 1", ch == {"store": 1, "online": 2, "other": 1})
    check("no relance measured yet: no impact figure is made up",
          ins["impact"]["rate"] is None and ins["impact"]["reactivated"] is None and ins["impact"]["revenue"] is None)
    # the sector's history: 3 other cafés, 30 relances, 9 came back within 15 days
    for i in range(3):
        db.tenants.insert_one({"id": f"p{i}", "name": f"Pair {i}", "sector": "cafe"})
    for i in range(30):
        tid = f"p{i % 3}"
        sent = ago(40)
        db.automation_log.insert_one({"id": f"s{i}", "tenant_id": tid, "scenario": "inactive", "customer_id": f"k{i}",
                                      "sent_at": sent, "status": "sent"})
        if i < 9:
            db.visits.insert_one({"tenant_id": tid, "customer_id": f"k{i}", "visit_time": sent + dt.timedelta(days=5)})
    ins = http("POST", "/api/owner/automations/preview",
               json={"scenario": "inactive", "targeting": tg, "trigger": {"days": 60}}).json()["inactive"]
    check("from 3 shops of the sector: 30 % potentiel de réactivation, 1 client of 4",
          ins["impact"]["basis"] == "sector" and ins["impact"]["rate"] == 0.3 and ins["impact"]["reactivated"] == 1)
    check("revenu potentiel = réactivés × panier moyen of these clients",
          ins["impact"]["basket"] == round((240 + 20 + 90) / (12 + 2 + 6 + 0), 2) and ins["impact"]["revenue"] == round(ins["impact"]["basket"]))
    # this shop's own history (20+ measured relances) wins
    for i in range(20):
        db.automation_log.insert_one({"id": f"own{i}", "tenant_id": "t1", "scenario": "inactive", "customer_id": f"own{i}",
                                      "sent_at": ago(30), "status": "sent"})
        if i < 10:
            db.visits.insert_one({"tenant_id": "t1", "customer_id": f"own{i}", "visit_time": ago(25)})
    ins = http("POST", "/api/owner/automations/preview",
               json={"scenario": "inactive", "targeting": tg, "trigger": {"days": 60}}).json()["inactive"]
    check("with 20 of its own measured relances: the shop's 50 %", ins["impact"]["basis"] == "shop" and ins["impact"]["rate"] == 0.5)
    db.automation_log.insert_one({"id": "young", "tenant_id": "t1", "scenario": "inactive", "customer_id": "y",
                                  "sent_at": ago(3), "status": "sent"})
    ins_b = http("POST", "/api/owner/automations/preview",
                 json={"scenario": "inactive", "targeting": tg, "trigger": {"days": 60}}).json()["inactive"]
    check("a relance sent 3 days ago is not measured yet (15-day window)", ins_b["impact"]["sends"] == 20)
    r = http("POST", "/api/owner/automations/preview", json={"scenario": "inactive", "targeting": tg, "trigger": {"days": 60}},
             headers=MGR)
    check("a manager sees the panels", r.status_code == 200 and "inactive" in r.json())
    r = http("POST", "/api/owner/automations/preview", json={"scenario": "inactive", "targeting": tg, "trigger": {"days": 60}},
             headers=STAFF)
    check("a staff member does not", r.status_code == 403)
    r = http("POST", "/api/owner/automations/preview", json={"scenario": "birthday", "targeting": tg})
    check("other scenarios are untouched (no inactive panel)", r.status_code == 200 and "inactive" not in r.json())
    r = http("POST", "/api/owner/automations/preview", json={"scenario": "inactive", "targeting": tg, "trigger": {"days": 2}})
    check("an inactivity under 7 days is read as 7", r.json()["inactive"]["days"] == 7)
    r2 = http("POST", "/api/owner/automations/preview", json={"scenario": "inactive", "targeting": tg, "trigger": {"days": 60}},
              headers=H2)
    check("the other shop sees only its own inactive client", r2.json()["inactive"]["count"] == 1)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
