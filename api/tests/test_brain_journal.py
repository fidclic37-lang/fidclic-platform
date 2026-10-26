"""
Prediction journal (user, 2026-10-25): every next-visit window the client
brain gives is written down, judged by the client's real next visit, compared
with the plain mean and the 30-day rule, and anonymised once judged. The
backtest replays the past (journal only); Super admin › Précision reads it.

Run: cd api && /usr/local/bin/python3 tests/test_brain_journal.py
"""
import asyncio
import contextlib
import csv
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-brain-journal")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import brain_journal as BJ
    from features import client_brain as CB

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(UTC).replace(microsecond=0)
    db.tenants.insert_many([
        {"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active",
         "is_active": True, "sector": "salon"},
        {"id": "t2", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active",
         "is_active": True, "sector": "cafe"},
    ])
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10})
    db.users.insert_many([
        {"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
        {"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem"},
    ])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    OWNER, BOSS = tok("o@x.fr", "business_owner"), tok("boss@fidclic.com", "super_admin", None)

    def visit(cid, at, tid="t1", amount=20.0):
        return {"id": f"{cid}-{at.isoformat()}", "tenant_id": tid, "customer_id": cid, "amount_paid": amount,
                "visit_time": at}

    # Règles clients › « Client actif »: 45 days for this shop (the café keeps the default 30)
    from features import customer_rules as RULES
    rules = RULES.load("t1")
    next(r for r in rules if r["key"] == "actif")["conditions"][0]["value"] = 45
    db.customer_status_config.update_one({"tenant_id": "t1"}, {"$set": {"tenant_id": "t1", "rules": rules}}, upsert=True)
    check("the shop's rule is read", BJ.rule_days("t1") == 45 and BJ.rule_days("t2") == 30)

    # ── live: a scan writes the window, the next day judges it ──────────────────
    print("En direct")
    start = now - dt.timedelta(days=30)
    db.visits.insert_many([visit("rahul", start + dt.timedelta(days=10 * i)) for i in range(3)])   # days −30, −20, −10
    db.customers.insert_one({"id": "rahul", "tenant_id": "t1", "name": "Rahul", "barcode_id": "FT-RAHUL",
                             "visits": 3, "deleted_at": None, "created_at": start})
    b = CB.refresh("t1", "rahul")
    BJ.record_visit("t1", "rahul", b)
    rows = [BJ.unpack(d) for d in db.brain_predictions.find({"customer_id": "rahul", "status": "open"})]
    check("a known rhythm leaves one open row, with the client while it waits", len(rows) == 1 and rows[0]["source"] == "live")
    row = rows[0]
    check("the window and both baselines are kept — the shop's own rule (45 days), not a fixed 30", row["pred"]["from"] < row["pred"]["centre"] < row["pred"]["to"]
          and row["baselines"]["mean"] and row["baselines"]["rule_days"] == 45)
    check("features hold numbers only — no name, no product", "name" not in str(row["features"]).lower()
          and row["features"]["visits_n"] == 3 and row["features"]["n_gaps"] == 2)
    # a second scan the same day: remade, not judged
    BJ.record_visit("t1", "rahul", b)
    check("same day again: still one open row, nothing judged",
          db.brain_predictions.count_documents({"customer_id": "rahul"}) == 1
          and db.brain_predictions.count_documents({"status": "resolved"}) == 0)
    row = BJ.unpack(db.brain_predictions.find_one({"customer_id": "rahul", "status": "open"}))       # the remade one
    # he comes back today (10 days after) — inside the window
    db.visits.insert_one(visit("rahul", now))
    b2 = CB.refresh("t1", "rahul")
    BJ.record_visit("t1", "rahul", b2)
    done = BJ.unpack(db.brain_predictions.find_one({"_id": row["_id"]}))
    check("the next day's visit judges it: resolved", done["status"] == "resolved")
    check("… and the client's id leaves the row", done["customer_id"] is None)
    check("real gap 10 days, error measured for the brain and the baselines",
          abs(done["outcome"]["actual_gap"] - 10) < 0.1 and done["outcome"]["error_mean"] == 0.0
          and abs(done["outcome"]["error_rule"] + 35) < 0.1 and done["outcome"]["error_days"] is not None)
    check("a new open row waits for the visit after", db.brain_predictions.count_documents(
        {"customer_id": "rahul", "status": "open"}) == 1)

    print("Non revenu")
    db.brain_predictions.update_one({"customer_id": "rahul", "status": "open"},
                                    {"$set": {"expires_at": now - dt.timedelta(days=1)}})
    check("the tick closes it", BJ.expire_due() == 1)
    gone = BJ.unpack(db.brain_predictions.find_one({"status": "expired"}))
    check("« non revenu », anonymous", gone["outcome"]["returned"] is False and gone["customer_id"] is None)

    print("Par le passage en caisse")
    db.visits.insert_many([visit("sami", now - dt.timedelta(days=d)) for d in (40, 26, 12)])
    db.customers.insert_one({"id": "sami", "tenant_id": "t1", "name": "Sami", "barcode_id": "FT-SAMI",
                             "visits": 3, "deleted_at": None, "created_at": now - dt.timedelta(days=41)})
    r = http("POST", "/api/owner/scan", headers=OWNER, json={"barcode_id": "FT-SAMI", "amount_paid": 20})
    check("scan ok", r.status_code == 200 or print(r.status_code, r.text[:200]))
    check("the scan judged nothing (no open row before) and opened one",
          db.brain_predictions.count_documents({"customer_id": "sami", "status": "open"}) == 1)

    print("Backtest")
    base = now - dt.timedelta(days=200)
    db.visits.insert_many([visit("bt", base + dt.timedelta(days=10 * i), "t2", 5) for i in range(6)])
    # two scans on one of those days: one visit day
    db.visits.insert_one({**visit("bt", base + dt.timedelta(days=20, minutes=30), "t2", 5), "id": "bt-dup"})
    db.customers.insert_one({"id": "bt", "tenant_id": "t2", "name": "Bt", "visits": 7, "deleted_at": None,
                             "created_at": base})
    out = BJ.backtest("t2", now)
    rows = [BJ.unpack(d) for d in db.brain_predictions.find({"tenant_id": "t2", "source": "backtest"})]
    # 6 visit days: guesses after days 3, 4, 5 are judged by 4, 5, 6; after day 6 (150 days ago, rhythm ~8) he never came back
    check("judged guesses from the third visit day on", out["resolved"] == 3)
    check("the last guess, long past its window: « non revenu »", out["expired"] == 1)
    check("backtest rows are anonymous from the start", all(r["customer_id"] is None for r in rows))
    check("it used the sector's rhythm, never today's shop figure", all(r["features"]["prior_source"] == "secteur" for r in rows))
    check("a second run replaces, never doubles", BJ.backtest("t2", now)["resolved"] == 3
          and db.brain_predictions.count_documents({"tenant_id": "t2", "source": "backtest"}) == 4)
    check("nothing else was written: the client is untouched",
          "brain" not in db.customers.find_one({"id": "bt"}) and db.visits.count_documents({"tenant_id": "t2"}) == 7)

    print("Le tick")
    db.platform_settings.delete_many({"key": {"$regex": "^brain_backtest:"}})
    t1 = server.tick_pass()
    t2 = server.tick_pass()
    ran = list((t1.get("brain_journal") or {}).get("backtest", {})) + list((t2.get("brain_journal") or {}).get("backtest", {}))
    check("one shop per tick, each once", sorted(ran) == ["t1", "t2"])
    check("then nothing left", server.tick_pass()["brain_journal"]["backtest"] == {})

    print("Précision (super admin)")
    r = http("GET", "/api/admin/ai/precision", headers=BOSS)
    d = r.json()
    check("200", r.status_code == 200 or print(r.status_code, r.text[-600:]))
    check("judged and not-returned counted", d["summary"]["checked"] >= 4 and d["summary"]["not_returned"] >= 2)
    check("brain against the plain mean and the 30-day rule",
          all(k in d["summary"] for k in ("brain", "mean", "rule")) and d["summary"]["in_window"] is not None)
    check("calibration buckets", d["summary"]["calibration"] and all("real" in c for c in d["summary"]["calibration"]))
    check("by sector", {x["sector"] for x in d["sectors"]} >= {"salon", "cafe"})
    lb = http("GET", "/api/admin/ai/precision", headers=BOSS, params={"source": "backtest", "sector": "cafe"}).json()
    check("filters: backtest, café only", lb["summary"]["checked"] == 3 and lb["summary"]["not_returned"] == 1)
    check("merchants: refused", http("GET", "/api/admin/ai/precision", headers=OWNER).status_code in (401, 403))
    csv_r = http("GET", "/api/admin/ai/precision/export.csv", headers=BOSS)
    body = csv_r.content.decode("utf-8-sig")
    lines = list(csv.reader(io.StringIO(body), delimiter=";"))
    check("CSV: one row per judged guess", csv_r.status_code == 200 and len(lines) - 1
          == db.brain_predictions.count_documents({"status": {"$in": ["resolved", "expired"]}}))
    check("CSV names nobody (no client, no shop)", "rahul" not in body.lower() and "sami" not in body.lower()
          and "t1" not in [c for row in lines for c in row[:3]] and "customer_id" not in lines[0])
    rb = http("POST", "/api/admin/ai/precision/backtest", headers=BOSS, json={"tenant_id": "t2"})
    check("« Relancer le backtest »", rb.status_code == 200 and rb.json()["done"]["t2"]["resolved"] == 3)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
