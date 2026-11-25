"""
« Inactif après N jours » counted on the Paris clock (user, 2026-11-25).

What this guards: a client becomes inactive at the same Paris clock time as
their last visit, N + 1 calendar days later — never an hour early or late
because France changed its clocks in between. Seen in a live shop, 2026-11-25:
a client came on 20 Oct at 12:22 (summer time) and, with a 35-day rule, showed
in « Clients inactifs » from 11:22 on 25 Nov instead of 12:22, because the
count used 36 × 24 hours and the night of 25 Oct had 25 of them.

Every place that draws the actif / inactif line must flip at the same instant:
the Clients page (chip + list), Règles clients (Statut), Segmentation
(« Clients inactifs ») and the relance automation.

Run:
    cd api && python3 tests/test_inactive_paris_clock.py
"""
import asyncio
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import httpx
import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

UTC = dt.timezone.utc
PARIS = ZoneInfo("Europe/Paris")


def paris(*a, fold=0):
    return dt.datetime(*a, tzinfo=PARIS, fold=fold).astimezone(UTC)


def utc(*a):
    return dt.datetime(*a, tzinfo=UTC)


with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from services import paris_clock as PC
    from features import customer_rules as R
    from features import clients_page as CP
    from features import segmentation as SG
    from features import automations as AU
    import auth

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    # ------------------------------------------------------------------ unit
    print("\nparis_clock.days_between — calendar days on the Paris clock")
    check("plain 10 days", PC.days_between(paris(2026, 11, 1, 9, 0), paris(2026, 11, 11, 9, 0)) == 10.0)
    check("across the October change: 20 Oct 12:22 → 25 Nov 12:22 = 36.0",
          PC.days_between(paris(2026, 10, 20, 12, 22), paris(2026, 11, 25, 12, 22)) == 36.0)
    check("…and 25 Nov 11:22 is still under 36",
          PC.days_between(paris(2026, 10, 20, 12, 22), paris(2026, 11, 25, 11, 22)) < 36.0)
    check("across the March change: 20 Mar 12:00 → 25 Apr 12:00 = 36.0",
          PC.days_between(paris(2027, 3, 20, 12, 0), paris(2027, 4, 25, 12, 0)) == 36.0)
    check("half a day is 0.5", PC.days_between(paris(2026, 11, 1, 0, 0), paris(2026, 11, 1, 12, 0)) == 0.5)
    check("zero", PC.days_between(paris(2026, 11, 1, 8, 0), paris(2026, 11, 1, 8, 0)) == 0.0)
    check("backwards is negative", PC.days_between(paris(2026, 11, 3, 8, 0), paris(2026, 11, 1, 8, 0)) == -2.0)
    check("a naive date is read as UTC",
          PC.days_between(dt.datetime(2026, 10, 20, 10, 22), utc(2026, 11, 25, 11, 22)) == 36.0)
    check("an ISO string is read", PC.days_between("2026-10-20T10:22:00+00:00", utc(2026, 11, 25, 11, 22)) == 36.0)
    check("no date → None", PC.days_between(None, utc(2026, 11, 25)) is None)
    check("garbage → None", PC.days_between("pas une date", utc(2026, 11, 25)) is None)
    big = dt.datetime.max.replace(tzinfo=UTC)
    small = dt.datetime.min.replace(tzinfo=UTC)
    try:
        far = PC.days_between(utc(2026, 11, 25), big)
        check("year 9999 (a broken import) does not crash and reads far away", far is not None and far > 2_000_000)
    except Exception as e:
        check(f"year 9999 does not crash ({type(e).__name__})", False)
    try:
        far = PC.days_between(small, utc(2026, 11, 25))
        check("year 1 does not crash and reads far away", far is not None and far > 700_000)
    except Exception as e:
        check(f"year 1 does not crash ({type(e).__name__})", False)
    try:
        check("year 1 last visit → lapsed, no crash", CP.lapsed(small, utc(2026, 11, 25), 35))
        check("year 9999 last visit → not lapsed, no crash", not CP.lapsed(big, utc(2026, 11, 25), 35))
    except Exception as e:
        check(f"lapsed on extreme dates does not crash ({type(e).__name__})", False)

    print("\nclients_page.lapsed — the case seen on 2026-11-25")
    last_a = utc(2026, 10, 20, 10, 22, 24)          # 12:22:24 Paris, summer time
    check("11:30 Paris on 25 Nov → still actif (was inactif before the fix)",
          not CP.lapsed(last_a, paris(2026, 11, 25, 11, 30), 35))
    check("12:22:23 Paris → still actif", not CP.lapsed(last_a, paris(2026, 11, 25, 12, 22, 23), 35))
    check("12:22:24 Paris → inactif", CP.lapsed(last_a, paris(2026, 11, 25, 12, 22, 24), 35))

    print("\nlapsed — the March change (one hour missing)")
    march = paris(2027, 3, 20, 12, 0)
    check("25 Apr 11:59 Paris → still actif", not CP.lapsed(march, paris(2027, 4, 25, 11, 59), 35))
    check("25 Apr 12:00 Paris → inactif (was 13:00 before the fix)", CP.lapsed(march, paris(2027, 4, 25, 12, 0), 35))

    print("\nlapsed — the visit falls in the repeated hour (25 Oct 02:00–03:00)")
    for fold in (0, 1):
        v = paris(2026, 10, 25, 2, 30, fold=fold)
        check(f"02:30 (fold {fold}) → actif at 30 Nov 02:29", not CP.lapsed(v, paris(2026, 11, 30, 2, 29), 35))
        check(f"02:30 (fold {fold}) → inactif at 30 Nov 02:30", CP.lapsed(v, paris(2026, 11, 30, 2, 30), 35))

    print("\nlapsed — the deadline falls in the missing hour (28 Mar 2027 02:00–03:00)")
    v = paris(2027, 2, 20, 2, 30)                     # + 36 days = 28 Mar 02:30, which does not exist
    check("01:59 Paris → still actif", not CP.lapsed(v, paris(2027, 3, 28, 1, 59), 35))
    check("03:00 Paris (the first minute after the gap) → inactif", CP.lapsed(v, paris(2027, 3, 28, 3, 0), 35))

    print("\nlapsed — edges kept")
    now = paris(2026, 11, 25, 15, 0)
    check("35 days exactly → not yet", not CP.lapsed(now - dt.timedelta(days=35), now, 35))
    check("36 days (no clock change between) → lapsed", CP.lapsed(paris(2026, 10, 20, 15, 0), now, 35))
    check("rule of 0 days → inactif after one full day", CP.lapsed(paris(2026, 11, 24, 15, 0), now, 0))
    check("rule of 0 days → not inactif the same day", not CP.lapsed(paris(2026, 11, 25, 9, 0), now, 0))
    check("a future date → not lapsed", not CP.lapsed(now + dt.timedelta(days=2), now, 35))
    check("no date → lapsed", CP.lapsed(None, now, 35))

    print("\nRègles clients — Statut flips at the same instant")
    rules = R.defaults()
    next(r for r in rules if r["key"] == "actif")["conditions"][0]["value"] = 35
    next(r for r in rules if r["key"] == "bientot_perdu")["conditions"][0]["value"] = 36
    cust = {"id": "a", "visits": 3, "created_at": utc(2026, 9, 1), "last_visit_date": last_a}
    check("11:30 Paris → not « bientôt perdu »",
          R.status_key(R.primary(cust, paris(2026, 11, 25, 11, 30), rules)) != "bientot_perdu")
    check("11:30 Paris → « Client actif » rule still holds",
          R.matches(R.rule(rules, "actif"), cust, paris(2026, 11, 25, 11, 30)))
    check("12:22:24 Paris → « Client actif » no longer holds",
          not R.matches(R.rule(rules, "actif"), cust, paris(2026, 11, 25, 12, 22, 24)))
    check("12:22:24 Paris → « bientôt perdu »",
          R.status_key(R.primary(cust, paris(2026, 11, 25, 12, 22, 24), rules)) == "bientot_perdu")
    for at in (paris(2026, 11, 25, 11, 30), paris(2026, 11, 25, 12, 22, 24), paris(2026, 11, 25, 12, 22, 23)):
        check(f"actif rule and inactive chip never both true / both false at {at.astimezone(PARIS):%H:%M:%S}",
              R.matches(R.rule(rules, "actif"), cust, at) != CP.is_inactive(cust, at, rules))
    never = {"id": "n", "visits": 0, "created_at": utc(2026, 10, 20, 10, 22, 24)}
    check("never came: dormant/at-risk age read from sign-up on the Paris clock",
          R._days_since(never, paris(2026, 11, 25, 12, 22, 24)) == 36.0)

    print("\nSegmentation — « Pas venu depuis plus de N jours »")
    rule = {"field": "last_visit", "op": "gt", "value": 35}
    check("11:30 Paris → not in the segment", not SG._matches(cust, rule, paris(2026, 11, 25, 11, 30), None))
    check("12:22:24 Paris → in the segment", SG._matches(cust, rule, paris(2026, 11, 25, 12, 22, 24), None))
    rule_lt = {"field": "last_visit", "op": "lt", "value": 36}
    check("« moins de 36 jours » still true at 11:30 Paris", SG._matches(cust, rule_lt, paris(2026, 11, 25, 11, 30), None))
    joined = {"field": "joined", "op": "lt", "value": 36}
    jc = {"id": "j", "visits": 0, "created_at": last_a}
    check("« inscrit depuis moins de 36 jours » still true at 11:30 Paris",
          SG._matches(jc, joined, paris(2026, 11, 25, 11, 30), None))
    check("…and false at 12:22:24 Paris", not SG._matches(jc, joined, paris(2026, 11, 25, 12, 22, 24), None))

    # ----------------------------------------------------------- integration
    print("\nIntegration — the HTTP pages and the relance on one shop")
    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "T1", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.users.insert_one({"email": "o@t1.fr", "role": "business_owner", "tenant_id": "t1"})
    db.customer_status_config.delete_many({})
    R.init(db); CP.init(db)
    saved = R.defaults()
    next(r for r in saved if r["key"] == "actif")["conditions"][0]["value"] = 35
    db.customer_status_config.insert_one({"tenant_id": "t1", "rules": saved})
    base = {"tenant_id": "t1", "visits": 1, "created_at": utc(2026, 9, 1)}
    db.customers.insert_many([
        {**base, "id": "a", "name": "Client A", "barcode_id": "FT-A", "last_visit_date": last_a},
        {**base, "id": "old", "name": "Ancien", "barcode_id": "FT-OLD", "last_visit_date": utc(2026, 10, 1, 9, 0)},
        {**base, "id": "new", "name": "Récent", "barcode_id": "FT-NEW", "last_visit_date": utc(2026, 11, 20, 9, 0)},
    ])
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@t1.fr", "role": "business_owner",
                                                                 "tenant_id": "t1"})}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def at_time(when):
        CP._now = lambda: when
        SG._now = lambda: when

    def ids_in_list():
        r = http("GET", "/api/owner/clients/list?segment=inactive&per_page=50")
        return r.status_code, sorted(x["id"] for x in r.json().get("rows", []))

    def card():
        r = http("GET", "/api/owner/clients/overview")
        return next(c["value"] for c in r.json()["cards"] if c["key"] == "inactive")

    def seg_count():
        r = http("POST", "/api/owner/segmentation/preview",
                 json={"rules": [{"field": "last_visit", "op": "gt", "value": 35}]})
        return r.json().get("count")

    row = {"id": "r", "tenant_id": "t1", "scenario": "inactive", "trigger": {"days": 35, "repeat": "once"}}

    at_time(paris(2026, 11, 25, 11, 30))
    code, ids = ids_in_list()
    check("11:30 Paris — list answers 200", code == 200)
    check(f"11:30 Paris — client A not in Clients inactifs {ids}", ids == ["old"])
    check("11:30 Paris — the chip says 1", card() == 1)
    check("11:30 Paris — Segmentation says 1", seg_count() == 1)
    due = [c["id"] for c in AU._inactive_due("t1", row, paris(2026, 11, 25, 11, 30))]
    check("11:30 Paris — relance not due for client A", "a" not in due)

    at_time(paris(2026, 11, 25, 12, 22, 24))
    code, ids = ids_in_list()
    check("12:22:24 Paris — client A in Clients inactifs", ids == ["a", "old"])
    check("12:22:24 Paris — the chip says 2", card() == 2)
    check("12:22:24 Paris — Segmentation says 2", seg_count() == 2)
    due = [c["id"] for c in AU._inactive_due("t1", row, paris(2026, 11, 25, 12, 22, 24))]
    check("12:22:24 Paris — relance due for client A", "a" in due)
    check("a recent client is never inactive", "new" not in ids and "new" not in due)

    print("\nIntegration — another shop sees none of it")
    db.tenants.insert_one({"id": "t2", "slug": "t2", "name": "T2", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.users.insert_one({"email": "o@t2.fr", "role": "business_owner", "tenant_id": "t2"})
    H2 = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@t2.fr", "role": "business_owner",
                                                                  "tenant_id": "t2"})}

    async def other():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
            return await ac.get("/api/owner/clients/list?segment=inactive&per_page=50", headers=H2)
    r = asyncio.get_event_loop().run_until_complete(other())
    check("shop t2 gets an empty inactive list", r.status_code == 200 and r.json().get("rows") == [])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
