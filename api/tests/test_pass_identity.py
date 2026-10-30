"""
One Apple Pass Type ID per business (user, 2026-10-30: « saare cards created
from fidclic is showing side by side in the apple wallet »). Wallet groups the
passes that share a pass type identifier; every FidClic card shared one.

  • a business can hold its own identity (pass type id + certificate + key,
    the key encrypted at rest);
  • a card is pinned to one pass type id the first time its pass is made —
    new cards of a business with an identity get it; cards already in a
    Wallet keep the shared one (user: « waise hi chalne do »);
  • every pass is signed with the certificate of ITS pass type id, every
    update an iPhone asks for is served with the id it holds, and every push
    goes out with the topic and certificate of the registration's id;
  • super admin: the business's identity status, a manual upload (fallback
    to the automatic creation, next PR), and switching it off for new cards.

Run: cd api && /usr/local/bin/python3 tests/test_pass_identity.py
"""
import asyncio
import base64
import datetime as dt
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
DEFAULT_PT = "pass.com.fidclic.loyalty"


def selfsigned(pt, days=365, cn=None):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.USER_ID, pt),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn or f"Pass Type ID: {pt}")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=2))
            .not_valid_after(now + dt.timedelta(days=days)).sign(key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM).decode(),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()).decode(), cert)


DEF_CERT, DEF_KEY, _ = selfsigned(DEFAULT_PT)
WWDR, _, _ = selfsigned("wwdr")
os.environ.update({
    "APPLE_PASS_TYPE_ID": DEFAULT_PT, "APPLE_TEAM_ID": "TEAM123456",
    "APPLE_PASS_CERT_B64": base64.b64encode(DEF_CERT.encode()).decode(),
    "APPLE_PASS_KEY_B64": base64.b64encode(DEF_KEY.encode()).decode(),
    "APPLE_WWDR_B64": base64.b64encode(WWDR.encode()).decode(),
    "PASS_AUTH_SECRET": "test-secret", "JWT_SECRET": "test-jwt-pass-identity", "DISABLE_SEED": "1",
    "PASS_IDENTITY_SECRET": "a-long-random-secret-for-tests-only",
})
passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))


def raises(fn):
    try:
        fn()
    except ValueError as e:
        return str(e) or True
    return False


def main():
    import server
    import auth
    import httpx
    from features import wallet_passes as W
    from services import apns_passes as AP
    from services import pass_identity as PI

    db = server.db
    W._db = db
    PI.init(db)
    now = dt.datetime.now(dt.timezone.utc)
    for t in ("t1", "t2", "t3"):
        db.tenants.insert_one({"id": t, "slug": t, "name": t.upper(), "plan": "vip", "subscription_status": "active", "is_active": True})
        db.users.insert_one({"email": f"o@{t}.fr", "role": "business_owner", "tenant_id": t, "active": True})

    def cust(cid, t, **f):
        db.customers.insert_one({"id": cid, "tenant_id": t, "name": cid, "barcode_id": f"FT-{cid.upper()}",
                                 "created_at": now, "visits": 2, **f})
        return f"FT-{cid.upper()}"

    T1_PT = "pass.com.fidclic.t1"
    T1_CERT, T1_KEY, t1_cert_obj = selfsigned(T1_PT)

    print("\nSaving a business's identity (unit)")
    check("no identity yet → the shared id", PI.for_new_card("t1") == DEFAULT_PT)
    check("pass type id must start with « pass. »", raises(lambda: PI.save("t1", "com.x", T1_CERT, T1_KEY, source="manual")))
    other_cert, other_key, _ = selfsigned("pass.com.fidclic.other")
    check("certificate of another id → refused", raises(lambda: PI.save("t1", T1_PT, other_cert, other_key, source="manual")))
    check("key that is not the certificate's → refused", raises(lambda: PI.save("t1", T1_PT, T1_CERT, other_key, source="manual")))
    old_cert, old_key, _ = selfsigned(T1_PT, days=-1)
    check("expired certificate → refused", raises(lambda: PI.save("t1", T1_PT, old_cert, old_key, source="manual")))
    check("garbage PEM → refused", raises(lambda: PI.save("t1", T1_PT, "not a cert", "not a key", source="manual")))
    check("the shared id can never be given to one business",
          raises(lambda: PI.save("t1", DEFAULT_PT, DEF_CERT, DEF_KEY, source="manual")))
    secret = os.environ.pop("PASS_IDENTITY_SECRET")
    check("no PASS_IDENTITY_SECRET → refused (a key is never stored in clear)",
          raises(lambda: PI.save("t1", T1_PT, T1_CERT, T1_KEY, source="manual")))
    os.environ["PASS_IDENTITY_SECRET"] = secret
    st = PI.save("t1", T1_PT, T1_CERT, T1_KEY, source="manual")
    check("a valid identity is saved", st.get("pass_type_id") == T1_PT and st.get("active") is True, st)
    check("…its status never carries the key", "PRIVATE KEY" not in json.dumps(st, default=str))
    doc = db.pass_identities.find_one({"tenant_id": "t1"})
    check("the key is encrypted at rest", "PRIVATE KEY" not in json.dumps(doc, default=str))
    check("the certificate's end date is kept", isinstance(doc.get("expires_at"), dt.datetime))
    check("another business cannot take the same id", raises(lambda: PI.save("t2", T1_PT, T1_CERT, T1_KEY, source="manual")))
    check("t1's new cards → t1's id", PI.for_new_card("t1") == T1_PT)
    check("t2 (none) → the shared id", PI.for_new_card("t2") == DEFAULT_PT)
    ident = PI.get(T1_PT)
    check("get(t1's id) → its certificate and decrypted key", ident and ident.cert_pem == T1_CERT.encode()
          and b"PRIVATE KEY" in ident.key_pem)
    check("get(shared id) → the environment's identity", PI.get(DEFAULT_PT) and PI.get(DEFAULT_PT).pass_type_id == DEFAULT_PT)
    check("get(unknown) → None", PI.get("pass.com.nobody") is None)
    check("get(None) → the shared identity", PI.get(None).pass_type_id == DEFAULT_PT)

    print("\nWhich id a card gets (pinned once)")
    new = cust("new", "t1")
    legacy_added = cust("legacy1", "t1", wallet_added_at=now - dt.timedelta(days=9))
    legacy_dl = cust("legacy2", "t1", apple_downloaded_at=now - dt.timedelta(days=2))
    legacy_reg = cust("legacy3", "t1")
    db.pass_registrations.insert_one({"device_id": "D3", "serial": legacy_reg, "push_token": "tok3",
                                      "pass_type_id": DEFAULT_PT, "tenant_id": "t1"})
    google_only = cust("android", "t1", google_added_at=now - dt.timedelta(days=1))
    store_b = cust("storeb", "t1", branch_id="B")
    t2c = cust("t2c", "t2")
    pin = lambda s: PI.pin(db.customers.find_one({"barcode_id": s}))   # noqa: E731
    check("a new card of t1 → t1's id", pin(new) == T1_PT)
    check("…kept on the client", db.customers.find_one({"barcode_id": new}).get("apple_pass_type_id") == T1_PT)
    check("already in a Wallet (added) → keeps the shared id", pin(legacy_added) == DEFAULT_PT)
    check("already downloaded → keeps the shared id", pin(legacy_dl) == DEFAULT_PT)
    check("registered on an iPhone → keeps the shared id", pin(legacy_reg) == DEFAULT_PT)
    check("only in Google Wallet → may take t1's id", pin(google_only) == T1_PT)
    check("another store of t1 → the business's id (one per business)", pin(store_b) == T1_PT)
    check("t2's card → the shared id", pin(t2c) == DEFAULT_PT)
    check("empty customer → the shared id, nothing written", PI.pin({}) == DEFAULT_PT)

    print("\nThe pass: id in pass.json, signed with that id's certificate")

    def bundle(serial, pt=None):
        resp = W._pkpass_response(serial, pt) if pt else W._pkpass_response(serial)
        z = zipfile.ZipFile(io.BytesIO(resp.body))
        signer = pkcs7.load_der_pkcs7_certificates(z.read("signature"))
        return json.loads(z.read("pass.json")), {c.subject.rfc4514_string() for c in signer}

    pj, signers = bundle(new)
    check("t1's new card → passTypeIdentifier = t1's id", pj["passTypeIdentifier"] == T1_PT, pj["passTypeIdentifier"])
    check("…signed with t1's certificate", any(T1_PT in s for s in signers), signers)
    pj, signers = bundle(legacy_added)
    check("t1's old card → the shared id, the shared certificate",
          pj["passTypeIdentifier"] == DEFAULT_PT and any(DEFAULT_PT in s for s in signers), (pj["passTypeIdentifier"], signers))
    pj, _ = bundle(t2c)
    check("t2's card → the shared id", pj["passTypeIdentifier"] == DEFAULT_PT)
    check("the team id is the same for every id", pj["teamIdentifier"] == "TEAM123456")

    print("\nAn iPhone asks for the card under the id it holds")
    auth_h = lambda s: f"ApplePass {W._auth_token(s)}"     # noqa: E731
    r = W.latest_pass(DEFAULT_PT, new, auth_h(new))
    z = zipfile.ZipFile(io.BytesIO(r.body))
    check("asked under the shared id → served under the shared id (never switched under the iPhone)",
          json.loads(z.read("pass.json"))["passTypeIdentifier"] == DEFAULT_PT)
    r = W.latest_pass(T1_PT, new, auth_h(new))
    check("asked under t1's id → t1's id",
          json.loads(zipfile.ZipFile(io.BytesIO(r.body)).read("pass.json"))["passTypeIdentifier"] == T1_PT)
    try:
        W.latest_pass("pass.com.nobody", new, auth_h(new))
        code = 200
    except Exception as e:                       # noqa: BLE001
        code = getattr(e, "status_code", 500)
    check(f"asked under an unknown id → 404 ({code})", code == 404)
    try:
        W.latest_pass(T1_PT, t2c, auth_h(t2c))
        code = 200
    except Exception as e:                       # noqa: BLE001
        code = getattr(e, "status_code", 500)
    check(f"another business's id for t2's card → 404 ({code})", code == 404)

    print("\nPushes: grouped by id, each with its topic and certificate")
    calls = []

    def fake_push(tokens, pass_type_id=None):
        calls.append((sorted(tokens), pass_type_id))
        return {"sent": len(tokens), "gone": [], "failed": 0, "errors": [],
                "results": [{"token": t, "status": 200} for t in tokens]}
    AP.push_to_tokens, AP.is_configured = fake_push, (lambda: True)
    db.pass_registrations.insert_many([
        {"device_id": "DN", "serial": new, "push_token": "tokN", "pass_type_id": T1_PT, "tenant_id": "t1"},
        {"device_id": "DS", "serial": store_b, "push_token": "tokS", "pass_type_id": T1_PT, "tenant_id": "t1"}])
    W._notify_apple([new, legacy_reg, store_b])
    by = {pt: toks for toks, pt in calls}
    check("two pushes: one per id", len(calls) == 2, calls)
    check("t1's id → its two iPhones", by.get(T1_PT) == ["tokN", "tokS"], calls)
    check("shared id → the old card's iPhone", (by.get(DEFAULT_PT) or by.get(None)) == ["tok3"], calls)

    seen = {}

    class FakeClient:
        def __init__(self, http2=True, cert=None, timeout=None):
            seen["cert"] = cert

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, content=None):
            seen["topic"] = headers.get("apns-topic")

            class R:
                status_code = 200
                headers = {"apns-id": "x"}
            return R()
    import importlib
    AP_real = importlib.reload(AP)
    real_client = httpx.Client
    httpx.Client = FakeClient
    try:
        AP_real.push_to_tokens(["tokN"], pass_type_id=T1_PT)
        cert_path = seen["cert"][0] if seen.get("cert") else ""
        check("APNs topic = t1's id", seen.get("topic") == T1_PT, seen)
        check("…with t1's certificate", cert_path and open(cert_path).read() == T1_CERT, cert_path)
        AP_real.push_to_tokens(["tok3"])
        check("no id → the shared topic", seen.get("topic") == DEFAULT_PT, seen)
        AP_real.push_to_tokens(["tokX"], pass_type_id="pass.com.nobody")
        check("unknown id → nothing sent to Apple", seen.get("topic") == DEFAULT_PT, seen)
    finally:
        httpx.Client = real_client

    print("\nSuper admin: status, manual upload, off for new cards")

    def call(method, path, token=None, body=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as ac:
                h = {"Authorization": f"Bearer {token}"} if token else {}
                return await ac.request(method, path, headers=h, json=body)
        return asyncio.get_event_loop().run_until_complete(run())
    boss = auth.create_access_token({"sub": "boss@fidclic.com", "role": "super_admin"})
    owner = auth.create_access_token({"sub": "o@t1.fr", "role": "business_owner", "tenant_id": "t1"})
    r = call("GET", "/api/admin/commerces/t1/pass-identity", boss)
    d = r.json() if r.status_code == 200 else {}
    check(f"status 200 ({r.status_code})", r.status_code == 200, r.text[:200])
    check("t1: its id, manual, active, end date", d.get("pass_type_id") == T1_PT and d.get("source") == "manual"
          and d.get("active") is True and d.get("expires_at"), d)
    check("…how many cards are on it", d.get("cards") == 3, d)
    check("…never the key", "PRIVATE" not in r.text)
    r = call("GET", "/api/admin/commerces/t2/pass-identity", boss)
    check("t2: none → the shared id", r.status_code == 200 and r.json().get("pass_type_id") is None
          and r.json().get("shared") == DEFAULT_PT, r.text[:200])
    T3_PT = "pass.com.fidclic.t3"
    T3_CERT, T3_KEY, _ = selfsigned(T3_PT)
    body = {"pass_type_id": T3_PT, "certificate_pem": T3_CERT, "key_pem": T3_KEY}
    check("a business owner cannot upload → 403", call("POST", "/api/admin/commerces/t3/pass-identity", owner, body).status_code == 403)
    check("no token → 401/403", call("POST", "/api/admin/commerces/t3/pass-identity", None, body).status_code in (401, 403))
    bad = dict(body, key_pem=other_key)
    r = call("POST", "/api/admin/commerces/t3/pass-identity", boss, bad)
    check(f"a mismatched key → 400 with the reason ({r.status_code})", r.status_code == 400 and r.json().get("detail"), r.text[:200])
    r = call("POST", "/api/admin/commerces/t3/pass-identity", boss, body)
    check(f"super admin uploads t3's identity → 200 ({r.status_code})", r.status_code == 200, r.text[:200])
    check("…the answer has no key", "PRIVATE" not in r.text)
    check("unknown business → 404", call("POST", "/api/admin/commerces/nope/pass-identity", boss, body).status_code == 404)
    r = call("POST", "/api/admin/commerces/t1/pass-identity/active", boss, {"active": False})
    check(f"t1 off for new cards → 200 ({r.status_code})", r.status_code == 200, r.text[:200])
    later = cust("later", "t1")
    check("a new t1 card now → the shared id", pin(later) == DEFAULT_PT)
    pj, signers = bundle(new)
    check("a card already on t1's id keeps it and its signature", pj["passTypeIdentifier"] == T1_PT and any(T1_PT in s for s in signers))
    T1B = "pass.com.fidclic.t1b"
    t1b_cert, t1b_key, _ = selfsigned(T1B)
    r = call("POST", "/api/admin/commerces/t1/pass-identity", boss,
             {"pass_type_id": T1B, "certificate_pem": t1b_cert, "key_pem": t1b_key})
    check(f"t1's id cannot be swapped while cards use it → 400 ({r.status_code})", r.status_code == 400, r.text[:200])
    r = call("POST", "/api/admin/commerces/t1/pass-identity", boss,
             {"pass_type_id": T1_PT, "certificate_pem": T1_CERT, "key_pem": T1_KEY})
    check(f"…but its certificate can be renewed (same id) → 200 ({r.status_code})", r.status_code == 200, r.text[:200])
    call("POST", "/api/admin/commerces/t1/pass-identity/active", boss, {"active": False})
    check("audit kept for the upload", db.audit_logs.count_documents({"action": {"$regex": "pass_identity"}}) >= 1)


main()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
