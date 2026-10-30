"""
« Plusieurs personnes » at the till (user, 2026-10-30): one client pays for
several people — a mother and her three children at the hairdresser — and
the card gets what each of them would have earned. « bina kisi fail k ».

Rules decided:
    · ON by default for the service trades (salon, spa: coiffure, barbier,
      institut, onglerie, spa / massage); any shop can switch it on or off
      (card settings), and sets the most people a visit may have (default 6)
    · ONE visit: visits, palier and the shop's figures count 1
    · × the number of people the till entered: the tampons, and the points
      of a « points par visite » card; « points par euro » and the cagnotte
      follow the amount, which already pays for everyone
    · a card filled past its end banks the full card, as any visit does

Run: cd api && python3 tests/test_multi_person.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-multi-person")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:300]}"))


def main():
    import server
    import auth
    import httpx
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import multi_person as MP

    db = server.db
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    WP.notify_tenant = lambda *a, **k: {"sent": 0}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    # ------------------------------------------------------------------
    print("\nWho has it by default")
    # ------------------------------------------------------------------
    sal = {"activity_key": "coiffure_femme"}
    check("a hairdresser: ON", MP.settings(sal, {})["enabled"] is True)
    check("a barber, an institut, an onglerie, a spa: ON",
          all(MP.settings({"activity_key": k}, {})["enabled"] for k in ("barbier", "institut", "onglerie", "spa_massage")))
    check("an old shop whose sector names the trade (« barbier »): ON", MP.settings({"sector": "barbier"}, {})["enabled"])
    check("a café, a bakery, a restaurant: OFF",
          not any(MP.settings({"activity_key": k}, {})["enabled"] for k in ("cafe", "boulangerie", "restaurant")))
    check("the shop's own switch wins, both ways",
          MP.settings({"activity_key": "cafe"}, {"multi_person": True})["enabled"] is True
          and MP.settings(sal, {"multi_person": False})["enabled"] is False)
    check("6 people at most by default", MP.settings(sal, {})["max"] == 6)
    check("the shop's own most (2–20); a value outside (never saved by the page) reads as the default 6",
          MP.settings(sal, {"multi_person_max": 3})["max"] == 3 and MP.settings(sal, {"multi_person_max": 20})["max"] == 20
          and MP.settings(sal, {"multi_person_max": 99})["max"] == 6 and MP.settings(sal, {"multi_person_max": 0})["max"] == 6)

    # ------------------------------------------------------------------
    db.tenants.insert_one({"id": "t1", "slug": "salon", "name": "Salon Léa", "is_active": True, "plan": "vip",
                           "subscription_status": "active", "sector": "salon", "activity_key": "coiffure_mixte"})
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "s@x.fr", "role": "staff", "tenant_id": "t1"}])
    tok = lambda email, role: {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": email, "role": role, "tenant_id": "t1"})}
    H, STAFF = tok("o@x.fr", "business_owner"), tok("s@x.fr", "staff")

    def template(**kw):
        db.card_templates.delete_many({"tenant_id": "t1"})
        db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10,
                                      "visits_per_stamp": 1, "points_per_visit": 10, "points_per_euro": 2,
                                      "cashback_rate": 5, "reward_description": "Un brushing offert", **kw})

    n = [0]

    def new_customer():
        n[0] += 1
        r = http("POST", "/api/join/salon", json={"name": f"Maman {n[0]}", "phone": f"06123400{n[0]:02d}",
                                                  "postal_code": "37000", "birthday": "1990-01-02", "consent": True})
        assert r.status_code == 200, r.text
        bc = r.json()["barcode_id"]
        return bc, db.customers.find_one({"barcode_id": bc})["id"]

    def scan(bc, persons=None, headers=STAFF, **extra):
        body = {"barcode_id": bc, "amount_paid": 40, **extra}
        if persons is not None:
            body["persons"] = persons
        return http("POST", "/api/owner/scan", headers=headers, json=body)

    def meter(cid):
        c = db.customers.find_one({"id": cid})
        return int(c.get("visits") or 0) - int(c.get("visits_at_last_redemption") or 0)

    template()
    print("\nThe till knows")
    bc, cid = new_customer()
    k = http("GET", f"/api/owner/scan/card?barcode={bc}", headers=STAFF).json()
    check("/scan/card says: on, 6 at most, a tampons card", k.get("multi") == {"enabled": True, "max": 6, "programme": "stamps"},
          k.get("multi"))

    print("\nA mother and her two children: 3 people on a tampons card")
    r = scan(bc, 3)
    d = r.json()
    check("the visit goes through", r.status_code == 200, r.text[:200])
    c = db.customers.find_one({"id": cid})
    check("ONE visit (palier and figures count 1)", c["visits"] == 1)
    check("3 tampons on the card", meter(cid) == 3 and d["stamps_on_card"] == 3)
    check("the receipt says +3 tampons, for 3 people", d["stamps_earned"] == 3 and d["persons"] == 3)
    check("still no points on a tampons card", c["points"] == 0)
    v = db.visits.find_one({"customer_id": cid})
    check("the visit row says 3 people and 3 tampons", v.get("persons") == 3 and v.get("stamps_awarded") == 3, v)
    check("the amount is the one paid, not × 3", v.get("amount_paid") == 40)

    print("\nOne person is an ordinary visit")
    for p in (None, 1):
        before = meter(cid)
        d = scan(bc, p).json()
        check(f"persons={p}: +1 tampon, persons 1", meter(cid) == before + 1 and d["stamps_earned"] == 1 and d["persons"] == 1)

    print("\nA card filled past its end")
    bc2, cid2 = new_customer()
    for _ in range(8):
        scan(bc2)
    d = scan(bc2, 3).json()
    check("8 + 3: the full card is banked « à remettre » and the new card holds 1",
          d["rewards_pending"] == 1 and d["stamps_on_card"] == 1 and meter(cid2) == 1, d)
    check("…and the till is told a card was completed by this visit", d["cards_completed"] == 1)
    bc3, cid3 = new_customer()
    for _ in range(7):
        scan(bc3)
    d = scan(bc3, 3).json()
    check("7 + 3 = exactly 10: the reward is unlocked now, nothing banked",
          d["reward_unlocked"] is True and d["rewards_pending"] == 0 and d["cards_completed"] == 1, d)
    template(reward_threshold_stamps=2)
    bc4, cid4 = new_customer()
    d = scan(bc4, 6).json()
    check("6 people on a 2-tampon card: 3 cards (2 banked + 1 unlocked)",
          d["cards_completed"] == 3 and d["rewards_pending"] == 2 and d["reward_unlocked"] is True, d)
    check("…each banked card is one « à remettre » row",
          db.rewards_earned.count_documents({"customer_id": cid4, "status": "pending"}) == 2)

    print("\nSeveral visits per tampon")
    template(visits_per_stamp=2)
    bc5, cid5 = new_customer()
    scan(bc5)                                            # half a tampon
    d = scan(bc5, 3).json()
    check("1 visit-unit + 3 people = 4 units = 2 tampons, +2 on the receipt",
          d["stamps_earned"] == 2 and d["stamps_on_card"] == 2, d)

    print("\nPoints and cagnotte")
    template(programme="points_visit", points_mode="per_visit")
    bc6, cid6 = new_customer()
    d = scan(bc6, 3).json()
    c = db.customers.find_one({"id": cid6})
    check("points par visite: 10 × 3 = 30", d["points_earned"] == 30 and c["points"] == 30 and c["points_lifetime"] == 30, d)
    template(programme="points_euro", points_mode="per_euro")
    bc7, cid7 = new_customer()
    d = scan(bc7, 3).json()
    check("points par euro: from the 40 € paid (80), never × 3", d["points_earned"] == 80, d)
    template(programme="cashback", points_mode="per_euro")
    bc8, cid8 = new_customer()
    d = scan(bc8, 3).json()
    check("cagnotte: 5 % of 40 € (2,00 €), never × 3", d["points_earned"] == 200, d)

    print("\nWith the paper card in the same visit")
    template()
    bc9, cid9 = new_customer()
    d = scan(bc9, 2, paper_stamps=4).json()
    check("4 paper + 2 people = 6 tampons, one visit", meter(cid9) == 6 and d["stamps_earned"] == 6
          and db.customers.find_one({"id": cid9})["visits"] == 1, d)

    print("\nRefused — and nothing written")
    bcx, cidx = new_customer()
    scan(bcx)
    snap = db.customers.find_one({"id": cidx}, {"_id": 0, "visits": 1, "visits_at_last_redemption": 1, "points": 1})
    nvis = db.visits.count_documents({"customer_id": cidx})
    for bad, why in ((7, "over 6"), (0, "zero"), (-2, "negative"), (2.5, "half a person"), (True, "true"),
                     ("abc", "text"), ([3], "a list")):
        r = scan(bcx, bad)
        check(f"persons={bad!r} ({why}) → refused ({r.status_code})", r.status_code in (400, 422), r.text[:120])
    check("…the client and the visits are untouched",
          db.customers.find_one({"id": cidx}, {"_id": 0, "visits": 1, "visits_at_last_redemption": 1, "points": 1}) == snap
          and db.visits.count_documents({"customer_id": cidx}) == nvis)
    r = scan(bcx, 7)
    check("the message says the most", "6 personnes au maximum" in r.text, r.text)

    print("\nThe owner can see it afterwards")
    h = http("GET", "/api/owner/history/activity?days=1&per_page=100", headers=H).json()
    rows = h.get("rows") or h.get("items") or []
    mine = [r for r in rows if (r.get("customer_id") == cid or r.get("customer_name") == "Maman 1") and "personnes" in (r.get("detail") or "")]
    check("Historique says « Scan de la carte en magasin · 3 personnes »",
          any(r.get("detail") == "Scan de la carte en magasin · 3 personnes" for r in mine), [r.get("detail") for r in rows[:5]])
    check("…and an ordinary scan keeps its words",
          any(r.get("detail") == "Scan de la carte en magasin" for r in rows))

    print("\nThe shop's own setting")
    r = http("PUT", "/api/owner/card/settings", headers=H, json={"multi_person_max": 3})
    check("the owner sets 3 at most", r.status_code == 200 and db.card_templates.find_one({"tenant_id": "t1"})["multi_person_max"] == 3)
    check("…4 is refused, 3 goes through", scan(bcx, 4).status_code == 400 and scan(bcx, 3).status_code == 200)
    for bad in (1, 21):
        check(f"a most of {bad} is refused", http("PUT", "/api/owner/card/settings", headers=H,
                                                  json={"multi_person_max": bad}).status_code == 400)
    r = http("PUT", "/api/owner/card/settings", headers=H, json={"multi_person": False})
    check("the owner switches it off", r.status_code == 200)
    r = scan(bcx, 2)
    check("…then 2 people is refused, with the reason", r.status_code == 400 and "plusieurs personnes" in r.text.lower(), r.text)
    check("…and a one-person visit still works", scan(bcx).status_code == 200)
    k = http("GET", f"/api/owner/scan/card?barcode={bcx}", headers=STAFF).json()
    check("…and the till no longer shows the option", k["multi"]["enabled"] is False)
    g = http("GET", "/api/owner/card/settings", headers=H).json()
    check("card settings show it off, with the most", g["programme"]["multi_person"] == {"enabled": False, "max": 3, "default": True}, g["programme"].get("multi_person"))
    check("staff cannot change it", http("PUT", "/api/owner/card/settings", headers=STAFF,
                                         json={"multi_person": True}).status_code == 403)
    http("PUT", "/api/owner/card/settings", headers=H, json={"multi_person": True})

    print("\nA café switches it on")
    db.tenants.insert_one({"id": "t2", "slug": "cafe", "name": "Café", "is_active": True, "plan": "vip",
                           "subscription_status": "active", "sector": "cafe"})
    db.users.insert_one({"email": "o2@x.fr", "role": "business_owner", "tenant_id": "t2"})
    H2 = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o2@x.fr", "role": "business_owner", "tenant_id": "t2"})}
    db.card_templates.insert_one({"tenant_id": "t2", "programme": "stamps", "reward_threshold_stamps": 10})
    r = http("POST", "/api/join/cafe", json={"name": "Paul", "phone": "0611220099", "postal_code": "37000",
                                             "birthday": "1990-01-02", "consent": True})
    bcc = r.json()["barcode_id"]
    check("off by default: 2 people refused",
          http("POST", "/api/owner/scan", headers=H2, json={"barcode_id": bcc, "amount_paid": 5, "persons": 2}).status_code == 400)
    http("PUT", "/api/owner/card/settings", headers=H2, json={"multi_person": True})
    r = http("POST", "/api/owner/scan", headers=H2, json={"barcode_id": bcc, "amount_paid": 5, "persons": 2})
    check("switched on: 2 people, 2 tampons", r.status_code == 200 and r.json()["stamps_earned"] == 2, r.text[:200])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
