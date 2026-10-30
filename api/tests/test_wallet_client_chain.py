"""
Wallet chain per client (user, 2026-10-30, ROYAL TRIM LIBÉRTÉ: « 80 % des
clients doivent rafraîchir leur carte »). The shop's Wallet stats showed only
the 30 newest iPhones, so a returning client's card could not be traced. Now:

  • every registration event is kept with its reason (added, removed by the
    iPhone, token refused by Apple, refused registration, downloaded, updated
    by an iPhone that is not registered);
  • GET /api/owner/clients/{id}/wallet — one client's whole chain: where the
    card is, each iPhone, the last pushes with what happened, the events;
  • the shop's stats count every client by where the card is, so « pas
    inscrit » is told apart from Android / never added / removed.

Run: cd api && /usr/local/bin/python3 tests/test_wallet_client_chain.py
"""
import asyncio
import base64
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-wallet-chain")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ["APPLE_PASS_TYPE_ID"] = "pass.com.fidclic.test"
os.environ["APPLE_PASS_CERT_B64"] = base64.b64encode(b"cert").decode()
os.environ["APPLE_PASS_KEY_B64"] = base64.b64encode(b"key").decode()
passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))


def main():
    import server
    import auth
    import httpx
    from features import wallet_passes as W
    from services import apns_passes as AP
    from fastapi import HTTPException

    db = server.db
    W._db = db
    PT = "pass.com.fidclic.test"
    now = dt.datetime.now(dt.timezone.utc)
    for t in ("t1", "t2"):
        db.tenants.insert_one({"id": t, "slug": t, "name": t.upper(), "plan": "vip", "subscription_status": "active", "is_active": True})
        db.users.insert_one({"email": f"o@{t}.fr", "role": "business_owner", "tenant_id": t, "active": True})
    people = [("c1", "Ana", "FT-CHAIN001"), ("c2", "Bob", "FT-CHAIN002"), ("c3", "Cal", "FT-CHAIN003"),
              ("c4", "Dan", "FT-CHAIN004"), ("c5", "Eve", "FT-CHAIN005"), ("c6", "Fay", "FT-CHAIN006")]
    for cid, name, serial in people:
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": name, "barcode_id": serial, "created_at": now})
    db.customers.insert_one({"id": "x1", "tenant_id": "t2", "name": "Other", "barcode_id": "FT-OTHER01", "created_at": now})

    def tok(t="t1", role="business_owner"):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": f"o@{t}.fr", "role": role, "tenant_id": t})}

    def get(path, h=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(path, headers=h if h is not None else tok())
        return asyncio.get_event_loop().run_until_complete(run())

    def register(dev, serial, token, auth_ok=True):
        a = f"ApplePass {W._auth_token(serial) if auth_ok else 'wrong-wrong-wrong-wrong'}"
        try:
            return W.register_device(dev, PT, serial, W.Registration(pushToken=token), a).status_code
        except HTTPException as e:
            return e.status_code

    def kinds(serial):
        return [e["kind"] for e in db.pass_registration_log.find({"serial": serial}).sort("at", 1)]

    print("\nRegistration events are kept, with the reason")
    check("Ana's iPhone registers → 201", register("DEVAAAAAAAAAAAAAAAA1", "FT-CHAIN001", "tokA0000000000000000001") == 201)
    check("…logged « added »", kinds("FT-CHAIN001") == ["added"], kinds("FT-CHAIN001"))
    register("DEVAAAAAAAAAAAAAAAA1", "FT-CHAIN001", "tokA0000000000000000001")
    check("same iPhone, same token again → no noise", kinds("FT-CHAIN001") == ["added"], kinds("FT-CHAIN001"))
    register("DEVAAAAAAAAAAAAAAAA1", "FT-CHAIN001", "tokA0000000000000000NEW")
    check("same iPhone, new push token → « renewed »", kinds("FT-CHAIN001") == ["added", "renewed"], kinds("FT-CHAIN001"))
    check("a wrong key is refused (401)…", register("DEVBBBBBBBBBBBBBBBB2", "FT-CHAIN002", "tokB0000000000000000001", auth_ok=False) == 401)
    check("…and logged on the card « register_refused »", kinds("FT-CHAIN002") == ["register_refused"], kinds("FT-CHAIN002"))
    # a card number is on its QR: wrong-key attempts must not fill the database
    codes = {register(f"DEVFLOOD{i:012d}", "FT-CHAIN002", "tokF", auth_ok=False) for i in range(1000)}
    check("1000 more wrong-key attempts → all 401", codes == {401}, codes)
    check("…still one « register_refused » row for the card (one an hour)",
          kinds("FT-CHAIN002") == ["register_refused"], len(kinds("FT-CHAIN002")))
    register("DEVOOOOOOOOOOOOOOOO1", "FT-OTHER01", "tokO", auth_ok=False)
    check("another card still gets its own row", kinds("FT-OTHER01") == ["register_refused"], kinds("FT-OTHER01"))
    db.pass_registration_log.update_many({"serial": "FT-CHAIN002"},
                                         {"$set": {"at": now - dt.timedelta(minutes=61)}})
    register("DEVBBBBBBBBBBBBBBBB2", "FT-CHAIN002", "tokB", auth_ok=False)
    check("an hour later, a new attempt is kept again", kinds("FT-CHAIN002") == ["register_refused"] * 2, len(kinds("FT-CHAIN002")))
    db.pass_registration_log.delete_many({"serial": {"$in": ["FT-CHAIN002", "FT-OTHER01"]}, "at": {"$lt": now}})
    check("an unknown card number logs nothing (no tenant to file it under)",
          register("DEVZZZZZZZZZZZZZZZZ9", "FT-NOPE0000", "tokZ", auth_ok=True) == 404
          and db.pass_registration_log.count_documents({"serial": "FT-NOPE0000"}) == 0)
    ev = db.pass_registration_log.find_one({"serial": "FT-CHAIN001"})
    check("device ids are never stored whole", "…" in (ev.get("device") or "") and "DEVAAAAAAAAAAAAAAAA1" not in str(ev))
    check("the event carries the shop", ev.get("tenant_id") == "t1")

    register("DEVCCCCCCCCCCCCCCCC3", "FT-CHAIN003", "tokC0000000000000000001")
    W.unregister_device("DEVCCCCCCCCCCCCCCCC3", PT, "FT-CHAIN003", f"ApplePass {W._auth_token('FT-CHAIN003')}")
    check("removed by the iPhone → « removed_by_phone »", kinds("FT-CHAIN003") == ["added", "removed_by_phone"], kinds("FT-CHAIN003"))

    print("\nApple refuses a token: the registration goes, and the reason stays")
    register("DEVDDDDDDDDDDDDDDDD4", "FT-CHAIN004", "tokD0000000000000000001")

    def fake_push(tokens):
        res = {"sent": 0, "gone": [], "failed": 0, "errors": [], "results": []}
        for t in tokens:
            if t.startswith("tokD"):
                res["results"].append({"token": t, "status": 410, "reason": "Unregistered", "apns_id": "id-d"})
                res["gone"].append(t)
            else:
                res["results"].append({"token": t, "status": 200, "reason": "", "apns_id": "id-ok"})
                res["sent"] += 1
        return res
    real_push, real_ready = AP.push_to_tokens, AP.is_configured
    AP.push_to_tokens, AP.is_configured = fake_push, (lambda: True)
    try:
        W._notify_apple(["FT-CHAIN001", "FT-CHAIN004"])
    finally:
        AP.push_to_tokens, AP.is_configured = real_push, real_ready
    check("the dead registration is gone", db.pass_registrations.count_documents({"serial": "FT-CHAIN004"}) == 0)
    k4 = kinds("FT-CHAIN004")
    check("…logged « token_dropped » with Apple's reason", k4 == ["added", "token_dropped"]
          and db.pass_registration_log.find_one({"serial": "FT-CHAIN004", "kind": "token_dropped"}).get("detail") == "Unregistered", k4)

    print("\nDownloaded from the card page, and an iPhone that updates without being registered")
    real_resp = W._pkpass_response
    W._pkpass_response = lambda serial, **kw: None
    real_plan, real_owner = W._wallet_in_plan, W._owner_only
    W._wallet_in_plan, W._owner_only = (lambda b: True), (lambda b, r: None)
    try:
        W.download_apple_pass("FT-CHAIN005")
        W.latest_pass(PT, "FT-CHAIN005", f"ApplePass {W._auth_token('FT-CHAIN005')}")
        W.latest_pass(PT, "FT-CHAIN005", f"ApplePass {W._auth_token('FT-CHAIN005')}")
        W.latest_pass(PT, "FT-CHAIN001", f"ApplePass {W._auth_token('FT-CHAIN001')}")
    finally:
        W._pkpass_response = real_resp
        W._wallet_in_plan, W._owner_only = real_plan, real_owner
    check("the download is logged and stamped", kinds("FT-CHAIN005")[0] == "downloaded"
          and db.customers.find_one({"id": "c5"}).get("apple_downloaded_at"))
    check("an update with no registration is logged once an hour, not every time",
          kinds("FT-CHAIN005") == ["downloaded", "fetched_unregistered"], kinds("FT-CHAIN005"))
    check("a registered card's update logs nothing", "fetched_unregistered" not in kinds("FT-CHAIN001"))

    print("\nWhere each card is (unit)")
    regs = {"FT-CHAIN001"}
    G = {"FT-CHAIN006"}
    st = lambda cid: W.apple_state(db.customers.find_one({"id": cid}), regs, G, now=now)["key"]
    check("registered", st("c1") == "registered", st("c1"))
    check("refused registration, never added → « none »", st("c2") == "none", st("c2"))
    db.customers.update_one({"id": "c3"}, {"$set": {"wallet_removed_at": now}})
    check("removed by the iPhone", st("c3") == "removed", st("c3"))
    check("on an iPhone but not registered (an unregistered update seen)", st("c5") == "on_phone_unregistered", st("c5"))
    db.customers.insert_one({"id": "c7", "tenant_id": "t1", "name": "Gil", "barcode_id": "FT-CHAIN007", "created_at": now,
                             "apple_downloaded_at": now - dt.timedelta(hours=2)})
    check("downloaded, never registered", st("c7") == "downloaded_not_registered", st("c7"))
    db.customers.insert_one({"id": "c8", "tenant_id": "t1", "name": "Hal", "barcode_id": "FT-CHAIN008", "created_at": now,
                             "apple_downloaded_at": now - dt.timedelta(minutes=1)})
    check("downloaded a minute ago → still « none » (the iPhone has not answered yet)", st("c8") == "none", st("c8"))
    check("Google Wallet", st("c6") == "google", st("c6"))
    check("empty customer → « none »", W.apple_state({}, set(), set(), now=now)["key"] == "none")
    check("every state has a French label", all(W.apple_state(db.customers.find_one({"id": c}), regs, G, now=now)["label"]
                                                 for c in ("c1", "c2", "c3", "c5", "c6", "c7")))

    print("\nGET /api/owner/clients/{id}/wallet")
    r = get("/api/owner/clients/c1/wallet")
    check(f"200 for the shop's own client ({r.status_code})", r.status_code == 200, r.text[:200])
    d = r.json()
    check("the card number and its state", d["serial"] == "FT-CHAIN001" and d["apple"]["state"]["key"] == "registered")
    check("one iPhone, shortened", len(d["apple"]["devices"]) == 1 and "…" in d["apple"]["devices"][0]["device"])
    check("the push with Apple's answer and what happened", d["apple"]["pushes"] and d["apple"]["pushes"][0]["apple"] == 200
          and d["apple"]["pushes"][0]["state"])
    check("the events, newest first, labelled", [e["kind"] for e in d["apple"]["events"]][:2] == ["renewed", "added"]
          and all(e["label"] for e in d["apple"]["events"]))
    check("no push token in the answer", "tokA0000000000000000NEW" not in r.text and "DEVAAAAAAAAAAAAAAAA1" not in r.text)
    r4 = get("/api/owner/clients/c4/wallet").json()
    check("a dropped card keeps its history (push refused by Apple, token_dropped)",
          r4["apple"]["state"]["key"] != "registered" and any(e["kind"] == "token_dropped" for e in r4["apple"]["events"])
          and r4["apple"]["pushes"] and r4["apple"]["pushes"][0]["apple"] == 410)
    check("another shop's client → 404", get("/api/owner/clients/x1/wallet").status_code == 404)
    check("a client of t1 seen from t2 → 404", get("/api/owner/clients/c1/wallet", tok("t2")).status_code == 404)
    check("no token → 401/403", get("/api/owner/clients/c1/wallet", {}).status_code in (401, 403))
    check("unknown id → 404", get("/api/owner/clients/nope/wallet").status_code == 404)
    db.customers.update_one({"id": "c2"}, {"$set": {"deleted_at": now}})
    check("a deleted client → 404", get("/api/owner/clients/c2/wallet").status_code == 404)
    db.customers.update_one({"id": "c2"}, {"$unset": {"deleted_at": ""}})

    print("\nThe shop's stats count every client by where the card is")
    db.google_wallet_objects.insert_one({"serial": "FT-CHAIN006", "tenant_id": "t1"})
    s = get("/api/owner/wallet/stats").json()
    a = s.get("apple_states") or {}
    total = sum(a.values())
    check(f"every client counted once ({total} vs {s.get('customers')})", total == s.get("customers"), a)
    check("registered 1, removed 1, google 1, on an iPhone unregistered 1, downloaded unregistered 1",
          a.get("registered") == 1 and a.get("removed") == 1 and a.get("google") == 1
          and a.get("on_phone_unregistered") == 1 and a.get("downloaded_not_registered") == 1, a)
    check("other shops' clients not counted", "FT-OTHER01" not in str(s))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
