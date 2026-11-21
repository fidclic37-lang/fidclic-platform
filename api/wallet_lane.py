"""
The iPhone's own lane — a Vercel function of its own (user, 2026-11-21).

An iPhone that adds a card tells the server once « this card is on me »
(the registration). On 2026-11-20 that one call was lost for a client: it
queued behind the card page's own requests on the same instance (3 database
connections, a 10 s wait, then 503) and Wallet never asked again — no push
could reach the card.

Here the iPhone's four small calls run alone:

    POST   /api/passes/v1/devices/{device}/registrations/{pass_type}/{serial}
    GET    /api/passes/v1/devices/{device}/registrations/{pass_type}
    DELETE /api/passes/v1/devices/{device}/registrations/{pass_type}/{serial}
    POST   /api/passes/v1/log

with the same code as the server (features/wallet_passes), without loading
server.py (no seed, no migration, a short cold start), and with a MongoDB
client of 2 connections at most. Atlas M0 allows 500: the platform's budget
is api instances × 3 + lane instances × 2.

The card download (/api/passes/v1/passes/…) builds the whole card and stays
on the server. « Bienvenue » needs the server too: the lane queues it
(wallet_welcome_due) and wakes the server at once (POST /api/wallet/welcome-due);
the 15-minute tick sweeps what is left.

vercel.json routes the four paths here, before its /api catch-all.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pymongo  # noqa: E402
from pymongo import errors as _mongo_errors  # noqa: E402
from fastapi import FastAPI  # noqa: E402

LANE_CLIENT_OPTIONS = dict(
    serverSelectionTimeoutMS=5000,
    maxPoolSize=2,             # the lane's share of Atlas M0's 500 connections
    minPoolSize=0,
    maxIdleTimeMS=30_000,      # idle sockets handed back to Atlas
    waitQueueTimeoutMS=8_000,  # a full pool answers 503 before Wallet gives up
    connectTimeoutMS=5000,
    appname="fidclic-wallet-lane",
    tz_aware=True,
)

from services import mongo_pool as _mongo_pool  # noqa: E402
_mongo_pool.install()

from features import wallet_passes as WP  # noqa: E402
from features import wallet_identities as WI  # noqa: E402

db = None


def connect(database=None):
    """The lane's database: `database` (tests), else its own small client.
    Indexes are the server's job (wallet_passes.init) — none made here."""
    global db
    if database is None:
        uri = os.environ.get("MONGODB_URI", "")
        client = pymongo.MongoClient(uri, **LANE_CLIENT_OPTIONS) if uri else pymongo.MongoClient(**LANE_CLIENT_OPTIONS)
        database = client.fidelitour_db
    db = database
    WP._db = database
    WI._db = database
    WP.LANE = True              # « Bienvenue » goes to the server
    return database


app = FastAPI(title="FidClic wallet lane", docs_url=None, redoc_url=None, openapi_url=None)
for _path, _fn, _methods in WP.LANE_ROUTES:
    app.add_api_route(_path, _fn, methods=_methods)


@app.middleware("http")
async def _which_lane(request, call_next):
    """Every answer says it came from this lane: a preview checks the routing,
    the health page counts it."""
    response = await call_next(request)
    response.headers["X-FidClic-Lane"] = "wallet"
    return response


@app.exception_handler(_mongo_errors.ConnectionFailure)
async def _database_unavailable(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={"detail": "busy"}, headers={"Retry-After": "30"})


if os.environ.get("MONGODB_URI") or os.environ.get("VERCEL"):
    connect()
