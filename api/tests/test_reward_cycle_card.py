"""
A full card restarts, its reward stays (user, 2026-10-09: « 10th visit done,
claimed or not, the meter must restart at the next visit and the reward stay
valid — otherwise it looks unprofessional »), and « Récompense proche » goes
out one visit before, counted in the shop's daily limit.

Run: cd api && /usr/local/bin/python3 tests/test_reward_cycle_card.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-reward-cycle-card")
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
    import services.sms as SMS

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    pushed, google, sms = [], [], []
    PS.fan_out_to_customer = lambda tid, cid, title, body, url=None: pushed.append((title, body)) or {"sent": 1}
    WP.notify_customer = lambda cid, message=None, google_notify=None: google.append(google_notify) or {}
    SMS.send_sms = lambda *a, **k: sms.append(a) or {"sent": True}

    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Café", "is_active": True,
                           "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10,
                                  "visits_per_stamp": 1, "reward_description": "Un café offert"})
    bc = http("POST", "/api/join/cafe", json={"name": "Marie Dupont", "phone": "0612345678", "postal_code": "37000",
                                              "birthday": "1990-01-02", "consent": True}).json()["barcode_id"]
    cid = db.customers.find_one({"barcode_id": bc})["id"]

    def scan():
        r = http("POST", "/api/owner/scan", headers=H, json={"barcode_id": bc, "amount_paid": 5})
        assert r.status_code == 200, r.text
        return r.json()

    def card():
        return server._serialize_card_payload(db.customers.find_one({"id": cid}))["customer"]

    def kinds(kind):
        return list(db.push_notifications.find({"customer_id": cid, "type": kind}))

    print("1. Une visite avant : « Récompense proche »")
    for _ in range(8):
        scan()
    check("not at 8/10", not kinds("near_reward"))
    google.clear()
    r = scan()
    check("at 9/10 it goes out", r["stamps_in_cycle"] == 9 and len(kinds("near_reward")) == 1)
    body = kinds("near_reward")[0]["body"]
    check("« Plus que 1 visite » — singular, names the reward", "1 visite " in body and "Un café offert" in body)
    check("Google Wallet gets it as a notifying message",
          any(isinstance(g, dict) and g.get("kind") == "near_reward" for g in google))

    print("\n2. 10e visite : carte pleine, récompense débloquée")
    r = scan()
    check("10/10, unlocked", r["stamps_in_cycle"] == 10 and r["reward_unlocked"] and r["rewards_pending"] == 0)
    check("the card shows 10 on this cycle", card()["cycle_visits"] == 10 and card()["rewards_pending"] == 0)
    check("one « Récompense débloquée »", len(kinds("reward_unlocked")) == 1)

    print("\n3. 11e visite sans réclamer : le compteur repart, la récompense reste")
    r = scan()
    check("the meter restarts at 1/10", r["stamps_in_cycle"] == 1 and r["cycle_restarted"] and not r["reward_unlocked"])
    check("the reward waits, still valid", r["rewards_pending"] == 1)
    c = card()
    check("the card: 1 on this cycle, 1 reward to collect, 11 lifetime visits",
          c["cycle_visits"] == 1 and c["rewards_pending"] == 1 and c["visits"] == 11)
    pj = WP.build_pass_json(WP._card_payload(bc))
    back = {f["key"]: f for f in pj.get("storeCard", pj.get("generic", {})).get("backFields", [])}
    check("the Wallet pass says a reward is waiting", "1 récompense à récupérer" in back["pending_rewards"]["value"])
    scan()
    check("no second « Récompense débloquée » at 12 (lifetime visits no longer count)", len(kinds("reward_unlocked")) == 1)

    print("\n4. La carte suivante : le rappel revient, puis le déblocage")
    for _ in range(6):
        scan()                                                 # 13 … 18
    r = scan()                                                 # 19 → 9/10 on card 2
    check("9/10 on the second card: « Récompense proche » again", r["stamps_in_cycle"] == 9
          and len(kinds("near_reward")) == 2)
    r = scan()                                                 # 20 → 10/10
    check("10/10: unlocked again, the first reward still waiting",
          r["reward_unlocked"] and r["rewards_pending"] == 1 and len(kinds("reward_unlocked")) == 2)

    print("\n5. Remise en caisse")
    red = http("POST", "/api/owner/rewards/redeem", headers=H, json={"customer_id": cid, "reward_name": "Café"})
    c = card()
    check(f"the oldest card is handed over first, the full card stays full ({red.status_code})",
          red.status_code == 200 and c["rewards_pending"] == 0 and c["cycle_visits"] == 10)
    http("POST", "/api/owner/rewards/redeem", headers=H, json={"customer_id": cid, "reward_name": "Café"})
    check("then the full card: the meter goes back to 0", card()["cycle_visits"] == 0)

    print("\n6. Compté dans la limite du jour")
    import features.send_rules as SR
    SR.put_rules(SR.RulesIn(per_client_day=1, per_client_week=0), token_data=type("O", (), {
        "email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})())
    server.dispatch_to_customer("t1", db.customers.find_one({"id": cid}), "Promo", "…", kind="campaign")
    for _ in range(8):
        scan()                                                 # 21 … 28 → 8/10
    google.clear()
    before = len(pushed)
    r = scan()                                                 # 29 → 9/10
    check("over the limit: « Récompense proche » waits for tomorrow",
          db.deferred_messages.count_documents({"kind": "near_reward", "status": "waiting"}) == 1
          and not any("presque" in t for t, b in pushed[before:]))
    check("…and the Wallet card stays quiet too", not any(isinstance(g, dict) and g.get("kind") == "near_reward" for g in google))
    check("no SMS anywhere", not sms)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
