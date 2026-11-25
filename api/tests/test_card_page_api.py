"""
The redesigned « Ma carte en ligne » page (2026-11-25), through the real
HTTP endpoints on the mongomock server:

  GET /api/card/{bc}/activity   the client's own history: visits, rewards,
                                validated parrainages — newest first, paged
  GET /api/card/{bc}            + customer.first_name, card.socials,
                                card.hero_photo_url (per establishment)
  PUT /api/owner/etablissement  + business.socials (the owner's 4 networks)
  POST /api/owner/card-template/details keeps tiktok / snapchat

Run: cd api && python3 tests/test_card_page_api.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-page-api")
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
                           "subscription_status": "active",
                           "branches": [{"id": "main", "name": "LIBERTÉ", "is_main": True},
                                        {"id": "pal", "name": "PALISSY"}]})
    db.tenants.insert_one({"id": "t2", "slug": "gs", "name": "GREEN SMOKE", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    A, B, C = "a" * 32, "b" * 32, "c" * 32
    real_tpl = db["card_templates"]._real
    real_tpl.insert_one({"tenant_id": "t1", "store_id": None, "programme": "stamps", "reward_threshold_stamps": 10,
                         "reward_description": "Une coupe offerte", "hero_image_url": f"/api/media/{A}",
                         "details": {"instagram": "@royaltrim", "facebook": "javascript:alert(1)",
                                     "tiktok": "https://www.tiktok.com/@royaltrim?lang=fr", "snapchat": "royaltrim"}})
    real_tpl.insert_one({"tenant_id": "t1", "store_id": "pal", "programme": "points_visit", "points_per_visit": 10,
                         "reward_description": "Un shampoing offert", "hero_image_url": f"/api/media/{A}",
                         "poster_image_url": f"/api/media/{B}"})
    real_tpl.insert_one({"tenant_id": "t2", "store_id": None, "programme": "stamps"})

    def cust(cid, tid, name, branch=None, **kw):
        bc = f"FT-{cid.upper()}"
        db.customers.insert_one({"id": cid, "tenant_id": tid, "barcode_id": bc, "name": name, "email": f"{cid}@x.fr",
                                 "phone": "0611111111", "visits": 3, "points": 0, "branch_id": branch, **kw})
        return bc

    BC = cust("marie", "t1", "  Marie   Dupont ", "main")
    BC_PAL = cust("paul", "t1", "Paul Martin", "pal")
    BC_T2 = cust("zoe", "t2", "Zoé Other")
    cust("lucas", "t1", "Lucas Bernard", "main")       # Marie's filleul
    cust("sofia", "t1", "Sofia Leroy", "main")         # Marie's parraine
    cust("noah", "t1", "Noah Pending", "main")         # a filleul not validated yet
    KEY, KEY_PAL = CO.key_for(BC), CO.key_for(BC_PAL)
    OWN = {"X-Card-Key": KEY}

    # Marie's history (main store) — plus other clients' rows that must never leak in
    db.visits.insert_many([
        {"id": "v1", "tenant_id": "t1", "customer_id": "marie", "branch_id": "main", "points_awarded": 0,
         "stamps_awarded": 1, "amount_paid": 18.5, "visit_time": ago(days=10)},
        {"id": "v2", "tenant_id": "t1", "customer_id": "marie", "branch_id": "pal", "points_awarded": 0,
         "stamps_awarded": 2, "paper_stamps": 3, "persons": 2, "amount_paid": 0.0, "visit_time": ago(days=5)},
        {"id": "v3", "tenant_id": "t1", "customer_id": "marie", "points_awarded": None,
         "visit_time": ago(days=1)},                                       # old row: no stamps field, no branch
        {"id": "vx", "tenant_id": "t1", "customer_id": "paul", "branch_id": "pal", "points_awarded": 10,
         "amount_paid": 99.0, "visit_time": ago(days=2)},
        {"id": "vy", "tenant_id": "t2", "customer_id": "marie", "points_awarded": 7,
         "amount_paid": 55.0, "visit_time": ago(days=3)},                  # another business, same id
    ])
    db.visits_cancelled.insert_one({"id": "vc", "tenant_id": "t1", "customer_id": "marie", "visit_time": ago(days=4),
                                    "cancelled_at": ago(days=4)})
    db.rewards_redeemed.insert_many([
        {"id": "r1", "tenant_id": "t1", "customer_id": "marie", "customer_name": "Marie Dupont",
         "reward_name": "Coupe homme", "branch_id": "pal", "redeemed_at": ago(days=4), "stamps_spent": 10,
         "staff_email": "staff@x.fr", "notes": "secret"},
        {"id": "r2", "tenant_id": "t1", "customer_id": "marie", "reward_name": "Reward", "redeemed_at": ago(days=8)},
        {"id": "rx", "tenant_id": "t1", "customer_id": "paul", "reward_name": "Autre", "redeemed_at": ago(days=3)},
    ])
    db.referral_redemptions.insert_many([
        {"tenant_id": "t1", "referrer_customer_id": "marie", "referee_customer_id": "lucas",
         "referrer_pending": False, "settled_at": ago(days=6), "created_at": ago(days=9),
         "referrer_points": 0, "referrer_given": {"points": 0, "stamps": 2, "offers": 0, "offer_text": ""},
         "referee_given": {"points": 50, "stamps": 0, "offers": 0, "offer_text": ""}},
        {"tenant_id": "t1", "referrer_customer_id": "sofia", "referee_customer_id": "marie",
         "referrer_pending": False, "settled_at": ago(days=9), "created_at": ago(days=12),
         "referee_points": 30, "referrer_points": 30},
        {"tenant_id": "t1", "referrer_customer_id": "marie", "referee_customer_id": "noah",
         "referrer_pending": True, "created_at": ago(days=2)},
    ])

    def act(bc=BC, headers=OWN, **params):
        return http("GET", f"/api/card/{bc}/activity", headers=headers, params=params)

    print("1. Who may read the history")
    check("no key, no login → 403", act(headers={}).status_code == 403)
    check("a wrong key → 403", act(headers={"X-Card-Key": "nope"}).status_code == 403)
    check("another card's key → 403", act(headers={"X-Card-Key": KEY_PAL}).status_code == 403)
    check("unknown card → 404", act(bc="FT-NOPE0000").status_code == 404)
    check("the key in ?k= works", http("GET", f"/api/card/{BC}/activity", params={"k": KEY}).status_code == 200)
    check("the shop's owner login → 200", act(headers=login("business_owner", "t1")).status_code == 200)
    check("another business's owner → 403", act(headers=login("business_owner", "t2")).status_code == 403)
    check("card number in lower case still finds the card", act(bc=BC.lower()).status_code == 200)

    print("2. The feed")
    r = act()
    body = r.json()
    items = body["items"]
    kinds = [i["kind"] for i in items]
    check(f"200 with items + next ({r.status_code}, {kinds})", r.status_code == 200 and set(body) == {"items", "next"})
    check("visits, rewards and validated referrals, newest first",
          kinds == ["visit", "reward", "visit", "referral", "reward", "referral", "visit"])
    ats = [i["at"] for i in items]
    check("sorted by at desc", ats == sorted(ats, reverse=True))
    check("every at is ISO UTC with Z", all(a.endswith("Z") and "T" in a for a in ats))
    check("nothing more → next is null", body["next"] is None)
    v3, v2, v1 = [i for i in items if i["kind"] == "visit"]
    check(f"a visit: points 0 when none, stamps on a tampons card ({v1})",
          v1 == {"kind": "visit", "at": v1["at"], "points": 0, "stamps": 1, "amount": 18.5, "store": "LIBERTÉ"})
    check(f"paper stamps count with the visit's ({v2['stamps']}), its store by name ({v2['store']})",
          v2["stamps"] == 5 and v2["store"] == "PALISSY")
    check("a 0 € visit says 0.0, not null", v2["amount"] == 0.0)
    check(f"an old row: 1 tampon, no amount, the main store ({v3})",
          v3["stamps"] == 1 and v3["amount"] is None and v3["store"] == "LIBERTÉ" and v3["points"] == 0)
    rw = [i for i in items if i["kind"] == "reward"]
    check(f"a reward: its name and store ({rw[0]})",
          rw[0] == {"kind": "reward", "at": rw[0]["at"], "title": "Coupe homme", "store": "PALISSY"})
    check(f"the placeholder « Reward » → the card's reward ({rw[1]['title']})",
          rw[1]["title"] == "Une coupe offerte" and rw[1]["store"] == "LIBERTÉ")
    refs = [i for i in items if i["kind"] == "referral"]
    parrain = next(i for i in refs if i["role"] == "parrain")
    filleul = next(i for i in refs if i["role"] == "filleul")
    check(f"as parrain: the friend's first name, what she got ({parrain})",
          parrain["friend"] == "Lucas" and parrain["stamps"] == 2 and parrain["points"] is None)
    check(f"as filleule: the parraine's first name ({filleul})",
          filleul["friend"] == "Sofia" and filleul["points"] == 30 and filleul["stamps"] is None)
    check("a referral not validated yet is not shown", not any(i.get("friend") == "Noah" for i in items))
    raw = r.text
    for leak in ("Bernard", "Leroy", "0611111111", "@x.fr", "lucas", "sofia", "secret", "staff", "99.0", "55.0",
                 "customer_id", "referee_customer_id", "_id", "\"id\""):
        check(f"no leak of {leak!r}", leak not in raw)
    check("a cancelled visit never shows", len([i for i in items if i["kind"] == "visit"]) == 3)
    check("another business's visit of the same id never shows", not any(i.get("points") == 7 for i in items))

    print("3. Paging")
    p1 = act(limit=3).json()
    check(f"limit=3 → 3 items, next = the 3rd's at ({p1['next']})",
          len(p1["items"]) == 3 and p1["next"] == p1["items"][-1]["at"])
    p2 = act(limit=3, before=p1["next"]).json()
    p3 = act(limit=3, before=p2["next"]).json()
    joined = p1["items"] + p2["items"] + p3["items"]
    check(f"pages join with no gap and no repeat ({len(joined)})", joined == items)
    check("the last page has next null", p3["next"] is None and len(p3["items"]) == 1)
    check("limit=1", len(act(limit=1).json()["items"]) == 1)
    check("limit=0 → clamped to 1", act(limit=0).status_code == 200 and len(act(limit=0).json()["items"]) == 1)
    check("limit=-4 → clamped to 1", len(act(limit=-4).json()["items"]) == 1)
    check("limit=5000 → clamped to 100 (all 7 here)", len(act(limit=5000).json()["items"]) == 7)
    check("limit=abc → 422", act(limit="abc").status_code == 422)
    check("before=hier → 422", act(before="hier").status_code == 422)
    check("before={'$gt':1} → 422", act(before='{"$gt": 1}').status_code == 422)
    check("before far in the past → empty", act(before="2000-01-01T00:00:00Z").json() == {"items": [], "next": None})
    # an exactly-limit page: next only when more exist
    check("limit=7 (exactly all) → next null", act(limit=7).json()["next"] is None)
    check("limit=6 → next set", act(limit=6).json()["next"] is not None)

    print("4. Time zones / DST (Paris)")
    db.customers.insert_one({"id": "dst", "tenant_id": "t1", "barcode_id": "FT-DST00001", "name": "Dst",
                             "visits": 2, "branch_id": "main"})
    # 2026-10-25: Paris goes 03:00 CEST → 02:00 CET (01:00 UTC). Both 02:30 local times exist.
    db.visits.insert_many([
        {"id": "d1", "tenant_id": "t1", "customer_id": "dst", "visit_time": datetime(2026, 10, 25, 0, 30)},  # 02:30 CEST
        {"id": "d2", "tenant_id": "t1", "customer_id": "dst", "visit_time": datetime(2026, 10, 25, 1, 30)},  # 02:30 CET
    ])
    kd = {"X-Card-Key": CO.key_for("FT-DST00001")}
    d = act(bc="FT-DST00001", headers=kd).json()["items"]
    check(f"two visits at « 02:30 » Paris that night, ordered by the real instant ({[i['at'] for i in d]})",
          [i["at"] for i in d] == ["2026-10-25T01:30:00Z", "2026-10-25T00:30:00Z"])
    d = act(bc="FT-DST00001", headers=kd, before="2026-10-25T02:30:00+01:00").json()["items"]
    check("before in CET (+01:00) = 01:30 UTC → only the CEST one", [i["at"] for i in d] == ["2026-10-25T00:30:00Z"])
    d = act(bc="FT-DST00001", headers=kd, before="2026-10-25T02:31:00+02:00").json()["items"]
    check("before in CEST (+02:00) = 00:31 UTC → the CEST one", [i["at"] for i in d] == ["2026-10-25T00:30:00Z"])

    print("5. Multi-store: a points card (Palissy)")
    pi = act(bc=BC_PAL, headers={"X-Card-Key": KEY_PAL}).json()["items"]
    check(f"Paul sees only his own visit and reward ({pi})", [i["kind"] for i in pi] == ["visit", "reward"]
          and pi[0]["points"] == 10 and pi[0]["amount"] == 99.0 and pi[1]["title"] == "Autre")
    check("a points card: stamps null", pi[0]["stamps"] is None)
    bad_addr = http("PUT", "/api/owner/etablissement", headers={**login("business_owner", "t1"), "X-FidClic-Store": "pal"},
                    json={"business": {"socials": {"instagram": "@nevermind"}}, "address": {"postal_code": "ABC"}})
    check(f"a save refused for another field writes no network ({bad_addr.status_code})", bad_addr.status_code == 400
          and "nevermind" not in str(db["card_templates"]._real.find_one({"tenant_id": "t1", "store_id": "pal"})))
    check("Zoé (other business) sees nothing of t1",
          act(bc=BC_T2, headers={"X-Card-Key": CO.key_for(BC_T2)}).json()["items"] == [])

    print("6. GET /api/card: first name, socials, hero photo")
    g = http("GET", f"/api/card/{BC}", headers=OWN).json()
    check(f"customer.first_name ({g['customer'].get('first_name')!r})", g["customer"].get("first_name") == "Marie")
    check(f"card.socials: bad Facebook dropped, order kept ({g['card'].get('socials')})",
          g["card"].get("socials") == [{"network": "instagram", "url": "https://www.instagram.com/royaltrim"},
                                       {"network": "tiktok", "url": "https://www.tiktok.com/@royaltrim"},
                                       {"network": "snapchat", "url": "https://www.snapchat.com/add/royaltrim"}])
    check(f"main store: the banner ({g['card'].get('hero_photo_url')})", g["card"].get("hero_photo_url") == f"/api/media/{A}")
    gp = http("GET", f"/api/card/{BC_PAL}", headers={"X-Card-Key": KEY_PAL}).json()
    check(f"Palissy: its own « Ajuster » poster ({gp['card'].get('hero_photo_url')})",
          gp["card"].get("hero_photo_url") == f"/api/media/{B}")
    check("Palissy: its card has no socials → []", gp["card"].get("socials") == [])
    check("Paul's first name", gp["customer"].get("first_name") == "Paul")
    db.campaigns.insert_one({"id": "camp1", "tenant_id": "t1", "status": "sent", "wallet_offer": True,
                             "wallet_photo": True, "recipient_ids": ["paul"], "name": "Promo de Noël",
                             "content": "-20 %", "image_url": f"/api/media/{C}", "sent_at": ago(days=1)})
    gp = http("GET", f"/api/card/{BC_PAL}", headers={"X-Card-Key": KEY_PAL}).json()
    check(f"a live Wallet campaign with its photo wins ({gp['card'].get('hero_photo_url')})",
          gp["card"].get("hero_photo_url") == f"/api/media/{C}")
    g = http("GET", f"/api/card/{BC}", headers=OWN).json()
    check("…only for its recipients (Marie keeps the banner)", g["card"].get("hero_photo_url") == f"/api/media/{A}")
    db.customers.update_one({"id": "paul"}, {"$set": {"paused_at": now}})
    gp = http("GET", f"/api/card/{BC_PAL}", headers={"X-Card-Key": KEY_PAL}).json()
    check("a paused client gets no campaign photo (the poster)", gp["card"].get("hero_photo_url") == f"/api/media/{B}")
    db.customers.update_one({"id": "paul"}, {"$unset": {"paused_at": ""}})
    m = http("GET", f"/api/media/{A}")
    check(f"/api/media/<id> needs no key (404 here only because the test has no picture: {m.status_code})",
          m.status_code in (200, 404, 307) and m.status_code != 403)
    real_tpl.update_one({"tenant_id": "t2", "store_id": None}, {"$set": {"hero_mode": "brand"}})
    gz = http("GET", f"/api/card/{BC_T2}", headers={"X-Card-Key": CO.key_for(BC_T2)}).json()
    check("no photo at all → null (never a gradient)", gz["card"].get("hero_photo_url") is None)
    check("another business's card shows none of t1's socials", gz["card"].get("socials") == [])

    print("7. The owner saves the 4 networks (Paramètres › Établissement)")
    OWNER = login("business_owner", "t1")
    pal_hdr = {**OWNER, "X-FidClic-Store": "pal"}
    e = http("GET", "/api/owner/etablissement", headers=pal_hdr).json()
    check(f"the page reads Palissy's (empty) networks ({e['business'].get('socials')})",
          e["business"].get("socials") == {"instagram": "", "facebook": "", "tiktok": "", "snapchat": ""})
    s = http("PUT", "/api/owner/etablissement", headers=pal_hdr,
             json={"business": {"socials": {"instagram": "@palissy", "facebook": "https://fb.com/palissy37",
                                            "tiktok": "@palissy.tours", "snapchat": "palissy37"}}})
    check(f"saved ({s.status_code})", s.status_code == 200)
    check("the answer shows them", s.json()["business"].get("socials", {}).get("tiktok") == "@palissy.tours")
    gp = http("GET", f"/api/card/{BC_PAL}", headers={"X-Card-Key": KEY_PAL}).json()
    check(f"Palissy's card now lists all 4 ({[x['network'] for x in gp['card'].get('socials') or []]})",
          [x["url"] for x in gp["card"].get("socials") or []] == [
              "https://www.instagram.com/palissy", "https://www.facebook.com/palissy37",
              "https://www.tiktok.com/@palissy.tours", "https://www.snapchat.com/add/palissy37"])
    g = http("GET", f"/api/card/{BC}", headers=OWN).json()
    check("the main store's card keeps its own", [x["network"] for x in g["card"]["socials"]] == ["instagram", "tiktok", "snapchat"])
    bad = http("PUT", "/api/owner/etablissement", headers=pal_hdr,
               json={"business": {"socials": {"tiktok": "javascript:alert(1)"}}})
    check(f"an invalid link is refused with a French message ({bad.status_code}: {bad.json().get('detail')})",
          bad.status_code == 400 and "TikTok" in str(bad.json().get("detail")))
    check("…and nothing changed", http("GET", "/api/owner/etablissement", headers=pal_hdr).json()
          ["business"]["socials"]["tiktok"] == "@palissy.tours")
    clr = http("PUT", "/api/owner/etablissement", headers=pal_hdr, json={"business": {"socials": {"snapchat": ""}}})
    e = http("GET", "/api/owner/etablissement", headers=pal_hdr).json()["business"]["socials"]
    check(f"one network emptied, the others kept ({clr.status_code}, {e})",
          clr.status_code == 200 and e["snapchat"] == "" and e["instagram"] == "@palissy")
    long_ = http("PUT", "/api/owner/etablissement", headers=pal_hdr,
                 json={"business": {"socials": {"instagram": "a" * 5000}}})
    check(f"a 5 000-char value → 422/400 ({long_.status_code})", long_.status_code in (400, 422))
    mgr = http("PUT", "/api/owner/etablissement", headers={**login("manager", "t1"), "X-FidClic-Store": "pal"},
               json={"business": {"socials": {"instagram": "@pirate"}}})
    check(f"a manager cannot change them ({mgr.status_code})", mgr.status_code == 403)
    other = http("PUT", "/api/owner/etablissement", headers=login("business_owner", "t2"),
                 json={"business": {"socials": {"instagram": "@gs"}}})
    check("another business's owner writes only its own card", other.status_code == 200 and
          real_tpl.find_one({"tenant_id": "t1", "store_id": "pal"})["details"]["instagram"] == "@palissy")
    a = http("PUT", "/api/owner/etablissement", headers=pal_hdr, json={"business": {"description": "Barbier."}})
    check("a save without socials leaves them as they are", a.status_code == 200 and
          real_tpl.find_one({"tenant_id": "t1", "store_id": "pal"})["details"]["instagram"] == "@palissy")

    print("8. The card details endpoint keeps TikTok / Snapchat")
    d = http("POST", "/api/owner/card-template/details", headers=OWNER,
             json={"about": "Barbier", "instagram": "@rt", "tiktok": "@rt.tiktok", "snapchat": "rtsnap"})
    check(f"saved ({d.status_code})", d.status_code == 200)
    saved = real_tpl.find_one({"tenant_id": "t1", "store_id": None})["details"]
    check(f"tiktok + snapchat persisted ({saved.get('tiktok')}, {saved.get('snapchat')})",
          saved.get("tiktok") == "@rt.tiktok" and saved.get("snapchat") == "rtsnap")
    check("missing ones default to ''", saved.get("facebook") == "")
    g = http("GET", f"/api/card/{BC}", headers=OWN).json()
    check("and the card lists them", [x["network"] for x in g["card"]["socials"]] == ["instagram", "tiktok", "snapchat"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
