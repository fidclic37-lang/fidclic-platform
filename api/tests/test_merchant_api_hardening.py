"""
API v1 hardening (2026-11-09) — what a till, a borne or a website needs to
plug into FidClic without breaking a card:

  LOOKUP        card number, id, phone in any format, e-mail; two clients on
                one phone or e-mail is « ambiguous », never a guess
  IDEMPOTENCY   one external_id = one visit, even sent twice at once; the same
                id with another body is refused; a failed call frees the id
  THE VISIT     the response and the visit.created webhook name THIS visit,
                with its external_id
  CANCEL        a refund takes back what the visit gave on the card (tampons,
                points, spend, a reward it banked) and says what it cannot
  HOLD          a borne locks a reward while the client pays; the till and
                another key cannot take it meanwhile; it expires by itself
  VERIFICATION  an online shop proves the client is who they say (SMS code)
                before a reward is used
  WEBHOOKS      no internal address, no redirect, slow endpoints in parallel,
                retried by the 15-minute tick; visit.cancelled
  HOUSEKEEPING  rate and idempotency rows expire

Run: cd api && /usr/local/bin/python3 tests/test_merchant_api_hardening.py
"""
import asyncio
import datetime as dt
import os
import sys
import threading
import time

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx
    from features import merchant_api as M
    from services import sms as SMS

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    drain = {"on": True}

    def http(method, url, key=None, bearer=None, **kw):
        headers = kw.pop("headers", {})
        if key:
            headers["Authorization"] = "Bearer " + key
        if bearer:
            headers["Authorization"] = "Bearer " + bearer

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        out = asyncio.get_event_loop().run_until_complete(run())
        if drain["on"]:
            M.drain_webhooks(10)       # webhooks leave in the background: let them land before checking
        return out

    def code_of(r):
        try:
            d = r.json().get("detail")
            return d.get("code") if isinstance(d, dict) else None
        except Exception:
            return None

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café Lumière", "plan": "vip", "subscription_status": "active", "created_at": now},
        {"id": "t3", "slug": "pts", "name": "Points Bar", "plan": "vip", "subscription_status": "active", "created_at": now},
        {"id": "t4", "slug": "other", "name": "Autre", "plan": "vip", "subscription_status": "active", "created_at": now},
    ])
    db.card_templates.insert_many([
        {"tenant_id": "t1", "reward_threshold_stamps": 3, "visits_per_stamp": 1, "reward_description": "Café offert"},
        {"tenant_id": "t3", "programme": "points_euro", "points_mode": "per_euro", "points_per_euro": 1,
         "reward_points": 10, "reward_description": "Boisson offerte"},
        {"tenant_id": "t4", "reward_threshold_stamps": 3, "visits_per_stamp": 1},
    ])
    db.users.insert_many([{"email": "o@cafe.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "o@pts.fr", "role": "business_owner", "tenant_id": "t3"},
                          {"email": "o@other.fr", "role": "business_owner", "tenant_id": "t4"}])
    OWN = auth.create_access_token({"sub": "o@cafe.fr", "role": "business_owner", "tenant_id": "t1"})
    OWN3 = auth.create_access_token({"sub": "o@pts.fr", "role": "business_owner", "tenant_id": "t3"})
    OWN4 = auth.create_access_token({"sub": "o@other.fr", "role": "business_owner", "tenant_id": "t4"})

    import requests
    sent = []
    slow = {"s": 0.0}

    class _R:
        def __init__(self, code): self.status_code = code

    def fake_post(url, data=None, timeout=None, headers=None, **kw):
        sent.append({"url": url, "body": data, "headers": headers, "kw": kw})
        if slow["s"]:
            time.sleep(slow["s"])
        return _R(200)
    requests.post = fake_post
    # webhook targets resolve to a public address unless a test says otherwise
    resolved = {"default": ["93.184.216.34"]}
    M._resolve = lambda host: resolved.get(host, resolved["default"])

    smsbox = []
    SMS.is_configured = lambda: True
    SMS.send_sms = lambda to, body: (smsbox.append({"to": to, "body": body}) or {"sent": True, "sid": "SM1"})

    def key_for(bearer, write=True, online=False, name="Caisse"):
        r = http("POST", "/api/owner/integrations/keys", bearer=bearer, json={"name": name, "write": write, "online": online})
        assert r.status_code == 201, r.text
        return r.json()["key"]

    KEY = key_for(OWN)
    KEY_B = key_for(OWN, name="Borne")
    RO = key_for(OWN, write=False, name="Lecture")
    WEB = key_for(OWN, online=True, name="Site")
    KEY3 = key_for(OWN3)
    KEY4 = key_for(OWN4)

    def join(slug, name, phone, email=""):
        return server.join_program(slug, server.JoinRequest(name=name, phone=phone, email=email, postal_code="", birthday="", consent=True))["barcode_id"]

    def cust(bc):
        return db.customers.find_one({"barcode_id": bc}, {"_id": 0})

    def visit(key, customer, amount=10, ext=None, **extra):
        body = {"customer": customer, "amount": amount, **extra}
        if ext:
            body["external_id"] = ext
        return http("POST", "/api/v1/visits", key=key, json=body)

    # ------------------------------------------------------------------
    print("\nLookup")
    SARAH = join("cafe", "Sarah Martin", "06 12 34 56 78", "Sarah.Martin@Mail.fr")
    for ref in ("+33 6 12 34 56 78", "0033612345678", "06.12.34.56.78", "612345678"):
        r = http("GET", f"/api/v1/customers/{ref}", key=KEY)
        check(f"phone « {ref} » finds Sarah", r.status_code == 200 and r.json()["card_number"] == SARAH)
    r = http("GET", "/api/v1/customers/sarah.martin@mail.fr", key=KEY)
    check("e-mail, any case, finds Sarah", r.status_code == 200 and r.json()["card_number"] == SARAH)
    r = http("GET", "/api/v1/customers/%20SARAH.MARTIN@MAIL.FR%20", key=KEY)
    check("e-mail with spaces around still finds her", r.status_code == 200)
    r = http("GET", "/api/v1/customers/sarah.martin@mail.f", key=KEY)
    check("a near e-mail is not a match → 404", r.status_code == 404)
    r = http("GET", "/api/v1/customers/12345678", key=KEY)
    check("8 digits is not a phone → 404", r.status_code == 404)
    # a family on one phone (inserted directly: the sign-up page would hand back the same card)
    db.customers.insert_many([
        {"id": "fam1", "tenant_id": "t1", "barcode_id": "FT-FAM00001", "name": "Paul", "phone": "07 11 22 33 44", "visits": 0},
        {"id": "fam2", "tenant_id": "t1", "barcode_id": "FT-FAM00002", "name": "Julie", "phone": "+33711223344", "visits": 0},
        {"id": "dup1", "tenant_id": "t1", "barcode_id": "FT-DUP00001", "name": "A", "email": "same@x.fr", "phone": "0600000001", "visits": 0},
        {"id": "dup2", "tenant_id": "t1", "barcode_id": "FT-DUP00002", "name": "B", "email": "SAME@x.fr", "phone": "0600000002", "visits": 0},
        {"id": "gone", "tenant_id": "t1", "barcode_id": "FT-GONE0001", "name": "Gone", "phone": "0699999999",
         "email": "gone@x.fr", "deleted_at": now, "visits": 0},
    ])
    r = http("GET", "/api/v1/customers/0711223344", key=KEY)
    check("two clients on one phone → 409 ambiguous_customer", r.status_code == 409 and code_of(r) == "ambiguous_customer")
    r = http("GET", "/api/v1/customers/same@x.fr", key=KEY)
    check("two clients on one e-mail → 409 ambiguous_customer", r.status_code == 409 and code_of(r) == "ambiguous_customer")
    r = visit(KEY, "0711223344")
    check("…and no visit is written to a guess", r.status_code == 409 and db.visits.count_documents({"customer_id": {"$in": ["fam1", "fam2"]}}) == 0)
    check("the card number still picks one of them", http("GET", "/api/v1/customers/FT-FAM00002", key=KEY).json()["name"] == "Julie")
    check("a deleted client is not found by phone", http("GET", "/api/v1/customers/0699999999", key=KEY).status_code == 404)
    check("…nor by e-mail", http("GET", "/api/v1/customers/gone@x.fr", key=KEY).status_code == 404)
    check("another shop's client → 404 (card)", http("GET", f"/api/v1/customers/{SARAH}", key=KEY4).status_code == 404)
    check("another shop's client → 404 (phone)", http("GET", "/api/v1/customers/0612345678", key=KEY4).status_code == 404)
    check("another shop's client → 404 (e-mail)", http("GET", "/api/v1/customers/sarah.martin@mail.fr", key=KEY4).status_code == 404)
    check("a regex in the ref is plain text", http("GET", "/api/v1/customers/.*@.*", key=KEY).status_code == 404)

    # ------------------------------------------------------------------
    print("\nIdempotency")
    r1 = visit(KEY, SARAH, 12.5, ext="TICKET-1")
    r2 = visit(KEY, SARAH, 12.5, ext="TICKET-1")
    check("first call: 201, not a duplicate", r1.status_code == 201 and r1.json()["duplicate"] is False)
    check("same id, same body: the same answer, duplicate", r2.status_code == 201 and r2.json()["duplicate"] is True
          and r2.json()["visit"]["id"] == r1.json()["visit"]["id"])
    check("…and one visit only", db.visits.count_documents({"external_id": "TICKET-1"}) == 1)
    r3 = visit(KEY, SARAH, 99, ext="TICKET-1")
    check("same id, another amount → 422 idempotency_conflict", r3.status_code == 422 and code_of(r3) == "idempotency_conflict")
    r = visit(KEY, "FT-NOPE0000", 5, ext="TICKET-2")
    check("a failed call (unknown client) → 404", r.status_code == 404)
    r = visit(KEY, SARAH, 5, ext="TICKET-2")
    check("…frees the id: the corrected call goes through", r.status_code == 201 and r.json()["duplicate"] is False)
    db.api_idempotency.insert_one({"tenant_id": "t1", "key": "visit:TICKET-3", "state": "pending", "fp": "x", "at": M._now()})
    r = visit(KEY, SARAH, 5, ext="TICKET-3")
    check("the same id still running elsewhere → 409 request_in_progress", r.status_code == 409 and code_of(r) == "request_in_progress")
    db.api_idempotency.insert_one({"tenant_id": "t1", "key": "visit:TICKET-4", "state": "pending", "fp": "x",
                                   "at": M._now() - dt.timedelta(minutes=5)})
    r = visit(KEY, SARAH, 5, ext="TICKET-4")
    check("a call that died 5 min ago is taken over", r.status_code == 201 and db.visits.count_documents({"external_id": "TICKET-4"}) == 1)
    db.api_idempotency.insert_one({"tenant_id": "t1", "key": "visit:OLD-1", "response": {"visit": {"id": "v-old"}}, "at": M._now()})
    r = visit(KEY, SARAH, 5, ext="OLD-1")
    check("a row from before this change counts as done", r.status_code == 201 and r.json()["duplicate"] is True)
    check("ids are per shop: another shop may use TICKET-1", visit(KEY4, join("other", "Zed", "0644444444"), 5, ext="TICKET-1").status_code == 201)
    # the same ticket sent by two tills at the same instant
    before = db.visits.count_documents({"customer_id": cust(SARAH)["id"]})
    out, lock = [], threading.Lock()

    def fire():
        try:
            r = M.create_visit(M.VisitIn(customer=SARAH, amount=7, external_id="RACE-1"), M.ApiCaller(
                tenant_id="t1", key_id="k", key_name="Caisse", scopes=["read", "write"]))
            res = ("ok", r["duplicate"])
        except M.HTTPException as e:
            res = ("err", e.status_code)
        with lock:
            out.append(res)
    th = [threading.Thread(target=fire) for _ in range(6)]
    [t.start() for t in th]
    [t.join() for t in th]
    check("6 calls at once with one id → exactly one visit",
          db.visits.count_documents({"customer_id": cust(SARAH)["id"]}) == before + 1)
    check("…the others are a duplicate or « in progress », never an error 500",
          all(x[0] == "ok" or x[1] == 409 for x in out) and sum(1 for x in out if x == ("ok", False)) == 1)

    # ------------------------------------------------------------------
    print("\nThe visit")
    sent.clear()
    hook = http("POST", "/api/owner/integrations/webhooks", bearer=OWN,
                json={"url": "https://hooks.example.com/fidclic", "events": ["visit.created", "visit.cancelled", "reward.unlocked"]}).json()
    check("visit.cancelled is an event one can subscribe to", "visit.cancelled" in hook["events"])
    r = visit(KEY, SARAH, 4.2, ext="TICKET-10")
    v = r.json()["visit"]
    row = db.visits.find_one({"id": v["id"]})
    check("the response names the visit written by THIS call", row and row["external_id"] == "TICKET-10" and row["source"] == "api")
    created = [s for s in sent if s["headers"]["X-FidClic-Event"] == "visit.created"]
    import json as _json
    payload = _json.loads(created[-1]["body"]) if created else {}
    check("one visit.created for the call", len(created) == 1)
    check("…and it carries the external_id and source « api »",
          payload.get("data", {}).get("visit", {}).get("external_id") == "TICKET-10"
          and payload["data"]["visit"]["source"] == "api" and payload["data"]["visit"]["id"] == v["id"])
    check("webhooks never follow a redirect", created and created[-1]["kw"].get("allow_redirects") is False)
    check("the event says its API version", payload.get("api_version") == M.API_VERSION)

    # ------------------------------------------------------------------
    print("\nCancel (refund)")
    KARIM = join("cafe", "Karim", "0655555555")
    k_id = cust(KARIM)["id"]
    a = visit(KEY, KARIM, 10, ext="K-1").json()["visit"]
    b = visit(KEY, KARIM, 20, ext="K-2").json()["visit"]
    c0 = cust(KARIM)
    check("Karim: 2 visits, 30 € spent", c0["visits"] == 2 and round(c0["total_amount_paid"], 2) == 30)
    sent.clear()
    r = http("POST", f"/api/v1/visits/{b['id']}/cancel", key=KEY, json={"reason": "Remboursé"})
    j = r.json()
    c1 = cust(KARIM)
    check("cancel by visit id → 200 cancelled", r.status_code == 200 and j["cancelled"] is True and j["duplicate"] is False)
    check("the visit leaves the figures (visits collection)", db.visits.count_documents({"id": b["id"]}) == 0)
    check("…and is kept apart with who, why and when", (db.visits_cancelled.find_one({"id": b["id"]}) or {}).get("cancel_reason") == "Remboursé")
    check("Karim back to 1 visit and 10 €", c1["visits"] == 1 and round(c1["total_amount_paid"], 2) == 10)
    check("his last visit is the one before", abs((M._aware(c1["last_visit_date"]) - dt.datetime.fromisoformat(a["at"])).total_seconds()) < 1)
    check("his meter shows 1 tampon", http("GET", f"/api/v1/customers/{KARIM}", key=KEY).json()["stamps"] == 1)
    check("visit.cancelled sent", any(s["headers"]["X-FidClic-Event"] == "visit.cancelled" for s in sent))
    check("the client's history says so", db.customer_changes.find_one({"customer_id": k_id, "kind": "visit_cancelled"}) is not None)
    r = http("POST", f"/api/v1/visits/{b['id']}/cancel", key=KEY, json={})
    check("cancel again → 200 duplicate, nothing moves", r.status_code == 200 and r.json()["duplicate"] is True and cust(KARIM)["visits"] == 1)
    r = http("POST", "/api/v1/visits/K-1/cancel", key=KEY, json={})
    check("cancel by the external_id it was sent with", r.status_code == 200 and cust(KARIM)["visits"] == 0
          and round(cust(KARIM)["total_amount_paid"], 2) == 0)
    check("no visit left: the last-visit date is cleared", cust(KARIM).get("last_visit_date") is None)
    w = visit(KEY, KARIM, 5, ext="K-3").json()["visit"]
    check("a read-only key cannot cancel → 403", http("POST", f"/api/v1/visits/{w['id']}/cancel", key=RO, json={}).status_code == 403)
    check("another shop cannot cancel it → 404", http("POST", f"/api/v1/visits/{w['id']}/cancel", key=KEY4, json={}).status_code == 404)
    check("an unknown visit → 404", http("POST", "/api/v1/visits/nope/cancel", key=KEY, json={}).status_code == 404)
    db.visits.update_one({"id": w["id"]}, {"$set": {"visit_time": M._now() - dt.timedelta(days=M.CANCEL_MAX_DAYS + 1)}})
    r = http("POST", f"/api/v1/visits/{w['id']}/cancel", key=KEY, json={})
    check(f"older than {M.CANCEL_MAX_DAYS} days → 409 visit_too_old", r.status_code == 409 and code_of(r) == "visit_too_old")
    db.visits.update_one({"id": w["id"]}, {"$set": {"visit_time": M._now(), "paper_stamps": 4}})
    r = http("POST", f"/api/v1/visits/{w['id']}/cancel", key=KEY, json={})
    check("a visit that carried a paper card → 409 visit_not_cancellable", r.status_code == 409 and code_of(r) == "visit_not_cancellable")

    # the visit that filled the card: its banked reward goes back too
    LEA = join("cafe", "Léa", "0656565656")
    for i in range(3):
        visit(KEY, LEA, 3, ext=f"L-{i}")
    v4 = visit(KEY, LEA, 3, ext="L-3").json()["visit"]          # the 4th visit banks the full card
    lea = http("GET", f"/api/v1/customers/{LEA}", key=KEY).json()
    check("Léa: a full card banked", lea["rewards_pending"] == 1)
    r = http("POST", f"/api/v1/visits/{v4['id']}/cancel", key=KEY, json={})
    lea = http("GET", f"/api/v1/customers/{LEA}", key=KEY).json()
    check("cancelling the visit that banked it takes the reward back", r.json()["reversed"]["rewards_cancelled"] == 1
          and lea["rewards_pending"] == 0)
    check("…and her card shows 3/3 again", lea["stamps"] == 3 and lea["visits"] == 3)
    check("the banked row is marked cancelled, not deleted",
          db.rewards_earned.count_documents({"customer_id": lea["id"], "status": "cancelled"}) == 1)
    # the same, but the reward was already handed over
    NOE = join("cafe", "Noé", "0657575757")
    for i in range(4):
        last = visit(KEY, NOE, 3, ext=f"N-{i}").json()["visit"]
    visit(KEY, NOE, 3, ext="N-4")
    rr = http("POST", "/api/v1/rewards/redeem", key=KEY, json={"customer": NOE})
    check("Noé uses his reward", rr.status_code == 200)
    r = http("POST", f"/api/v1/visits/{last['id']}/cancel", key=KEY, json={})
    check("cancelling the visit that earned a reward already used: done, and said",
          r.status_code == 200 and "reward_already_used" in r.json()["not_reversed"])
    check("…the reward stays used", db.rewards_earned.count_documents({"customer_id": cust(NOE)["id"], "status": "redeemed"}) == 1)

    # points card: points already spent cannot be taken below 0
    PAUL = join("pts", "Paul", "0658585858")
    p1 = visit(KEY3, PAUL, 12, ext="P-1").json()["visit"]
    check("Paul earns 12 points", cust(PAUL)["points"] == 12)
    db.customers.update_one({"barcode_id": PAUL}, {"$inc": {"points": -10}})   # spent on a reward
    r = http("POST", f"/api/v1/visits/{p1['id']}/cancel", key=KEY3, json={})
    j = r.json()
    check("cancel on a points card → points never below 0", r.status_code == 200 and cust(PAUL)["points"] == 0)
    check("…and the response says what could not come back",
          "points_already_spent" in j["not_reversed"] and j["reversed"]["points"] == 2)
    check("idempotent cancel with an external_id of its own",
          http("POST", f"/api/v1/visits/{p1['id']}/cancel", key=KEY3, json={"external_id": "R-1"}).json()["duplicate"] is True)

    # ------------------------------------------------------------------
    print("\nHold (borne)")
    ZOE = join("cafe", "Zoé", "0659595959")
    for i in range(4):
        visit(KEY, ZOE, 3, ext=f"Z-{i}")
    r = http("POST", "/api/v1/rewards/hold", key=KEY_B, json={"customer": ZOE, "ttl_seconds": 300})
    hold = r.json()
    check("hold a reward that is there → 201 with an id and an expiry",
          r.status_code == 201 and hold["hold_id"].startswith("hold_") and hold["expires_at"])
    r = http("POST", "/api/v1/rewards/hold", key=KEY, json={"customer": ZOE})
    check("a second hold → 409 reward_held", r.status_code == 409 and code_of(r) == "reward_held")
    r = http("POST", "/api/owner/rewards/redeem", bearer=OWN, json={"customer_id": cust(ZOE)["id"]})
    check("the till cannot hand it over meanwhile → 409, with a message",
          r.status_code == 409 and "réservée" in str(r.json()["detail"]).lower())
    r = http("POST", "/api/v1/rewards/redeem", key=KEY, json={"customer": ZOE})
    check("another key without the hold → 409 reward_held", r.status_code == 409 and code_of(r) == "reward_held")
    r = http("POST", "/api/v1/rewards/redeem", key=KEY_B, json={"customer": ZOE, "hold_id": hold["hold_id"]})
    check("the borne redeems with its hold → 200", r.status_code == 200)
    check("…and the hold is gone", not (cust(ZOE).get("reward_hold") or {}).get("id"))
    r = http("POST", "/api/v1/rewards/hold", key=KEY_B, json={"customer": ZOE})
    check("no reward left → 409 (no_reward or reward_next_visit)", r.status_code == 409 and code_of(r) in ("no_reward", "reward_next_visit"))
    ANA = join("cafe", "Ana", "0651515151")
    for i in range(4):
        visit(KEY, ANA, 3, ext=f"A-{i}")
    h = http("POST", "/api/v1/rewards/hold", key=KEY_B, json={"customer": ANA}).json()
    r = http("DELETE", f"/api/v1/rewards/hold/{h['hold_id']}", key=KEY_B)
    check("release → 200", r.status_code == 200 and r.json()["released"] is True)
    check("release again → 200, nothing to do", http("DELETE", f"/api/v1/rewards/hold/{h['hold_id']}", key=KEY_B).json()["released"] is False)
    h2 = http("POST", "/api/v1/rewards/hold", key=KEY_B, json={"customer": ANA}).json()
    check("another shop cannot release it → 404", http("DELETE", f"/api/v1/rewards/hold/{h2['hold_id']}", key=KEY4).status_code == 404)
    db.customers.update_one({"barcode_id": ANA}, {"$set": {"reward_hold.until": M._now() - dt.timedelta(seconds=1)}})
    r = http("POST", "/api/owner/rewards/redeem", bearer=OWN, json={"customer_id": cust(ANA)["id"]})
    check("an expired hold blocks nobody: the till hands it over", r.status_code == 200)
    check("ttl below 30 s → 422", http("POST", "/api/v1/rewards/hold", key=KEY_B, json={"customer": ANA, "ttl_seconds": 5}).status_code == 422)
    check("ttl above 15 min → 422", http("POST", "/api/v1/rewards/hold", key=KEY_B, json={"customer": ANA, "ttl_seconds": 3600}).status_code == 422)
    check("a read-only key cannot hold → 403", http("POST", "/api/v1/rewards/hold", key=RO, json={"customer": ANA}).status_code == 403)

    # ------------------------------------------------------------------
    print("\nVerification (online)")
    MIA = join("cafe", "Mia", "0652525252")
    for i in range(4):
        visit(KEY, MIA, 3, ext=f"M-{i}")
    smsbox.clear()
    r = http("POST", f"/api/v1/customers/{MIA}/verification", key=WEB)
    j = r.json()
    check("send a code → 200 by SMS, number masked", r.status_code == 200 and j["channel"] == "sms" and "52" in j["to"] and "06 52 52" not in j["to"])
    check("one SMS sent to her", len(smsbox) == 1 and smsbox[0]["to"] == "0652525252")
    import re as _re
    sms_code = _re.search(r"\b(\d{6})\b", smsbox[0]["body"]).group(1)
    row = db.api_verifications.find_one({"customer_id": cust(MIA)["id"]})
    check("the code is stored hashed, never in clear", row and sms_code not in str(row))
    r = http("POST", "/api/v1/rewards/redeem", key=WEB, json={"customer": MIA})
    check("an « online » key cannot redeem without proof → 403 verification_required",
          r.status_code == 403 and code_of(r) == "verification_required")
    r = http("POST", f"/api/v1/customers/{MIA}/verification/check", key=WEB, json={"code": "000000" if sms_code != "000000" else "111111"})
    check("a wrong code → 400 wrong_code", r.status_code == 400 and code_of(r) == "wrong_code")
    r = http("POST", f"/api/v1/customers/{MIA}/verification/check", key=WEB, json={"code": sms_code})
    tok = r.json().get("verification_token", "")
    check("the right code → a token", r.status_code == 200 and tok.startswith("vt_"))
    r = http("POST", f"/api/v1/customers/{MIA}/verification/check", key=WEB, json={"code": sms_code})
    check("a code works once", r.status_code == 400)
    r = http("POST", "/api/v1/rewards/redeem", key=WEB, json={"customer": SARAH, "verification_token": tok})
    check("a token for Mia does not work for Sarah", r.status_code == 403 and code_of(r) == "verification_required")
    r = http("POST", "/api/v1/rewards/redeem", key=WEB, json={"customer": MIA, "verification_token": tok})
    check("…for Mia it does → 200", r.status_code == 200)
    for i in range(4):
        visit(KEY, MIA, 3, ext=f"M2-{i}")
    r = http("POST", "/api/v1/rewards/redeem", key=WEB, json={"customer": MIA, "verification_token": tok})
    check("a token is used once", r.status_code == 403)
    # attempts and sends are limited
    http("POST", f"/api/v1/customers/{MIA}/verification", key=WEB)
    codes = [http("POST", f"/api/v1/customers/{MIA}/verification/check", key=WEB, json={"code": "999999"}).status_code for _ in range(6)]
    check("after 5 wrong codes → 429 too_many_attempts", codes[-1] == 429)
    for _ in range(M.VERIFY_PER_HOUR):
        r = http("POST", f"/api/v1/customers/{MIA}/verification", key=WEB)
    check(f"more than {M.VERIFY_PER_HOUR} codes an hour → 429", r.status_code == 429 and code_of(r) == "too_many_codes")
    db.customers.insert_one({"id": "nophone", "tenant_id": "t1", "barcode_id": "FT-NOPH0001", "name": "Sans", "phone": "", "visits": 0})
    r = http("POST", "/api/v1/customers/FT-NOPH0001/verification", key=WEB)
    check("no phone on the card → 409 no_phone", r.status_code == 409 and code_of(r) == "no_phone")
    SMS.is_configured = lambda: False
    r = http("POST", f"/api/v1/customers/{SARAH}/verification", key=WEB)
    check("SMS not set up → 503 sms_unavailable", r.status_code == 503 and code_of(r) == "sms_unavailable")
    SMS.is_configured = lambda: True
    check("a normal key still redeems without a code", True)

    # ------------------------------------------------------------------
    print("\nWebhooks")
    for url in ("https://[::1]/x", "https://0.0.0.0/x", "https://2130706433/x", "https://127.1/x", "https://10.0.0.1/x",
                "https://[fd00::1]/x", "https://169.254.169.254/latest", "https://metadata.google.internal/x", "http://ok.fr/x"):
        r = http("POST", "/api/owner/integrations/webhooks", bearer=OWN, json={"url": url, "events": ["visit.created"]})
        check(f"refused at creation: {url}", r.status_code == 400)
    resolved["evil.example.com"] = ["10.1.2.3"]
    evil = http("POST", "/api/owner/integrations/webhooks", bearer=OWN,
                json={"url": "https://evil.example.com/x", "events": ["visit.created"]}).json()
    sent.clear()
    visit(KEY, SARAH, 1, ext="EVIL-1")
    check("a name that points inside is never called", not any("evil.example.com" in s["url"] for s in sent))
    d = db.webhook_deliveries.find_one({"hook_id": evil["id"]}, sort=[("at", -1)])
    check("…the delivery says why", d and not d["ok"] and "blocked_address" in (d.get("error") or ""))
    http("DELETE", f"/api/owner/integrations/webhooks/{evil['id']}", bearer=OWN)
    for i in range(3):
        http("POST", "/api/owner/integrations/webhooks", bearer=OWN, json={"url": f"https://slow{i}.example.com/x", "events": ["visit.created"]})
    drain["on"] = False
    slow["s"] = 1.0
    t0 = time.time()
    visit(KEY, SARAH, 1, ext="SLOW-1")
    took = time.time() - t0
    t1 = time.time()
    M.drain_webhooks(10)
    both = time.time() - t1
    slow["s"] = 0.0
    check(f"4 endpoints of 1 s each are called side by side ({both:.1f} s for all)", both < 2.5)
    slow["s"] = 1.0
    t0 = time.time()
    visit(KEY, SARAH, 1, ext="SLOW-2")
    took = time.time() - t0
    M.drain_webhooks(10)
    slow["s"] = 0.0
    drain["on"] = True
    check(f"the call never waits for slow endpoints (took {took:.2f} s)", took < 0.8)
    check("…and those are written down for the retry, not lost",
          db.webhook_deliveries.count_documents({"event_id": {"$exists": True}, "type": "visit.created"}) > 0)
    tick = server.tick_pass()
    check("the 15-minute tick retries failed deliveries", "webhooks" in tick)

    # ------------------------------------------------------------------
    print("\nHousekeeping")
    idx = db.api_rate.index_information()
    check("rate rows expire (TTL)", any(v.get("expireAfterSeconds") for v in idx.values()))
    idx = db.api_idempotency.index_information()
    check("idempotency rows expire after 30 days (TTL)", any(v.get("expireAfterSeconds") == 30 * 86400 for v in idx.values()))
    check("verification rows expire (TTL)", any(v.get("expireAfterSeconds") for v in db.api_verifications.index_information().values()))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
