"""
One unit per programme, and parrainage rewards of any kind (user, 2026-10-13).

  • QA BUG-009: a Tampons card gave « +10 points » AND « +1 tampon » at every
    scan. A Tampons programme now gives tampons only; the receipt counts in
    tampons (« visites par tampon » included).
  • Parrainage: the owner chooses, for the parrain and for the filleul
    separately, points, tampons or an offer of their own (« 1 café offert »)
    handed over at the till with « Remettre » — whatever the programme.

Run: cd api && /usr/local/bin/python3 tests/test_programme_rewards.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-programme-rewards")
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
    import features.referrals as R
    import features.wallet_passes as WP
    import features.automations as AU

    db = server.db
    R._db = db
    WP.notify_customer = lambda *a, **k: {}
    fired = []
    AU.fire = lambda scenario, tid, cust, ctx=None: scenario == "referral" and fired.append((cust.get("id"), dict(ctx or {})))

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "petit-cafe", "name": "Le Petit Café", "is_active": True,
                           "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}

    def template(**kw):
        db.card_templates.delete_many({"tenant_id": "t1"})
        db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 10, "points_per_visit": 10, **kw})

    n = [0]

    def customer(**kw):
        n[0] += 1
        bc = f"FT-PR{n[0]:06d}"
        db.customers.insert_one({"id": f"c{n[0]}", "tenant_id": "t1", "barcode_id": bc, "name": f"Client {n[0]}",
                                 "visits": 0, "points": 0, **kw})
        return bc

    def scan(bc, **kw):
        r = http("POST", "/api/owner/scan", headers=H, json={"barcode_id": bc, "amount_paid": 12, **kw})
        assert r.status_code == 200, r.text
        return r.json()

    cust = lambda bc: db.customers.find_one({"barcode_id": bc}, {"_id": 0})   # noqa: E731

    print("\nBUG-009 — a Tampons card gives tampons only")
    template(programme="stamps")
    bc = customer(points=40)
    s = scan(bc)
    check(f"no points ({s['points_earned']})", s["points_earned"] == 0 and cust(bc)["points"] == 40)
    check("points already on the card stay", cust(bc)["points"] == 40)
    check(f"the receipt says « stamps », +1 tampon, 1/10 ({s['programme']}, {s['stamps_earned']}, "
          f"{s['stamps_on_card']}/{s['stamps_target']})",
          s["programme"] == "stamps" and s["stamps_earned"] == 1 and (s["stamps_on_card"], s["stamps_target"]) == (1, 10))

    template(programme="stamps", visits_per_stamp=2)
    bc = customer()
    a, b = scan(bc), scan(bc)
    check(f"2 visits per tampon: 1st visit +0, 2nd +1 ({a['stamps_earned']}, {b['stamps_earned']})",
          a["stamps_earned"] == 0 and b["stamps_earned"] == 1)
    check(f"counted in tampons: 1/10, not 2/20 ({b['stamps_on_card']}/{b['stamps_target']})",
          (b["stamps_on_card"], b["stamps_target"]) == (1, 10))

    template(points_mode="per_visit")           # saved before « programme » existed: a Tampons card
    bc = customer()
    check("an older card without « programme »: tampons, no points", scan(bc)["points_earned"] == 0)

    print("\n…and a Points card gives points only")
    template(programme="points_visit", points_mode="per_visit", points_per_visit=10)
    bc = customer()
    s = scan(bc)
    check(f"per visit: +10 ({s['points_earned']}, {s['programme']})", s["points_earned"] == 10 and s["programme"] == "points_visit")
    template(programme="points_euro", points_mode="per_euro", points_per_euro=2)
    check("per euro: 12 € × 2 = +24", scan(customer())["points_earned"] == 24)

    print("\nQA R7 BUG-009 — a Points card leaves no tampon behind")
    template(programme="points_euro", points_mode="per_euro", points_per_euro=2, reward_points=100)
    bc = customer()
    s = scan(bc, amount_paid=12.5)
    v = db.visits.find_one({"customer_id": cust(bc)["id"]}, sort=[("visit_time", -1)])
    check(f"12,50 € × 2 = +25 points, and the visit stores no tampon ({v.get('points_awarded')}, {v.get('stamps_awarded')})",
          s["points_earned"] == 25 and v.get("points_awarded") == 25 and v.get("stamps_awarded") == 0)
    check(f"the receipt says no tampon ({s['stamps_earned']}, {s['stamps_in_cycle']}, {s['reward_unlocked']})",
          s["stamps_earned"] == 0 and s["stamps_in_cycle"] == 0 and s["reward_unlocked"] is False)
    c = cust(bc)
    check(f"the visit counts as a visit ({c['visits']}), its stamp card does not move "
          f"({c['visits'] - int(c.get('visits_at_last_redemption') or 0)})",
          c["visits"] == 1 and c["visits"] - int(c.get("visits_at_last_redemption") or 0) == 0)
    for _ in range(11):                               # more than a stamp card's 10
        scan(bc, amount_paid=1)
    check(f"11 more points visits bank no stamp reward ({db.rewards_earned.count_documents({'customer_id': cust(bc)['id']})})",
          db.rewards_earned.count_documents({"customer_id": cust(bc)["id"]}) == 0)
    check("…and send no « carte complète » push",
          db.push_notifications.count_documents({"customer_id": cust(bc)["id"], "type": "reward_unlocked"}) == 0)
    template(programme="stamps")                      # the shop goes back to Tampons
    s2 = scan(bc)
    check(f"back on Tampons: the first tampon is today's, not « 13/10 » ({s2['stamps_on_card']}/{s2['stamps_target']})",
          s2["stamps_on_card"] == 1 and s2["reward_unlocked"] is False)
    template(programme="points_euro", points_mode="per_euro", points_per_euro=2)
    check("per euro, a visit at 0 € earns nothing (it gave « points par visite »)",
          scan(customer(), amount_paid=0)["points_earned"] == 0)
    template(programme="points_visit", points_mode="per_visit", points_per_visit=10)
    check("per visit, a visit at 0 € still earns its points", scan(customer(), amount_paid=0)["points_earned"] == 10)

    print("\nQA R7 F28 — the card describes the programme the shop set")
    template(programme="points_euro", points_mode="per_euro", points_per_euro=2, reward_points=100,
             reward_description="Un dessert offert")
    bc = customer(points=25)
    card = server._serialize_card_payload_raw(cust(bc))["card"]
    check(f"the web card gets the programme and its rate ({card.get('programme_kind')}, {card.get('points_per_euro')}, "
          f"{card.get('reward_points')})",
          card.get("programme_kind") == "points_euro" and card.get("points_per_euro") == 2 and card.get("reward_points") == 100)
    check(f"« {{points_remaining}} » on a points card: 100 − 25 = 75 ({server._compute_points_to_next_reward(cust(bc), 't1')})",
          server._compute_points_to_next_reward(cust(bc), "t1") == 75)
    template(programme="points", points_mode="per_euro")                  # a card saved before « points_euro »
    check("an older « points » card reads as points per euro",
          server._serialize_card_payload_raw(cust(bc))["card"].get("programme_kind") == "points_euro")

    print("\nParrainage settings — each side its own kind")
    base = {"enabled": True, "minimum_visits_to_earn": 1, "reward_mode": "once"}
    r = http("PUT", "/api/owner/referrals/config", headers=H, json={**base, "referrer_reward_kind": "gold"})
    check(f"an unknown kind: refused ({r.status_code})", r.status_code == 400)
    r = http("PUT", "/api/owner/referrals/config", headers=H, json={**base, "referee_reward_kind": "offer"})
    check(f"an offer with no words: refused ({r.json().get('detail')})", r.status_code == 400 and "filleul" in r.json()["detail"])
    r = http("PUT", "/api/owner/referrals/config", headers=H, json={
        **base, "referrer_reward_kind": "stamps", "referrer_reward_stamps": 2,
        "referee_reward_kind": "offer", "referee_reward_offer": "  1 café   offert "})
    check("tampons for the parrain, an offer for the filleul: saved", r.status_code == 200
          and r.json()["referee_reward_offer"] == "1 café offert")

    template(programme="stamps", visits_per_stamp=1)
    parrain = customer(visits=3)
    inv = http("GET", f"/api/card/{parrain}/inviter").json()
    check(f"the signup form says what the filleul gets ({inv.get('referee_reward')})", inv.get("referee_reward") == "1 café offert")
    j = http("POST", "/api/join/petit-cafe", json={"name": "Léa Amie", "phone": "0611000001", "postal_code": "37000",
                                                   "birthday": "02/01/1990", "consent": True, "parrain_barcode": parrain})
    check(f"the filleul signs up ({j.status_code})", j.status_code == 200)
    filleul = j.json()["barcode_id"]
    # the owner then sets the filleul's reward to nothing: today gives less
    # than the promise, so the promise stands (due(), user 2026-10-27 — a
    # change of kind would pay today's reward instead)
    http("PUT", "/api/owner/referrals/config", headers=H, json={**base, "referee_reward_kind": "points", "referee_reward_points": 0})
    before = cust(parrain).get("visits_at_last_redemption") or 0
    s = scan(filleul)
    check(f"the filleul's receipt: « 1 café offert » ({s.get('referral_reward')})", s.get("referral_reward") == "1 café offert")
    offers = [x for x in s["defi_rewards"] if x.get("kind") == "parrainage"]
    check(f"…waiting at the till with « Remettre » ({offers})", len(offers) == 1 and offers[0]["reward"] == "1 café offert")
    check("the filleul got no points for it", cust(filleul)["points"] == 0)
    after = cust(parrain).get("visits_at_last_redemption") or 0
    check(f"the parrain: +2 tampons on the card ({before} → {after})", before - after == 2)
    p = http("GET", f"/api/owner/scan/preview?barcode={parrain}", headers=H).json()
    check(f"…his card reads 5 tampons now (3 visits + 2) ({p.get('stamps')})", p.get("stamps") == 5)
    r = http("POST", f"/api/owner/defis/rewards/{offers[0]['id']}/redeem", headers=H)
    check(f"« Remettre »: handed over ({r.status_code})", r.status_code == 200)
    check("…and gone from the till", not [x for x in scan(filleul)["defi_rewards"] if x.get("kind") == "parrainage"])
    words = {cid: ctx.get("reward") for cid, ctx in fired}
    check(f"the messages name the reward ({words})",
          words.get(cust(parrain)["id"]) == "2 tampons" and words.get(cust(filleul)["id"]) == "1 café offert")

    print("\nParrainage in points still works, and « Bonus puis récurrent » with tampons")
    http("PUT", "/api/owner/referrals/config", headers=H, json={
        **base, "reward_mode": "first_then", "referrer_reward_kind": "points", "referrer_reward_points": 50,
        "referrer_reward_points_next": 10, "referee_reward_kind": "stamps", "referee_reward_stamps": 1,
        "referee_reward_stamps_next": 1})
    parrain2 = customer()
    j = http("POST", "/api/join/petit-cafe", json={"name": "Tom Ami", "phone": "0611000002", "postal_code": "37000",
                                                   "birthday": "02/01/1990", "consent": True, "parrain_barcode": parrain2})
    f2 = j.json()["barcode_id"]
    s1 = scan(f2)
    check(f"validation: parrain +50 points, filleul +1 tampon ({cust(parrain2)['points']}, {s1.get('referral_reward')})",
          cust(parrain2)["points"] == 50 and s1.get("referral_reward") == "1 tampon")
    check(f"…the filleul's card: 2 tampons after 1 visit ({s1['stamps_on_card']})", s1["stamps_on_card"] == 2)
    s2 = scan(f2)
    check(f"next visit: parrain +10, filleul +1 tampon ({cust(parrain2)['points']}, {s2['stamps_on_card']})",
          cust(parrain2)["points"] == 60 and s2["stamps_on_card"] == 4)

    print("\nA referral recorded before today (points only) is paid the shop's reward today, never less")
    old_p, old_f = customer(), customer()
    db.referral_redemptions.insert_one({"tenant_id": "t1", "referrer_customer_id": cust(old_p)["id"],
                                        "referee_customer_id": cust(old_f)["id"], "referrer_points_promised": 30,
                                        "referee_points_promised": 15, "referrer_pending": True})
    s3 = scan(old_f)
    check(f"parrain: today's 50 points, more than the 30 promised ({cust(old_p)['points']})", cust(old_p)["points"] == 50)
    check(f"filleul: the shop is in tampons now → 1 tampon, not 15 points ({s3.get('referral_reward')}, {cust(old_f)['points']})",
          s3.get("referral_reward") == "1 tampon" and cust(old_f)["points"] == 0)


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
