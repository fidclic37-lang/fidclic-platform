"""
The card's reward starts from the shop's sector (user, 2026-10-05: a gym's
card said « Un café gratuit », like every other card).

Run: cd api && /usr/local/bin/python3 tests/test_sector_rewards.py
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
    import auth
    import httpx
    from services import sector_rewards as SR

    db = server.db
    passed = failed = 0

    def check(label, cond, extra=""):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))

    def http(method, url, bearer=None, **kw):
        headers = {"Authorization": "Bearer " + bearer} if bearer else {}

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def reward(tid):
        return (db.card_templates.find_one({"tenant_id": tid}) or {}).get("reward_description")

    now = dt.datetime.now(dt.timezone.utc)

    print("\nThe defaults")
    check("a gym's card offers a session", SR.default_reward("gym") == "Une séance offerte")
    check("a salon's offers a haircut", SR.default_reward("salon") == "Une coupe offerte")
    check("a café keeps its coffee", SR.default_reward("cafe") == "Un café offert")
    check("an unknown sector gets a neutral reward", SR.default_reward("crypto") == "Une récompense offerte")
    check("every onboarding sector has its own", all(SR.default_reward(s) for s in
          ("cafe", "restaurant", "pizzeria", "bakery", "bar", "spa", "salon", "gym", "retail", "other")))

    print("\nA shop already on the old placeholder (BLOO JOB, gym)")
    db.tenants.insert_one({"id": "g1", "slug": "gym", "name": "BLOO JOB", "sector": "gym", "plan": "vip",
                           "subscription_status": "trialing", "created_at": now})
    db.card_templates.insert_one({"tenant_id": "g1", "reward_description": "Un café gratuit",
                                  "reward_threshold_stamps": 10})
    db.tenants.insert_one({"id": "k1", "slug": "kebab", "name": "Chez Ali", "sector": "restaurant", "plan": "vip",
                           "subscription_status": "trialing", "created_at": now})
    db.card_templates.insert_one({"tenant_id": "k1", "reward_description": "Un kebab offert"})
    SR._synced = False
    SR.sync_all(db)
    check("the gym's card now offers a session", reward("g1") == "Une séance offerte", reward("g1"))
    check("a reward the merchant wrote is never touched", reward("k1") == "Un kebab offert")
    check("…and the other card settings stay", db.card_templates.find_one({"tenant_id": "g1"})["reward_threshold_stamps"] == 10)

    print("\nThe pass and the web card read it")
    db.customers.insert_one({"id": "c1", "tenant_id": "g1", "name": "Léa", "barcode_id": "FT-GYM00001",
                             "visits": 0, "points": 0, "created_at": now})
    payload = server._serialize_card_payload(db.customers.find_one({"id": "c1"}))
    check("the card payload says « Une séance offerte »", payload["card"]["reward_description"] == "Une séance offerte")
    from features import wallet_passes as W
    W._db = db
    _pj = W.build_pass_json(payload)
    back = {f["key"]: f["value"] for f in (_pj.get("storeCard") or _pj.get("generic"))["backFields"]}
    check("Wallet's « Prochaine récompense » no longer mentions coffee",
          "séance" in back["next_reward"] and "café" not in back["next_reward"], back["next_reward"])
    check("…nor « Programme de fidélité »", back["program"].startswith("Une séance offerte"), back["program"])

    print("\nThe dashboard reminder")
    OWN = auth.create_access_token({"sub": "o@gym.fr", "role": "business_owner", "tenant_id": "g1"})
    MAN = auth.create_access_token({"sub": "m@gym.fr", "role": "manager", "tenant_id": "g1"})
    db.users.insert_one({"email": "o@gym.fr", "role": "business_owner", "tenant_id": "g1"})
    home = http("GET", "/api/owner/home/overview", OWN).json()
    check("asks the owner to choose, showing today's reward",
          (home.get("reward_setup") or {}).get("reward") == "Une séance offerte", str(home.get("reward_setup")))
    check("the manager is not asked (only the owner can change the card)",
          http("GET", "/api/owner/home/overview", MAN).json().get("reward_setup") is None)
    db.users.insert_one({"email": "o@kebab.fr", "role": "business_owner", "tenant_id": "k1"})
    OWN_K = auth.create_access_token({"sub": "o@kebab.fr", "role": "business_owner", "tenant_id": "k1"})
    check("a shop that wrote its own reward is not asked",
          http("GET", "/api/owner/home/overview", OWN_K).json().get("reward_setup") is None)

    print("\nThe owner saves the Carte de fidélité")
    settings = http("GET", "/api/owner/card/settings", OWN).json()
    check("the page shows the sector's reward", settings["programme"]["reward_description"] == "Une séance offerte")
    r = http("PUT", "/api/owner/card/settings", OWN, json={"reward_description": "Une séance offerte"})
    check("saving keeps it", r.status_code == 200 and reward("g1") == "Une séance offerte", r.text[:200])
    check("…and it is now theirs: no more reminder",
          http("GET", "/api/owner/home/overview", OWN).json().get("reward_setup") is None)
    http("PUT", "/api/owner/etablissement", OWN, json={"business": {"sector": "spa"}})
    check("a chosen reward does not follow a sector change", reward("g1") == "Une séance offerte", reward("g1"))

    print("\nA sector change before any choice")
    db.tenants.insert_one({"id": "s1", "slug": "spa", "name": "Zen", "sector": "salon", "plan": "vip",
                           "subscription_status": "trialing", "created_at": now})
    db.users.insert_one({"email": "o@zen.fr", "role": "business_owner", "tenant_id": "s1"})
    OWN_S = auth.create_access_token({"sub": "o@zen.fr", "role": "business_owner", "tenant_id": "s1"})
    SR.apply(db, "s1")
    check("starts as a salon", reward("s1") == "Une coupe offerte")
    http("PUT", "/api/owner/etablissement", OWN_S, json={"business": {"sector": "spa"}})
    check("follows the new sector", reward("s1") == "Un soin offert", reward("s1"))

    print("\nThe old designer saves the whole template")
    old = {"tenant_id": "s1", "reward_description": "Un soin offert"}
    pl = {"reward_description": "Une récompense offerte"}       # the model's default
    SR.on_full_save(db, "s1", pl, old)
    check("a placeholder never overwrites the card's reward",
          pl["reward_description"] == "Un soin offert" and not pl.get("reward_chosen"))
    pl2 = {"reward_description": "Un massage de 20 min"}
    SR.on_full_save(db, "s1", pl2, old)
    check("a new wording is the merchant's choice", pl2.get("reward_chosen") is True)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
