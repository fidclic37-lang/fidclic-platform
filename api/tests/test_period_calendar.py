"""
A calendar period — a whole month, one date, a from–to range, « Ce mois-ci »
(user, 2026-11-03: « November select krun toh November ka hi data dikhna
chahiye », 1 → 28/29/30/31, « particular date bhi », on the 1st the new month).

  • P.span(date_from, date_to) cuts Paris days, start of the first to the end
    of the last — today ends now, a future day is refused, two years back at most;
  • the « période précédente » is the same slice one month earlier (a month →
    the month before, 1–15 → 1–15, a day → that date last month), clamped to
    the month's length (31 mars → 28 février);
  • one day is drawn hour by hour, whatever day it is;
  • `days` alone works exactly as before;
  • Analyses (every tab), the export, the Tableau de bord and its campaign
    cards read the same calendar period through ?date_from=&date_to=.

Run: cd api && /usr/local/bin/python3 tests/test_period_calendar.py
"""
import asyncio
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-period-calendar")
os.environ.setdefault("DISABLE_SEED", "1")
PARIS = ZoneInfo("Europe/Paris")
UTC = dt.timezone.utc
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def paris(y, m, d, h=0, mi=0, s=0, us=0):
    return dt.datetime(y, m, d, h, mi, s, us, tzinfo=PARIS).astimezone(UTC)


def refused(f):
    from fastapi import HTTPException
    try:
        f()
    except (HTTPException, ValueError) as e:
        return getattr(e, "status_code", 422) == 422
    return False


def unit():
    from features import period as P
    now = paris(2026, 11, 3, 15, 20)

    print("\nA whole month")
    s = P.span(date_from="2026-10-01", date_to="2026-10-31", now=now)
    check("October starts at midnight on the 1st, Paris (22:00 UTC the 30th, summer time)",
          s.start == dt.datetime(2026, 9, 30, 22, 0, tzinfo=UTC))
    check("…and ends at the last instant of the 31st, Paris (winter time since the 25th)",
          s.end == dt.datetime(2026, 10, 31, 22, 59, 59, 999999, tzinfo=UTC))
    check("31 days", s.days == 31)
    check("not drawn hour by hour", not s.hourly)
    check("compared with all of September (1 → 30)",
          s.prev_start == paris(2026, 9, 1) and s.prev_end == paris(2026, 9, 30, 23, 59, 59, 999999))
    s = P.span(date_from="2026-03-01", date_to="2026-03-31", now=now)
    check("March 2026: 31 days, compared with February 1 → 28",
          s.days == 31 and s.prev_start == paris(2026, 2, 1) and s.prev_end == paris(2026, 2, 28, 23, 59, 59, 999999))
    later = paris(2028, 4, 10, 12)
    s = P.span(date_from="2028-02-01", date_to="2028-02-29", now=later)
    check("February 2028 (leap year): 29 days", s.days == 29)
    s = P.span(date_from="2028-03-01", date_to="2028-03-31", now=later)
    check("March 2028 compared with February 1 → 29 (leap)",
          s.prev_end == paris(2028, 2, 29, 23, 59, 59, 999999))
    s = P.span(date_from="2027-02-01", date_to="2027-02-28", now=later)
    check("February 2027: 28 days, compared with January 1 → 31",
          s.days == 28 and s.prev_start == paris(2027, 1, 1) and s.prev_end == paris(2027, 1, 31, 23, 59, 59, 999999))
    s = P.span(date_from="2026-04-01", date_to="2026-04-30", now=now)
    check("April: 30 days, compared with March 1 → 31 (a whole month is compared with a whole month)",
          s.days == 30 and s.prev_end == paris(2026, 3, 31, 23, 59, 59, 999999))
    s = P.span(date_from="2026-01-01", date_to="2026-01-31", now=now)
    check("January compared with December of the year before",
          s.prev_start == paris(2025, 12, 1) and s.prev_end == paris(2025, 12, 31, 23, 59, 59, 999999))

    print("\n« Ce mois-ci » — the 1st until now")
    s = P.span(date_from="2026-11-01", date_to="2026-11-03", now=now)
    check("ends now, not at midnight tonight", s.end == now)
    check("3 days", s.days == 3)
    check("compared with October 1 → October 3 at the same hour (15:20 Paris)",
          s.prev_start == paris(2026, 10, 1) and s.prev_end == paris(2026, 10, 3, 15, 20))
    first = paris(2026, 11, 1, 8, 5)
    s = P.span(date_from="2026-11-01", date_to="2026-11-01", now=first)
    check("on the 1st at 08:05: only today, drawn hour by hour",
          s.start == paris(2026, 11, 1) and s.end == first and s.days == 1 and s.hourly)
    check("…its hours 0h → 8h", [x["label"] for x in P.slots(s.start, s.end, s)] == [f"{h}h" for h in range(9)])

    print("\nOne date")
    s = P.span(date_from="2026-10-15", date_to="2026-10-15", now=now)
    check("October 15: midnight → 23:59:59.999999, Paris",
          s.start == paris(2026, 10, 15) and s.end == paris(2026, 10, 15, 23, 59, 59, 999999))
    check("drawn hour by hour, all 24 hours", s.hourly and len(P.slots(s.start, s.end, s)) == 24)
    check("compared with September 15", s.prev_start == paris(2026, 9, 15)
          and s.prev_end == paris(2026, 9, 15, 23, 59, 59, 999999))
    s = P.span(date_from="2026-10-25", date_to="2026-10-25", now=now)
    check("the day the clocks go back (25 h long) is still one day of 24 hour rows",
          s.days == 1 and len(P.slots(s.start, s.end, s)) == 24 and (s.end - s.start) > dt.timedelta(hours=24))
    s = P.span(date_from="2026-03-31", date_to="2026-03-31", now=now)
    check("March 31 compared with February 28 (no February 31)", s.prev_start == paris(2026, 2, 28))

    print("\nA from–to range")
    s = P.span(date_from="2026-10-20", date_to="2026-11-02", now=now)
    check("20 Oct → 2 Nov: 14 days, to the end of the 2nd",
          s.days == 14 and s.end == paris(2026, 11, 2, 23, 59, 59, 999999))
    check("compared with 20 Sept → 2 Oct", s.prev_start == paris(2026, 9, 20)
          and s.prev_end == paris(2026, 10, 2, 23, 59, 59, 999999))
    s = P.span(date_from="2026-10-01", date_to="2026-10-15", now=now)
    check("1 → 15 October compared with 1 → 15 September",
          s.prev_start == paris(2026, 9, 1) and s.prev_end == paris(2026, 9, 15, 23, 59, 59, 999999))

    print("\nWhat is refused or trimmed")
    s = P.span(date_from="2026-11-01", date_to="2026-11-30", now=now)
    check("November asked on the 3rd: until now (the rest has not happened)", s.end == now and s.days == 3)
    check("…compared with October 1 → 3 at the same hour", s.prev_end == paris(2026, 10, 3, 15, 20))
    check("a day in the future is refused", refused(lambda: P.span(date_from="2026-11-04", date_to="2026-11-04", now=now)))
    check("from after to is refused", refused(lambda: P.span(date_from="2026-10-10", date_to="2026-10-01", now=now)))
    check("a date that is not one is refused", refused(lambda: P.span(date_from="2026-02-30", date_to="2026-03-01", now=now)))
    check("text is refused", refused(lambda: P.span(date_from="hier", date_to="2026-03-01", now=now)))
    check("a from without a to is refused", refused(lambda: P.span(date_from="2026-10-01", now=now)))
    check("further back than two years is refused",
          refused(lambda: P.span(date_from="2024-10-01", date_to="2024-10-31", now=now)))
    check("two years back exactly is accepted", P.span(date_from="2024-11-04", date_to="2024-11-04", now=now).days == 1)
    check("a day before that is refused", refused(lambda: P.span(date_from="2024-11-03", date_to="2024-12-01", now=now)))
    check("two years back to today: 730 days", P.span(date_from="2024-11-04", date_to="2026-11-03", now=now).days == 730)

    print("\n`days` alone — as before")
    s = P.span(days=30, now=now)
    a, b = P.window(30, now)
    check("same window as before", (s.start, s.end) == (a, b) and s.days == 30)
    check("the period before: the same length just before",
          s.prev_end == a - dt.timedelta(microseconds=1) and s.prev_start == s.prev_end - (b - a))
    s = P.span(days=1, now=now)
    check("« Aujourd'hui » still hour by hour", s.hourly and s.days == 1)
    check("nothing given = 30 days", P.span(now=now).days == 30)


def http():
    import server
    import auth
    import httpx
    db = server.db
    now = dt.datetime.now(UTC)
    loc = now.astimezone(PARIS)
    # two months ago, whole — always in the past, whatever day the suite runs
    y, m = (loc.year, loc.month - 2) if loc.month > 2 else (loc.year - 1, loc.month + 10)
    first = dt.date(y, m, 1)
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "R", "plan": "vip", "subscription_status": "active",
                           "branches": [{"id": "main", "name": "LIB", "is_main": True}, {"id": "mon", "name": "MON"}]})
    db.tenants.insert_one({"id": "t2", "slug": "t2", "name": "Other", "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "A", "branch_id": "main",
                             "created_at": paris(py, pm, 3), "deleted_at": None, "total_amount_paid": 0})
    db.customers.insert_one({"id": "c2", "tenant_id": "t1", "name": "B", "branch_id": "main",
                             "created_at": paris(y, m, 10, 12), "deleted_at": None, "total_amount_paid": 0})
    db.customers.insert_one({"id": "z1", "tenant_id": "t2", "name": "Z", "created_at": paris(y, m, 10),
                             "deleted_at": None, "total_amount_paid": 0})

    def visit(i, at, amount, cid="c1", tid="t1", branch="main"):
        db.visits.insert_one({"id": f"v{i}", "tenant_id": tid, "customer_id": cid, "branch_id": branch,
                              "amount_paid": amount, "visit_time": at})
    end_prev_month = dt.datetime.combine(first - dt.timedelta(days=1), dt.time(23, 30), PARIS).astimezone(UTC)
    visit(1, end_prev_month, 100)                                   # last evening of the month before
    visit(2, paris(y, m, 1, 0, 30), 10)                             # 00:30 on the 1st (22:30 UTC the day before)
    visit(3, paris(y, m, 10, 14), 20)
    visit(4, paris(y, m, 10, 18), 5, cid="c2")
    visit(5, dt.datetime.combine(last, dt.time(23, 30), PARIS).astimezone(UTC), 30)   # 23:30 on the last day
    nxt = last + dt.timedelta(days=1)
    visit(6, paris(nxt.year, nxt.month, 1, 0, 10), 1000)            # 00:10 on the 1st of the next month
    visit(7, paris(py, pm, 10, 9), 40)                              # the month before, for the comparison
    visit(8, paris(y, m, 10, 15), 777, cid="z1", tid="t2")          # another shop
    visit(9, paris(y, m, 12, 11), 3, branch="mon")                  # another establishment

    def get(path, **headers):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(path, headers={**H, **headers})
        return asyncio.get_event_loop().run_until_complete(run())

    month = f"date_from={first.isoformat()}&date_to={last.isoformat()}"
    print(f"\nAnalyses › Vue for {first:%B %Y} (?{month})")
    r = get(f"/api/owner/analyses?tab=vue&{month}")
    check("200", r.status_code == 200)
    d = r.json()
    strip = {x["key"]: x for x in d["data"]["strip"]}
    check("visits of the month only, the 1st at 00:30 and the last day at 23:30 included (5)",
          strip["visits"]["value"] == 5)
    check("revenue of the month only: 10 + 20 + 5 + 30 + 3 = 68 € (not the 100 € before, not the 1 000 € after, not the other shop)",
          strip["revenue"]["value"] == 68)
    check("the answer names its period: the month's first and last day",
          d.get("date_from") == first.isoformat() and d.get("date_to") == last.isoformat() and d.get("days") == last.day)
    r2 = get(f"/api/owner/analyses?tab=vue&{month}", **{"X-FidClic-Store": "main"})
    s2 = {x["key"]: x for x in r2.json()["data"]["strip"]}
    check("one establishment: its own 65 €", s2["revenue"]["value"] == 65)
    check("compared with the whole month before (100 € its last evening + 40 € = 140 € → 68 €: −51 %)",
          strip["revenue"].get("delta_pct") == -51)

    day = paris(y, m, 10).astimezone(PARIS).date().isoformat()
    print(f"\nOne date ({day})")
    d = get(f"/api/owner/analyses?tab=vue&date_from={day}&date_to={day}").json()
    strip = {x["key"]: x for x in d["data"]["strip"]}
    check("that day's 2 visits (25 €)", strip["visits"]["value"] == 2 and strip["revenue"]["value"] == 25)

    for tab in ("campagnes", "fidelite", "avis", "produits", "acquisition"):
        r = get(f"/api/owner/analyses?tab={tab}&{month}")
        check(f"tab « {tab} » reads the month too", r.status_code == 200 and r.json().get("date_from") == first.isoformat())
    r = get(f"/api/owner/analyses/export?{month}")
    check("the export reads the month", r.status_code == 200)

    print("\nTableau de bord")
    r = get(f"/api/owner/home/overview?{month}")
    check("200", r.status_code == 200)
    d = r.json()
    check("revenue of the month (68 €), compared with the month before (140 €: −51 %)",
          round(d["revenue_total"]) == 68 and d["revenue_delta"] == -51)
    series = d["revenue_series"]
    check(f"one point per day of the month ({last.day})", len(series) == last.day)
    check("from / to are the month's first instant and last instant",
          d["from"] == paris(y, m, 1).isoformat() and d["days"] == last.day)
    r = get(f"/api/owner/home/campaigns?{month}")
    check("campaign cards read the month", r.status_code == 200)

    print("\nWhat the API refuses")
    check("a future date: 422", get(f"/api/owner/analyses?tab=vue&date_from=2999-01-01&date_to=2999-01-02").status_code == 422)
    check("from after to: 422", get(f"/api/owner/home/overview?date_from={last}&date_to={first}").status_code == 422)
    check("garbage: 422", get("/api/owner/analyses?tab=vue&date_from=x&date_to=y").status_code == 422)
    check("?days=30 alone still answers as before",
          get("/api/owner/analyses?tab=vue&days=30").json().get("days") == 30)


if __name__ == "__main__":
    unit()
    http()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
