"""
Super admin › import a business's Apple certificate by hand (user,
2026-10-30: the fallback when App Store Connect cannot make it — « super
admin se certificate haath se upload »). Built on features/wallet_identities
(#410): the same row, the same sealed key, the same signing and pushes.

    POST /api/admin/wallet-identities/{tid}/upload   Super Admin only

Run: cd api && /usr/local/bin/python3 tests/test_wallet_identity_upload.py
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
COMMON = "pass.com.fidclic.loyalty"


def selfsigned(pt, days=365, uid=True):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attrs = ([x509.NameAttribute(NameOID.USER_ID, pt)] if uid else []) + \
        [x509.NameAttribute(NameOID.COMMON_NAME, f"Pass Type ID: {pt}")]
    name = x509.Name(attrs)
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=2))
            .not_valid_after(now + dt.timedelta(days=days)).sign(key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM).decode(),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()).decode())


GC, GK = selfsigned(COMMON)
WW, _ = selfsigned("wwdr")
os.environ.update({
    "APPLE_PASS_TYPE_ID": COMMON, "APPLE_TEAM_ID": "TEAM123456",
    "APPLE_PASS_CERT_B64": base64.b64encode(GC.encode()).decode(),
    "APPLE_PASS_KEY_B64": base64.b64encode(GK.encode()).decode(),
    "APPLE_WWDR_B64": base64.b64encode(WW.encode()).decode(),
    "PASS_AUTH_SECRET": "test-secret", "JWT_SECRET": "test-jwt-upload", "DISABLE_SEED": "1",
    "WALLET_KEYS_SECRET": "a-long-random-wallet-keys-secret",
})
for k in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_PRIVATE_KEY"):
    os.environ.pop(k, None)              # App Store Connect not set: the case the upload is for
passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))


def main():
    import server
    import auth
    import httpx
    from features import wallet_identities as WI
    from features import wallet_passes as W

    db = server.db
    W._db = db
    WI.init(db)
    WI._db = db
    now = dt.datetime.now(dt.timezone.utc)
    for t, slug in (("t1", "royal-trim"), ("t2", "green-smoke"), ("t3", "cafe")):
        db.tenants.insert_one({"id": t, "slug": slug, "name": slug.upper(), "plan": "vip", "subscription_status": "active", "is_active": True})
        db.users.insert_one({"email": f"o@{t}.fr", "role": "business_owner", "tenant_id": t, "active": True})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Ana", "barcode_id": "FT-UP0001", "created_at": now, "visits": 1})
    db.customers.insert_one({"id": "c2", "tenant_id": "t2", "name": "Bob", "barcode_id": "FT-UP0002", "created_at": now, "visits": 1})
    T1 = WI.identifier_for(db.tenants.find_one({"id": "t1"}))
    C1, K1 = selfsigned(T1)

    def call(method, path, token=None, body=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as ac:
                h = {"Authorization": f"Bearer {token}"} if token else {}
                return await ac.request(method, path, headers=h, json=body)
        return asyncio.get_event_loop().run_until_complete(run())
    boss = auth.create_access_token({"sub": "boss@fidclic.com", "role": "super_admin"})
    owner = auth.create_access_token({"sub": "o@t1.fr", "role": "business_owner", "tenant_id": "t1"})
    up = lambda tid, body, tok=boss: call("POST", f"/api/admin/wallet-identities/{tid}/upload", tok, body)   # noqa: E731

    print("\nWho may import")
    body = {"certificate_pem": C1, "key_pem": K1}
    check("a business owner → 403", up("t1", body, owner).status_code == 403)
    check("no token → 401/403", up("t1", body, None).status_code in (401, 403))
    check("unknown business → 404", up("nope", body).status_code == 404)

    print("\nWhat is refused, with the reason")
    oc, ok_ = selfsigned("pass.com.fidclic.someone-else")
    for label, b in (("certificate of another id", {"certificate_pem": oc, "key_pem": ok_}),
                     ("key that is not the certificate's", {"certificate_pem": C1, "key_pem": ok_}),
                     ("expired certificate", dict(zip(("certificate_pem", "key_pem"), selfsigned(T1, days=-1)))),
                     ("garbage", {"certificate_pem": "nope", "key_pem": "nope"}),
                     ("300 KB of junk", {"certificate_pem": "A" * 300_000, "key_pem": "A" * 300_000}),
                     ("the common id", {"identifier": COMMON, "certificate_pem": GC, "key_pem": GK}),
                     ("an id not starting with pass.", {"identifier": "com.x", "certificate_pem": C1, "key_pem": K1})):
        r = up("t1", b)
        check(f"{label} → 400 with a reason ({r.status_code})", r.status_code == 400 and (r.json() or {}).get("detail"), r.text[:160])
    check("nothing saved after refusals", db.wallet_pass_types.count_documents({"tenant_id": "t1"}) == 0)

    print("\nA valid import")
    r = up("t1", body)
    d = r.json() if r.status_code == 200 else {}
    check(f"200 ({r.status_code})", r.status_code == 200, r.text[:200])
    check("the business's id, ready, manual, end date", d.get("identifier") == T1 and d.get("status") == "ready"
          and d.get("source") == "manual" and d.get("expires_at"), d)
    check("the answer never carries the key", "PRIVATE KEY" not in r.text)
    row = db.wallet_pass_types.find_one({"tenant_id": "t1"})
    check("the key is sealed in the database", "PRIVATE KEY" not in json.dumps(row, default=str) and row.get("key_enc"))
    check("…and opens back to the same key", WI.identity_for_type(T1) and WI.identity_for_type(T1)["key_pem"].decode().strip() == K1.strip())
    check("WI.tenant_type(t1) → its id", WI.tenant_type("t1") == T1)
    check("an audit row is kept", db.audit_logs.count_documents({"action": "admin.wallet_identity.upload"}) == 1)
    lst = call("GET", "/api/admin/wallet-identities", boss).json()
    r1 = [x for x in lst["rows"] if x["tenant_id"] == "t1"]
    check("the list shows it as manual", r1 and r1[0].get("source") == "manual" and r1[0]["status"] == "ready", r1)
    check("the list offers every business to import for", {"t1", "t2", "t3"} <= {b["id"] for b in lst.get("businesses", [])}, lst.get("businesses"))

    print("\nA new card of t1 takes the imported id, signed with it")
    resp = W.download_apple_pass("FT-UP0001", None) if W.download_apple_pass.__code__.co_argcount >= 2 else W.download_apple_pass("FT-UP0001")
    z = zipfile.ZipFile(io.BytesIO(resp.body))
    pj = json.loads(z.read("pass.json"))
    signer = {c.subject.rfc4514_string() for c in pkcs7.load_der_pkcs7_certificates(z.read("signature"))}
    check("passTypeIdentifier = the imported id", pj["passTypeIdentifier"] == T1, pj["passTypeIdentifier"])
    check("…signed with the imported certificate", any(T1 in s for s in signer), signer)

    print("\nAn id given by hand, other businesses, renewing")
    T3 = "pass.com.fidclic.cafe-manual"
    c3, k3 = selfsigned(T3, uid=False)                    # CN only: some Apple exports
    r = up("t3", {"identifier": T3, "certificate_pem": c3, "key_pem": k3})
    check(f"t3 with its own id (CN only) → 200 ({r.status_code})", r.status_code == 200 and r.json().get("identifier") == T3, r.text[:200])
    r = up("t2", {"identifier": T3, "certificate_pem": c3, "key_pem": k3})
    check(f"t2 cannot take t3's id → 400 ({r.status_code})", r.status_code == 400, r.text[:160])
    T1B = "pass.com.fidclic.royal-other"
    c1b, k1b = selfsigned(T1B)
    r = up("t1", {"identifier": T1B, "certificate_pem": c1b, "key_pem": k1b})
    check(f"t1's id cannot be swapped once a card carries it → 400 ({r.status_code})", r.status_code == 400, r.text[:160])
    C1n, K1n = selfsigned(T1, days=400)
    r = up("t1", {"certificate_pem": C1n, "key_pem": K1n})
    check(f"a new certificate for the same id (renewal) → 200 ({r.status_code})", r.status_code == 200, r.text[:160])
    check("…the new one signs from now on", WI.identity_for_type(T1)["cert_pem"].decode().strip() == C1n.strip())
    db.wallet_pass_types.update_one({"tenant_id": "t2"}, {"$set": {"tenant_id": "t2", "identifier": WI.identifier_for(
        db.tenants.find_one({"id": "t2"})), "status": "failed", "error": "Apple refuse", "attempts": 3}}, upsert=True)
    T2 = WI.identifier_for(db.tenants.find_one({"id": "t2"}))
    c2, k2 = selfsigned(T2)
    r = up("t2", {"certificate_pem": c2, "key_pem": k2})
    row2 = db.wallet_pass_types.find_one({"tenant_id": "t2"})
    check(f"a business whose automatic try failed → ready by hand ({r.status_code})",
          r.status_code == 200 and row2["status"] == "ready" and not row2.get("error") and row2.get("attempts") == 0, row2)


main()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
