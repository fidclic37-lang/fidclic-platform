"""
« Vos offres » — what a customer's card shows as running offers (2026-10-09
redesign from the user's mockup). Every campaign of the last 45 days used to
reach every card, a VIP-only or birthday one included, some already past
their « Valable jusqu'au ».

Run: cd api && /usr/local/bin/python3 tests/test_offers_page.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-offers-page")
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
    import httpx
    from services import card_owner as CO
    db = server.db
    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip",
                           "subscription_status": "active", "sector": "cafe"})
    for cid, bc in (("me", "FT-0FFE0A01"), ("other", "FT-0FFE0B01")):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "barcode_id": bc, "name": cid.title(),
                                 "phone": "06" + bc[-8:].replace("A", "1").replace("B", "2").replace("F", "3").replace("E", "4"),
                                 "visits": 3, "points": 30, "created_at": now})
    db.card_templates.insert_one({"tenant_id": "t1", "active_offer_active": True,
                                  "active_offer_title": "Café offert le lundi", "reward_description": "Un dessert offert"})

    def camp(cid, name, days_ago, to):
        db.campaigns.insert_one({"id": cid, "tenant_id": "t1", "name": name, "content": "…", "status": "sent",
                                 "sent_at": now - dt.timedelta(days=days_ago), "recipient_ids": to})
    camp("c-mine", "-20% sur votre prochaine commande", 3, ["me", "other"])
    camp("c-vip", "Soirée VIP", 2, ["other"])
    camp("c-old", "Menu étudiant", 31, ["me"])

    def card(bc):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(f"/api/card/{bc}", headers={"X-Card-Key": CO.key_for(bc)})
        return asyncio.get_event_loop().run_until_complete(run()).json()

    print("\nOffers on my card")
    d = card("FT-0FFE0A01")
    ids = [o["id"] for o in d["offers"]]
    check("a campaign sent to me is there", "c-mine" in ids)
    check("a campaign sent only to someone else is not", "c-vip" not in ids)
    check("a campaign sent 31 days ago (past its 30 days) is not", "c-old" not in ids)
    mine = next(o for o in d["offers"] if o["id"] == "c-mine")
    until = dt.datetime.fromisoformat(mine["valid_until"])
    check("« Valable jusqu'au » = sent + 30 days", abs((until - (now - dt.timedelta(days=3) + dt.timedelta(days=30))).total_seconds()) < 5)
    primary = next(o for o in d["offers"] if o["kind"] == "primary")
    check("the shop's own offer has no invented end date", primary["valid_until"] is None)
    msgs = [n["id"] for n in d["notifications"]]
    check("the card's messages (45-day history) list only campaigns sent to me",
          "c-mine" in msgs and "c-old" in msgs and "c-vip" not in msgs)
    check("the shop's trade comes with the card (the page's pictures)", d["tenant"]["sector"] == "cafe")

    print("\nSomeone else's card")
    other = [o["id"] for o in card("FT-0FFE0B01")["offers"]]
    check("the VIP campaign shows on the card it was sent to", "c-vip" in other and "c-mine" in other)

    print("\nThe shop's own offer with an end date")
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"active_offer_expires_at": now - dt.timedelta(days=1)}})
    check("past its end date it is gone", all(o["kind"] != "primary" for o in card("FT-0FFE0A01")["offers"]))
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"active_offer_expires_at": (now + dt.timedelta(days=5)).isoformat()}})
    p = next((o for o in card("FT-0FFE0A01")["offers"] if o["kind"] == "primary"), None)
    check("before it, it shows with that date", p is not None and p["valid_until"] and p["valid_until"].startswith((now + dt.timedelta(days=5)).date().isoformat()))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
