"""
Super admin › Paramètres › Services (user, 2026-11-11): every service FidClic
runs on — set or missing, what stops without it — and « Tester », a real small
check of each. Never a key's value; a test never reaches a shop or a customer
(the test e-mail goes to the person who pressed the button).

Run: cd api && python3 -u tests/test_admin_settings_services.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-admin-services")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0
SECRET_VALUES = {"BREVO_API_KEY": "xkeysib-SECRET-brevo-123", "STRIPE_SECRET_KEY": "sk_live_SECRET_stripe",
                 "TWILIO_ACCOUNT_SID": "ACsecretsid", "TWILIO_AUTH_TOKEN": "tw-SECRET-token", "TWILIO_FROM_NUMBER": "+33700000000",
                 "ANTHROPIC_API_KEY": "sk-ant-SECRET-key", "BLOB_READ_WRITE_TOKEN": "vercel_blob_rw_SECRET"}


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail!r}"))


def main():
    for k, v in SECRET_VALUES.items():
        os.environ[k] = v
    for k in ("STRIPE_WEBHOOK_SECRET", "WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "PREDICTHQ_TOKEN", "CRON_SECRET"):
        os.environ.pop(k, None)
    import server
    import auth
    import httpx
    from features import platform_services as SV, platform_access as PA
    from services import mailer

    db = server.db
    PA.forget()

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def tok(email, role, tid=None):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tid})}

    db.users.insert_many([
        {"email": "boss@fidclic.com", "role": "super_admin"},
        {"email": "ops@fidclic.com", "role": "fidclic_team", "platform_role": "ops"},
        {"email": "look@fidclic.com", "role": "fidclic_team", "platform_role": "look"},
        {"email": "none@fidclic.com", "role": "fidclic_team", "platform_role": "none"},
        {"email": "own@shop.fr", "role": "business_owner", "tenant_id": "s"},
    ])
    db.platform_roles.insert_many([
        {"id": "ops", "name": "Ops", "perms": {"parametres": {"view": True, "edit": True}}},
        {"id": "look", "name": "Look", "perms": {"parametres": {"view": True, "edit": False}}},
        {"id": "none", "name": "None", "perms": {"support": {"view": True, "edit": True}}},
    ])
    BOSS, OPS, LOOK, NONE = (tok("boss@fidclic.com", "super_admin"), tok("ops@fidclic.com", "fidclic_team"),
                             tok("look@fidclic.com", "fidclic_team"), tok("none@fidclic.com", "fidclic_team"))
    OWN = tok("own@shop.fr", "business_owner", "s")
    URL = "/api/admin/settings/services"

    # ------------------------------------------------------------------ who
    print("Qui peut")
    check("a business owner: 403", http("GET", URL, headers=OWN).status_code == 403)
    check("no token: 401/403", http("GET", URL).status_code in (401, 403))
    check("a team member without « Paramètres »: 403", http("GET", URL, headers=NONE).status_code == 403)
    check("« Voir »: the list", http("GET", URL, headers=LOOK).status_code == 200)
    check("« Voir » only cannot run a test (403)", http("POST", f"{URL}/mongo/test", headers=LOOK).status_code == 403)

    # ------------------------------------------------------------------ the list
    print("\nLa liste")
    r = http("GET", URL, headers=BOSS)
    j = r.json()
    items = {i["key"]: i for g in j["groups"] for i in g["items"]}
    check("grouped (socle, emails, SMS, paiements, wallet, stockage, IA, connexion, autres)",
          [g["key"] for g in j["groups"]] == ["socle", "emails", "messages", "paiements", "wallet", "stockage", "ia", "connexion", "autres"],
          [g["key"] for g in j["groups"]])
    for k in ("mongo", "jwt", "app_url", "cron", "brevo", "support_smtp", "twilio", "whatsapp", "stripe", "vapid", "apple_wallet",
              "asc_api", "google_wallet", "samsung_wallet", "blob", "warehouse", "anthropic", "ai_backup", "golden", "google_signin",
              "apple_signin", "predicthq"):
        check(f"« {k} » is listed", k in items)
    check("a set service says so (Brevo)", items["brevo"]["present"] is True, items["brevo"])
    check("a missing one says so, with the names to set (Stripe webhook)",
          items["stripe"]["present"] is False and items["stripe"]["missing"] == ["STRIPE_WEBHOOK_SECRET"], items["stripe"])
    check("…and what stops without it", items["stripe"]["without"] and items["whatsapp"]["without"], items["stripe"])
    check("each says what it is for", all(i["powers"] for i in items.values()))
    check("the required ones are marked (database, connexions)", items["mongo"]["required"] and items["jwt"]["required"]
          and not items["whatsapp"]["required"])
    check("which can be tested", items["brevo"]["testable"] and items["stripe"]["testable"] and items["twilio"]["testable"]
          and items["anthropic"]["testable"] and items["blob"]["testable"] and items["mongo"]["testable"]
          and not items["whatsapp"]["testable"])
    check("Stripe stays « missing » without its webhook, but can be tested with its key",
          items["stripe"]["present"] is False and items["stripe"]["testable"])
    check("a summary: ready / missing", j["summary"]["total"] == len(items)
          and j["summary"]["ready"] == sum(1 for i in items.values() if i["present"]), j["summary"])
    check("NO key value anywhere in the answer", not any(v in r.text for v in SECRET_VALUES.values()))
    check("…not even a piece of one", "SECRET-" not in r.text and "SECRET_stripe" not in r.text and "xkeysib" not in r.text
          and "sk_live" not in r.text and "ACsecretsid" not in r.text)

    # ------------------------------------------------------------------ tests
    print("\nTester")
    calls = []

    def fake_http(method, url, headers=None, data=None, timeout=8):
        calls.append((method, url))
        if "stripe.com" in url:
            return 200, {"livemode": True, "available": []}
        if "twilio.com" in url:
            return 200, {"status": "active", "friendly_name": "FidClic"}
        if "anthropic.com" in url:
            return 401, {"error": {"type": "authentication_error"}}
        if "blob.vercel-storage.com" in url:
            return 200, {"blobs": []}
        return 404, {}
    SV._http = fake_http
    mails = []
    mailer.send = lambda to, subject, html, text=None, to_name=None, reply_to=None: (mails.append(to), {"sent": True})[1]

    r = http("POST", f"{URL}/mongo/test", headers=OPS)
    check("database: ping → OK", r.status_code == 200 and r.json()["ok"] is True, r.text)
    r = http("POST", f"{URL}/brevo/test", headers=OPS)
    check("e-mail: a test e-mail to the person who pressed, nobody else",
          r.status_code == 200 and r.json()["ok"] is True and mails == ["ops@fidclic.com"], (r.text, mails))
    check("…and it says where it went", "ops@fidclic.com" in r.json()["message"])
    r = http("POST", f"{URL}/stripe/test", headers=OPS)
    check("Stripe: the account answers → OK, live mode said", r.json()["ok"] is True and "live" in r.json()["message"].lower(), r.json())
    r = http("POST", f"{URL}/twilio/test", headers=OPS)
    check("Twilio: the account is read, NO SMS sent", r.json()["ok"] is True and all("Messages" not in u for _, u in calls), calls)
    r = http("POST", f"{URL}/anthropic/test", headers=OPS)
    check("Anthropic: a refused key → not OK, said plainly", r.json()["ok"] is False and "refus" in r.json()["message"].lower(), r.json())
    check("…the models list is read, no paid call", any("/v1/models" in u for _, u in calls) and not any("/messages" in u for _, u in calls))
    r = http("POST", f"{URL}/blob/test", headers=OPS)
    check("photos store: answers → OK", r.json()["ok"] is True, r.json())
    check("no test ever writes a key into its answer", not any(v in str(calls) + r.text for v in ("tw-SECRET-token",)))
    r = http("POST", f"{URL}/whatsapp/test", headers=OPS)
    check("a service with no test → 400", r.status_code == 400, r.status_code)
    r = http("POST", f"{URL}/nope/test", headers=OPS)
    check("an unknown service → 404", r.status_code == 404, r.status_code)
    os.environ.pop("STRIPE_SECRET_KEY")
    r = http("POST", f"{URL}/stripe/test", headers=OPS)
    check("a missing key → not OK, « non configuré », no network call", r.json()["ok"] is False
          and "configur" in r.json()["message"].lower() and not any("stripe" in u for _, u in calls[-1:]), r.json())

    def boom(*a, **k):
        raise TimeoutError("timed out")
    SV._http = boom
    r = http("POST", f"{URL}/twilio/test", headers=OPS)
    check("a service that does not answer → not OK, never a 500", r.status_code == 200 and r.json()["ok"] is False, r.text)
    check("every test is in the journal", db.audit_logs.count_documents({"action": "platform.service_test"}) >= 8)
    row = db.audit_logs.find_one({"action": "platform.service_test", "target": "brevo"})
    check("…with who and the result, no key", row and row["actor"] == "ops@fidclic.com" and "SECRET-" not in str(row), row)

    # ------------------------------------------------------------------ abuse
    print("\nAbus")
    SV._http = fake_http
    SV._tries.clear()
    codes = [http("POST", f"{URL}/mongo/test", headers=OPS).status_code for _ in range(12)]
    check("at most 10 tests a minute per person (then 429)", codes[:10] == [200] * 10 and codes[10:] == [429, 429], codes)
    check("…another person is not blocked", http("POST", f"{URL}/mongo/test", headers=BOSS).status_code == 200)


    # ------------------------------------------------------------------ local checks (no network)
    print("\nVérifications locales")
    import base64 as B64
    import datetime as dt
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    k = ec.generate_private_key(ec.SECP256R1())
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    priv = k.private_numbers().private_value.to_bytes(32, "big")
    u = lambda b: B64.urlsafe_b64encode(b).decode().rstrip("=")          # noqa: E731
    os.environ.update(VAPID_PUBLIC_KEY=u(pub), VAPID_PRIVATE_KEY=u(priv), VAPID_SUBJECT="mailto:ops@fidclic.com")
    check("VAPID: a real key pair → valid", SV._t_vapid("x")[0] is True)
    os.environ["VAPID_SUBJECT"] = "ops@fidclic.com"
    check("VAPID: a subject without mailto: → refused", SV._t_vapid("x")[0] is False)
    os.environ.update(VAPID_SUBJECT="mailto:a@b.fr", VAPID_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----")
    check("VAPID: a PEM private key → refused, said", SV._t_vapid("x")[0] is False)
    os.environ["VAPID_PUBLIC_KEY"] = u(pub[:30])
    check("VAPID: a short public key → refused", SV._t_vapid("x")[0] is False)

    def cert(days):
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Pass Type ID: pass.com.fidclic")])
        now = dt.datetime.now(dt.timezone.utc)
        c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
             .serial_number(1).not_valid_before(now - dt.timedelta(days=400)).not_valid_after(now + dt.timedelta(days=days))
             .sign(k, hashes.SHA256()))
        return B64.b64encode(c.public_bytes(serialization.Encoding.PEM)).decode()
    os.environ["APPLE_PASS_CERT_B64"] = cert(200)
    ok, msg = SV._t_apple("x")
    check("Apple: valid 200 days → OK with its end date", ok and "jusqu'au" in msg, msg)
    os.environ["APPLE_PASS_CERT_B64"] = cert(10)
    ok, msg = SV._t_apple("x")
    check("Apple: 10 days left → warned (not OK), « renouveler »", not ok and "renouveler" in msg, msg)
    os.environ["APPLE_PASS_CERT_B64"] = cert(-3)
    ok, msg = SV._t_apple("x")
    check("Apple: expired → not OK, « expiré »", not ok and "expiré" in msg, msg)

    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
