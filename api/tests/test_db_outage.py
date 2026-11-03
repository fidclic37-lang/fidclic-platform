"""
Panne MongoDB du 2026-11-03 : Atlas Cluster0 (M0) à 502/500 connexions, le
primaire refusait les nouvelles connexions et la connexion répondait
« Email ou mot de passe incorrect » à tout le monde.

1. Chaque instance Vercel ne garde qu'un petit pool (pymongo en ouvre 100
   par défaut, sans jamais fermer les connexions inactives).
2. Une base injoignable donne un 503 lisible, jamais un 500 que la page de
   connexion prend pour de mauvais identifiants.

Standalone script, like the others: python3 api/tests/test_db_outage.py
"""
import sys, os
import asyncio

import mongomock
from pymongo import errors as PE

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_patch = mongomock.patch(servers=(("localhost", 27017),))
_patch.start()

import server as S                      # noqa: E402 — must come after the patch
import httpx                            # noqa: E402

passed = failed = 0


def check(label, cond):
    global passed, failed
    passed += bool(cond); failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def post(url, **kw):
    """Straight into the app, like test_platform_security (the installed
    TestClient and httpx disagree on versions). An unhandled error is a 500."""
    async def run():
        transport = httpx.ASGITransport(app=S.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.post(url, **kw)
    return asyncio.run(run())


def login():
    return post("/api/auth/login", json={"email": "someone@example.fr", "password": "whatever-1A!"})


def with_find_one_raising(exc, fn):
    """Every find_one raises `exc` while `fn` runs (the database is down)."""
    Coll = mongomock.collection.Collection
    original = Coll.find_one

    def boom(*_a, **_k):
        raise exc
    Coll.find_one = boom
    try:
        return fn()
    finally:
        Coll.find_one = original


print("\nPool")
o = S.MONGO_CLIENT_OPTIONS
check("at most 10 connections per instance", 1 <= o["maxPoolSize"] <= 10)
check("no connections kept open on purpose", o["minPoolSize"] == 0)
check("idle connections are closed within a minute", 0 < o["maxIdleTimeMS"] <= 60_000)
check("a full pool fails fast instead of hanging", 0 < o["waitQueueTimeoutMS"] <= 15_000)
check("server selection still gives up after 5 s", o["serverSelectionTimeoutMS"] == 5000)
check("dates stay timezone-aware", o["tz_aware"] is True)

seen = {}


class FakeClient:
    def __init__(self, *args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs


real = S.pymongo.MongoClient
S.pymongo.MongoClient = FakeClient
try:
    S.make_client("mongodb+srv://example/")
    check("the Atlas URI gets the options", seen["args"] == ("mongodb+srv://example/",) and seen["kwargs"] == o)
    S.make_client("")
    check("no URI (local, tests) gets them too", seen["args"] == () and seen["kwargs"] == o)
finally:
    S.pymongo.MongoClient = real

print("\nDatabase unreachable → 503, never « incorrect »")
for exc in (PE.ServerSelectionTimeoutError('No replica set members match selector "Primary()"'),
            PE.AutoReconnect("SSL handshake failed"),
            PE.NetworkTimeout("timed out"),
            PE.ConnectionFailure("connection refused"),
            PE.WaitQueueTimeoutError("pool full")):
    name = type(exc).__name__
    r = with_find_one_raising(exc, login)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    check(f"{name}: 503", r.status_code == 503)
    check(f"{name}: readable French sentence", body.get("detail") == S.DB_UNAVAILABLE_DETAIL and "indisponible" in body.get("detail", ""))
    check(f"{name}: machine code db_unavailable", body.get("code") == "db_unavailable")
    check(f"{name}: Retry-After 30", r.headers.get("retry-after") == "30")
    check(f"{name}: nothing about the cluster leaks", "mongodb" not in r.text.lower() and "replica" not in r.text.lower())

print("\nNot an outage")
r = with_find_one_raising(PE.OperationFailure("bad query"), login)
check("a query error stays a 500 (a bug must not hide behind « réessayez »)", r.status_code == 500)
r = post("/api/auth/login", json={"email": "nobody@example.fr", "password": "whatever-1A!"})
check("wrong credentials are still 400 « Incorrect credentials »",
      r.status_code == 400 and r.json().get("detail") == "Incorrect credentials")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
