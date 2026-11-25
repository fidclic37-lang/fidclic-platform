"""
GET /api/card/{bc}: the offers and défis reads are bounded and indexed, and
the customer sees exactly what they saw before (2026-11-25, after the load
review of PR #519: one card open moved ~20 MB of campaign documents, every
campaign's full recipient_ids list included, and the défis lookup read every
défi the client was ever in, plus one visits read per running défi).

Checked through the real HTTP endpoint on the mongomock server:

  • the same offers in the same order, the same running défis and the same
    won rewards as the previous code (kept below as `legacy_*`, the
    reference): live / ended / not-for-this-customer / cancelled /
    scheduled campaigns, a paused client, a client past the 60-campaign
    window, a won défi, a défi on its last day;
  • every campaigns read of a card open names its fields (never
    recipient_ids) and is bounded: a limit, or the défi end date;
  • the défi read never returns a défi that is over;
  • the défis cost one defi_rewards read and at most one visits read,
    whatever the number of running défis;
  • unit: first_live_day across midnight / DST, progress_many == progress.

Run: cd api && python3 tests/test_card_reads_bounded.py
"""
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-reads-bounded")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


# ---------------------------------------------------------------------------
# a recorder of every find() (collection, filter, projection, limit)
# ---------------------------------------------------------------------------
CALLS = []
_orig_find = mongomock.collection.Collection.find
_orig_limit = mongomock.collection.Cursor.limit


def _find(self, filter=None, projection=None, *a, **kw):
    cur = _orig_find(self, filter, projection, *a, **kw)
    rec = {"coll": self.name, "filter": filter or {}, "projection": projection if projection is not None
           else kw.get("projection"), "limit": None}
    CALLS.append(rec)
    cur._rec = rec
    return cur


def _limit(self, n):
    rec = getattr(self, "_rec", None)
    if rec is not None:
        rec["limit"] = n
    return _orig_limit(self, n)


mongomock.collection.Collection.find = _find
mongomock.collection.Cursor.limit = _limit


# ---------------------------------------------------------------------------
# the reference: the card's offers and défis exactly as the code before
# this change computed them (server.py _derive_offers_for_tenant, defis.card_view)
# ---------------------------------------------------------------------------
def legacy_offers(server, tenant_id, customer_id):
    from features import campaign_kinds as K
    db = server.db
    now_utc = datetime.now(timezone.utc)
    out = []
    tpl = db.card_templates.find_one({"tenant_id": tenant_id})
    if tpl and tpl.get("active_offer_active") and tpl.get("active_offer_title"):
        out.append("offer-main")
    cutoff = now_utc - timedelta(days=365)
    q = {"tenant_id": tenant_id, "status": "sent", "sent_at": {"$gte": cutoff}, "recipient_ids": customer_id}
    camps = list(db.campaigns.find(q).sort("sent_at", -1).limit(60))
    camps = [c for c in camps if c.get("kind") != "defi" and K.is_live(c, now_utc)][:10]
    return out + [c.get("id") for c in camps]


def legacy_defis(server, cust):
    from features import campaign_kinds as K
    from features import defis as D
    db = server.db
    at = datetime.now(timezone.utc)
    won_ids = {r["campaign_id"] for r in db.defi_rewards.find({"customer_id": cust["id"]}, {"_id": 0, "campaign_id": 1})}
    running = []
    for c in db.campaigns.find({"tenant_id": cust["tenant_id"], "kind": "defi", "status": "sent",
                                "recipient_ids": cust["id"]}, {"_id": 0}):
        sent = K.aware(c.get("sent_at"))
        _, until = K.window(c)
        if not (sent and until and sent <= at <= until) or c["id"] in won_ids:
            continue
        d = c.get("defi") or {}
        days_left = max(0, (until.astimezone(K.PARIS).date() - at.astimezone(K.PARIS).date()).days + 1)
        running.append({"id": c["id"], "title": c.get("name") or "Défi", "message": c.get("content") or "",
                        "target": int(d.get("target") or 0), "progress": D.progress(c, cust["id"], at),
                        "count_mode": d.get("count_mode"), "reward": d.get("reward"),
                        "end_date": d.get("end_date"), "days_left": days_left,
                        "image_url": c.get("image_url")})
    running.sort(key=lambda x: x.get("end_date") or "9999")
    return {"running": running, "won": D.pending_rewards(cust["id"], at)}


def main():
    import server
    import httpx
    from features import campaign_kinds as K
    from features import defis as D
    from services import card_owner as CO

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = datetime.now(timezone.utc).replace(microsecond=0)
    ago = lambda **kw: now - timedelta(**kw)   # noqa: E731
    today = now.astimezone(K.PARIS).date()
    day = lambda n: (today + timedelta(days=n)).isoformat()   # noqa: E731

    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL LAB", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    db["card_templates"]._real.insert_one({"tenant_id": "t1", "store_id": None, "programme": "stamps",
                                           "reward_threshold_stamps": 10, "active_offer_active": True,
                                           "active_offer_title": "Offre maison"})
    for cid, extra in (("c1", {}), ("c2", {}), ("c3", {"paused_at": ago(days=2)}), ("c4", {}), ("c5", {})):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "barcode_id": f"FT-{cid.upper()}00", "name": f"Client {cid}",
                                 "visits": 4, "points": 0, "created_at": ago(days=300), **extra})
    ME = ["c1", "c3", "c4"]
    big = [f"x{i:05d}" for i in range(3000)]          # a shop-wide send: a long recipients list

    def camp(cid, kind, sent, rec=None, status="sent", **kw):
        db.campaigns.insert_one({"id": cid, "tenant_id": "t1", "name": f"Campagne {cid}", "content": f"Texte {cid}",
                                 "kind": kind, "status": status, "sent_at": sent,
                                 "recipient_ids": (rec if rec is not None else ME) + big, **kw})

    camp("o_live", "offre", ago(days=2), offer={"start_date": day(-2), "end_date": day(10), "all_day": True},
         image_url="/api/media/" + "a" * 32, link_url="https://example.fr/menu")
    camp("o_ended", "offre", ago(days=20), offer={"start_date": day(-20), "end_date": day(-1), "all_day": True})
    camp("o_long", "offre", ago(days=200), offer={"start_date": day(-200), "end_date": day(30), "all_day": True})
    camp("o_soon", "configurer", ago(hours=5), offer={"start_date": day(2), "end_date": day(9), "all_day": False,
                                                      "time_from": "17:00", "time_to": "19:00",
                                                      "discount_type": "percent", "discount_value": 20})
    camp("n_live", "nouveaute", ago(days=3))
    camp("n_old", "nouveaute", ago(days=9))
    camp("n_vis", "nouveaute", ago(days=15), visible_until=day(5))
    camp("legacy", None, ago(hours=20))
    camp("ev_live", "evenement", ago(hours=30), event={"date": day(3), "time": "20:00", "place": "Salle"})
    camp("ev_past", "evenement", ago(days=6), event={"date": day(-2)})
    camp("o_other", "offre", ago(days=1), rec=["c2"], offer={"start_date": day(-1), "end_date": day(5), "all_day": True})
    camp("o_cancel", "offre", ago(days=1), status="cancelled", offer={"start_date": day(-1), "end_date": day(5)})
    camp("o_sched", "offre", None, status="scheduled", offer={"start_date": day(1), "end_date": day(5)})
    camp("o_year", "offre", ago(days=380), offer={"start_date": day(-380), "end_date": day(30), "all_day": True})

    defi = lambda end, mode="per_day", target=3: {"target": target, "end_date": end, "count_mode": mode,  # noqa: E731
                                                  "reward": "Dessert", "reward_valid_days": 30}
    camp("d_run1", "defi", ago(days=3), defi=defi(day(5)))
    camp("d_run2", "defi", ago(days=1), defi=defi(day(20), "per_scan", 5))
    camp("d_today", "defi", ago(days=4), defi=defi(day(0)))
    camp("d_ended", "defi", ago(days=30), defi=defi(day(-1)))
    camp("d_won", "defi", ago(days=2), defi=defi(day(8)))
    camp("d_given", "defi", ago(days=6), defi=defi(day(12)))     # won AND handed over, still running
    camp("d_other", "defi", ago(days=2), rec=["c2"], defi=defi(day(8)))
    camp("d_old", "defi", ago(days=400), defi=defi(day(-300)))
    db.defi_rewards.insert_one({"id": "r_won", "tenant_id": "t1", "campaign_id": "d_won", "customer_id": "c1",
                                "title": "Défi d_won", "reward": "Dessert", "won_at": ago(hours=3),
                                "expires_at": now + timedelta(days=20), "status": "pending"})
    db.defi_rewards.insert_one({"id": "r_given", "tenant_id": "t1", "campaign_id": "d_given", "customer_id": "c1",
                                "title": "Défi d_given", "reward": "Dessert", "won_at": ago(days=2),
                                "expires_at": now + timedelta(days=20), "status": "redeemed"})
    db.defi_rewards.insert_one({"id": "r_old", "tenant_id": "t1", "campaign_id": "d_old", "customer_id": "c1",
                                "title": "Défi d_old", "reward": "Dessert", "won_at": ago(days=320),
                                "expires_at": ago(days=290), "status": "redeemed"})
    db.defi_rewards.insert_one({"id": "r_par", "tenant_id": "t1", "campaign_id": "parrainage:x", "customer_id": "c1",
                                "kind": "parrainage", "title": "Parrainage", "reward": "Une coupe", "won_at": ago(days=5),
                                "expires_at": None, "status": "pending"})
    for i, h in enumerate((2, 26, 27, 50, 75, 100)):            # c1's visits: some in, some before the défis
        db.visits.insert_one({"id": f"v{i}", "tenant_id": "t1", "customer_id": "c1", "visit_time": ago(hours=h)})
    db.visits.insert_one({"id": "v-old", "tenant_id": "t1", "customer_id": "c1", "visit_time": ago(days=40)})
    db.visits.insert_one({"id": "v-c3", "tenant_id": "t1", "customer_id": "c3", "visit_time": ago(hours=5)})
    # c4 also got 62 newer messages that are over: o_long falls out of the 60-campaign window (before as now)
    for i in range(62):
        db.campaigns.insert_one({"id": f"flood{i}", "tenant_id": "t1", "name": "x", "content": "x", "kind": "nouveaute",
                                 "status": "sent", "sent_at": ago(days=8, minutes=i), "recipient_ids": ["c4"]})

    def open_card(cid):
        bc = f"FT-{cid.upper()}00"
        CALLS.clear()
        r = http("GET", f"/api/card/{bc}", headers={"X-Card-Key": CO.key_for(bc)})
        return r, list(CALLS)

    # ------------------------------------------------------------------
    print("same offers, same order, same défis as before")
    for cid, label in (("c1", "client"), ("c2", "another client (o_other only)"), ("c3", "paused client"),
                       ("c4", "client past the 60-campaign window"), ("c5", "client who got nothing")):
        cust = db.customers.find_one({"id": cid})
        r, _ = open_card(cid)
        check(f"{label}: 200", r.status_code == 200)
        body = r.json()
        got_offers = [o["id"] for o in body.get("offers") or []]
        check(f"{label}: offers {got_offers} == before", got_offers == legacy_offers(server, "t1", cid))
        check(f"{label}: défis == before", body.get("defis") == legacy_defis(server, cust))

    r, _ = open_card("c1")
    body = r.json()
    ids = [o["id"] for o in body["offers"]]
    check("c1 sees: shop offer, then the live campaigns newest first",
          ids == ["offer-main", "o_soon", "legacy", "ev_live", "o_live", "n_live", "n_vis", "o_long"])
    check("never: ended, other client's, cancelled, scheduled, older than a year, défis",
          not set(ids) & {"o_ended", "n_old", "ev_past", "o_other", "o_cancel", "o_sched", "o_year", "d_run1"})
    o_live = next(o for o in body["offers"] if o["id"] == "o_live")
    check("an offer keeps its photo, link, text and end", o_live["image_url"] == "/api/media/" + "a" * 32
          and o_live["link"] == "https://example.fr/menu" and o_live["body"] == "Texte o_live"
          and o_live["valid_until"] and o_live["campaign_kind"] == "offre")
    o_soon = next(o for o in body["offers"] if o["id"] == "o_soon")
    check("a future offer keeps valid_from, discount and hours", o_soon["valid_from"] and o_soon["discount_label"]
          and o_soon["hours_label"])
    run = body["defis"]["running"]
    check(f"c1's running défis, soonest end first: {[d['id'] for d in run]}",
          [d["id"] for d in run] == ["d_today", "d_run1", "d_run2"])
    check("défi progress counted (per_scan d_run2 = the 1 scan since its send yesterday)",
          {d["id"]: d["progress"] for d in run}["d_run2"] == 1 and all(d["progress"] > 0 for d in run))
    check("a défi won and handed over (d_given) never comes back as running", "d_given" not in [d["id"] for d in run])
    check("won: the pending défi reward and the parrainage, not the redeemed ones",
          sorted(w["id"] for w in body["defis"]["won"]) == ["r_par", "r_won"])
    check("c2 sees o_other and its own défi only",
          [o["id"] for o in open_card("c2")[0].json()["offers"]] == ["offer-main", "o_other"]
          and [d["id"] for d in open_card("c2")[0].json()["defis"]["running"]] == ["d_other"])

    # ------------------------------------------------------------------
    print("every campaigns read of a card open is bounded and names its fields")
    r, calls = open_card("c1")
    camp_reads = [c for c in calls if c["coll"] == "campaigns"]
    check(f"campaigns reads per open: {len(camp_reads)} (offers, défis, notifications, photo)", len(camp_reads) <= 4)
    for c in camp_reads:
        p = c["projection"] or {}
        names = set(p) if isinstance(p, dict) else set(p)
        inclusive = isinstance(p, dict) and any(v for k, v in p.items() if k != "_id")
        check(f"  {sorted(c['filter'])[:5]}…: a projection without recipient_ids",
              p and "recipient_ids" not in names and (inclusive or not isinstance(p, dict)))
        bounded = (c["limit"] is not None and 0 < c["limit"] <= 60) or "defi.end_date" in str(c["filter"])
        check(f"  …: bounded (limit={c['limit']})", bounded)
    offers_read = next((c for c in camp_reads if c["filter"].get("status") == "sent" and "kind" not in c["filter"]
                        and c["limit"] == 60), None)
    check("the offers read: limit 60 (the same window as before)", offers_read is not None)
    defi_read = next((c for c in camp_reads if "defi" in str(c["filter"].get("kind", ""))
                      or "defi" in str(c["filter"].get("$or", ""))), None)
    check("the défi read exists", defi_read is not None)
    if defi_read:
        got = {d["id"] for d in db.campaigns.find(defi_read["filter"], {"_id": 0, "id": 1})}
        check(f"the défi read returns only défis not over: {sorted(got)}",
              got and not got & {"d_ended", "d_old", "d_other"} and {"d_run1", "d_run2", "d_today"} <= got)
        check("  … and only défis", got <= {"d_run1", "d_run2", "d_today", "d_won", "d_given"})

    print("the défis cost one rewards read and one visits read")
    rew = [c for c in calls if c["coll"] == "defi_rewards"]
    vis = [c for c in calls if c["coll"] == "visits" and "visit_time" in c["filter"]]
    check(f"defi_rewards reads per open: {len(rew)} == 1", len(rew) == 1)
    check(f"défi visits reads with 3 running défis: {len(vis)} == 1", len(vis) == 1)
    _, calls5 = open_card("c5")
    check("a client with no running défi: no visits read for défis",
          not [c for c in calls5 if c["coll"] == "visits" and "visit_time" in c["filter"]])
    idx = db.campaigns.index_information().get("defi_running") or {}
    check("index defi_running: tenant + recipient + défi end date, défi campaigns only",
          list(idx.get("key") or []) == [("tenant_id", 1), ("recipient_ids", 1), ("defi.end_date", 1)]
          and idx.get("partialFilterExpression") == {"kind": "defi"})

    # ------------------------------------------------------------------
    print("unit: first_live_day")
    from zoneinfo import ZoneInfo
    paris = ZoneInfo("Europe/Paris")
    for label, local in (("noon", datetime(2026, 11, 25, 12, 0)), ("23:59:58", datetime(2026, 11, 25, 23, 59, 58)),
                         ("23:59:59.5", datetime(2026, 11, 25, 23, 59, 59, 500000)),
                         ("00:00:00", datetime(2026, 11, 26, 0, 0, 0)),
                         ("DST end 25 Oct 02:30", datetime(2026, 10, 25, 2, 30)),
                         ("DST start 29 Mar 03:30", datetime(2026, 3, 29, 3, 30)),
                         ("31 Dec 23:59:59.9", datetime(2026, 12, 31, 23, 59, 59, 900000))):
        at = local.replace(tzinfo=paris).astimezone(timezone.utc)
        d0 = D.first_live_day(at)
        first = date.fromisoformat(d0)
        check(f"{label}: {d0} is the first day still running", K.end_of(first) >= at
              and K.end_of(first - timedelta(days=1)) < at)
    check("23:59:59.5 Paris → tomorrow (the day already ended)",
          D.first_live_day(datetime(2026, 11, 25, 23, 59, 59, 500000, tzinfo=paris)) == "2026-11-26")

    print("unit: progress_many == progress")
    cust = db.customers.find_one({"id": "c1"})
    cs = list(db.campaigns.find({"id": {"$in": ["d_run1", "d_run2", "d_today", "d_ended"]}}, {"_id": 0}))
    many = D.progress_many(cs, "c1", now)
    check("one value per défi", set(many) == {c["id"] for c in cs})
    for c in cs:
        check(f"  {c['id']}: {many[c['id']]} == {D.progress(c, 'c1', now)}", many[c["id"]] == D.progress(c, "c1", now))
    check("no défi → {} and no read", D.progress_many([], "c1", now) == {})
    check("a défi without sent_at → 0", D.progress_many([{"id": "z", "tenant_id": "t1", "defi": {}}], "c1", now) == {"z": 0})

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
