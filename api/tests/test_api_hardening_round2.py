"""
API hardening, round 2 (user, 2026-11-09: « ye sab fix kr do, same pr mein »)
— the five points left open by #454's pentest and load lab:

  1  NON-FINITE NUMBERS   1e309, NaN, -Infinity in a JSON body: a 422 that
                          says so, never a 500, on every route
  2  PHONE TAIL           the last 9 digits of every client's phone, kept by
                          the database's own writes (any writer), indexed,
                          back-filled once; the API looks a phone up by it
  3  WEBHOOKS IN THE BACK the till never waits for a merchant's endpoint;
                          a delivery the instance never finished is retried
  4  HOLD LIMIT           a reward cannot be held again and again: 3 unused
                          holds per client per hour, then 429
  5  REFUNDS AND RGPD     a client's cancelled visits are in their data
                          export; erasing the client empties the free text

Run: cd api && /usr/local/bin/python3 tests/test_api_hardening_round2.py
"""
import asyncio
import datetime as dt
import json
import os
import sys
import time

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

# The e-mail check asks DNS whether the domain receives mail (services/
# email_check). A test must not depend on the network: the stub answers
# « unreachable », which the module treats as « accept » — on a laptop with no
# DNS and on the CI (where x.fr really has no MX) alike.
import services.email_check as EC  # noqa: E402

EC.domain_receives_mail = lambda d: None

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx
    from pymongo import UpdateOne, InsertOne, ReplaceOne
    from features import merchant_api as M
    from services import sms as SMS

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def http(method, url, key=None, bearer=None, **kw):
        headers = kw.pop("headers", {})
        if key:
            headers["Authorization"] = "Bearer " + key
        if bearer:
            headers["Authorization"] = "Bearer " + bearer

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        try:
            return asyncio.run(run())
        except Exception as e:                     # a crash in the app is what this file looks for
            class Crash:
                status_code = f"CRASH {type(e).__name__}"
                text = str(e)

                def json(self):
                    return {}
            return Crash()

    def code_of(r):
        try:
            d = r.json().get("detail")
            return d.get("code") if isinstance(d, dict) else None
        except Exception:
            return None

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active", "created_at": now},
        {"id": "t2", "slug": "bar", "name": "Bar", "plan": "vip", "subscription_status": "active", "created_at": now},
    ])
    db.card_templates.insert_many([{"tenant_id": "t1", "reward_threshold_stamps": 3, "visits_per_stamp": 1, "reward_description": "Café"},
                                   {"tenant_id": "t2", "reward_threshold_stamps": 3, "visits_per_stamp": 1}])
    db.users.insert_many([{"email": "o@cafe.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "o@bar.fr", "role": "business_owner", "tenant_id": "t2"}])
    OWN = auth.create_access_token({"sub": "o@cafe.fr", "role": "business_owner", "tenant_id": "t1"})

    import requests
    sent = []
    slow = {"s": 0.0}

    class _R:
        def __init__(self, code): self.status_code = code

    def fake_post(url, data=None, timeout=None, headers=None, **kw):
        if slow["s"]:
            time.sleep(slow["s"])
        sent.append({"url": url, "headers": headers})
        return _R(200)
    requests.post = fake_post
    M._resolve = lambda host: ["93.184.216.34"]
    SMS.is_configured = lambda: True
    SMS.send_sms = lambda to, body: {"sent": True}

    KEY = http("POST", "/api/owner/integrations/keys", bearer=OWN, json={"name": "Caisse", "write": True}).json()["key"]

    def join(slug, name, phone, email=""):
        return server.join_program(slug, server.JoinRequest(name=name, phone=phone, email=email, postal_code="", birthday="",
                                                            consent=True))["barcode_id"]

    def cust(bc):
        return db.customers.find_one({"barcode_id": bc}, {"_id": 0})

    def raw(url, body, key=KEY, bearer=None):
        return http("POST", url, key=key if not bearer else None, bearer=bearer, content=body,
                    headers={"Content-Type": "application/json"})

    SARAH = join("cafe", "Sarah", "06 12 34 56 78")

    # ------------------------------------------------------------------
    print("\n1. Numbers that are not numbers")
    for lit in ("1e309", "-1e309", "NaN", "Infinity", "-Infinity"):
        r = raw("/api/v1/visits", '{"customer": "%s", "amount": %s}' % (SARAH, lit))
        check(f"amount {lit} → 422, not a crash", r.status_code == 422)
    r = raw("/api/v1/visits", '{"customer": "%s", "amount": 1e309}' % SARAH)
    check("…and it says why, in French", "fini" in r.text.lower() or "invalide" in r.text.lower())
    r = raw("/api/v1/visits", '{"customer": "%s", "amount": 2, "items": [{"item_id": "x", "qty": 1e400}]}' % SARAH)
    check("deep inside a list too", r.status_code == 422)
    r = raw("/api/owner/scan", '{"barcode_id": "%s", "amount_paid": 1e309}' % SARAH, bearer=OWN)
    check("on a counter route as well (the till's scan)", r.status_code in (400, 422))
    r = raw("/api/v1/visits", '{"customer": "%s", "amount": 1e30}' % SARAH)
    check("a huge but finite number is the route's to judge (422 from its own limit)", r.status_code == 422)
    r = raw("/api/v1/visits", '{"customer": "%s", "amount": 12.5}' % SARAH)
    check("a normal amount still goes through", r.status_code == 201)
    r = http("POST", "/api/v1/customers", key=KEY, json={"name": "Infinity NaN", "phone": "0611111199", "consent": True})
    check("the WORDS « Infinity » / « NaN » in a text are fine", r.status_code == 201)
    r = raw("/api/v1/visits", '{"customer": "%s", "amount": ' % SARAH)
    check("broken JSON is still a 422, not a crash", r.status_code == 422)
    r = raw("/api/v1/visits", '{"customer": "%s", "amount": 1e309}' % SARAH, key="fc_live_nope")
    check("without a valid key: still refused cleanly (401 or 422)", r.status_code in (401, 422))
    from fastapi.exceptions import RequestValidationError
    from services import finite_json as FJ
    resp = asyncio.run(FJ.validation_error(None, RequestValidationError(
        [{"type": "less_than_equal", "loc": ["query", "x"], "msg": "m", "input": float("inf")}])))
    check("a validation error holding ∞ (e.g. ?x=inf) is still written as a 422", resp.status_code == 422 and b"inf" in resp.body)

    # ------------------------------------------------------------------
    print("\n2. Phone tail")
    c = cust(SARAH)
    check("sign-up writes the tail", c.get("phone_tail") == "612345678")
    db.customers.update_one({"id": c["id"]}, {"$set": {"phone": "+33 7 00 00 00 01"}})
    check("any $set of the phone moves the tail", cust(SARAH)["phone_tail"] == "700000001")
    db.customers.find_one_and_update({"id": c["id"]}, {"$set": {"phone": "07.00.00.00.02"}})
    check("find_one_and_update too", cust(SARAH)["phone_tail"] == "700000002")
    db.customers.insert_one({"id": "raw1", "tenant_id": "t1", "barcode_id": "FT-RAW00001", "name": "Raw", "phone": "0033 6 55 44 33 22"})
    check("a direct insert gets it", cust("FT-RAW00001")["phone_tail"] == "655443322")
    db.customers.insert_many([{"id": "raw2", "tenant_id": "t1", "barcode_id": "FT-RAW00002", "name": "R2", "phone": "0655443300"},
                              {"id": "raw3", "tenant_id": "t1", "barcode_id": "FT-RAW00003", "name": "R3"}])
    check("insert_many too, and a client without phone has an empty tail",
          cust("FT-RAW00002")["phone_tail"] == "655443300" and cust("FT-RAW00003").get("phone_tail") == "")
    db.customers.update_many({"id": {"$in": ["raw2"]}}, {"$set": {"phone": "06 99 88 77 66"}})
    check("update_many too", cust("FT-RAW00002")["phone_tail"] == "699887766")
    db.customers.bulk_write([UpdateOne({"id": "raw3"}, {"$set": {"phone": "0612121212"}}),
                             InsertOne({"id": "raw4", "tenant_id": "t1", "barcode_id": "FT-RAW00004", "name": "R4", "phone": "0634343434"})])
    check("bulk_write (imports) too", cust("FT-RAW00003")["phone_tail"] == "612121212" and cust("FT-RAW00004")["phone_tail"] == "634343434")
    db.customers.replace_one({"id": "raw4"}, {"id": "raw4", "tenant_id": "t1", "barcode_id": "FT-RAW00004", "name": "R4", "phone": "0656565600"})
    check("replace_one too", cust("FT-RAW00004")["phone_tail"] == "656565600")
    db.customers.update_one({"id": "raw4"}, {"$unset": {"phone": ""}})
    check("$unset of the phone empties the tail", cust("FT-RAW00004").get("phone_tail") == "")
    db.customers.update_one({"id": "raw1", "phone": {"$exists": False}}, {"$set": {"phone": "0600000000"}})
    check("a write whose filter matched nothing changes nothing", cust("FT-RAW00001")["phone_tail"] == "655443322")
    db.customers.update_one({"id": "upsert1"}, {"$setOnInsert": {"tenant_id": "t1", "barcode_id": "FT-UPS00001", "name": "U",
                                                                  "phone": "06 10 20 30 40"}}, upsert=True)
    check("an upsert's $setOnInsert too", cust("FT-UPS00001")["phone_tail"] == "610203040")
    r = http("GET", "/api/v1/customers/+33 7 00 00 00 02", key=KEY)
    check("the API finds by the tail", r.status_code == 200 and r.json()["card_number"] == SARAH)
    # a client written before the tail existed
    db.customers.update_one({"id": "raw2"}, {"$unset": {"phone_tail": ""}})
    r = http("GET", "/api/v1/customers/0699887766", key=KEY)
    check("a client without a tail yet is still found", r.status_code == 200 and r.json()["card_number"] == "FT-RAW00002")
    db.platform_settings.delete_many({"key": M.PHONE_TAIL_MIGRATION})
    n = M.backfill_phone_tails()
    check("the one-time back-fill writes the missing tails", n >= 1 and cust("FT-RAW00002")["phone_tail"] == "699887766")
    check("…and runs once", M.backfill_phone_tails() == 0)
    db.customers.insert_many([
        {"id": "f1", "tenant_id": "t1", "barcode_id": "FT-FAM10001", "name": "Paul", "phone": "07 11 22 33 44"},
        {"id": "f2", "tenant_id": "t1", "barcode_id": "FT-FAM10002", "name": "Julie", "phone": "+33711223344"}])
    r = http("GET", "/api/v1/customers/0711223344", key=KEY)
    check("two clients on one tail → 409 ambiguous_customer, as before", r.status_code == 409 and code_of(r) == "ambiguous_customer")
    check("another shop never sees them", http("GET", "/api/v1/customers/0711223344",
          key=http("POST", "/api/owner/integrations/keys", bearer=auth.create_access_token(
              {"sub": "o@bar.fr", "role": "business_owner", "tenant_id": "t2"}), json={"name": "K", "write": True}).json()["key"]).status_code == 404)
    idx = db.customers.index_information()
    check("the tail is indexed per shop", any(v.get("key") == [("tenant_id", 1), ("phone_tail", 1)] for v in idx.values()))
    check("the client's id is indexed (every scan reads a client by id)", any(v.get("key") == [("id", 1)] for v in idx.values()))
    check("the card number is indexed per shop", any(v.get("key") == [("tenant_id", 1), ("barcode_id", 1)] for v in idx.values()))

    # ------------------------------------------------------------------
    print("\n3. Webhooks in the back")
    http("POST", "/api/owner/integrations/webhooks", bearer=OWN, json={"url": "https://slow.example.com/x", "events": ["visit.created"]})
    http("POST", "/api/owner/integrations/webhooks", bearer=OWN, json={"url": "https://slow2.example.com/x", "events": ["visit.created"]})
    slow["s"] = 1.0
    sent.clear()
    t0 = time.time()
    r = http("POST", "/api/v1/visits", key=KEY, json={"customer": SARAH, "amount": 3, "external_id": "BG-1"})
    took = time.time() - t0
    check(f"two 1 s endpoints: the visit answers at once ({took:.2f} s)", r.status_code == 201 and took < 0.8)
    M.drain_webhooks(5)
    slow["s"] = 0.0
    check("…and both get it a moment later", len([s for s in sent if "slow" in s["url"]]) == 2)
    check("…logged as delivered", db.webhook_deliveries.count_documents({"type": "visit.created", "ok": True, "error": None}) >= 2)
    # an instance frozen before it sent: the row stays « pending » and the tick sends it
    keep = M._submit
    M._submit = lambda *a, **k: None
    sent.clear()
    http("POST", "/api/v1/visits", key=KEY, json={"customer": SARAH, "amount": 3, "external_id": "BG-2"})
    M._submit = keep
    pend = db.webhook_deliveries.count_documents({"error": "pending"})
    check("a delivery the instance never ran stays written down", pend == 2 and not sent)
    out = M.retry_failed(M._now() + dt.timedelta(minutes=3))
    check("the 15-minute tick sends it", out["ok"] == 2 and db.webhook_deliveries.count_documents({"error": "pending"}) == 0)
    check(f"a bounded pool (at most {M.WEBHOOK_WORKERS} threads)", 1 <= M.WEBHOOK_WORKERS <= 16)
    # a merchant's server down for an hour: the instance's queue never grows without end
    keep_max, keep_inflight = M.WEBHOOK_QUEUE_MAX, set(M._INFLIGHT)
    M.WEBHOOK_QUEUE_MAX = 0
    sent.clear()
    t0 = time.time()
    http("POST", "/api/v1/visits", key=KEY, json={"customer": SARAH, "amount": 3, "external_id": "BG-3"})
    M.drain_webhooks(5)
    M.WEBHOOK_QUEUE_MAX = keep_max
    check("queue full: nothing more is held in memory, the rows wait for the tick",
          not sent and db.webhook_deliveries.count_documents({"error": "pending"}) == 2)
    check("…and the tick sends them", M.retry_failed(M._now() + dt.timedelta(minutes=3))["ok"] == 2)

    # ------------------------------------------------------------------
    print("\n4. Hold limit")
    LEO = join("cafe", "Léo", "0653535353")
    for i in range(4):
        http("POST", "/api/v1/visits", key=KEY, json={"customer": LEO, "amount": 2})
    ids = []
    for i in range(M.HOLDS_PER_HOUR):
        r = http("POST", "/api/v1/rewards/hold", key=KEY, json={"customer": LEO})
        ids.append(r.json().get("hold_id"))
        http("DELETE", f"/api/v1/rewards/hold/{ids[-1]}", key=KEY)
    check(f"{M.HOLDS_PER_HOUR} holds let go in an hour are allowed", all(ids))
    r = http("POST", "/api/v1/rewards/hold", key=KEY, json={"customer": LEO})
    check("one more → 429 too_many_holds", r.status_code == 429 and code_of(r) == "too_many_holds")
    r = http("POST", "/api/owner/rewards/redeem", bearer=OWN, json={"customer_id": cust(LEO)["id"]})
    check("…and the till hands the reward over meanwhile", r.status_code == 200)
    MAX = join("cafe", "Max", "0654545454")
    for i in range(4):
        http("POST", "/api/v1/visits", key=KEY, json={"customer": MAX, "amount": 2})
    check("another client is not limited", http("POST", "/api/v1/rewards/hold", key=KEY, json={"customer": MAX}).status_code == 201)
    db.api_reward_holds.update_many({"customer_id": cust(LEO)["id"]}, {"$set": {"at": M._now() - dt.timedelta(minutes=61)}})
    for i in range(4):
        http("POST", "/api/v1/visits", key=KEY, json={"customer": LEO, "amount": 2})
    check("an hour later it may hold again", http("POST", "/api/v1/rewards/hold", key=KEY, json={"customer": LEO}).status_code == 201)
    ZED = join("cafe", "Zed", "0655556666")
    for i in range(8):
        http("POST", "/api/v1/visits", key=KEY, json={"customer": ZED, "amount": 2})
    used = 0
    for i in range(M.HOLDS_PER_HOUR + 1):
        h = http("POST", "/api/v1/rewards/hold", key=KEY, json={"customer": ZED}).json()
        if h.get("hold_id") and http("POST", "/api/v1/rewards/redeem", key=KEY, json={"customer": ZED, "hold_id": h["hold_id"]}).status_code == 200:
            used += 1
        for j in range(4):
            http("POST", "/api/v1/visits", key=KEY, json={"customer": ZED, "amount": 2})
    check("holds that ended in a used reward do not count", used == M.HOLDS_PER_HOUR + 1)

    # ------------------------------------------------------------------
    print("\n5. Refunds in the client's data")
    EVA = join("cafe", "Eva", "0657778888", "eva@x.fr")
    v = http("POST", "/api/v1/visits", key=KEY, json={"customer": EVA, "amount": 9, "external_id": "EVA-1"}).json()["visit"]
    http("POST", f"/api/v1/visits/{v['id']}/cancel", key=KEY, json={"reason": "Eva Martin, remboursée"})
    r = http("GET", f"/api/card/{EVA}/my-data", bearer=OWN)
    j = r.json() if r.status_code == 200 else {}
    check("my-data lists the cancelled visit", r.status_code == 200 and [x.get("id") for x in j.get("visits_cancelled", [])] == [v["id"]])
    check("…apart from the visits that count", all(x.get("id") != v["id"] for x in j.get("visits", [])))
    r = http("POST", f"/api/card/{EVA}/forget-me", bearer=OWN, json={"confirm": True})
    row = db.visits_cancelled.find_one({"id": v["id"]}) or {}
    check("erasing the client empties the free text of their refunds", r.status_code == 200 and not row.get("cancel_reason"))
    check("…and keeps the figures (amount)", float(row.get("amount_paid") or 0) == 9)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
