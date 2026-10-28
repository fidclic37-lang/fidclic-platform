"""
Parrainage page (user, 2026-10-28):
  1. « Top parrains › Voir tous » opened a CSV download — it must open the
     list of every parrain (search, pages), not a file;
  2. « Derniers parrainages › Récompense » showed only the parrain's side
     (« 2 tampons ») while both got 2 — it shows the TOTAL of both sides, and
     each side on its own for the tooltip (« Parrain : 2 tampons · Filleul :
     2 tampons »). Same in « Voir tous » and the CSV.

Run: cd api && /usr/local/bin/python3 tests/test_referral_total_reward.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-referral-total")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


Z = {"points": 0, "stamps": 0, "offers": 0, "offer_text": ""}


def unit(R):
    print("1. Le total des deux côtés, en mots (unit)")
    t = R.total_words
    check("2 tampons + 2 tampons → « 4 tampons »", t({**Z, "stamps": 2}, {**Z, "stamps": 2}) == "4 tampons")
    check("50 points + 25 points → « 75 points »", t({**Z, "points": 50}, {**Z, "points": 25}) == "75 points")
    check("2 tampons + 25 points → « 2 tampons · 25 points »",
          t({**Z, "stamps": 2}, {**Z, "points": 25}) == "2 tampons · 25 points")
    check("one side empty → the other side's words", t({**Z, "stamps": 2}, dict(Z)) == "2 tampons"
          and t(dict(Z), {**Z, "points": 1}) == "1 point")
    check("both empty → «»", t(dict(Z), dict(Z)) == "")
    check("two different offers → both named « A + B »",
          t({**Z, "offers": 1, "offer_text": "1 coupe offerte"}, {**Z, "offers": 1, "offer_text": "-20 % sur la coupe"})
          == "1 coupe offerte + -20 % sur la coupe")
    check("the same offer twice → « 2 × 1 café offert »",
          t({**Z, "offers": 1, "offer_text": "1 café offert"}, {**Z, "offers": 1, "offer_text": "1 café offert"})
          == "2 × 1 café offert")
    check("an offer + tampons → « 2 tampons · 1 café offert »",
          t({**Z, "stamps": 2}, {**Z, "offers": 1, "offer_text": "1 café offert"}) == "2 tampons · 1 café offert")
    check("several offers on one side (repeat mode) → « 3 offres + … »",
          t({**Z, "offers": 3, "offer_text": "1 café offert"}, {**Z, "offers": 1, "offer_text": "1 croissant"})
          == "3 offres + 1 croissant")
    check("garbage never crashes", t({"stamps": "x"}, None) == "" or isinstance(t({"stamps": "x"}, None), str))

    print("\n2. Une ligne porte les deux côtés")
    cfg = {"referrer_reward_kind": "stamps", "referrer_reward_stamps": 2,
           "referee_reward_kind": "stamps", "referee_reward_stamps": 2}
    done = {"_id": "r1", "referrer_pending": False, "referrer_customer_id": "p", "referee_customer_id": "f",
            "referrer_given": {**Z, "stamps": 2}, "referee_given": {**Z, "stamps": 2},
            "created_at": dt.datetime(2026, 10, 27, tzinfo=dt.timezone.utc)}
    people = {"p": {"name": "Ahmed Alami"}, "f": {"name": "Ingrid Argiola"}}
    row = R._table_row(done, people, cfg)
    check(f"validated: « 4 tampons » in total ({row.get('reward')!r})", row.get("reward") == "4 tampons")
    check("…the parrain's side", row.get("reward_parrain") == "2 tampons")
    check("…the filleul's side", row.get("reward_filleul") == "2 tampons")
    check("…kind stamps", row.get("reward_kind") == "stamps")
    pend = {"_id": "r2", "referrer_pending": True, "referrer_customer_id": "p", "referee_customer_id": "f",
            "referrer_reward_promised": {"kind": "stamps", "n": 2}, "referee_reward_promised": {"kind": "points", "n": 25}}
    row = R._table_row(pend, people, cfg)
    check(f"pending: the promise of both sides ({row.get('reward')!r})", row.get("reward") == "2 tampons · 25 points"
          and row.get("reward_parrain") == "2 tampons" and row.get("reward_filleul") == "25 points")
    old = {"_id": "r3", "referrer_pending": True, "referrer_customer_id": "p", "referee_customer_id": "f",
           "referrer_points_promised": 50, "referee_points_promised": 10}
    row = R._table_row(old, people, {})
    check(f"pending row from before the reward kinds: its points ({row.get('reward')!r})",
          row.get("reward") == "60 points" and row.get("reward_filleul") == "10 points")
    legacy = {"_id": "r4", "referrer_pending": False, "referrer_customer_id": "p", "referee_customer_id": "f",
              "referrer_points": 50, "referee_points": 20}
    row = R._table_row(legacy, people, {})
    check(f"validated row from before *_given: « 70 points » ({row.get('reward')!r})", row.get("reward") == "70 points")
    noree = {**done, "referee_given": dict(Z)}
    row = R._table_row(noree, people, cfg)
    check("filleul got nothing → total = parrain's, filleul side «»",
          row.get("reward") == "2 tampons" and row.get("reward_filleul") == "")


def integration(server, auth, R, db):
    import httpx

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_many([
        {"id": "t1", "slug": "royal-test", "name": "Royal Test", "is_active": True, "plan": "vip",
         "subscription_status": "active",
         "branches": [{"id": "lib", "name": "LIBERTÉ", "is_main": True}, {"id": "pal", "name": "PALISSY"}]},
        {"id": "t2", "slug": "rival", "name": "Rival", "is_active": True, "plan": "vip", "subscription_status": "active"},
    ])
    db.users.insert_many([
        {"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
        {"email": "pal@x.fr", "role": "administrateur", "tenant_id": "t1", "active": True, "branch_ids": ["pal"]},
        {"email": "s@x.fr", "role": "staff", "tenant_id": "t1", "active": True},
        {"email": "r@x.fr", "role": "business_owner", "tenant_id": "t2", "active": True},
    ])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, PAL, STAFF, RIVAL = tok("o@x.fr", "business_owner"), tok("pal@x.fr", "administrateur"), \
        tok("s@x.fr", "staff"), tok("r@x.fr", "business_owner", "t2")
    r = http("PUT", "/api/owner/referrals/config", headers=H, json={
        "enabled": True, "minimum_visits_to_earn": 1, "reward_mode": "once",
        "referrer_reward_kind": "stamps", "referee_reward_kind": "stamps",
        "referrer_reward_stamps": 2, "referee_reward_stamps": 2})
    assert r.status_code == 200, r.text
    n = [0]

    def join(name, parrain=None, store="lib"):
        n[0] += 1
        body = {"name": name, "phone": f"06{n[0]:08d}", "postal_code": "37000", "birthday": "02/01/1990",
                "consent": True, "store": store}
        if parrain:
            body["parrain_barcode"] = parrain
        r = http("POST", "/api/join/royal-test", json=body)
        assert r.status_code == 200, r.text
        return r.json()["barcode_id"]

    def scan(bc):
        r = http("POST", "/api/owner/scan", headers={**H, "X-FidClic-Store": "lib"},
                 json={"barcode_id": bc, "amount_paid": 10, "branch_id": "lib"})
        assert r.status_code == 200, r.text
        return r

    print("\n3. Derniers parrainages : le total, et chaque côté")
    ahmed = join("Ahmed Alami")
    ingrid = join("Ingrid Argiola", parrain=ahmed)
    scan(ingrid)
    v = http("GET", "/api/owner/referrals/overview", headers=H).json()
    row = v["recent"][0]
    check(f"the table: « 4 tampons » ({row.get('reward')!r})", row.get("reward") == "4 tampons")
    check("…each side for the tooltip", row.get("reward_parrain") == "2 tampons" and row.get("reward_filleul") == "2 tampons")
    lst = http("GET", "/api/owner/referrals/list", headers=H).json()
    check("« Voir tous » (the table) says the same", lst["rows"][0].get("reward") == "4 tampons"
          and lst["rows"][0].get("reward_filleul") == "2 tampons")
    csv = http("GET", "/api/owner/referrals/export", headers=H).text
    check("CSV: a column per side and the total", all(h in csv for h in ("Récompense parrain", "Récompense filleul", "Récompense totale"))
          and ";2 tampons;2 tampons;4 tampons;" in csv)
    check(f"the top parrain still says what HE got (2 tampons) ({v['top_parrains']})", v["top_parrains"][0].get("reward") == "2 tampons")

    print("\n4. Top parrains › Voir tous : la liste de tous, pas un fichier")
    parrains = [ahmed] + [join(f"Parrain {i}") for i in range(1, 8)]
    for i, p in enumerate(parrains[1:], 1):
        for k in range(i % 3 + 1):
            f = join(f"Filleul {i}-{k}", parrain=p)
            if k == 0:
                scan(f)
    r = http("GET", "/api/owner/referrals/parrains", headers=H)
    d = r.json()
    check(f"answered as JSON ({r.status_code}, {r.headers.get('content-type')})",
          r.status_code == 200 and "application/json" in r.headers.get("content-type", ""))
    check(f"every parrain, not 5 ({d.get('total')})", d.get("total") == 8 and len(d.get("rows") or []) == 8)
    check("ranked like the top 5 (the first five are the overview's)",
          [x["customer_id"] for x in d["rows"][:5]] == [x["customer_id"] for x in
                                                         http("GET", "/api/owner/referrals/overview", headers=H).json()["top_parrains"]])
    check("each with its rank, filleuls and reward", all({"rank", "name", "filleuls", "reward", "initials"} <= set(x) for x in d["rows"])
          and [x["rank"] for x in d["rows"]] == list(range(1, 9)))
    s = http("GET", "/api/owner/referrals/parrains", headers=H, params={"search": "parrain 3"}).json()
    check(f"search by name ({[x['name'] for x in s['rows']]})", s["total"] == 1 and s["rows"][0]["name"].startswith("Parrain"))
    s = http("GET", "/api/owner/referrals/parrains", headers=H, params={"search": "AHMED"}).json()
    check("search ignores case and accents", s["total"] == 1)
    p2 = http("GET", "/api/owner/referrals/parrains", headers=H, params={"per_page": 3, "page": 3}).json()
    check(f"pages: 3 per page, page 3 holds the last 2 ({len(p2['rows'])})", p2["pages"] == 3 and len(p2["rows"]) == 2
          and p2["rows"][0]["rank"] == 7)
    check("a page past the end → the last page", http("GET", "/api/owner/referrals/parrains", headers=H,
                                                          params={"per_page": 3, "page": 99}).json()["page"] == 3)
    check("per_page above 100 refused", http("GET", "/api/owner/referrals/parrains", headers=H,
                                             params={"per_page": 5000}).status_code == 422)
    check("a weird search is just text (no crash)", http("GET", "/api/owner/referrals/parrains", headers=H,
                                                         params={"search": ".*[(\\"}).status_code == 200)

    print("\n5. Qui peut voir")
    check("another account sees none of them", http("GET", "/api/owner/referrals/parrains", headers=RIVAL).json()["total"] == 0)
    check("staff (no Parrainage page) refused", http("GET", "/api/owner/referrals/parrains", headers=STAFF).status_code == 403)
    palissy = join("Pierre Palissy", store="pal")
    join("Fanny Palissy", parrain=palissy, store="pal")
    pal = http("GET", "/api/owner/referrals/parrains", headers={**PAL, "X-FidClic-Store": "pal"}).json()
    check(f"a PALISSY administrateur: PALISSY's parrainages only ({[x['name'] for x in pal['rows']]})",
          pal["total"] == 1 and pal["rows"][0]["name"].startswith("Pierre"))
    check("no phone, e-mail or full card number in a row", not any(k in pal["rows"][0] for k in ("phone", "email", "barcode_id")))


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    from features import referrals as R
    unit(R)
    integration(server, auth, R, server.db)
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
