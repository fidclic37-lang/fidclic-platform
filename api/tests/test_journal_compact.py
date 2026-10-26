"""
The prediction journal, stored compact (audit 2026-10-26: ~1 000 bytes a row,
about one row per visit — user: « chhota karo », the same information, keep
everything, the whole history replayed).

    · a row takes about half the room: the features in one short string, the
      window / baselines / outcome as numbers from the day of the last visit
      (the dates they gave are rebuilt from it), Mongo's own _id for the id
    · nothing is lost: what a reader gets back is the row as before — the
      Précision page and the CSV are the same, to the figure
    · rows written before are converted by the tick, a batch at a time, and
      read correctly until then (a journal half old, half new)

Run: cd api && /usr/local/bin/python3 tests/test_journal_compact.py
"""
import asyncio
import csv
import datetime as dt
import io
import os
import random
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-journal-compact")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail}"))


def main():
    import bson
    import server
    import auth
    import httpx
    from features import brain_journal as BJ
    from features import brain_v2 as V2
    from features import client_brain as CB

    db = server.db
    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC).replace(microsecond=0)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    TA = str(uuid.uuid4())                         # real shops have uuid ids
    TB = str(uuid.uuid4())
    db.tenants.insert_many([{"id": TA, "slug": "cafe", "name": "Café", "sector": "cafe", "plan": "vip",
                             "subscription_status": "active", "is_active": True},
                            {"id": TB, "slug": "salon", "name": "Salon", "sector": "salon", "plan": "vip",
                             "subscription_status": "active", "is_active": True}])
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": TA, "active": True},
                          {"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem"}])
    tok = lambda e, r, t=None: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    OWNER, BOSS = tok("o@x.fr", "business_owner", TA), tok("boss@fidclic.com", "super_admin")
    rnd = random.Random(7)
    for tid, n, gap in ((TA, 40, 7), (TB, 25, 30)):
        for c in range(n):
            cid = f"{tid[:4]}-c{c}"
            db.customers.insert_one({"id": cid, "tenant_id": tid, "name": f"C{c}", "barcode_id": "FT-" + cid.replace("-", "").upper(),
                                     "visits": 0, "deleted_at": None, "created_at": now - dt.timedelta(days=400)})
            t = now - dt.timedelta(days=400)
            stop = now - dt.timedelta(days=200 if c < 5 else gap)      # the first five stopped coming
            while t < stop:
                db.visits.insert_one({"id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": cid,
                                      "visit_time": t, "amount_paid": rnd.choice([0, 4.5, 12.0]),
                                      "items": [{"name": "Café"}]})
                t += dt.timedelta(days=max(1.0, rnd.gauss(gap, gap / 3)))

    def size(d):
        return len(bson.BSON.encode({k: v for k, v in d.items()}))

    # ── 1. the format ───────────────────────────────────────────────────────────
    print("Le format")
    BJ.backtest(TA, now)
    BJ.backtest(TB, now)
    raw = list(db.brain_predictions.find({}))
    check(f"the backtest wrote rows ({len(raw)})", len(raw) > 500)
    avg = sum(size(d) for d in raw) / len(raw)
    old = [BJ.legacy(BJ.unpack(d)) for d in raw]
    avg_old = sum(size(d) for d in old) / len(old)
    check(f"a row takes about half the room ({avg:.0f} B, was {avg_old:.0f} B)", avg <= 520 and avg <= 0.55 * avg_old)
    d = raw[0]
    check("no second id: Mongo's _id is the row's id", "id" not in d and "_id" in d)
    check("the bulky parts are compact (f, p, b, o), the queried fields keep their names",
          not {"features", "pred", "baselines", "outcome", "resolved_at"} & set(d)
          and {"kind", "model", "source", "tenant_id", "sector", "status", "made_at", "basis_last"} <= set(d), sorted(d))
    check("a closed row keeps neither client nor expiry", all("customer_id" not in x and "expires_at" not in x
                                                              for x in raw))

    # ── 2. nothing is lost ─────────────────────────────────────────────────────
    print("Rien n'est perdu")
    full = [BJ.unpack(x) for x in raw]
    check("every reader gets the row as before", all(
        {"kind", "model", "source", "tenant_id", "sector", "customer_id", "made_at", "basis_last", "pred",
         "baselines", "features", "status", "expires_at", "outcome"} <= set(r) for r in full))
    r = next(x for x in full if x["status"] == "resolved")
    last = CB._aware(r["basis_last"])
    p = r["pred"]
    check("the window: from < centre < to, centre = last visit + rhythm",
          CB._aware(p["from"]) < CB._aware(p["centre"]) < CB._aware(p["to"])
          and abs((CB._aware(p["centre"]) - last).total_seconds() / 86400 - p["gap_days"]) < 1e-6)
    check("the shop's rule date = last visit + its days",
          CB._aware(r["baselines"]["rule"]) == last + dt.timedelta(days=r["baselines"]["rule_days"]))
    check("the outcome: the real visit, to the second",
          abs((CB._aware(r["outcome"]["actual"]) - last).total_seconds() / 86400 - r["outcome"]["actual_gap"]) < 0.06)
    check("features: numbers stay numbers, words stay words",
          isinstance(r["features"]["visits_n"], int) and isinstance(r["features"]["gap_days"], float)
          and r["features"]["prior_source"] == "secteur" and set(r["features"]) == set(BJ.FEATURE_KEYS))
    e = next((x for x in full if x["status"] == "expired"), None)
    check("« non revenu »: returned False, never in the window",
          e and e["outcome"]["returned"] is False and e["outcome"]["in_window"] is False)
    # exact round trip on built rows, odd values included
    b = {"last": now - dt.timedelta(days=3), "gap_days": 6.25, "confidence": None, "visits_n": 3, "n_gaps": 2,
         "trend": None, "slot": {"key": "soir", "share": 0.333333333333}, "weekday": {"key": 4, "share": 1.0},
         "basket": None, "cv": 0.0}
    made = BJ.make(TA, "cafe", {**b, "known": True}, [], now, "live", "x1", 45) or \
        BJ.make(TA, "cafe", b, [6.0, 6.5], now, "live", "x1", 45)
    if made:
        made.pop("id", None)
        back = BJ.unpack(BJ.pack(made))
        check("an open row comes back identical (None, 0.0, words, 1/3 kept as they were)",
              {k: v for k, v in back.items() if k != "_id"} == made,
              {k: (made.get(k), back.get(k)) for k in set(made) | set(back) if made.get(k) != back.get(k)})
    else:
        check("an open row comes back identical", False, "make() gave nothing")

    # ── 3. the same figures, to the digit ──────────────────────────────────────
    print("Les mêmes chiffres")

    def figures():
        pr = http("GET", "/api/admin/ai/precision", headers=BOSS).json()
        pr.pop("learned", None)
        for x in pr.get("runs") or []:
            x.pop("at", None)
        body = http("GET", "/api/admin/ai/precision/export.csv", headers=BOSS).content.decode("utf-8-sig")
        return pr, sorted(csv.reader(io.StringIO(body), delimiter=";"))

    new_pr, new_csv = figures()
    # the same journal, written the old way
    db.brain_predictions.delete_many({})
    db.brain_predictions.insert_many([BJ.legacy(x) for x in full])
    old_pr, old_csv = figures()
    check("Précision: the same page", new_pr == old_pr)
    check(f"CSV: the same {len(new_csv) - 1} lines, the same columns", new_csv == old_csv and len(new_csv) > 500)
    check("CSV header unchanged", new_csv[-1][:3] != [] and BJ.CSV_COLUMNS[:3] == ["model", "source", "sector"])

    # ── 4. the old rows are converted by the tick ──────────────────────────────
    print("Conversion des anciennes lignes")
    n_old = db.brain_predictions.count_documents({})
    first = BJ.compact_due(batch=200)
    check(f"one batch at a time ({first['converted']})", first["converted"] == 200)
    mixed_pr, mixed_csv = figures()
    check("half old, half new: still the same figures", mixed_pr == old_pr and mixed_csv == old_csv)
    rounds = 1
    while BJ.compact_due(batch=200)["converted"]:
        rounds += 1
    check(f"…until none is left ({rounds} batches)", db.brain_predictions.count_documents({"features": {"$exists": True}}) == 0
          and db.brain_predictions.count_documents({}) == n_old)
    check("then the tick knows it is done (no scan of the journal every 15 minutes)",
          BJ.compact_due(batch=200).get("done") is True
          and (db.platform_settings.find_one({"key": "brain_journal_compact"}) or {}).get("done") is True)
    after_pr, after_csv = figures()
    check("after: the same figures", after_pr == old_pr and after_csv == old_csv)
    avg2 = sum(size(x) for x in db.brain_predictions.find({})) / n_old
    check(f"…in about half the room ({avg2:.0f} B a row)", avg2 <= 520)
    check("converting again changes nothing", BJ.compact_due(batch=200, force=True)["converted"] == 0)
    db.platform_settings.delete_one({"key": "brain_journal_compact"})
    t = server.tick_pass()
    check("the tick runs it", "compact" in (t.get("brain_journal") or {}), t.get("brain_journal"))

    # ── 5. live: open rows, old or new, are judged ─────────────────────────────
    print("En direct")
    cid = f"{TA[:4]}-c1"
    db.brain_predictions.delete_many({"customer_id": cid})
    bb = CB.refresh(TA, cid)
    BJ.record_visit(TA, cid, bb)
    opened = list(db.brain_predictions.find({"customer_id": cid, "status": "open"}))
    check("a scan opens a compact row, with the client and its expiry while it waits",
          len(opened) >= 1 and all("f" in x and "expires_at" in x and "id" not in x for x in opened))
    # an open row written before (old shape, its own « id »)
    legacy_open = BJ.legacy(BJ.unpack(opened[0]))
    legacy_open.pop("_id", None)
    db.brain_predictions.delete_many({"customer_id": cid})
    db.brain_predictions.insert_one(dict(legacy_open))
    r = http("POST", "/api/owner/scan", headers=OWNER, json={"barcode_id": "FT-" + cid.replace("-", "").upper(), "amount_paid": 4})
    check(f"the scan ({r.status_code})", r.status_code == 200, r.text[:200])
    judged = db.brain_predictions.find_one({"tenant_id": TA, "source": "live", "status": "resolved"})
    check("the old open row is judged, and written compact", judged and "o" in judged and "features" not in judged
          and "customer_id" not in judged, judged and sorted(judged))
    check("…its outcome: the real visit", judged and BJ.unpack(judged)["outcome"]["returned"] is True)
    check("a new compact row waits for the next visit",
          db.brain_predictions.count_documents({"customer_id": cid, "status": "open", "f": {"$exists": True}}) >= 1)
    db.brain_predictions.update_many({"customer_id": cid, "status": "open"},
                                     {"$set": {"expires_at": now - dt.timedelta(days=1)}})
    leg2 = dict(legacy_open, id=str(uuid.uuid4()), expires_at=now - dt.timedelta(days=1), customer_id="ghost")
    db.brain_predictions.insert_one(leg2)
    n = BJ.expire_due()
    gone = list(db.brain_predictions.find({"status": "expired", "source": "live"}))
    check(f"the tick closes open rows, old or new ({n})", n >= 2 and all("customer_id" not in g and "o" in g for g in gone))

    # ── 6. brain-v2 writes compact rows too ────────────────────────────────────
    print("brain-v2")
    V2.learn(now)
    v2 = list(db.brain_predictions.find({"model": "brain-v2"}))
    check(f"its backtest rows are compact ({len(v2)})", v2 and all("f" in x and "features" not in x for x in v2))
    check("an empty journal: the page still answers", True)
    db.brain_predictions.delete_many({})
    db.brain_journal_stats.delete_many({})              # an empty journal has empty tallies (features/journal_stats)
    r = http("GET", "/api/admin/ai/precision", headers=BOSS)
    check("…200, nothing checked", r.status_code == 200 and r.json()["summary"]["checked"] == 0)
    check("merchants: refused", http("GET", "/api/admin/ai/precision/export.csv", headers=OWNER).status_code in (401, 403))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
