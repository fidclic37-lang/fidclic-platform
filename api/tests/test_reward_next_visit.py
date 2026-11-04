"""
A reward is claimed at the visit AFTER the one that earned it (user,
2026-11-04: « agli visit pr reward claim kr sakega »). 10 tampons, 9 on the
card: today's scan fills it and says so, the reward is handed over next time.
Same for a points card, for « Plusieurs personnes », for paper stamps that only
get there with today's visit, and through every way in: the till's `apply`, the
redeem endpoint, the public API. A reward that was already earned stays
available at once, and is never lost.

Run: cd api && /usr/local/bin/python3 tests/test_reward_next_visit.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-reward-next-visit")
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
    import features.scan_page as SP
    import features.wallet_passes as WP
    import features.push_subscriptions as PS

    db = server.db
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    for t in ("t1", "t2"):
        db.tenants.insert_one({"id": t, "slug": t, "name": "Le Café", "is_active": True,
                               "plan": "vip", "subscription_status": "active"})
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "p@x.fr", "role": "business_owner", "tenant_id": "t2"}])
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10,
                                  "visits_per_stamp": 1, "reward_description": "Café offert",
                                  "multi_person": True, "multi_person_max": 20})
    db.card_templates.insert_one({"tenant_id": "t2", "programme": "points_visit", "points_per_visit": 20,
                                  "reward_points": 100, "reward_description": "Café offert"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    H2 = {"Authorization": "Bearer " + auth.create_access_token({"sub": "p@x.fr", "role": "business_owner", "tenant_id": "t2"})}

    n = [0]

    def customer(tid="t1", **kw):
        n[0] += 1
        cid = f"c{n[0]}"
        db.customers.insert_one({"id": cid, "tenant_id": tid, "barcode_id": f"FT-RNV{n[0]:03d}", "name": "Léa",
                                 "visits": 0, "points": 0, "visits_at_last_redemption": 0, **kw})
        return cid, f"FT-RNV{n[0]:03d}"

    def scan(bc, headers=H, **kw):
        return http("POST", "/api/owner/scan", headers=headers, json={"barcode_id": bc, "amount_paid": 5, **kw})

    def redeem(cid, headers=H):
        return http("POST", "/api/owner/rewards/redeem", headers=headers, json={"customer_id": cid, "reward_name": "Café"})

    def card_row(bc, headers=H):
        r = http("GET", f"/api/owner/scan/card?barcode={bc}", headers=headers)
        assert r.status_code == 200, r.text
        return next((a for a in r.json()["applicables"] if a["kind"] == "card"), None)

    print("\n9/10: today fills the card, the reward waits for the next visit")
    cid, bc = customer(visits=9)
    row = card_row(bc)
    check("before the scan: announced for later, not to be picked", row and row["available"] is False and row["after_visit"] is True)
    d = scan(bc).json()
    check("the scan says the card is full", d["reward_unlocked"] is True and d["stamps_in_cycle"] == 10 and d["cards_completed"] == 1)
    r = redeem(cid)
    check(f"handing it over right after is refused ({r.status_code})", r.status_code == 400 and "prochaine visite" in r.json()["detail"])
    check("nothing moved", db.rewards_redeemed.count_documents({"customer_id": cid}) == 0
          and db.customers.find_one({"id": cid})["visits_at_last_redemption"] == 0)

    print("\nThe till asks for it in the scan that fills the card")
    cid, bc = customer(visits=9)
    d = scan(bc, apply="card").json()
    check("the visit is written, the refusal is said", d["visits"] == 10 and d["applied"]["ok"] is False
          and "prochaine visite" in d["applied"]["error"])
    check("the card stays full", d["stamps_in_cycle"] == 10)
    check("no reward was given", db.rewards_redeemed.count_documents({"customer_id": cid}) == 0)

    print("\nThe next visit, picked at the till")
    row = card_row(bc)
    check("the till now offers it", row and row["available"] is True and row["after_visit"] is False)
    d = scan(bc, apply="card").json()
    check("handed over", d["applied"]["ok"] is True and db.rewards_redeemed.count_documents({"customer_id": cid}) == 1)
    check("this visit is stamp 1 of the new card", d["stamps_in_cycle"] == 1 and d["visits"] == 11)
    check("no reward left", d["rewards_pending"] == 0 and redeem(cid).status_code == 400)

    print("\nThe next visit, not picked: it is banked and stays valid")
    cid, bc = customer(visits=9)
    scan(bc)
    d = scan(bc).json()
    check("banked, the new card starts", d["rewards_pending"] == 1 and d["stamps_in_cycle"] == 1)
    check("it can be handed over during that visit", redeem(cid).status_code == 200)
    check("the new card keeps its stamp", db.customers.find_one({"id": cid})["visits"] - db.customers.find_one({"id": cid})["visits_at_last_redemption"] == 1)
    check("and only one reward was there", redeem(cid).status_code == 400)

    print("\nCards full before this rule, or before today")
    cid, bc = customer(visits=10)
    check("an old full card (no scan since the rule): available", redeem(cid).status_code == 200)
    cid, bc = customer(visits=10)
    check("offered at the till", card_row(bc)["available"] is True)
    d = scan(bc, apply="card").json()
    check("handed over at this visit", d["applied"]["ok"] is True)
    cid, bc = customer(visits=11)
    db.rewards_earned.insert_one({"id": "old1", "tenant_id": "t1", "customer_id": cid, "status": "pending", "threshold": 10})
    check("an old banked reward: available", redeem(cid).status_code == 200)

    print("\nOne stamp below the limit, and one reward at a time")
    cid, bc = customer(visits=8)
    check("8/10: nothing announced", card_row(bc) is None)
    d = scan(bc, apply="card").json()
    check("9/10: refused, still short", d["applied"]["ok"] is False and "prochaine visite" not in d["applied"]["error"])
    cid, bc = customer(visits=0)
    check("empty card: refused", redeem(cid).status_code == 400)

    print("\nVisits per stamp (2 visits = 1 tampon, 10 tampons)")
    db.card_templates.insert_one({"tenant_id": "t3", "programme": "stamps", "reward_threshold_stamps": 10, "visits_per_stamp": 2})
    db.tenants.insert_one({"id": "t3", "slug": "t3", "name": "C", "is_active": True, "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "q@x.fr", "role": "business_owner", "tenant_id": "t3"})
    H3 = {"Authorization": "Bearer " + auth.create_access_token({"sub": "q@x.fr", "role": "business_owner", "tenant_id": "t3"})}
    cid, bc = customer("t3", visits=19)
    scan(bc, headers=H3)
    check("full at 20 visits: next visit", redeem(cid, H3).status_code == 400)
    scan(bc, headers=H3)
    check("21st visit: yes", redeem(cid, H3).status_code == 200)

    print("\n« Plusieurs personnes »")
    cid, bc = customer(visits=8)
    d = scan(bc, persons=4, apply="card").json()
    check("8 + 4 fills a card today and is banked", d["rewards_pending"] == 1 and d["stamps_in_cycle"] == 2 and d["applied"]["ok"] is False)
    check("not during this visit", redeem(cid).status_code == 400)
    check("still counted as waiting at the till", card_row(bc)["available"] is True)
    scan(bc)
    check("the next visit: yes", redeem(cid).status_code == 200)
    cid, bc = customer(visits=10)
    d = scan(bc, persons=12).json()
    check("10 + 12: two cards banked", d["rewards_pending"] == 2 and d["stamps_in_cycle"] == 2)
    check("the older one can go today", redeem(cid).status_code == 200)
    check("the one filled today cannot", redeem(cid).status_code == 400)
    scan(bc)
    check("…next visit it can", redeem(cid).status_code == 200)

    print("\nPaper stamps")
    cid, bc = customer()
    d = scan(bc, paper_stamps=9).json()
    check("9 paper + today = 10/10", d["stamps_in_cycle"] == 10 and d["reward_unlocked"] is True)
    check("today's visit completed it: next visit", redeem(cid).status_code == 400)
    scan(bc)
    check("the next visit: yes", redeem(cid).status_code == 200)
    cid, bc = customer()
    d = scan(bc, paper_stamps=10).json()
    check("a full paper card, earned on paper before today", d["rewards_pending"] == 1 and d["stamps_in_cycle"] == 1)
    check("can be handed over today", redeem(cid).status_code == 200)

    print("\nA points card (100 points, 20 per visit)")
    cid, bc = customer("t2", points=80)
    check("80 points: nothing to pick", card_row(bc, H2) is None)
    d = scan(bc, headers=H2, apply="card").json()
    check("100 reached today: not during this visit", d["points"] == 100 and d["applied"]["ok"] is False
          and "prochaine visite" in d["applied"]["error"])
    r = redeem(cid, H2)
    check(f"redeem refused too ({r.status_code})", r.status_code == 400 and "prochaine visite" in r.json()["detail"])
    check("no points spent", db.customers.find_one({"id": cid})["points"] == 100)
    check("the next visit offers it", card_row(bc, H2)["available"] is True)
    d = scan(bc, headers=H2, apply="card").json()
    check("handed over, the price taken", d["applied"]["ok"] is True and db.customers.find_one({"id": cid})["points"] == 20)
    check("the rest is not enough for another", redeem(cid, H2).status_code == 400)
    cid, bc = customer("t2", points=150)
    check("points earned long ago: available", redeem(cid, H2).status_code == 200)
    cid, bc = customer("t2", points=100)
    d = scan(bc, headers=H2).json()
    check("had the price before today: available during this visit", redeem(cid, H2).status_code == 200)
    check("what today earned stays on the balance", db.customers.find_one({"id": cid})["points"] == 20)

    print("\nAnother shop cannot get at it")
    cid, bc = customer(visits=10)
    check("another shop's owner: 404", redeem(cid, H2).status_code == 404)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
