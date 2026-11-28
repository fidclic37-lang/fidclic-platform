"""
Square plug against Square's REAL sandbox (fake money, the owner's own test
shop) — checks that services/pos/square.py reads what Square really sends,
not only what the tests' fake sends.

    SQUARE_ENV_FILE=~/Desktop/website_antiG/.secrets/square-sandbox.env \
        python3 -I scripts/square_sandbox_check.py

It: reads the test shop and its locations → pushes one test card as a Square
customer (name + card code) → pays 4,20 € in the sandbox with that customer
(Square's test card nonce) → finds the sale in the nightly list → reads the
card code back from the customer → refunds it → finds the refund. Prints
what it saw; never prints a token. Sandbox only: refuses production.
"""
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))


def load_env(path):
    for ln in open(os.path.expanduser(path), encoding="utf-8"):
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main():
    load_env(os.environ.get("SQUARE_ENV_FILE") or "~/Desktop/website_antiG/.secrets/square-sandbox.env")
    if (os.environ.get("SQUARE_ENV") or "sandbox").lower() != "sandbox":
        sys.exit("sandbox only")
    os.environ.pop("SQUARE_API_BASE", None)
    from services.pos.square import SquareAdapter
    from services.pos.base import PosError
    sq = SquareAdapter()
    tok = os.environ["SQUARE_ACCESS_TOKEN"]
    ok = True

    def say(label, cond, extra=""):
        nonlocal ok
        ok &= bool(cond)
        print(("  ✓ " if cond else "  ✗ ") + label + (f"  ({extra})" if extra else ""))

    name = sq.merchant_name(tok)
    locs = sq.list_locations(tok)
    say("test shop read", bool(name), name)
    say("locations read", bool(locs), ", ".join(f"{l['name']} [{l['currency']}]" for l in locs))
    loc = locs[0]["id"]

    code = "FT-SBX" + uuid.uuid4().hex[:6].upper()
    ref = f"https://app.fidclic.com/card/{code}"
    made = sq.push_customers(tok, [{"fidclic_id": "sandbox-check", "reference_id": ref, "given_name": "Test", "family_name": "FidClic"}])
    cust = made.get("sandbox-check")
    say("one card pushed as a Square customer", bool(cust))
    say("its reference id read back = the card's code", sq.customer_reference(tok, cust) == ref)

    begin = datetime.now(timezone.utc) - timedelta(minutes=2)
    st, body = sq.http("POST", "/v2/payments", token=tok, json={
        "source_id": "cnon:card-nonce-ok", "idempotency_key": uuid.uuid4().hex, "customer_id": cust, "location_id": loc,
        "amount_money": {"amount": 420, "currency": locs[0].get("currency") or "EUR"}})
    pay = (body or {}).get("payment") or {}
    say("sandbox payment made (4,20)", st == 200 and pay.get("id"), f"HTTP {st} {pay.get('status')}")
    ticket = sq._sale(pay)
    say("the payment read as a sale ticket", ticket and ticket["amount"] == 4.2 and ticket["customer_id"] == cust)

    found = None
    for _ in range(6):
        ts = sq.list_tickets(tok, [loc], begin, datetime.now(timezone.utc) + timedelta(minutes=1))
        found = next((t for t in ts if t["ticket_id"] == pay.get("id")), None)
        if found:
            break
        time.sleep(2)
    say("the nightly list finds it, with its customer", found and found["customer_id"] == cust)

    import re
    m = re.search(r"(FT-[A-Z0-9]+)", sq.customer_reference(tok, cust) or "", re.I)
    say("the card code comes back from the sale's customer", m and m.group(1).upper() == code)

    st, body = sq.http("POST", "/v2/refunds", token=tok, json={
        "idempotency_key": uuid.uuid4().hex, "payment_id": pay.get("id"), "amount_money": {"amount": 420, "currency": locs[0].get("currency") or "EUR"}})
    rf = (body or {}).get("refund") or {}
    say("sandbox refund made", st == 200 and rf.get("id"), f"HTTP {st} {rf.get('status')}")
    got = None
    for _ in range(10):
        ts = sq.list_tickets(tok, [loc], begin, datetime.now(timezone.utc) + timedelta(minutes=1))
        got = next((t for t in ts if t["kind"] == "refund" and t["refund_of"] == pay.get("id")), None)
        if got:
            break
        time.sleep(3)
    say("the refund found (COMPLETED) and points at its sale", got is not None,
        "still PENDING in the sandbox" if got is None else f"{got['amount']} {got['currency']}")
    try:
        sq.http("DELETE", f"/v2/customers/{cust}", token=tok)
    except PosError:
        pass
    print("\nOK" if ok else "\nSOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
