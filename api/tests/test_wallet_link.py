"""
« Wallet mein tampons update nhi hue » (user, 2026-11-07, Royal Trim Liberté,
Nathan): the card was downloaded, its iPhone never registered, so no scan could
reach it, and nobody at the till knew. Now:

  • the scan answer says whether the client's Wallet card is linked to a phone
    (an iPhone registered, or Google confirmed the save), and why not;
  • « Google Wallet » is said only when Google confirmed the save: a Google link
    made by the card page is not a card in Google Wallet.

Run: cd api && python3 tests/test_wallet_link.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-wallet-link")
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
    import features.wallet_passes as W
    import features.push_subscriptions as PS

    db = server.db
    W.notify_customer = lambda *a, **k: {}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}
    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)

    def http(method, url, headers, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    for t in ("t1", "t2"):
        db.tenants.insert_one({"id": t, "slug": t, "name": t.upper(), "plan": "vip", "subscription_status": "active", "is_active": True})
        db.users.insert_one({"email": f"o@{t}.fr", "role": "business_owner", "tenant_id": t})
        db.card_templates.insert_one({"tenant_id": t, "programme": "stamps", "reward_threshold_stamps": 10})
    db.users.insert_one({"email": "s@t1.fr", "role": "staff", "tenant_id": "t1"})
    tok = lambda e, r, t: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, S, H2 = tok("o@t1.fr", "business_owner", "t1"), tok("s@t1.fr", "staff", "t1"), tok("o@t2.fr", "business_owner", "t2")

    def client(cid, **kw):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": f"Client {cid}", "barcode_id": f"FT-{cid.upper()}",
                                 "visits": 1, "points": 0, "created_at": now - dt.timedelta(days=3), **kw})
        return f"FT-{cid.upper()}"

    def reg(serial):
        db.pass_registrations.insert_one({"serial": serial, "device_id": f"dev-{serial}", "push_token": f"tok-{serial}",
                                          "tenant_id": "t1", "created_at": now})

    def gobj(serial, created=None):
        db.google_wallet_objects.insert_one({"serial": serial, "object_id": f"x.{serial}", "tenant_id": "t1",
                                             "created_at": created or now - dt.timedelta(days=1)})

    def scan(card, headers=H):
        r = http("POST", "/api/owner/scan", headers, json={"barcode_id": card, "amount_paid": 5})
        assert r.status_code == 200, r.text
        return r.json()["wallet_link"]

    print("\n1. The scan says whether the Wallet card can be updated")
    a = client("apple"); reg(a)
    w = scan(a)
    check("an iPhone registered: linked, Apple", w["linked"] is True and w["where"] == "apple")
    g = client("goog", google_added_at=now - dt.timedelta(hours=2)); gobj(g)
    w = scan(g)
    check("Google confirmed the save: linked, Google", w["linked"] is True and w["where"] == "google")
    n = client("nathan", apple_downloaded_at=now - dt.timedelta(minutes=1)); gobj(n)
    w = scan(n)
    check("Nathan's case: downloaded, no iPhone, only a Google link: NOT linked", w["linked"] is False)
    check("…and why: downloaded, never added", w["reason"] == "downloaded_not_registered")
    nv = client("never")
    w = scan(nv)
    check("never put in a Wallet: not linked, said so", w["linked"] is False and w["reason"] == "never_added")
    gr = client("grem", google_added_at=now - dt.timedelta(days=2), google_removed_at=now - dt.timedelta(days=1)); gobj(gr)
    check("saved to Google then removed: not linked", scan(gr)["linked"] is False)
    gb = client("gback", google_added_at=now - dt.timedelta(hours=1), google_removed_at=now - dt.timedelta(days=1)); gobj(gb)
    check("removed then saved again: linked", scan(gb)["linked"] is True)
    ar = client("arem", wallet_removed_at=now - dt.timedelta(hours=1), apple_downloaded_at=now - dt.timedelta(days=2))
    check("removed from Apple Wallet: not linked, said so", scan(ar)["linked"] is False and scan(ar)["reason"] == "removed")
    old = client("legacy"); gobj(old, created=dt.datetime(2026, 10, 1, tzinfo=UTC))
    check("a Google card from before Google told us about saves: not flagged", scan(old)["linked"] is True)
    both = client("both", google_added_at=now); reg(both); gobj(both)
    check("on an iPhone and in Google: linked", scan(both)["linked"] is True)
    check("the staff's till says it too", scan(n, S)["linked"] is False)
    r = http("POST", "/api/owner/scan", H2, json={"barcode_id": n, "amount_paid": 5})
    check("another shop: refused, nothing said", r.status_code in (403, 404) and "wallet_link" not in r.text)

    print("\n2. « Google Wallet » only when Google said so")
    st = http("GET", "/api/owner/wallet/stats", H).json()["apple_states"]
    check("Nathan is not counted in Google Wallet", st["google"] == 3)          # goog, gback, legacy
    check("…but as downloaded, never registered, once its grace is over", st["downloaded_not_registered"] == 0)
    db.customers.update_one({"id": "nathan"}, {"$set": {"apple_downloaded_at": now - dt.timedelta(minutes=30)}})
    st = http("GET", "/api/owner/wallet/stats", H).json()["apple_states"]
    check("thirty minutes on: downloaded, never registered", st["downloaded_not_registered"] == 1)
    one = http("GET", "/api/owner/clients/nathan/wallet", H).json()
    check("his own page says it", one["apple"]["state"]["key"] == "downloaded_not_registered")
    check("and Google: a link was made, no save confirmed", one["google"]["card"] is True and one["google"]["saved"] is False)
    one = http("GET", "/api/owner/clients/goog/wallet", H).json()
    check("a confirmed Google save reads Google Wallet", one["apple"]["state"]["key"] == "google" and one["google"]["saved"] is True)
    one = http("GET", "/api/owner/clients/grem/wallet", H).json()
    check("removed from Google: not Google Wallet", one["apple"]["state"]["key"] != "google")

    print("\n3. Which Wallet the problem is in (the till's steps depend on it)")
    keys = {"linked", "where", "reason", "wallet"}
    check("Nathan: downloaded on an iPhone, never linked → Apple", scan(n)["wallet"] == "apple")
    check("removed from Apple Wallet → Apple", scan(ar)["wallet"] == "apple" and scan(ar)["reason"] == "removed")
    check("removed from Google Wallet → Google", scan(gr)["wallet"] == "google" and scan(gr)["reason"] == "removed")
    gl = client("glater", wallet_removed_at=now - dt.timedelta(days=2), google_added_at=now - dt.timedelta(days=3),
                google_removed_at=now - dt.timedelta(hours=1))
    check("both removed, Google last → Google", scan(gl)["wallet"] == "google")
    al = client("alater", wallet_removed_at=now - dt.timedelta(hours=1), google_added_at=now - dt.timedelta(days=3),
                google_removed_at=now - dt.timedelta(days=2))
    check("both removed, Apple last → Apple", scan(al)["wallet"] == "apple")
    check("never in a Wallet → no Wallet named", scan(nv)["wallet"] is None)
    check("linked: the Wallet it is in", scan(a)["wallet"] == "apple" and scan(g)["wallet"] == "google")
    check("nothing but the link state is sent", set(scan(n)) == keys)

    print("\n4. The till asks again while the client adds the card (no new visit)")
    URL = "/api/owner/scan/wallet-link"
    fresh = client("fresh")
    visits_before = db.visits.count_documents({"customer_id": "fresh"})
    r = http("GET", URL, S, params={"barcode": fresh})
    check(f"staff may ask ({r.status_code})", r.status_code == 200)
    check("not in a Wallet yet", r.json().get("linked") is False and r.json().get("reason") == "never_added")
    check("only the link state comes back (no name, no phone)", set(r.json()) == keys)
    reg(fresh)
    r = http("GET", URL, H, params={"barcode": fresh})
    check("the iPhone registered: linked, Apple", r.json().get("linked") is True and r.json().get("where") == "apple")
    gnew = client("gnew"); gobj(gnew, created=now)
    check("Google link made, not saved: not linked", http("GET", URL, H, params={"barcode": gnew}).json()["linked"] is False)
    db.customers.update_one({"id": "gnew"}, {"$set": {"google_added_at": now}})
    r = http("GET", URL, H, params={"barcode": gnew}).json()
    check("Google confirmed the save: linked, Google", r["linked"] is True and r["where"] == "google")
    r = http("GET", URL, H, params={"barcode": f"https://app.fidclic.com/card/{fresh}?k=abc"})
    check("the card's own QR (a URL) works too", r.status_code == 200 and r.json()["linked"] is True)
    check("asking records no visit", db.visits.count_documents({"customer_id": "fresh"}) == visits_before)
    r = http("GET", URL, H2, params={"barcode": fresh})
    check(f"another shop: not found, nothing said ({r.status_code})", r.status_code == 404 and "linked" not in r.text)
    r = http("GET", URL, H, params={"barcode": "FT-NOPE0000"})
    check("unknown card: 404", r.status_code == 404)
    r = http("GET", URL, H, params={"barcode": ""})
    check(f"empty code: refused ({r.status_code})", r.status_code in (400, 404, 422))
    r = http("GET", URL, {}, params={"barcode": fresh})
    check(f"no login: refused ({r.status_code})", r.status_code in (401, 403))
    cust_tok = tok("c@t1.fr", "customer", "t1")
    r = http("GET", URL, cust_tok, params={"barcode": fresh})
    check(f"a customer token: refused ({r.status_code})", r.status_code in (401, 403))
    client("gone", deleted_at=now)
    r = http("GET", URL, H, params={"barcode": "FT-GONE"})
    check(f"deleted client: gone, nothing said ({r.status_code})", r.status_code == 410 and "linked" not in r.text)
    from features import role_perms as RP
    check("the page it belongs to is the till's (role rights apply)", RP.page_of(URL) == "scan")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
