"""
Campagnes — the page, the audiences, the send and the assistant.

Boots the real server.py on mongomock, so the module is exercised exactly as
it is registered in production: the same router, the same collections, the
same cron entry point.

What is checked, in the order it matters:
  • an audience is what it says it is, and an unknown one messages NOBODY
  • the composer writes what the merchant approved, on the channels they chose
  • a scheduled campaign waits, then the cron sends it — exactly once
  • the open rate means "card opened within 72 h", and nothing else
  • a campaign becomes the wallet card's offer, and stops being it later
  • the assistant writes two strings and never sends anything
Run: /usr/local/bin/python3 api/tests/test_campaigns_page.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-for-campaigns-page")

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
    import features.campaigns_page as C
    from services import llm

    db = server.db
    C._db = db
    now = dt.datetime.now(dt.timezone.utc)

    class TD:
        email, role, tenant_id = "owner@shop.fr", "business_owner", "t1"

    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café", "plan": "gold"})   # campaigns are a Pro feature
    db.tenants.insert_one({"id": "t2", "name": "Rival"})

    # id, visits, last visit (days ago), birthday (days from today), barcode
    CAST = [
        ("c1", 9, 1, 400, "FT-0001"),     # loyal, active
        ("c2", 5, 2, 3, "FT-0002"),       # loyal, birthday this week
        ("c3", 3, 3, 200, "FT-0003"),     # exactly 3 visits → NOT "plus de 3"
        ("c4", 1, 95, 100, "FT-0004"),    # inactive
        ("c5", 0, None, 2, "FT-0005"),    # never came → inactive, birthday
    ]
    for cid, visits, last, bday, barcode in CAST:
        doc = {"id": cid, "tenant_id": "t1", "name": f"Client {cid}", "visits": visits,
               "barcode_id": barcode, "phone": f"060000000{cid[-1]}",
               "birthday": (now + dt.timedelta(days=bday)).strftime("%m-%d"),
               "created_at": now - dt.timedelta(days=300)}
        if last is not None:
            doc["last_visit_date"] = now - dt.timedelta(days=last)
        db.customers.insert_one(doc)
    db.customers.insert_one({"id": "x1", "tenant_id": "t2", "name": "Rival client",
                             "visits": 50, "barcode_id": "FT-9999",
                             "last_visit_date": now, "birthday": now.strftime("%m-%d")})

    # ---- audiences -------------------------------------------------------------------------
    print("\nAudiences")
    ids = lambda seg: {c["id"] for c in C.audience("t1", seg, now)}

    check("'Tous mes clients' is every client of THIS shop", ids("all") == {c[0] for c in CAST})
    check("another shop's clients are never in the audience", "x1" not in ids("all"))

    loyal = ids("loyal")
    from features import clients_page as CP_, customer_rules as R_
    _people = list(db.customers.find({"tenant_id": "t1"}, {"_id": 0}))
    _rules = R_.load("t1")
    check("'Clients fidèles' is the Clients page's own (the shop's Règles clients)",
          loyal == {c["id"] for c in _people if CP_.is_loyal(c, now, _rules)})
    check("and so is 'Clients inactifs'",
          ids("inactive") == {c["id"] for c in _people if CP_.is_inactive(c, now, _rules)})

    inactive = ids("inactive")
    check("'Plus de 30 jours' catches the client who stopped coming", "c4" in inactive)
    check("a client who has never come at all counts as inactive", "c5" in inactive)
    check("a client who came yesterday is not inactive", "c1" not in inactive)

    bday = ids("birthday")
    check("'Cette semaine' catches the birthdays inside the window",
          bday == {c[0] for c in CAST if c[3] < C.BIRTHDAY_DAYS})
    check("a birthday months away is not 'cette semaine'", "c1" not in bday)

    try:
        C.audience("t1", "tout-le-monde", now)
        refused = False
    except Exception as exc:
        refused = getattr(exc, "status_code", None) == 400
    check("an unknown segment is refused, never resolved to everybody", refused)

    # ---- the composer ----------------------------------------------------------------------
    print("\nLe composeur")

    def compose(**kw):
        body = {"title": "Un titre", "message": "Un message", "segment": "all"}
        body.update(kw)
        return C.compose(C.Compose(**body), token_data=TD())

    try:
        compose(title="  ")
        rejected = False
    except Exception as exc:
        rejected = getattr(exc, "status_code", None) == 400
    check("a campaign with no title is refused", rejected)

    try:
        compose(push=False, wallet=False)
        rejected = False
    except Exception as exc:
        rejected = getattr(exc, "status_code", None) == 400
    check("a campaign with no channel at all is refused", rejected)

    long_title = "x" * 200
    res = compose(title=long_title, message="y" * 400, segment="loyal", draft=True)
    saved = db.campaigns.find_one({"id": res["id"]})
    check("a draft is saved, not sent", res["status"] == "draft" and saved["sent_at"] is None)
    check("the title is cut to what a push can carry", len(saved["name"]) == C.TITLE_MAX)
    check("the message is cut to what a push can carry", len(saved["content"]) == C.MESSAGE_MAX)
    check("the audience the merchant chose is the audience that is stored",
          set(saved["recipient_ids"]) == ids("loyal"))
    check("the draft names its audience in words", saved["audience_label"] == "Clients fidèles")

    sent = compose(title="Café offert", message="Cette semaine seulement", segment="inactive")
    camp = db.campaigns.find_one({"id": sent["id"]})
    check("a send reaches exactly the chosen audience",
          set(camp["recipient_ids"]) == ids("inactive") and sent["audience"] == len(ids("inactive")))
    check("the campaign is marked sent, with a time", camp["status"] == "sent" and camp["sent_at"])
    feed = list(db.push_notifications.find({"campaign_id": sent["id"]}))
    check("every recipient gets the offer in their card feed, push or no push",
          {f["customer_id"] for f in feed} == ids("inactive"))
    check("the card feed carries the title and the message",
          feed[0]["title"] == "Café offert" and feed[0]["body"] == "Cette semaine seulement")

    chosen = compose(title="Pour vous", message="Une attention", customer_ids=["c1", "c2"])
    hand = db.campaigns.find_one({"id": chosen["id"]})
    check("a hand-picked list is honoured as given", set(hand["recipient_ids"]) == {"c1", "c2"})
    check("a hand-picked list says how many people it is", hand["audience_label"] == "2 clients")

    # ---- scheduling ------------------------------------------------------------------------
    print("\nPlanification")
    later = (now + dt.timedelta(days=2)).isoformat()
    sch = compose(title="Samedi", message="On vous attend", schedule_at=later)
    doc = db.campaigns.find_one({"id": sch["id"]})
    check("a campaign planned for later waits", sch["status"] == "scheduled" and doc["sent_at"] is None)
    check("nothing is delivered before its time",
          db.push_notifications.count_documents({"campaign_id": sch["id"]}) == 0)

    check("the cron leaves a campaign whose time has not come",
          C.run_due(now)["sent"] == 0 and
          db.campaigns.find_one({"id": sch["id"]})["status"] == "scheduled")

    fired = C.run_due(now + dt.timedelta(days=3))
    doc = db.campaigns.find_one({"id": sch["id"]})
    check("the cron sends it once its time has come", fired["sent"] == 1 and doc["status"] == "sent")
    check("the delivery happened for real",
          db.push_notifications.count_documents({"campaign_id": sch["id"]}) == len(ids("all")))
    check("running the cron again does not send it twice",
          C.run_due(now + dt.timedelta(days=4))["sent"] == 0 and
          db.push_notifications.count_documents({"campaign_id": sch["id"]}) == len(ids("all")))

    past = compose(title="Tout de suite", message="Maintenant",
                   schedule_at=(now - dt.timedelta(hours=2)).isoformat())
    check("a time already past means send now, not never", past["status"] == "sent")

    # ---- the page --------------------------------------------------------------------------
    print("\nLa page")
    db.campaigns.delete_many({})
    db.push_notifications.delete_many({})
    db.card_opens.delete_many({})
    db.visits.delete_many({})

    older = now - dt.timedelta(days=45)      # previous period
    recent = now - dt.timedelta(days=5)      # current period
    db.campaigns.insert_many([
        {"id": "old-1", "tenant_id": "t1", "name": "Ancienne", "content": "...", "status": "sent",
         "sent_at": older, "recipient_ids": ["c1", "c2"], "offer_clicks": 2, "segment": "all"},
        {"id": "new-1", "tenant_id": "t1", "name": "Récente", "content": "Un café offert",
         "status": "sent", "sent_at": recent, "recipient_ids": ["c1", "c2", "c3", "c4"],
         "offer_clicks": 6, "segment": "all", "delivered_count": 4},
    ])
    # c1 and c2 opened their card the day after the send; c3 opened it a month
    # later, which is outside the window and must not count.
    db.card_opens.insert_many([
        {"tenant_id": "t1", "customer_id": "c1", "day": "d1", "at": recent + dt.timedelta(hours=10)},
        {"tenant_id": "t1", "customer_id": "c2", "day": "d2", "at": recent + dt.timedelta(hours=40)},
        {"tenant_id": "t1", "customer_id": "c3", "day": "d3", "at": recent + dt.timedelta(days=20)},
    ])
    db.visits.insert_many([
        {"tenant_id": "t1", "customer_id": "c1", "amount_paid": 12.5,
         "visit_time": recent + dt.timedelta(days=2)},
        {"tenant_id": "t1", "customer_id": "c2", "amount_paid": 7.5,
         "visit_time": recent + dt.timedelta(days=3)},
        {"tenant_id": "t1", "customer_id": "c3", "amount_paid": 99.0,
         "visit_time": recent + dt.timedelta(days=40)},      # outside attribution
    ])

    p = C.page(token_data=TD())
    strip = {s["key"]: s for s in p["strip"]}
    check("the strip has the five figures of the design", len(p["strip"]) == 5)
    check("only this period's campaigns are counted", strip["sent"]["value"] == 1)
    check("'Clients touchés' is the recipients of those campaigns", strip["reach"]["value"] == 4)
    check("an open is a card opened inside the 72 h window",
          strip["open_rate"]["value"] == 50)           # c1 + c2 of 4
    check("a card opened weeks later is not an open", strip["open_rate"]["value"] != 75)
    check("clicks come from the campaigns themselves", strip["clicks"]["value"] == 6)
    check("'CA généré' counts only spend inside the attribution window",
          strip["revenue"]["value"] == 20.0)
    check("the delta compares with the period before", strip["sent"]["delta_pct"] == 0)
    check("a figure with no previous period says nothing rather than +100 %",
          strip["revenue"]["delta_pct"] is None)

    check("the page prints what an 'ouverture' actually is",
          str(C.OPEN_WINDOW_H) in p["open_note"] and "accusé de lecture" in p["open_note"])
    check("the page prints what 'CA généré' actually is",
          str(C.ATTRIBUTION_DAYS) in p["revenue_note"])

    segs = {s["key"]: s for s in p["segments"]}
    check("the preview signs the push with the shop's own name",
          p["tenant_name"] == "Le Petit Café")
    check("the four audience cards of the design are there", len(p["segments"]) == 4)
    check("each card carries its own live count",
          segs["all"]["count"] == len(ids("all")) and segs["loyal"]["count"] == len(ids("loyal")))
    check("the cards say what they mean, from the shop's Règles clients",
          segs["inactive"]["hint"] == f"Pas venus depuis {R_.active_days(_rules)} jours"
          and segs["loyal"]["hint"] == "Selon vos Règles clients")

    rows = {r["id"]: r for r in p["recent"]}
    check("the recent list is newest first", p["recent"][0]["id"] == "new-1")
    check("a row shows how many it reached", rows["new-1"]["sent"] == 4)
    check("a row shows its own open rate", rows["new-1"]["open_rate"] == 50)
    check("a row names its audience", rows["new-1"]["audience"] == "Tous mes clients")
    check("a row carries the message under the name", rows["new-1"]["subtitle"] == "Un café offert")

    empty = C.page(token_data=type("T", (), {"email": "o@r.fr", "role": "business_owner",
                                             "tenant_id": "t2"}))
    check("a shop that never sent anything reads zero, and says so",
          empty["empty"] and empty["strip"][0]["value"] == 0)
    check("an empty shop still gets its audience cards",
          len(empty["segments"]) == 4 and empty["segments"][0]["count"] == 1)

    # ---- the wallet offer ------------------------------------------------------------------
    print("\nL'offre dans le wallet")
    import features.wallet_passes as W
    W._db = db
    db.campaigns.delete_many({})
    db.campaigns.insert_one({
        "id": "w-1", "tenant_id": "t1", "name": "-20 % sur votre café",
        "content": "Valable jusqu'au 30 sept.", "status": "sent", "wallet_offer": True,
        "recipient_ids": ["c1"], "sent_at": now - dt.timedelta(days=2)})

    card = {}
    W._attach_campaign_offer(card, db.customers.find_one({"id": "c1"}))
    check("the campaign becomes the card's offer",
          card.get("campaign_offer", {}).get("title") == "-20 % sur votre café")
    check("the offer carries the message as its subtitle",
          card["campaign_offer"]["subtitle"] == "Valable jusqu'au 30 sept.")
    check("the pass reads that offer first, above the merchant's own",
          W._offer_text({**card, "offer_box_text": "Ancienne offre"})[0] == "-20 % sur votre café")

    other = {}
    W._attach_campaign_offer(other, db.customers.find_one({"id": "c2"}))
    check("a customer the campaign never reached does not get the offer",
          "campaign_offer" not in other)

    db.campaigns.update_one({"id": "w-1"}, {"$set": {
        "sent_at": now - dt.timedelta(days=W.CAMPAIGN_OFFER_DAYS + 1)}})
    stale = {}
    W._attach_campaign_offer(stale, db.customers.find_one({"id": "c1"}))
    check("an expired campaign stops being the card's offer", "campaign_offer" not in stale)

    # Google's own banner — its `messages` element, the closest thing to the
    # mockup. Apple has no banner element at all: it raises a lock-screen
    # notification from changeMessage instead.
    db.campaigns.update_one({"id": "w-1"}, {"$set": {"sent_at": now - dt.timedelta(days=2)}})
    live = {}
    W._attach_campaign_offer(live, db.customers.find_one({"id": "c1"}))
    msg = {"id": "campaign", "header": live["campaign_offer"]["title"][:60],
           "body": live["campaign_offer"]["subtitle"][:300], "messageType": "TEXT"}
    check("the Google banner carries the campaign title",
          msg["header"] == "-20 % sur votre café")
    check("the Google banner carries the message under it",
          msg["body"] == "Valable jusqu'au 30 sept.")

    db.campaigns.update_one({"id": "w-1"}, {"$set": {"sent_at": now, "wallet_offer": False}})
    push_only = {}
    W._attach_campaign_offer(push_only, db.customers.find_one({"id": "c1"}))
    check("a push-only campaign never touches the wallet card", "campaign_offer" not in push_only)

    # ---- the assistant ---------------------------------------------------------------------
    print("\nL'assistant")
    llm._force_complete = lambda system, user: (
        "TITRE: Votre café vous attend ☕\nMESSAGE: Revenez cette semaine, une surprise vous attend.")
    draft = C.ai_draft(C.Draft(objective="faire revenir les clients inactifs",
                               segment="inactive"), token_data=TD())
    check("the assistant returns a title", draft["title"] == "Votre café vous attend ☕")
    check("the assistant returns a message",
          draft["message"] == "Revenez cette semaine, une surprise vous attend.")
    before = db.campaigns.count_documents({})
    C.ai_draft(C.Draft(objective="promouvoir une offre"), token_data=TD())
    check("the assistant never sends anything by itself",
          db.campaigns.count_documents({}) == before)
    check("the page offers the objectives of the design", len(draft["examples"]) == 4)

    llm._force_complete = lambda system, user: "x" * 500
    long_draft = C.ai_draft(C.Draft(objective="test"), token_data=TD())
    check("a model that rambles is cut to what a push can carry",
          len(long_draft["title"]) == C.TITLE_MAX and len(long_draft["message"]) == C.MESSAGE_MAX)

    llm._force_complete = lambda system, user: (
        "Votre café vous attend. Revenez cette semaine, une surprise vous attend.")
    block = C.ai_draft(C.Draft(objective="test"), token_data=TD())
    check("a model that ignores the format is split, not refused",
          block["title"] == "Votre café vous attend"
          and block["message"] == "Revenez cette semaine, une surprise vous attend.")

    llm._force_complete = lambda system, user: ""
    try:
        C.ai_draft(C.Draft(objective="test"), token_data=TD())
        told = False
    except Exception as exc:
        told = getattr(exc, "status_code", None) == 503
    check("a silent model is reported, never faked", told)

    def boom(system, user):
        raise RuntimeError("provider down")
    llm._force_complete = boom
    try:
        C.ai_draft(C.Draft(objective="test"), token_data=TD())
        told = False
    except Exception as exc:
        told = getattr(exc, "status_code", None) == 503
    check("a broken provider is reported, never faked", told)
    llm._force_complete = None
    try:
        C.ai_draft(C.Draft(objective="faire revenir les clients"), token_data=TD())
        said = False
    except Exception as exc:
        said = (getattr(exc, "status_code", None) == 503
                and "configuré" in str(getattr(exc, "detail", "")))
    check("an installation with no model key says so, not 'reformulez'",
          said or llm.is_configured())

    try:
        C.ai_draft(C.Draft(objective="   "), token_data=TD())
        refused = False
    except Exception as exc:
        refused = getattr(exc, "status_code", None) == 400
    check("an empty objective is refused before the model is called", refused)

    # ---- wiring ----------------------------------------------------------------------------
    print("\nLe câblage")
    paths = {r.path for r in server.app.routes if hasattr(r, "methods")}
    for want in ("/api/owner/campaigns/page", "/api/owner/campaigns/compose",
                 "/api/owner/campaigns/ai-draft"):
        check(f"{want} is mounted on the real app", want in paths)
    check("the daily cron drains the scheduled campaigns",
          "features.campaigns_page import run_due" in open(
              os.path.join(os.path.dirname(__file__), "..", "server.py")).read())
    check("the module is registered with the loader",
          "features.campaigns_page" in open(
              os.path.join(os.path.dirname(__file__), "..", "features", "_loader.py")).read())

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
