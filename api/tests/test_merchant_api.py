"""
API & Intégrations — keys (shown once, hashed, read / write, revoke), the
public API over HTTP (me, customers, visits with the counter's rules and
idempotency, rewards), the plan switch, the rate limit, and webhooks
(signature, events from the real flows, test, delivery log, retries).

Run: cd api && /usr/local/bin/python3 tests/test_merchant_api.py
"""
import asyncio
import datetime as dt
import hashlib
import hmac
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx
    from fastapi import HTTPException
    from models import TokenData
    from features import merchant_api as M

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
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café Lumière", "plan": "vip", "subscription_status": "active", "created_at": now},
        {"id": "t2", "slug": "boul", "name": "Boulangerie", "plan": "silver", "subscription_status": "active", "created_at": now},
    ])
    db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 3, "visits_per_stamp": 1, "reward_description": "Café offert"})
    db.users.insert_many([{"email": "o@cafe.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "o@boul.fr", "role": "business_owner", "tenant_id": "t2"}])
    OWN = auth.create_access_token({"sub": "o@cafe.fr", "role": "business_owner", "tenant_id": "t1"})
    OWN2 = auth.create_access_token({"sub": "o@boul.fr", "role": "business_owner", "tenant_id": "t2"})

    # Webhook deliveries are captured, not sent.
    import requests
    sent = []

    class _R:
        def __init__(self, code): self.status_code = code

    fail = {"on": False}

    def fake_post(url, data=None, timeout=None, headers=None):
        sent.append({"url": url, "body": data, "headers": headers})
        return _R(500 if fail["on"] else 200)
    requests.post = fake_post

    print("\nKeys")
    r = http("POST", "/api/owner/integrations/keys", bearer=OWN, json={"name": "Caisse", "write": True})
    k = r.json()
    KEY = k.get("key", "")
    check("created: the full key shown once, fc_live_…", r.status_code == 201 and KEY.startswith("fc_live_") and len(KEY) > 30)
    doc = db.api_keys.find_one({"id": k["id"]})
    check("stored as a hash, never in clear", doc["hash"] == hashlib.sha256(KEY.encode()).hexdigest() and KEY not in str(doc))
    page = http("GET", "/api/owner/integrations", bearer=OWN).json()
    check("the list shows the prefix, not the key", page["keys"][0]["prefix"] == KEY[:14] and "key" not in page["keys"][0])
    RO = http("POST", "/api/owner/integrations/keys", bearer=OWN, json={"name": "Lecture", "write": False}).json()["key"]
    r2 = http("GET", "/api/owner/integrations", bearer=OWN2)
    check("a plan without « API & Intégrations » → 403 with the upgrade", r2.status_code == 403 and r2.json()["detail"]["code"] == "PLAN_FEATURE_DISABLED")

    print("\nPublic API")
    check("no key → 401", http("GET", "/api/v1/me").status_code == 401)
    check("wrong key → 401", http("GET", "/api/v1/me", key="fc_live_nope").status_code == 401)
    me = http("GET", "/api/v1/me", key=KEY).json()
    check("me: the business and its card rules", me["business"]["name"] == "Café Lumière" and me["card"]["reward_threshold"] == 3 and me["plan"] == "Pro AI")
    r = http("POST", "/api/v1/customers", key=KEY, json={"name": "Inès Fontaine", "phone": "06 12 34 56 78", "consent": False})
    check("customer without consent refused", r.status_code == 400 and r.json()["detail"]["code"] == "consent_required")
    r = http("POST", "/api/v1/customers", key=KEY, json={"name": "Inès Fontaine", "phone": "06 12 34 56 78", "email": "ines@ex.fr", "consent": True})
    c = r.json()
    check("customer created with a card number and card link", r.status_code == 201 and c["card_number"].startswith("FT-") and f"/card/{c['card_number']}?k=" in c["card_url"])   # the owner's link (services/card_owner)
    check("same phone again → the same card", http("POST", "/api/v1/customers", key=KEY, json={"name": "Inès F.", "phone": "0612345678", "consent": True}).json()["id"] == c["id"])
    check("read-only key cannot write", http("POST", "/api/v1/customers", key=RO, json={"name": "X", "phone": "0600000000", "consent": True}).status_code == 403)
    check("find by phone in any format", http("GET", "/api/v1/customers/+33612345678", key=RO).json()["id"] == c["id"])
    check("find by card number", http("GET", f"/api/v1/customers/{c['card_number'].lower()}", key=RO).json()["id"] == c["id"])
    check("search", http("GET", "/api/v1/customers?search=fontaine", key=RO).json()["total"] == 1)

    print("\nVisits (the counter's rules)")
    v1 = http("POST", "/api/v1/visits", key=KEY, json={"customer": c["card_number"], "amount": 12.5, "external_id": "T-1001"})
    b = v1.json()
    check("visit recorded: stamp, spend, source api, ticket number", v1.status_code == 201 and b["customer"]["stamps"] == 1
          and b["customer"]["total_spent"] == 12.5 and b["visit"]["source"] == "api" and b["visit"]["external_id"] == "T-1001")
    again = http("POST", "/api/v1/visits", key=KEY, json={"customer": c["card_number"], "amount": 12.5, "external_id": "T-1001"}).json()
    check("same ticket twice → counted once", again["duplicate"] is True and db.visits.count_documents({"customer_id": c["id"]}) == 1)
    for n in ("T-1002", "T-1003"):
        last = http("POST", "/api/v1/visits", key=KEY, json={"customer": c["id"], "amount": 4, "external_id": n}).json()
    check("3rd visit: reward unlocked", last["reward_unlocked"] is True and last["customer"]["reward_unlocked"] is True)
    lst = http("GET", f"/api/v1/visits?customer={c['id']}", key=RO).json()
    check("visits listed, newest first", lst["total"] == 3 and lst["data"][0]["external_id"] == "T-1003")
    rd = http("POST", "/api/v1/rewards/redeem", key=KEY, json={"customer": c["id"], "reward_name": "Café offert", "external_id": "R-1"})
    check("reward redeemed, card restarts", rd.status_code == 200 and rd.json()["customer"]["stamps"] == 0)
    check("no reward left → 409", http("POST", "/api/v1/rewards/redeem", key=KEY, json={"customer": c["id"]}).status_code == 409)
    check("unknown customer → 404", http("POST", "/api/v1/visits", key=KEY, json={"customer": "FT-NOPE", "amount": 1}).status_code == 404)

    print("\nPlan, suspension, revocation, rate limit")
    db.tenants.update_one({"id": "t1"}, {"$set": {"plan": "gold"}})
    check("plan without API → the key stops at once (403)", http("GET", "/api/v1/me", key=KEY).status_code == 403)
    db.tenants.update_one({"id": "t1"}, {"$set": {"plan": "vip"}})
    ro_id = db.api_keys.find_one({"name": "Lecture"})["id"]
    http("DELETE", f"/api/owner/integrations/keys/{ro_id}", bearer=OWN)
    check("revoked key → 401", http("GET", "/api/v1/me", key=RO).status_code == 401)
    kid = db.api_keys.find_one({"name": "Caisse"})["id"]
    import time
    db.api_rate.update_one({"key_id": kid, "minute": int(time.time() // 60)}, {"$set": {"n": M.RATE_PER_MINUTE}}, upsert=True)
    check("over 120 a minute → 429", http("GET", "/api/v1/me", key=KEY).status_code == 429)
    db.api_rate.delete_many({})

    print("\nWebhooks")
    check("http:// refused", http("POST", "/api/owner/integrations/webhooks", bearer=OWN, json={"url": "http://x.fr/h", "events": ["visit.created"]}).status_code == 400)
    check("internal address refused", http("POST", "/api/owner/integrations/webhooks", bearer=OWN, json={"url": "https://192.168.1.4/h", "events": ["visit.created"]}).status_code == 400)
    h = http("POST", "/api/owner/integrations/webhooks", bearer=OWN, json={"url": "https://outil.example.fr/fidclic",
                                                                           "events": ["customer.created", "visit.created", "reward.unlocked", "reward.redeemed"]}).json()
    check("webhook created with its secret", h["secret"].startswith("whsec_") and h["active"])
    sent.clear()
    t = http("POST", f"/api/owner/integrations/webhooks/{h['id']}/test", bearer=OWN).json()
    check("test event sent", t["ok"] is True and sent and sent[0]["headers"]["X-FidClic-Event"] == "test")
    sig = sent[0]["headers"]["X-FidClic-Signature"]
    ts, mac = sig.split(",")[0][2:], sig.split(",")[1][3:]
    expect = hmac.new(h["secret"].encode(), f"{ts}.".encode() + sent[0]["body"], hashlib.sha256).hexdigest()
    check("signature = HMAC-SHA256(secret, « t.body »)", hmac.compare_digest(mac, expect))
    sent.clear()
    nc = http("POST", "/api/v1/customers", key=KEY, json={"name": "Tom Fournier", "phone": "0698765432", "consent": True}).json()
    check("customer.created from the sign-up flow", [s["headers"]["X-FidClic-Event"] for s in sent] == ["customer.created"])
    sent.clear()
    for n in ("V1", "V2", "V3"):
        http("POST", "/api/v1/visits", key=KEY, json={"customer": nc["id"], "amount": 3, "external_id": n})
    kinds = [s["headers"]["X-FidClic-Event"] for s in sent]
    check("visit.created ×3 and reward.unlocked once", kinds.count("visit.created") == 3 and kinds.count("reward.unlocked") == 1)
    sent.clear()
    server.redeem_reward(server.RedeemRewardRequest(customer_id=nc["id"]), token_data=TokenData(email="o@cafe.fr", role="business_owner", tenant_id="t1"))
    check("reward.redeemed from the counter too", [s["headers"]["X-FidClic-Event"] for s in sent] == ["reward.redeemed"])
    fail["on"] = True
    sent.clear()
    server.scan_visit(server.ScanRequest(barcode_id=nc["card_number"]), token_data=TokenData(email="o@cafe.fr", role="business_owner", tenant_id="t1"))
    bad = db.webhook_deliveries.find_one({"ok": False, "type": "visit.created"})
    check("a failed delivery is logged", bad and bad["status"] == 500 and bad["attempts"] == 1)
    fail["on"] = False
    res = M.retry_failed()
    check("the daily retry re-sends it", res["ok"] >= 1 and db.webhook_deliveries.find_one({"id": bad["id"]})["ok"] is True)
    check("nothing sent for a business without webhooks", M.emit("t2", "visit.created", {}) == 0)
    pg = http("GET", "/api/owner/integrations", bearer=OWN).json()
    check("the page lists deliveries and stats", pg["deliveries"] and pg["stats"]["active_hooks"] == 1 and pg["stats"]["active_keys"] == 1)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
