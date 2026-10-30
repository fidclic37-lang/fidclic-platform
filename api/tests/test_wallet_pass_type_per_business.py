"""
One Apple Pass Type ID per business (user, 2026-10-30): every FidClic card
sat in ONE Wallet stack, because Wallet groups passes by pass type id. Each
business now gets its own id and certificate, made by the platform through
the App Store Connect API — nobody does anything by hand.

  • services/asc_api       App Store Connect: ES256 token, pass type ids,
                           PASS_TYPE_ID certificates from a CSR
  • features/wallet_identities
                           one identity per business: id, certificate, key
                           (encrypted); made on the tick and, if still
                           missing, the moment a card is first downloaded;
                           retried with backoff; renewed before it expires
  • features/wallet_passes a new card gets its business's id; a card already
                           on an iPhone keeps the common id (user: « purana
                           card chalta rahe »); each pass is signed and pushed
                           with its own id's certificate

Apple is never called: its API is a fake that signs the CSR it is sent.
Run: cd api && /usr/local/bin/python3 tests/test_wallet_pass_type_per_business.py
"""
import base64
import datetime as dt
import io
import json
import os
import sys
import threading
import zipfile

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID


def _selfsigned(cn):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30)).sign(key, hashes.SHA256()))
    return key, cert


gkey, gcert = _selfsigned("Pass Type ID: pass.com.fidclic.loyalty")
ca_key, wwdr = _selfsigned("Fake WWDR")
asc_key = ec.generate_private_key(ec.SECP256R1())
os.environ.update({
    "APPLE_PASS_TYPE_ID": "pass.com.fidclic.loyalty",
    "APPLE_TEAM_ID": "TEAM123456",
    "APPLE_PASS_CERT_B64": base64.b64encode(gcert.public_bytes(serialization.Encoding.PEM)).decode(),
    "APPLE_PASS_KEY_B64": base64.b64encode(gkey.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode(),
    "APPLE_WWDR_B64": base64.b64encode(wwdr.public_bytes(serialization.Encoding.PEM)).decode(),
    "PASS_AUTH_SECRET": "test-secret", "JWT_SECRET": "test-jwt-secret", "DISABLE_SEED": "1",
    "ASC_KEY_ID": "KEY1234567", "ASC_ISSUER_ID": "11111111-2222-3333-4444-555555555555",
    "ASC_PRIVATE_KEY": base64.b64encode(asc_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode(),
})

passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))


class FakeApple:
    """App Store Connect as far as we use it. Signs every CSR with a fake CA,
    the way Apple returns a certificate for the CSR's key."""

    def __init__(self):
        self.calls = []
        self.types = {}          # identifier → resource id
        self.fail = None         # (method, path-fragment, status)
        self.cert_wants_identifier = False
        self.lock = threading.Lock()
        self.delay = 0.0         # seconds Apple takes to answer

    def __call__(self, method, url, headers, body):
        if self.delay:
            import time
            time.sleep(self.delay)
        with self.lock:
            self.calls.append((method, url, json.loads(body) if body else None, headers))
        path = url.split("api.appstoreconnect.apple.com", 1)[-1]
        if self.fail and method == self.fail[0] and self.fail[1] in path:
            return self.fail[2], {"errors": [{"status": str(self.fail[2]), "detail": "simulated"}]}
        if method == "GET" and path.startswith("/v1/passTypeIds"):
            ident = path.split("filter%5Bidentifier%5D=", 1)[-1].split("&")[0] if "filter" in path else None
            from urllib.parse import unquote
            ident = unquote(ident) if ident else None
            rows = [{"type": "passTypeIds", "id": rid, "attributes": {"identifier": i}}
                    for i, rid in self.types.items() if ident in (None, i)]
            return 200, {"data": rows}
        if method == "POST" and path == "/v1/passTypeIds":
            ident = json.loads(body)["data"]["attributes"]["identifier"]
            if ident in self.types:
                return 409, {"errors": [{"status": "409", "detail": "already exists"}]}
            rid = f"RID{len(self.types) + 1:04d}"
            self.types[ident] = rid
            return 201, {"data": {"type": "passTypeIds", "id": rid, "attributes": {"identifier": ident}}}
        if method == "POST" and path == "/v1/certificates":
            d = json.loads(body)["data"]
            rel = d["relationships"]["passTypeId"]["data"]["id"]
            ident = next((i for i, r in self.types.items() if r == rel), None)
            if self.cert_wants_identifier:
                if rel not in self.types:
                    return 404, {"errors": [{"status": "404", "detail": "There is no identifier with ID 'null'"}]}
                ident = rel
            if not ident:
                return 404, {"errors": [{"status": "404", "detail": "no such pass type"}]}
            csr = x509.load_pem_x509_csr(d["attributes"]["csrContent"].encode())
            now = dt.datetime.now(dt.timezone.utc)
            name = x509.Name([x509.NameAttribute(NameOID.USER_ID, ident),
                              x509.NameAttribute(NameOID.COMMON_NAME, f"Pass Type ID: {ident}"),
                              x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "TEAM123456")])
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(wwdr.subject).public_key(csr.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now)
                    .not_valid_after(now + dt.timedelta(days=395)).sign(ca_key, hashes.SHA256()))
            return 201, {"data": {"type": "certificates", "id": f"CERT-{ident}", "attributes": {
                "certificateContent": base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode(),
                "expirationDate": (now + dt.timedelta(days=395)).isoformat(), "certificateType": "PASS_TYPE_ID"}}}
        return 400, {"errors": [{"status": "400", "detail": f"unexpected {method} {path}"}]}


with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import jwt as pyjwt
    from fastapi import HTTPException
    from features import wallet_passes as WP
    from features import wallet_identities as WI
    from services import asc_api as A
    from services import apns_passes as AP

    db = server.db
    WP._db = db
    WI._db = db
    apple = FakeApple()
    A._send = apple
    now = dt.datetime.now(dt.timezone.utc)

    def tenant(tid, slug, name, **kw):
        db.tenants.insert_one({"id": tid, "slug": slug, "name": name, "is_active": True, "plan": "vip",
                               "subscription_status": "active", **kw})
        db.card_templates.insert_one({"tenant_id": tid, "card_name": name, "reward_threshold_stamps": 10, "poster_style": False})

    def customer(cid, tid, serial, **kw):
        db.customers.insert_one({"id": cid, "tenant_id": tid, "barcode_id": serial, "name": cid, "visits": 1,
                                 "created_at": now, **kw})

    def pass_of(resp_or_bytes):
        data = resp_or_bytes if isinstance(resp_or_bytes, bytes) else resp_or_bytes.body
        z = zipfile.ZipFile(io.BytesIO(data))
        pj = json.loads(z.read("pass.json"))
        certs = pkcs7.load_der_pkcs7_certificates(z.read("signature"))
        signer = [c for c in certs if c.subject != wwdr.subject][0]
        cn = signer.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        return pj, cn

    tenant("6ff2a3ba-152d-47fd-b23b-91930b4be55d", "royal-trim-liberte", "ROYAL TRIM LIBÉRTÉ")
    tenant("t-cafe", "cafe-lumiere", "Café Lumière")
    tenant("t-closed", "ferme", "Fermé", is_active=False)
    RT = "6ff2a3ba-152d-47fd-b23b-91930b4be55d"

    print("\nThe id of a business (unit)")
    i1 = WI.identifier_for(db.tenants.find_one({"id": RT}))
    check(f"prefix + slug + tenant mark ({i1})", i1 == "pass.com.fidclic.royal-trim-liberte-6ff2a3")
    check("accents and spaces cleaned", WI.identifier_for({"id": "abcdef12-0000", "slug": "", "name": "Crêpe & Café du Port"})
          == "pass.com.fidclic.crepe-cafe-du-port-abcdef")
    long_id = WI.identifier_for({"id": "aaaaaa00", "slug": "x" * 200})
    check(f"a long name is cut ({len(long_id)} chars)", len(long_id) <= 64 and long_id.endswith("-aaaaaa"))
    check("no name at all → still valid", WI.identifier_for({"id": "bbbbbb00"}) == "pass.com.fidclic.b-bbbbbb")
    check("two businesses with the same slug → two ids",
          WI.identifier_for({"id": "111111aa", "slug": "barber"}) != WI.identifier_for({"id": "222222aa", "slug": "barber"}))
    import re
    check("only letters, digits, dots, dashes", all(re.fullmatch(r"[a-z0-9.\-]+", x) for x in (i1, long_id)))

    print("\nThe key is never stored readable (unit)")
    secret = WI._seal(b"-----BEGIN PRIVATE KEY-----abc")
    check("sealed ≠ plain", b"abc" not in secret.encode())
    check("opened again", WI._open(secret) == b"-----BEGIN PRIVATE KEY-----abc")
    check("garbage → None, no crash", WI._open("not-a-token") is None)

    print("\nThe App Store Connect token (unit)")
    tok = A._token()
    hdr = pyjwt.get_unverified_header(tok)
    claims = pyjwt.decode(tok, asc_key.public_key(), algorithms=["ES256"], audience="appstoreconnect-v1")
    check("ES256 with the key id", hdr["alg"] == "ES256" and hdr["kid"] == "KEY1234567")
    check("issuer, audience, ≤ 20 minutes", claims["iss"] == "11111111-2222-3333-4444-555555555555"
          and claims["exp"] - claims["iat"] <= 20 * 60)
    check("configured", A.configured())
    saved = os.environ.pop("ASC_KEY_ID")
    check("no key id → not configured, no crash", not A.configured())
    os.environ["ASC_KEY_ID"] = saved

    print("\nMaking a business's identity")
    r = WI.ensure(RT)
    row = db.wallet_pass_types.find_one({"tenant_id": RT})
    check(f"ready ({r.get('status')}, {r.get('error')})", row and row["status"] == "ready")
    check("Apple was asked for the id, then the certificate",
          [c[0] + " " + c[1].split(".com", 1)[-1].split("?")[0] for c in apple.calls][-2:] == ["POST /v1/passTypeIds", "POST /v1/certificates"],
          [c[1] for c in apple.calls])
    cert_req = [c for c in apple.calls if c[1].endswith("/v1/certificates")][-1][2]["data"]
    check("certificate type PASS_TYPE_ID with the pass type relationship",
          cert_req["attributes"]["certificateType"] == "PASS_TYPE_ID" and cert_req["relationships"]["passTypeId"]["data"]["type"] == "passTypeIds")
    check("every call carries the bearer token", all(c[3].get("Authorization", "").startswith("Bearer ") for c in apple.calls))
    check("the private key is stored sealed", "PRIVATE KEY" not in json.dumps(row, default=str))
    check("the expiry is kept", isinstance(row.get("expires_at"), dt.datetime))
    n = len(apple.calls)
    WI.ensure(RT)
    check("ready → nothing asked again", len(apple.calls) == n)
    check("tenant_type gives the id", WI.tenant_type(RT) == i1)
    ident = WI.identity_for_type(i1)
    check("identity opens: certificate + key", ident and b"BEGIN CERTIFICATE" in ident["cert_pem"] and b"PRIVATE KEY" in ident["key_pem"])

    print("\nThe id already exists at Apple (a second try after a crash)")
    i_cafe = WI.identifier_for(db.tenants.find_one({"id": "t-cafe"}))
    apple.types[i_cafe] = "RIDEXIST"
    WI.ensure("t-cafe")
    check("reused, ready", db.wallet_pass_types.find_one({"tenant_id": "t-cafe"})["status"] == "ready")
    check("no second POST of the id", not any(c[0] == "POST" and c[1].endswith("/v1/passTypeIds")
                                              and c[2]["data"]["attributes"]["identifier"] == i_cafe for c in apple.calls))

    print("\nApple wants the identifier string in the relationship (its docs disagree)")
    tenant("t-alt", "alt", "Alt")
    apple.cert_wants_identifier = True
    WI.ensure("t-alt")
    apple.cert_wants_identifier = False
    check("retried with the identifier → ready", db.wallet_pass_types.find_one({"tenant_id": "t-alt"})["status"] == "ready")

    print("\nApple fails: kept, retried later, never twice at once")
    tenant("t-fail", "fail", "Fail")
    apple.fail = ("POST", "/v1/passTypeIds", 500)
    out = WI.ensure("t-fail")
    rowf = db.wallet_pass_types.find_one({"tenant_id": "t-fail"})
    check(f"failed with the reason ({rowf.get('error')})", rowf["status"] == "failed" and "500" in (rowf.get("error") or ""))
    check("a next try is planned", rowf.get("next_try_at") and WI._aware(rowf["next_try_at"]) > now)
    check("ensure never raises", isinstance(out, dict))
    n = len(apple.calls)
    WI.ensure("t-fail")
    check("before the next try → Apple not asked", len(apple.calls) == n)
    apple.fail = None
    WI.ensure("t-fail", force=True)
    check("forced (the download path) → ready", db.wallet_pass_types.find_one({"tenant_id": "t-fail"})["status"] == "ready")

    tenant("t-race", "race", "Race")
    before = len([c for c in apple.calls if c[1].endswith("/v1/passTypeIds") and c[0] == "POST"])
    ts = [threading.Thread(target=WI.ensure, args=("t-race",)) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    after = len([c for c in apple.calls if c[1].endswith("/v1/passTypeIds") and c[0] == "POST"])
    check(f"8 at once → one creation ({after - before})", after - before == 1)

    saved = os.environ.pop("ASC_PRIVATE_KEY")
    tenant("t-noasc", "noasc", "NoAsc")
    out = WI.ensure("t-noasc")
    os.environ["ASC_PRIVATE_KEY"] = saved
    check("no API key → skipped, no crash, nothing stored as failed",
          out.get("status") == "skipped" and not db.wallet_pass_types.find_one({"tenant_id": "t-noasc", "status": "failed"}))

    print("\nThe tick: every business, retries, renewals")
    db.wallet_pass_types.delete_many({"tenant_id": {"$in": ["t-noasc"]}})
    tenant("t-empty", "empty", "Empty")          # fix 3: no customer yet → no id asked of Apple
    customer("c-noasc", "t-noasc", "FT-NOASC001")
    res = WI.run_due(now)
    check(f"the business without an id gets one ({res})", db.wallet_pass_types.find_one({"tenant_id": "t-noasc", "status": "ready"}))
    check("a closed business is skipped", not db.wallet_pass_types.find_one({"tenant_id": "t-closed"}))
    check("a business with no customer yet is skipped (fake signups make no ids)",
          not db.wallet_pass_types.find_one({"tenant_id": "t-empty"}))
    db.wallet_pass_types.update_one({"tenant_id": "t-cafe"}, {"$set": {"expires_at": now + dt.timedelta(days=10)}})
    old_cert = db.wallet_pass_types.find_one({"tenant_id": "t-cafe"})["cert_pem"]
    WI.run_due(now)
    rc = db.wallet_pass_types.find_one({"tenant_id": "t-cafe"})
    check("a certificate 10 days from expiry is renewed (same id, new certificate)",
          rc["cert_pem"] != old_cert and rc["identifier"] == i_cafe and WI._aware(rc["expires_at"]) > now + dt.timedelta(days=300))
    n = len(apple.calls)
    WI.run_due(now)
    check("nothing due → Apple not asked", len(apple.calls) == n)
    check("the tick runs it", "wallet_identities" in server.tick_pass(now))

    print("\nCards: a new card gets the business's id, an old card keeps the common one")
    customer("n1", RT, "FT-NEW00001")
    resp = WP.download_apple_pass("FT-NEW00001")
    pj, cn = pass_of(resp)
    check(f"new card → the business's id ({pj['passTypeIdentifier']})", pj["passTypeIdentifier"] == i1)
    check(f"signed with the business's certificate ({cn})", cn == f"Pass Type ID: {i1}")
    check("the customer is pinned to it", db.customers.find_one({"id": "n1"}).get("apple_pass_type") == i1)
    check("team id unchanged", pj["teamIdentifier"] == "TEAM123456")

    customer("o1", RT, "FT-OLD00001", apple_downloaded_at=now - dt.timedelta(days=20))
    db.pass_registrations.insert_one({"device_id": "DEVOLD000000000000001", "serial": "FT-OLD00001", "push_token": "tokOLD1",
                                      "pass_type_id": "pass.com.fidclic.loyalty", "tenant_id": RT, "created_at": now})
    pj, cn = pass_of(WP.download_apple_pass("FT-OLD00001"))
    check("card already on an iPhone → common id, so no second card", pj["passTypeIdentifier"] == "pass.com.fidclic.loyalty"
          and cn == "Pass Type ID: pass.com.fidclic.loyalty")

    customer("o2", RT, "FT-OLD00002", wallet_removed_at=now - dt.timedelta(days=2), apple_downloaded_at=now - dt.timedelta(days=30))
    pj, _ = pass_of(WP.download_apple_pass("FT-OLD00002"))
    check("removed from Wallet then added again → the business's id", pj["passTypeIdentifier"] == i1)

    auth_h = lambda s: f"ApplePass {WP._auth_token(s)}"
    r = WP.latest_pass("pass.com.fidclic.loyalty", "FT-OLD00001", auth_h("FT-OLD00001"))
    check("Wallet updating an old card gets the common id back", pass_of(r)[0]["passTypeIdentifier"] == "pass.com.fidclic.loyalty")
    r = WP.latest_pass(i1, "FT-NEW00001", auth_h("FT-NEW00001"))
    check("Wallet updating a new card gets the business's id back", pass_of(r)[0]["passTypeIdentifier"] == i1)
    try:
        WP.latest_pass(i_cafe, "FT-NEW00001", auth_h("FT-NEW00001"))
        check("another business's id for this card → 404", False)
    except HTTPException as e:
        check("another business's id for this card → 404", e.status_code == 404)

    print("\nNo identity yet: made at the first download; if Apple fails, the card still works")
    tenant("t-late", "late", "Late")
    customer("l1", "t-late", "FT-LATE0001")
    pj, _ = pass_of(WP.download_apple_pass("FT-LATE0001"))
    check("made on the spot → the business's id", pj["passTypeIdentifier"] == WI.identifier_for(db.tenants.find_one({"id": "t-late"})))
    tenant("t-down", "down", "Down")
    customer("d1", "t-down", "FT-DOWN0001")
    apple.fail = ("POST", "/v1/passTypeIds", 503)
    pj, cn = pass_of(WP.download_apple_pass("FT-DOWN0001"))
    apple.fail = None
    check("Apple down → the common id, card works", pj["passTypeIdentifier"] == "pass.com.fidclic.loyalty")
    check("…and the failure is kept for the super admin", db.wallet_pass_types.find_one({"tenant_id": "t-down"})["status"] == "failed")

    print("\nMulti-store: one id per business")
    db.branches.insert_many([{"id": "sA", "tenant_id": RT, "name": "Liberté"}, {"id": "sB", "tenant_id": RT, "name": "Palissy"}])
    customer("m1", RT, "FT-MSA00001", branch_id="sA")
    customer("m2", RT, "FT-MSB00001", branch_id="sB")
    a = pass_of(WP.download_apple_pass("FT-MSA00001"))[0]["passTypeIdentifier"]
    b = pass_of(WP.download_apple_pass("FT-MSB00001"))[0]["passTypeIdentifier"]
    check("two stores, same id", a == b == i1)

    print("\nPushes go out per id, each with its own certificate")
    db.pass_registrations.insert_one({"device_id": "DEVNEW000000000000001", "serial": "FT-NEW00001", "push_token": "tokNEW1",
                                      "pass_type_id": i1, "tenant_id": RT, "created_at": now})
    sent = []

    def fake_push(tokens, topic=None, cert_paths=None):
        sent.append({"tokens": list(tokens), "topic": topic, "cert": open(cert_paths[0], "rb").read() if cert_paths else None})
        return {"sent": len(tokens), "gone": [], "failed": 0, "errors": [],
                "results": [{"token": t, "status": 200, "reason": "", "apns_id": "x"} for t in tokens]}
    real_push, real_conf = AP.push_to_tokens, AP.is_configured
    AP.push_to_tokens, AP.is_configured = fake_push, (lambda: True)
    try:
        WP._notify_apple(["FT-OLD00001", "FT-NEW00001"])
    finally:
        AP.push_to_tokens, AP.is_configured = real_push, real_conf
    by_topic = {(s["topic"] or "pass.com.fidclic.loyalty"): s for s in sent}
    check(f"two pushes, one per id ({sorted(by_topic)})", set(by_topic) == {"pass.com.fidclic.loyalty", i1})
    check("old card's token with the common id", by_topic.get("pass.com.fidclic.loyalty", {}).get("tokens") == ["tokOLD1"])
    check("new card's token with the business's certificate", by_topic.get(i1, {}).get("tokens") == ["tokNEW1"]
          and b"BEGIN CERTIFICATE" in (by_topic.get(i1, {}).get("cert") or b"")
          and by_topic[i1]["cert"] != base64.b64decode(os.environ["APPLE_PASS_CERT_B64"]))

    print("\nA rush of first downloads while the id is being made (fix 1)")
    tenant("t-rush", "rush", "Rush")
    for i in range(20):
        customer(f"ru{i}", "t-rush", f"FT-RUSH{i:04d}")
    apple.delay = 0.3
    got = []
    ths = [threading.Thread(target=lambda i=i: got.append(WP._card_payload(f"FT-RUSH{i:04d}", make=True)["_pass_type"]))
           for i in range(20)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    apple.delay = 0.0
    own = WI.tenant_type("t-rush")
    check(f"20 at once → all get the business's id ({sum(g == own for g in got)}/20)", own and got.count(own) == 20, got)

    print("\nAn iPhone registers only under the card's own id (fix 2)")
    au = f"ApplePass {WP._auth_token('FT-NEW00001')}"

    def reg_status(ptype, dev):
        try:
            return WP.register_device(dev, ptype, "FT-NEW00001", WP.Registration(pushToken=f"tok{dev}"), au).status_code
        except HTTPException as e:
            return e.status_code
    check("under another business's id → 404", reg_status(i_cafe, "DEVX0000000000000001") == 404)
    check("…nothing stored", not db.pass_registrations.find_one({"device_id": "DEVX0000000000000001"}))
    check("under an id no business owns → as before (201): nothing to protect, no edge case broken",
          reg_status("pass.com.other.x", "DEVX0000000000000002") == 201)
    check("under its business's id → 201", reg_status(i1, "DEVX0000000000000003") == 201)
    check("under the common id (an old card) → 201", reg_status("pass.com.fidclic.loyalty", "DEVX0000000000000004") == 201)

    print("\nSuper admin makes one business's id now (the first real test, fix 4)")
    tenant("t-now", "now", "Now")
    HW = {"Authorization": "Bearer " + auth.create_access_token({"sub": "sa@x.fr", "role": "super_admin"})}
    HOW = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t-now"})}
    import asyncio as _aio
    import httpx as _hx

    def post(path, h):
        async def run():
            async with _hx.AsyncClient(transport=_hx.ASGITransport(app=server.app), base_url="http://t") as ac:
                return await ac.post(path, headers=h)
        return _aio.get_event_loop().run_until_complete(run())
    check("a business owner → 403", post("/api/admin/wallet-identities/t-now/make", HOW).status_code == 403)
    r = post("/api/admin/wallet-identities/t-now/make", HW)
    check(f"super admin → made, even without customers ({r.status_code} {r.text[:120]})",
          r.status_code == 200 and r.json().get("status") == "ready" and "PRIVATE KEY" not in r.text)
    check("unknown business → 404", post("/api/admin/wallet-identities/nope/make", HW).status_code == 404)

    print("\nSuper admin sees where each business stands")
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "sa@x.fr", "role": "super_admin"})}
    HO = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": RT})}
    import asyncio
    import httpx

    def get(path, h):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as ac:
                return await ac.get(path, headers=h)
        return asyncio.get_event_loop().run_until_complete(run())
    r = get("/api/admin/wallet-identities", H)
    check(f"super admin → 200 ({r.status_code})", r.status_code == 200, r.text[:160])
    body = r.json() if r.status_code == 200 else {}
    rows = {x["tenant_id"]: x for x in body.get("rows", [])}
    check("each business: id, status, expiry", rows.get(RT, {}).get("identifier") == i1 and rows[RT]["status"] == "ready"
          and rows[RT].get("expires_at"))
    check("the failure shows its reason", rows.get("t-down", {}).get("status") == "failed" and rows["t-down"].get("error"))
    check("no key or certificate in the answer", "PRIVATE KEY" not in r.text and "BEGIN CERTIFICATE" not in r.text and "key_enc" not in r.text)
    check("counts", body.get("counts", {}).get("ready", 0) >= 5 and body.get("counts", {}).get("failed") == 1)
    check("a business owner → 403", get("/api/admin/wallet-identities", HO).status_code == 403)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
