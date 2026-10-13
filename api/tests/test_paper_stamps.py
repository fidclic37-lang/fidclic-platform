"""
Paper-card stamps moved onto the digital card at a scan (user, 2026-10-10:
« the owner enters 4 … the customer should see 4 stamps filled already …
100% accurate and strong, no exceptions »).

Rules decided: optional; 4 paper + today's visit = 5; 0 to a full card
(9 + today = the reward today, 10 = a full paper card banked « à récupérer »
and today starts the new card); never above a full card counting the stamps
already there; once per customer; the card's meter only — not visits,
points or palier.

Run: cd api && /usr/local/bin/python3 tests/test_paper_stamps.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-paper-stamps")
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

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Café", "is_active": True,
                           "plan": "vip", "subscription_status": "active"})
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "s@x.fr", "role": "staff", "tenant_id": "t1"}])
    tok = lambda email, role: {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": email, "role": role, "tenant_id": "t1"})}
    H, STAFF = tok("o@x.fr", "business_owner"), tok("s@x.fr", "staff")
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10,
                                  "visits_per_stamp": 1, "points_per_visit": 10, "reward_description": "Un café offert"})
    n = [0]

    def new_customer():
        n[0] += 1
        r = http("POST", "/api/join/cafe", json={"name": f"Client {n[0]}", "phone": f"06123400{n[0]:02d}",
                                                 "postal_code": "37000", "birthday": "1990-01-02", "consent": True})
        assert r.status_code == 200, r.text
        bc = r.json()["barcode_id"]
        return bc, db.customers.find_one({"barcode_id": bc})["id"]

    def scan(bc, paper=None, headers=H, **extra):
        body = {"barcode_id": bc, "amount_paid": 5, **extra}
        if paper is not None:
            body["paper_stamps"] = paper
        return http("POST", "/api/owner/scan", headers=headers, json=body)

    def card(cid):
        return server._serialize_card_payload(db.customers.find_one({"id": cid}))

    print("\n4 paper stamps on a new card (staff till)")
    bc, cid = new_customer()
    pre = http("GET", f"/api/owner/scan/preview?barcode={bc}", headers=STAFF).json()
    check("the preview shows the customer, 0/10 and room for 10 paper stamps",
          pre["name"] == "Client 1" and pre["stamps"] == 0 and pre["threshold"] == 10
          and pre["paper_max"] == 10 and pre["paper_done"] is False)
    r = scan(bc, 4, headers=STAFF)
    d = r.json()
    check("the scan goes through", r.status_code == 200)
    check("4 paper + today's visit = 5 stamps on the receipt", d["stamps_in_cycle"] == 5 and d["paper_stamps"] == 4)
    c = db.customers.find_one({"id": cid})
    check("one real visit only (not 5)", c["visits"] == 1)
    # a Tampons card gives tampons, never points (QA BUG-009, 2026-10-13)
    check("no points on a Tampons card (not 10, not 50)", c["points"] == 0)
    check("palier unchanged by paper stamps", c["tier"] == "bronze")
    check("the card the customer sees reads 5", card(cid)["customer"]["cycle_visits"] == 5
          and card(cid)["card"].get("stamps_earned", 5) == 5)
    check("recorded once: amount, by whom, when", c["paper_stamps"] == 4 and c["paper_stamps_by"] == "s@x.fr"
          and c.get("paper_stamps_at"))
    v = db.visits.find_one({"customer_id": cid})
    check("the visit row carries the 4 paper stamps", v and v.get("paper_stamps") == 4)
    log = db.customer_changes.find_one({"customer_id": cid, "kind": "paper_stamps"})
    check("the client's history says « Carte papier transférée : 4 tampons »",
          log and log["text"] == "Carte papier transférée : 4 tampons")
    fiche = http("GET", f"/api/owner/clients/{cid}/fiche", headers=H).json()
    check("the fiche shows the transfer", (fiche.get("client") or fiche).get("paper_stamps") == 4)

    print("\nOnce per customer")
    r = scan(bc, 3)
    check("a second transfer is refused (409), with the date and the number",
          r.status_code == 409 and "déjà été transférée" in r.json()["detail"] and "4 tampons" in r.json()["detail"])
    c2 = db.customers.find_one({"id": cid})
    check("…and nothing was written: no visit, no stamp", c2["visits"] == 1 and card(cid)["customer"]["cycle_visits"] == 5)
    check("the preview says it is done", http("GET", f"/api/owner/scan/preview?barcode={bc}", headers=H).json()["paper_done"])
    check("a scan without paper stamps still works", scan(bc).status_code == 200
          and card(cid)["customer"]["cycle_visits"] == 6)

    print("\n9 paper stamps: the reward today")
    bc, cid = new_customer()
    d = scan(bc, 9).json()
    check("9 + today = 10/10, reward unlocked", d["stamps_in_cycle"] == 10 and d["reward_unlocked"] is True)
    r = http("POST", "/api/owner/rewards/redeem", headers=H, json={"barcode_id": bc, "reward_name": "Café"})
    check("the reward can be handed over (1 real visit, a full card)", r.status_code == 200, )
    check("…and the card starts again from 0", card(cid)["customer"]["cycle_visits"] == 0)
    d = scan(bc).json()
    check("next visit = 1/10", d["stamps_in_cycle"] == 1 and not d["reward_unlocked"])

    print("\n10 paper stamps: a full paper card")
    bc, cid = new_customer()
    d = scan(bc, 10).json()
    check("the paper card is banked « à récupérer »", d["rewards_pending"] == 1 and d["cycle_restarted"] is True)
    check("today's visit starts the new card (1/10)", d["stamps_in_cycle"] == 1)
    r = http("POST", "/api/owner/rewards/redeem", headers=H, json={"barcode_id": bc, "reward_name": "Café"})
    check("its reward can be handed over", r.status_code == 200)
    check("…and the new card keeps its stamp", card(cid)["customer"]["cycle_visits"] == 1)

    print("\nNever above a full card")
    bc, cid = new_customer()
    for _ in range(5):
        scan(bc)
    check("preview: 5 on the card, room for 5", http("GET", f"/api/owner/scan/preview?barcode={bc}",
                                                    headers=H).json()["paper_max"] == 5)
    r = scan(bc, 6)
    check("5 digital + 6 paper is refused, saying 5 at most",
          r.status_code == 400 and "5 tampons de la carte papier au maximum" in r.json()["detail"])
    check("…and the refused scan wrote nothing", db.customers.find_one({"id": cid})["visits"] == 5)
    d = scan(bc, 5).json()
    check("5 + 5 = a full card; today starts the next one", d["rewards_pending"] == 1 and d["stamps_in_cycle"] == 1)

    print("\nWhat the field accepts")
    bc, cid = new_customer()
    for bad, why in ((11, "11 > a full card"), (-2, "negative"), (2.5, "2,5"), ("abc", "text"), (True, "true")):
        r = scan(bc, bad)
        check(f"refused: {why}", r.status_code in (400, 422))
    check("none of them wrote a visit", db.customers.find_one({"id": cid})["visits"] == 0)
    d = scan(bc, 0).json()
    check("0 is « no paper card »: a normal scan, the transfer stays open",
          d["stamps_in_cycle"] == 1 and db.customers.find_one({"id": cid}).get("paper_stamps") is None)
    d = scan(bc, "3").json()
    check("« 3 » typed as text is 3", d["paper_stamps"] == 3 and d["stamps_in_cycle"] == 5)

    print("\nTwo tills at once")
    bc, cid = new_customer()
    real_check = server._paper_stamps_check
    db.customers.update_one({"id": cid}, {"$set": {"paper_stamps": 2}})   # the other till won
    server._paper_stamps_check = lambda cust, tid, value, cv: {"stamps": 4, "visits": 4}   # this one read too early
    r = scan(bc, 4)
    server._paper_stamps_check = real_check
    check("the guarded write refuses the second transfer (409)", r.status_code == 409)
    c = db.customers.find_one({"id": cid})
    check("…with no visit and no stamps written", c["visits"] == 0 and int(c.get("visits_at_last_redemption") or 0) == 0)

    print("\n2 visits per stamp")
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"visits_per_stamp": 2}})
    bc, cid = new_customer()
    d = scan(bc, 3).json()
    c = db.customers.find_one({"id": cid})
    check("3 paper stamps = 6 visits on the meter, plus today's 1", c["visits"] == 1
          and c["visits"] - c["visits_at_last_redemption"] == 7)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"visits_per_stamp": 1}})

    print("\nAnother shop's card")
    db.tenants.insert_one({"id": "t2", "slug": "rival", "name": "Rival", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    H2 = {"Authorization": "Bearer " + auth.create_access_token({"sub": "r@x.fr", "role": "business_owner", "tenant_id": "t2"})}
    db.users.insert_one({"email": "r@x.fr", "role": "business_owner", "tenant_id": "t2"})
    bc, cid = new_customer()
    check("the preview never shows another shop's customer",
          http("GET", f"/api/owner/scan/preview?barcode={bc}", headers=H2).status_code == 404)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
