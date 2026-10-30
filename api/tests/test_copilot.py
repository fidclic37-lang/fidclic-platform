"""
FidClic IA Copilote — every number from the shop's own rows, or none at all.

Boots the real server.py on mongomock. Network calls (Open-Meteo, PredictHQ)
are replaced by a stub so the forecast is tested on known weather, and the
language model by `llm._force_complete`. Expected figures are derived from the
fixture with the merchant's own formula, never typed in by hand.

Run: /usr/local/bin/python3 api/tests/test_copilot.py
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-for-copilot")
os.environ.pop("PREDICTHQ_TOKEN", None)

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}")


def main():
    import server
    import features.copilot as K
    import features.insights_page as E
    import features.campaigns_page as C
    import features.push_wallet as PW
    import features.segmentation as SEG
    from services import llm

    db = server.db
    for m in (K, E, C, PW, SEG):
        m._db = db
    now = dt.datetime(2026, 9, 23, 15, 0, tzinfo=dt.timezone.utc)   # a Wednesday
    K._now = lambda: now

    def T(tid="cafe"):
        return type("TD", (), {"email": "o@x", "role": "business_owner", "tenant_id": tid})()

    db.tenants.insert_many([
        {"id": "cafe", "slug": "cafe", "name": "Le Petit Café", "sector": "cafe", "plan": "vip",   # full AI: Pro AI
         "latitude": 47.3941, "longitude": 0.6848},
        {"id": "empty", "slug": "empty", "name": "Tout neuf", "sector": "cafe"},
    ])

    # id, visits, spend, last visit (days ago), joined (days ago), birthday in (days), student
    CAST = [
        ("r1", 12, 240.0, 2, 200, 300, False),    # regular, active
        ("r2", 10, 150.0, 5, 180, 3, False),      # regular, birthday this week
        ("r3", 9, 180.0, 8, 150, 200, True),      # regular, student, 1 from silver
        ("k1", 8, 160.0, 60, 150, 100, False),    # regular gone quiet → at risk (gap 13 d, silent 60)
        ("k2", 6, 60.0, 50, 120, 150, False),     # regular gone quiet → at risk
        ("d1", 3, 45.0, 120, 300, 4, False),      # dormant, birthday this week
        # one visit and not back: a café's clients are due back from day 10.5
        # (brain_detectors, 2026-10-25 — « pas revenus après la 1ère visite »)
        ("n1", 1, 12.0, 12, 12, 250, True),       # one-timer, student
        ("n2", 1, 18.0, 16, 16, 280, False),      # one-timer
        ("z0", 0, 0.0, None, 40, 330, False),     # never bought
    ]
    for cid, visits, spend, last, joined, bday, student in CAST:
        doc = {"id": cid, "tenant_id": "cafe", "name": f"Client {cid}", "visits": visits,
               "total_amount_paid": spend, "barcode_id": f"FT-{cid.upper()}", "is_student": student,
               "tier": "bronze", "created_at": now - dt.timedelta(days=joined),
               "birthday": (now + dt.timedelta(days=bday)).strftime("%m-%d")}
        if last is not None:
            doc["last_visit_date"] = now - dt.timedelta(days=last)
        db.customers.insert_one(doc)

    # Ninety days of visits. Saturdays are busy; rainy days are half as busy.
    RAIN = {}
    for i in range(1, 91):
        d = (now - dt.timedelta(days=i)).date()
        rainy = i % 5 == 0
        RAIN[d.isoformat()] = 6.0 if rainy else 0.0
        n = 6 if d.weekday() == 5 else 3
        if rainy:
            n = max(1, n // 2)
        for j in range(n):
            db.visits.insert_one({"tenant_id": "cafe", "customer_id": ["r1", "r2", "r3"][j % 3],
                                  "amount_paid": 10.0,
                                  "visit_time": dt.datetime(d.year, d.month, d.day, 12, j, tzinfo=dt.timezone.utc)})

    calls = []

    def fake_http(url, headers=None, timeout=4.0):
        calls.append(url)
        if "archive-api.open-meteo" in url:
            return {"daily": {"time": list(RAIN), "precipitation_sum": list(RAIN.values())}}
        if "api.open-meteo.com" in url:
            days = [(now.date() + dt.timedelta(days=i)).isoformat() for i in range(7)]
            return {"daily": {"time": days, "precipitation_sum": [0.0] * 7,
                              "temperature_2m_max": [21.0] * 7}}
        if "predicthq" in url:
            sat = (now.date() + dt.timedelta(days=(5 - now.weekday()) % 7)).isoformat()
            return {"results": [{"title": "Fête de la Loire", "category": "festivals", "rank": 72,
                                 "start": f"{sat}T10:00:00Z"}]}
        return None
    K._http_json = fake_http

    shop = E.Shop("cafe", now)

    # ---- the one brain -----------------------------------------------------------------------
    print("\nUn seul moteur")
    risk = {c["id"] for c in E._at_risk(shop)}
    check("at-risk: regulars silent > 45 days AND > twice their own rhythm", risk == {"k1", "k2"})
    check("a dormant occasional client is not 'at risk' — just inactive", "d1" not in risk)
    check("no « étudiants » audience any more (removed, user 2026-10-30)", not hasattr(E, "_students"))
    best = E._best_weekday(shop)
    check("the strongest day is found in the visits", best["weekday"] == 5 and best["lift"] > 50)

    # ---- recommendations ---------------------------------------------------------------------
    print("\nRecommandations")
    recs = K.recommendations(shop)
    by = {r["key"]: r for r in recs}
    check("no « Étudiants » recommendation, even with declared students in the base", "etudiants" not in by)
    dormant = E._inactive(shop)

    def worth(people):
        v = e = 0.0
        # the shop's basket: spent ÷ visits, as Analyses counts it (QA F15)
        avg = shop.shop_avg
        for c in people:
            lo, hi = E._p_range(c, now)
            p = (lo + hi) / 2
            v += p
            e += ((c["total_amount_paid"] / c["visits"]) if c["visits"] else avg) * p
        return v, e

    v, e = worth(dormant)
    base = len(shop.recent(30))
    check("'Relancer N clients inactifs' names the real count",
          by["relance_inactifs"]["title"] == f"Relancer {len(dormant)} clients inactifs")
    want = f"+{round(v)} visite{'s' if round(v) > 1 else ''}" if v >= 0.5 else "< 1 visite"
    check("its visits metric is a number of visits, not a percentage",
          by["relance_inactifs"]["metrics"][0]["label"] == want)
    check("four dormant clients are worth less than one visit, and it says so",
          v < 0.5 and want == "< 1 visite")
    check("no card metric is a percentage of visits",
          all("% visites" not in m["label"] for r in recs for m in r["metrics"]))
    check("its revenue metric is the formula in euros",
          by["relance_inactifs"]["metrics"][1]["label"] == f"+{round(e)} € CA")
    check("the best-day offer names the day and its measured lift",
          by["offre_jour"]["title"] == "Créer une offre spéciale samedi"
          and f"{best['lift']}%" in by["offre_jour"]["body"])
    check("… and it is tagged week-end, as the design does", by["offre_jour"]["chip"] == "Week-end")
    thresholds = [t for _, t in K.TIERS]
    near = [c for c in CAST if c[1] > 0 and any(0 < t - c[1] <= K.NEAR_TIER for t in thresholds
                                                 if t > c[1] and t == min(x for x in thresholds if x > c[1]))]
    check("the VIP tier card counts the clients within reach of their next tier",
          by["palier_vip"]["metrics"][1]["label"] == f"+{len(near)} clients" and len(near) == 2)
    check("no card carries a sector estimate — only computed figures",
          all("secteur" not in json.dumps(r, ensure_ascii=False) for r in recs))
    check("they are ranked by what they are worth", recs == sorted(recs, key=lambda r: -r["score"]))

    K.feedback("offre_jour", K.Feedback(kind="not_relevant"), token_data=T())
    check("'Pas pertinent' removes a card", "offre_jour" not in {r["key"] for r in K.recommendations(shop)})
    K.feedback("a_risque", K.Feedback(kind="later"), token_data=T())
    check("'Plus tard' hides it for now", "a_risque" not in {r["key"] for r in K.recommendations(shop)})
    later = E.Shop("cafe", now + dt.timedelta(days=8))
    check("… and brings it back after a week", "a_risque" in {r["key"] for r in K.recommendations(later)})
    before = by["seconde_visite"]["score"]
    for _ in range(2):
        K.feedback("seconde_visite", K.Feedback(kind="accepted"), token_data=T())
    after = {r["key"]: r for r in K.recommendations(shop)}["seconde_visite"]["score"]
    # the ranking that learns (2026-10-30): taken ideas rise — by what was learned, not a fixed +15 %
    check("a card the merchant keeps acting on rises", after > before)
    try:
        K.feedback("x", K.Feedback(kind="whatever"), token_data=T())
        bad = False
    except Exception as exc:
        bad = getattr(exc, "status_code", None) == 400
    check("an unknown feedback is refused", bad)
    db.copilot_feedback.delete_many({})
    recs = K.recommendations(shop)

    top = recs[0]
    db.campaigns.insert_one({"id": "used-c", "tenant_id": "cafe", "template": top["cta"]["template"],
                             "status": "sent", "sent_at": now - dt.timedelta(days=1), "name": "u"})
    fresh = K.recommendations(E.Shop("cafe", now))
    check("a recommendation whose campaign just went out makes way",
          top["key"] not in [r["key"] for r in fresh] and fresh[0]["key"] != top["key"])
    db.campaigns.delete_many({"id": "used-c"})
    recs = K.recommendations(shop)

    # ---- growth potential --------------------------------------------------------------------
    print("\nPotentiel de croissance")
    g30 = K.growth(shop, recs, 30)
    chosen = [r for r in recs if r["kind"] == "campaign"][:6]
    ids = {i for r in chosen for i in r["ids"]}
    people = [c for c in shop.people if c["id"] in ids]
    gv, ge = worth(people)
    check("each client is counted once, however many campaigns target them",
          len(ids) < sum(len(r["ids"]) for r in chosen) and g30["clients_targeted"] == len(ids))
    check("the euros are the formula over those clients", g30["euros"] == round(ge + 1e-9, 2))
    check("the percentage is against the same horizon of revenue",
          g30["pct"] == round(ge / shop.monthly * 100))
    rows = {r["key"]: r for r in g30["rows"]}
    check("'visites estimées' is the sum of their probabilities", rows["visits"]["value"] == round(gv))
    signups = [c for c in shop.people if (now - c["created_at"]).days <= 30]
    check("new clients continue at the last 30 days' pace", rows["new"]["value"] == len(signups))
    check("a week looks at fewer campaigns than a month",
          K.growth(shop, recs, 7)["clients_targeted"] <= g30["clients_targeted"])
    check("and scales new clients to the horizon", K.growth(shop, recs, 90)["rows"][1]["value"] == len(signups) * 3)
    empty = E.Shop("empty", now)
    ge0 = K.growth(empty, K.recommendations(empty), 30)
    check("a shop with no data shows no percentage rather than a made-up one", ge0["pct"] is None)

    # ---- activity ----------------------------------------------------------------------------
    print("\nAnalyse de votre activité")
    for days, bars in ((7, 7), (30, 10), (90, 13)):
        a = K.activity("cafe", days, now)
        cards = {c["key"]: c for c in a["cards"]}
        rows7 = [v for v in db.visits.find({"tenant_id": "cafe"})
                 if now - dt.timedelta(days=days) <= v["visit_time"].replace(tzinfo=dt.timezone.utc) <= now]
        check(f"{days} days: visits are counted", cards["visits"]["value"] == len(rows7))
        check(f"{days} days: {bars} bars under each figure", len(cards["visits"]["series"]) == bars)
        check(f"{days} days: the bars add up to the figure", sum(cards["visits"]["series"]) == len(rows7))
    a7 = {c["key"]: c for c in K.activity("cafe", 7, now)["cards"]}
    check("revenue, active clients and basket are there too",
          a7["revenue"]["value"] > 0 and a7["active"]["value"] == 3 and a7["basket"]["value"] == 10.0)
    check("an empty shop shows zeros, not deltas against nothing",
          all(c["delta"] is None for c in K.activity("empty", 7, now)["cards"]))

    # ---- the forecast ------------------------------------------------------------------------
    print("\nPrévision : historique + météo + événements")
    factor = K.rain_sensitivity("cafe", (47.3941, 0.6848), now)
    check("the shop's own rain sensitivity is learned from its past", factor is not None and factor < 0.8)
    check("… and bounded", 0.5 <= factor <= 1.5)
    db.copilot_cache.delete_many({})
    few = dict(RAIN)
    for k in list(few)[:80]:
        few[k] = 0.0
    saved = RAIN.copy()
    RAIN.clear(); RAIN.update(few)
    check("too few rainy days to learn from → no adjustment at all",
          K.rain_sensitivity("cafe", (47.3941, 0.6848), now) is None)
    RAIN.clear(); RAIN.update(saved)
    db.copilot_cache.delete_many({})

    fc = K.forecast_week(shop)
    check("seven days are forecast", len(fc["days"]) == 7)
    sat = next(d for d in fc["days"] if d["weekday"] == 5)
    check("Saturday is forecast busier than the week", sat["predicted"] > fc["mean"])
    check("without a PredictHQ token, no events are claimed",
          "événements" not in fc["sources"] and all(not d["events"] for d in fc["days"]))
    aff = K._affluence(shop, fc)
    check("the busy day becomes an opportunity", aff and aff["title"] == "Forte affluence prévue ce samedi")
    check("… saying where it comes from", aff["body"] == "Météo + historique de vos visites.")
    check("… with a potential in euros", aff["potential"] > 0)
    check("… and an offer for THAT day", aff["cta"]["template"] == "offre_jour" and aff["cta"]["day"] == 5)

    os.environ["PREDICTHQ_TOKEN"] = "test-token"
    db.copilot_cache.delete_many({})
    fc2 = K.forecast_week(shop)
    check("with a token, local events are attached to their day",
          any(d["events"] for d in fc2["days"] if d["weekday"] == 5))
    check("… and the source says so",
          K._affluence(shop, fc2)["body"] == "Météo + événement dans la zone.")
    check("the events call sends the token as a bearer header, never in the URL",
          all("test-token" not in u for u in calls))
    os.environ.pop("PREDICTHQ_TOKEN")
    db.copilot_cache.delete_many({})

    K._http_json = lambda *a, **k: None
    check("with the network down, the forecast falls back to history alone",
          K.forecast_week(shop)["sources"] == ["historique"])
    K._http_json = fake_http

    # ---- opportunities -----------------------------------------------------------------------
    print("\nOpportunités détectées")
    opps = {o["key"]: o for o in K.opportunities(shop, K.forecast_week(shop))}
    check("the at-risk regulars are an opportunity with their count",
          opps["a_risque"]["title"] == "2 clients à risque de partir")
    check("… and their potential is the formula", opps["a_risque"]["potential"]
          == round(worth([c for c in shop.people if c["id"] in risk])[1] + 1e-9, 2))
    bd = [c for c in shop.people if c["id"] in {"r2", "d1"}]
    check("birthdays this week are counted", opps["anniversaires"]["body"] == "2 clients à souhaiter.")
    check("an opportunity only appears when detected — no basket drop in a flat fixture",
          "panier" not in opps)

    # ---- the plan ----------------------------------------------------------------------------
    print("\nPlan d'action sur 7 jours")
    fake = [{"key": "offre_jour", "kind": "campaign", "cta": {"template": "offre_jour", "day": 5}},
            {"key": "relance_inactifs", "kind": "campaign", "cta": {"template": "relance_inactifs"}},
            {"key": "a_risque", "kind": "campaign", "cta": {"template": "a_risque"}}]
    built = K._build_plan(shop, fake)
    by_key = {s["key"]: s["offset"] for s in built["steps"]}
    check("a Saturday offer goes out on the Friday before it, not today",
          by_key["offre_jour"] == (5 - now.weekday() - 1) % 7 == 2)
    check("the other campaigns take the first free days", by_key["relance_inactifs"] == 0
          and by_key["a_risque"] == 1)
    check("the steps are in date order", [s["offset"] for s in built["steps"]]
          == sorted(s["offset"] for s in built["steps"]))
    doc = K._plan(shop, recs)
    kinds = [s["kind"] for s in doc["steps"]]
    check("three campaigns, then set-up, then the analysis", kinds[:3] == ["campaign"] * 3
          and kinds[-1] == "analysis")
    view = [K._step_view(shop, doc, s, {r["key"]: r for r in recs}) for s in doc["steps"]]
    check("today's step is 'À faire'", view[0]["when"] == "Aujourd'hui" and view[0]["status"] == "À faire")
    check("tomorrow is called tomorrow", view[1]["when"] == "Demain")
    check("the analysis waits for something to analyse", view[-1]["status"] == "Après les envois")

    sent_before = db.push_notifications.count_documents({})
    # The plan's steps are prepared on the owner's « Préparer les étapes » —
    # the Autopilot is features/autopilot.py now (tests/test_autopilot.py).
    res = K.prepare_plan(token_data=T())
    check("« Préparer les étapes » prepares every campaign step", res["prepared"] == 3)
    check("… and sends NOTHING", db.push_notifications.count_documents({}) == sent_before)
    doc = K._plan(shop, recs)
    drafts = [db.campaigns.find_one({"id": s["campaign_id"]}) for s in doc["steps"] if s.get("campaign_id")]
    check("the prepared steps are drafts", drafts and all(d["status"] == "draft" for d in drafts))
    check("… each tagged with the recommendation it came from", all(d.get("template") for d in drafts))
    view = [K._step_view(shop, doc, s, {r["key"]: r for r in recs}) for s in doc["steps"]]
    check("and read 'Préparée'", all(v["status"] == "Préparée" for v in view[:3]))
    check("preparing again prepares nothing twice", K.autopilot_prepare("cafe", now, force=True) == 0)

    alerts = K.pending_alerts("cafe", now)
    check("the bell announces today's prepared step", len(alerts) == 1 and "prête" in alerts[0]["title"])
    check("… and links to the plan", alerts[0]["action"] == "/dashboard/ai-assistant#plan")
    served = server.get_proactive_alerts(token_data=T(), branch_id=None)
    check("it reaches the real alerts endpoint the bell reads",
          any(a["id"].startswith("copilot:") for a in served["alerts"]))

    today_step, tomorrow_step = doc["steps"][0], doc["steps"][1]
    r = K.approve(today_step["id"], token_data=T())
    check("approving today's step sends it", r["status"] == "sent"
          and db.campaigns.find_one({"id": today_step["campaign_id"]})["status"] == "sent")
    check("… to real customers", db.push_notifications.count_documents({}) > sent_before)
    r2 = K.approve(tomorrow_step["id"], token_data=T())
    sched = db.campaigns.find_one({"id": tomorrow_step["campaign_id"]})
    check("approving a later step schedules it for its day",
          r2["status"] == "scheduled" and sched["status"] == "scheduled")
    check("… just before the daily run that sends it",
          sched["scheduled_for"].hour == K.SEND_HOUR_UTC and sched["scheduled_for"].date() == (now + dt.timedelta(days=1)).date())
    try:
        K.approve(today_step["id"], token_data=T())
        twice = False
    except Exception as exc:
        twice = getattr(exc, "status_code", None) == 409
    check("a step cannot be approved twice", twice)
    check("the bell goes quiet once approved", K.pending_alerts("cafe", now) == [])
    view = {v["id"]: v for v in [K._step_view(shop, K._plan(shop, recs), s, {}) for s in K._plan(shop, recs)["steps"]]}
    check("sent reads 'Envoyée', scheduled reads 'Programmée'",
          view[today_step["id"]]["status"] == "Envoyée" and view[tomorrow_step["id"]]["status"] == "Programmée")
    check("… and the analysis step is now 'À suivre'", list(view.values())[-1]["status"] == "À suivre")

    # a step still recommended right now (today's step was just sent, so it is not)
    live = [r for r in K.recommendations(E.Shop("cafe", K._now())) if r.get("kind", "campaign") == "campaign"]
    kept = live[0]["key"]
    K.edit_plan(K.PlanEdit(steps=[{"key": kept, "offset": 0},
                                  {"key": "hack", "offset": 1},
                                  {"key": "etudiants", "offset": 2},
                                  {"key": kept, "offset": 3},
                                  {"key": "analyse", "offset": 5}]), token_data=T())
    keys = [(s["key"], s["offset"]) for s in K._plan(shop, recs)["steps"]]
    check(f"'Modifier le plan' keeps only what is recommended, once, inside the week ({kept})",
          keys == [(kept, 0), ("analyse", 5)])
    try:
        K.edit_plan(K.PlanEdit(steps=[{"key": "hack", "offset": 0}]), token_data=T())
        emptyp = False
    except Exception as exc:
        emptyp = getattr(exc, "status_code", None) == 400
    check("an empty plan is refused", emptyp)
    K.set_autopilot(K.Autopilot(enabled=False), token_data=T())

    # ---- templates the plan and the cards open -----------------------------------------------
    print("\nModèles")
    t = E.template("offre_jour", day=5, token_data=T())
    check("an offer for a given day names that day", "samedi" in t["title"])
    t = E.template("a_risque", token_data=T())
    check("the at-risk campaign goes to the at-risk clients, by id", set(t["audience"]["ids"]) == risk)
    try:
        E.template("etudiants", token_data=T())
        gone = False
    except Exception as exc:
        gone = getattr(exc, "status_code", None) == 404
    check("the student campaign is gone (404)", gone)

    # ---- the chat ----------------------------------------------------------------------------
    print("\nLe chat")
    seen = {}

    def model(system, user):
        seen["system"], seen["user"] = system, user
        return "Vous avez des clients inactifs : une relance ciblée est la priorité."
    llm._force_complete = model
    out = K.chat(K.ChatIn(message="Relancer mes clients inactifs"), token_data=T())
    check("the model answers", out["reply"].startswith("Vous avez des clients inactifs"))
    check("it is given the shop's own figures", f'"clients_inactifs_30j": {len(dormant)}' in seen["user"])
    check("and told to invent nothing", "n'invente aucun chiffre" in seen["system"])
    check("the action buttons come from the server, not the model",
          out["actions"] and out["actions"][0]["template"] == "relance_inactifs")
    out = K.chat(K.ChatIn(message="Créer une campagne pour les étudiants"), token_data=T())
    check("« étudiants » no longer opens a student campaign",
          all(a.get("template") != "etudiants" for a in out.get("actions") or []))
    check("…and the facts given to the model carry no student count", '"etudiants"' not in seen["user"])
    check("… and the model is told what went out recently", '"campagnes_recentes"' in seen["user"])
    out = K.chat(K.ChatIn(message="Analyser mes derniers résultats"), token_data=T())
    check("results → the analytics page", out["actions"][0]["to"] == "/dashboard/analytics")

    llm._force_complete = lambda s, u: ""
    out = K.chat(K.ChatIn(message="Proposer une offre pour les anniversaires"), token_data=T())
    check("a silent model still gets an answer — from the facts", out["source"] == "facts"
          and "anniversaire" in out["reply"].lower())

    def boom(s, u):
        raise RuntimeError("provider down")
    llm._force_complete = boom
    out = K.chat(K.ChatIn(message="Augmenter mes ventes ce week-end"), token_data=T())
    check("a broken model never breaks the chat", out["source"] == "facts" and out["reply"])
    llm._force_complete = None
    try:
        K.chat(K.ChatIn(message="   "), token_data=T())
        blank = False
    except Exception as exc:
        blank = getattr(exc, "status_code", None) == 400
    check("an empty question is refused", blank)
    hist = K.chat_history(token_data=T())["messages"]
    check("the conversation is kept, in order", hist[0]["role"] == "user" and hist[-1]["role"] == "assistant")

    # ---- the page ----------------------------------------------------------------------------
    print("\nLa page")
    llm._force_complete = lambda s, u: "ok"
    p = K.page(horizon=30, days=7, token_data=T())
    check("three priority recommendations", len(p["recommendations"]["top"]) == 3)
    check("'Voir toutes (N)' is the real count", p["recommendations"]["total"] == len(K.recommendations(shop)))
    check("no internal ids leak to the page",
          all("ids" not in r and "score" not in r for r in p["recommendations"]["all"]))
    check("the chat says it is online when a model is set", p["assistant"]["online"] is True)
    llm._force_complete = None
    check("… and offline when not", K.page(token_data=T())["assistant"]["online"] is K._llm_ready())
    check("an unknown horizon falls back to 30 days", K.page(horizon=999, token_data=T())["growth"]["horizon"] == 30)

    # ---- wiring ------------------------------------------------------------------------------
    print("\nLe câblage")
    paths = {r.path for r in server.app.routes if hasattr(r, "methods")}
    for want in ("/api/owner/copilot/page", "/api/owner/copilot/chat",
                 "/api/owner/copilot/autopilot", "/api/owner/copilot/plan",
                 "/api/owner/copilot/plan/steps/{step_id}/approve",
                 "/api/owner/copilot/recommendations/{key}/feedback"):
        check(f"{want} is mounted", want in paths)
    src = open(os.path.join(os.path.dirname(__file__), "..", "server.py")).read()
    check("the daily cron runs the one Autopilot", "from features.autopilot import run as _run_autopilot" in src)
    check("the plan's « Préparer les étapes » is mounted", "/api/owner/copilot/plan/prepare" in paths)
    here = os.path.dirname(__file__)
    for f in ("robot-hero.webp", "robot-avatar.webp"):
        check(f"public/copilot/{f} is bundled",
              os.path.exists(os.path.join(here, "..", "..", "public", "copilot", f)))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
