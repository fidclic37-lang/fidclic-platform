"""
Security incident 2026-10-27: the repository was public from 2026-09-18. No
key or connection string was ever committed, but account passwords were — in
the seed (two super admins among them, seeded on production from April to
October), an old handoff table and the tests — and auth fell back to a JWT
secret committed in the repo when JWT_SECRET was unset. User: lock by code.

    · on Vercel (production or preview), a password ever published in the
      repo never signs anyone in — whatever the account — and is refused
      wherever a password is checked
    · the seeded accounts still holding their published password get a
      random one, once (the tick), their sessions ended: « Mot de passe
      oublié » sets a new one
    · on Vercel, no JWT_SECRET = no token at all (503), never the committed
      one; a token signed with it is refused
    · the seed no longer creates the owner's own super admin; no password left
      in the docs or the scripts

Locally (tests, e2e) the seed's passwords keep working.

Run: cd api && /usr/local/bin/python3 tests/test_published_secrets.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-published")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ.pop("VERCEL", None)
UTC = dt.timezone.utc
passed = failed = 0
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:300]}"))


def main():
    import jwt
    import server
    import auth
    import httpx
    from services import published_passwords as PP

    db = server.db
    now = dt.datetime.now(UTC)

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    def login(email, pw):
        return http("POST", "/api/auth/login", json={"email": email, "password": pw})

    def user(email, pw, role="business_owner", tid="t1"):
        db.users.insert_one({"email": email, "role": role, "tenant_id": tid, "active": True,
                             "hashed_password": auth.hash_password(pw)})

    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "T1", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    user("admin@fidelitour.com", "Fidelit0ur!Adm", "super_admin", None)
    user("akshanshshukla963@gmail.com", "AkshFT!2026", "super_admin", None)
    user("demo.owner@fidelitour.com", "Owner!Demo2026")
    user("owner+cafe-ext@fidclic.com", "Demo!2026")
    user("owner@cafelumiere.fr", "Un-Nouveau-Secret-2026")          # changed since the seed: left alone
    user("vrai@commerce.fr", "Caisse!Royal2026")                     # a real account that picked a published one
    user("solide@commerce.fr", "Tres-Solide-Et-Unique-77")

    # ── 1. the list ─────────────────────────────────────────────────────────────
    print("La liste")
    for pw in ("Fidelit0ur!Adm", "AkshFT!2026", "Admin!Demo2026", "Owner!Demo2026", "Staff!Demo2026", "CafeLum!2026",
               "Boulang!2026", "Demo!2026", "Business2026!Xy", "Caisse!Royal2026", "Manager!Royal2026", "Chef!Royal2026",
               "Commis!Royal2026", "Corner!Secret-2026", "Bon!Motdepasse1"):
        if pw not in PP.PUBLISHED:
            check(f"« {pw} » is on the list", False)
            break
    else:
        check(f"every password found in the repo's history is on the list ({len(PP.PUBLISHED)})", True)

    # ── 2. locally: unchanged ──────────────────────────────────────────────────
    print("En local")
    check("locally the seed's password still signs in (tests, e2e)", login("admin@fidelitour.com", "Fidelit0ur!Adm").status_code == 200)

    # ── 3. on Vercel: published passwords never sign in ────────────────────────
    print("Sur Vercel")
    os.environ["VERCEL"] = "1"
    for email, pw in (("admin@fidelitour.com", "Fidelit0ur!Adm"), ("akshanshshukla963@gmail.com", "AkshFT!2026"),
                      ("owner+cafe-ext@fidclic.com", "Demo!2026"), ("vrai@commerce.fr", "Caisse!Royal2026")):
        r = login(email, pw)
        check(f"{email} with its published password: refused ({r.status_code})", r.status_code in (400, 401, 403))
    r = login("solide@commerce.fr", "Tres-Solide-Et-Unique-77")
    check(f"an account with its own password signs in ({r.status_code})", r.status_code == 200, r.text[:200])
    r2 = login("vrai@commerce.fr", "wrong")
    r1 = login("vrai@commerce.fr", "Caisse!Royal2026")
    check("refused with the same answer as a wrong password (nothing to learn)", r1.json() == r2.json(), (r1.json(), r2.json()))
    check("every password check refuses them (verify_password)",
          not auth.verify_password("Caisse!Royal2026", db.users.find_one({"email": "vrai@commerce.fr"})["hashed_password"]))

    # ── 4. the seeded accounts are locked once ─────────────────────────────────
    print("Comptes semés verrouillés")
    db.user_sessions.insert_many([{"sid": "s-admin", "email": "admin@fidelitour.com", "revoked_at": None},
                                  {"sid": "s-solide", "email": "solide@commerce.fr", "revoked_at": None}])
    before = {u["email"]: u["hashed_password"] for u in db.users.find({}, {"_id": 0})}
    out = server.tick_pass()
    locked = out.get("published_lock") or {}
    after = {u["email"]: u["hashed_password"] for u in db.users.find({}, {"_id": 0})}
    for email in ("admin@fidelitour.com", "akshanshshukla963@gmail.com", "demo.owner@fidelitour.com", "owner+cafe-ext@fidclic.com"):
        check(f"{email}: a new random password", after[email] != before[email]
              and (db.users.find_one({"email": email}) or {}).get("password_locked_at"))
    check("a seeded account whose password was changed: untouched", after["owner@cafelumiere.fr"] == before["owner@cafelumiere.fr"])
    check("real accounts: untouched (the login refusal covers them)",
          after["vrai@commerce.fr"] == before["vrai@commerce.fr"] and after["solide@commerce.fr"] == before["solide@commerce.fr"])
    check("the locked accounts' sessions are ended, the others' kept",
          db.user_sessions.find_one({"sid": "s-admin"}).get("revoked_at")
          and not db.user_sessions.find_one({"sid": "s-solide"}).get("revoked_at"))
    check(f"traced ({locked.get('locked')})", locked.get("locked") == 4
          and db.audit_logs.find_one({"action": "security.published_password_locked"}) is not None)
    check("done once: the next tick does nothing", (server.tick_pass().get("published_lock") or {}).get("locked", 0) == 0)

    # ── 5. JWT ──────────────────────────────────────────────────────────────────
    print("JWT")
    legacy = jwt.encode({"sub": "admin@fidelitour.com", "role": "super_admin",
                         "exp": now + dt.timedelta(hours=1)}, auth._LEGACY_INSECURE_SECRET, algorithm="HS256")
    r = http("GET", "/api/admin/env-status", headers={"Authorization": f"Bearer {legacy}"})
    check(f"a token signed with the committed secret is refused ({r.status_code})", r.status_code == 401)
    saved = os.environ.pop("JWT_SECRET")
    r = login("solide@commerce.fr", "Tres-Solide-Et-Unique-77")
    check(f"on Vercel without JWT_SECRET: no token at all ({r.status_code})", r.status_code == 503, r.text[:200])
    r = http("GET", "/api/admin/env-status", headers={"Authorization": f"Bearer {legacy}"})
    check(f"…and the committed secret never opens anything ({r.status_code})", r.status_code in (401, 503))
    from services import card_owner as CO
    try:
        CO.key_for("c1") if hasattr(CO, "key_for") else CO._secret()
        ok = False
    except Exception:
        ok = True
    check("…nor signs a card's owner link", ok)
    os.environ["JWT_SECRET"] = saved
    os.environ.pop("VERCEL", None)

    # ── 6. the repo itself ─────────────────────────────────────────────────────
    print("Le dépôt")
    src = open(os.path.join(ROOT, "api", "server.py")).read()
    check("the seed no longer creates the owner's own super admin", "AkshFT!2026" not in src and
          "akshanshshukla963@gmail.com" not in src.split("def mock_seed_data")[1][:200000])
    for f in ("CLAUDE.md", "BUILD-FIDELITE-THEME.md", "scripts/seed_test_customers.py"):
        txt = open(os.path.join(ROOT, f)).read()
        hits = [p for p in PP.PUBLISHED if len(p) > 8 and p in txt]
        check(f"no password in {f} ({hits})", not hits)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
