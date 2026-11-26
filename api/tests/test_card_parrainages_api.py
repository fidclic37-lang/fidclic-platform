"""
« Mes parrainages » on the client's own card page (user, 2026-11-26): what
the shop gives each side, the friends this card invited and, for each,
« Récompensé » or « En attente » — exactly as the referral rows say.

  GET /api/card/{bc}/parrainages

Through the real HTTP endpoint on the mongomock server, with referrals
recorded and paid by features/referrals (record → visits → settle), the way
the signup and the till do it.

Run: cd api && python3 tests/test_card_parrainages_api.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-parrainages")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import auth
    import server
    import httpx
    from services import card_owner as CO
    from features import referrals as R

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def login(role, tenant):
        email = f"{role}-{tenant}@x.fr"
        db.users.update_one({"email": email}, {"$set": {"email": email, "role": role, "tenant_id": tenant}}, upsert=True)
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tenant})}

    now = datetime.now(timezone.utc).replace(microsecond=0)
    ago = lambda **kw: now - timedelta(**kw)   # noqa: E731

    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    db.tenants.insert_one({"id": "t2", "slug": "gs", "name": "GREEN SMOKE", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    real_tpl = db["card_templates"]._real
    real_tpl.insert_one({"tenant_id": "t1", "store_id": None, "programme": "stamps", "reward_threshold_stamps": 10})
    real_tpl.insert_one({"tenant_id": "t2", "store_id": None, "programme": "stamps"})

    def cust(cid, tid, name, visits=0, **kw):
        bc = f"FT-{cid.upper()}"
        db.customers.insert_one({"id": cid, "tenant_id": tid, "barcode_id": bc, "name": name, "email": f"{cid}@x.fr",
                                 "phone": "0611111111", "visits": visits, "points": 0, **kw})
        return bc

    def visit(cid, tid="t1"):
        db.customers.update_one({"id": cid}, {"$inc": {"visits": 1}})
        return R.settle(tid, cid)

    def config(**kw):
        base = {"tenant_id": "t1", "enabled": True, "minimum_visits_to_earn": 1, "reward_mode": "once",
                "referrer_reward_kind": "stamps", "referrer_reward_stamps": 2,
                "referee_reward_kind": "stamps", "referee_reward_stamps": 2}
        db.referral_config.replace_one({"tenant_id": "t1"}, {**base, **kw}, upsert=True)

    BC = cust("marie", "t1", "Marie Dupont", 5)
    BC_OTHER = cust("paul", "t1", "Paul Martin", 2)
    cust("zoe", "t2", "Zoé Ailleurs", 1)
    KEY, KEY_OTHER = CO.key_for(BC), CO.key_for(BC_OTHER)
    OWN = {"X-Card-Key": KEY}

    def get(bc=BC, headers=OWN):
        return http("GET", f"/api/card/{bc}/parrainages", headers=headers)

    config()

    print("1. Who may read it")
    check("no key, no login → 403", get(headers={}).status_code == 403)
    check("a wrong key → 403", get(headers={"X-Card-Key": "nope"}).status_code == 403)
    check("another card's key → 403", get(headers={"X-Card-Key": KEY_OTHER}).status_code == 403)
    check("unknown card → 404", get(bc="FT-NOPE0000").status_code == 404)
    check("the key in ?k= works", http("GET", f"/api/card/{BC}/parrainages", params={"k": KEY}).status_code == 200)
    check("the shop's owner login → 200", get(headers=login("business_owner", "t1")).status_code == 200)
    check("another business's owner → 403", get(headers=login("business_owner", "t2")).status_code == 403)

    print("2. Nobody invited yet")
    r = get().json()
    check(f"programme on ({r.get('enabled')})", r.get("enabled") is True)
    check(f"you get « 2 tampons » ({r.get('me')})", r["me"]["label"] == "2 tampons" and r["me"]["kind"] == "stamps")
    check(f"the friend gets « 2 tampons » ({r.get('friend')})", r["friend"]["label"] == "2 tampons")
    check("paid once, at the 1st visit", r["mode"] == "once" and r["need"] == 1)
    check("0 invited, 0 rewarded, 0 pending, nothing earned",
          (r["invited"], r["rewarded"], r["pending"]) == (0, 0, 0) and r["earned_label"] == "")
    check("an empty list", r["friends"] == [])

    print("3. Invitations, as the signup records them")
    for cid, name in (("thomas", "Thomas Petit"), ("sarah", "Sarah  Lemoine"), ("ines", "Inès Garcia")):
        cust(cid, "t1", name, 0)
        check(f"{cid} recorded as Marie's filleul", R.record("t1", BC, db.customers.find_one({"id": cid})) is not None)
    r = get().json()
    check(f"3 invited, all pending ({r['invited']}, {r['pending']})", r["invited"] == 3 and r["pending"] == 3 and r["rewarded"] == 0)
    check("every row « pending »", all(f["status"] == "pending" for f in r["friends"]))
    check("first names only", sorted(f["first_name"] for f in r["friends"]) == ["Inès", "Sarah", "Thomas"])
    leak = str(r)
    check("no surname, phone, e-mail, id or card number of a friend",
          not any(s in leak for s in ("Petit", "Lemoine", "Garcia", "0611111111", "@x.fr", "FT-THOMAS", "'thomas'")))
    check("pending rows: 0 visit out of 1", all(f["visits"] == 0 and f["need"] == 1 for f in r["friends"]))
    check("each row has the date the card was made", all(f.get("joined_at") for f in r["friends"]))

    print("4. A friend comes: « Récompensé », and what Marie got")
    visit("thomas")
    r = get().json()
    t = next(f for f in r["friends"] if f["first_name"] == "Thomas")
    check(f"Thomas rewarded ({t['status']})", t["status"] == "rewarded")
    check(f"with the date and « 2 tampons » for Marie ({t.get('rewarded_at')}, {t.get('given')})",
          t.get("rewarded_at") and t.get("given") == "2 tampons")
    check("1 rewarded, 2 pending", r["rewarded"] == 1 and r["pending"] == 2)
    check(f"earned: 2 tampons ({r['earned']})", r["earned"]["stamps"] == 2 and r["earned"]["points"] == 0
          and r["earned_label"] == "2 tampons")
    visit("thomas")
    r = get().json()
    check("« une fois »: a 2nd visit gives nothing more", r["earned"]["stamps"] == 2)

    print("5. « Dès la 2e visite »: progress, then paid")
    config(minimum_visits_to_earn=2)
    visit("sarah")
    r = get().json()
    s = next(f for f in r["friends"] if f["first_name"] == "Sarah")
    check(f"Sarah pending, 1 visit out of 2 ({s['status']}, {s['visits']}/{s['need']})",
          s["status"] == "pending" and s["visits"] == 1 and s["need"] == 2 and r["need"] == 2)
    visit("sarah")
    r = get().json()
    s = next(f for f in r["friends"] if f["first_name"] == "Sarah")
    check("then rewarded at her 2nd", s["status"] == "rewarded")
    check("earned: 4 tampons", r["earned"]["stamps"] == 4)

    print("6. « À chaque visite »: each visit counts, still accurate")
    config(minimum_visits_to_earn=1, reward_mode="every")
    visit("sarah")
    r = get().json()
    s = next(f for f in r["friends"] if f["first_name"] == "Sarah")
    check(f"Sarah's row: 2 payments, « 4 tampons » ({s.get('times')}, {s.get('given')})",
          s.get("times") == 2 and s.get("given") == "4 tampons")
    check("earned: 6 tampons", r["earned"]["stamps"] == 6 and r["mode"] == "every")

    print("7. Points and offers, each in their own words")
    config(referrer_reward_kind="points", referrer_reward_points=50, referee_reward_kind="offer",
           referee_reward_offer="-50 % sur la 1re coupe")
    r = get().json()
    check(f"you: « 50 points »; friend: the offer ({r['me']['label']} / {r['friend']['label']})",
          r["me"]["label"] == "50 points" and r["me"]["kind"] == "points" and r["friend"]["label"] == "-50 % sur la 1re coupe"
          and r["friend"]["kind"] == "offer")
    check("what was already paid stays as it was paid (tampons)", r["earned"]["stamps"] == 6 and r["earned"]["points"] == 0)
    config(referrer_reward_kind="offer", referrer_reward_offer="1 coupe offerte")
    r = get().json()
    check("offer for you", r["me"]["label"] == "1 coupe offerte" and r["me"]["kind"] == "offer")
    config(reward_mode="first_then", referrer_reward_stamps=2, referrer_reward_stamps_next=1)
    r = get().json()
    check(f"« Bonus puis récurrent »: the next amount too ({r['me'].get('next_label')})",
          r["mode"] == "first_then" and r["me"]["label"] == "2 tampons" and r["me"].get("next_label") == "1 tampon")

    print("8. Only this card's own invitations, newest first")
    cust("lea", "t1", "Léa Autre", 0)
    R.record("t1", BC_OTHER, db.customers.find_one({"id": "lea"}))
    db.referral_redemptions.insert_one({"tenant_id": "t2", "referrer_customer_id": "marie",
                                        "referee_customer_id": "zoe", "referrer_pending": True,
                                        "created_at": now})     # another business, same id
    r = get().json()
    names = [f["first_name"] for f in r["friends"]]
    check(f"Paul's filleule and another business's row are not here ({names})",
          "Léa" not in names and "Zoé" not in names and len(names) == 3)
    db.referral_redemptions.update_one({"referee_customer_id": "ines"}, {"$set": {"created_at": now + timedelta(seconds=5)}})
    r = get().json()
    check(f"newest invitation first ({[f['first_name'] for f in r['friends']]})", r["friends"][0]["first_name"] == "Inès")
    o = get(BC_OTHER, {"X-Card-Key": KEY_OTHER}).json()
    check("Paul sees his one filleule", [f["first_name"] for f in o["friends"]] == ["Léa"] and o["invited"] == 1)

    print("9. A friend whose card was deleted, a programme switched off")
    db.customers.delete_one({"id": "ines"})
    r = get().json()
    i = next((f for f in r["friends"] if f["status"] == "pending"), None)
    check(f"still counted, no name to show ({i})", r["invited"] == 3 and i is not None and i["first_name"] == "")
    db.referral_config.update_one({"tenant_id": "t1"}, {"$set": {"enabled": False}})
    r = get().json()
    check("switched off: enabled false, the history still there", r["enabled"] is False and r["invited"] == 3)
    db.referral_config.delete_one({"tenant_id": "t1"})
    r = get().json()
    check("never set up: off, no reward words", r["enabled"] is False and r["me"]["label"] == "" and r["friend"]["label"] == "")

    print("10. A long list is capped, the counts are not")
    config()
    for n in range(60):
        cid = f"bulk{n}"
        cust(cid, "t1", f"Ami{n} X", 0)
        R.record("t1", BC, db.customers.find_one({"id": cid}))
    r = get().json()
    check(f"invited counts all 63 ({r['invited']}); the list stops at 50 ({len(r['friends'])})",
          r["invited"] == 63 and len(r["friends"]) == 50 and r["more"] == 13)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
