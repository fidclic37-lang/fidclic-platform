"""
Parrainage, friend after friend (user, 2026-10-09: « my second friend scanned
my QR, came and bought — I got nothing »):
  • every new friend pays the parrain, not only the first;
  • someone who already has a card at the shop (even removed from Wallet)
    gets it back and is told parrainage is for new customers — no silent
    « Bienvenue »;
  • when the points land, both sides are told why: the Wallet pass shows
    « Votre ami Marie est venu… » on the points change, Google gets a
    message, web push too; no SMS.

Run: cd api && /usr/local/bin/python3 tests/test_parrainage_repeat.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-parrainage-repeat")
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
    import features.push_subscriptions as PS

    db = server.db
    R._db = db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    woken, pushed, sms = [], [], []
    WP.notify_customer = lambda cid, message=None, google_notify=None: woken.append((cid, google_notify)) or {}
    PS.fan_out_to_customer = lambda tid, cid, title, body, url=None: pushed.append((cid, title, body)) or {"sent": 1}
    import services.sms as SMS
    SMS.send_sms = lambda *a, **k: sms.append(a) or {"sent": True}

    db.tenants.insert_one({"id": "t1", "slug": "petit-cafe", "name": "Le Petit Café", "is_active": True,
                           "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.referral_config.insert_one({"tenant_id": "t1", "enabled": True, "referrer_reward_points": 50,
                                   "referee_reward_points": 25, "minimum_visits_to_earn": 1, "reward_mode": "once"})

    def join(name, phone, parrain=None, email=""):
        body = {"name": name, "phone": phone, "email": email, "postal_code": "37000", "birthday": "1990-01-02", "consent": True}
        if parrain:
            body["parrain_barcode"] = parrain
        return http("POST", "/api/join/petit-cafe", json=body)

    def scan(bc):
        return http("POST", "/api/owner/scan", headers=H, json={"barcode_id": bc, "amount_paid": 10})

    def cust(bc):
        return db.customers.find_one({"barcode_id": bc}, {"_id": 0})

    me = join("Akshansh Test", "0611111111").json()["barcode_id"]
    db.customers.update_one({"barcode_id": me}, {"$set": {"points": 0}})
    # the defaults follow the mockups (no names, 2026-10-11); this owner names the
    # friend with the « Prénom de l'ami » chip — the names must reach both sides
    http("GET", "/api/owner/automations", headers=H)
    db.automations.update_one({"tenant_id": "t1", "scenario": "referral"}, {"$set": {
        "message.body": "Votre ami {filleul} {visite_ami} chez {nom_commerce} : +{points_gagnés} points.",
        "message_filleul.body": "Merci d'être venu grâce à {parrain} : +{points_gagnés} points de parrainage."}})

    print("1. Chaque ami paie le parrain, pas seulement le premier")
    friends = []
    for i, (name, phone) in enumerate([("Marie Dupont", "0622222222"), ("Sami Ben", "0633333333"),
                                       ("Lina Roy", "0644444444")], 1):
        r = join(name, phone, parrain=me).json()
        friends.append(r["barcode_id"])
        check(f"friend {i} signs up as a parrainage", r.get("parrainage") is True and not r.get("already_member"))
        scan(r["barcode_id"])
        check(f"…and after their first purchase the parrain has {50 * i} points", cust(me)["points"] == 50 * i)
    check("three rows, all paid", db.referral_redemptions.count_documents({"referrer_pending": False}) == 3)

    print("\n2. Les deux sont prévenus, avec la raison")
    marie = cust(friends[0])
    msgs = [b for c, t, b in pushed if c == cust(me)["id"]]
    check("the parrain hears each friend by name (web push)",
          any("Marie" in b and "+50 points" in b for b in msgs) and any("Lina" in b for b in msgs))
    check("the filleul hears whom they owe it to",
          any(c == marie["id"] and "Akshansh" in b and "+25 points de parrainage" in b for c, t, b in pushed))
    g = [n for c, n in woken if c == cust(me)["id"] and isinstance(n, dict)]
    check("Google Wallet gets a parrainage message for the parrain",
          g and g[-1]["kind"] == "parrainage" and "Lina" in g[-1]["body"])
    check("no SMS is spent on it", not sms)

    print("\n3. La carte Apple dit pourquoi les points ont bougé")
    pj = WP.build_pass_json(WP._card_payload(me))
    fields = [f for k in ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields", "backFields")
              for f in pj.get("generic", pj.get("storeCard", {})).get(k, [])]
    pts = next((f for f in fields if f.get("key") == "points"), None)
    check("the points field's changeMessage names the friend, with %@",
          pts and "Lina" in pts["changeMessage"] and "%@" in pts["changeMessage"])
    pj = WP.build_pass_json(WP._card_payload(friends[2]))
    fields = [f for k in ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields", "backFields")
              for f in pj.get("generic", pj.get("storeCard", {})).get(k, [])]
    pts = next((f for f in fields if f.get("key") == "points"), None)
    check("the filleul's card names the parrain", pts and "Akshansh" in pts["changeMessage"])
    db.customers.update_one({"barcode_id": me}, {"$inc": {"points": 5}})
    pj = WP.build_pass_json(WP._card_payload(me))
    fields = [f for k in ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields", "backFields")
              for f in pj.get("generic", pj.get("storeCard", {})).get(k, [])]
    pts = next((f for f in fields if f.get("key") == "points"), None)
    check("once the points move again, the usual message is back", pts and "Lina" not in pts["changeMessage"])
    db.customers.update_one({"barcode_id": me}, {"$set": {"points_news.points": 155,
                                                          "points_news.at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)}})
    check("and an old reason is never replayed", WP._points_news({"points_news": cust(me)["points_news"]}, 155) is None)

    print("\n4. Déjà client : pas de parrainage, et on le dit — sans donner la carte")
    # (user, 2026-10-09) a typed number never hands over the card it belongs to
    rows = db.referral_redemptions.count_documents({})
    r = join("Marie Dupont", "0622222222", parrain=friends[1])
    det = (r.json() or {}).get("detail") or {}
    check(f"Marie, already a customer: told so, parrainage refused ({r.status_code})",
          r.status_code == 409 and det.get("code") == "already_member"
          and "réservé aux nouveaux clients" in det.get("message", ""))
    check("…given no card and no key", "barcode_id" not in r.json() and "card_key" not in r.json())
    check("…and no parrainage is recorded", db.referral_redemptions.count_documents({}) == rows)
    db.customers.update_one({"barcode_id": friends[1]}, {"$set": {"wallet_removed_at": dt.datetime.now(dt.timezone.utc)}})
    r = join("Sami Ben", "+33 6 33 33 33 33", parrain=me)
    check("a card removed from Wallet is still a customer — the number written « +33 » too",
          r.status_code == 409 and db.referral_redemptions.count_documents({}) == rows)
    r = join("Akshansh Test", "0611111111", parrain=me)
    check("my own QR on a new phone: told my number has a card", r.status_code == 409)
    r = join("Akshansh Test", "0611111111")
    det = (r.json() or {}).get("detail") or {}
    check("without a parrain: already a member, nothing about parrainage",
          r.status_code == 409 and "parrainage" not in det.get("message", ""))

    print("\n5. « À chaque visite » : chaque visite est annoncée")
    db.referral_config.update_one({"tenant_id": "t1"}, {"$set": {"reward_mode": "every",
                                                                 "referrer_reward_points": 10, "referee_reward_points": 5}})
    r = join("Nora Lee", "0655555555", parrain=me).json()
    scan(r["barcode_id"])
    before = len(pushed)
    m0 = cust(me)["points"]
    scan(r["barcode_id"])
    check("the 2nd visit pays the parrain again", cust(me)["points"] == m0 + 10)
    check("…and says the friend came back", any("Nora est revenu" in b for c, t, b in pushed[before:]))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
