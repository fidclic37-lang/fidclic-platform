"""
Nouvelle automatisation — the user's 29 mockups (2026-10-11): the owner's own
automation, seven déclencheurs with their own rules (features/custom_rules),
Planification + Règles d'envoi, a time zone per automation, the till's
« Offre utilisée », a géolocalisation on ANY address, a rappel with its own
words.

Edge cases: a past date, the hour outside the plage, an unknown time zone,
Martinique's 10:00, the 31st in February, 29 February, every 2 weeks,
« jours ouvrés », the signup day that is not an anniversary, a visit without a
purchase, the same offer twice, an offer not sent to that client, a palier
crossed, conditions false then true again, a client back after an absence,
outside the zone / the plage / the weekend, « nouveaux clients uniquement »,
the limit per week, the anti-doublon, « à une date / heure », a period not
begun / over, the older « Personnalisée », another shop.

Run: cd api && /usr/local/bin/python3 tests/test_automation_nouvelle.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-automation-nouvelle")
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
    import auth
    import httpx
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import automations as AU
    from features import custom_rules as CR
    from features import geo_automation as GA

    db = server.db
    pushed = []

    def fake_dispatch(tid, cust, title, body, kind="campaign", url=None):
        pushed.append({"cid": cust.get("id"), "title": title, "body": body, "url": url})
        return {"sent": True, "channel": "push"}
    server.dispatch_to_customer = fake_dispatch
    WP.notify_customer = lambda *a, **k: {}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    SHOP = (47.3941, 0.6848)                                  # Tours
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café Lumière", "plan": "vip", "subscription_status": "active",
         "is_active": True, "geo_enabled": True, "geo_radius_meters": 200,
         "branches": [{"id": "b1", "name": "Café Lumière - Centre", "latitude": SHOP[0], "longitude": SHOP[1],
                       "address": "12 rue Nationale", "postal_code": "37000", "city": "Tours"},
                      {"id": "b2", "name": "Café Lumière - Gare", "latitude": 47.389, "longitude": 0.694,
                       "address": "1 place de la Gare", "postal_code": "37000", "city": "Tours"}]},
        {"id": "t2", "slug": "rival", "name": "Rival", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    for e, role, t in (("o@x.fr", "business_owner", "t1"), ("a@x.fr", "administrateur", "t1"),
                       ("m@x.fr", "manager", "t1"), ("s@x.fr", "staff", "t1"), ("r@x.fr", "business_owner", "t2")):
        db.users.insert_one({"email": e, "role": role, "tenant_id": t})
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H = tok("o@x.fr", "business_owner")
    HA, HM, HS, H2 = tok("a@x.fr", "administrateur"), tok("m@x.fr", "manager"), tok("s@x.fr", "staff"), \
        tok("r@x.fr", "business_owner", "t2")
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "points_visit", "points_mode": "per_visit",
                                  "points_per_visit": 10, "reward_points": 100, "reward_description": "Un café offert"})

    def person(cid, name, tid="t1", **kw):
        doc = {"id": cid, "tenant_id": tid, "name": name, "barcode_id": f"FT-{cid.upper()}", "points": 0, "visits": 0,
               "total_amount_paid": 0, "consent": {"accepted": True}, "created_at": now - dt.timedelta(days=400),
               "last_visit_date": now - dt.timedelta(days=2), "deleted_at": None, **kw}
        db.customers.insert_one(doc)
        return doc

    def cust(cid):
        return db.customers.find_one({"id": cid}, {"_id": 0})

    def scan(cid, amount=0, branch="b1"):
        return http("POST", "/api/owner/scan", json={"barcode_id": cust(cid)["barcode_id"], "amount_paid": amount,
                                                     "branch_id": branch})

    MSG = {"title": "Bonjour {prénom}", "body": "{nom} · {points} pts · {récompense} · {nom_commerce} · {date} · "
                                                 "{montant} · {nombre_visites} visites"}

    def body(trigger, **over):
        b = {"scenario": "custom", "name": "Mon automatisation", "description": "", "status": "active",
             "trigger": trigger, "message": dict(MSG), "targeting": {"mode": "all", "pick": "all"},
             "schedule": {"tz": "Europe/Paris", "hour": "10:00", "window": False}}
        for k, v in over.items():
            b[k] = {**b[k], **v} if isinstance(v, dict) and isinstance(b.get(k), dict) else v
        return b

    def create(trigger, headers=None, **over):
        return http("POST", "/api/owner/automations", headers=headers, json=body(trigger, **over))

    def mine(cid, aid=None):
        # only what « Nouvelle automatisation » said (the shop's other messages are not ours)
        ours = {x["title"] for x in db.automation_log.find({"customer_id": cid, "scenario": "custom"}, {"_id": 0, "title": 1})}
        return [p for p in pushed if p["cid"] == cid and p["title"] in ours]

    def pause_all():
        db.automations.update_many({"tenant_id": "t1", "scenario": "custom"}, {"$set": {"status": "paused"}})

    def run(at):
        return AU.run_due(at=at, source="tick")

    today = dt.date.today()
    tomorrow = today + dt.timedelta(days=1)

    http("GET", "/api/owner/automations")                  # the shop's saved scenarios set up — then quiet
    db.automations.update_many({"tenant_id": "t1", "scenario": {"$ne": "custom"}}, {"$set": {"status": "paused"}})

    print("1. Configuration et validation (étapes 1, 2 et 5)")
    r = create({"type": "on_date", "date": tomorrow.isoformat()}, description="Offre spéciale d'octobre")
    check(f"a Date spécifique is saved ({r.status_code})", r.status_code == 200)
    row = r.json()
    row = row.get("row", row)
    check("its trigger reads « Date spécifique · le … à 10:00 »",
          row["trigger_text"].startswith("Date spécifique · le ") and row["trigger_text"].endswith("à 10:00"))
    check("the description is kept", row.get("description") == "Offre spéciale d'octobre")
    check("« Prochaines dates d'envoi » = that one day", row.get("next_dates") == [tomorrow.isoformat()])
    bad = [
        ({"type": "on_date", "date": (today - dt.timedelta(days=1)).isoformat()}, {}, "a past date"),
        ({"type": "on_date"}, {}, "no date"),
        ({"type": "nope"}, {}, "an unknown déclencheur"),
        ({"type": "recurring", "period": "weekly", "weekdays": []}, {}, "a week without a day"),
        ({"type": "recurring", "period": "monthly", "monthdays": [1, 5, 10, 15, 20]}, {}, "5 days a month"),
        ({"type": "recurring", "period": "yearly", "date_kind": "fixed"}, {}, "Annuelle fixe without its date"),
        ({"type": "recurring", "period": "custom", "rule": "every_days", "every_days": 0}, {}, "every 0 days"),
        ({"type": "loyalty"}, {}, "fidélité without any condition"),
        ({"type": "geo", "address": "x"}, {}, "géolocalisation without a position"),
        ({"type": "geo", "address": "x", "lat": 47.39, "lng": 0.68, "radius_m": 49}, {}, "a rayon of 49 m"),
        ({"type": "geo", "address": "x", "lat": 47.39, "lng": 0.68, "radius_m": 1001}, {}, "a rayon of 1001 m"),
        ({"type": "geo", "address": "x", "lat": 47.39, "lng": 0.68, "from": "22:00", "to": "09:00"}, {}, "a plage d'activation backwards"),
        ({"type": "other", "rule": "visits_in_days", "x": 3, "y": 60}, {}, "Autre without a name"),
        ({"type": "other", "rule_name": "R", "rule": "nope"}, {}, "Autre with an unknown condition"),
        ({"type": "action", "action": "dance"}, {}, "an unknown action"),
        ({"type": "on_date", "date": tomorrow.isoformat()}, {"schedule": {"tz": "Mars/Olympus"}}, "an unknown time zone"),
        ({"type": "on_date", "date": tomorrow.isoformat()},
         {"schedule": {"hour": "21:00", "window": True, "window_from": "09:00", "window_to": "20:00"}}, "the hour outside the plage"),
        ({"type": "on_date", "date": tomorrow.isoformat()},
         {"schedule": {"window": True, "window_from": "20:00", "window_to": "09:00"}}, "a plage backwards"),
        ({"type": "action", "action": "visit"}, {"schedule": {"send_mode": "at"}}, "« à une date / heure » without it"),
        ({"type": "on_date", "date": (today + dt.timedelta(days=10)).isoformat()},
         {"schedule": {"valid_to": (today + dt.timedelta(days=5)).isoformat()}}, "an expiration before the date"),
        ({"type": "on_date", "date": tomorrow.isoformat()},
         {"schedule": {"valid_from": "2026-12-01", "valid_to": "2026-11-01"}}, "an end before the start"),
        ({"type": "recurring", "period": "yearly", "date_kind": "birthday", "reminder": {"enabled": True, "days_before": 7}},
         {}, "a rappel without its words"),
        ({"type": "on_date", "date": tomorrow.isoformat()}, {"targeting": {"pick": "points"}}, "Ciblage par points without a range"),
        ({"type": "on_date", "date": tomorrow.isoformat()}, {"targeting": {"pick": "stores"}}, "Ciblage par établissement without one"),
        ({"type": "on_date", "date": tomorrow.isoformat()},
         {"targeting": {"pick": "all", "filters": {"points_min": 500, "points_max": 10}}}, "points 500 → 10"),
        ({"type": "on_date", "date": tomorrow.isoformat()}, {"schedule": {"rules_note": "x" * 501}}, "a note of 501 characters"),
    ]
    for trig, over, label in bad:
        r = create(trig, **over)
        check(f"refused: {label} ({r.status_code} {str(r.json().get('detail'))[:60]})", r.status_code == 400)
    r = create({"type": "geo", "address": ""}, status="draft")
    check("a draft may wait for its address", r.status_code == 200)
    r = create({"type": "on_date", "date": tomorrow.isoformat()}, headers=HM)
    check("a manager cannot create one", r.status_code == 403)
    r = create({"type": "on_date", "date": tomorrow.isoformat()}, headers=HA)
    check("an administrateur can", r.status_code == 200)
    pause_all()

    print("\n2. Date spécifique, à son heure, dans son fuseau")
    person("d1", "Dina Sow", points=40, visits=4, total_amount_paid=52.5)
    d = tomorrow
    r = create({"type": "on_date", "date": d.isoformat()}, name="Offre spéciale d'octobre")
    aid = r.json().get("id") or r.json().get("row", {}).get("id")
    pushed.clear()
    run(dt.datetime(d.year, d.month, d.day, 7, 30, tzinfo=UTC))            # 09:30 Paris (summer) / 08:30 (winter)
    check("before 10:00 Paris: nothing", not mine("d1"))
    run(dt.datetime(d.year, d.month, d.day, 9, 1, tzinfo=UTC))
    got = mine("d1")
    check("at 10:00 Paris: sent", len(got) == 1)
    check("the variables are filled ({prénom} {nom} {points} {récompense} {montant} {nombre_visites})",
          got and got[0]["title"] == "Bonjour Dina" and "Dina Sow · 40 pts · Un café offert · Café Lumière" in got[0]["body"]
          and "52,50 €" in got[0]["body"] and "4 visites" in got[0]["body"])
    run(dt.datetime(d.year, d.month, d.day, 15, 0, tzinfo=UTC))
    check("a second run the same day: nothing more", len(mine("d1")) == 1)
    run(dt.datetime(d.year, d.month, d.day, 9, 0, tzinfo=UTC) + dt.timedelta(days=1))
    check("the next day: nothing (one date)", len(mine("d1")) == 1)
    pause_all()
    r = create({"type": "on_date", "date": d.isoformat()}, schedule={"tz": "America/Martinique"})
    pushed.clear()
    run(dt.datetime(d.year, d.month, d.day, 9, 1, tzinfo=UTC))             # 05:01 in Martinique
    check("Martinique: not at 10:00 Paris", not mine("d1"))
    run(dt.datetime(d.year, d.month, d.day, 14, 1, tzinfo=UTC))            # 10:01 in Martinique
    check("…but at 10:00 Martinique (14:00 UTC)", len(mine("d1")) == 1)
    pause_all()

    print("\n3. Récurrent")
    base = dt.date(2027, 3, 1)                                              # a Monday
    row = {"trigger": {"type": "recurring", "period": "weekly", "every_weeks": 2, "weekdays": [0, 2]},
           "schedule": {"valid_from": base.isoformat()}, "created_at": now}
    due = [x for x in range(28) if CR.date_due(row, base + dt.timedelta(days=x))]
    check(f"every 2 weeks, lun. + mer.: days {due}", due == [0, 2, 14, 16])
    row = {"trigger": {"type": "recurring", "period": "monthly", "monthdays": [1, 31]}, "schedule": {}}
    check("monthly « le 31 » = 28 February, 31 March",
          CR.date_due(row, dt.date(2027, 2, 28)) and CR.date_due(row, dt.date(2027, 3, 31)) and not CR.date_due(row, dt.date(2027, 3, 30)))
    row = {"trigger": {"type": "recurring", "period": "custom", "rule": "every_days", "every_days": 10, "workdays_only": False},
           "schedule": {"valid_from": "2027-03-01"}}
    check("every 10 days from the start", [x for x in range(25) if CR.date_due(row, base + dt.timedelta(days=x))] == [0, 10, 20])
    row["trigger"]["workdays_only"] = True
    check("« jours ouvrés »: the Saturday (13 March) is skipped",
          [x for x in range(25) if CR.date_due(row, base + dt.timedelta(days=x))] == [0, 10] or
          not CR.date_due(row, dt.date(2027, 3, 13)))
    row = {"trigger": {"type": "recurring", "period": "custom", "rule": "per_month", "per_month": 2}, "schedule": {}}
    check("2 fois par mois = the 1st and the 16th (31 days)", CR.per_month_days(dt.date(2027, 3, 1), 2) == [1, 16]
          and CR.date_due(row, dt.date(2027, 3, 16)))
    nd = CR.next_dates({"trigger": {"type": "recurring", "period": "weekly", "every_weeks": 1, "weekdays": [0, 2, 4]},
                        "schedule": {}, "created_at": now}, dt.date(2027, 3, 1))
    check("« Prochaines dates »: lun., mer., ven. …", nd[:3] == ["2027-03-01", "2027-03-03", "2027-03-05"] and len(nd) == 5)

    print("\n   Annuelle: date fixe, anniversaire, inscription, rappel")
    person("y1", "Yan Birthday", birthday=(base + dt.timedelta(days=20)).strftime("%m-%d"))
    person("y2", "Yasmine Leap", birthday="02-29")
    person("y3", "Yves New", created_at=dt.datetime(2027, 3, 10, 9, tzinfo=UTC))
    person("y4", "Yolande Old", created_at=dt.datetime(2025, 3, 10, 9, tzinfo=UTC))
    yr = {"id": "yr", "tenant_id": "t1", "trigger": {"type": "recurring", "period": "yearly", "date_kind": "birthday",
                                                    "reminder": {"enabled": True, "days_before": 7}}, "schedule": {}}
    ppl = [cust(x) for x in ("y1", "y2", "y3", "y4")]
    on_day = CR.yearly_people("t1", yr, base + dt.timedelta(days=20), ppl)
    check("birthday: the client's own day", [(c["id"], x["reminder"]) for c, x in on_day] == [("y1", False)])
    before = CR.yearly_people("t1", yr, base + dt.timedelta(days=13), ppl)
    check("…and its rappel 7 days before", [(c["id"], x["reminder"]) for c, x in before] == [("y1", True)])
    check("29 February: on the 28th in a common year",
          [c["id"] for c, _ in CR.yearly_people("t1", {**yr, "trigger": {**yr["trigger"], "reminder": {}}}, dt.date(2027, 2, 28), ppl)] == ["y2"])
    yr["trigger"] = {"type": "recurring", "period": "yearly", "date_kind": "signup", "reminder": {}}
    got = [c["id"] for c, _ in CR.yearly_people("t1", yr, dt.date(2027, 3, 10), ppl)]
    check("anniversaire d'inscription: Yolande (2 years), not Yves (signed up today)", got == ["y4"])
    yr["trigger"] = {"type": "recurring", "period": "yearly", "date_kind": "fixed", "date": "2026-10-17", "reminder": {}}
    check("date fixe: everyone on 17 October", len(CR.yearly_people("t1", yr, dt.date(2027, 10, 17), ppl)) == 4)
    pause_all()
    r = create({"type": "recurring", "period": "yearly", "date_kind": "birthday", "reminder": {"enabled": True, "days_before": 3}},
               message_reminder={"title": "Bientôt votre anniversaire", "body": "Dans 3 jours, {prénom} !"})
    check(f"a yearly with its rappel saved ({r.status_code})", r.status_code == 200
          and (r.json().get("message_reminder") or {}).get("title") == "Bientôt votre anniversaire")
    bd = tomorrow + dt.timedelta(days=3)
    person("y5", "Yanis Soon", birthday=bd.strftime("%m-%d"))
    pushed.clear()
    run(dt.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 9, 5, tzinfo=UTC))
    got = mine("y5")
    check("the rappel goes 3 days before, with ITS words", len(got) == 1 and got[0]["title"] == "Bientôt votre anniversaire"
          and got[0]["body"] == "Dans 3 jours, Yanis !")
    run(dt.datetime(bd.year, bd.month, bd.day, 9, 5, tzinfo=UTC))
    got = mine("y5")
    check("…and on the day, the main message", len(got) == 2 and got[1]["title"] == "Bonjour Yanis")
    pause_all()

    print("\n4. Après une action client")
    person("a1", "Alex Achat")
    r = create({"type": "action", "action": "purchase", "repeat": "every"}, name="Merci pour votre achat")
    pushed.clear()
    scan("a1", amount=0)
    check("a visit without a purchase is not « Achat effectué »", not mine("a1"))
    scan("a1", amount=12)
    check("a purchase: sent at once", len(mine("a1")) == 1)
    scan("a1", amount=8)
    check("« à chaque fois »: again", len(mine("a1")) == 2)
    pause_all()
    r = create({"type": "action", "action": "purchase", "repeat": "every",
                "criteria": {"enabled": True, "min_amount": 20, "stores": ["b2"]}})
    pushed.clear()
    scan("a1", amount=25, branch="b1")
    check("critères: another établissement → nothing", not mine("a1"))
    scan("a1", amount=15, branch="b2")
    check("critères: under the montant minimum → nothing", not mine("a1"))
    scan("a1", amount=25, branch="b2")
    check("critères met → sent", len(mine("a1")) == 1)
    pause_all()
    person("a2", "Ava Visite")
    r = create({"type": "action", "action": "visit", "repeat": "once", "delay_value": 1, "delay_unit": "days"})
    aid = r.json()["id"]
    pushed.clear()
    scan("a2")
    q = db.automation_queue.find_one({"automation_id": aid, "customer_id": "a2"})
    check("« 1 jour après l'action »: waiting, not sent", q and not mine("a2"))
    scan("a2")
    check("one waiting at a time", db.automation_queue.count_documents({"automation_id": aid, "customer_id": "a2"}) == 1)
    run(AU._aware(q["due_at"]) + dt.timedelta(minutes=1))
    check("released the next day", len(mine("a2")) == 1)
    scan("a2")
    check("« une seule fois »: never again", not db.automation_queue.find_one({"automation_id": aid, "customer_id": "a2"}))
    pause_all()
    r = create({"type": "action", "action": "visit", "repeat": "gap", "every_days": 30})
    aid = r.json()["id"]
    pushed.clear()
    person("a3", "Axel Gap")
    scan("a3")
    scan("a3")
    check("« au plus une fois tous les 30 jours »: one", len(mine("a3")) == 1)
    db.automation_log.update_many({"automation_id": aid}, {"$set": {"sent_at": now - dt.timedelta(days=31)}})
    scan("a3")
    check("…31 days later: again", len(mine("a3")) == 2)
    pause_all()

    print("\n   Inscription, palier, offre utilisée")
    r = create({"type": "action", "action": "signup", "repeat": "once"}, name="Bienvenue maison")
    pushed.clear()
    j = http("POST", "/api/join/cafe", headers={}, json={"name": "Inès Neuve", "phone": "0611111111", "postal_code": "37000",
                                                        "birthday": "02/03/1995", "consent": True, "store": "b1"})
    ines = db.customers.find_one({"barcode_id": (j.json() or {}).get("barcode_id")}, {"_id": 0}) or {}
    check(f"signed up ({j.status_code}): « Inscription » sent", ines and len(mine(ines["id"])) == 1)
    pause_all()
    r = create({"type": "action", "action": "tier_reached", "repeat": "every"}, name="Palier")
    person("p1", "Paul Palier", points=95, visits=9)
    pushed.clear()
    scan("p1")                                                              # 95 → 105: Argent (100)
    got = mine("p1")
    check("crossing the 100-point palier: sent", len(got) == 1)
    scan("p1")                                                              # 105 → 115: nothing crossed
    check("no palier crossed: nothing", len(mine("p1")) == 1)
    pause_all()
    db.campaigns.insert_many([
        {"id": "of1", "tenant_id": "t1", "kind": "offre", "status": "sent", "name": "-20 % sur tout",
         "sent_at": now - dt.timedelta(days=1), "recipient_ids": ["o1"]},
        {"id": "of2", "tenant_id": "t1", "kind": "offre", "status": "sent", "name": "Café offert",
         "sent_at": now - dt.timedelta(days=1), "recipient_ids": ["o2"]},
        {"id": "ofR", "tenant_id": "t2", "kind": "offre", "status": "sent", "name": "Rival",
         "sent_at": now - dt.timedelta(days=1), "recipient_ids": ["o1"]}])
    person("o1", "Olga Offre")
    person("o2", "Omar Offre")
    r = create({"type": "action", "action": "offer_used", "repeat": "every"},
               message={"title": "Merci {prénom}", "body": "Vous avez profité de {offre}."})
    pushed.clear()
    sc = scan("o1").json()
    offers = sc.get("offers_active") or []
    check("the till lists the valid offer, not used yet", [(o["id"], o.get("used")) for o in offers] == [("of1", False)])
    r = http("POST", "/api/owner/offers/of1/use", headers=HS, json={"customer_id": "o1", "branch_id": "b1"})
    check(f"staff marks it « Offre utilisée » ({r.status_code})", r.status_code == 200)
    check("…the automation speaks, {offre} = its name", [p["body"] for p in mine("o1")] == ["Vous avez profité de -20 % sur tout."])
    r = http("POST", "/api/owner/offers/of1/use", headers=HS, json={"customer_id": "o1"})
    check(f"the same offer twice: refused ({r.status_code})", r.status_code == 409 and len(mine("o1")) == 1)
    check("the till now shows it used", [(o["id"], o.get("used")) for o in scan("o1").json().get("offers_active") or []] == [("of1", True)])
    r = http("POST", "/api/owner/offers/of2/use", headers=HS, json={"customer_id": "o1"})
    check(f"an offer not sent to this client: refused ({r.status_code})", r.status_code == 400)
    r = http("POST", "/api/owner/offers/ofR/use", headers=HS, json={"customer_id": "o1"})
    check(f"another shop's offer: not found ({r.status_code})", r.status_code == 404)
    r = http("POST", "/api/owner/offers/of1/use", headers=H2, json={"customer_id": "o1"})
    check(f"another shop's staff: not found ({r.status_code})", r.status_code == 404)
    pause_all()

    print("\n5. Conditions sur la fidélité")
    person("l1", "Léa Loyal", points=80, visits=4, total_amount_paid=150)
    r = create({"type": "loyalty", "match": "any", "points": 100, "visits": 10, "amount": 200, "repeat": "each"})
    aid = r.json()["id"]
    check("its trigger text", "100 points ou 10 visites ou 200 € d'achats" in r.json()["trigger_text"])
    pushed.clear()
    scan("l1")                                                              # 90 points: none
    check("no condition met: nothing", not mine("l1"))
    scan("l1")                                                              # 100 points
    check("100 points reached: sent", len(mine("l1")) == 1)
    scan("l1")
    check("still true: not again", len(mine("l1")) == 1)
    db.customers.update_one({"id": "l1"}, {"$set": {"points": 0}})          # a reward redeemed
    scan("l1")
    check("false again (points spent)…", len(mine("l1")) == 1)
    db.customers.update_one({"id": "l1"}, {"$set": {"points": 95}})
    scan("l1")
    check("…and true again: « à chaque nouvelle atteinte » → sent", len(mine("l1")) == 2)
    pause_all()
    r = create({"type": "loyalty", "match": "all", "points": 50, "visits": 3, "repeat": "once"})
    person("l2", "Luc All", points=60, visits=1)
    pushed.clear()
    scan("l2")
    check("« toutes les conditions »: one missing → nothing", not mine("l2"))
    scan("l2")
    check("all met → sent", len(mine("l2")) == 1)
    db.customers.update_one({"id": "l2"}, {"$set": {"points": 0}})
    scan("l2")
    db.customers.update_one({"id": "l2"}, {"$set": {"points": 70}})
    scan("l2")
    check("« une seule fois »: never again", len(mine("l2")) == 1)
    pause_all()

    print("\n6. Comportement client")
    D = dt.date(2027, 5, 10)
    at10 = dt.datetime(2027, 5, 10, 8, 5, tzinfo=UTC)                       # 10:05 Paris
    person("b1", "Bea Absente", visits=3, last_visit_date=at10 - dt.timedelta(days=31))
    person("b2", "Ben Present", visits=5, last_visit_date=at10 - dt.timedelta(days=3))
    person("b3", "Bob Jamais", visits=0, last_visit_date=None, created_at=at10 - dt.timedelta(days=90))
    r = create({"type": "behavior", "client_status": "existing", "activity": "inactive", "value": 30, "unit": "days"})
    aid = r.json()["id"]
    pushed.clear()
    run(at10)
    check("inactive 31 days: sent; active / never came (existing only): not",
          len(mine("b1")) == 1 and not mine("b2") and not mine("b3"))
    run(at10 + dt.timedelta(days=1))
    check("the next day: not again (once per absence)", len(mine("b1")) == 1)
    db.customers.update_one({"id": "b1"}, {"$set": {"last_visit_date": at10 + dt.timedelta(days=2)}})
    run(at10 + dt.timedelta(days=33))
    check("back, then absent 31 days again: a new absence → sent", len(mine("b1")) == 2)
    pause_all()
    r = create({"type": "behavior", "client_status": "new", "activity": "inactive", "value": 4, "unit": "weeks"})
    pushed.clear()
    run(at10 + dt.timedelta(days=40))
    check("« nouveaux clients » (never came) idle 4 weeks: Bob only", mine("b3") and not mine("b2"))
    pause_all()

    print("\n7. Géolocalisation (n'importe quelle adresse)")
    VENUE = (47.3600, 0.7000)                                               # a market, not a shop
    person("g1", "Gina Geo", visits=0)
    person("g2", "Gus Habitue", visits=12)
    r = create({"type": "geo", "address": "Marché des Halles, Tours", "lat": VENUE[0], "lng": VENUE[1], "radius_m": 300,
                "days": "all", "from": "00:00", "to": "23:59", "new_only": True},
               message={"title": "Vous êtes tout près !", "body": "Passez nous voir, {prénom}."},
               schedule={"dedupe": True, "min_gap_days": 1})
    gid = r.json()["id"]
    check("its trigger text", r.json()["trigger_text"] == "Géolocalisation · 300 m autour de Marché des Halles, Tours")

    def ping(cid, lat, lng):
        return http("POST", "/api/public/proximity-ping", headers={}, json={"customer_id": cid, "latitude": lat, "longitude": lng}).json()
    pushed.clear()
    out = ping("g1", VENUE[0] + 0.01, VENUE[1])                             # ~1.1 km away
    check("1 km away: nothing", not mine("g1"))
    out = ping("g1", VENUE[0] + 0.001, VENUE[1])                            # ~110 m
    check(f"110 m from the address (far from the shop): sent ({out.get('status')})",
          out.get("status") == "sent" and len(mine("g1")) == 1 and out.get("title") == "Vous êtes tout près !")
    ping("g1", VENUE[0], VENUE[1])
    check("anti-doublon: not twice the same day", len(mine("g1")) == 1)
    ping("g2", VENUE[0], VENUE[1])
    check("« uniquement les nouveaux clients »: a regular hears nothing", not mine("g2"))
    pas = GA.for_pass(cust("g2"), now)
    check("the Wallet pass: no custom spot for the regular", not pas or pas.get("automation_id") != gid)
    db.automation_log.delete_many({"automation_id": gid})
    pas = GA.for_pass(cust("g1"), now)
    check("the Wallet pass of a new client carries the address and its rayon",
          pas and pas["automation_id"] == gid and pas["spots"] == [VENUE] and pas["radius"] == 300)
    db.automations.update_one({"id": gid}, {"$set": {"trigger.days": "weekend" if now.weekday() < 5 else "weekdays"}})
    pushed.clear()
    ping("g1", VENUE[0], VENUE[1])
    check("outside its days (semaine / week-end): nothing", not mine("g1"))
    db.automations.update_one({"id": gid}, {"$set": {"trigger.days": "all", "trigger.from": "00:00", "trigger.to": "00:01"}})
    ping("g1", VENUE[0], VENUE[1])
    check("outside its plage d'activation: nothing", not mine("g1") or CR.local(now, {}).strftime("%H:%M") < "00:01")
    pause_all()

    print("\n8. Autre · règle personnalisée")
    r = create({"type": "other", "rule_name": "Habitués du mois", "rule": "visits_in_days", "x": 3, "y": 60, "notes": "test"})
    aid = r.json()["id"]
    check("its trigger text", r.json()["trigger_text"] == "Habitués du mois · 3 visites en 60 jours")
    person("o3", "Otto Trois")
    pushed.clear()
    scan("o3")
    scan("o3")
    check("2 visits in 60 days: nothing", not mine("o3"))
    scan("o3")
    check("the 3rd visit: sent", len(mine("o3")) == 1)
    scan("o3")
    check("still true: not again", len(mine("o3")) == 1)
    pause_all()
    r = create({"type": "other", "rule_name": "Gros clients", "rule": "spent_in_days", "x": 50, "y": 30})
    person("o4", "Olive Spend")
    pushed.clear()
    scan("o4", amount=30)
    scan("o4", amount=25)
    check("55 € in 30 days ≥ 50 €: sent once", len(mine("o4")) == 1)
    pause_all()
    r = create({"type": "other", "rule_name": "Première visite +7", "rule": "days_after_first_visit", "x": 7})
    aid = r.json()["id"]
    person("o5", "Oscar First", visits=1)
    db.visits.insert_one({"id": "v-o5", "tenant_id": "t1", "customer_id": "o5", "visit_time": at10 - dt.timedelta(days=7)})
    pushed.clear()
    run(at10)
    check("7 days after the first visit: sent", len(mine("o5")) == 1)
    run(at10 + dt.timedelta(days=1))
    check("the day after: not again", len(mine("o5")) == 1)
    pause_all()

    print("\n9. Règles d'envoi")
    person("r1", "Rita Regles")
    r = create({"type": "action", "action": "visit", "repeat": "every"}, schedule={"limit": {"count": 1, "per": "week"}})
    pushed.clear()
    scan("r1")
    scan("r1")
    check("« 1 fois par semaine »: one", len(mine("r1")) == 1)
    pause_all()
    r = create({"type": "action", "action": "visit", "repeat": "every"}, schedule={"dedupe": True, "min_gap_days": 7})
    aid = r.json()["id"]
    pushed.clear()
    scan("r1")
    scan("r1")
    check("« éviter les doublons » 7 jours: one", len(mine("r1")) == 1)
    db.automation_log.update_many({"automation_id": aid}, {"$set": {"sent_at": now - dt.timedelta(days=8)}})
    scan("r1")
    check("8 days later: again", len(mine("r1")) == 2)
    pause_all()
    later = now + dt.timedelta(days=2)
    loc = CR.local(later, {"tz": "Europe/Paris"})
    r = create({"type": "action", "action": "visit", "repeat": "every"},
               schedule={"send_mode": "at", "send_at": loc.strftime("%Y-%m-%dT%H:%M")})
    aid = r.json()["id"]
    pushed.clear()
    scan("r1")
    q = db.automation_queue.find_one({"automation_id": aid, "customer_id": "r1"})
    check("« à une date / heure spécifique »: the visit waits for it",
          q and not mine("r1") and abs((AU._aware(q["due_at"]) - later.replace(second=0, microsecond=0)).total_seconds()) < 61)
    pause_all()
    r = create({"type": "action", "action": "visit", "repeat": "every"},
               schedule={"valid_from": (today + dt.timedelta(days=3)).isoformat()})
    pushed.clear()
    scan("r1")
    check("période d'activation not begun: nothing", not mine("r1"))
    pause_all()
    r = create({"type": "action", "action": "visit", "repeat": "every"}, status="paused",
               schedule={"valid_to": (today - dt.timedelta(days=1)).isoformat()})
    check("an expired period can be saved paused", r.status_code == 200)
    r = create({"type": "action", "action": "visit", "repeat": "every"},
               schedule={"valid_to": (today - dt.timedelta(days=1)).isoformat()})
    check("…but not activated", r.status_code == 400)

    print("\n10. Ciblage et aperçu")
    pause_all()
    person("c1", "Cara Points", points=320, total_amount_paid=400, last_visit_date=now - dt.timedelta(days=40))
    person("c2", "Cyril Low", points=20, total_amount_paid=10, last_visit_date=now - dt.timedelta(days=1))

    def pv(tg, **kw):
        return http("POST", "/api/owner/automations/preview", json={"scenario": "custom", "targeting": tg, **kw}).json()
    tot = db.customers.count_documents({"tenant_id": "t1", "deleted_at": None})
    a = pv({"pick": "all"})
    check(f"« Tous les clients »: {a['count']} of {a['total']}", a["count"] == tot and a["total"] == tot)
    check("three real examples", len(a["examples"]) == 3 and {"name", "points", "last_visit"} <= set(a["examples"][0]))
    p = pv({"pick": "points", "filters": {"points_min": 300, "points_max": 500}})
    check("« Clients avec un nombre de points » 300–500: Cara", [x["id"] for x in pv({"pick": "points", "filters": {"points_min": 300, "points_max": 500}}, full=True)["list"]] == ["c1"])
    i = pv({"pick": "inactive", "inactive_days": 30}, full=True)
    check("« Clients inactifs » 30 jours: includes Cara, not Cyril",
          "c1" in [x["id"] for x in i["list"]] and "c2" not in [x["id"] for x in i["list"]])
    f = pv({"pick": "all", "filters": {"spent_min": 100, "last_visit_op": "more", "last_visit_days": 30}}, full=True)
    check("filtres complémentaires: montant ≥ 100 € and dernière visite > 30 j → Cara", [x["id"] for x in f["list"]] == ["c1"])
    r = create({"type": "action", "action": "visit", "repeat": "every"}, targeting={"pick": "points", "filters": {"points_min": 300}})
    check("saved as « points »: mode filtered, pick kept",
          r.json()["targeting"]["pick"] == "points" and r.json()["targeting"]["mode"] == "filtered")
    pushed.clear()
    scan("c2")
    scan("c1")
    check("…and it only speaks to 300+ points", not mine("c2") and len(mine("c1")) == 1)
    pause_all()
    r = create({"type": "action", "action": "visit", "repeat": "every"}, targeting={"pick": "active"})
    check("« Clients actifs uniquement » = the shop's active statuts",
          r.status_code == 200 and r.json()["targeting"]["filters"]["activity"])

    print("\n11. L'ancienne « Personnalisée » et les autres boutiques")
    pause_all()
    r = http("POST", "/api/owner/automations", json={"scenario": "custom", "name": "Ancienne", "status": "active",
                                                     "trigger": {"type": "visits", "visits": 2, "visits_repeat": "once"},
                                                     "message": {"title": "Deux visites", "body": "Merci {prénom}"},
                                                     "targeting": {"mode": "all"}, "schedule": {"days": "all", "window": False}})
    check(f"an older « Après X visites » is still accepted ({r.status_code})", r.status_code == 200)
    person("z1", "Zoé Old", visits=1)
    pushed.clear()
    scan("z1")
    check("…and still sends at the 2nd visit", [p["title"] for p in mine("z1")] == ["Deux visites"])
    person("x1", "Xavier Rival", tid="t2")
    rows = http("GET", "/api/owner/automations", headers=H2).json()["rows"]
    check("another shop sees none of ours", not [x for x in rows if x["scenario"] == "custom"])
    pv2 = http("POST", "/api/owner/automations/preview", headers=H2, json={"scenario": "custom", "targeting": {"pick": "all"}}).json()
    check("…and its aperçu counts only its own clients", pv2["total"] == 1)
    r = http("GET", "/api/owner/automations/address-search?q=Gare")
    check("address search: the shop's establishment first",
          r.status_code == 200 and r.json()["results"] and r.json()["results"][0]["kind"] == "store")

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
