"""
A campaign's figures, counted one way on both pages (QA F32, 2026-10-11:
Campagnes 1 click / 8 263 €, Analyses › Campagnes 0 clicks / 5 547 € for the
same 7 campaigns). services/campaign_figures: clicks from the offer's counter,
each visit once for the latest campaign before it, 15 days after the send.

Run: cd api && /usr/local/bin/python3 tests/test_campaign_figures.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-campaign-figures")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    import auth
    import httpx
    from services import campaign_figures as CF

    db = server.db

    def http(url):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(url, headers=H)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    for cid in ("a", "b", "c"):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid.upper(), "barcode_id": f"FT-{cid.upper()}0000000"})

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    # within this calendar month (the Campagnes page's period) and the last 30 days (Analyses)
    first = max(now - dt.timedelta(days=4), now.replace(day=1, hour=0, minute=0, second=1))
    t = lambda h: first + dt.timedelta(hours=h)         # noqa: E731
    db.campaigns.insert_many([
        {"id": "k1", "tenant_id": "t1", "name": "Petit-déjeuner", "status": "sent", "sent_at": t(0),
         "recipient_ids": ["a", "b"], "offer_clicks": 3, "clicks": 0},
        {"id": "k2", "tenant_id": "t1", "name": "Happy hour", "status": "sent", "sent_at": t(10),
         "recipient_ids": ["a", "c"], "offer_clicks": 1},
        {"id": "k3", "tenant_id": "t1", "name": "Brouillon", "status": "draft", "sent_at": None,
         "recipient_ids": ["a", "b", "c"], "offer_clicks": 9},
    ])
    db.visits.insert_many([
        {"id": "v1", "tenant_id": "t1", "customer_id": "a", "amount_paid": 10.0, "visit_time": t(5)},    # after k1 only
        {"id": "v2", "tenant_id": "t1", "customer_id": "a", "amount_paid": 20.0, "visit_time": t(12)},   # after k1 AND k2
        {"id": "v3", "tenant_id": "t1", "customer_id": "b", "amount_paid": 30.0, "visit_time": t(12)},   # k1 (b never got k2)
        {"id": "v4", "tenant_id": "t1", "customer_id": "c", "amount_paid": 0.0, "visit_time": t(14)},    # k2, a zero-value visit
        {"id": "v5", "tenant_id": "t1", "customer_id": "c", "amount_paid": 15.0, "visit_time": t(16)},   # k2, came back
        {"id": "v6", "tenant_id": "t1", "customer_id": "b", "amount_paid": 99.0, "visit_time": t(-2)},   # before any send
    ])

    print("\nOne visit, one campaign")
    att = CF.attribution(db, "t1", list(db.campaigns.find({"status": "sent"}, {"_id": 0})))
    check(f"k1: a's first visit and b's ({att['k1']})", att["k1"] == {"revenue": 40.0, "sales": 2, "buyers": 2})
    check(f"k2: a's visit after both goes to the newer one; c's two, the 0 € one counted ({att['k2']})",
          att["k2"] == {"revenue": 35.0, "sales": 3, "buyers": 2})
    check("nothing counted twice: 75 € = the visits after a send", att["k1"]["revenue"] + att["k2"]["revenue"] == 75.0)
    late = CF.attribution(db, "t1", [{"id": "k1", "sent_at": t(0), "recipient_ids": ["a", "b"]}])
    check("asked alone, k1 still leaves a's later visit to k2 (the newer send)", late["k1"]["revenue"] == 40.0)

    print("\nBoth pages say the same")
    cp = http("/api/owner/campaigns/page").json()
    strip = {s["key"]: s["value"] for s in cp["strip"]}
    an = http("/api/owner/analyses?tab=campagnes&days=30").json()["data"]
    an_strip = {s["key"]: s["value"] for s in an["strip"]}
    check(f"campaigns sent: {strip.get('sent')} / {an_strip.get('sent')} (a draft is not sent)", strip.get("sent") == an_strip.get("sent") == 2)
    check(f"clicks: {strip.get('clicks')} / {an_strip.get('clicks')} — the offer's counter",
          strip.get("clicks") == an_strip.get("clicks") == 4)
    check(f"revenue: {strip.get('revenue')} € / {an.get('revenue_attributed')} €",
          strip.get("revenue") == an.get("revenue_attributed") == 75.0)
    check("the same rule is printed on both", cp.get("revenue_note") == an.get("note") == CF.REVENUE_NOTE)
    row = {r["id"]: r for r in an["table"]}
    check(f"Analyses per campaign: k2 3 sales, 35 € ({row['k2']['sales']}, {row['k2']['revenue']})",
          row["k2"]["sales"] == 3 and row["k2"]["revenue"] == 35.0)
    d = http("/api/owner/campaigns/k2/detail").json()
    check(f"the campaign's own page: 35 €, 1 click ({(d.get('stats') or {}).get('revenue')})",
          (d.get("stats") or {}).get("revenue") == 35.0 and d["stats"]["clicks"] == 1)


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
