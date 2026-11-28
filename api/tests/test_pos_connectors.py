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
import re
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
    square = {"calls": [], "deleted": [], "refresh_fails": False, "revoked": [], "payments": [], "refunds": [], "customers": {},
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
                m = re.search(r"(FT-[A-Z0-9]+)", v.get("reference_id") or "")
                fid = (db.customers.find_one({"barcode_id": m.group(1)}) or {}).get("id") if m else None
                if fid:                                  # Square's id, played as SQ-<FidClic id> so the tests can name it
                    square["customers"]["SQ-" + fid] = v.get("reference_id")
                    out[k] = {"customer": {"id": "SQ-" + fid}}
            return 200, {"responses": out}
        if path == "/v2/customers/bulk-delete":
            ids = (json or {}).get("customer_ids") or []
            square["deleted"].extend(ids)
            return 200, {"responses": {i: {} for i in ids}}
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
    COOKIE = "fc_pos_nonce"

    def begin(bearer, **kw):
        """« Connecter » in one browser: Square's link, its state, and the browser's own cookie."""
        r = http("POST", "/api/owner/pos/square/connect", bearer=bearer, **kw)
        st = parse_qs(urlsplit(r.json().get("url", "")).query).get("state", [""])[0]
        return r, st, r.cookies.get(COOKIE) or ""

    def back(qs, nonce=None):
        """Square sends that browser back to us (its cookie comes along, or not)."""
        return http("GET", f"/api/pos/square/callback?{qs}", headers={"cookie": f"{COOKIE}={nonce}"} if nonce else {})

    r, state, nonce = begin(OWN)
    url = r.json().get("url", "")
    check("connect gives Square's page with a long one-use state", r.status_code == 200 and url.startswith("https://connect.squareupsandbox.com/oauth2/authorize") and len(state) >= 32)
    check("the state is not stored in clear", db.pos_oauth_states.count_documents({"state": state}) == 0 and db.pos_oauth_states.count_documents({}) == 1)
    sc = r.headers.get("set-cookie", "")
    check("connect leaves a browser cookie: HttpOnly, SameSite=Lax, only for /api/pos", nonce and len(nonce) >= 32 and "httponly" in sc.lower()
          and "samesite=lax" in sc.lower() and "path=/api/pos" in sc.lower())
    check("…and the cookie is not stored in clear either", nonce not in json.dumps(list(db.pos_oauth_states.find({}, {"_id": 0})), default=str))
    rs, _, _ = begin(OWN, headers={"x-forwarded-proto": "https"})
    check("on https the cookie is Secure", "secure" in rs.headers.get("set-cookie", "").lower())
    bad = back("code=code-1&state=forged", nonce)
    check("a forged state → back to the page with an error, nothing connected",
          bad.status_code in (302, 303, 307) and "caisse=erreur" in bad.headers.get("location", "") and db.pos_connections.count_documents({}) == 0)
    deny = back(f"error=access_denied&state={state}", nonce)
    check("the owner said no on Square → error shown, nothing connected", "caisse=erreur" in deny.headers.get("location", "") and db.pos_connections.count_documents({}) == 0)

    print("\nConnecting: someone else's link (OAuth CSRF, pentest 2026-11-28)")
    _, st_att, nonce_att = begin(OWN3)                 # the attacker's own « Connecter » (t3)
    _, _, nonce_vic = begin(OWN)                       # the victim's browser has its own cookie (or none at all)
    csrf = back(f"code=code-1&state={st_att}", nonce_vic)
    check("attacker's link approved in the victim's browser → refused, the victim's Square is NOT linked to the attacker",
          "caisse=erreur" in csrf.headers.get("location", "") and db.pos_connections.count_documents({"merchant_id": "MERCH1"}) == 0)
    csrf2 = back(f"code=code-1&state={st_att}")
    check("…and with no cookie at all → refused", "caisse=erreur" in csrf2.headers.get("location", "") and db.pos_connections.count_documents({}) == 0)
    _, st_att2, _ = begin(OWN3)
    csrf3 = back(f"code=code-1&state={st_att2}", "x" * 43)
    check("…and with a made-up cookie → refused", "caisse=erreur" in csrf3.headers.get("location", "") and db.pos_connections.count_documents({}) == 0)
    check("the refusal says why in plain words (lien)", "raison=lien" in csrf.headers.get("location", ""))

    _, state, nonce = begin(OWN)
    ok = back(f"code=code-1&state={state}", nonce)
    conn = db.pos_connections.find_one({"tenant_id": "t1"})
    check("a good code in the same browser → connected, back on Paramètres", "caisse=ok" in ok.headers.get("location", "") and conn and conn["status"] == "connected")
    check("the cookie is cleared once used", COOKIE in ok.headers.get("set-cookie", "") and "max-age=0" in ok.headers.get("set-cookie", "").lower())
    check("Square shop, merchant id and both locations saved", conn["merchant_id"] == "MERCH1" and [l["id"] for l in conn["locations"]] == ["LOC1", "LOC2"])
    raw = json.dumps(conn, default=str)
    check("the tokens are sealed in the database, never in clear", "EAAA-secret" not in raw and "EQAA-secret" not in raw and conn.get("tokens_sealed"))
    again = back(f"code=code-1&state={state}", nonce)
    check("the same state used twice → refused (one use)", "caisse=erreur" in again.headers.get("location", ""))
    _, st3, n3 = begin(OWN3)
    dup = back(f"code=code-again&state={st3}", n3)
    check("the same Square shop cannot be linked to a second FidClic business",
          "caisse=erreur" in dup.headers.get("location", "") and db.pos_connections.count_documents({"tenant_id": "t3"}) == 0)
    _, st_old, n_old = begin(OWN3)
    db.pos_oauth_states.update_many({}, {"$set": {"expires_at": now - dt.timedelta(minutes=1)}})
    exp = back(f"code=code-2&state={st_old}", n_old)
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
    pushed = [c for c in square["calls"] if c["path"] == "/v2/customers/bulk-create"]
    body = pushed[-1]["json"]["customers"] if pushed else {}
    check("the cards go to Square right at connect (no hours of waiting, load 2026-11-28)",
          db.pos_customer_links.count_documents({"conn_id": CID}) == 2)
    sent = {re.search(r"FT-[A-Z0-9]+", v.get("reference_id", "")).group(0): v for v in body.values()}
    check("the live cards of this business pushed, not the deleted one, not another shop's", set(sent) == {"FT-AAA111", "FT-BBB222"})
    ines = sent.get("FT-AAA111", {})
    check("Inès goes as given/family name + her card's code", ines.get("given_name") == "Inès" and ines.get("family_name") == "Fontaine")
    check("no phone, no e-mail, no birthday sent to Square", all("0612345678" not in json.dumps(v) and "ines@ex.fr" not in json.dumps(v) for v in body.values()))
    check("links say FidClic made them (so FidClic may delete them)", db.pos_customer_links.count_documents({"conn_id": CID, "origin": "pushed"}) == 2)
    square["calls"].clear()
    check("a second run pushes nobody again", P.sync_customers(CID, limit=50) == 0 and not square["calls"])
    db.customers.insert_one({"id": "c3", "tenant_id": "t1", "barcode_id": "FT-CCC333", "name": "Zoé", "visits": 0, "points": 0, "created_at": now,
                             "last_visit_date": now - dt.timedelta(days=400)})
    db.customers.insert_one({"id": "c4", "tenant_id": "t1", "barcode_id": "FT-DDD444", "name": "Habitué", "visits": 30, "points": 0, "created_at": now,
                             "last_visit_date": now})
    square["calls"].clear()
    check("new cards later → pushed, a limit of 1 takes the regular first", P.sync_customers(CID, limit=1) == 1
          and "FT-DDD444" in json.dumps(square["calls"][-1]["json"]["customers"]))
    check("…and the rest on the next run", P.sync_customers(CID, limit=50) == 1)
    check("a tick pushes thousands, not 200 (load 2026-11-28)", P.SYNC_PER_TICK >= 2000 and P.SYNC_TOTAL_PER_TICK >= 5000)

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
    check("…it waits for its sale (Square does not promise the order)", db.pos_tickets.find_one({"ticket_id": "R9"})["status"] == "refund_waiting")

    print("\nRefund BEFORE its sale (pentest 2026-11-28)")
    def refund_obj(rid, pid, amount):
        return {"id": rid, "status": "COMPLETED", "amount_money": {"amount": amount, "currency": "EUR"}, "payment_id": pid,
                "location_id": "LOC1", "created_at": "2026-11-28T11:10:00Z"}
    v0 = db.customers.find_one({"id": "c1"})["visits"]
    hook(refund_obj("RE1", "PE1", 2000), kind="refund")
    hook(pay_obj("PE1", amount=2000, cust="SQ-c1"))
    check("paid 20 €, refunded 20 € — refund first → no visit, the card does not move",
          not db.visits.find_one({"external_id": "square:PE1"}) and db.customers.find_one({"id": "c1"})["visits"] == v0)
    check("the sale says refunded, its refund is done", db.pos_tickets.find_one({"ticket_id": "PE1"})["status"] == "refunded"
          and db.pos_tickets.find_one({"ticket_id": "RE1"})["status"] == "refund_done")
    hook(refund_obj("RE2", "PE2", 500), kind="refund")
    hook(pay_obj("PE2", amount=2000, cust="SQ-c1"))
    check("refund first, but only 5 € of 20 € → the visit is made, the sale says partial",
          db.visits.find_one({"external_id": "square:PE2"}) and db.pos_tickets.find_one({"ticket_id": "PE2"})["status"] == "partial_refund"
          and db.customers.find_one({"id": "c1"})["visits"] == v0 + 1)
    hook(refund_obj("RE3", "PE2", 1500), kind="refund")
    check("…the rest refunded later → the visit is cancelled", not db.visits.find_one({"external_id": "square:PE2"})
          and db.customers.find_one({"id": "c1"})["visits"] == v0)
    # the race: the refund looks while the sale is still being applied (it sees « processing ») and waits
    hook(pay_obj("PE3", amount=1000, cust="SQ-c1"))
    db.pos_tickets.insert_one({"provider": "square", "ticket_id": "RE4", "tenant_id": "t1", "conn_id": CID, "kind": "refund", "amount": 10.0,
                               "currency": "EUR", "location_id": "LOC1", "refund_of": "PE3", "at": now, "created_at": now, "status": "refund_waiting"})
    check("(race set-up: the sale is applied, its refund is waiting)", db.visits.find_one({"external_id": "square:PE3"}) is not None)
    P.run_due(now)
    check("the tick settles a waiting refund → the visit is cancelled", not db.visits.find_one({"external_id": "square:PE3"})
          and db.pos_tickets.find_one({"ticket_id": "RE4"})["status"] == "refund_done"
          and db.pos_tickets.find_one({"ticket_id": "PE3"})["status"] == "refunded")
    square["payments"] = [pay_obj("PE4", amount=1200, cust="SQ-c1")]
    square["refunds"] = [refund_obj("RE5", "PE4", 1200)]
    hook(refund_obj("RE5", "PE4", 1200), kind="refund")      # the door got the refund, never the sale
    P.reconcile(db.pos_connections.find_one({"id": CID}, {"_id": 0}), now)
    check("night check brings the missed sale of a refund already seen → no visit", not db.visits.find_one({"external_id": "square:PE4"})
          and db.pos_tickets.find_one({"ticket_id": "PE4"})["status"] == "refunded")
    square["payments"], square["refunds"] = [], []

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
    P.INLINE_PER_15MIN = 3000
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

    print("\nA big night check is cut into pieces (load 2026-11-28)")
    P.RECONCILE_MAX_APPLY = 2
    db.pos_connections.update_one({"id": CID}, {"$set": {"last_reconcile_day": "2027-03-28"}})
    square["payments"] = [pay_obj(f"NB{i}", amount=500, cust="SQ-c1") for i in range(5)]
    n3 = dt.datetime(2027, 3, 29, 1, 30, tzinfo=dt.timezone.utc)      # 03:30 Paris
    P.run_due(n3)
    got = db.visits.count_documents({"external_id": {"$regex": "^square:NB"}})
    c = db.pos_connections.find_one({"id": CID})
    check("one tick applies at most RECONCILE_MAX_APPLY missed tickets", got == 2)
    check("…and the night is not marked done while some are left", c.get("last_reconcile_day") != "2027-03-29" and c.get("reconcile_open"))
    P.run_due(n3 + dt.timedelta(minutes=15))
    P.run_due(n3 + dt.timedelta(minutes=30))
    c = db.pos_connections.find_one({"id": CID})
    check("the next ticks finish it, nothing twice", db.visits.count_documents({"external_id": {"$regex": "^square:NB"}}) == 5
          and c.get("last_reconcile_day") == "2027-03-29" and not c.get("reconcile_open"))
    P.RECONCILE_MAX_APPLY = 400
    square["payments"] = []

    print("\nThe tick is fair between shops (load 2026-11-28)")
    db.pos_connections.insert_one({"id": "pos_other", "tenant_id": "t3", "provider": "square", "label": "Square", "merchant_id": "MERCH9",
                                   "status": "connected", "created_at": now, "locations": [], "location_map": {},
                                   "tokens_sealed": P._seal({"access_token": "EAAA-x", "refresh_token": "r"}), "expires_at": now + dt.timedelta(days=60)})
    for i in range(10):
        db.pos_events.insert_one({"id": f"fa{i}", "provider": "square", "conn_id": CID, "tenant_id": "t1", "state": "pending", "attempts": 0,
                                  "at": now - dt.timedelta(minutes=30 - i), "ticket": {**P._ticket_out({"provider": "square", "ticket_id": f"FA{i}", "kind": "sale",
                                  "amount": 1.0, "currency": "EUR", "location_id": "LOC1", "customer_id": None, "refund_of": None, "at": now})}})
    db.pos_events.insert_one({"id": "fb0", "provider": "square", "conn_id": "pos_other", "tenant_id": "t3", "state": "pending", "attempts": 0,
                              "at": now, "ticket": {"provider": "square", "ticket_id": "FB0", "kind": "sale", "amount": 1.0, "currency": "EUR",
                                                    "location_id": "X", "customer_id": None, "refund_of": None, "at": now}})
    P.TICK_EVENTS, P.TICK_PER_CONN = 5, 3
    P.run_due(now)
    check("a shop with a long queue does not starve another shop's ticket", db.pos_events.find_one({"id": "fb0"})["state"] == "done")
    check("…and gets at most its share per tick", db.pos_events.count_documents({"id": {"$regex": "^fa"}, "state": "done"}) == 3)
    P.TICK_EVENTS, P.TICK_PER_CONN = 2000, 600
    P.run_due(now)
    check("the next tick finishes the queue", db.pos_events.count_documents({"id": {"$regex": "^f[ab]"}, "state": "pending"}) == 0)
    check("defaults let a lunch rush through: 3000 events / 15 min inline, 2000 a tick",
          P.INLINE_PER_15MIN >= 3000 and P.TICK_EVENTS >= 2000)
    db.pos_connections.delete_one({"id": "pos_other"})

    print("\nCheck now (owner button)")
    r = http("POST", f"/api/owner/pos/connections/{CID}/sync", bearer=OWN)
    check("« Vérifier maintenant » runs", r.status_code == 200)
    r = http("POST", f"/api/owner/pos/connections/{CID}/sync", bearer=OWN)
    check("twice within 5 minutes → 429 (no hammering Square)", r.status_code == 429)
    check("another business → 404", http("POST", f"/api/owner/pos/connections/{CID}/sync", bearer=OWN3).status_code == 404)

    print("\nA deleted card leaves Square too (pentest 2026-11-28)")
    square["deleted"].clear()
    db.customers.update_one({"id": "c3"}, {"$set": {"deleted_at": now}})
    db.customers.update_one({"id": "c2"}, {"$set": {"deleted_at": now}})        # c2 was linked by FidClic's push
    sq_c3 = db.pos_customer_links.find_one({"conn_id": CID, "customer_id": "c3"})["provider_customer_id"]
    P.run_due(now)
    check("the Square customer FidClic made for a deleted card is deleted at Square", sq_c3 in square["deleted"])
    check("…and the link is gone", not db.pos_customer_links.find_one({"conn_id": CID, "customer_id": "c3"}))
    db.pos_customer_links.update_one({"conn_id": CID, "customer_id": "c1"}, {"$set": {"origin": "found", "provider_customer_id": "SQ-HANDMADE"}})
    db.customers.update_one({"id": "c1"}, {"$set": {"card_deleted_at": now}})
    P.run_due(now)
    check("a Square customer the shop typed by hand is never deleted by FidClic (only unlinked)",
          "SQ-HANDMADE" not in square["deleted"] and not db.pos_customer_links.find_one({"conn_id": CID, "customer_id": "c1"}))
    db.customers.update_many({"id": {"$in": ["c1", "c2"]}}, {"$unset": {"deleted_at": "", "card_deleted_at": ""}})
    P.sync_customers(CID, limit=50)
    check("a restored card goes back to Square (client restore is allowed any time)",
          db.pos_customer_links.find_one({"conn_id": CID, "customer_id": "c2", "origin": "pushed"}) is not None)
    db.customers.update_one({"id": "c4"}, {"$set": {"paused_at": now}})
    P.run_due(now)
    check("a paused client stays at Square (pause = no messages, the card still works)",
          db.pos_customer_links.find_one({"conn_id": CID, "customer_id": "c4"}) is not None)

    print("\nThe token key (pentest 2026-11-28)")
    saved_jwt = os.environ.get("JWT_SECRET")
    os.environ["VERCEL"] = "1"
    os.environ["JWT_SECRET"] = "a-real-login-key-for-this-test"          # Vercel always has one
    OWNV = auth.create_access_token({"sub": "o@burger.fr", "role": "business_owner", "tenant_id": "t1"})
    saved_k = os.environ.pop("POS_TOKENS_SECRET", None)
    st = http("GET", "/api/owner/pos", bearer=OWNV).json()
    check("on Vercel without POS_TOKENS_SECRET → Square is « bientôt », never sealed with the login key",
          not next(p for p in st["providers"] if p["name"] == "square")["configured"])
    check("…and connect refuses (409)", http("POST", "/api/owner/pos/square/connect", bearer=OWNV).status_code == 409)
    os.environ["POS_TOKENS_SECRET"] = "a-separate-secret-for-caisse-tokens"
    check("with its own key → offered", next(p for p in http("GET", "/api/owner/pos", bearer=OWNV).json()["providers"] if p["name"] == "square")["configured"])
    os.environ.pop("VERCEL")
    os.environ.pop("POS_TOKENS_SECRET")
    if saved_jwt is None:
        os.environ.pop("JWT_SECRET")
    else:
        os.environ["JWT_SECRET"] = saved_jwt
    if saved_k:
        os.environ["POS_TOKENS_SECRET"] = saved_k

    print("\nDisconnecting")
    check("a manager cannot disconnect", http("DELETE", f"/api/owner/pos/connections/{CID}", bearer=MAN).status_code == 403)
    check("another business cannot", http("DELETE", f"/api/owner/pos/connections/{CID}", bearer=OWN3).status_code == 404)
    square["deleted"].clear()
    mine = {l["provider_customer_id"] for l in db.pos_customer_links.find({"conn_id": CID, "origin": "pushed"})}
    r = http("DELETE", f"/api/owner/pos/connections/{CID}", bearer=OWN)
    c = db.pos_connections.find_one({"id": CID})
    check("« Déconnecter » stops at once: status disconnecting", r.status_code == 200 and c["status"] == "disconnecting")
    hook(pay_obj("AFTER1", amount=500, cust="SQ-c4"))
    check("after disconnecting, a sale changes nothing", not db.visits.find_one({"external_id": "square:AFTER1"}))
    check("the page no longer offers it as connected", all(x["status"] != "connected" for x in http("GET", "/api/owner/pos", bearer=OWN).json()["connections"]))
    P.run_due(now)
    c = db.pos_connections.find_one({"id": CID})
    check("the tick removes from Square every customer FidClic made", mine and mine <= set(square["deleted"]))
    check("…then tells Square, wipes the tokens and keeps the history",
          square["revoked"] and c["status"] == "disconnected" and not c.get("tokens_sealed")
          and db.pos_customer_links.count_documents({"conn_id": CID}) == 0)
    check("the past tickets and visits stay", db.visits.find_one({"external_id": "square:P1"}) is not None)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
