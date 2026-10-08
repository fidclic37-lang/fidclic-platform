"""
Where a customer came from, and parrainage rewards (user, 2026-10-08):
  • one link per channel — /join/<slug>/insta, /wa… — counted exactly; an
    unknown word is « Non renseigné », never « QR code en magasin »;
  • a friend's card is « Parrainage », never « QR code en magasin »;
  • Clients filters by source, Analyses shows each source on its own and
    opens its clients, the Lien d'inscription page counts each channel;
  • parrainage pays once, at every visit, or a first amount then another.

Run: cd api && /usr/local/bin/python3 tests/test_sources_parrainage.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-sources")
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
    from services import sources as SRC

    db = server.db
    R._db = db
    now = dt.datetime.now(dt.timezone.utc)

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "petit-cafe", "name": "Le Petit Café", "is_active": True,
                           "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    tok = auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + tok}
    db.referral_config.insert_one({"tenant_id": "t1", "enabled": True, "referrer_reward_points": 50,
                                   "referee_reward_points": 25, "minimum_visits_to_earn": 1})
    db.customers.insert_one({"id": "c-marie", "tenant_id": "t1", "barcode_id": "FT-MARIE01", "name": "Marie Dupont",
                             "visits": 5, "points": 100, "phone": "0611111111", "created_at": now,
                             "acquisition_source": "qr_store"})

    print("1. Les mots des liens")
    check("wa / whatsapp → WhatsApp", SRC.normalize("wa") == "whatsapp" and SRC.normalize("WhatsApp") == "whatsapp")
    check("insta, fb, site, mail, google, qr", [SRC.normalize(x) for x in ("insta", "fb", "site", "mail", "google", "qr")]
          == ["instagram", "facebook", "website", "email", "google", "qr_store"])
    check("an unknown word is no source (never « QR »)", SRC.normalize("snapchat-bio") is None)
    check("every channel word reads back as its own source",
          all(SRC.normalize(w) == k for k, w in SRC.CHANNEL_WORDS.items()))

    n = [0]

    def join(source=None, parrain=None, chain=None):
        n[0] += 1
        body = {"name": f"Client {n[0]}", "phone": f"07{n[0]:08d}", "postal_code": "06000",
                "birthday": "01-02", "consent": True}
        if source is not None:
            body["acquisition_source"] = source
        if parrain:
            body["parrain_barcode"] = parrain
        if chain:
            body["touchpoints_history"] = chain
        r = http("POST", "/api/join/petit-cafe", json=body)
        assert r.status_code == 200, r.text
        return db.customers.find_one({"barcode_id": r.json()["barcode_id"]})

    print("\n2. L'inscription compte la bonne source")
    check("the WhatsApp link → WhatsApp (it used to read « QR en magasin »)", join("wa")["acquisition_source"] == "whatsapp")
    check("the Instagram link → Instagram", join("insta")["acquisition_source"] == "instagram")
    check("the shop's QR → QR code en magasin", join("qr")["acquisition_source"] == "qr_store")
    check("an e-mail link → E-mail", join("mail")["acquisition_source"] == "email")
    check("an unknown word → Non renseigné, not QR", join("myspace")["acquisition_source"] is None)
    check("no channel and no answer → Non renseigné", join("")["acquisition_source"] is None)
    friend = join("qr", parrain="FT-MARIE01")
    check("a friend's card → Parrainage, even with a QR tag", friend["acquisition_source"] == "referral")
    check("…and the referral is recorded", db.referral_redemptions.find_one({"referee_customer_id": friend["id"]}))
    check("an unknown parrain card does not make it Parrainage",
          join("insta", parrain="FT-NOBODY")["acquisition_source"] == "instagram")
    multi = join("qr", chain=[{"source": "insta", "ts": "2026-10-01T10:00:00Z"}, {"source": "qr", "ts": "2026-10-08T10:00:00Z"}])
    check("Instagram first, then the shop's QR: first and last touch kept",
          multi.get("first_touch_source") == "instagram" and multi.get("last_touch_source") == "qr_store"
          and multi["acquisition_source"] == "qr_store")

    print("\n3. Clients : le filtre Source")
    ov = http("GET", "/api/owner/clients/overview", headers=H).json()
    keys = {s["key"]: s["count"] for s in ov.get("sources", [])}
    check("the filter lists each source with its count",
          keys.get("whatsapp") == 1 and keys.get("referral") == 1 and keys.get("none") == 2)
    lst = http("GET", "/api/owner/clients/list?source=whatsapp", headers=H).json()
    check("?source=whatsapp → only the WhatsApp clients", lst["total"] == 1 and lst["rows"][0]["source"] == "whatsapp"
          and lst["rows"][0]["source_label"] == "WhatsApp")
    ids = http("GET", "/api/owner/clients/ids?source=referral", headers=H).json()
    check("« Contacter » reaches the same clients (ids)", ids["ids"] == [friend["id"]])
    check("« Non renseigné » is a filter too", http("GET", "/api/owner/clients/list?source=none", headers=H).json()["total"] == 2)
    csv = http("GET", "/api/owner/clients/export?source=instagram", headers=H).content.decode("utf-8-sig")
    check("the export has a Source column, and only the filtered clients",
          "Source" in csv.splitlines()[0] and csv.count("Instagram") == 2)

    print("\n4. Analyses : chaque source à part, et cliquable")
    r = http("GET", "/api/owner/analyses?tab=acquisition", headers=H)
    data = r.json() if r.status_code == 200 else {}
    tab = data.get("data") or data
    srcs = {s.get("key"): s for s in (tab.get("sources") or [])}
    check(f"Instagram and WhatsApp are separate bars, each with its key ({r.status_code})",
          "instagram" in srcs and "whatsapp" in srcs and srcs["whatsapp"]["name"] == "WhatsApp")
    check("Parrainage is its own bar, not « QR en magasin »", "referral" in srcs and srcs["referral"]["count"] == 1)

    print("\n5. Lien d'inscription : un lien par canal")
    jl = http("GET", "/api/owner/join-link", headers=H).json()
    ch = {c["key"]: c for c in jl.get("channels", [])}
    check("a link word for each channel", ch["whatsapp"]["word"] == "wa" and ch["instagram"]["word"] == "insta"
          and ch["qr_store"]["word"] == "qr")
    check("and how many each brought", ch["whatsapp"]["total"] == 1 and ch["instagram"]["total"] == 2)

    print("\n6. Parrainage : quand créditer")

    def filleul(cid):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "barcode_id": f"FT-{cid.upper()}", "name": cid,
                                 "visits": 0, "points": 0, "created_at": now})
        R.record("t1", "FT-MARIE01", db.customers.find_one({"id": cid}))

    def visit(cid, n):
        db.customers.update_one({"id": cid}, {"$set": {"visits": n}})
        return R.settle("t1", cid)

    def pts(cid):
        return db.customers.find_one({"id": cid})["points"]

    # once (default)
    filleul("f-once")
    m0 = pts("c-marie")
    visit("f-once", 1); visit("f-once", 2); visit("f-once", 3)
    check("« Une seule fois »: paid at the 1st visit only", pts("f-once") == 25 and pts("c-marie") == m0 + 50)

    # every
    db.referral_config.update_one({"tenant_id": "t1"}, {"$set": {"reward_mode": "every",
                                                                 "referrer_reward_points": 10, "referee_reward_points": 5}})
    filleul("f-every")
    m0 = pts("c-marie")
    visit("f-every", 1)
    check("« À chaque visite »: the 1st visit pays what was promised", pts("f-every") == 5 and pts("c-marie") == m0 + 10)
    visit("f-every", 2); visit("f-every", 3)
    check("…and every later visit pays again", pts("f-every") == 15 and pts("c-marie") == m0 + 30)
    check("the same visit is never paid twice (two tills)", visit("f-every", 3) is None and pts("f-every") == 15)
    row = db.referral_redemptions.find_one({"referee_customer_id": "f-every"})
    check("the row keeps the totals and the visit count", row["rewarded_visits"] == 3 and row["referee_points"] == 15)

    # first then
    db.referral_config.update_one({"tenant_id": "t1"}, {"$set": {"reward_mode": "first_then", "referrer_reward_points": 40,
                                                                 "referee_reward_points": 20, "referrer_reward_points_next": 4,
                                                                 "referee_reward_points_next": 2, "minimum_visits_to_earn": 2}})
    filleul("f-first")
    m0 = pts("c-marie")
    check("nothing before the visit the shop asked for (2nd)", visit("f-first", 1) is None and pts("f-first") == 0)
    visit("f-first", 2)
    check("« Bonus puis récurrent »: the bonus at the 2nd visit", pts("f-first") == 20 and pts("c-marie") == m0 + 40)
    visit("f-first", 3); visit("f-first", 4)
    check("…then the smaller amount at each later visit", pts("f-first") == 24 and pts("c-marie") == m0 + 48)

    # back to once: an old referral stops paying
    db.referral_config.update_one({"tenant_id": "t1"}, {"$set": {"reward_mode": "once"}})
    check("switching back to « Une seule fois » stops later payments", visit("f-every", 4) is None and pts("f-every") == 15)

    r = http("PUT", "/api/owner/referrals/config", headers=H, json={"enabled": True, "reward_mode": "sometimes"})
    check(f"an unknown mode is refused ({r.status_code})", r.status_code == 400)
    r = http("PUT", "/api/owner/referrals/config", headers=H, json={
        "enabled": True, "reward_mode": "first_then", "referrer_reward_points": 30, "referee_reward_points": 10,
        "referrer_reward_points_next": 3, "referee_reward_points_next": 1, "minimum_visits_to_earn": 1})
    cfg = db.referral_config.find_one({"tenant_id": "t1"})
    check(f"the settings save the mode and the next amounts ({r.status_code})",
          r.status_code == 200 and cfg["reward_mode"] == "first_then" and cfg["referrer_reward_points_next"] == 3)
    inv = R.inviter("FT-MARIE01")
    check("the signup form is told when points come", inv["minimum_visits"] == 1 and inv["reward_mode"] == "first_then")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
