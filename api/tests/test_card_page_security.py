"""
« Ma carte en ligne » — the six findings of the local pentest / load run
(2026-11-25), through the real HTTP endpoints on the mongomock server:

  1. PUT/GET /api/owner/etablissement: the establishment the menu sends
     (X-FidClic-Store) must be one the account covers — else 403, nothing written.
  2. A shop login covering store A sees a client's store-B visit, never its
     euros (activity `amount: null`, card `customer.total_amount_paid: null`
     when the client's home store is not covered).
  3. `before` out of the datetime range (0001-01-01+14:00, 9999-12-31-14:00) → 422.
  4. Stable paging: (at desc, kind, id) with an opaque `next` cursor; identical
     timestamps across a page boundary are never skipped nor repeated; a plain
     ISO `before` still works; a visit whose time is stored as text is kept.
  5. The card page's campaign photo: one bounded, indexed query — same photo
     as the Wallet pass.
  6. Failed card lookups (404 / 403) are counted per client IP in Mongo (TTL):
     after 30 in 10 minutes → 429, successes never count.

Run: cd api && python3 tests/test_card_page_security.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-page-security")
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
    _ip_seq = [0]

    def fresh_ip():
        """Every request gets its own client IP unless a test says otherwise:
        the failed-lookup counter (finding 6) must not leak between sections."""
        _ip_seq[0] += 1
        return f"198.51.100.{_ip_seq[0] % 250 + 1}" if _ip_seq[0] < 250 else f"198.51.{_ip_seq[0] // 250}.{_ip_seq[0] % 250 + 1}"

    def http(method, url, headers=None, ip=None, **kw):
        h = dict(headers or {})
        if "X-Forwarded-For" not in h:
            h["X-Forwarded-For"] = ip or fresh_ip()

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app, raise_app_exceptions=False), base_url="http://test") as ac:
                return await ac.request(method, url, headers=h, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def login(email, role, tenant, **user):
        db.users.update_one({"email": email}, {"$set": {"email": email, "role": role, "tenant_id": tenant,
                                                        "active": True, **user}}, upsert=True)
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tenant})}

    now = datetime.now(timezone.utc).replace(microsecond=0)
    ago = lambda **kw: now - timedelta(**kw)   # noqa: E731

    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "is_active": True, "plan": "vip",
                           "subscription_status": "active",
                           "branches": [{"id": "main", "name": "LIBERTÉ", "is_main": True},
                                        {"id": "pal", "name": "PALISSY"}]})
    db.tenants.insert_one({"id": "t2", "slug": "gs", "name": "GREEN SMOKE", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    real_tpl = db["card_templates"]._real
    real_tpl.insert_one({"tenant_id": "t1", "store_id": None, "programme": "stamps", "reward_threshold_stamps": 10,
                         "reward_description": "Une coupe offerte", "details": {"instagram": "@royaltrim"}})
    real_tpl.insert_one({"tenant_id": "t1", "store_id": "pal", "programme": "points_visit", "points_per_visit": 10,
                         "reward_description": "Un shampoing offert", "details": {"instagram": "@palissy"},
                         "poster_image_url": f"/api/media/{'b' * 32}"})
    real_tpl.insert_one({"tenant_id": "t2", "store_id": None, "programme": "stamps"})

    def cust(cid, tid, name, branch=None, **kw):
        bc = f"FT-{cid.upper()}"
        db.customers.insert_one({"id": cid, "tenant_id": tid, "barcode_id": bc, "name": name, "email": f"{cid}@x.fr",
                                 "phone": "0611111111", "visits": 3, "points": 0, "branch_id": branch, **kw})
        return bc

    OWNER = login("owner@rt.fr", "business_owner", "t1")
    ADM_MAIN = login("adm-main@rt.fr", "administrateur", "t1", branch_ids=["main"])
    ADM_PAL = login("adm-pal@rt.fr", "administrateur", "t1", branch_ids=["pal"])
    ADM_ALL = login("adm-all@rt.fr", "administrateur", "t1")             # made before stores were assigned: all
    MGR_MAIN = login("mgr-main@rt.fr", "manager", "t1", branch_ids=["main"])
    STAFF_PAL = login("staff-pal@rt.fr", "staff", "t1", branch_ids=["pal"])
    MGR_BOTH = login("mgr-both@rt.fr", "manager", "t1", branch_ids=["main", "pal"])
    SUPER = login("root@fidclic.fr", "super_admin", None)

    # ------------------------------------------------------------------
    print("1. Paramètres › Établissement: the menu's store must be one the account covers")

    def tenant_branch(sid):
        return next(b for b in db.tenants.find_one({"id": "t1"})["branches"] if b["id"] == sid)

    def pal_social():
        return (real_tpl.find_one({"tenant_id": "t1", "store_id": "pal"}) or {}).get("details", {}).get("instagram")

    pal = {"X-FidClic-Store": "pal"}
    versions = db.settings_versions.count_documents({})
    r = http("PUT", "/api/owner/etablissement", headers={**ADM_MAIN, **pal},
             json={"business": {"name": "PIRATE", "phone": "0700000000", "socials": {"instagram": "@pirate"}}})
    check(f"administrateur of main → store pal → 403 ({r.status_code})", r.status_code == 403)
    check(f"…with a clear French message ({r.json().get('detail')!r})",
          "établissement" in str(r.json().get("detail")).lower())
    check("…pal's name unchanged", tenant_branch("pal").get("name") == "PALISSY")
    check("…pal's phone unchanged", not tenant_branch("pal").get("phone"))
    check("…pal's networks unchanged", pal_social() == "@palissy")
    check("…the account's own name unchanged", db.tenants.find_one({"id": "t1"})["name"] == "ROYAL TRIM")
    check("…and no « Réinitialiser » version noted", db.settings_versions.count_documents({}) == versions)
    r = http("PUT", "/api/owner/etablissement", headers={**ADM_MAIN, **pal}, json={"legal": {"legal_name": "Pirate SAS"}})
    check(f"…any field under that header is refused (legal: {r.status_code})", r.status_code == 403
          and db.tenants.find_one({"id": "t1"}).get("legal_name") != "Pirate SAS")
    r = http("PUT", "/api/owner/etablissement", headers={**ADM_MAIN, "X-FidClic-Store": "  pal "},
             json={"business": {"name": "PIRATE"}})
    check(f"…padding the header changes nothing ({r.status_code})", r.status_code == 403)
    r = http("GET", "/api/owner/etablissement", headers={**ADM_MAIN, **pal})
    check(f"GET: administrateur of main → store pal → 403 ({r.status_code})", r.status_code == 403)
    r = http("GET", "/api/owner/etablissement", headers={**MGR_MAIN, **pal})
    check(f"GET: manager of main → store pal → 403 ({r.status_code})", r.status_code == 403)
    r = http("GET", "/api/owner/etablissement", headers={**MGR_MAIN, "X-FidClic-Store": "main"})
    check(f"GET: manager of main → main → 200 ({r.status_code})", r.status_code == 200)
    r = http("PUT", "/api/owner/etablissement", headers={**ADM_PAL, **pal}, json={"business": {"name": "PALISSY 2"}})
    check(f"administrateur of pal → pal → 200 ({r.status_code})", r.status_code == 200
          and tenant_branch("pal")["name"] == "PALISSY 2")
    r = http("PUT", "/api/owner/etablissement", headers={**ADM_ALL, **pal}, json={"business": {"name": "PALISSY 3"}})
    check(f"administrateur covering every store → pal → 200 ({r.status_code})", r.status_code == 200
          and tenant_branch("pal")["name"] == "PALISSY 3")
    r = http("PUT", "/api/owner/etablissement", headers={**OWNER, **pal}, json={"business": {"name": "PALISSY"}})
    check(f"owner → pal → 200 ({r.status_code})", r.status_code == 200 and tenant_branch("pal")["name"] == "PALISSY")
    r = http("PUT", "/api/owner/etablissement", headers={**OWNER, "X-FidClic-Store": "main"},
             json={"business": {"name": "LIBERTÉ"}})
    check(f"owner → main → 200 ({r.status_code})", r.status_code == 200)
    r = http("PUT", "/api/owner/etablissement", headers={**ADM_MAIN, "X-FidClic-Store": "main"},
             json={"business": {"description": "Barbier."}})
    check(f"administrateur of main → main → 200 ({r.status_code})", r.status_code == 200)
    r = http("PUT", "/api/owner/etablissement", headers=ADM_MAIN, json={"business": {"description": "Barbier !"}})
    check(f"no header → the account's own fields, as before ({r.status_code})", r.status_code == 200
          and db.tenants.find_one({"id": "t1"}).get("description") == "Barbier !")
    r = http("GET", "/api/owner/etablissement", headers={**ADM_MAIN, "X-FidClic-Store": "all"})
    check(f"header « all » = no header ({r.status_code})", r.status_code == 200)
    r = http("GET", "/api/owner/etablissement", headers={**ADM_MAIN, "X-FidClic-Store": "nope"})
    check(f"an unknown store = no header ({r.status_code})", r.status_code == 200)
    r = http("PUT", "/api/owner/etablissement/stores/pal", headers=ADM_MAIN, json={"phone": "0700000000"})
    check(f"stores sub-route: still refused for a store not covered ({r.status_code})", r.status_code == 403)
    r = http("GET", "/api/owner/etablissement", headers={**login("owner@gs.fr", "business_owner", "t2"), **pal})
    check(f"another business's owner naming t1's store reads only its own ({r.status_code})",
          r.status_code == 200 and r.json()["business"]["name"] == "GREEN SMOKE")

    # ------------------------------------------------------------------
    print("2. Another store's euros stay hidden from a login that does not cover it")
    BC = cust("marie", "t1", "Marie Dupont", "main", total_amount_paid=158.5)
    BC_PAL = cust("paul", "t1", "Paul Martin", "pal", total_amount_paid=99.0)
    BC_OLD = cust("old", "t1", "Old Client", None, total_amount_paid=12.0)      # signed up before stores
    db.visits.insert_many([
        {"id": "m1", "tenant_id": "t1", "customer_id": "marie", "branch_id": "main", "amount_paid": 18.5,
         "stamps_awarded": 1, "points_awarded": 0, "visit_time": ago(days=3)},
        {"id": "m2", "tenant_id": "t1", "customer_id": "marie", "branch_id": "pal", "amount_paid": 140.0,
         "stamps_awarded": 2, "points_awarded": 0, "visit_time": ago(days=2)},
        {"id": "m3", "tenant_id": "t1", "customer_id": "marie", "amount_paid": 7.0,             # untagged = main
         "stamps_awarded": 1, "points_awarded": 0, "visit_time": ago(days=1)},
    ])
    KEY = CO.key_for(BC)

    def feed(headers, bc=BC):
        r = http("GET", f"/api/card/{bc}/activity", headers=headers)
        return r.status_code, {i["at"]: i for i in r.json().get("items", [])} if r.status_code == 200 else {}

    at = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")   # noqa: E731
    s, f = feed(MGR_MAIN)
    check(f"manager of main reads Marie's feed ({s})", s == 200 and len(f) == 3)
    check(f"…her main visit with its amount ({f.get(at(ago(days=3)))})", f.get(at(ago(days=3)), {}).get("amount") == 18.5)
    pv = f.get(at(ago(days=2)), {})
    check(f"…her Palissy visit: amount null ({pv})", "amount" in pv and pv["amount"] is None)
    check("…but the visit, its store and tampons are kept", pv.get("kind") == "visit" and pv.get("store") == "PALISSY"
          and pv.get("stamps") == 2 and pv.get("points") == 0)
    check("…an untagged (main) visit keeps its amount", f.get(at(ago(days=1)), {}).get("amount") == 7.0)
    s, f = feed(STAFF_PAL)
    check(f"staff of pal: the pal visit's amount, not main's ({s})", s == 200
          and f[at(ago(days=2))]["amount"] == 140.0 and f[at(ago(days=3))]["amount"] is None
          and f[at(ago(days=1))]["amount"] is None)
    for label, h in (("owner", OWNER), ("administrateur covering all", ADM_ALL), ("manager of both stores", MGR_BOTH),
                     ("super admin", SUPER), ("the customer's own key", {"X-Card-Key": KEY})):
        s, f = feed(h)
        check(f"{label} sees every amount ({s})", s == 200 and sorted(i["amount"] for i in f.values()) == [7.0, 18.5, 140.0])
    raw = http("GET", f"/api/card/{BC}/activity", headers=MGR_MAIN).text
    check("no « 140 » anywhere in the manager's answer", "140" not in raw)

    def total(headers, bc):
        r = http("GET", f"/api/card/{bc}", headers=headers)
        return r.status_code, (r.json().get("customer") or {}).get("total_amount_paid", "missing") if r.status_code == 200 else None

    check(f"card: manager of main, a main client → total shown {total(MGR_MAIN, BC)}", total(MGR_MAIN, BC) == (200, 158.5))
    check(f"card: staff of pal, a main client → total null {total(STAFF_PAL, BC)}", total(STAFF_PAL, BC) == (200, None))
    check(f"card: manager of main, a pal client → total null {total(MGR_MAIN, BC_PAL)}", total(MGR_MAIN, BC_PAL) == (200, None))
    check(f"card: staff of pal, a pal client → total shown {total(STAFF_PAL, BC_PAL)}", total(STAFF_PAL, BC_PAL) == (200, 99.0))
    check(f"card: a client with no home store belongs to main {total(MGR_MAIN, BC_OLD)} {total(STAFF_PAL, BC_OLD)}",
          total(MGR_MAIN, BC_OLD) == (200, 12.0) and total(STAFF_PAL, BC_OLD) == (200, None))
    check("card: owner / super admin / key see the total",
          total(OWNER, BC_PAL) == (200, 99.0) and total(SUPER, BC_PAL) == (200, 99.0)
          and total({"X-Card-Key": CO.key_for(BC_PAL)}, BC_PAL) == (200, 99.0))
    BC_GS = cust("gs1", "t2", "Gs Client", None, total_amount_paid=30.0)
    db.visits.insert_one({"id": "g1", "tenant_id": "t2", "customer_id": "gs1", "amount_paid": 30.0,
                          "visit_time": ago(days=1)})
    STAFF_GS = login("staff@gs.fr", "staff", "t2", branch_ids=["main"])
    s, f = feed(STAFF_GS, BC_GS)
    check(f"a one-shop business: its staff covers everything ({s}, {list(f.values())})",
          s == 200 and [i["amount"] for i in f.values()] == [30.0] and total(STAFF_GS, BC_GS) == (200, 30.0))

    # ------------------------------------------------------------------
    print("3. `before` out of range → 422, never 500")
    OWN = {"X-Card-Key": KEY}
    for v in ("0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00", "0001-01-01T00:00:00+23:59"):
        r = http("GET", f"/api/card/{BC}/activity", headers=OWN, params={"before": v})
        check(f"before={v} → 422 ({r.status_code})", r.status_code == 422)
    r = http("GET", f"/api/card/{BC}/activity", headers=OWN, params={"before": "0001-01-01T00:00:00Z"})
    check(f"the smallest date in UTC → 200, empty ({r.status_code})", r.status_code == 200 and r.json()["items"] == [])
    r = http("GET", f"/api/card/{BC}/activity", headers=OWN, params={"before": "9999-12-31T23:59:59Z"})
    check(f"the largest date in UTC → 200, everything ({r.status_code})", r.status_code == 200 and len(r.json()["items"]) == 3)
    r = http("GET", f"/api/card/{BC}/activity", headers=OWN, params={"before": at(ago(days=2))})
    check(f"a normal value still pages ({r.status_code})", r.status_code == 200 and len(r.json()["items"]) == 1)

    # ------------------------------------------------------------------
    print("4. Stable paging: identical timestamps never skipped nor repeated")
    BC_T = cust("tie", "t1", "Tie Client", "main")
    T1, T2, T3 = ago(hours=5), ago(hours=9), ago(days=4)
    expected = set()
    visits = []
    for n in range(12):
        visits.append({"id": f"tv{n}", "tenant_id": "t1", "customer_id": "tie", "branch_id": "main",
                       "amount_paid": 100.0 + n, "stamps_awarded": 1, "visit_time": T1 if n < 9 else T2})
        expected.add(("visit", 100.0 + n))
    # old rows whose time was saved as text: one at T1 exactly, one older
    visits.append({"id": "tvs1", "tenant_id": "t1", "customer_id": "tie", "branch_id": "main", "amount_paid": 500.0,
                   "stamps_awarded": 1, "visit_time": T1.strftime("%Y-%m-%dT%H:%M:%S+00:00")})
    visits.append({"id": "tvs2", "tenant_id": "t1", "customer_id": "tie", "branch_id": "main", "amount_paid": 501.0,
                   "stamps_awarded": 1, "visit_time": T3.strftime("%Y-%m-%dT%H:%M:%SZ")})
    expected |= {("visit", 500.0), ("visit", 501.0)}
    db.visits.insert_many(visits)
    db.rewards_redeemed.insert_many([{"id": f"tr{n}", "tenant_id": "t1", "customer_id": "tie",
                                      "reward_name": f"Cadeau {n}", "redeemed_at": T1 if n < 5 else T3}
                                     for n in range(7)])
    expected |= {("reward", f"Cadeau {n}") for n in range(7)}
    friends = []
    for n in range(5):
        cust(f"fr{n}", "t1", f"Ami{n} Nom", "main")
        friends.append({"tenant_id": "t1", "referrer_customer_id": "tie", "referee_customer_id": f"fr{n}",
                        "referrer_pending": False, "settled_at": T1 if n < 4 else T2,
                        "referrer_given": {"points": 0, "stamps": 1, "offers": 0, "offer_text": ""}})
        expected.add(("referral", f"Ami{n}"))
    db.referral_redemptions.insert_many(friends)
    OWN_T = {"X-Card-Key": CO.key_for(BC_T)}

    def sig(i):
        return (i["kind"], i.get("amount") if i["kind"] == "visit" else i.get("title") if i["kind"] == "reward"
                else i.get("friend"))

    def walk(limit):
        out, before, pages = [], None, 0
        while pages < 200:
            params = {"limit": limit, **({"before": before} if before else {})}
            r = http("GET", f"/api/card/{BC_T}/activity", headers=OWN_T, params=params)
            if r.status_code != 200:
                return out, f"HTTP {r.status_code}"
            body = r.json()
            out += body["items"]
            pages += 1
            before = body["next"]
            if not before:
                return out, None
        return out, "too many pages"

    full = http("GET", f"/api/card/{BC_T}/activity", headers=OWN_T, params={"limit": 100}).json()
    check(f"one page of 100: all {len(expected)} rows ({len(full['items'])})",
          {sig(i) for i in full["items"]} == expected and len(full["items"]) == len(expected) and full["next"] is None)
    ats = [i["at"] for i in full["items"]]
    check("…newest first", ats == sorted(ats, reverse=True))
    check("…the text-dated visits are in their place",
          any(sig(i) == ("visit", 500.0) and i["at"] == at(T1) for i in full["items"])
          and any(sig(i) == ("visit", 501.0) and i["at"] == at(T3) for i in full["items"]))
    for limit in (1, 2, 3, 20):
        got, err = walk(limit)
        sigs = [sig(i) for i in got]
        check(f"limit={limit}: every row exactly once ({len(sigs)}/{len(expected)}, {err})",
              err is None and len(sigs) == len(expected) and set(sigs) == expected)
        check(f"limit={limit}: the same order as one page", got == full["items"])
    p = http("GET", f"/api/card/{BC_T}/activity", headers=OWN_T, params={"limit": 2}).json()
    check(f"next is an opaque cursor, not a date ({p['next']!r})", isinstance(p["next"], str) and not p["next"][:1].isdigit())
    p2 = http("GET", f"/api/card/{BC_T}/activity", headers=OWN_T, params={"limit": 2, "before": p["next"]}).json()
    p2b = http("GET", f"/api/card/{BC_T}/activity?limit=2&before={p['next']}", headers=OWN_T).json()
    check("the cursor works url-encoded or not", p2 == p2b and p2["items"] != p["items"])
    old = http("GET", f"/api/card/{BC_T}/activity", headers=OWN_T, params={"limit": 100, "before": at(T1)}).json()
    check(f"a plain ISO before still works (older than T1: {len(old['items'])})",
          {sig(i) for i in old["items"]} == {s for s in expected if s not in
                                              {sig(i) for i in full["items"] if i["at"] == at(T1)}})
    old2 = http("GET", f"/api/card/{BC_T}/activity", headers=OWN_T,
                params={"limit": 100, "before": (T1 + timedelta(seconds=1)).isoformat()}).json()
    check("…and with an offset (+00:00)", len(old2["items"]) == len(expected))
    for bad in ("c1.", "c1.!!!", "c1.Zm9v", "c1." + "A" * 120, "c9.abc"):
        r = http("GET", f"/api/card/{BC_T}/activity", headers=OWN_T, params={"before": bad})
        check(f"a broken cursor {bad[:12]!r}… → 422 ({r.status_code})", r.status_code == 422)

    # ------------------------------------------------------------------
    print("5. The campaign photo: one bounded query, same photo as the pass")
    from features import wallet_passes as WP
    from features import card_page as CP
    import mongomock.collection as MC

    BC_C = cust("cam", "t1", "Cam Client", "pal")
    KEY_C = {"X-Card-Key": CO.key_for(BC_C)}
    C1 = "d" * 32
    # 300 old campaigns to this client — a read of them all is what finding 5 was about
    db.campaigns.insert_many([{"id": f"old{n}", "tenant_id": "t1", "status": "sent", "wallet_offer": True,
                               "wallet_photo": True, "recipient_ids": ["cam"], "name": f"Vieille {n}",
                               "image_url": f"/api/media/{'e' * 32}", "sent_at": ago(days=60 + n)}
                              for n in range(300)])

    def page_photo():
        return http("GET", f"/api/card/{BC_C}", headers=KEY_C).json()["card"].get("hero_photo_url")

    def pass_photo():
        c = db.customers.find_one({"id": "cam"})
        return CP.hero_photo_url(WP._card_payload_of(server, c).get("card") or {})

    calls = []
    real_find = MC.Collection.find

    def spy_find(self, *a, **kw):
        cur = real_find(self, *a, **kw)
        if self.name == "campaigns":
            rec = {"filter": a[0] if a else kw.get("filter"), "projection": a[1] if len(a) > 1 else kw.get("projection"),
                   "limit": None}
            calls.append(rec)
            real_limit = cur.limit

            def limit(n):
                rec["limit"] = n
                return real_limit(n)
            cur.limit = limit
        return cur

    MC.Collection.find = spy_find

    def opened():
        """The card page once: its photo and the wallet-campaign queries it made
        (the card's other campaign reads — « Mes offres », défis — are the
        card payload's own, shared with the pass, and not this finding's)."""
        calls.clear()
        photo = page_photo()
        return photo, [c for c in calls if (c["filter"] or {}).get("wallet_offer")]

    try:
        photo, q = opened()
        check(f"ended campaigns only → the store's poster, like the pass ({photo})",
              photo == f"/api/media/{'b' * 32}" and photo == pass_photo())
        check(f"one wallet-campaign query per card open ({len(q)})", len(q) == 1)
        check(f"…bounded: limit ≤ 5 ({q[0]['limit'] if q else None})", q and q[0]["limit"] and 0 < q[0]["limit"] <= 5)
        check("…with a projection", q and isinstance(q[0]["projection"], dict) and q[0]["projection"])
        check("…for this client only", q and q[0]["filter"].get("recipient_ids") == "cam"
              and q[0]["filter"].get("tenant_id") == "t1")
        db.campaigns.insert_one({"id": "live", "tenant_id": "t1", "status": "sent", "wallet_offer": True,
                                 "wallet_photo": True, "recipient_ids": ["cam"], "name": "Promo",
                                 "content": "-20 %", "image_url": f"/api/media/{C1}", "sent_at": ago(days=1)})
        photo, q = opened()
        check(f"a live Wallet-photo campaign to this client → its photo ({photo})",
              photo == f"/api/media/{C1}" and photo == pass_photo())
        check(f"…still one bounded query ({len(q)})", len(q) == 1 and 0 < (q[0]["limit"] or 0) <= 5)
        BC_O = cust("other", "t1", "Other Client", "pal")
        po = http("GET", f"/api/card/{BC_O}", headers={"X-Card-Key": CO.key_for(BC_O)}).json()["card"].get("hero_photo_url")
        co = CP.hero_photo_url(WP._card_payload_of(server, db.customers.find_one({"id": "other"}))["card"])
        check(f"a campaign not for this client → no campaign photo ({po})", po != f"/api/media/{C1}" and po == co)
        db.customers.update_one({"id": "cam"}, {"$set": {"paused_at": now}})
        photo, q = opened()
        check(f"a paused client → no campaign photo, no wallet-campaign query ({photo}, {len(q)})",
              photo != f"/api/media/{C1}" and photo == pass_photo() and len(q) == 0)
        db.customers.update_one({"id": "cam"}, {"$unset": {"paused_at": ""}})
        db.campaigns.insert_one({"id": "nophoto", "tenant_id": "t1", "status": "sent", "wallet_offer": True,
                                 "wallet_photo": False, "recipient_ids": ["cam"], "name": "Sans photo",
                                 "image_url": f"/api/media/{'f' * 32}", "sent_at": ago(hours=2)})
        photo, q = opened()
        check(f"a newer campaign without the Wallet photo wins → no campaign photo ({photo})",
              photo != f"/api/media/{C1}" and photo == pass_photo())
        db.campaigns.update_many({"id": {"$in": ["live", "nophoto"]}}, {"$set": {"sent_at": ago(days=45)}})
        photo, q = opened()
        check(f"an ended campaign → no campaign photo ({photo})", photo != f"/api/media/{C1}" and photo == pass_photo())
    finally:
        MC.Collection.find = real_find
    idx = db.campaigns.index_information()
    check(f"an index serves the lookup ({sorted(idx)})",
          any([k for k, _ in v["key"]][:2] == ["tenant_id", "recipient_ids"] for v in idx.values()))

    # ------------------------------------------------------------------
    print("6. Failed card lookups are rate-limited per IP (Mongo, TTL)")
    from services import card_probe as PR
    BAD, GOOD = "203.0.113.7", "203.0.113.8"
    for n in range(30):
        r = http("GET", f"/api/card/FT-NOPE{n:04d}", ip=BAD)
        if r.status_code != 404:
            break
    check(f"30 unknown cards → 404 each ({r.status_code})", r.status_code == 404)
    r = http("GET", "/api/card/FT-NOPE9999", ip=BAD)
    check(f"the 31st → 429 ({r.status_code})", r.status_code == 429)
    check(f"…« Trop de tentatives, réessayez dans quelques minutes. » ({r.json().get('detail')!r})",
          r.json().get("detail") == "Trop de tentatives, réessayez dans quelques minutes.")
    r = http("GET", f"/api/card/{BC}", headers=OWN, ip=BAD)
    check(f"…the blocked IP is blocked even with a good key ({r.status_code})", r.status_code == 429)
    r = http("GET", f"/api/card/{BC}/activity", headers=OWN, ip=BAD)
    check(f"…and on the sub-routes ({r.status_code})", r.status_code == 429)
    r = http("GET", f"/api/card/{BC}", headers=OWN, ip=GOOD)
    check(f"a good key from another IP still works ({r.status_code})", r.status_code == 200)
    r = http("GET", "/api/card/FT-NOPE0001", ip=GOOD)
    check(f"…and that IP's own failure is a plain 404 ({r.status_code})", r.status_code == 404)

    # 403s count too; successes never do
    MID = "203.0.113.20"
    codes = [http("GET", f"/api/card/{BC}", ip=MID).status_code for _ in range(29)]
    check(f"29 × no key → 403 ({set(codes)})", set(codes) == {403})
    oks = [http("GET", f"/api/card/{BC}", headers=OWN, ip=MID).status_code for _ in range(10)]
    check(f"…then 10 good requests → 200, not counted ({set(oks)})", set(oks) == {200})
    r = http("GET", f"/api/card/{BC}", headers={"X-Card-Key": "wrong"}, ip=MID)
    check(f"…the 30th failure (wrong key) → 403 ({r.status_code})", r.status_code == 403)
    r = http("GET", f"/api/card/{BC}", headers=OWN, ip=MID)
    check(f"…then the IP is over the limit → 429 ({r.status_code})", r.status_code == 429)
    clean = "203.0.113.30"
    for _ in range(50):
        http("GET", f"/api/card/{BC}", headers=OWN, ip=clean)
    check("50 successful opens leave no counter row", db[PR.COLLECTION].count_documents({"ip": clean}) == 0)
    check("a blocked IP's extra tries are not stored without end",
          db[PR.COLLECTION].count_documents({"ip": BAD}) <= PR.LIMIT + 1)

    # a login of the card's own business refused for its rights is no probe; another business's is
    SAME = "203.0.113.50"
    codes = [http("GET", f"/api/card/{BC}/my-data", headers=STAFF_PAL, ip=SAME).status_code for _ in range(35)]
    check(f"35 × staff of the shop on the owner-only export → 403, never 429 ({set(codes)})", set(codes) == {403})
    check("…and nothing counted", db[PR.COLLECTION].count_documents({"ip": SAME}) == 0)
    OTHER = "203.0.113.51"
    GS_OWNER = login("owner@gs.fr", "business_owner", "t2")
    codes = [http("GET", f"/api/card/{BC}", headers=GS_OWNER, ip=OTHER).status_code for _ in range(31)]
    check(f"another business's owner on t1's card: 30 × 403 then 429 ({codes[-2:]})",
          set(codes[:30]) == {403} and codes[30] == 429)
    r = http("GET", "/api/card/FT-NOPE0003", headers=STAFF_PAL, ip="203.0.113.52")
    check(f"an unknown card counts whoever asks ({r.status_code}, "
          f"{db[PR.COLLECTION].count_documents({'ip': '203.0.113.52'})} row)",
          r.status_code == 404 and db[PR.COLLECTION].count_documents({"ip": "203.0.113.52"}) == 1)

    # the window passes
    real_now = PR._now
    try:
        PR._now = lambda: real_now() + timedelta(minutes=11)
        r = http("GET", f"/api/card/{BC}", headers=OWN, ip=BAD)
        check(f"11 minutes later the IP is free again ({r.status_code})", r.status_code == 200)
        r = http("GET", "/api/card/FT-NOPE0002", ip=BAD)
        check(f"…and a new failure is a plain 404 ({r.status_code})", r.status_code == 404)
    finally:
        PR._now = real_now
    ttl = [v for v in db[PR.COLLECTION].index_information().values() if v.get("expireAfterSeconds") is not None]
    check(f"a TTL index cleans the counters ({ttl})", bool(ttl))

    # X-Forwarded-For: the first address, as server._client_ip reads it everywhere
    CHAIN = "203.0.113.40"
    for n in range(30):
        http("GET", f"/api/card/FT-XFF{n:04d}", headers={"X-Forwarded-For": f"{CHAIN}, 10.0.0.1"})
    r = http("GET", f"/api/card/{BC}", headers={**OWN, "X-Forwarded-For": CHAIN})
    check(f"a proxy chain counts for its first address ({r.status_code})", r.status_code == 429)
    r = http("GET", f"/api/card/{BC}", headers={**OWN, "X-Forwarded-For": f"10.0.0.1, {CHAIN}"})
    check(f"…another first address is another client ({r.status_code})", r.status_code == 200)

    async def no_xff():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app, raise_app_exceptions=False), base_url="http://test") as ac:
            return await ac.get(f"/api/card/{BC}", headers=OWN)
    r = asyncio.get_event_loop().run_until_complete(no_xff())
    check(f"no X-Forwarded-For: the socket address, unaffected ({r.status_code})", r.status_code == 200)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
