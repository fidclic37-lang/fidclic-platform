"""
Insights — « Faites grandir votre commerce ».

Boots the real server.py on mongomock. The computed impacts are checked
against the merchant's own formula applied to the fixture, never against a
hand-worked number; every benchmark is checked to say it is one.

Run: /usr/local/bin/python3 api/tests/test_insights_page.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-for-insights")

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
    import features.insights_page as I
    import features.push_wallet as PW
    import features.segmentation as SEG

    db = server.db
    for mod in (I, PW, SEG):
        mod._db = db
    # A fixed "now" in September, so the seasonal shelf is the mockup's.
    now = dt.datetime(2026, 9, 26, 15, 0, tzinfo=dt.timezone.utc)

    def T(tid):
        return type("TD", (), {"email": f"o@{tid}", "role": "business_owner", "tenant_id": tid})()

    db.tenants.insert_many([
        {"id": "cafe", "slug": "petit-cafe", "name": "Le Petit Café", "sector": "cafe",
         "monthly_revenue_goal": 2500.0, "latitude": 47.3941, "longitude": 0.6848},
        {"id": "spa", "slug": "zen", "name": "Zen Spa", "sector": "spa"},
        {"id": "blank", "slug": "blank", "name": "Sans secteur"},
    ])

    # id, visits, spend, last visit (days ago), joined (days ago), birthday offset (days), lat/lng
    CAST = [
        ("a1", 12, 240.0, 3, 300, 400, (47.3945, 0.6850)),    # active, local
        ("a2", 9, 180.0, 10, 250, 12, (47.3950, 0.6860)),     # active, local, birthday soon
        ("w1", 6, 90.0, 45, 200, 200, (47.5000, 0.8000)),     # warm, far
        ("d1", 4, 100.0, 120, 300, 5, None),                  # dormant, birthday soon
        ("d2", 2, 30.0, 200, 320, 300, None),                 # dormant
        ("n1", 1, 18.0, 8, 8, 100, (47.3942, 0.6849)),        # one-timer, new, local
        ("n2", 1, 22.0, 3, 3, 150, None),                     # one-timer, new
        ("z0", 0, 0.0, None, 100, 90, None),                  # never bought
    ]
    for cid, visits, spend, last, joined, bday, pos in CAST:
        doc = {"id": cid, "tenant_id": "cafe", "name": f"Client {cid}", "visits": visits,
               "total_amount_paid": spend, "barcode_id": f"FT-{cid.upper()}",
               "created_at": now - dt.timedelta(days=joined),
               "birthday": (now + dt.timedelta(days=bday)).strftime("%m-%d")}
        if last is not None:
            doc["last_visit_date"] = now - dt.timedelta(days=last)
        if pos:
            doc["latitude"], doc["longitude"] = pos
        db.customers.insert_one(doc)

    # Visits: this month ahead of the same days of last month, lunch is busy,
    # 15h is quiet, and items are recorded so "1,8 produit" can be computed.
    def visit(days_ago, hour, amount, items=None, cid="a1"):
        t = (now - dt.timedelta(days=days_ago)).replace(hour=hour, minute=10)
        v = {"tenant_id": "cafe", "customer_id": cid, "amount_paid": amount, "visit_time": t}
        if items:
            v["items"] = items
        db.visits.insert_one(v)

    for d in range(1, 25):                                    # September
        visit(d, 12, 20.0, [{"name": "Croissant", "quantity": 1}, {"name": "Café", "quantity": 1}])
        visit(d, 13, 15.0, [{"name": "Café", "qty": 2}])     # the Scan page's key
    for d in range(1, 8):
        visit(d, 15, 5.0, [{"name": "Café", "quantity": 1}])
    for d in range(32, 57):                                   # August, same days
        visit(d, 12, 20.0)

    db.reviews.insert_many([
        {"tenant_id": "cafe", "customer_id": "a1", "rating": 9},
        {"tenant_id": "cafe", "customer_id": "a2", "rating": 10},
        {"tenant_id": "cafe", "customer_id": "w1", "rating": 4},
    ])

    data = I._payload("cafe", now)

    # ---- the hero ---------------------------------------------------------------------------
    print("\nL'en-tête")
    h = data["hero"]
    check("a month ahead of last month reads as progress", h["direction"] == "up" and h["pct"] > 0)
    check("the chip carries the real percentage", h["chip"] == f"+{h['pct']}%")
    check("and the design's words", h["title"] == "Votre activité est en progression !")

    shop = I.Shop("cafe", now)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_start = (start - dt.timedelta(days=1)).replace(day=1)
    prev_end = prev_start + (now - start)
    rev = lambda a, b: sum(v["amount_paid"] for v in shop.visits
                           if a <= I._aware(v["visit_time"]) <= b)
    check("it compares the SAME number of days of each month",
          h["pct"] == round((rev(start, now) - rev(prev_start, prev_end)) / rev(prev_start, prev_end) * 100))

    def scale_month(k):
        for v in list(db.visits.find({"tenant_id": "cafe", "visit_time": {"$gte": start}})):
            db.visits.update_one({"_id": v["_id"]}, {"$set": {"amount_paid": v["amount_paid"] * k}})

    scale_month(0.1)
    down = I._payload("cafe", now)["hero"]
    check("a falling month is called a falling month",
          down["direction"] == "down" and down["pct"] < 0 and "ralentit" in down["title"])
    check("and never 'en progression'", "progression" not in down["title"])
    scale_month(10)
    check("a shop with nothing last month is told it is starting",
          I._payload("spa", now)["hero"]["direction"] == "start")

    # ---- the goal ---------------------------------------------------------------------------
    print("\nL'objectif du mois")
    g = data["goal"]
    check("it is the same goal the Tableau de bord tracks", g["target"] == 2500.0 and g["is_set"])
    check("it counts this month's takings", g["reached"] == round(rev(start, now), 2))
    check("and what is left", g["remaining"] == round(max(0, 2500 - rev(start, now)), 2))

    # ---- opportunités -----------------------------------------------------------------------
    print("\nOpportunités")
    opp = {o["key"]: o for o in data["opportunities"]["all"]}
    check("three are shown, as the design does", len(data["opportunities"]["shown"]) == 3)
    cats = [o["category"]["key"] for o in data["opportunities"]["shown"]]
    check("and they keep the mix — one per category first", len(set(cats)) == 3)

    dormant = I._inactive(shop)
    check("inactifs counts the clients gone over 30 days (and the one who never came)",
          {c["id"] for c in dormant} == {"w1", "d1", "d2", "z0"})
    check("the body states that count", opp["inactifs"]["body"].startswith("4 clients"))

    lo = hi = 0.0
    # the shop's basket: spent ÷ visits over the last 30 days, as Analyses (QA F15)
    month = [v for v in shop.visits if v["visit_time"].replace(tzinfo=dt.timezone.utc) >= now - dt.timedelta(days=30)]
    shop_avg = sum(v.get("amount_paid") or 0 for v in month) / len(month)
    check("the shop's basket is spent ÷ visits, not an average of averages (QA F15)", abs(shop.shop_avg - shop_avg) < 1e-6)
    for c in dormant:
        basket = (c["total_amount_paid"] / c["visits"]) if c["visits"] else shop_avg
        days = None if not c.get("last_visit_date") else (now - c["last_visit_date"]).days
        rng = ((0.05, 0.10) if days is None else (0.25, 0.35) if days < 30 else
               (0.15, 0.20) if days < 60 else (0.10, 0.15) if days < 90 else (0.05, 0.10))
        lo += basket * rng[0]
        hi += basket * rng[1]
    fmt = lambda n: f"{round(n):,}".replace(",", " ")
    want = (f"+{fmt(lo)} € de CA" if round(lo) == round(hi) else f"+{fmt(lo)} à {fmt(hi)} € de CA")
    check("its impact is the merchant's own formula, as a range IN EUROS",
          opp["inactifs"]["impact"]["label"] == want)
    check("… with the exact euros kept alongside", opp["inactifs"]["impact"]["euros"]
          == [round(lo + 1e-9, 2), round(hi + 1e-9, 2)])
    check("and it says it was calculated", opp["inactifs"]["impact"]["kind"] == "calcule"
          and "calculé" in opp["inactifs"]["impact"]["basis"])

    # 24 lunches of 2 items + 24 of 1 + 7 afternoon coffees, over 55 visits.
    with_items = [v for v in shop.recent(90) if v.get("items")]
    per_visit = sum(sum(i.get("qty") or i.get("quantity", 1) for i in v["items"]) for v in with_items) / len(with_items)
    check("panier moyen reads the items per visit from the scans",
          f"en moyenne {per_visit:.1f}".replace(".", ",") in opp["panier_moyen"]["body"])
    check("a benchmark says it is one",
          opp["panier_moyen"]["impact"]["basis"].startswith(I.BENCHMARK)
          and opp["panier_moyen"]["impact"]["kind"] == "secteur")
    check("… and is applied to THIS shop's revenue, in euros",
          opp["panier_moyen"]["impact"]["label"] ==
          f"+{fmt(shop.monthly * 0.05)} à {fmt(shop.monthly * 0.12)} € de CA"
          and "5–12 %" in opp["panier_moyen"]["impact"]["basis"])
    check("an acquisition estimate becomes a number of new clients at the shop's own pace",
          opp["proximite"]["impact"]["label"].endswith("nouveaux clients")
          and "%" not in opp["proximite"]["impact"]["label"])
    check("no impact on the page is a percentage any more, where money can be shown",
          all("%" not in x["impact"]["label"] for x in data["opportunities"]["all"] + data["actions"]["all"]))

    locs = I._locals(shop)
    check("proximité counts the clients within 2 km", {c["id"] for c in locs} == {"a1", "a2", "n1"})
    check("and says so in its body", opp["proximite"]["body"].startswith("3 de vos clients"))
    blank_opp = {o["key"]: o for o in I._payload("blank", now)["opportunities"]["all"]}
    check("a shop with no position is not told nobody lives nearby",
          "De nombreux clients potentiels" in blank_opp["proximite"]["body"])

    check("one-time new clients are their own opportunity",
          opp["seconde_visite"]["body"].startswith("2 nouveaux clients"))
    # Two-hour windows, sliding by the hour: the quietest open one is the first
    # that holds the afternoon coffees and nothing else.
    per_hour = {}
    for v in shop.recent(90):
        h = I._paris(I._aware(v["visit_time"])).hour          # the shop's clock (QA F19)
        per_hour[h] = per_hour.get(h, 0) + 1
    windows = {h: per_hour.get(h, 0) + per_hour.get(h + 1, 0) for h in range(7, 22)}
    quiet = min((h for h, n in windows.items() if n > 0), key=lambda h: (windows[h], h))
    busy = max(windows, key=lambda h: (windows[h], per_hour.get(h, 0), -h))
    check("the quiet hour is found in the scans",
          f"{quiet}h–{quiet + 2}h" in opp["heures_creuses"]["body"])
    check("and it is a slot the shop is actually open", windows[quiet] > 0)

    # ---- actions ----------------------------------------------------------------------------
    print("\nActions recommandées")
    act = {x["key"]: x for x in data["actions"]["all"]}
    check("four are shown", len(data["actions"]["shown"]) == 4)
    check("each says how long it takes", all(x.get("setup") for x in data["actions"]["all"]))
    check("each carries its benefit chip", all(x.get("benefit") for x in data["actions"]["all"]))
    bdays = {c["id"] for c in I._birthdays(shop)}
    check("the birthday offer is sized on this month's birthdays", bdays == {"a2", "d1"}
          and "2 anniversaires" in act["anniversaire"]["impact"]["basis"])
    check("the review action counts the satisfied reviewers",
          act["avis_google"]["impact"]["label"] == "+1 à 2 avis"
          and "2 clients satisfaits" in act["avis_google"]["impact"]["basis"])
    check("an unhappy reviewer is not counted as satisfied", "w1" not in
          {r["customer_id"] for r in db.reviews.find({"rating": {"$gte": I.SATISFIED_AT}})})

    check("the birthday offer is not done yet", act["anniversaire"]["done"] is False)
    res = I.activate("birthday", token_data=T("cafe"))
    check("'Activer' switches the birthday scenario on", res["enabled"] is True
          and db.push_scenarios.find_one({"tenant_id": "cafe", "builtin": "birthday"})["enabled"])
    after = I._payload("cafe", now)["actions"]
    check("and once on, it leaves the shelf", "anniversaire" not in {x["key"] for x in after["shown"]})
    check("but stays in 'Voir toutes', marked done",
          next(x for x in after["all"] if x["key"] == "anniversaire")["done"] is True
          and after["all"][-1]["done"] is True)
    try:
        I.activate("nuke-everything", token_data=T("cafe"))
        unknown = False
    except Exception as exc:
        unknown = getattr(exc, "status_code", None) == 404
    check("an unknown action is refused", unknown)

    # ---- idées ------------------------------------------------------------------------------
    print("\nIdées de campagnes")
    ideas = [i["key"] for i in data["ideas"]["shown"]]
    check("in September, the four of the design, in its order",
          ideas == ["rentree", "happy_hour", "parrainage", "fetes"])
    check("each carries its category chip",
          [i["category"]["label"] for i in data["ideas"]["shown"]] ==
          ["Automne", "Ventes", "Fidélisation", "Événement"])
    check("each opens the composer", all(i["cta"]["kind"] == "template" for i in data["ideas"]["shown"]))
    check("the season turns with the calendar",
          I._payload("cafe", dt.datetime(2026, 12, 5, tzinfo=dt.timezone.utc))["ideas"]["shown"][0]["key"] == "fetes")

    # ---- personalisation by sector ----------------------------------------------------------
    print("\nSelon le secteur")
    spa = I._payload("spa", now)
    spa_ideas = {i["key"] for i in spa["ideas"]["all"]}
    check("a spa is never offered a Happy Hour on drinks", "happy_hour" not in spa_ideas)
    check("it gets quiet-hours instead", "heures_creuses" in spa_ideas)
    spa_acts = {x["key"] for x in spa["actions"]["all"]}
    check("nor a menu du jour", "menu_du_jour" not in spa_acts and "offre_moment" in spa_acts)
    check("its referral idea offers a reduction, not a drink",
          "boisson" not in next(i for i in spa["ideas"]["all"] if i["key"] == "parrainage")["body"])
    check("a café does not see the spa's quiet-hours idea",
          "heures_creuses" not in {i["key"] for i in data["ideas"]["all"]})
    check("a shop with no sector is treated as the platform's core audience",
          I._payload("blank", now)["food"] is True)

    # ---- conseils ---------------------------------------------------------------------------
    print("\nConseils")
    tips = {t["key"]: t for t in data["tips"]["all"]}
    check("four are shown", len(data["tips"]["shown"]) == 4)
    check(f"the best hours come from the scans, in Paris time ({busy}h–{busy + 2}h)",
          f"entre {busy}h et {busy + 2}h (heure de Paris)" in tips["horaires"]["body"])
    check("the best-seller is named", "« Café »" in tips["best_sellers"]["body"])
    check("the rating is the shop's own", "7,7/10" in tips["experience"]["body"])
    check("no unsourced statistic is presented as fact", "20%" not in tips["visibilite"]["body"])

    # ---- every figure has a basis -----------------------------------------------------------
    print("\nChaque chiffre dit d'où il vient")
    figures = [x["impact"] for x in data["opportunities"]["all"] + data["actions"]["all"]]
    check("no impact is shown without its basis", all(f.get("basis") for f in figures))
    check("every one is either calculated or a sector estimate",
          all(f["kind"] in ("calcule", "secteur") for f in figures))
    check("the page prints how the calculation works",
          "25–35 %" in data["impact_note"] and "estimations du secteur" in data["impact_note"]
          and "en euros" in data["impact_note"])

    # ---- a used recommendation makes way ------------------------------------------------------
    print("\nCe qui a servi laisse sa place")
    shown = I._payload("cafe", now)["opportunities"]["shown"]
    target = next(o for o in shown if o["cta"]["kind"] == "template")
    db.campaigns.insert_one({"id": "used-1", "tenant_id": "cafe", "template": target["cta"]["template"],
                             "status": "sent", "sent_at": now - dt.timedelta(days=2), "name": "x"})
    after = I._payload("cafe", now)["opportunities"]
    check(f"once « {target['title']} » is sent, it leaves the shelf",
          target["key"] not in [o["key"] for o in after["shown"]])
    check("… and something else takes its place", len(after["shown"]) == 3)
    used = next(o for o in after["all"] if o["key"] == target["key"])
    check("… it stays in 'Voir toutes', saying when it was sent",
          used["done"] is True and used["cta"]["done_label"].startswith("Envoyée le 24"))
    back = I._payload("cafe", now + dt.timedelta(days=I.USED_DAYS + 1))["opportunities"]["shown"]
    check("after two weeks it may come back — if the data still calls for it",
          target["key"] in [o["key"] for o in back] or target["key"] in
          [o["key"] for o in I._payload("cafe", now + dt.timedelta(days=I.USED_DAYS + 1))["opportunities"]["all"]
           if not o.get("done")])
    db.campaigns.insert_one({"id": "draft-1", "tenant_id": "cafe", "template": "happy_hour",
                             "status": "draft", "created_at": now, "name": "y"})
    check("a draft does not count as used — nothing was sent",
          "happy_hour" in [i["key"] for i in I._payload("cafe", now)["ideas"]["shown"]])
    db.campaigns.insert_one({"id": "used-2", "tenant_id": "cafe", "template": "happy_hour",
                             "status": "scheduled", "scheduled_for": now + dt.timedelta(days=1), "name": "z"})
    ideas2 = I._payload("cafe", now)["ideas"]
    check("a scheduled idea gives its place to the next idea",
          "happy_hour" not in [i["key"] for i in ideas2["shown"]] and len(ideas2["shown"]) == 4)
    check("… and reads 'Programmée'",
          next(i for i in ideas2["all"] if i["key"] == "happy_hour")["cta"]["done_label"].startswith("Programmée"))
    check("another shop's campaigns never retire this shop's advice",
          I.used_templates("spa", now) == {})
    db.campaigns.delete_many({"id": {"$in": ["used-1", "draft-1", "used-2"]}})

    # ---- templates for the composer ---------------------------------------------------------
    print("\nModèles pour le composeur")
    t = I.template("relance_inactifs", token_data=T("cafe"))
    check("'Relancer ces clients' pre-fills the inactive audience", t["segment"] == "inactive")
    check("and fits a push (title ≤ 50, message ≤ 160)",
          len(t["title"]) <= 50 and len(t["message"]) <= 160)
    loc = I.template("offre_locale", token_data=T("cafe"))
    check("a local campaign is sent to the local clients, by id",
          set(loc["audience"]["ids"]) == {"a1", "a2", "n1"})
    once = I.template("seconde_visite", token_data=T("cafe"))
    check("the second-visit offer goes to the one-timers", set(once["audience"]["ids"]) == {"n1", "n2"})
    check("every template fits a push", all(
        len(v["title"]) <= 50 and len(v["message"]) <= 160
        for food in (True, False) for v in I._templates(food).values()))
    try:
        I.template("inconnu", token_data=T("cafe"))
        missing = False
    except Exception as exc:
        missing = getattr(exc, "status_code", None) == 404
    check("an unknown template is a 404", missing)

    # ---- avis Google ------------------------------------------------------------------------
    print("\nAvis Google")
    try:
        I.set_google_review(I.GoogleReview(url="https://evil.example.com/phish"), token_data=T("cafe"))
        refused = False
    except Exception as exc:
        refused = getattr(exc, "status_code", None) == 400
    check("a link that is not Google's is refused — it is shown to customers", refused)
    ok = I.set_google_review(I.GoogleReview(url="https://g.page/r/abc123/review"), token_data=T("cafe"))
    check("a Google review link is accepted and switched on", ok["enabled"] is True)
    check("the action now reads as done",
          next(x for x in I._payload("cafe", now)["actions"]["all"] if x["key"] == "avis_google")["done"])
    check("a happy customer is handed the link",
          I.google_invite_for("cafe", 9) == "https://g.page/r/abc123/review")
    check("an unhappy one is not", I.google_invite_for("cafe", 5) is None)
    check("a shop that has not switched it on hands nothing", I.google_invite_for("spa", 10) is None)
    I.set_google_review(I.GoogleReview(url="", enabled=False), token_data=T("cafe"))
    check("switching it off stops the invitations", I.google_invite_for("cafe", 10) is None)
    I.set_google_review(I.GoogleReview(url="https://g.page/r/abc123/review"), token_data=T("cafe"))

    resp = server.submit_review(server.ReviewSubmit(barcode_id="FT-A1", rating=9, text="Parfait"))
    check("the card's review endpoint returns the invitation to a happy customer",
          resp["google_review_url"] == "https://g.page/r/abc123/review")
    resp = server.submit_review(server.ReviewSubmit(barcode_id="FT-W1", rating=3, text="Lent"))
    check("and nothing to an unhappy one", resp["google_review_url"] is None)
    I.google_review_click("FT-A1")
    check("following the invitation is logged",
          db.google_review_clicks.count_documents({"tenant_id": "cafe"}) == 1)

    # ---- export -----------------------------------------------------------------------------
    print("\nExport")
    pdf = I.export_pdf(token_data=T("cafe"))
    check("the export is a PDF", pdf.media_type == "application/pdf" and pdf.body[:4] == b"%PDF")
    check("with a dated filename", "fidclic-recommandations-" in pdf.headers["content-disposition"])
    check("and something in it", len(pdf.body) > 3000)
    # QA UX08: numbered pages, header rows repeated, impacts that say their unit
    import io as _io
    from pypdf import PdfReader
    pages = PdfReader(_io.BytesIO(pdf.body)).pages
    texts = [pg.extract_text() or "" for pg in pages]
    check(f"every page is numbered « Page n / {len(pages)} »", all(f"Page {i + 1} / {len(pages)}" in t for i, t in enumerate(texts)))
    joined = " ".join(texts)
    check("impacts say what they count", "Chiffre d'affaires :" in joined or "Clients :" in joined or "Avis Google :" in joined)
    if len(pages) > 1:
        heads = ("Opportunité", "Action", "Campagne", "Conseil")
        check("a page that continues a table starts with its header again",
              all(any(h in t.split("\n", 3)[-1][:400] or h in t[:400] for h in heads) for t in texts[1:]))

    # ---- wiring -----------------------------------------------------------------------------
    print("\nLe câblage")
    paths = {r.path for r in server.app.routes if hasattr(r, "methods")}
    for want in ("/api/owner/insights/page", "/api/owner/insights/templates/{key}",
                 "/api/owner/insights/actions/{action}/activate",
                 "/api/owner/insights/google-review", "/api/owner/insights/export.pdf",
                 "/api/card/{barcode_id}/google-review-click"):
        check(f"{want} is mounted", want in paths)
    here = os.path.dirname(__file__)
    check("the module is registered",
          "features.insights_page" in open(os.path.join(here, "..", "features", "_loader.py")).read())
    check("the PDF dependency is declared for the deployment",
          "reportlab" in open(os.path.join(here, "..", "requirements.txt")).read())
    comp = open(os.path.join(here, "..", "..", "src", "pages", "CampagnesPage.jsx")).read()
    check("the composer reads ?template= and asks the server for the copy",
          "get('template')" in comp and "ownerAPI.insightTemplate(key, params.get('day'), params.get('store'))" in comp)
    check("… and sends the recommendation's key with the campaign, so it can step aside",
          "...(fromTemplate ? { template: fromTemplate } : {})" in comp)
    check("a narrower audience is sent by id, not widened to a card",
          "...(custom ? { customer_ids: custom.ids } : {})" in comp)
    check("the parameter is dropped once applied, so a reload never overwrites edits",
          "['template', 'day', 'store', 'from'].forEach((k) => rest.delete(k))" in comp
          and "{ replace: true }" in comp)
    card = open(os.path.join(here, "..", "..", "src", "pages", "MyWalletCardPage.jsx")).read()
    check("the card shows the Google invitation only when the server hands one back",
          "setGoogleReviewUrl(sent?.google_review_url || null)" in card
          and "googleReviewUrl && (" in card)
    # Every item, in every sector and every season, now has a photo: the icon
    # tile is a safety net, not a design.
    shown = set()
    for tid in ("cafe", "spa"):
        for month in range(1, 13):
            pl = I._payload(tid, dt.datetime(2026, month, 15, 12, tzinfo=dt.timezone.utc))
            for shelf in ("opportunities", "actions", "ideas"):
                for it in pl[shelf]["all"]:
                    shown.add((it["key"], it.get("image")))
    missing = sorted(k for k, img in shown if not img)
    check("no item in any sector or season falls back to an icon tile", missing == [])
    for k in sorted({img for _, img in shown if img and img != "google"}):
        check(f"public/insights/{k}.webp exists for what the page references",
              os.path.exists(os.path.join(here, "..", "..", "public", "insights", f"{k}.webp")))
    for k in ("panier", "inactifs", "proximite", "anniversaire", "menu", "fidelite",
              "automne", "happyhour", "parrainage", "fetes", "panier_services", "heures_creuses",
              "offre_moment", "saint_valentin", "printemps", "ete"):
        check(f"public/insights/{k}.webp is bundled",
              os.path.exists(os.path.join(here, "..", "..", "public", "insights", f"{k}.webp")))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
