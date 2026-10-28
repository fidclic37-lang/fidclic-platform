"""
A pending parrainage pays what the card can show (user, 2026-10-28, ROYAL
TRIM: two parrainages made while the shop paid points still promised
« 75 points » after it moved to tampons — on a tampons card points never
show, so the reward would have vanished). Rule chosen by the user:
  • a promise of the card's own kind (tampons on a tampons card, points on a
    points card) or an offer stays as promised;
  • a promise the card cannot show (points on a tampons card, tampons on a
    points card) becomes today's setting for that side, when it is paid AND
    on the page while it waits;
  • each side follows ITS OWN card (multi-store: each establishment's card).

Run: cd api && /usr/local/bin/python3 tests/test_referral_promise_fits_card.py
"""
import asyncio
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-promise-fits")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def unit(R):
    print("1. Ce que la carte sait montrer (unit)")
    cfg = {"referrer_reward_kind": "stamps", "referrer_reward_stamps": 2,
           "referee_reward_kind": "stamps", "referee_reward_stamps": 3}
    pts = {"referrer_reward_promised": {"kind": "points", "n": 50}, "referee_reward_promised": {"kind": "points", "n": 25}}
    check("points promised, tampons card → today's tampons (parrain 2)",
          R.effective_promise(pts, "referrer", cfg, "stamps") == {"kind": "stamps", "n": 2})
    check("…filleul's own setting (3)", R.effective_promise(pts, "referee", cfg, "stamps") == {"kind": "stamps", "n": 3})
    st = {"referrer_reward_promised": {"kind": "stamps", "n": 1}}
    check("tampons promised, tampons card → as promised (1, not today's 2)",
          R.effective_promise(st, "referrer", cfg, "stamps") == {"kind": "stamps", "n": 1})
    check("tampons promised, points card → today's setting",
          R.effective_promise(st, "referrer", {"referrer_reward_kind": "points", "referrer_reward_points": 40},
                              "points_visit") == {"kind": "points", "n": 40})
    check("points promised, points card → as promised",
          R.effective_promise(pts, "referrer", {"referrer_reward_kind": "points", "referrer_reward_points": 99},
                              "points_euro") == {"kind": "points", "n": 50})
    off = {"referrer_reward_promised": {"kind": "offer", "text": "1 café offert"}}
    check("an offer is shown on any card → as promised", R.effective_promise(off, "referrer", cfg, "stamps")["kind"] == "offer")
    old = {"referrer_points_promised": 50}
    check("rows older than the reward kinds (points number only) → today's tampons",
          R.effective_promise(old, "referrer", cfg, "stamps") == {"kind": "stamps", "n": 2})
    check("nothing promised stays nothing", R.effective_promise({"referrer_points_promised": 0}, "referrer", cfg, "stamps")
          == {"kind": "points", "n": 0})
    check("cashback counts as a points card", R.effective_promise(pts, "referrer", cfg, "cashback")["kind"] == "points")
    check("unknown programme → as promised (never guess)", R.effective_promise(pts, "referrer", cfg, None)["kind"] == "points")
    # the owner pays points on purpose on a tampons card (its back shows a
    # points balance): a points promise there stays as promised (30, not 50)
    on_purpose = {"referrer_reward_kind": "points", "referrer_reward_points": 50}
    check("points promised, points still chosen today, tampons card → as promised (30)",
          R.effective_promise({"referrer_reward_promised": {"kind": "points", "n": 30}}, "referrer", on_purpose, "stamps")
          == {"kind": "points", "n": 30})


def integration(server, auth, R, db):
    import httpx

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "royal-test", "name": "Royal Test", "is_active": True, "plan": "vip",
                           "subscription_status": "active",
                           "branches": [{"id": "lib", "name": "LIBERTÉ", "is_main": True}, {"id": "pal", "name": "PALISSY"}]})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "points_visit", "points_per_visit": 10})
    n = [0]

    def settings(**kw):
        base = {"enabled": True, "minimum_visits_to_earn": 1, "reward_mode": "once",
                "referrer_reward_kind": "points", "referee_reward_kind": "points",
                "referrer_reward_points": 50, "referee_reward_points": 25,
                "referrer_reward_stamps": 2, "referee_reward_stamps": 2}
        r = http("PUT", "/api/owner/referrals/config", headers=H, json={**base, **kw})
        assert r.status_code == 200, r.text

    def join(name, parrain=None, store="lib"):
        n[0] += 1
        body = {"name": name, "phone": f"06{n[0]:08d}", "postal_code": "37000", "birthday": "02/01/1990",
                "consent": True, "store": store}
        if parrain:
            body["parrain_barcode"] = parrain
        r = http("POST", "/api/join/royal-test", json=body)
        assert r.status_code == 200, r.text
        return r.json()["barcode_id"]

    def scan(bc, store="lib"):
        r = http("POST", "/api/owner/scan", headers={**H, "X-FidClic-Store": store},
                 json={"barcode_id": bc, "amount_paid": 10, "branch_id": store})
        assert r.status_code == 200, r.text

    cust = lambda bc: db.customers.find_one({"barcode_id": bc}, {"_id": 0})  # noqa: E731
    row = lambda bc: db.referral_redemptions.find_one({"referee_customer_id": cust(bc)["id"]})  # noqa: E731

    print("\n2. Le cas ROYAL TRIM : promis en points, la boutique passe aux tampons")
    settings()
    mahdi = join("Mahdi Fakir")
    adams = join("Adams Yao", parrain=mahdi)
    check("the promise was points (50 / 25)", row(adams)["referrer_reward_promised"] == {"kind": "points", "n": 50})
    settings(referrer_reward_kind="stamps", referee_reward_kind="stamps")
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"programme": "stamps", "reward_threshold_stamps": 10}})
    v = http("GET", "/api/owner/referrals/overview", headers=H).json()
    pend = [x for x in v["recent"] if x["status"] == "pending"][0]
    check(f"waiting, the page says what will be given: « 4 tampons » ({pend['reward']!r})",
          pend["reward"] == "4 tampons" and pend["reward_parrain"] == "2 tampons" and pend["reward_filleul"] == "2 tampons")
    csv = http("GET", "/api/owner/referrals/export", headers=H).text
    check("…the CSV too", ";2 tampons;2 tampons;4 tampons;" in csv and "75 points" not in csv)
    before = cust(mahdi)
    scan(adams)
    r = row(adams)
    check(f"paid in tampons: parrain 2, filleul 2 ({r.get('referrer_given')}, {r.get('referee_given')})",
          (r.get("referrer_given") or {}).get("stamps") == 2 and (r.get("referee_given") or {}).get("stamps") == 2)
    check("…no invisible points on either card", int(cust(mahdi).get("points") or 0) == int(before.get("points") or 0)
          and (r.get("referrer_given") or {}).get("points") == 0 and r.get("referrer_points") == 0)
    v = http("GET", "/api/owner/referrals/overview", headers=H).json()
    done = [x for x in v["recent"] if x["filleul"]["name"].startswith("Adams")][0]
    check(f"validated row: « 4 tampons » ({done['reward']!r})", done["reward"] == "4 tampons")
    check("the « Tampons offerts » card counts them (4)", {c["key"]: c for c in v["cards"]}["points"]["value"] == 4)

    print("\n3. Une promesse que la carte sait montrer reste telle quelle")
    roth = join("Roth Ancien")
    evan = join("Evan Riviere", parrain=roth)                      # promised 2 tampons (today's)
    settings(referrer_reward_kind="stamps", referee_reward_kind="stamps", referrer_reward_stamps=5, referee_reward_stamps=5)
    scan(evan)
    r = row(evan)
    check(f"tampons promised on a tampons card: 2 as promised, not today's 5 ({r.get('referrer_given')})",
          (r.get("referrer_given") or {}).get("stamps") == 2)

    print("\n4. Chaque côté suit SA carte (multi-boutique)")
    db.card_templates.insert_one({"tenant_id": "t1", "store_id": "pal", "programme": "points_visit", "points_per_visit": 10})
    settings()                                                     # points again: promises in points
    lea = join("Léa Liberte", store="lib")                         # LIBERTÉ: tampons card
    paul = join("Paul Palissy", parrain=lea, store="pal")          # joins the parrain's store (LIBERTÉ)
    zoe = join("Zoé Palissy", store="pal")                         # PALISSY: points card
    max_ = join("Max Palissy", parrain=zoe, store="pal")
    settings(referrer_reward_kind="stamps", referee_reward_kind="stamps")
    scan(paul)
    scan(max_, store="pal")
    r1, r2 = row(paul), row(max_)
    check(f"LIBERTÉ parrain (tampons card): points promise → 2 tampons ({r1.get('referrer_given')})",
          (r1.get("referrer_given") or {}).get("stamps") == 2)
    check(f"PALISSY parrain (points card): points promise kept → 50 points ({r2.get('referrer_given')})",
          (r2.get("referrer_given") or {}).get("points") == 50 and (r2.get("referrer_given") or {}).get("stamps") == 0)


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
