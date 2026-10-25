"""
brain-v2 (user, 2026-10-25): the usual rhythm learned from the network per
sector, the window learned from real returns (7 in 10 inside), « confiance »
measured on shops the model did not learn from; backtested shop by shop
without letting a shop see itself; in shadow beside v1 until the super admin
switches on Précision — only once v2 beats v1 and the plain mean.

Run: cd api && /usr/local/bin/python3 tests/test_brain_v2.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-brain-v2")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, show=None):
    global passed, failed
    if not cond and show is not None:
        print("    →", show)
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
    from features import brain_v2 as V2
    from features import client_brain as CB

    db = server.db
    rnd = random.Random(7)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    print("pure")
    check("sector names read as keys", CB.sector_key("Boulangerie") == "bakery" and CB.sector_key("barbier") == "salon"
          and CB.sector_key("salon") == "salon" and CB.sector_key("cbd") == "retail" and CB.sector_key("???") == "other")
    check("groups: gaps band × regularity (measured from 4 gaps)",
          V2.bucket(2, 0.1) == "2|?" and V2.bucket(6, 0.1) == "5-9|a" and V2.bucket(12, 0.9) == "10+|d")
    t = V2.table({"5-9|a": [1.0] * 50, "5-9|b": [1.5] * 10, "2|?": [0.8] * 5})
    check("a small group falls back to its band, then to everyone",
          V2.window_for(t, 6, 0.1)["bucket"] == "5-9|a" and V2.window_for(t, 6, 0.3)["bucket"] == "5-9"
          and V2.window_for(t, 2, None)["bucket"] == "tous")
    check("nothing learned: no window (v1's stands)", V2.window_for(None, 6, 0.1) is None)
    s = sorted([0.5, 0.8, 1.0, 1.2, 2.0] * 10)
    w = V2._window(s)
    check("window = 15th–85th percentile, centre = median",
          0.5 <= w["lo"] <= 0.8 and w["mid"] == 1.0 and 1.2 <= w["hi"] <= 2.0, w)

    now = dt.datetime.now(UTC).replace(microsecond=0)
    db.tenants.insert_many([
        {"id": "b1", "name": "Boulangerie A", "sector": "boulangerie"},
        {"id": "b2", "name": "Bakery B", "sector": "bakery"},
        {"id": "b3", "name": "Boulangerie C", "sector": "boulangerie"},
        {"id": "s1", "name": "Salon", "sector": "salon", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.users.insert_many([
        {"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem"},
        {"email": "o@x.fr", "role": "business_owner", "tenant_id": "s1", "active": True},
    ])
    tok = lambda e, r, t=None: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    BOSS, OWNER = tok("boss@fidclic.com", "super_admin"), tok("o@x.fr", "business_owner", "s1")

    def shop(tid, n_clients, gap, jitter, visits):
        for c in range(n_clients):
            cid = f"{tid}-c{c}"
            t = now - dt.timedelta(days=gap * visits + rnd.uniform(0, gap))
            for _ in range(visits):
                db.visits.insert_one({"tenant_id": tid, "customer_id": cid, "amount_paid": 5.0, "visit_time": t})
                # now and then a holiday: one gap five times the usual (real life — and
                # what drags a plain mean off while a median holds)
                g = gap * rnd.uniform(1 - jitter, 1 + jitter) * (5 if rnd.random() < 0.12 else 1)
                t += dt.timedelta(days=max(0.6, g))
            db.customers.insert_one({"id": cid, "tenant_id": tid, "name": cid, "barcode_id": f"FT-{cid.upper()}",
                                     "visits": visits, "deleted_at": None, "created_at": now - dt.timedelta(days=400)})
    for tid in ("b1", "b2", "b3"):
        shop(tid, 15, 4, 0.5, 14)
    shop("s1", 12, 30, 0.4, 7)

    print("Avant d'apprendre")
    check("no tables: v2 has no calibration", V2.calibration() is None)
    r = http("POST", "/api/admin/ai/precision/champion", headers=BOSS, json={"model": "brain-v2"})
    check("« Passer à brain-v2 » refused, and says why", r.status_code == 409 and "brain-v2" in r.json()["detail"])
    for tid in ("b1", "b2", "b3", "s1"):
        BJ.backtest(tid, now)
    v1_rows = db.brain_predictions.count_documents({"model": "brain-v1", "source": "backtest"})
    check("v1's backtest is there to compare", v1_rows > 300)

    print("Apprendre")
    out = V2.learn(now)
    check("learned from every shop", out["shops"] == 4 and out["returns"] > 300)
    doc = db.brain_models.find_one({"model": "brain-v2"})
    check("network rhythm for bakeries (45 regulars), about 4 days",
          doc["priors"]["a:boulangerie"]["clients"] == 45 and 3 <= doc["priors"]["a:boulangerie"]["gap"] <= 5)
    check("« boulangerie » gets it", V2.sector_prior("boulangerie")[1] == "reseau"
          and 3 <= V2.sector_prior("boulangerie")[0] <= 5)
    check("salons: 12 regulars only — the researched figure of « coiffure mixte » (42 days) stays",
          V2.sector_prior("salon") == (42.0, "secteur"))
    check("a barber chose its activity: 21 days (researched), not the salon's",
          V2.sector_prior({"sector": "salon", "activity_key": "barbier"}) == (21.0, "secteur"))
    check("v1's rows untouched", db.brain_predictions.count_documents({"model": "brain-v1", "source": "backtest"}) == v1_rows)
    v2rows = list(db.brain_predictions.find({"model": "brain-v2", "source": "backtest"}))
    check("v2 backtest rows, anonymous", len(v2rows) > 300 and all(r["customer_id"] is None for r in v2rows))
    check("leave-one-shop-out: each bakery's rhythm came from the 30 regulars of the two others",
          all(r["features"]["prior_source"] == "reseau" for r in v2rows if r["tenant_id"] in ("b1", "b2", "b3")))
    check("… and the salon, alone of its sector, learned nothing from itself",
          all(r["features"]["prior_source"] == "secteur" for r in v2rows if r["tenant_id"] == "s1"))
    win = [r for r in v2rows if r["status"] == "resolved"]
    inside = sum(1 for r in win if r["outcome"]["in_window"]) / len(win)
    check(f"about 7 returns in 10 inside the learned window ({round(100 * inside)} %)", 0.55 <= inside <= 0.85)
    check("once a day: a second look the same day learns nothing", V2.learn_due(now + dt.timedelta(hours=2)) is None)

    print("La règle du passage")
    row = lambda m, e, em: {"model": m, "status": "resolved", "pred": {"confidence": 70},  # noqa: E731
                            "outcome": {"in_window": True, "error_days": e, "error_mean": em, "error_rule": 20}}
    tie = BJ.compare([row("brain-v1", 3, 2) for _ in range(250)] + [row("brain-v2", 2, 2) for _ in range(250)])
    check("as good as the plain mean is not enough: closed, and said",
          not tie["can_switch"] and tie["why_not"] == ["brain-v2 ne se trompe pas moins que la moyenne simple."], tie)
    few = BJ.compare([row("brain-v1", 3, 3) for _ in range(250)] + [row("brain-v2", 1, 3) for _ in range(50)])
    check("better but on 50 guesses only: closed", not few["can_switch"] and "50 prédictions" in few["why_not"][0], few)

    print("Précision")
    d = http("GET", "/api/admin/ai/precision", headers=BOSS, params={"source": "backtest"}).json()
    c = d["compare"]
    check("v1 and v2 side by side", c["v1"]["checked"] > 0 and c["v2"]["checked"] > 0 and d["champion"] == "brain-v1")
    check("v2 errs less than v1 and than the plain mean here",
          c["v2"]["brain"]["median_error"] < c["v1"]["brain"]["median_error"]
          and c["v2"]["brain"]["median_error"] < c["v1"]["mean"]["median_error"], c)
    check("… so the switch opens", c["can_switch"] and c["why_not"] == [])
    check("detail of brain-v2 on request", http("GET", "/api/admin/ai/precision", headers=BOSS,
                                                params={"model": "brain-v2"}).json()["model"] == "brain-v2")
    check("merchants: refused (learn)", http("POST", "/api/admin/ai/precision/learn", headers=OWNER).status_code in (401, 403))
    check("merchants: refused (switch)", http("POST", "/api/admin/ai/precision/champion", headers=OWNER,
                                             json={"model": "brain-v2"}).status_code in (401, 403))

    print("En observation (shadow)")
    CB.ensure("s1")
    cid = "s1-c0"
    db.visits.insert_one({"tenant_id": "s1", "customer_id": cid, "amount_paid": 5.0, "visit_time": now})
    BJ.record_visit("s1", cid, CB.refresh("s1", cid))
    models = sorted(r["model"] for r in db.brain_predictions.find({"customer_id": cid, "status": "open"}))
    check("each visit: the brain in service AND the one in observation guess", models == ["brain-v1", "brain-v2"])
    check("merchants still see v1", db.customers.find_one({"id": cid})["brain"]["model"] == 1)

    print("Passer à brain-v2")
    r = http("POST", "/api/admin/ai/precision/champion", headers=BOSS, json={"model": "brain-v2"})
    check("switched", r.status_code == 200 and CB.champion(fresh=True) == 2)
    done = CB.ensure_all()
    b = db.customers.find_one({"id": "s1-c1"})["brain"]
    check("every client re-learned by v2, with its learned window", sum(done.values()) >= 50 and b["model"] == 2 and b.get("win"))
    p = http("GET", "/api/owner/clients/s1-c1/profil", headers=OWNER).json()
    check("the profile says how v2 counts", "7 sur 10" in p["how"] and p["next"] and p["next"]["confidence"] is not None)
    r = http("POST", "/api/admin/ai/precision/champion", headers=BOSS, json={"model": "brain-v1"})
    check("back to v1 at any time", r.status_code == 200 and CB.champion(fresh=True) == 1
          and CB.ensure_all().get("s1", 0) > 0 and db.customers.find_one({"id": "s1-c1"})["brain"]["model"] == 1)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
