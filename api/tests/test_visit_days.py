"""
« Roz ka hisaab » — the register of each past day's visits (user, 2026-10-28).

The Tableau de bord read every visit of its period, twice (and the month once
more), and rebuilt a client brain per visit for « attendus »: 2.9 s for a
2 000-client shop, locally. Now each finished Paris day is summed once into
`visit_days` and read from there; today stays live.

    · the figures are EXACTLY the ones read from the visits — every period,
      every establishment, DST days, odd rows
    · a change to a past day (a visit added, edited, moved, deleted,
      unlinked; a message, a campaign, a parrainage that changes what
      FidClic brought) rebuilds that day — and the later days of the same
      clients, whose « attendus » read their history — at once
    · a change landing while a day is being summed never leaves a stale day
    · a new brain (champion, the shop's rhythm) recounts « attendus » in the
      background; days without a candidate are not touched
    · a shop never reads or invalidates another's register

Run: cd api && /usr/local/bin/python3 tests/test_visit_days.py
"""
import datetime as dt
import os
import random
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-visit-days")
os.environ.setdefault("DISABLE_SEED", "1")
UTC, PARIS = dt.timezone.utc, ZoneInfo("Europe/Paris")
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:400]}"))


def diff(a, b, path=""):
    """The first place two payloads differ, or None."""
    if type(a) is not type(b):
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                return f"{path}.{k}: missing on one side"
            d = diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} items != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


def main():
    import server
    from features import dashboard_home as DH, visit_days as VD, client_brain as CB, ai_jobs as AJ

    db = server.db
    rnd = random.Random(28)
    AT = [dt.datetime(2026, 10, 28, 11, 0, tzinfo=UTC)]          # 12:00 in Paris

    def now():
        return AT[0]
    DH._now = now
    VD._now = now

    class TD:
        email, role, tenant_id = "owner@t1.fr", "business_owner", "t1"

    class TD2:
        email, role, tenant_id = "owner@t2.fr", "business_owner", "t2"

    class Req:
        def __init__(self, store=None):
            self.query_params = {"store": store} if store else {}
            self.headers = {}

    db.tenants.insert_many([
        {"id": "t1", "name": "Café Test", "city": "Tours", "sector": "cafe", "plan": "vip",
         "branches": [{"id": "main", "name": "Centre"}, {"id": "b2", "name": "Plumereau"},
                      {"id": "b3", "name": "Gare"}, {"id": "gone", "name": "Fermé", "status": "closed"}]},
        {"id": "t2", "name": "Rival", "sector": "cafe"}])
    db.users.insert_many([{"email": "owner@t1.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "owner@t2.fr", "role": "business_owner", "tenant_id": "t2"},
                          {"email": "mgr@t1.fr", "role": "manager", "tenant_id": "t1", "branch_ids": ["b2"]}])

    # ── data: regular clients over 26 months, every kind of message ──────────
    STORES = [None, "main", "b2", "", "b3", "gone"]
    NAMES = ["Café", "Croissant", "Thé.vert", "$pécial", "  Latte  ", "", None]
    AT0 = AT[0]
    customers, visits = [], []
    for i in range(28):
        cid = f"c{i:02d}"
        gap = rnd.choice([5, 6, 7, 9, 12, 15, 20])
        home = rnd.choice(STORES)
        t = AT0 - dt.timedelta(days=790 - rnd.random() * gap)
        n = 0
        while t < AT0 + dt.timedelta(days=2):          # a few rows in the future: never counted
            items = [{"name": rnd.choice(NAMES), "price": rnd.choice([2, 3.5, 4.2, None]),
                      **({"qty": rnd.choice([1, 2, 3])} if rnd.random() < .6 else
                         {"quantity": rnd.choice([1, 2])} if rnd.random() < .5 else {})}
                     for _ in range(rnd.choice([0, 1, 1, 2, 3]))]
            vt = t if rnd.random() < .85 else (t.replace(tzinfo=None) if rnd.random() < .5 else t.isoformat())
            visits.append({"id": f"v{len(visits):05d}", "tenant_id": "t1", "customer_id": cid,
                           "branch_id": home if rnd.random() < .8 else rnd.choice(STORES),
                           "amount_paid": rnd.choice([round(rnd.uniform(2, 40), 2), 0, None, "12.5"]),
                           "visit_time": vt, "items": items if rnd.random() < .95 else None})
            n += 1
            t = t + dt.timedelta(days=gap * rnd.uniform(.7, 1.3), hours=rnd.uniform(-5, 5))
        customers.append({"id": cid, "tenant_id": "t1", "name": f"Client {i}", "visits": n,
                          "branch_id": home, "created_at": AT0 - dt.timedelta(days=800)})
    visits.append({"id": "v-notime", "tenant_id": "t1", "customer_id": "c01", "amount_paid": 9})
    # the night of the change to winter time, and midnight in Paris
    for when in (dt.datetime(2026, 10, 25, 0, 30, tzinfo=UTC), dt.datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
                 dt.datetime(2026, 10, 24, 22, 0, tzinfo=UTC), dt.datetime(2026, 3, 29, 1, 30, tzinfo=UTC)):
        visits.append({"id": f"v-dst-{when:%m%d%H}", "tenant_id": "t1", "customer_id": "c02",
                       "branch_id": "b2", "amount_paid": 7, "visit_time": when, "items": [{"name": "Café"}]})
    db.customers.insert_many(customers)
    db.visits.insert_many(visits)

    KINDS = ["campaign", "offer", "birthday", "inactive", "geofence", "proximity", "welcome", "manual",
             "flash_sale", "news", "reactivation"]
    notes, wallet = [], []
    for c in customers:
        for _ in range(30):
            at = AT0 - dt.timedelta(days=rnd.uniform(0, 780))
            notes.append({"tenant_id": "t1", "customer_id": c["id"], "type": rnd.choice(KINDS), "sent_at": at,
                          "campaign_id": rnd.choice([None, "k1", "k2"]), "temoin": rnd.random() < .1})
        for _ in range(4):
            wallet.append({"id": f"w{len(wallet)}", "tenant_id": "t1", "customer_id": c["id"],
                           "sent_at": AT0 - dt.timedelta(days=rnd.uniform(0, 780)), "scenario_id": "old"})
    db.push_notifications.insert_many(notes)
    db.push_wallet_log.insert_many(wallet)
    db.campaigns.insert_many([{"id": f"k{j}", "tenant_id": "t1", "name": f"Camp {j}", "status": "sent",
                               "sent_at": AT0 - dt.timedelta(days=rnd.uniform(0, 700)),
                               "recipient_ids": rnd.sample([c["id"] for c in customers], 8),
                               **({"holdout_ids": ["c27"]} if j % 2 else {})} for j in range(16)])
    db.referral_redemptions.insert_one({"tenant_id": "t1", "referee_customer_id": "c05", "referrer_customer_id": "c06"})
    db.visits.insert_one({"id": "r1", "tenant_id": "t2", "customer_id": "x1", "amount_paid": 500,
                          "visit_time": AT0 - dt.timedelta(days=3)})
    db.customers.insert_one({"id": "x1", "tenant_id": "t2", "name": "Rival", "created_at": AT0 - dt.timedelta(days=9)})
    with_brains = 0
    for c in customers:
        if CB.refresh("t1", c["id"]):
            with_brains += 1
    CB._usual_cache.clear()

    def both(days=30, store=None, td=TD):
        CB._usual_cache.clear()
        VD.ENABLED = False
        want = DH.overview(request=Req(store), days=days, token_data=td())
        VD.ENABLED = True
        got = DH.overview(request=Req(store), days=days, token_data=td())
        return want, got

    def same(label, days=30, store=None, td=TD):
        want, got = both(days, store, td)
        d = diff(want, got)
        check(label, d is None, d)
        return want, got

    # ── 1. the data is worth testing ──────────────────────────────────────────
    print("Les données")
    w, _ = both(365)
    imp = w["impact"]
    full = FI_impact = None
    from features import fidclic_impact as FI
    rows = list(db.visits.find({"tenant_id": "t1"}, {"_id": 0}))
    full = FI.impact("t1", [r for r in rows if FI._aware(r.get("visit_time")) and FI._aware(r["visit_time"]) <= AT0])
    check(f"brains learned ({with_brains}), CA FidClic split by source, « attendus » non-zero "
          f"({full['attendus']['visits']})", with_brains > 10 and full["attendus"]["visits"] > 0
          and sum(1 for s in full["sources"].values() if s["visits"]) >= 3, full)

    # ── 2. exactly the same figures ───────────────────────────────────────────
    print("Mêmes chiffres, registre froid puis chaud")
    for days in (1, 2, 7, 30, 45, 90, 365, 730):
        for store in (None, "main", "b2", "b3"):
            same(f"{days} jour(s), {store or 'tous'}: identical (cold)", days, store)
    n_docs = db.visit_days.count_documents({"tenant_id": "t1"})
    check(f"one register row per finished day ({n_docs})", 700 <= n_docs <= 2 * 730 + 2, n_docs)
    check("no row for today or the future", db.visit_days.count_documents(
        {"tenant_id": "t1", "day": {"$gte": AT0.astimezone(PARIS).date().isoformat()}}) == 0)
    reads = {"n": 0}
    real = VD._raw

    def counting(*a, **k):
        out = real(*a, **k)
        if VD.ENABLED:                      # the register's read, not the reference's
            reads["n"] += len(out)
        return out
    VD._raw = counting
    for days in (30, 365):
        for store in (None, "b2"):
            same(f"{days} jours, {store or 'tous'}: identical (warm)", days, store)
    VD._raw = real
    today = sum(1 for r in rows if FI._aware(r.get("visit_time")) and
                FI._aware(r["visit_time"]).astimezone(PARIS).date() == AT0.astimezone(PARIS).date())
    check(f"warm: only today's and the cut days' visits are read ({reads['n']} rows for 4 pages; "
          f"{len(rows)} in the shop)", reads["n"] < len(rows) / 4, reads)
    _, g = both(30)
    # (a visit_time kept as text was never in a period: the date filter skips it)
    rev = sum(float(r.get("amount_paid") or 0) for r in rows if isinstance(r.get("visit_time"), dt.datetime)
              and DH._window(30)[0] <= FI._aware(r["visit_time"]) <= AT0)
    check(f"the revenue is the visits' sum ({g['revenue_total']} €)", abs(g["revenue_total"] - round(rev, 2)) < .005)

    # ── 3. DST, midnight, the month's first day ───────────────────────────────
    print("Heure d'hiver / d'été")
    for at in (dt.datetime(2026, 10, 25, 22, 30, tzinfo=UTC), dt.datetime(2026, 10, 26, 0, 30, tzinfo=UTC),
               dt.datetime(2026, 3, 29, 10, 0, tzinfo=UTC), dt.datetime(2026, 10, 1, 0, 15, tzinfo=UTC),
               dt.datetime(2026, 9, 30, 22, 15, tzinfo=UTC)):
        AT[0] = at
        for days in (1, 7, 30):
            same(f"{at.astimezone(PARIS):%d/%m %H:%M} Paris, {days} j: identical", days)
    AT[0] = AT0

    # ── 4. a change to a past day shows at once ───────────────────────────────
    print("Un jour passé qui change")
    stamps = lambda: {d["day"]: d.get("n") for d in db.visit_days_stamps.find({"tenant_id": "t1"}, {"_id": 0})}

    def changed(label, fn, days=30, store=None, moves=True):
        both(days, store)                                     # warm
        before = DH.overview(request=Req(store), days=days, token_data=TD())
        fn()
        w2, g2 = both(days, store)
        d = diff(w2, g2)
        check(f"{label}: identical after", d is None, d)
        if moves:
            check(f"{label}: …and the page moved", diff(before, g2) is not None)

    two = AT0 - dt.timedelta(days=2)
    changed("a visit added two days ago (Tampons papier, import)", lambda: db.visits.insert_one(
        {"id": "new1", "tenant_id": "t1", "customer_id": "c03", "branch_id": "b2", "amount_paid": 33.3,
         "visit_time": two, "items": [{"name": "Gâteau", "price": 33.3}]}))
    changed("its amount edited", lambda: db.visits.update_one({"id": "new1"}, {"$set": {"amount_paid": 44}}))
    changed("moved to another day", lambda: db.visits.update_one(
        {"id": "new1"}, {"$set": {"visit_time": AT0 - dt.timedelta(days=9)}}))
    changed("moved to another establishment", lambda: db.visits.update_many(
        {"tenant_id": "t1", "customer_id": "c03"}, {"$set": {"branch_id": "b3"}}), store="b2")
    changed("find_one_and_update", lambda: db.visits.find_one_and_update(
        {"id": "new1"}, {"$set": {"amount_paid": 5}}))
    changed("replace_one", lambda: db.visits.replace_one(
        {"id": "new1"}, {"id": "new1", "tenant_id": "t1", "customer_id": "c03", "branch_id": "b2",
                         "amount_paid": 61, "visit_time": two}))
    changed("deleted", lambda: db.visits.delete_one({"id": "new1"}))
    changed("a client's visits deleted", lambda: db.visits.delete_many({"tenant_id": "t1", "customer_id": "c09"}), 90)
    changed("visits unlinked from their client (RGPD)", lambda: db.visits.update_many(
        {"tenant_id": "t1", "customer_id": "c10"}, {"$set": {"customer_id": None}}), 365)
    target = next(r for r in sorted(rows, key=lambda r: str(r.get("visit_time")), reverse=True)
                  if r.get("customer_id") == "c11" and isinstance(r.get("visit_time"), dt.datetime)
                  and FI._aware(r["visit_time"]) < AT0 - dt.timedelta(days=2))
    tv = FI._aware(target["visit_time"])
    s1 = stamps().get(VD.day_of(tv), 0)
    changed("a message dated before an old visit (CA FidClic)", lambda: db.push_notifications.insert_one(
        {"tenant_id": "t1", "customer_id": "c11", "type": "proximity", "sent_at": tv - dt.timedelta(hours=3)}),
        365, moves=False)
    check("…that visit's day is summed again", stamps().get(VD.day_of(tv), 0) > s1)
    changed("old Wallet pushes deleted (automations engine)", lambda: db.push_wallet_log.delete_many(
        {"tenant_id": "t1", "scenario_id": "old"}), 365)
    changed("a campaign's recipients corrected", lambda: db.campaigns.update_one(
        {"id": "k3"}, {"$set": {"recipient_ids": ["c12", "c13"]}}), 730, moves=False)
    changed("a campaign deleted", lambda: db.campaigns.delete_one({"id": "k4"}), 730, moves=False)
    changed("a filleul recorded after their visits", lambda: db.referral_redemptions.insert_one(
        {"tenant_id": "t1", "referee_customer_id": "c14", "referrer_customer_id": "c15"}), 365)
    s0 = stamps()
    db.push_notifications.update_many({"tenant_id": "t1"}, {"$set": {"opened_at": AT0}})
    db.campaigns.update_one({"id": "k5"}, {"$inc": {"clicks": 1}})
    db.push_wallet_log.update_one({"id": "w1"}, {"$set": {"clicked_at": AT0}})
    check("what changes no figure (opened, clicked) rebuilds nothing", stamps() == s0)
    db.visits.insert_one({"id": "today1", "tenant_id": "t1", "customer_id": "c16", "branch_id": "main",
                          "amount_paid": 18, "visit_time": AT0 - dt.timedelta(minutes=5)})
    db.push_notifications.insert_one({"tenant_id": "t1", "customer_id": "c16", "type": "offer", "sent_at": AT0})
    check("a scan today and a send now rebuild nothing", stamps() == s0)
    w3, g3 = both(1)
    check("…and today's scan shows at once", diff(w3, g3) is None and g3["revenue_total"] >= 18)

    # ── 5. a change while a day is being summed ───────────────────────────────
    print("Un changement pendant le calcul")
    db.visit_days.delete_many({"tenant_id": "t1"})
    once = {"done": False}
    real = VD._raw

    def racing(*a, **k):
        out = real(*a, **k)
        if not once["done"]:
            once["done"] = True
            db.visits.insert_one({"id": "race1", "tenant_id": "t1", "customer_id": "c17", "branch_id": "b2",
                                  "amount_paid": 99, "visit_time": AT0 - dt.timedelta(days=4)})
        return out
    VD._raw = racing
    DH.overview(request=Req(), days=30, token_data=TD())
    VD._raw = real
    same("a visit written mid-sum is in the next read")

    # ── 6. a new brain ─────────────────────────────────────────────────────────
    print("Nouveau cerveau")
    same("warm before", 365)
    built = {d["day"]: d.get("built_at") for d in db.visit_days.find({"tenant_id": "t1"}, {"_id": 0})}
    db.platform_settings.update_one({"key": "brain_champion"}, {"$set": {"key": "brain_champion", "value": 2}}, upsert=True)
    CB.champion(fresh=True)
    VD._bv_cache.clear()                     # (the version is re-read every 10 minutes)
    t0 = time.time()
    DH.overview(request=Req(), days=365, token_data=TD())
    check(f"the page still answers from the register ({time.time() - t0:.2f}s)",
          db.ai_jobs.count_documents({"kind": "visit_days", "tenant_id": "t1", "status": {"$in": ["queued", "running"]}}) == 1)
    for _ in range(40):
        if not AJ.run(budget_s=30):
            break
    after = {d["day"]: d for d in db.visit_days.find({"tenant_id": "t1"}, {"_id": 0})}
    redone = [d for d in after if after[d].get("built_at") != built.get(d)]
    quiet = [d for d in redone if not after[d].get("cand")]
    check(f"recounted in the background ({len(redone)} days), only days with a candidate ({len(quiet)} others)",
          redone and not quiet, quiet[:5])
    same("…and identical to the new brain's figures", 365)
    db.platform_settings.update_one({"key": "brain_champion"}, {"$set": {"value": 1}})
    CB.champion(fresh=True)

    # ── 7. one shop, one register ─────────────────────────────────────────────
    print("Chaque commerce le sien")
    s0 = stamps()
    db.visits.insert_one({"id": "r2", "tenant_id": "t2", "customer_id": "x1", "amount_paid": 7,
                          "visit_time": AT0 - dt.timedelta(days=5)})
    check("another shop's visit never touches this register", stamps() == s0)
    w4, g4 = both(30, td=TD2)
    check(f"the other shop reads its own ({g4['revenue_total']} €)", diff(w4, g4) is None and g4["revenue_total"] == 507)
    check("…from its own rows", not db.visit_days.find_one({"tenant_id": "t2", "stores.s": {"$in": ["b2", "~none"]}})
          or all(d["tenant_id"] == "t2" for d in db.visit_days.find({"tenant_id": "t2"}, {"_id": 0})))

    # ── 8. an empty shop, an empty day ────────────────────────────────────────
    print("Commerce vide")
    db.tenants.insert_one({"id": "t3", "name": "Vide"})

    class TD3:
        email, role, tenant_id = "o@t3.fr", "business_owner", "t3"
    db.users.insert_one({"email": "o@t3.fr", "role": "business_owner", "tenant_id": "t3"})
    w5, g5 = both(30, td=TD3)
    check("a shop with no visit: identical, zero", diff(w5, g5) is None and g5["revenue_total"] == 0)
    n3 = db.visit_days.count_documents({"tenant_id": "t3"})
    DH.overview(request=Req(), days=30, token_data=TD3())
    check(f"its empty days are written once, not summed on every read ({n3})",
          n3 == db.visit_days.count_documents({"tenant_id": "t3"}) and n3 >= 29)

    # ── 8b. ties among products ───────────────────────────────────────────────
    print("Produits à égalité")
    T = VD.Totals()
    T.add("2026-10-01", {"n": 0, "r": 0, "h": {}, "att": [0, 0], "src": {}, "cand": 0,
                         "p": {"Bagel": [3, 6 * VD.MICRO], "Café": [3, 9 * VD.MICRO], "Jus": [3, 6 * VD.MICRO],
                               "Thé": [5, 1 * VD.MICRO]}})
    check("most sold first; at equal sales the one that brought more; then by name",
          [p["name"] for p in T.top_products(5)] == ["Thé", "Café", "Bagel", "Jus"], T.top_products(5))
    check("top 2 is two", len(T.top_products(2)) == 2 and VD.Totals().top_products(5) == [])

    # ── 8c. a shop whose register was never opened ────────────────────────────
    # An import of old visits (or a test seeding thousands) must not pay a
    # hearing per row for a register nobody has read yet: its first read sums
    # every day from the visits anyway.
    print("Registre jamais ouvert")
    db.tenants.insert_many([{"id": "t4", "name": "Neuf"}, {"id": "t5", "name": "Course"}])

    class TD4:
        email, role, tenant_id = "o@t4.fr", "business_owner", "t4"

    class TD5:
        email, role, tenant_id = "o@t5.fr", "business_owner", "t5"
    db.users.insert_many([{"email": "o@t4.fr", "role": "business_owner", "tenant_id": "t4"},
                          {"email": "o@t5.fr", "role": "business_owner", "tenant_id": "t5"}])
    heard = {"n": 0}
    real_later = VD._later_days

    def counted(*a, **k):
        heard["n"] += 1
        return real_later(*a, **k)
    VD._later_days = counted
    for i in range(20):
        db.visits.insert_one({"id": f"n{i}", "tenant_id": "t4", "customer_id": f"y{i % 4}", "branch_id": "main",
                              "amount_paid": 5 + i, "visit_time": AT0 - dt.timedelta(days=3 + i, hours=i % 5)})
    db.visits.update_one({"id": "n3"}, {"$set": {"amount_paid": 40}})
    check("old visits written before any read: no hearing, no stamp",
          heard["n"] == 0 and db.visit_days_stamps.count_documents({"tenant_id": "t4"}) == 0, heard)
    same("…and its first read counts them all", 30, td=TD4)
    db.visits.insert_one({"id": "n99", "tenant_id": "t4", "customer_id": "y1", "branch_id": "main",
                          "amount_paid": 12, "visit_time": AT0 - dt.timedelta(days=6)})
    check("once read, an old visit is heard", heard["n"] > 0 and db.visit_days_stamps.count_documents(
        {"tenant_id": "t4", "day": VD.day_of(AT0 - dt.timedelta(days=6))}) == 1)
    same("…and the page moves with it", 30, td=TD4)
    VD._later_days = real_later

    for i in range(6):
        db.visits.insert_one({"id": f"q{i}", "tenant_id": "t5", "customer_id": "z1", "branch_id": "main",
                              "amount_paid": 10, "visit_time": AT0 - dt.timedelta(days=2 + 3 * i)})
    once["done"] = False

    def racing5(*a, **k):
        out = real(*a, **k)
        if not once["done"]:
            once["done"] = True
            db.visits.insert_one({"id": "q99", "tenant_id": "t5", "customer_id": "z1", "branch_id": "main",
                                  "amount_paid": 77, "visit_time": AT0 - dt.timedelta(days=4)})
        return out
    import mongomock.collection as MC
    writes = {"n": 0}
    real_bulk, real_replace = MC.Collection.bulk_write, MC.Collection.replace_one

    def count(fn):
        def wrapped(self, *a, **k):
            if self.name == "visit_days":
                writes["n"] += 1
            return fn(self, *a, **k)
        return wrapped
    MC.Collection.bulk_write, MC.Collection.replace_one = count(real_bulk), count(real_replace)
    VD._raw = racing5
    DH.overview(request=Req(), days=30, token_data=TD5())
    VD._raw = real
    MC.Collection.bulk_write, MC.Collection.replace_one = real_bulk, real_replace
    check(f"a first read writes its days in one request, not one per day ({writes['n']})", writes["n"] == 1)
    w6, g6 = same("a visit written during a shop's very first sum is in the next read", 30, td=TD5)
    check("…all 7 of them", g6["revenue_total"] == 137, g6["revenue_total"])

    # ── 9. through HTTP, with a manager's establishment ──────────────────────
    print("HTTP")
    import asyncio
    import auth
    import httpx

    def get(url, token, store=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as ac:
                return await ac.get(url, headers={"Authorization": f"Bearer {token}",
                                                  **({"X-FidClic-Store": store} if store else {})})
        return asyncio.new_event_loop().run_until_complete(run())
    real_now = dt.datetime.now(UTC)
    DH._now = lambda: real_now
    VD._now = lambda: real_now
    mgr = auth.create_access_token({"sub": "mgr@t1.fr", "role": "manager", "tenant_id": "t1"})
    VD.ENABLED = False
    want = get("/api/owner/home/overview?days=90", mgr).json()
    VD.ENABLED = True
    r = get("/api/owner/home/overview?days=90", mgr)
    got = r.json()
    check(f"a manager of Plumereau: identical through HTTP ({r.status_code})", r.status_code == 200 and diff(want, got) is None,
          diff(want, got))
    r = get("/api/owner/home/overview?days=90", mgr, store="main")
    check("…and never the establishments they don't cover", r.json().get("scope", {}).get("ids") == ["b2"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
