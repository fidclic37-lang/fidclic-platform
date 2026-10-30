"""
La prévision du Copilote sur le registre, en jours de Paris (user,
2026-10-30, queue item 5):

- days are Paris days, read from the daily register (features/visit_days),
  like Analyses — a visit at 00:30 in Paris counts for that day, not the one
  before (UTC);
- closed days — the Horaires settings (weekly day off, holidays ticked,
  annual closures) and what the owner told FidClic IA (« je ferme le
  mardi ») — show « Fermé », get no affluence card, and past closed days do
  not drag their weekday's average down as zeros;
- jours fériés when the shop is open: learned from the shop's own past
  fériés AND from shops of the same activité / secteur (each shop weighs
  the same, from 3 shops, no shop id kept), the shop's own pulled toward
  the network's.

Run: cd api && /usr/local/bin/python3 tests/test_forecast_register.py
"""
import contextlib
import datetime as dt
import io
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-forecast-register")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ.pop("PREDICTHQ_TOKEN", None)
passed = failed = 0
UTC = dt.timezone.utc
PARIS = ZoneInfo("Europe/Paris")


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", str(show)[:700])
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    from features import copilot as K
    from features import holiday_learning as HL
    from features import insights_page as E

    db = server.db
    now = dt.datetime(2026, 10, 30, 10, tzinfo=UTC)          # a Friday; Toussaint is Sunday 1 November

    def shop_of(tid, at=now):
        s = E.Shop(tid, at)
        return s

    def paris(d, h=12, m=0):
        return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=PARIS).astimezone(UTC)

    def visit(tid, when, n=1, i=[0]):
        for _ in range(n):
            i[0] += 1
            db.visits.insert_one({"id": f"v{i[0]}", "tenant_id": tid, "customer_id": f"{tid}-c{i[0] % 7}",
                                  "amount_paid": 10.0, "visit_time": when})

    def tenant(tid, **kw):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": tid, "sector": "salon", "activity_key": "barbier",
                               "plan": "vip", "is_active": True, "subscription_status": "active", **kw})
        db.users.insert_one({"email": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid, "active": True})
        for k in range(7):
            db.customers.insert_one({"id": f"{tid}-c{k}", "tenant_id": tid, "name": f"C{k}", "deleted_at": None,
                                     "visits": 5, "created_at": now - dt.timedelta(days=400)})

    def history(tid, per_weekday, weeks=8, at=now, skip=()):
        """`per_weekday[w]` visits each past day of weekday w, at noon Paris."""
        today = at.astimezone(PARIS).date()
        for i in range(1, weeks * 7 + 1):
            d = today - dt.timedelta(days=i)
            if d in skip:
                continue
            n = per_weekday.get(d.weekday(), 0)
            if n:
                visit(tid, paris(d), n)

    # ---------------------------------------------------------------- Paris days
    print("Les jours de Paris")
    tenant("paris")
    history("paris", {0: 4, 1: 4, 2: 4, 3: 4, 4: 4, 5: 4})
    today = now.astimezone(PARIS).date()
    for i in range(1, 57):                                   # 3 more each Monday, at 00:30 in Paris = Sunday 23:30 UTC
        d = today - dt.timedelta(days=i)
        if d.weekday() == 0:
            visit("paris", paris(d, 0, 30), 3)
    fc = K.forecast_week(shop_of("paris"))
    by = {d["weekday"]: d for d in fc["days"]}
    check("a visit at 00:30 in Paris counts for its Paris day (Monday 7, not 4)", by[0]["base"] == 7.0, by.get(0))
    check("…and not for the day before in UTC (Sunday stays without history)", 6 not in by or not by[6].get("base"), by.get(6))
    late = dt.datetime(2026, 10, 30, 23, 30, tzinfo=UTC)    # 00:30 on Saturday 31 in Paris
    fc = K.forecast_week(shop_of("paris", late))
    check("« today » is today in Paris (late Friday UTC → the forecast starts Saturday)", fc["days"][0]["date"] == "2026-10-31", fc["days"][:1])

    s1, s2 = shop_of("paris"), shop_of("paris")
    K.forecast_week(s1)                                       # the register is built once
    reads = []
    real_find = db.visits.find
    db.visits.find = lambda *a, **k: (reads.append(1), real_find(*a, **k))[1]
    K.forecast_week(s2)
    db.visits.find = real_find
    check("past days come from the register: a second forecast reads only today's visits", len(reads) <= 4, len(reads))

    # ---------------------------------------------------------------- closed days
    print("\nLes jours fermés")
    weekly = [{"day": d, "closed": d == "monday"} for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")]
    tenant("ferme", weekly_schedule=weekly, holiday_closures={"2026-11-04": True},
           annual_closures=[{"start": "2026-11-05", "end": "2026-11-05"}])
    wed_closed = today - dt.timedelta(days=(today.weekday() - 2) % 7 or 7)   # last Wednesday: closed that day
    db.tenants.update_one({"id": "ferme"}, {"$push": {"annual_closures": {"start": wed_closed.isoformat(), "end": wed_closed.isoformat()}}})
    history("ferme", {0: 9, 1: 5, 2: 10, 3: 5, 4: 5, 5: 30, 6: 5}, skip={wed_closed})
    db.copilot_memory.insert_one({"id": "f1", "tenant_id": "ferme", "by": "o@ferme.fr", "text": "Je ferme le samedi",
                                  "source": "vous", "at": now, "updated_at": now})
    fc = K.forecast_week(shop_of("ferme"))
    by = {d["date"]: d for d in fc["days"]}
    mon = by["2026-11-02"]
    check("Monday closed in Horaires: « Fermé », nothing expected", mon.get("closed") is True and mon["predicted"] == 0
          and mon.get("closed_reason") == "Fermé le lundi (Horaires)", mon)
    check("a holiday closure ticked in Horaires", by["2026-11-04"].get("closed") is True
          and "Horaires" in by["2026-11-04"]["closed_reason"], by["2026-11-04"])
    check("an annual closure", by["2026-11-05"].get("closed") is True and "Congés" in by["2026-11-05"]["closed_reason"], by["2026-11-05"])
    sat = by["2026-10-31"]
    check("a day the owner told FidClic IA is closed (« Je ferme le samedi »)", sat.get("closed") is True
          and sat["closed_reason"] == "Selon ce que vous avez dit : « Je ferme le samedi »", sat)
    bases = K._weekday_bases(shop_of("ferme"))
    check("a closed day past is left out of its weekday's average (Wednesday 10, not 8.75)", bases.get(2) == 10.0, bases)
    check("…and a weekday closed now has no average at all (Monday, Saturday)", 0 not in bases and 5 not in bases, bases)
    aff = K._affluence(shop_of("ferme"), fc)
    check("Saturday's 30 visits a week do not make « Forte affluence » on a closed Saturday",
          not aff or aff["detail"]["date"] != "2026-10-31", aff)
    check("the open days' mean leaves closed days out", fc["mean"] is not None and fc["mean"] < 10, fc["mean"])

    # ---------------------------------------------------------------- jours fériés
    print("\nLes jours fériés : le commerce et ses pareils")

    def holidays_history(tid, ratio_by_year, per_weekday, network=False):
        """Two years of plain weeks around past Toussaint, and the Toussaint days themselves."""
        for year, ratio in ratio_by_year.items():
            h = dt.date(year, 11, 1)
            for i in range(1, 57):
                d = h - dt.timedelta(days=i)
                n = per_weekday.get(d.weekday(), 0)
                if n:
                    visit(tid, paris(d), n)
            if ratio is not None:
                visit(tid, paris(h), round(per_weekday.get(h.weekday(), 0) * ratio))

    tenant("own")
    history("own", {w: 6 for w in range(7)})
    holidays_history("own", {2025: 2.0, 2024: 2.0}, {w: 6 for w in range(7)})
    fc = K.forecast_week(shop_of("own"))
    tous = next(d for d in fc["days"] if d["date"] == "2026-11-01")
    check("Toussaint is named", (tous.get("holiday") or {}).get("name") == "Toussaint", tous)
    check("its own two past Toussaint (×2) → ×2 expected", tous.get("holiday_factor") == 2.0 and tous["predicted"] == 12.0, tous)
    check("…and it says why", tous.get("holiday_basis") == "Vos 2 Toussaint passées", tous.get("holiday_basis"))

    tenant("one")
    history("one", {w: 6 for w in range(7)})
    holidays_history("one", {2025: 3.0}, {w: 6 for w in range(7)})
    fc = K.forecast_week(shop_of("one"))
    tous = next(d for d in fc["days"] if d["date"] == "2026-11-01")
    check("one past Toussaint and no network: named, number unchanged", tous.get("holiday", {}).get("name") == "Toussaint"
          and tous.get("holiday_factor") is None and tous["predicted"] == 6.0, tous)

    for i, r in enumerate((1.4, 1.5, 1.6)):
        tenant(f"net{i}")
        holidays_history(f"net{i}", {2025: r, 2024: r}, {w: 10 for w in range(7)})
    tenant("netclosed")                                        # closed on Toussaint: no visits that day — not counted
    holidays_history("netclosed", {2025: None, 2024: None}, {w: 10 for w in range(7)})
    tenant("cafe1", sector="cafe", activity_key="cafe")
    holidays_history("cafe1", {2025: 9.0, 2024: 9.0}, {w: 10 for w in range(7)})
    out = HL.learn(now)
    doc = db.platform_settings.find_one({"key": HL.NET_KEY}) or {}
    toussaint = (doc.get("by") or {}).get("a:barbier|toussaint") or {}
    # the barbers with a Toussaint: own ×2, one ×3, net ×1.4 / 1.5 / 1.6 → the middle one is ×1.6
    check("the network: barbers' Toussaint, each shop one vote, the middle one (×1.6)", toussaint.get("ratio") == 1.6, toussaint)
    check("…a shop closed that day is not a vote (5 shops, not 6)", toussaint.get("shops") == 5, toussaint)
    check("…no shop id is kept", not any(t in str(doc) for t in ("net0", "net1", "own", "cafe1")))
    check("…a café's Toussaint never counts for barbers", toussaint.get("ratio") != 9.0)

    tenant("newbie")
    history("newbie", {w: 8 for w in range(7)})
    fc = K.forecast_week(shop_of("newbie"))
    tous = next(d for d in fc["days"] if d["date"] == "2026-11-01")
    check("a shop with no past Toussaint: the barbers' network (×1.6)", tous.get("holiday_factor") == 1.6
          and tous["predicted"] == 12.8, tous)
    check("…saying so", "barbiers" in (tous.get("holiday_basis") or "") and "comme vous" in tous["holiday_basis"], tous.get("holiday_basis"))
    fc = K.forecast_week(shop_of("one"))
    tous = next(d for d in fc["days"] if d["date"] == "2026-11-01")
    check("its one own Toussaint (×3) pulled toward the network (×1.6): (3 + 2×1.6) / 3 = ×2.07", tous.get("holiday_factor") == 2.07, tous)
    check("…both said", "Votre Toussaint passée" in (tous.get("holiday_basis") or "") and "barbiers" in tous["holiday_basis"], tous.get("holiday_basis"))
    check("learning runs once a day from the tick", HL.learn_due(now) is None and HL.learn_due(now + dt.timedelta(hours=25)) is not None)
    src = open(os.path.join(os.path.dirname(__file__), "..", "server.py")).read()
    check("the tick runs it", "holiday_learning" in src)

    print("\nLa charge (audit de #411)")
    doc = db.holiday_measures.find_one({"tenant_id": "own", "scope": "all"})
    check("a shop's holiday measures are stored (not rebuilt at each page)", doc and doc.get("ratios", {}).get("toussaint") == [2.0, 2.0], doc)
    built = []
    own_shop = shop_of("own")
    from features import visit_days as VD
    real_many = VD.span_many
    VD.span_many = lambda tid, scope, ranges, *a, **k: (built.append(max((b - a2).days for a2, b in ranges)), real_many(tid, scope, ranges, *a, **k))[1]
    counted = []
    real_count = db.visits.count_documents
    db.visits.count_documents = lambda *a, **k: (counted.append(1), real_count(*a, **k))[1]
    HL._cache.clear()
    K.forecast_week(own_shop)
    VD.span_many = real_many
    db.visits.count_documents = real_count
    check("a page never reads two years of register (60 days at most: the weekday averages)", max(built or [0]) <= 60, built)
    check("…and with its measures stored, counts no holiday at all", not counted, len(counted))
    HL.PASS_SECONDS, real_budget = 0.0, HL.PASS_SECONDS
    db.holiday_measures.delete_many({})
    out = HL.learn(now)
    HL.PASS_SECONDS = real_budget
    check("the network pass keeps to its time budget: what it did not measure waits for the next pass",
          out.get("measured", 0) <= 1, out)
    while db.holiday_measures.count_documents({"scope": "all"}) < db.tenants.count_documents({}):
        if not HL.learn(now).get("measured"):
            break
    check("…then every shop is measured", db.holiday_measures.count_documents({"scope": "all"}) == db.tenants.count_documents({}))
    db.holiday_measures.delete_one({"tenant_id": "own"})
    check("a shop still unmeasured: the next tick goes on at once (not a day later)", HL.learn_due(now) is not None)
    check("…all measured: once a day again", HL.learn_due(now) is None)

    tenant("busy")
    history("busy", {w: 10 for w in range(7)})
    holidays_history("busy", {2025: 3.0, 2024: 3.0}, {w: 10 for w in range(7)})
    aff = K._affluence(shop_of("busy"), K.forecast_week(shop_of("busy")))
    check("a busy holiday becomes the affluence card, and says why", aff and aff["detail"]["date"] == "2026-11-01"
          and "Toussaint" in aff["body"], aff)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
