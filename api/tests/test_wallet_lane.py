"""
The iPhone's own lane (user, 2026-11-21, PR A after #511). An iPhone that
adds a card tells the server once « this card is on me »; that call used to
queue behind the card page's own requests on the same instance (3 database
connections, a 10 s wait, then 503) and could be lost for good.

The iPhone's four small calls — link a card, « what changed? », unlink, its
error log — now run in their own Vercel function, api/wallet_lane.py:

    · it never loads the big server (server.py): a cold start of a few
      hundred ms, not seconds, and no seed, no migration, no cron in it;
    · its own MongoDB client, 2 connections at most — the platform's budget on
      Atlas M0 (500) stays known: api instances × 3 + lane instances × 2;
    · the same answers as before, through the same code (wallet_passes);
    · « Bienvenue », which needs the whole server, is handed to it: queued,
      the server is woken at once, the 15-minute tick sweeps what is left —
      sent once per client, never twice;
    · vercel.json sends exactly those four paths to the lane, the card
      download (/api/passes/v1/passes/…) stays on the server.

Run: cd api && python3 tests/test_wallet_lane.py
"""
import asyncio
import base64
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-wallet-lane")
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
    import httpx
    PT = "pass.com.fidclic.test"
    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda **kw: now - dt.timedelta(**kw)     # noqa: E731

    print("\n1. The lane is light")
    import wallet_lane as L
    check("importing the lane never loads server.py", "server" not in sys.modules)
    check(f"its own client: 2 connections at most ({L.LANE_CLIENT_OPTIONS.get('maxPoolSize')})",
          L.LANE_CLIENT_OPTIONS.get("maxPoolSize") == 2)
    check("a full pool fails fast, before Apple gives up",
          0 < L.LANE_CLIENT_OPTIONS.get("waitQueueTimeoutMS", 0) <= 8000)
    check("idle connections handed back", L.LANE_CLIENT_OPTIONS.get("maxIdleTimeMS", 0) <= 30_000)

    db = mongomock.MongoClient().fidelitour_db
    L.connect(db)
    from features import wallet_passes as W
    from services import apns_passes as AP
    check("the wallet code reads the lane's database", W._db is db)

    sent = []

    def fake_push(tokens, topic=None, cert_paths=None):
        tokens = list(tokens)
        sent.extend(tokens)
        return {"sent": len(tokens), "gone": [], "failed": 0, "errors": [],
                "results": [{"token": t, "status": 200, "reason": "", "apns_id": "x"} for t in tokens]}
    AP.push_to_tokens, AP.is_configured = fake_push, (lambda: True)

    pings = []
    W._ping_main = lambda: pings.append(1)

    def http(app, method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "T1", "is_active": True})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-LANE0001", "name": "Otero", "visits": 1,
                             "apple_downloaded_at": ago(seconds=40), "last_visit_date": ago(seconds=5),
                             "updated_at": ago(seconds=5)})
    auth = {"Authorization": "ApplePass " + W._auth_token("FT-LANE0001")}

    print("\n2. The iPhone's four calls, in the lane")
    r = http(L.app, "POST", f"/api/passes/v1/devices/dev1/registrations/{PT}/FT-LANE0001", auth, json={"pushToken": "tok1"})
    check(f"link: 201 ({r.status_code})", r.status_code == 201, r.text[:200])
    check("the answer says it came from the wallet lane", r.headers.get("x-fidclic-lane") == "wallet")
    check("…written", db.pass_registrations.find_one({"serial": "FT-LANE0001", "device_id": "dev1", "push_token": "tok1"}))
    check("…the card scanned 35 s before is pushed to it", "tok1" in sent)
    check("…the history says « added »", db.pass_registration_log.find_one({"serial": "FT-LANE0001", "kind": "added"}))
    check("…Clients › Carte reads « Active »", (db.customers.find_one({"id": "c1"}) or {}).get("wallet_added_at"))
    check("« Bienvenue » handed to the server: queued once", db.wallet_welcome_due.count_documents({"serial": "FT-LANE0001"}) == 1)
    check("…and the server woken at once", pings == [1])
    check("server.py still not loaded by any of it", "server" not in sys.modules)

    r = http(L.app, "POST", f"/api/passes/v1/devices/dev1/registrations/{PT}/FT-LANE0001", auth, json={"pushToken": "tok1"})
    check(f"the same iPhone again: 200, no second « Bienvenue » ({r.status_code})",
          r.status_code == 200 and db.wallet_welcome_due.count_documents({}) == 1)

    r = http(L.app, "POST", f"/api/passes/v1/devices/dev1/registrations/{PT}/FT-LANE0001",
             {"Authorization": "ApplePass nope-nope-nope-nope-nope"}, json={"pushToken": "tok1"})
    check(f"a wrong key: 401 ({r.status_code})", r.status_code == 401)

    r = http(L.app, "GET", f"/api/passes/v1/devices/dev1/registrations/{PT}")
    check(f"« what changed? » without a date: the card ({r.status_code})",
          r.status_code == 200 and r.json().get("serialNumbers") == ["FT-LANE0001"])
    later = str(int((now + dt.timedelta(minutes=1)).timestamp()))
    r = http(L.app, "GET", f"/api/passes/v1/devices/dev1/registrations/{PT}?passesUpdatedSince={later}")
    check(f"« what changed since later? »: nothing, 204 ({r.status_code})", r.status_code == 204)

    r = http(L.app, "POST", "/api/passes/v1/log", json={"logs": ["Web service error for pass: test line"]})
    check(f"the iPhone's error log: kept ({r.status_code})",
          r.status_code == 200 and db.pass_device_logs.find_one({"line": {"$regex": "test line"}}))

    r = http(L.app, "DELETE", f"/api/passes/v1/devices/dev1/registrations/{PT}/FT-LANE0001", auth)
    check(f"unlink: 200 ({r.status_code})", r.status_code == 200)
    check("…the row is gone", not db.pass_registrations.find_one({"serial": "FT-LANE0001"}))
    check("…the card reads « removed »", (db.customers.find_one({"id": "c1"}) or {}).get("wallet_removed_at"))
    ch = db.customer_changes.find_one({"customer_id": "c1", "kind": "card_state"}) or {}
    check(f"…Historique: « Carte retirée d'Apple Wallet », by the client ({ch.get('text')})",
          ch.get("text") == "Carte retirée d'Apple Wallet" and ch.get("by") == "le client" and ch.get("tenant_id") == "t1")
    check("still no server.py", "server" not in sys.modules)

    r = http(L.app, "GET", f"/api/passes/v1/passes/{PT}/FT-LANE0001", auth)
    check(f"the card download is not the lane's ({r.status_code})", r.status_code == 404)

    print("\n3. The server sends « Bienvenue » for the lane")
    import server
    from features import automations as AU
    sdb = server.db
    W._db = sdb
    welcomed = []
    AU.wallet_added = lambda tid, c, where: welcomed.append((tid, c.get("barcode_id"), where))
    sdb.customers.insert_one({"id": "c2", "tenant_id": "t1", "barcode_id": "FT-LANE0002", "name": "Client"})
    sdb.wallet_welcome_due.insert_one({"serial": "FT-LANE0002", "tenant_id": "t1", "at": ago(seconds=2)})
    sdb.wallet_welcome_due.insert_one({"serial": "FT-GONE0002", "tenant_id": "t1", "at": ago(seconds=2)})

    def shttp(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.new_event_loop().run_until_complete(run())
    r = shttp("POST", "/api/wallet/welcome-due")
    check(f"woken: 200 ({r.status_code})", r.status_code == 200, r.text[:200])
    check(f"« Bienvenue » sent for the linked card ({welcomed})", welcomed == [("t1", "FT-LANE0002", "apple")])
    check("…the queue is empty (a card deleted since: dropped)", sdb.wallet_welcome_due.count_documents({}) == 0)
    r = shttp("POST", "/api/wallet/welcome-due")
    check("woken again: nothing sent twice", r.status_code == 200 and len(welcomed) == 1)
    check("the answer says only how many, no client data", set(r.json()) <= {"sent", "left"})

    sdb.wallet_welcome_due.insert_one({"serial": "FT-LANE0002", "tenant_id": "t1", "at": ago(minutes=20)})
    res = server.tick_pass(now)
    check(f"the 15-minute tick sweeps what is left ({res.get('wallet_welcome')})",
          sdb.wallet_welcome_due.count_documents({}) == 0 and "wallet_welcome" in res)

    print("\n4. vercel.json sends the four calls, and only them, to the lane")
    cfg = json.load(open(os.path.join(HERE, "..", "..", "vercel.json")))
    rw = cfg.get("rewrites") or []
    dests = [(r.get("source"), r.get("destination")) for r in rw]
    lane = [s for s, d in dests if d == "/api/wallet_lane.py"]
    first_api = next(i for i, (s, d) in enumerate(dests) if d == "/api/index.py")
    check(f"the devices calls go to the lane ({lane})", "/api/passes/v1/devices/:path*" in lane)
    check("the iPhone's log goes to the lane", "/api/passes/v1/log" in lane)
    check("…before the server's catch-all",
          all(i < first_api for i, (s, d) in enumerate(dests) if d == "/api/wallet_lane.py"))
    check("the card download stays on the server", not any("passes/v1/passes" in s for s in lane))
    check("the lane has its own function settings", "api/wallet_lane.py" in (cfg.get("functions") or {}))

    print("\n5. The lane serves exactly the server's paths")
    main_paths = {(r.path, m) for r in server.app.routes if getattr(r, "path", "").startswith("/api/passes/v1/")
                  for m in (getattr(r, "methods", None) or [])}
    lane_paths = {(r.path, m) for r in L.app.routes if getattr(r, "path", "").startswith("/api/passes/v1/")
                  for m in (getattr(r, "methods", None) or [])}
    check(f"every lane path is a server path too ({sorted(lane_paths - main_paths)})", lane_paths <= main_paths)
    want = {("/api/passes/v1/devices/{device_id}/registrations/{pass_type_id}/{serial}", "POST"),
            ("/api/passes/v1/devices/{device_id}/registrations/{pass_type_id}/{serial}", "DELETE"),
            ("/api/passes/v1/devices/{device_id}/registrations/{pass_type_id}", "GET"),
            ("/api/passes/v1/log", "POST")}
    check(f"the lane has the four calls ({sorted(want - lane_paths)})", want <= lane_paths)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
