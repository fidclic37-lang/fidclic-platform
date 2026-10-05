"""
Wallet push history (user, 2026-10-05): for every test iPhone, the chain
deviceLibraryIdentifier → pushToken → passTypeIdentifier → serialNumber, and
for every push Apple's answer, its apns-id, and whether the device came back.

Run: cd api && /usr/local/bin/python3 tests/test_wallet_push_history.py
"""
import base64
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"
os.environ["APPLE_PASS_TYPE_ID"] = "pass.com.fidclic.test"
os.environ["APPLE_PASS_CERT_B64"] = base64.b64encode(b"cert").decode()
os.environ["APPLE_PASS_KEY_B64"] = base64.b64encode(b"key").decode()

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from features import wallet_passes as W
    from services import apns_passes as AP
    from models import TokenData

    db = server.db
    W._db = db
    passed = failed = 0

    def check(label, cond, extra=""):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))

    PT = "pass.com.fidclic.test"
    db.tenants.insert_one({"id": "t1", "name": "BLOO JOB"})
    for i, name in enumerate(["Akshansh", "Partenaire", "Ami", "Quatrième"], 1):
        db.customers.insert_one({"id": f"c{i}", "tenant_id": "t1", "name": name, "barcode_id": f"FT-HIST000{i}",
                                 "created_at": dt.datetime.now(dt.timezone.utc)})

    def register(dev, serial, token):
        auth = f"ApplePass {W._auth_token(serial)}"
        return W.register_device(dev, PT, serial, W.Registration(pushToken=token), auth).status_code

    print("\nRegistration — three of the four iPhones register")
    check("first registration → 201", register("DEVICEAAAAAAAAAA1111", "FT-HIST0001", "tokAAAAAAAAAAAAAAAAAAAAAA01") == 201)
    register("DEVICEBBBBBBBBBB2222", "FT-HIST0002", "tokBBBBBBBBBBBBBBBBBBBBBB02")
    register("DEVICECCCCCCCCCC3333", "FT-HIST0003", "tokCCCCCCCCCCCCCCCCCCCCCC03")

    print("\nA push — Apple accepts two, refuses one")
    def fake_push(tokens):
        res = {"sent": 0, "gone": [], "failed": 0, "errors": [], "results": []}
        for t in tokens:
            if t.endswith("03"):
                res["results"].append({"token": t, "status": 400, "reason": "BadDeviceToken", "apns_id": "id-3"})
                res["gone"].append(t)
            else:
                res["results"].append({"token": t, "status": 200, "reason": "", "apns_id": f"id-{t[-1]}"})
                res["sent"] += 1
        return res
    real_push, real_ready = AP.push_to_tokens, AP.is_configured
    AP.push_to_tokens, AP.is_configured = fake_push, (lambda: True)
    try:
        W._notify_apple(["FT-HIST0001", "FT-HIST0002", "FT-HIST0003"])
    finally:
        AP.push_to_tokens, AP.is_configured = real_push, real_ready
    rows = list(db.pass_push_log.find({}))
    check("one history row per device", len(rows) == 3)
    row1 = db.pass_push_log.find_one({"serial": "FT-HIST0001"})
    check("Apple's answer and receipt number kept", row1["status"] == 200 and row1["apns_id"] == "id-1")
    check("the push token is never stored whole", "…" in row1["token"] and "tokAAAAAAAAAAAAAAAAAAAAAA01" not in str(row1))

    print("\nThe iPhones come back (or not)")
    W.serials_for_device("DEVICEAAAAAAAAAA1111", PT, None)
    real_resp = W._pkpass_response
    W._pkpass_response = lambda serial: None
    try:
        W.latest_pass(PT, "FT-HIST0001", f"ApplePass {W._auth_token('FT-HIST0001')}")
    finally:
        W._pkpass_response = real_resp
    row1 = db.pass_push_log.find_one({"serial": "FT-HIST0001"})
    check("device 1 asked, then downloaded", row1["checked_at"] is not None and row1["fetched_at"] is not None)
    # device 2 never comes back; make its push old enough to stop being « en attente »
    db.pass_push_log.update_many({"serial": "FT-HIST0002"},
                                 {"$set": {"sent_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)}})

    print("\nThe stats page")
    s = W.owner_wallet_stats(token_data=TokenData(email="o@x.fr", role="business_owner", tenant_id="t1"))
    devs = {d["card"]: d for d in s["devices_detail"]}
    d1 = devs.get("FT-HIST0001") or {}
    check("the chain is there: device, token, pass type, card, registration date",
          d1.get("device", "").startswith("DEVICE") and "…" in d1.get("device", "") and "…" in d1.get("push_token", "")
          and d1.get("pass_type") == PT and d1.get("registered_at"))
    check("the customer is named", d1.get("customer") == "Akshansh")
    p1 = (d1.get("pushes") or [{}])[0]
    check("its push reads « mis à jour », with Apple's 200 and the apns-id",
          p1.get("state") == "mis à jour" and p1.get("apple") == 200 and p1.get("apns_id") == "id-1", str(p1))
    p2 = ((devs.get("FT-HIST0002") or {}).get("pushes") or [{}])[0]
    check("a device that never came back reads « pas récupéré »", p2.get("state") == "pas récupéré", str(p2))
    check("a refused token is dropped from the registrations", "FT-HIST0003" not in devs)
    without = {c["card"]: c for c in s["cards_without_device"]}
    check("cards on no device are listed by name (the 4th iPhone, and the refused one)",
          set(without) == {"FT-HIST0003", "FT-HIST0004"} and without["FT-HIST0004"]["customer"] == "Quatrième",
          str(list(without)))
    row3 = db.pass_push_log.find_one({"serial": "FT-HIST0003"})
    check("…and the refused push stays in the history with Apple's reason",
          row3["status"] == 400 and row3["reason"] == "BadDeviceToken"
          and W._push_state(row3, dt.datetime.now(dt.timezone.utc)).startswith("refusé par Apple"))

    print("\nHistory is kept 30 days")
    db.pass_push_log.insert_one({"serial": "FT-HIST0001", "device_id": "old", "sent_at":
                                 dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=31)})
    W._log_pushes([], [], dt.datetime.now(dt.timezone.utc))
    check("older rows are pruned", db.pass_push_log.count_documents({"device_id": "old"}) == 0)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
