"""
Super admin › Tableau de bord › « Activité du jour » (user, 2026-11-10: the
old « Activité récente » was « ekdm ghatiya »). Three sections, every
business's activity of ONE Paris day — midnight to midnight, live today,
‹ › to past days:

    Parrainage                  the parrainages made that day
    Campagnes + automatisations the campaigns sent and the automation
                                messages sent that day
    Nouveaux clients            the clients who joined that day

One line per business — per store for a franchise — with its count and its
latest time; the line opens its details. No phone, no e-mail: a client is
« Prénom N. ».

Run: cd api && python3 -u tests/test_admin_daily_activity.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-daily-activity")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail!r}"))


def main():
    import server
    import auth
    import httpx
    from features import admin_dashboard as D

    db = server.db
    # « now » = 2026-11-10 16:00 Paris (15:00 UTC)
    NOW = dt.datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
    D._now = lambda: NOW

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    at = lambda *a: dt.datetime(*a, tzinfo=UTC)          # noqa: E731

    db.tenants.insert_one({"id": "rt", "slug": "rt", "name": "ROYAL TRIM", "is_active": True, "created_at": at(2026, 10, 1),
                           "branches": [{"id": "main", "name": "ROYAL TRIM LIBÉRTÉ", "is_main": True},
                                        {"id": "b2", "name": "ROYAL TRIM PL-MONSTRE"}]})
    db.tenants.insert_one({"id": "gs", "slug": "gs", "name": "Green Smoke", "is_active": True, "created_at": at(2026, 10, 1)})
    db.tenants.insert_one({"id": "quiet", "slug": "quiet", "name": "Café Calme", "is_active": True, "created_at": at(2026, 10, 1)})
    db.users.insert_one({"email": "admin@fidclic.com", "role": "super_admin", "tenant_id": None})
    db.users.insert_one({"email": "own@rt.fr", "role": "business_owner", "tenant_id": "rt"})

    def cust(cid, tid, name, created, branch=None, **kw):
        doc = {"id": cid, "tenant_id": tid, "name": name, "created_at": created, "phone": "0611223344",
               "email": f"{cid}@mail.fr", "acquisition_source": kw.pop("source", "qr_comptoir"), **kw}
        if branch:
            doc["branch_id"] = branch
        db.customers.insert_one(doc)

    # --- today, 10 Nov (Paris) -----------------------------------------------
    cust("n1", "rt", "Jules Martin", at(2026, 11, 10, 9, 0))                  # no store → Libérté (main)
    cust("n2", "rt", "Nino Petit", at(2026, 11, 10, 14, 8), "main")
    cust("n3", "rt", "Amjad", at(2026, 11, 10, 11, 0), "b2", source="parrainage")
    cust("n4", "gs", "Sara Lopez", at(2026, 11, 9, 23, 30))                   # 00:30 Paris on the 10th → today
    cust("gone", "gs", "Effacé Moi", at(2026, 11, 10, 10, 0), deleted_at=at(2026, 11, 10, 12, 0))
    cust("y1", "gs", "Hier Client", at(2026, 11, 9, 22, 30))                  # 23:30 Paris on the 9th → yesterday
    cust("p1", "rt", "Parrain Un", at(2026, 9, 1), "b2")
    db.referral_redemptions.insert_one({"tenant_id": "rt", "referrer_customer_id": "p1", "referee_customer_id": "n3",
                                        "created_at": at(2026, 11, 10, 11, 0), "referrer_pending": True, "source": "qr_card"})
    db.referral_redemptions.insert_one({"tenant_id": "rt", "referrer_customer_id": "p1", "referee_customer_id": "old",
                                        "created_at": at(2026, 11, 9, 12, 0), "source": "qr_card"})
    db.campaigns.insert_one({"id": "k1", "tenant_id": "rt", "name": "Promo Monstre", "status": "sent", "sent_at": at(2026, 11, 10, 13, 0),
                             "store_ids": ["b2"], "recipient_ids": ["p1", "n3"], "targeted_count": 2})
    db.campaigns.insert_one({"id": "k2", "tenant_id": "gs", "name": "Happy hour", "status": "sent", "sent_at": at(2026, 11, 10, 8, 0),
                             "recipient_ids": ["n4", "y1", "x"], "targeted_count": 3})
    db.campaigns.insert_one({"id": "k3", "tenant_id": "gs", "name": "Brouillon", "status": "draft", "sent_at": None})
    db.campaigns.insert_one({"id": "k4", "tenant_id": "gs", "name": "Programmée", "status": "scheduled", "scheduled_at": at(2026, 11, 10, 18, 0)})
    for i, (cid, scen, st) in enumerate([("n1", "birthday", "sent"), ("n2", "birthday", "sent"), ("p1", "inactive", "sent"),
                                         ("n2", "inactive", "holdout"), ("n1", "inactive", "deferred")]):
        db.automation_log.insert_one({"id": f"l{i}", "tenant_id": "rt", "automation_id": f"a-{scen}", "scenario": scen,
                                      "customer_id": cid, "sent_at": at(2026, 11, 10, 7 + i, 0), "status": st})
    # --- the DST day: 25 Oct 2026 lasts 25 h in Paris -------------------------
    cust("d1", "gs", "Dst Début", at(2026, 10, 24, 22, 30))                  # 00:30 CEST on the 25th
    cust("d2", "gs", "Dst Fin", at(2026, 10, 25, 22, 30))                    # 23:30 CET on the 25th
    cust("d3", "gs", "Dst Après", at(2026, 10, 25, 23, 30))                  # 00:30 CET on the 26th

    admin = auth.create_access_token({"sub": "admin@fidclic.com", "role": "super_admin"})
    A = {"Authorization": "Bearer " + admin}

    def get(day=None):
        r = http("GET", "/api/admin/dashboard/activity" + (f"?day={day}" if day else ""), headers=A)
        return r, (r.json() if r.status_code == 200 else {})

    print("1. Aujourd'hui (Paris)")
    r, d = get()
    check(f"answers the super admin ({r.status_code})", r.status_code == 200, r.text[:300])
    check("the day is today in Paris, flagged as today", d.get("day") == "2026-11-10" and d.get("today") is True, (d.get("day"), d.get("today")))
    check("from Paris midnight (23:00 UTC the day before)", (d.get("from") or "").startswith("2026-11-09T23:00"), d.get("from"))
    sec = d.get("sections") or {}
    check("three sections, in order", [s.get("key") for s in sec] == ["parrainage", "campagnes", "nouveaux_clients"] if isinstance(sec, list) else False,
          sec if not isinstance(sec, list) else [s.get("key") for s in sec])
    S = {s["key"]: s for s in sec} if isinstance(sec, list) else {}

    def line(key, tid, store=None):
        return next((x for x in (S.get(key) or {}).get("rows") or [] if x.get("tenant_id") == tid and x.get("store_id") == store), None)

    print("2. Nouveaux clients")
    nc = S.get("nouveaux_clients") or {}
    check("4 new clients today (the deleted one and yesterday's are not)", nc.get("total") == 4, nc.get("total"))
    lib, mon, gs = line("nouveaux_clients", "rt", "main"), line("nouveaux_clients", "rt", "b2"), line("nouveaux_clients", "gs")
    check("Royal Trim: one line per store — Libérté 2 (one without a store), PL-Monstre 1",
          (lib or {}).get("count") == 2 and (mon or {}).get("count") == 1, (lib, mon))
    check("each line names the business and the store", (lib or {}).get("tenant_name") == "ROYAL TRIM" and (lib or {}).get("store_name") == "ROYAL TRIM LIBÉRTÉ")
    check("a one-store business: one line, no store", gs and gs.get("store_id") is None and gs.get("count") == 1, gs)
    check("00:30 Paris counts for the day it is in Paris", gs and gs["items"][0]["name"] == "Sara L.", gs)
    check("the line's latest time (Libérté: 14:08 UTC)", (lib or {}).get("last_at", "").startswith("2026-11-10T14:08"), (lib or {}).get("last_at"))
    check("details: newest first, « Prénom N. », its source", [i["name"] for i in (lib or {}).get("items") or []] == ["Nino P.", "Jules M."]
          and (lib or {})["items"][0].get("source"), (lib or {}).get("items"))
    blob = str(d)
    check("no phone, no e-mail anywhere", "0611223344" not in blob and "@mail.fr" not in blob)
    check("a business with nothing that day has no line", not any(x.get("tenant_id") == "quiet" for s in sec for x in s.get("rows") or []))
    check("busiest line first", [x["count"] for x in nc.get("rows") or []] == sorted([x["count"] for x in nc.get("rows") or []], reverse=True))

    print("3. Parrainage")
    pr = S.get("parrainage") or {}
    check("1 parrainage today (yesterday's is not)", pr.get("total") == 1, pr.get("total"))
    p = line("parrainage", "rt", "b2")
    check("on the filleul's store (PL-Monstre)", p and p.get("count") == 1, pr.get("rows"))
    it = ((p or {}).get("items") or [{}])[0]
    check("details: parrain → filleul, its status, its time", it.get("parrain") == "Parrain U." and it.get("filleul") == "Amjad"
          and it.get("status") == "En attente" and it.get("at", "").startswith("2026-11-10T11:00"), it)

    print("4. Campagnes + automatisations")
    ca = S.get("campagnes") or {}
    k1, k2, auto = line("campagnes", "rt", "b2"), line("campagnes", "gs"), line("campagnes", "rt", "main")
    check("a campaign of one store sits on that store", k1 and k1.get("campaigns") == 1, k1)
    check("a one-store business's campaign: its recipients", k2 and k2.get("campaigns") == 1 and k2.get("messages") == 3, k2)
    check("drafts and campaigns still to go out are not counted", not any("Brouillon" in str(x) or "Programmée" in str(x) for x in ca.get("rows") or []))
    check("automations: sent messages only (no témoin, no deferred), on the client's store",
          auto and auto.get("automations") == 2 and auto.get("messages") == 2, auto)
    mon_auto = k1 and k1.get("automations")
    check("PL-Monstre: its campaign + its inactive message", mon_auto == 1 and k1.get("messages") == 3, k1)
    names = {i.get("name"): i for i in (auto or {}).get("items") or []}
    check("details name the scenario and how many it reached", (names.get("Anniversaire") or {}).get("messages") == 2
          and (names.get("Anniversaire") or {}).get("kind") == "automatisation", (auto or {}).get("items"))
    camp = next((i for i in (k1 or {}).get("items") or [] if i.get("kind") == "campagne"), {})
    check("…and a campaign by its name", camp.get("name") == "Promo Monstre" and camp.get("messages") == 2, (k1 or {}).get("items"))
    check("section total = campaigns + automations sent", ca.get("total") == 2 + 3, ca.get("total"))

    print("5. Les jours passés")
    r, y = get("2026-11-09")
    S9 = {s["key"]: s for s in y.get("sections") or []}
    check("yesterday is not today, and says which day today is", y.get("day") == "2026-11-09" and y.get("today") is False
          and y.get("today_day") == "2026-11-10")
    check("yesterday's client (23:30 Paris) and parrainage are there",
          (S9.get("nouveaux_clients") or {}).get("total") == 1 and (S9.get("parrainage") or {}).get("total") == 1, S9)
    r, z = get("2026-10-25")
    Z = {s["key"]: s for s in z.get("sections") or []}
    check("the 25-hour DST day: 00:30 CEST and 23:30 CET both in, 00:30 the day after out",
          (Z.get("nouveaux_clients") or {}).get("total") == 2, (Z.get("nouveaux_clients") or {}).get("rows"))
    check("a day with nothing: three empty sections", get("2026-01-05")[1].get("sections") and all(
        s["total"] == 0 and s["rows"] == [] for s in get("2026-01-05")[1]["sections"]))
    check("the day after / before are given for ‹ ›", d.get("prev") == "2026-11-09" and d.get("next") is None
          and y.get("next") == "2026-11-10", (d.get("prev"), d.get("next"), y.get("next")))
    check("a future day → 400", get("2026-11-11")[0].status_code == 400)
    check("a wrong day → 400", get("2026-13-40")[0].status_code == 400 and get("hier")[0].status_code == 400)

    print("6. À minuit, le jour change tout seul")
    D._now = lambda: at(2026, 11, 10, 23, 0)                       # 00:00 Paris on the 11th
    r, n = get()
    check("at Paris midnight « today » is the new day, empty", n.get("day") == "2026-11-11"
          and all(s["total"] == 0 for s in n.get("sections") or [{"total": 1}]), (n.get("day"), [s.get("total") for s in n.get("sections") or []]))
    D._now = lambda: NOW

    print("6b. Lu par date sur toute la plateforme : un index par collection")
    def by_date(coll, field):
        return any(list(v["key"])[0][0] == field for v in db[coll].index_information().values())
    check("automation_log, referral_redemptions, customers, campaigns are indexed by date",
          by_date("automation_log", "sent_at") and by_date("referral_redemptions", "created_at")
          and by_date("customers", "created_at") and by_date("campaigns", "sent_at"),
          {c: [list(v["key"]) for v in db[c].index_information().values()] for c in ("automation_log", "referral_redemptions")})

    print("7. Qui peut")
    O = {"Authorization": "Bearer " + auth.create_access_token({"sub": "own@rt.fr", "role": "business_owner", "tenant_id": "rt"})}
    check("a business owner: never (403)", http("GET", "/api/admin/dashboard/activity", headers=O).status_code == 403)
    check("no session: never (401)", http("GET", "/api/admin/dashboard/activity").status_code == 401)

    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
