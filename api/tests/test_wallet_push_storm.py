"""
The Apple Wallet push storm (2026-11-12, 17:25–17:40 Paris): Royal Trim's
682 passes were pushed again and again while nothing on the cards had
changed; every iPhone answered each push with two requests and a full pass
download; MongoDB M0 hit its 500 connections; « Service momentanément
indisponible ».

What this test holds the server to:

    · a push goes out only when the pass's content changed (its fingerprint:
      the pass.json + the card + the store) — « the same card again » is 0 pushes;
    · a device that asks « anything newer than what I hold? » with
      If-Modified-Since is answered 304 (no body, no pass built) when nothing
      changed, and Last-Modified is the time of the last real change;
    · the refresh queue is drained by one worker at a time per shop (a lease),
      a second call answers « busy » at once; a drain that failed half-way
      does not push the same cards again.

Run: cd api && python3 -u tests/test_wallet_push_storm.py
"""
import base64
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _selfsigned(cn: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30)).sign(key, hashes.SHA256()))
    return key, cert


key, cert = _selfsigned("Pass Type ID: pass.com.fidclic.test")
_, wwdr = _selfsigned("Fake WWDR")
os.environ.update({
    "APPLE_PASS_TYPE_ID": "pass.com.fidclic.test", "APPLE_TEAM_ID": "TEAM123456",
    "APPLE_PASS_CERT_B64": base64.b64encode(cert.public_bytes(serialization.Encoding.PEM)).decode(),
    "APPLE_PASS_KEY_B64": base64.b64encode(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode(),
    "APPLE_WWDR_B64": base64.b64encode(wwdr.public_bytes(serialization.Encoding.PEM)).decode(),
    "PASS_AUTH_SECRET": "test-secret", "DISABLE_SEED": "1", "JWT_SECRET": "test-secret-push-storm",
})
PT = "pass.com.fidclic.test"
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail!r}"))


with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from fastapi import HTTPException
    from features import wallet_passes as WP
    import services.apns_passes as APNS

    db = server.db
    db.tenants.insert_one({"id": "t1", "slug": "royal-trim", "name": "ROYAL TRIM", "plan": "vip", "is_active": True,
                           "subscription_status": "active", "address": "12 rue Nationale, 37000 Tours"})
    db.card_templates.insert_one({"tenant_id": "t1", "layout_style": "wallet", "surface_color": "#000000", "brand_color": "#D4AF37",
                                  "card_name": "ROYAL TRIM", "reward_threshold_stamps": 10, "reward_description": "Une coupe offerte",
                                  "hero_mode": "none", "brand_fields": {"card_name": "ROYAL TRIM"}, "poster_style": False})
    N = 5
    serials = [f"FT-STORM00{i}" for i in range(1, N + 1)]
    for i, s in enumerate(serials, 1):
        db.customers.insert_one({"id": f"c{i}", "tenant_id": "t1", "barcode_id": s, "name": f"Client {i}", "visits": 3, "points": 30,
                                 "tier": "bronze", "created_at": dt.datetime.now(dt.timezone.utc)})
        db.pass_registrations.insert_one({"device_id": f"dev{i}", "serial": s, "push_token": f"tok{i}", "pass_type_id": PT,
                                          "tenant_id": "t1"})

    pushes = []                                   # one list per APNs call: the tokens pushed

    def fake_push(tokens, topic=None, cert_paths=None):
        toks = list(tokens)
        pushes.append(toks)
        return {"sent": len(toks), "gone": [], "failed": 0, "errors": [],
                "results": [{"token": t, "status": 200, "apns_id": f"id-{t}"} for t in toks]}
    APNS.push_to_tokens, APNS.is_configured = fake_push, (lambda: True)
    pushed = lambda: sum(len(p) for p in pushes)          # noqa: E731
    builds = []
    real_build = WP.build_pkpass

    def counting_build(payload):
        builds.append(payload.get("customer", {}).get("barcode_id") if isinstance(payload.get("customer"), dict) else 1)
        return real_build(payload)
    WP.build_pkpass = counting_build

    def status(fn, *a, **k):
        try:
            r = fn(*a, **k)
            return getattr(r, "status_code", 200), r
        except HTTPException as e:
            return e.status_code, None

    auth = lambda s: "ApplePass " + WP._auth_token(s)          # noqa: E731

    # ------------------------------------------------------------------ the same card again
    print("La même carte, encore : zéro push")
    r = WP.notify_tenant("t1")
    check(f"first push after a deploy: every registered pass pushed once ({pushed()})", pushed() == N and r["devices"] == N)
    fetched = {}
    for s in serials:
        st, resp = status(WP.latest_pass, PT, s, auth(s))
        fetched[s] = resp.headers.get("last-modified") if resp is not None else None
        check(f"{s}: the device fetches the pass (200, Last-Modified set)", st == 200 and fetched[s], (st, fetched[s]))
    before = pushed()
    r = WP.notify_tenant("t1")
    check(f"nothing changed → notify_tenant pushes nobody ({pushed() - before})", pushed() == before, r)
    check("…and says so", r.get("unchanged") == N and r["devices"] == 0, r)
    st, _ = status(WP.serials_for_device, "dev1", PT, str(int(time.time()) + 1))
    check("…the device asking « anything since my last fetch? » gets 204", st == 204, st)
    db.customers.update_one({"id": "c1"}, {"$set": {"updated_at": dt.datetime.now(dt.timezone.utc)}})
    r = WP.notify_tenant("t1")
    check("a record touched without the card changing (updated_at only) → still nobody", pushed() == before, r)
    db.customers.update_one({"id": "c2"}, {"$inc": {"visits": 1, "points": 10}})
    r = WP.notify_customer("c2")                              # a scan: that card, at once
    check("one client's visit → that one card pushed, the others not", pushed() == before + 1 and pushes[-1] == ["tok2"], (r, pushes[-1:]))
    r = WP.notify_customer("c2")
    check("…and not twice (a small push compares with what the device holds)", pushed() == before + 1 and r.get("unchanged") == 1, r)
    r = WP.notify_tenant("t1")
    check("…a whole-shop push with the same design: nobody, said as such", pushed() == before + 1 and r.get("design_unchanged"), r)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"reward_description": "Un soin offert"}})
    before = pushed()
    r = WP.notify_tenant("t1")
    check(f"a design change → every pass once ({pushed() - before})", pushed() - before == N, r)
    r = WP.notify_tenant("t1")
    check("…then nobody again", pushed() == before + N, r)
    before = pushed()
    r = WP.notify_tenant("t1", force=True)
    check("« Actualiser les cartes » (asked on purpose) looks at every card again, finds them up to date: 0 pushes, said",
          pushed() == before and not r.get("design_unchanged") and r.get("unchanged") == N, r)
    db.customers.update_one({"id": "c3"}, {"$inc": {"visits": 1}})
    r = WP.notify_tenant("t1", force=True)
    check("…and pushes the one card that differs", pushed() == before + 1 and pushes[-1] == ["tok3"], r)
    r = WP._notify_apple(["FT-NOBODY00"])
    check("a serial with no registration: 0 devices, no crash", r.get("devices") == 0, r)

    # ------------------------------------------------------------------ 304
    print("\nIf-Modified-Since : 304, pas de carte reconstruite")
    s = serials[3]                                            # untouched since its fetch above, except the design change
    st, resp = status(WP.latest_pass, PT, s, auth(s))
    lm = resp.headers.get("last-modified")
    nb = len(builds)
    st, resp = status(WP.latest_pass, PT, s, auth(s), if_modified_since=lm)
    check("same card, device holds this version → 304", st == 304, st)
    check("…no body", not (resp.body if resp is not None else b"x"))
    check("…no pass built for it", len(builds) == nb, len(builds) - nb)
    check("…Last-Modified still told", resp is not None and resp.headers.get("last-modified") == lm, resp and dict(resp.headers))
    st, resp = status(WP.latest_pass, PT, s, auth(s), if_modified_since="not a date")
    check("a garbage If-Modified-Since → 200, the pass", st == 200)
    old_lm = lm
    time.sleep(1.1)                                           # HTTP dates are whole seconds
    db.customers.update_one({"barcode_id": s}, {"$inc": {"visits": 1}})
    st, resp = status(WP.latest_pass, PT, s, auth(s), if_modified_since=old_lm)
    check("the card changed since → 200 with the new pass and a newer Last-Modified",
          st == 200 and resp.headers.get("last-modified") != old_lm, (st, old_lm, resp and resp.headers.get("last-modified")))
    new_lm = resp.headers.get("last-modified")
    st, _ = status(WP.latest_pass, PT, s, auth(s), if_modified_since=new_lm)
    check("…and 304 again right after", st == 304, st)
    yesterday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    st, _ = status(WP.latest_pass, PT, s, auth(s), if_modified_since=yesterday)
    check("a device with yesterday's pass → 200", st == 200, st)
    st, _ = status(WP.latest_pass, PT, s, "ApplePass nope", if_modified_since=new_lm)
    check("a bad token is still 401, 304 or not", st == 401, st)
    # the serial list still names a card whose record moved; the fetch is then cheap
    db.customers.update_one({"barcode_id": serials[0]}, {"$set": {"updated_at": dt.datetime.now(dt.timezone.utc)}})
    st, r = status(WP.serials_for_device, "dev1", PT, str(int(time.time()) - 5))
    nb = len(builds)
    st2, _ = status(WP.latest_pass, PT, serials[0], auth(serials[0]),
                    if_modified_since=status(WP.latest_pass, PT, serials[0], auth(serials[0]))[1].headers["last-modified"])
    check("a record touch lists the serial, and its fetch is a 304 (nothing to build)", st2 == 304, (st, st2))

    # ------------------------------------------------------------------ the queue: one worker, no repeat
    print("\nLa file : un seul ouvrier à la fois, jamais deux fois la même carte")
    WP.REFRESH_BUDGET_S = 6.0
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"reward_description": "Un massage offert"}})
    WP.queue_refresh("t1", serials, design_changed=True)
    db.wallet_refresh.update_one({"tenant_id": "t1"}, {"$set": {"draining_until": dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=30)}})
    before = pushed()
    r = WP.drain_refresh("t1", 5.0)
    check("another worker holds the shop's queue → this one answers « busy » at once, pushes nobody",
          r.get("busy") is True and r["left"] == N and pushed() == before, r)
    db.wallet_refresh.update_one({"tenant_id": "t1"}, {"$set": {"draining_until": dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)}})
    r = WP.drain_refresh("t1", 5.0)
    check("an expired lease is taken over: drained", not r.get("busy") and r["left"] == 0 and pushed() == before + N, r)
    check("…the lease is released with the queue", db.wallet_refresh.count_documents({"tenant_id": "t1"}) == 0)

    # a drain whose « mark as sent » fails half-way (MongoDB saturated, 2026-11-12)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"reward_description": "Une barbe offerte"}})
    WP.queue_refresh("t1", serials, design_changed=True)
    real_update = db.wallet_refresh.update_one
    state = {"fail": True}

    def flaky_update(flt, upd, *a, **k):
        if state["fail"] and "$pull" in upd:
            state["fail"] = False
            raise RuntimeError("connection pool paused")
        return real_update(flt, upd, *a, **k)
    db.wallet_refresh.update_one = flaky_update
    before = pushed()
    try:
        WP.drain_refresh("t1", 5.0)
    except Exception:                                       # noqa: BLE001 — may surface the failure, must not loop
        pass
    db.wallet_refresh.update_one = real_update
    first = pushed() - before
    r = WP.drain_refresh("t1", 5.0)
    check(f"a chunk leaves the queue before its push: across the failed drain and the retry, each card pushed once ({first} + {pushed() - before - first})",
          pushed() == before + N and r["left"] == 0, (first, pushed() - before, r))
    check("the queue is empty after the retry", WP.refresh_left("t1") == 0)
    # Apple itself down during a drain: the cards go back in line, nothing lost
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"reward_description": "Un shampoing offert"}})
    WP.queue_refresh("t1", serials, design_changed=True)
    real_apns = APNS.push_to_tokens
    APNS.push_to_tokens = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("APNs down"))
    r = WP.drain_refresh("t1", 5.0)
    APNS.push_to_tokens = real_apns
    check("APNs down: no crash, the cards are back in the queue", r["left"] == N and WP.refresh_left("t1") == N, r)
    before = pushed()
    r = WP.drain_refresh("t1", 5.0)
    check("…and go out at the next drain, once", pushed() == before + N and r["left"] == 0, r)

    # ------------------------------------------------------------------ the owner's follow-up call
    print("\nL'appel de suivi de la page")
    import auth as _auth
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})

    class _Tok:
        email, role, tenant_id = "o@x.fr", "business_owner", "t1"
    r = WP.owner_wallet_refresh(_Tok())
    check("nothing queued → the cheap answer", r == {"left": 0}, r)
    WP.queue_refresh("t1", serials[:2])
    db.wallet_refresh.update_one({"tenant_id": "t1"}, {"$set": {"draining_until": dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=30)}})
    r = WP.owner_wallet_refresh(_Tok())
    check("a drain already running elsewhere → « busy », the page stops asking", r.get("busy") is True and r["left"] == 2, r)
    db.wallet_refresh.delete_many({})

    # ------------------------------------------------------------------ the breaker
    print("\nLe disjoncteur : jamais plus de N pushes par appareil en 15 min, et le super admin sait pourquoi")
    db.tenants.insert_one({"id": "t2", "slug": "t2", "name": "Café Boucle", "plan": "vip", "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t2", "card_name": "BOUCLE", "reward_threshold_stamps": 10, "reward_description": "Un café"})
    for i in (1, 2):
        db.customers.insert_one({"id": f"b{i}", "tenant_id": "t2", "barcode_id": f"FT-BOUCLE0{i}", "name": f"B {i}", "visits": 1, "points": 1,
                                 "created_at": dt.datetime.now(dt.timezone.utc)})
        db.pass_registrations.insert_one({"device_id": f"bdev{i}", "serial": f"FT-BOUCLE0{i}", "push_token": f"btok{i}", "pass_type_id": PT, "tenant_id": "t2"})
    db.users.insert_one({"email": "boss@fidclic.com", "role": "super_admin"})
    from features import team_alerts as TA
    from services import mailer
    mails = []
    mailer.send = lambda to, subject, html, text=None, to_name=None, reply_to=None: (mails.append((to, subject)), {"sent": True})[1]
    TA.init(db)
    WP.STORM_MIN, WP.STORM_FACTOR = 4, 1               # 2 devices: the line is 4 pushes in the window
    got = []
    for k in range(5):                                  # a bug that changes the card and pushes, again and again
        db.customers.update_many({"tenant_id": "t2"}, {"$inc": {"visits": 1}})
        got.append(WP._notify_apple(["FT-BOUCLE01", "FT-BOUCLE02"]))
    sent = [g.get("sent", 0) for g in got]
    check(f"the first rounds go out, then the line is crossed and pushes are refused ({sent})", sent[:2] == [2, 2] and sent[2] == 0 and sent[4] == 0, got)
    check("…the refusal is said", got[2].get("throttled") == 2 and got[2]["devices"] == 0, got[2])
    rows = list(db.platform_alerts.find({"kind": "wallet_storm"}))
    check("one alert for the super admin (not one per refused push)", len(rows) == 1, len(rows))
    check("…it names the shop, the counts, the probable cause and what to do",
          rows and "Café Boucle" in rows[0]["text"] and "Cause probable" in rows[0]["detail"] and "À faire" in rows[0]["detail"], rows and rows[0]["text"])
    check("…and e-mails the super admin (platform health, on by default)", [m[0] for m in mails] == ["boss@fidclic.com"] and "Tempête" in mails[0][1], mails)
    from features import platform_security as PS
    PS.init(db) if hasattr(PS, "init") else None
    PS._db = db

    class _Boss:
        email, role, tenant_id = "boss@fidclic.com", "super_admin", None
    bell = PS.alerts(_Boss())["alerts"]
    storm = [b for b in bell if "Tempête" in b["title"]]
    check("the bell shows it as critical, with the cause in its body and a link",
          storm and storm[0]["severity"] == "critical" and "Cause probable" in storm[0]["body"] and storm[0]["action"]["href"], storm)
    WP.STORM_WINDOW = dt.timedelta(seconds=0)           # the window passed
    db.customers.update_many({"tenant_id": "t2"}, {"$inc": {"visits": 1}})
    r = WP._notify_apple(["FT-BOUCLE01", "FT-BOUCLE02"])
    check("after the window, pushes go again by themselves (the change is not lost)", r.get("sent") == 2, r)
    check("a shop under the line is never touched by another shop's storm",
          WP._storm("t1", 5) is None)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
