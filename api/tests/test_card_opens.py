"""
Campaign « ouverture » — measured on every signal we really get (user,
2026-10-05: the open rate read 0 % although the card and the link were opened).

Run: cd api && /usr/local/bin/python3 tests/test_card_opens.py
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
    import httpx
    from services import card_opens as CO
    from features import campaigns_page as C

    db = server.db
    C._db = db
    passed = failed = 0

    def check(label, cond, extra=""):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(dt.timezone.utc).replace(hour=15, minute=0, second=0, microsecond=0)
    morning, sent = now.replace(hour=9), now.replace(hour=14)
    db.tenants.insert_one({"id": "t1", "slug": "gym", "name": "BLOO JOB", "plan": "vip"})
    for i in range(1, 6):
        db.customers.insert_one({"id": f"c{i}", "tenant_id": "t1", "name": f"Client {i}",
                                 "barcode_id": f"FT-OPEN000{i}", "visits": 0, "points": 0})
    camp = {"id": "camp1", "tenant_id": "t1", "name": "Offre", "content": "-20 %", "status": "sent",
            "sent_at": sent, "recipient_ids": ["c1", "c2", "c3", "c4"], "click_customer_ids": []}
    db.campaigns.insert_one(dict(camp))

    def rate():
        c = db.campaigns.find_one({"id": "camp1"}, {"_id": 0})
        return C._opened_ids("t1", c["recipient_ids"], c["sent_at"], c)

    print("\nThe bug: a card opened in the morning, then again after the campaign")
    CO.log(db, {"id": "c1", "tenant_id": "t1"}, now=morning)
    CO.log(db, {"id": "c1", "tenant_id": "t1"}, now=sent + dt.timedelta(minutes=30))
    row = db.card_opens.find_one({"customer_id": "c1"})
    check("one row for the day, both openings kept", db.card_opens.count_documents({"customer_id": "c1"}) == 1
          and len(row["ats"]) == 2 and row["opens"] == 2)
    check("the afternoon opening counts for the campaign", "c1" in rate())

    print("\nWhat does not count")
    CO.log(db, {"id": "c2", "tenant_id": "t1"}, now=morning)
    check("a card opened only before the send", "c2" not in rate())
    CO.log(db, {"id": "c3", "tenant_id": "t1"}, now=sent + dt.timedelta(hours=CO.OPEN_WINDOW_H + 5))
    check("a card opened after the 72 h window", "c3" not in rate())
    CO.log(db, {"id": "c5", "tenant_id": "t1"}, now=sent + dt.timedelta(hours=1))
    check("someone the campaign never reached", "c5" not in rate())

    print("\nThe campaign itself, opened or clicked")
    r = http("GET", "/api/campaigns/camp1/pixel/c2.png")
    check("« Voir l'offre » / the offers feed (pixel) counts", r.status_code == 200 and "c2" in rate())
    r = http("POST", "/api/campaigns/camp1/track-click", params={"customer_id": "c4"})
    check("the campaign's link clicked counts", r.status_code == 200 and "c4" in rate())
    http("GET", "/api/campaigns/camp1/pixel/c5.png")
    check("a pixel from a non-recipient never counts", "c5" not in rate())

    print("\nThe card page itself logs every opening")
    db.card_opens.delete_many({"customer_id": "c3"})
    http("GET", "/api/card/FT-OPEN0003", headers={"X-Card-Key": __import__("services.card_owner", fromlist=["x"]).key_for("FT-OPEN0003")})
    http("GET", "/api/card/FT-OPEN0003", headers={"X-Card-Key": __import__("services.card_owner", fromlist=["x"]).key_for("FT-OPEN0003")})
    row = db.card_opens.find_one({"customer_id": "c3"})
    check("two openings of /card the same day → two times on the row", row and len(row.get("ats") or []) == 2)
    check("…and the customer's last opening is kept for the other pages",
          db.customers.find_one({"id": "c3"}).get("last_card_open_at") is not None)

    print("\nThe Campagnes page row")
    db.card_opens.delete_many({"customer_id": "c1"})        # keep the figure independent of the clock
    db.campaigns.update_one({"id": "camp1"}, {"$set": {"sent_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)}})

    class TD:
        email, role, tenant_id = "o@gym.fr", "business_owner", "t1"
    p = C.page(token_data=TD())
    row = next(x for x in p["recent"] if x["id"] == "camp1")
    # c2 opened the offer (pixel), c4 clicked, c3 just opened /card → 3 of 4
    check(f"the row reads the opens: {row['open_rate']} %", row["open_rate"] == 75)
    check("the note says what is and is not counted",
          "Voir l'offre" in p["open_note"] and "Apple Wallet" in p["open_note"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
