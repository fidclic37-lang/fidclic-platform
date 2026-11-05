"""
« Aaj visit hui, next visit pr reward milne waala hai: scan pr show hona chahiye »
(user, 2026-11-05). The scan's answer names the reward the till can hand over at
the next visit, on every programme and through every door. What it says is
checked against what the next scan really does, over a long random walk: said =
the next scan hands it over; not said = it refuses.

Run: cd api && python3 tests/test_scan_next_visit_reward.py
"""
import asyncio
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-next-visit-reward")
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

    db = server.db
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def shop(tid, **card):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": tid.title(), "is_active": True, "plan": "vip", "subscription_status": "active"})
        db.users.insert_one({"email": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid})
        db.card_templates.insert_one({"tenant_id": tid, "reward_description": "Café offert", "multi_person": True, "multi_person_max": 20, **card})
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid})}

    n = [0]

    def client(tid, **kw):
        n[0] += 1
        cid = f"c{n[0]}"
        db.customers.insert_one({"id": cid, "tenant_id": tid, "name": "Client", "barcode_id": f"FT-{n[0]:06d}", "visits": 0, "points": 0,
                                 "points_lifetime": 0, "total_amount_paid": 0, **kw})
        return db.customers.find_one({"id": cid}, {"_id": 0})

    def scan(H, c, amount=5, **kw):
        r = http("POST", "/api/owner/scan", H, json={"barcode_id": c["barcode_id"], "amount_paid": amount, **kw})
        assert r.status_code == 200, r.text
        return r.json()

    print("\n1. Tampons")
    H = shop("st", programme="stamps", reward_threshold_stamps=3, visits_per_stamp=1)
    c = client("st")
    check("first visit, 1/3: nothing said", scan(H, c)["next_visit_reward"] is None)
    check("2/3: the next visit only fills the card, nothing said yet", scan(H, c)["next_visit_reward"] is None)
    d = scan(H, c)
    check("3/3, today fills it: said", d["next_visit_reward"] and d["next_visit_reward"]["count"] == 1)
    check("with the card's own reward", d["next_visit_reward"]["title"] == "Café offert")
    check("it was earned by this visit", d["next_visit_reward"]["earned_today"] is True)
    d = scan(H, c)
    check("next visit, not handed over: still said, not new", d["next_visit_reward"]["count"] == 1 and d["next_visit_reward"]["earned_today"] is False)
    d = scan(H, c, apply="card")
    check("handed over: gone", d["applied"]["ok"] is True and d["next_visit_reward"] is None)

    H1 = shop("one", programme="stamps", reward_threshold_stamps=1, visits_per_stamp=1)
    c = client("one")
    check("a card of one tampon: said from the first visit", scan(H1, c)["next_visit_reward"]["count"] == 1)

    H3 = shop("per", programme="stamps", reward_threshold_stamps=2, visits_per_stamp=3)
    c = client("per")
    said = [bool(scan(H3, c)["next_visit_reward"]) for _ in range(6)]
    check("3 visits a tampon, 2 tampons: said at the 6th visit, not before", said == [False] * 5 + [True])

    print("\n2. Plusieurs personnes and the paper card")
    c = client("st")
    d = scan(H, c, persons=2)
    check("2 of 3: nothing", d["next_visit_reward"] is None)
    c = client("st")
    d = scan(H, c, persons=3)
    check("3 people fill it: said", d["next_visit_reward"]["count"] == 1)
    c = client("st")
    d = scan(H, c, persons=7)
    check("7 people on a card of 3: two full cards", d["next_visit_reward"]["count"] == 2)
    c = client("st")
    d = scan(H, c, paper_stamps=2)
    check("2 on paper + today = full: said", d["next_visit_reward"]["count"] == 1)
    c = client("st")
    d = scan(H, c, paper_stamps=3)
    check("a full paper card, not handed over: said", d["next_visit_reward"]["count"] >= 1)

    print("\n3. Points")
    Hp = shop("pv", programme="points_visit", points_per_visit=20, reward_points=50)
    c = client("pv")
    check("20 of 50: nothing", scan(Hp, c)["next_visit_reward"] is None)
    check("40: nothing", scan(Hp, c)["next_visit_reward"] is None)
    d = scan(Hp, c)
    check("60: said", d["next_visit_reward"]["count"] == 1 and d["next_visit_reward"]["title"] == "Café offert")
    d = scan(Hp, c, apply="card")
    check("handed over, 30 left: gone", d["applied"]["ok"] is True and d["next_visit_reward"] is None)

    He = shop("pe", programme="points_euro", points_mode="per_euro", points_per_euro=10, reward_points=100)
    c = client("pe")
    check("0 €: no points, nothing", scan(He, c, amount=0)["next_visit_reward"] is None)
    check("9 €: 90 points, nothing", scan(He, c, amount=9)["next_visit_reward"] is None)
    d = scan(He, c, amount=1)
    check("exactly 100: said", d["next_visit_reward"]["count"] == 1)
    c = client("pe")
    d = scan(He, c, amount=35)
    check("350 points at once: three", d["next_visit_reward"]["count"] == 3)

    Hn = shop("noprice", programme="points_visit", points_per_visit=20, reward_points=0)
    c = client("noprice")
    check("a points card with no reward price: never said", scan(Hn, c)["next_visit_reward"] is None)

    print("\n4. Cashback")
    Hc = shop("cb", programme="cashback", cashback_rate=5)
    c = client("cb")
    check("a cagnotte has no reward to announce", scan(Hc, c, amount=500)["next_visit_reward"] is None)
    # the Carte page saves a price of 100 on every programme: on a cagnotte that is 1 €, not a reward
    Hc2 = shop("cb2", programme="cashback", cashback_rate=10, reward_points=100)
    c = client("cb2")
    check("nor with the price the Carte page leaves behind", scan(Hc2, c, amount=124)["next_visit_reward"] is None)
    check("nor before the visit", http("GET", f"/api/owner/scan/card?barcode={c['barcode_id']}", Hc2).json()["reward_ahead"] is None)

    c = client("cb2", visits=3)
    db.rewards_earned.insert_one({"id": "cb-old", "tenant_id": "cb2", "customer_id": c["id"], "status": "pending", "reward_description": "Café offert",
                                  "earned_at": server.datetime.now(server.timezone.utc)})
    d = scan(Hc2, c, amount=1)
    check("a reward earned before the shop moved to a cagnotte is still said", d["next_visit_reward"] and d["next_visit_reward"]["count"] == 1)
    check("and handed over", scan(Hc2, c, amount=1, apply="card")["applied"]["ok"] is True)

    c = client("noprice", visits=3)
    db.rewards_earned.insert_one({"id": "np-old", "tenant_id": "noprice", "customer_id": c["id"], "status": "pending", "reward_description": "Café offert",
                                  "earned_at": server.datetime.now(server.timezone.utc)})
    r = http("GET", f"/api/owner/scan/card?barcode={c['barcode_id']}", Hn).json()
    check("a points card with no price and a reward waiting: on the till's list, never lost", any(a["kind"] == "card" and a["available"] for a in r["applicables"]))
    d = scan(Hn, c)
    check("and said", d["next_visit_reward"] and d["next_visit_reward"]["count"] == 1)

    print("\n5. A reward waiting from before, several, a paused client, roles, other shops")
    c = client("st", visits=1)
    db.rewards_earned.insert_many([{"id": "old1", "tenant_id": "st", "customer_id": c["id"], "status": "pending", "earned_at": server.datetime.now(server.timezone.utc)},
                                   {"id": "old2", "tenant_id": "st", "customer_id": c["id"], "status": "pending", "earned_at": server.datetime.now(server.timezone.utc)}])
    d = scan(H, c, apply="card")
    check("two waiting, one handed over today: one more for next time", d["applied"]["ok"] is True and d["next_visit_reward"]["count"] == 1)
    c = client("st", paused_at=server.datetime.now(server.timezone.utc), visits=2)
    check("a paused client's card still works: said", scan(H, c)["next_visit_reward"]["count"] == 1)
    db.users.insert_one({"email": "s@st.fr", "role": "staff", "tenant_id": "st"})
    HS = {"Authorization": "Bearer " + auth.create_access_token({"sub": "s@st.fr", "role": "staff", "tenant_id": "st"})}
    c = client("st", visits=2)
    check("the staff's till says it too", scan(HS, c)["next_visit_reward"]["count"] == 1)
    r = http("POST", "/api/owner/scan", Hp, json={"barcode_id": c["barcode_id"], "amount_paid": 5})
    check("another shop's owner can't read it", r.status_code in (403, 404))
    c = client("st", deleted_at=server.datetime.now(server.timezone.utc))
    r = http("POST", "/api/owner/scan", H, json={"barcode_id": c["barcode_id"], "amount_paid": 5})
    check("a deleted client: refused, no receipt", r.status_code >= 400 and "next_visit_reward" not in r.text)

    print("\n6. Before the visit: what the till needs to warn")
    c = client("st", visits=1)
    card = http("GET", f"/api/owner/scan/card?barcode={c['barcode_id']}", H).json()
    check("stamps: how many visits short", card["reward_ahead"]["need_visits"] == 2 and card["reward_ahead"]["per_stamp"] == 1)
    check("with the reward's name", card["reward_ahead"]["title"] == "Café offert")
    c = client("pv", points=30)
    card = http("GET", f"/api/owner/scan/card?barcode={c['barcode_id']}", Hp).json()
    check("points a visit: how many short, what a visit earns", card["reward_ahead"]["need_points"] == 20 and card["reward_ahead"]["per_visit"] == 20)
    c = client("pe", points=90)
    card = http("GET", f"/api/owner/scan/card?barcode={c['barcode_id']}", He).json()
    check("points a euro: what a euro earns", card["reward_ahead"]["need_points"] == 10 and card["reward_ahead"]["per_euro"] == 10)
    c = client("st", visits=3)
    check("already full: nothing ahead", http("GET", f"/api/owner/scan/card?barcode={c['barcode_id']}", H).json()["reward_ahead"] is None)
    c = client("cb")
    check("cashback: nothing ahead", http("GET", f"/api/owner/scan/card?barcode={c['barcode_id']}", Hc).json()["reward_ahead"] is None)

    print("\n7. The public API says it too")
    from features import merchant_api as MA
    c = client("st", visits=2)
    caller = MA.ApiCaller(tenant_id="st", key_id="k1", key_name="Caisse", scopes=["visits:write"])
    out = MA.create_visit(MA.VisitIn(customer=c["id"], amount=5, external_id="ext-1"), caller)
    check("POST /api/v1/visits names it", out["next_visit_reward"]["count"] == 1)
    caller_p = MA.ApiCaller(tenant_id="pv", key_id="k2", key_name="Caisse", scopes=["visits:write"])
    c = client("pv", points=40)
    out = MA.create_visit(MA.VisitIn(customer=c["id"], amount=5, external_id="ext-2"), caller_p)
    check("a points card: named, not available yet", out["next_visit_reward"]["count"] == 1 and out["customer"]["reward_available"] is False)
    try:
        MA.redeem(MA.RedeemIn(customer=c["id"]), caller_p)
        check("the same visit can't take it", False)
    except server.HTTPException as e:
        check("the same visit can't take it", e.status_code == 409 and e.detail["code"] == "reward_next_visit")
    out = MA.create_visit(MA.VisitIn(customer=c["id"], amount=5, external_id="ext-3"), caller_p)
    check("the next visit: available", out["customer"]["reward_available"] is True)
    check("and the API's redeem hands it over", MA.redeem(MA.RedeemIn(customer=c["id"]), caller_p)["redeemed"] is True)
    c = client("pv")
    try:
        MA.redeem(MA.RedeemIn(customer=c["id"]), caller_p)
        check("nothing there: refused", False)
    except server.HTTPException as e:
        check("nothing there: refused", e.status_code == 409 and e.detail["code"] == "no_reward")

    print("\n7b. Several stores: the client's own card, whichever till reads it")
    Hg = shop("grp", programme="stamps", reward_threshold_stamps=5, visits_per_stamp=1,
              )
    db.tenants.update_one({"id": "grp"}, {"$set": {"branches": [{"id": "g-a", "name": "A", "status": "active"}, {"id": "g-b", "name": "B", "status": "active"}]}})
    db["card_templates"].insert_one({"tenant_id": "grp", "store_id": "g-b", "programme": "stamps", "reward_threshold_stamps": 2,
                                     "visits_per_stamp": 1, "reward_description": "Thé offert"})
    c = client("grp", branch_id="g-b", home_store_id="g-b", visits=1)
    HgA = {**Hg, "X-FidClic-Store": "g-a"}
    r = http("GET", f"/api/owner/scan/card?barcode={c['barcode_id']}", HgA).json()
    check("read at store A's till: its own store's reward, how many short", r["reward_ahead"] and r["reward_ahead"]["title"] == "Thé offert" and r["reward_ahead"]["need_visits"] == 1)
    d = http("POST", "/api/owner/scan", HgA, json={"barcode_id": c["barcode_id"], "amount_paid": 5, "branch_id": "g-a"}).json()
    check("scanned at store A: its own store's card fills, and says so", d["next_visit_reward"] and d["next_visit_reward"]["title"] == "Thé offert")
    r = http("GET", f"/api/owner/scan/card?barcode={c['barcode_id']}", HgA).json()
    row = next((a for a in r["applicables"] if a["kind"] == "card"), None)
    check("the next visit at A: that very reward is on the list", row and row["title"] == "Thé offert" and row["available"])
    d = http("POST", "/api/owner/scan", HgA, json={"barcode_id": c["barcode_id"], "amount_paid": 5, "branch_id": "g-a", "apply": "card"}).json()
    check("and it is handed over", d["applied"]["ok"] is True)

    # a client with no store yet, first scanned at store B: B's card from now on
    Hb = shop("first", programme="stamps", reward_threshold_stamps=10, visits_per_stamp=1)
    db.tenants.update_one({"id": "first"}, {"$set": {"branches": [{"id": "f-a", "name": "A", "status": "active", "is_main": True}, {"id": "f-b", "name": "B", "status": "active"}]}})
    db["card_templates"].insert_one({"tenant_id": "first", "store_id": "f-b", "programme": "stamps", "reward_threshold_stamps": 1,
                                     "visits_per_stamp": 1, "reward_description": "Thé offert"})
    c = client("first")
    d = http("POST", "/api/owner/scan", Hb, json={"barcode_id": c["barcode_id"], "amount_paid": 5, "branch_id": "f-b"}).json()
    check("no store yet, first scan at B: B's card is what is said", d["next_visit_reward"] and d["next_visit_reward"]["title"] == "Thé offert")
    d = http("POST", "/api/owner/scan", Hb, json={"barcode_id": c["barcode_id"], "amount_paid": 5, "branch_id": "f-b", "apply": "card"}).json()
    check("and the next scan hands it over", d["applied"]["ok"] is True)

    c = client("first")
    d = http("POST", "/api/owner/scan", Hb, json={"barcode_id": c["barcode_id"], "amount_paid": 5, "branch_id": "f-b", "persons": 3}).json()
    check("no store yet, 3 people at B whose card is 1 tampon: three, not one", d["next_visit_reward"]["count"] == 3)
    got = [http("POST", "/api/owner/scan", Hb, json={"barcode_id": c["barcode_id"], "amount_paid": 5, "branch_id": "f-b", "apply": "card"}).json()["applied"]["ok"]
           for _ in range(3)]
    check("and the next three visits each hand one over", got == [True, True, True])

    Hd = shop("nodesc", programme="stamps", reward_threshold_stamps=1, visits_per_stamp=1, reward_description="")
    c = client("nodesc")
    check("a card that names no reward: not the ladder's top rung", scan(Hd, c)["next_visit_reward"]["title"] == "Récompense fidélité")

    print("\n8. Said = the next scan hands it over; not said = it refuses. A long walk on every card")
    cards = {
        "w1": dict(programme="stamps", reward_threshold_stamps=1, visits_per_stamp=1),
        "w2": dict(programme="stamps", reward_threshold_stamps=2, visits_per_stamp=1),
        "w3": dict(programme="stamps", reward_threshold_stamps=4, visits_per_stamp=2),
        "w4": dict(programme="stamps", reward_threshold_stamps=10, visits_per_stamp=1),
        "w5": dict(programme="points_visit", points_per_visit=10, reward_points=30),
        "w6": dict(programme="points_euro", points_mode="per_euro", points_per_euro=10, reward_points=100),
        "w7": dict(programme="points_visit", points_per_visit=50, reward_points=50),
        # a cagnotte announces nothing: the till's own offer on it is the user's to decide (F39),
        # but what IS said must still be true
        "w8": dict(programme="cashback", cashback_rate=10, reward_points=200),
    }
    rnd = random.Random(20261105)
    wrong, steps, said_n, not_said_n = [], 0, 0, 0
    for tid, spec in cards.items():
        Hw = shop(tid, **spec)
        for _ in range(4):
            c = client(tid)
            promise = None
            for _s in range(40):
                steps += 1
                body = {"amount": rnd.choice([0, 1, 3, 9, 25]), "persons": rnd.choice([1, 1, 1, 2, 3])}
                if rnd.random() < .08 and spec["programme"] == "stamps":
                    body["paper_stamps"] = rnd.choice([1, 2])
                # half the visits try to take the reward: the answer must be what was promised
                take = rnd.random() < .5
                if take:
                    body["apply"] = "card"
                r = http("POST", "/api/owner/scan", Hw, json={"barcode_id": c["barcode_id"], "amount_paid": body["amount"],
                                                              **{k: v for k, v in body.items() if k != "amount"}})
                if r.status_code != 200:          # a paper card can be refused: not this test's subject
                    continue
                d = r.json()
                if take:
                    # a paper stamp can make a reward available at once: only « promised and refused » counts there
                    got = d["applied"]["ok"]
                    if promise is not None and not got:
                        wrong.append((tid, c["id"], _s, "promised, refused", d["applied"]))
                    if promise is None and got and "paper_stamps" not in body and spec["programme"] != "cashback":
                        wrong.append((tid, c["id"], _s, "not promised, handed over"))
                    said_n += promise is not None
                    not_said_n += promise is None
                promise = d["next_visit_reward"]
    print(f"    {steps} scans, {said_n} promised then taken, {not_said_n} not promised then refused")
    for w in wrong[:5]:
        print("   ", w)
    check("not one wrong promise", not wrong)
    check("the walk really tried both ways", said_n > 50 and not_said_n > 50)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
