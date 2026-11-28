"""
Caisse connector — the common frame (features/pos_connectors.py) with the
Square plug, through the real HTTP endpoints and the database (mongomock).
Square's answers are played by a fake; nothing leaves the laptop.

Covers: who may connect (plan, role, another shop), the one-use state of the
connect link, tokens sealed in the database, one Square shop → one FidClic
business, the webhook (signature, unknown shop, a sale with a scanned card,
an unscanned sale, the same ticket twice, another shop's card, a deleted
card), refunds (full → visit cancelled, partial → kept), the store map
(multi-store), the breaker and the retries of the tick, the token refresh,
the customer push (name + card code only), the nightly check once per Paris
day (DST too), the status page (never a token) and disconnecting.

Run: cd api && /usr/local/bin/python3 tests/test_pos_connectors.py
"""
import asyncio
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import sys
from urllib.parse import parse_qs, urlsplit

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"
os.environ.update(SQUARE_ENV="sandbox", SQUARE_APPLICATION_ID="sandbox-sq0idb-TESTAPP",
                  SQUARE_APPLICATION_SECRET="sandbox-sq0csb-TESTSECRET", SQUARE_WEBHOOK_SIGNATURE_KEY="whkey-123",
                  SQUARE_WEBHOOK_URL="https://app.fidclic.com/api/pos/square/webhook")

import services.email_check as EC  # noqa: E402

EC.domain_receives_mail = lambda d: None

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx
    from features import pos_connectors as P
    from features import merchant_api as M
    from services.pos import square as SQ

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond)
        failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def http(method, url, bearer=None, **kw):
        headers = kw.pop("headers", {})
        if bearer:
            headers["Authorization"] = "Bearer " + bearer

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, follow_redirects=False, **kw)
        out = asyncio.get_event_loop().run_until_complete(run())
        M.drain_webhooks(10)
        return out

    # ---- Square, played by a fake --------------------------------------
    square = {"calls": [], "refresh_fails": False, "revoked": [], "payments": [], "refunds": [], "customers": {},
              "fail_customer_lookup": False}

    def fake_http(method, path, token=None, json=None, params=None, client_auth=False):
        square["calls"].append({"method": method, "path": path, "token": token, "json": json, "params": params})
        if path == "/oauth2/token":
            if (json or {}).get("grant_type") == "refresh_token":
                if square["refresh_fails"]:
                    return 401, {"errors": [{"code": "UNAUTHORIZED", "detail": "revoked"}]}
                return 200, {"access_token": "EAAA-new", "refresh_token": "EQAA-new", "expires_at": "2027-01-30T10:00:00Z", "merchant_id": "MERCH1"}
            code = (json or {}).get("code")
            merchant = {"code-1": "MERCH1", "code-again": "MERCH1", "code-2": "MERCH2"}.get(code)
            if not merchant:
                return 401, {"errors": [{"code": "UNAUTHORIZED"}]}
            return 200, {"access_token": "EAAA-secret-" + merchant, "refresh_token": "EQAA-secret-" + merchant,
                         "expires_at": square.get("expires_at", "2026-12-28T10:00:00Z"), "merchant_id": merchant}
        if path == "/oauth2/revoke":
            square["revoked"].append(json)
            return 200, {"success": True}
        if path == "/v2/merchants/me":
            return 200, {"merchant": {"id": "MERCH1", "business_name": "Burger Lumière (Square)"}}
        if path == "/v2/locations":
            return 200, {"locations": [{"id": "LOC1", "name": "Centre", "currency": "EUR", "status": "ACTIVE"},
                                       {"id": "LOC2", "name": "Nord", "currency": "EUR", "status": "ACTIVE"}]}
        if path.startswith("/v2/customers/") and method == "GET":
            if square["fail_customer_lookup"]:
                return 500, {"errors": [{"code": "INTERNAL"}]}
            cid = path.rsplit("/", 1)[1]
            ref = square["customers"].get(cid)
            return (200, {"customer": {"id": cid, "reference_id": ref}}) if ref else (404, {"errors": [{"code": "NOT_FOUND"}]})
        if path == "/v2/customers/bulk-create":
            out = {}
            for k, v in (json or {}).get("customers", {}).items():
                square["customers"]["SQ-" + k] = v.get("reference_id")
                out[k] = {"customer": {"id": "SQ-" + k}}
            return 200, {"responses": out}
        if path == "/v2/payments":
            return 200, {"payments": square["payments"]}
        if path == "/v2/refunds":
            return 200, {"refunds": square["refunds"]}
        return 404, {}

    SQ.SquareAdapter.http = staticmethod(fake_http)

    URL = os.environ["SQUARE_WEBHOOK_URL"]

    def sign(body: bytes) -> str:
        return base64.b64encode(hmac.new(b"whkey-123", URL.encode() + body, hashlib.sha256).digest()).decode()

    def pay_obj(pid, amount=1250, cust=None, loc="LOC1", status="COMPLETED", at="2026-11-28T10:15:00Z"):
        p = {"id": pid, "status": status, "amount_money": {"amount": amount, "currency": "EUR"}, "location_id": loc,
             "created_at": at, "updated_at": at}
        if cust:
            p["customer_id"] = cust
        return p

    def hook(obj, kind="payment", merchant="MERCH1", event_id=None, sig=None):
        body = json.dumps({"merchant_id": merchant, "type": f"{kind}.updated", "event_id": event_id or f"ev-{obj['id']}-{obj['status']}",
                           "created_at": "2026-11-28T10:15:03Z", "data": {"type": kind, "id": obj["id"], "object": {kind: obj}}}).encode()
        return http("POST", "/api/pos/square/webhook", content=body,
                    headers={"x-square-hmacsha256-signature": sig if sig is not None else sign(body), "content-type": "application/json"})

    # ---- two businesses --------------------------------------------------
    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_many([
        {"id": "t1", "slug": "burger", "name": "Burger Lumière", "plan": "vip", "subscription_status": "active", "created_at": now,
         "branches": [{"id": "main", "name": "Centre"}, {"id": "b2", "name": "Nord"}]},
        {"id": "t2", "slug": "boul", "name": "Boulangerie", "plan": "silver", "subscription_status": "active", "created_at": now},
        {"id": "t3", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active", "created_at": now},
    ])
    db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 3, "visits_per_stamp": 1, "reward_description": "Frites offertes"})
    db.users.insert_many([{"email": "o@burger.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "m@burger.fr", "role": "manager", "tenant_id": "t1"},
                          {"email": "o@boul.fr", "role": "business_owner", "tenant_id": "t2"},
                          {"email": "o@cafe.fr", "role": "business_owner", "tenant_id": "t3"}])
    OWN = auth.create_access_token({"sub": "o@burger.fr", "role": "business_owner", "tenant_id": "t1"})
    MAN = auth.create_access_token({"sub": "m@burger.fr", "role": "manager", "tenant_id": "t1"})
    OWN2 = auth.create_access_token({"sub": "o@boul.fr", "role": "business_owner", "tenant_id": "t2"})
    OWN3 = auth.create_access_token({"sub": "o@cafe.fr", "role": "business_owner", "tenant_id": "t3"})
    db.customers.insert_many([
        {"id": "c1", "tenant_id": "t1", "barcode_id": "FT-AAA111", "name": "Inès Fontaine", "phone": "0612345678", "email": "ines@ex.fr",
         "visits": 0, "points": 0, "total_amount_paid": 0, "created_at": now, "branch_id": "main"},
        {"id": "c2", "tenant_id": "t1", "barcode_id": "FT-BBB222", "name": "Malik", "phone": "0622222222", "visits": 0, "points": 0,
         "total_amount_paid": 0, "created_at": now, "branch_id": "b2"},
        {"id": "cx", "tenant_id": "t3", "barcode_id": "FT-XXX999", "name": "Autre", "visits": 0, "points": 0, "created_at": now},
        {"id": "cdel", "tenant_id": "t1", "barcode_id": "FT-DEL000", "name": "Parti", "visits": 0, "points": 0, "created_at": now,
         "deleted_at": now},
    ])

    print("\nWho may connect")
    r = http("POST", "/api/owner/pos/square/connect", bearer=OWN2)
    check("a plan without « API & Intégrations » → 403", r.status_code == 403)
    r = http("POST", "/api/owner/pos/square/connect", bearer=MAN)
    check("a manager cannot connect the till (owner only)", r.status_code == 403)
    check("no login → 401", http("POST", "/api/owner/pos/square/connect").status_code in (401, 403))
    check("an unknown caisse → 404", http("POST", "/api/owner/pos/nope/connect", bearer=OWN).status_code == 404)
    check("a manager does not see the caisse page (same readers as API & Intégrations)", http("GET", "/api/owner/pos", bearer=MAN).status_code == 403)
    page = http("GET", "/api/owner/pos", bearer=OWN)
    check("the owner sees Square offered", page.status_code == 200 and any(p["name"] == "square" and p["configured"] for p in page.json()["providers"]))

    print("\nConnecting (OAuth)")
    r = http("POST", "/api/owner/pos/square/connect", bearer=OWN)
    url = r.json().get("url", "")
    state = parse_qs(urlsplit(url).query).get("state", [""])[0]
    check("connect gives Square's page with a long one-use state", r.status_code == 200 and url.startswith("https://connect.squareupsandbox.com/oauth2/authorize") and len(state) >= 32)
    check("the state is not stored in clear", db.pos_oauth_states.count_documents({"state": state}) == 0 and db.pos_oauth_states.count_documents({}) == 1)
    bad = http("GET", "/api/pos/square/callback?code=code-1&state=forged")
    check("a forged state → back to the page with an error, nothing connected",
          bad.status_code in (302, 303, 307) and "caisse=erreur" in bad.headers.get("location", "") and db.pos_connections.count_documents({}) == 0)
    deny = http("GET", f"/api/pos/square/callback?error=access_denied&state={state}")
    check("the owner said no on Square → error shown, nothing connected", "caisse=erreur" in deny.headers.get("location", "") and db.pos_connections.count_documents({}) == 0)
    r = http("POST", "/api/owner/pos/square/connect", bearer=OWN)
    state = parse_qs(urlsplit(r.json()["url"]).query)["state"][0]
    ok = http("GET", f"/api/pos/square/callback?code=code-1&state={state}")
    conn = db.pos_connections.find_one({"tenant_id": "t1"})
    check("a good code → connected, back on Paramètres", "caisse=ok" in ok.headers.get("location", "") and conn and conn["status"] == "connected")
    check("Square shop, merchant id and both locations saved", conn["merchant_id"] == "MERCH1" and [l["id"] for l in conn["locations"]] == ["LOC1", "LOC2"])
    raw = json.dumps(conn, default=str)
    check("the tokens are sealed in the database, never in clear", "EAAA-secret" not in raw and "EQAA-secret" not in raw and conn.get("tokens_sealed"))
    again = http("GET", f"/api/pos/square/callback?code=code-1&state={state}")
    check("the same state used twice → refused (one use)", "caisse=erreur" in again.headers.get("location", ""))
    r3 = http("POST", "/api/owner/pos/square/connect", bearer=OWN3)
    st3 = parse_qs(urlsplit(r3.json()["url"]).query)["state"][0]
    dup = http("GET", f"/api/pos/square/callback?code=code-again&state={st3}")
    check("the same Square shop cannot be linked to a second FidClic business",
          "caisse=erreur" in dup.headers.get("location", "") and db.pos_connections.count_documents({"tenant_id": "t3"}) == 0)
    old = http("POST", "/api/owner/pos/square/connect", bearer=OWN3)
    st_old = parse_qs(urlsplit(old.json()["url"]).query)["state"][0]
    db.pos_oauth_states.update_many({}, {"$set": {"expires_at": now - dt.timedelta(minutes=1)}})
    exp = http("GET", f"/api/pos/square/callback?code=code-2&state={st_old}")
    check("an expired state (over 10 min) → refused", "caisse=erreur" in exp.headers.get("location", "") and db.pos_connections.count_documents({"tenant_id": "t3"}) == 0)
    CID = conn["id"]

    print("\nStatus page")
    st = http("GET", "/api/owner/pos", bearer=OWN).json()
    c0 = st["connections"][0]
    check("the page lists the connection with its shop and locations", c0["provider"] == "square" and c0["merchant_name"] and len(c0["locations"]) == 2)
    check("the stores of the business are offered for the map", {s["id"] for s in st["stores"]} == {"main", "b2"})
    check("no token, no sealed blob in the page", "EAAA" not in json.dumps(st) and "tokens_sealed" not in json.dumps(st))
    other = http("GET", "/api/owner/pos", bearer=OWN3).json()
    check("another business sees none of it", other["connections"] == [])

    print("\nStore map (multi-store)")
    r = http("PUT", f"/api/owner/pos/connections/{CID}/locations", bearer=OWN, json={"map": {"LOC1": "main", "LOC2": "nope"}})
    check("an unknown store → 400", r.status_code == 400)
    r = http("PUT", f"/api/owner/pos/connections/{CID}/locations", bearer=OWN, json={"map": {"LOCX": "main"}})
    check("a location that is not this Square shop's → 400", r.status_code == 400)
    r = http("PUT", f"/api/owner/pos/connections/{CID}/locations", bearer=OWN3, json={"map": {"LOC1": "main"}})
    check("another business cannot change it (404, never 403: no id guessing)", r.status_code == 404)
    r = http("PUT", f"/api/owner/pos/connections/{CID}/locations", bearer=MAN, json={"map": {"LOC1": "main"}})
    check("a manager cannot change it", r.status_code == 403)
    r = http("PUT", f"/api/owner/pos/connections/{CID}/locations", bearer=OWN, json={"map": {"LOC1": "main", "LOC2": "b2"}})
    check("Centre → main, Nord → b2 saved", r.status_code == 200 and db.pos_connections.find_one({"id": CID})["location_map"] == {"LOC1": "main", "LOC2": "b2"})

    print("\nCustomer push (name + card code only)")
    n = P.sync_customers(CID, limit=50)
    pushed = [c for c in square["calls"] if c["path"] == "/v2/customers/bulk-create"]
    body = pushed[-1]["json"]["customers"] if pushed else {}
    check("the live cards of this business pushed, not the deleted one, not another shop's",
          n == 2 and set(body) == {"c1", "c2"})
    check("Inès goes as given/family name + her card's code", body.get("c1", {}).get("given_name") == "Inès" and body["c1"].get("family_name") == "Fontaine"
          and "FT-AAA111" in body["c1"].get("reference_id", ""))
    check("no phone, no e-mail, no birthday sent to Square", all("0612345678" not in json.dumps(v) and "ines@ex.fr" not in json.dumps(v) for v in body.values()))
    check("links kept per card", db.pos_customer_links.count_documents({"conn_id": CID}) == 2)
    square["calls"].clear()
    check("a second run pushes nobody again", P.sync_customers(CID, limit=50) == 0 and not square["calls"])
    db.customers.insert_one({"id": "c3", "tenant_id": "t1", "barcode_id": "FT-CCC333", "name": "Zoé", "visits": 0, "points": 0, "created_at": now})
    check("a new card later → pushed alone", P.sync_customers(CID, limit=50) == 1)

    print("\nWebhook: who is talking")
    check("no signature → 401, nothing stored", hook(pay_obj("PX1", cust="SQ-c1"), sig="").status_code == 401 and db.pos_events.count_documents({}) == 0)
    check("a wrong signature → 401, nothing stored", hook(pay_obj("PX1", cust="SQ-c1"), sig="AAAA").status_code == 401 and db.pos_events.count_documents({}) == 0)
    r = hook(pay_obj("PU1", cust="SQ-c1"), merchant="UNKNOWN")
    check("a Square shop that no business connected → 200 (Square stops retrying), nothing applied",
          r.status_code == 200 and db.visits.count_documents({"tenant_id": "t1"}) == 0)

    print("\nWebhook: a sale")
    r = hook(pay_obj("P1", amount=1850, cust="SQ-c1", loc="LOC1"))
    v = db.visits.find_one({"tenant_id": "t1", "external_id": "square:P1"})
    check("a scanned card on a Square sale → a FidClic visit, same rules as the scan", r.status_code == 200 and v and v["customer_id"] == "c1")
    check("amount 18.50 €, store Centre, tagged as coming from the caisse", v and abs(v.get("amount_paid", 0) - 18.5) < 1e-9
          and v.get("branch_id") == "main" and v.get("source") == "pos" and v.get("pos_provider") == "square")
    check("the card moved: 1 visit", db.customers.find_one({"id": "c1"})["visits"] == 1)
    t = db.pos_tickets.find_one({"provider": "square", "ticket_id": "P1"})
    check("the ticket kept, matched to the client and the visit", t and t["status"] == "matched" and t["customer_id"] == "c1" and t["visit_id"] == v["id"])
    hook(pay_obj("P1", amount=1850, cust="SQ-c1", loc="LOC1"))
    hook(pay_obj("P1", amount=1850, cust="SQ-c1", loc="LOC1"), event_id="ev-other-id-same-payment")
    check("the same ticket twice (same event, or a new event for it) → still one visit",
          db.visits.count_documents({"tenant_id": "t1", "external_id": "square:P1"}) == 1 and db.customers.find_one({"id": "c1"})["visits"] == 1)
    hook(pay_obj("P2", amount=900, cust="SQ-c2", loc="LOC2"))
    check("Nord's sale lands on store b2", (db.visits.find_one({"external_id": "square:P2"}) or {}).get("branch_id") == "b2")
    hook(pay_obj("P3", amount=700, cust=None))
    t3 = db.pos_tickets.find_one({"ticket_id": "P3"})
    check("an unscanned sale → kept as a ticket without a client, no visit",
          t3 and t3["status"] == "unmatched" and t3.get("customer_id") is None and not db.visits.find_one({"external_id": "square:P3"}))
    check("…with its amount and store (for the shop's real takings)", t3["amount"] == 7.0 and t3["branch_id"] == "main")
    hook(pay_obj("P4", status="APPROVED", cust="SQ-c1"))
    check("an APPROVED payment (not finished) → nothing yet", not db.pos_tickets.find_one({"ticket_id": "P4"}))
    square["customers"]["SQMANUAL"] = "https://app.fidclic.com/card/FT-BBB222"
    hook(pay_obj("P5", amount=500, cust="SQMANUAL"))
    check("a Square customer made by hand with the card's code → found by the code", (db.visits.find_one({"external_id": "square:P5"}) or {}).get("customer_id") == "c2")
    square["customers"]["SQOTHER"] = "https://app.fidclic.com/card/FT-XXX999"
    hook(pay_obj("P6", amount=500, cust="SQOTHER"))
    check("another business's card typed into this Square → never credited", not db.visits.find_one({"external_id": "square:P6"})
          and db.customers.find_one({"id": "cx"})["visits"] == 0 and db.pos_tickets.find_one({"ticket_id": "P6"})["status"] == "unmatched")
    square["customers"]["SQDEL"] = "FT-DEL000"
    hook(pay_obj("P7", amount=500, cust="SQDEL"))
    check("a deleted card → no visit", not db.visits.find_one({"external_id": "square:P7"}))
    square["customers"]["SQJUNK"] = "<script>alert(1)</script>"
    r = hook(pay_obj("P8", amount=500, cust="SQJUNK"))
    check("junk in Square's reference id → unmatched, no crash", r.status_code == 200 and db.pos_tickets.find_one({"ticket_id": "P8"})["status"] == "unmatched")
    big = pay_obj("P9", amount=10_000_000_00, cust="SQ-c1")
    hook(big)
    check("an absurd amount (10 M€) → kept as a ticket, flagged, no visit", db.pos_tickets.find_one({"ticket_id": "P9"})["status"] == "rejected"
          and not db.visits.find_one({"external_id": "square:P9"}))

    print("\nRefunds")
    visits_before = db.customers.find_one({"id": "c2"})["visits"]
    hook({"id": "R1", "status": "COMPLETED", "amount_money": {"amount": 300, "currency": "EUR"}, "payment_id": "P2", "location_id": "LOC2",
          "created_at": "2026-11-28T11:00:00Z"}, kind="refund")
    check("a partial refund (3 € of 9 €) → the visit stays, the ticket says partial",
          db.visits.find_one({"external_id": "square:P2"}) and db.pos_tickets.find_one({"ticket_id": "P2"})["status"] == "partial_refund")
    hook({"id": "R2", "status": "COMPLETED", "amount_money": {"amount": 600, "currency": "EUR"}, "payment_id": "P2", "location_id": "LOC2",
          "created_at": "2026-11-28T11:05:00Z"}, kind="refund")
    check("the rest refunded (3 + 6 = 9 €) → the visit is cancelled, the card goes back",
          not db.visits.find_one({"external_id": "square:P2"}) and db.customers.find_one({"id": "c2"})["visits"] == visits_before - 1
          and db.pos_tickets.find_one({"ticket_id": "P2"})["status"] == "refunded")
    hook({"id": "R2", "status": "COMPLETED", "amount_money": {"amount": 600, "currency": "EUR"}, "payment_id": "P2", "location_id": "LOC2",
          "created_at": "2026-11-28T11:05:00Z"}, kind="refund", event_id="ev-R2-again")
    check("the same refund twice → taken back once", db.customers.find_one({"id": "c2"})["visits"] == visits_before - 1)
    r = hook({"id": "R9", "status": "COMPLETED", "amount_money": {"amount": 100, "currency": "EUR"}, "payment_id": "UNKNOWN", "location_id": "LOC1",
              "created_at": "2026-11-28T11:05:00Z"}, kind="refund")
    check("a refund of a sale FidClic never saw → kept, no crash", r.status_code == 200 and db.pos_tickets.find_one({"ticket_id": "R9"}))

    print("\nThe plan goes off")
    db.tenants.update_one({"id": "t1"}, {"$set": {"plan": "silver"}})
    hook(pay_obj("P10", amount=500, cust="SQ-c1"))
    check("on a plan without the API, a sale is kept but not applied to the card",
          not db.visits.find_one({"external_id": "square:P10"}) and db.pos_tickets.find_one({"ticket_id": "P10"})["status"] == "not_applied")
    db.tenants.update_one({"id": "t1"}, {"$set": {"plan": "vip"}})

    print("\nBreaker and retries (the tick)")
    P.INLINE_PER_15MIN = 3
    before = db.visits.count_documents({"tenant_id": "t1"})
    for i in range(6):
        hook(pay_obj(f"B{i}", amount=100, cust="SQ-c1"))
    applied_now = db.visits.count_documents({"tenant_id": "t1"}) - before
    check("a burst past the limit → the extra ones wait (the database is never flooded)", applied_now < 6
          and db.pos_events.count_documents({"state": "pending"}) >= 1)
    out = P.run_due(now)
    check("the tick applies the waiting ones", db.visits.count_documents({"tenant_id": "t1"}) - before == 6 and db.pos_events.count_documents({"state": "pending"}) == 0)
    P.INLINE_PER_15MIN = 600
    square["fail_customer_lookup"] = True
    hook(pay_obj("F1", amount=100, cust="SQ-unknown-yet"))
    e = db.pos_events.find_one({"ticket.ticket_id": "F1"})
    check("Square down while reading the customer → the event waits, nothing lost", e and e["state"] == "pending" and e.get("attempts", 0) >= 1)
    for _ in range(6):
        P.run_due(now)
    e = db.pos_events.find_one({"ticket.ticket_id": "F1"})
    check("after 5 tries it is marked failed and shown, never retried forever", e["state"] == "failed" and e["attempts"] == P.MAX_ATTEMPTS)
    square["fail_customer_lookup"] = False
    fails = http("GET", "/api/owner/pos", bearer=OWN).json()["connections"][0]
    check("the status page counts the failed ticket", fails.get("failed_events", 0) >= 1)

    print("\nTokens: refresh in the tick")
    db.pos_connections.update_one({"id": CID}, {"$set": {"expires_at": now + dt.timedelta(days=3)}})
    P.run_due(now)
    c = db.pos_connections.find_one({"id": CID})
    check("a token ending within 7 days is refreshed", c["expires_at"] > now + dt.timedelta(days=30) and c["status"] == "connected")
    square["refresh_fails"] = True
    db.pos_connections.update_one({"id": CID}, {"$set": {"expires_at": now + dt.timedelta(days=1)}})
    P.run_due(now)
    c = db.pos_connections.find_one({"id": CID})
    check("Square refuses the refresh → status « à reconnecter », the owner sees why",
          c["status"] == "error" and c.get("error", {}).get("code") == "reconnect")
    square["refresh_fails"] = False
    db.pos_connections.update_one({"id": CID}, {"$set": {"status": "connected", "error": None, "expires_at": now + dt.timedelta(days=30)}})

    print("\nNightly check (once per Paris day)")
    db.pos_connections.update_one({"id": CID}, {"$set": {"last_reconcile_day": None}})   # the ticks above ran on today's clock
    square["payments"] = [pay_obj("N1", amount=1200, cust="SQ-c1", at="2026-11-28T09:00:00Z"), pay_obj("P1", amount=1850, cust="SQ-c1")]
    square["refunds"] = []
    v_before = db.customers.find_one({"id": "c1"})["visits"]
    afternoon = dt.datetime(2026, 11, 28, 14, 0, tzinfo=dt.timezone.utc)
    P.run_due(afternoon)
    check("the first check runs on the day of connection: a sale the webhook missed is added",
          db.visits.find_one({"external_id": "square:N1"}) is not None and db.pos_connections.find_one({"id": CID})["last_reconcile_day"] == "2026-11-28")
    check("a sale already there is not doubled", db.visits.count_documents({"external_id": "square:P1"}) == 1
          and db.customers.find_one({"id": "c1"})["visits"] == v_before + 1)
    square["payments"].append(pay_obj("N2", amount=800, cust="SQ-c1", at="2026-11-28T20:00:00Z"))
    P.run_due(afternoon + dt.timedelta(hours=1))
    check("later the same day → not asked again", not db.visits.find_one({"external_id": "square:N2"}))
    early = dt.datetime(2026, 11, 29, 1, 30, tzinfo=dt.timezone.utc)      # 02:30 in Paris: before 03:00
    P.run_due(early)
    check("the next day before 03:00 Paris → still waits", not db.visits.find_one({"external_id": "square:N2"}))
    night = dt.datetime(2026, 11, 29, 2, 30, tzinfo=dt.timezone.utc)      # 03:30 in Paris (UTC+1)
    P.run_due(night)
    check("03:30 Paris the next night → yesterday evening's missed sale added", db.visits.find_one({"external_id": "square:N2"}) is not None)
    calls = len([x for x in square["calls"] if x["path"] == "/v2/payments"])
    P.run_due(night + dt.timedelta(minutes=15))
    check("the same night again → not asked twice", len([x for x in square["calls"] if x["path"] == "/v2/payments"]) == calls)
    check("the Paris day is written", db.pos_connections.find_one({"id": CID})["last_reconcile_day"] == "2026-11-29")
    dst = dt.datetime(2027, 3, 28, 1, 30, tzinfo=dt.timezone.utc)        # 03:30 Paris on the night clocks go forward (UTC+2)
    P.run_due(dst)
    check("DST night: 03:30 Paris is still « that night » (2027-03-28)", db.pos_connections.find_one({"id": CID})["last_reconcile_day"] == "2027-03-28")

    print("\nCheck now (owner button)")
    r = http("POST", f"/api/owner/pos/connections/{CID}/sync", bearer=OWN)
    check("« Vérifier maintenant » runs", r.status_code == 200)
    r = http("POST", f"/api/owner/pos/connections/{CID}/sync", bearer=OWN)
    check("twice within 5 minutes → 429 (no hammering Square)", r.status_code == 429)
    check("another business → 404", http("POST", f"/api/owner/pos/connections/{CID}/sync", bearer=OWN3).status_code == 404)

    print("\nDisconnecting")
    check("a manager cannot disconnect", http("DELETE", f"/api/owner/pos/connections/{CID}", bearer=MAN).status_code == 403)
    check("another business cannot", http("DELETE", f"/api/owner/pos/connections/{CID}", bearer=OWN3).status_code == 404)
    r = http("DELETE", f"/api/owner/pos/connections/{CID}", bearer=OWN)
    c = db.pos_connections.find_one({"id": CID})
    check("disconnected: Square told, tokens wiped, status kept for history",
          r.status_code == 200 and square["revoked"] and c["status"] == "disconnected" and not c.get("tokens_sealed"))
    hook(pay_obj("AFTER1", amount=500, cust="SQ-c1"))
    check("after disconnecting, a sale changes nothing", not db.visits.find_one({"external_id": "square:AFTER1"}))
    check("the past tickets and visits stay", db.visits.find_one({"external_id": "square:P1"}) is not None)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
