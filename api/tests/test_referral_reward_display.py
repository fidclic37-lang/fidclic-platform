"""
Parrainage page shows what was really given (user, 2026-10-27: « settings say
Tampons, the page says 0 points — the friends got their stamps in Wallet »):
  • each row, the top parrains, the « … offerts » card and the CSV speak the
    reward the shop chose — tampons, points or its own offer — never
    « 0 points » for a reward that was handed over;
  • what a row gave is written on the row when it is paid (`*_given`), so a
    later change of setting cannot rewrite history;
  • rows paid before that field existed read back from what they promised;
  • a pending row shows its promise in its own kind (« 2 tampons »), not the
    old points number left beside it.

Run: cd api && /usr/local/bin/python3 tests/test_referral_reward_display.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-referral-display")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def unit(R):
    print("1. Ce qu'une ligne a donné (unit)")
    z = {"points": 0, "stamps": 0, "offers": 0, "offer_text": ""}
    check("pending → nothing given", R.given({"referrer_pending": True, "referrer_points": 50}, "referrer") == z)
    check("new rows read *_given as written",
          R.given({"referrer_pending": False, "referrer_given": {"points": 0, "stamps": 4, "offers": 0}}, "referrer")["stamps"] == 4)
    legacy = {"referrer_pending": False, "referrer_points": 0, "rewarded_visits": 1,
              "referrer_reward_promised": {"kind": "stamps", "n": 2},
              "referee_reward_promised": {"kind": "offer", "text": "1 café offert"}}
    check("legacy stamps row → its promised tampons", R.given(legacy, "referrer")["stamps"] == 2)
    g = R.given(legacy, "referee")
    check("legacy offer row → one offer, with its words", g["offers"] == 1 and g["offer_text"] == "1 café offert")
    check("legacy points row → its points",
          R.given({"referrer_pending": False, "referrer_points": 50}, "referrer") == {**z, "points": 50})
    check("legacy row older than the promise fields → the points it carries",
          R.given({"referrer_pending": False, "referrer_points": 30, "referee_points": 10}, "referee")["points"] == 10)
    rep = {**legacy, "rewarded_visits": 3}
    cfg = {"reward_mode": "first_then", "referrer_reward_kind": "stamps", "referrer_reward_stamps_next": 1}
    check("legacy repeat row: first promise + the later visits from the settings (2+1+1)",
          R.given(rep, "referrer", cfg)["stamps"] == 4)
    check("garbage in the row never goes negative or crashes",
          R.given({"referrer_pending": False, "referrer_given": {"points": -5, "stamps": "x", "offers": None}},
                  "referrer") == z)
    check("missing row fields → nothing", R.given({}, "referrer") == z)

    print("\n2. En mots")
    check("nothing → «»", R.words(z) == "")
    check("1 tampon", R.words({**z, "stamps": 1}) == "1 tampon")
    check("2 tampons", R.words({**z, "stamps": 2}) == "2 tampons")
    check("1 point / 50 points", R.words({**z, "points": 1}) == "1 point" and R.words({**z, "points": 50}) == "50 points")
    check("one offer → its own words", R.words({**z, "offers": 1, "offer_text": "1 café offert"}) == "1 café offert")
    check("one offer without words → « 1 offre »", R.words({**z, "offers": 1}) == "1 offre")
    check("three offers → « 3 offres »", R.words({**z, "offers": 3, "offer_text": "1 café offert"}) == "3 offres")
    check("mixed → every part", R.words({**z, "stamps": 2, "points": 50}) == "2 tampons · 50 points")


def integration(server, auth, R, db):
    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    import httpx  # noqa: F811 — used by http() above
    globals()["httpx"] = httpx

    db.tenants.insert_one({"id": "t1", "slug": "royal-test", "name": "Royal Test", "is_active": True,
                           "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}

    def settings(**kw):
        base = {"enabled": True, "minimum_visits_to_earn": 1, "reward_mode": "once",
                "referrer_reward_kind": "stamps", "referee_reward_kind": "stamps",
                "referrer_reward_stamps": 2, "referee_reward_stamps": 2,
                "referrer_reward_points": 50, "referee_reward_points": 25}
        r = http("PUT", "/api/owner/referrals/config", headers=H, json={**base, **kw})
        assert r.status_code == 200, r.text

    def join(name, phone, parrain=None):
        body = {"name": name, "phone": phone, "email": "", "postal_code": "37000",
                "birthday": "1990-01-02", "consent": True}
        if parrain:
            body["parrain_barcode"] = parrain
        return http("POST", "/api/join/royal-test", json=body).json()["barcode_id"]

    def scan(bc):
        return http("POST", "/api/owner/scan", headers=H, json={"barcode_id": bc, "amount_paid": 10})

    def view():
        return http("GET", "/api/owner/referrals/overview", headers=H).json()

    print("\n3. Tampons choisis → la page parle en tampons (le bug Royal Trim)")
    settings()
    ahmed = join("Ahmed Alami", "0611111111")
    ingar = join("Ingrid Argiola", "0622222222", parrain=ahmed)
    scan(ingar)
    v = view()
    card = {c["key"]: c for c in v["cards"]}["points"]
    check(f"card says « Tampons offerts » ({card['label']})", card["label"] == "Tampons offerts")
    check(f"…and counts both sides' tampons: 4 ({card['value']})", card["value"] == 4)
    row = v["recent"][0]
    check(f"row reward « 2 tampons » ({row.get('reward')!r})", row.get("reward") == "2 tampons")
    check("row reward kind is stamps", row.get("reward_kind") == "stamps")
    top = v["top_parrains"][0]
    check(f"top parrain shows « 2 tampons » ({top.get('reward')!r})", top.get("reward") == "2 tampons")
    lst = http("GET", "/api/owner/referrals/list", headers=H).json()
    check("« Voir tous » list says the same", lst["rows"][0].get("reward") == "2 tampons")
    csv = http("GET", "/api/owner/referrals/export", headers=H).text
    check("CSV column is « Récompense » with « 2 tampons »", "Récompense" in csv and "2 tampons" in csv
          and "Récompense (points)" not in csv)
    check("the row stores what it gave", (db.referral_redemptions.find_one(
        {"referee_customer_id": db.customers.find_one({"barcode_id": ingar})["id"]}) or {})
          .get("referrer_given", {}).get("stamps") == 2)

    print("\n4. Une 2e caisse qui rejoue la même visite ne double rien")
    fid = db.customers.find_one({"barcode_id": ingar})["id"]
    R.settle("t1", fid)
    R.settle("t1", fid)
    check("still 4 tampons on the card", {c["key"]: c for c in view()["cards"]}["points"]["value"] == 4)

    print("\n5. En attente : la promesse dans son propre genre (le « 50 points » de Mahdi)")
    adams = join("Adams Yao", "0633333333", parrain=ahmed)
    pid = db.customers.find_one({"barcode_id": adams})["id"]
    db.referral_redemptions.update_one({"referee_customer_id": pid}, {"$set": {"referrer_points_promised": 50}})
    pend = [r for r in view()["recent"] if r["status"] == "pending"][0]
    check(f"pending row shows « 2 tampons » ({pend.get('reward')!r})", pend.get("reward") == "2 tampons")
    check("pending gives nothing to the card yet", {c["key"]: c for c in view()["cards"]}["points"]["value"] == 4)

    print("\n6. Bonus puis récurrent en tampons")
    settings(reward_mode="first_then", referrer_reward_stamps_next=1, referee_reward_stamps_next=1)
    lilian = join("Lilian Petit", "0644444444", parrain=ahmed)
    for _ in range(3):
        scan(lilian)
    lid = db.customers.find_one({"barcode_id": lilian})["id"]
    row = db.referral_redemptions.find_one({"referee_customer_id": lid})
    check(f"parrain got 2 + 1 + 1 = 4 tampons on this row ({row.get('referrer_given')})",
          (row.get("referrer_given") or {}).get("stamps") == 4)
    r = [x for x in view()["recent"] if x["filleul"]["name"].startswith("Lilian")][0]
    check(f"row reads « 4 tampons » ({r.get('reward')!r})", r.get("reward") == "4 tampons")

    print("\n6b. Ligne payée avant ce correctif, puis une nouvelle visite")
    old = join("Olga Ancienne", "0677777777", parrain=ahmed)
    scan(old)
    oid = db.customers.find_one({"barcode_id": old})["id"]
    db.referral_redemptions.update_one({"referee_customer_id": oid},
                                       {"$unset": {"referrer_given": "", "referee_given": ""}})
    scan(old)
    row = db.referral_redemptions.find_one({"referee_customer_id": oid})
    check(f"tally starts from the old payment: 2 + 1 = 3 ({row.get('referrer_given')})",
          (row.get("referrer_given") or {}).get("stamps") == 3)

    print("\n7. Une offre du commerce")
    settings(reward_mode="once", referrer_reward_kind="offer", referrer_reward_offer="1 coupe offerte",
             referee_reward_kind="offer", referee_reward_offer="-20 % sur la coupe")
    amjad = join("Amjad Kaci", "0655555555", parrain=ahmed)
    scan(amjad)
    r = [x for x in view()["recent"] if x["filleul"]["name"].startswith("Amjad")][0]
    check(f"row reads the offer « 1 coupe offerte » ({r.get('reward')!r})", r.get("reward") == "1 coupe offerte")
    card = {c["key"]: c for c in view()["cards"]}["points"]
    check(f"card follows the current setting: « Offres offertes » ({card['label']})", card["label"] == "Offres offertes")
    check(f"…counts the 2 offers ({card['value']})", card["value"] == 2)
    check(f"…and still names the tampons given before ({card.get('also')!r})", "tampons" in (card.get("also") or ""))

    print("\n7b. Le CSV n'exécute rien dans Excel (pentest 2026-10-27)")
    settings(reward_mode="once", referrer_reward_kind="offer", referrer_reward_offer='=HYPERLINK("http://x","clic")')
    evil = join("=cmd|' /C calc'!A0", "0688888888", parrain=ahmed)
    scan(evil)
    import csv as _csv, io as _io
    cells = [c for line in _csv.reader(_io.StringIO(http("GET", "/api/owner/referrals/export", headers=H).text.lstrip("﻿")),
                                       delimiter=";") for c in line]
    check("no cell starts with = + - @ (formula)", not any(c[:1] in ("=", "+", "-", "@") for c in cells))
    check("…the words are still there, behind a '", any(c.startswith("'=HYPERLINK") for c in cells))

    print("\n8. Points : rien ne change pour les commerces en points")
    db.referral_redemptions.delete_many({})
    settings(referrer_reward_kind="points", referee_reward_kind="points")
    a = join("Paul Points", "0666666666", parrain=ahmed)
    scan(a)
    v = view()
    card = {c["key"]: c for c in v["cards"]}["points"]
    check(f"« Points offerts » 75 ({card['label']}, {card['value']})",
          card["label"] == "Points offerts" and card["value"] == 75)
    check("row « 50 points », reward_points still 50 for older screens",
          v["recent"][0]["reward"] == "50 points" and v["recent"][0]["reward_points"] == 50)

    print("\n9. Aucun parrainage, réglage en tampons")
    db.referral_redemptions.delete_many({})
    settings()
    card = {c["key"]: c for c in view()["cards"]}["points"]
    check("« Tampons offerts » 0, no note", card["label"] == "Tampons offerts" and card["value"] == 0 and not card.get("also"))


def main():
    import server
    import auth
    import features.referrals as R
    import features.wallet_passes as WP
    import features.push_subscriptions as PS

    db = server.db
    R._db = db
    WP.notify_customer = lambda *a, **k: {}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    unit(R)
    integration(server, auth, R, db)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
