"""
Caisse connector — the Square plug alone (services/pos/square.py): the
connect link, the webhook signature, reading Square's payments and refunds
into FidClic's one ticket shape, the customer push (name + card code only)
and the paging of the nightly check. No database, no network: Square's HTTP
answers are played by a fake.

Run: cd api && /usr/local/bin/python3 tests/test_pos_square_adapter.py
"""
import base64
import datetime as dt
import hashlib
import hmac
import os
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.update(SQUARE_ENV="sandbox", SQUARE_APPLICATION_ID="sandbox-sq0idb-TESTAPP",
                  SQUARE_APPLICATION_SECRET="sandbox-sq0csb-TESTSECRET", SQUARE_WEBHOOK_SIGNATURE_KEY="whkey-123")

from services.pos import square as SQ  # noqa: E402
from services.pos import base as B  # noqa: E402

passed = failed = 0


def check(label, cond):
    global passed, failed
    passed += bool(cond)
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def pay(status="COMPLETED", amount=1250, tip=0, cur="EUR", cust="SQCUST1", loc="LOC1", pid="PAY1", **extra):
    p = {"id": pid, "status": status, "amount_money": {"amount": amount, "currency": cur},
         "tip_money": {"amount": tip, "currency": cur}, "total_money": {"amount": amount + tip, "currency": cur},
         "location_id": loc, "created_at": "2026-11-28T10:15:00.000Z", "updated_at": "2026-11-28T10:15:02.000Z"}
    if cust:
        p["customer_id"] = cust
    p.update(extra)
    return {"merchant_id": "MERCH1", "type": "payment.updated", "event_id": "ev-" + pid + status,
            "created_at": "2026-11-28T10:15:03Z", "data": {"type": "payment", "id": pid, "object": {"payment": p}}}


def refund(status="COMPLETED", amount=1250, rid="REF1", pid="PAY1"):
    r = {"id": rid, "status": status, "amount_money": {"amount": amount, "currency": "EUR"}, "payment_id": pid,
         "location_id": "LOC1", "created_at": "2026-11-28T11:00:00Z"}
    return {"merchant_id": "MERCH1", "type": "refund.updated", "event_id": "ev-" + rid + status,
            "created_at": "2026-11-28T11:00:01Z", "data": {"type": "refund", "id": rid, "object": {"refund": r}}}


sq = SQ.SquareAdapter()

print("\nSetup")
check("configured from the environment", sq.configured())
check("sandbox host in sandbox", sq.base == "https://connect.squareupsandbox.com")
os.environ["SQUARE_ENV"] = "production"
check("production host when SQUARE_ENV=production", SQ.SquareAdapter().base == "https://connect.squareup.com")
os.environ["SQUARE_API_BASE"] = "http://127.0.0.1:9"
check("a local stand-in is never used in production", SQ.SquareAdapter().base == "https://connect.squareup.com")
os.environ["SQUARE_ENV"] = "sandbox"
check("…but is used in sandbox (the e2e journey)", SQ.SquareAdapter().base == "http://127.0.0.1:9")
os.environ.pop("SQUARE_API_BASE")
saved = os.environ.pop("SQUARE_APPLICATION_SECRET")
check("no secret → not configured (the page says « bientôt », never a broken button)", not SQ.SquareAdapter().configured())
os.environ["SQUARE_APPLICATION_SECRET"] = saved

print("\nConnect link")
u = urlsplit(sq.authorize_url("STATE-abc"))
q = parse_qs(u.query)
check("Square's own authorize page", u.scheme == "https" and u.netloc == "connect.squareupsandbox.com" and u.path == "/oauth2/authorize")
check("our app id and the one-use state", q.get("client_id") == ["sandbox-sq0idb-TESTAPP"] and q.get("state") == ["STATE-abc"])
scopes = set((q.get("scope") or [""])[0].split(" "))
check("asks what PR 1 uses: payments, orders, customers, merchant profile",
      {"PAYMENTS_READ", "CUSTOMERS_READ", "CUSTOMERS_WRITE", "MERCHANT_PROFILE_READ", "ORDERS_READ"} <= scopes)
check("asks nothing it does not use (no payments write, no bank, no employees)",
      not ({"PAYMENTS_WRITE", "BANK_ACCOUNTS_READ", "EMPLOYEES_READ", "EMPLOYEES_WRITE", "SETTLEMENTS_READ"} & scopes))
check("session=false: the owner logs in to their own Square, not a kept session", q.get("session") == ["false"])
check("the secret never travels in the link", "TESTSECRET" not in sq.authorize_url("x"))

print("\nWebhook signature")
URL = "https://app.fidclic.com/api/pos/square/webhook"
body = b'{"event_id":"e1","merchant_id":"MERCH1"}'
good = base64.b64encode(hmac.new(b"whkey-123", URL.encode() + body, hashlib.sha256).digest()).decode()
check("Square's signature accepted", sq.verify_webhook(good, body, URL))
check("one byte changed in the body → refused", not sq.verify_webhook(good, body.replace(b"e1", b"e2"), URL))
check("signed for another address → refused", not sq.verify_webhook(good, body, URL + "x"))
check("no signature → refused", not sq.verify_webhook("", body, URL))
check("garbage signature → refused", not sq.verify_webhook("abc%%%", body, URL))
kept = os.environ.pop("SQUARE_WEBHOOK_SIGNATURE_KEY")
check("no signature key set → everything refused (never open by default)", not SQ.SquareAdapter().verify_webhook(good, body, URL))
os.environ["SQUARE_WEBHOOK_SIGNATURE_KEY"] = kept

print("\nReading a payment")
ev = sq.parse_event(pay())
t = ev["ticket"]
check("event id and merchant read", ev["event_id"] == "ev-PAY1COMPLETED" and ev["merchant_id"] == "MERCH1")
check("a completed payment is a sale ticket", t["kind"] == "sale" and t["ticket_id"] == "PAY1" and t["provider"] == "square")
check("amount in euros from cents", t["amount"] == 12.5 and t["currency"] == "EUR")
check("the tip is not counted as a purchase", sq.parse_event(pay(amount=1000, tip=200))["ticket"]["amount"] == 10.0)
check("location and Square customer kept", t["location_id"] == "LOC1" and t["customer_id"] == "SQCUST1")
check("time read as UTC", t["at"] == dt.datetime(2026, 11, 28, 10, 15, tzinfo=dt.timezone.utc))
check("no customer on the sale → customer None (an unscanned ticket)", sq.parse_event(pay(cust=None))["ticket"]["customer_id"] is None)
for st in ("APPROVED", "PENDING", "FAILED", "CANCELED"):
    check(f"a {st} payment is not a sale yet (ticket None)", sq.parse_event(pay(status=st))["ticket"] is None)
check("zero amount kept as 0", sq.parse_event(pay(amount=0))["ticket"]["amount"] == 0.0)
noamt = pay()
noamt["data"]["object"]["payment"].pop("amount_money")
check("no amount_money → 0, never a crash", sq.parse_event(noamt)["ticket"]["amount"] == 0.0)
check("zero-decimal currency (JPY) not divided by 100", sq.parse_event(pay(amount=500, cur="JPY"))["ticket"]["amount"] == 500.0)
check("an unknown event type → no ticket", sq.parse_event({"type": "inventory.count.updated", "event_id": "x", "merchant_id": "M"})["ticket"] is None)
check("an empty body → no ticket, no crash", sq.parse_event({})["ticket"] is None)
check("a body that is not an object → no ticket", sq.parse_event([])["ticket"] is None)

print("\nReading a refund")
r = sq.parse_event(refund())["ticket"]
check("a completed refund points at its payment", r["kind"] == "refund" and r["refund_of"] == "PAY1" and r["amount"] == 12.5)
check("a pending refund is nothing yet", sq.parse_event(refund(status="PENDING"))["ticket"] is None)
check("a rejected refund is nothing", sq.parse_event(refund(status="REJECTED"))["ticket"] is None)

print("\nTokens")
calls = []


def fake(method, path, token=None, json=None, params=None, client_auth=False):
    calls.append({"method": method, "path": path, "token": token, "json": json, "params": params, "client_auth": client_auth})
    if path == "/oauth2/token":
        if (json or {}).get("code") == "bad":
            return 401, {"errors": [{"code": "UNAUTHORIZED"}]}
        return 200, {"access_token": "EAAA-acc", "refresh_token": "EQAA-ref", "expires_at": "2026-12-28T10:00:00Z",
                     "merchant_id": "MERCH1", "token_type": "bearer"}
    if path == "/oauth2/revoke":
        return 200, {"success": True}
    if path == "/v2/merchants/me":
        return 200, {"merchant": {"id": "MERCH1", "business_name": "Burger Lumière", "country": "FR", "currency": "EUR"}}
    if path == "/v2/locations":
        return 200, {"locations": [{"id": "LOC1", "name": "Tours centre", "currency": "EUR", "country": "FR", "status": "ACTIVE"},
                                   {"id": "LOC2", "name": "Tours nord", "currency": "EUR", "country": "FR", "status": "ACTIVE"}]}
    if path == "/v2/customers/SQCUST1":
        return 200, {"customer": {"id": "SQCUST1", "reference_id": "https://app.fidclic.com/card/FT-AB12CD"}}
    if path.startswith("/v2/customers/") and method == "GET":
        return 404, {"errors": [{"code": "NOT_FOUND"}]}
    if path == "/v2/customers/bulk-create":
        out = {}
        for k, v in (json or {}).get("customers", {}).items():
            out[k] = {"customer": {"id": "SQ-" + k, "reference_id": v.get("reference_id")}} if k != "boom" else {"errors": [{"code": "BAD"}]}
        return 200, {"responses": out}
    if path == "/v2/payments":
        if not (params or {}).get("cursor"):
            return 200, {"payments": [pay(pid="P1")["data"]["object"]["payment"],
                                      pay(pid="P2", status="FAILED")["data"]["object"]["payment"]], "cursor": "c2"}
        return 200, {"payments": [pay(pid="P3")["data"]["object"]["payment"]]}
    if path == "/v2/refunds":
        return 200, {"refunds": [refund(rid="R1", pid="P1")["data"]["object"]["refund"]]}
    return 404, {}


sq.http = fake
tok = sq.exchange_code("good")
check("code exchanged: access, refresh, expiry and merchant", tok["access_token"] == "EAAA-acc" and tok["refresh_token"] == "EQAA-ref"
      and tok["merchant_id"] == "MERCH1" and tok["expires_at"].year == 2026)
sent = calls[-1]["json"]
check("the exchange sends our secret to Square only (server to server)", sent["client_secret"] == "sandbox-sq0csb-TESTSECRET"
      and sent["grant_type"] == "authorization_code")
try:
    sq.exchange_code("bad")
    check("a refused code raises PosError", False)
except B.PosError as e:
    check("a refused code raises PosError with Square's reason", "UNAUTHORIZED" in str(e))
tok2 = sq.refresh("EQAA-ref")
check("refresh uses the refresh token", calls[-1]["json"]["grant_type"] == "refresh_token" and tok2["access_token"] == "EAAA-acc")
check("revoke answers True", sq.revoke("EAAA-acc") is True and calls[-1]["client_auth"] is True)

print("\nShop and locations")
check("the Square shop's name", sq.merchant_name("EAAA-acc") == "Burger Lumière")
locs = sq.list_locations("EAAA-acc")
check("both locations, id + name", [l["id"] for l in locs] == ["LOC1", "LOC2"] and locs[0]["name"] == "Tours centre")

print("\nCustomers")
check("a Square customer's reference id read", sq.customer_reference("EAAA-acc", "SQCUST1") == "https://app.fidclic.com/card/FT-AB12CD")
check("an unknown Square customer → None", sq.customer_reference("EAAA-acc", "NOPE") is None)
check("no customer id → None, no call", sq.customer_reference("EAAA-acc", "") is None)
calls.clear()
out = sq.push_customers("EAAA-acc", [{"fidclic_id": "c1", "reference_id": "https://app.fidclic.com/card/FT-1", "given_name": "Inès", "family_name": "Fontaine"},
                                     {"fidclic_id": "boom", "reference_id": "x", "given_name": "B", "family_name": ""}])
check("created customers mapped back to FidClic ids", out == {"c1": "SQ-c1"})
body = calls[-1]["json"]["customers"]["c1"]
check("only name + card code go to Square (no phone, no e-mail, no birthday)",
      set(body) <= {"given_name", "family_name", "reference_id", "note"} and body["reference_id"].endswith("FT-1"))
calls.clear()
many = [{"fidclic_id": f"c{i}", "reference_id": f"r{i}", "given_name": "X", "family_name": ""} for i in range(250)]
out = sq.push_customers("EAAA-acc", many)
check("250 customers sent in batches of at most 100", len(calls) == 3 and all(len(c["json"]["customers"]) <= 100 for c in calls) and len(out) == 250)
check("an empty list sends nothing", sq.push_customers("EAAA-acc", []) == {} )

print("\nNightly check: every page, only finished sales and refunds")
since = dt.datetime(2026, 11, 27, tzinfo=dt.timezone.utc)
calls.clear()
ts = sq.list_tickets("EAAA-acc", ["LOC1"], since, since + dt.timedelta(days=1))
ids = [(t["kind"], t["ticket_id"]) for t in ts]
check("both pages read, the FAILED one left out", ("sale", "P1") in ids and ("sale", "P3") in ids and ("sale", "P2") not in ids)
check("completed refunds included", ("refund", "R1") in ids)
pcalls = [c for c in calls if c["path"] == "/v2/payments"]
check("asked per location, with the time window", pcalls[0]["params"]["location_id"] == "LOC1" and pcalls[0]["params"]["begin_time"].startswith("2026-11-27"))
check("no location → nothing asked, nothing returned", sq.list_tickets("EAAA-acc", [], since, since) == [])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
