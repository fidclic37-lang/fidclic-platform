"""
« Impact FidClic » — the detail behind the figure (user, 2026-11-10).

The card said « + 230 € » and nothing else: not when, not which clients, not
which message brought them. Clicked, it now opens on the same page:

    Par action   each campagne / automatisation / offre / géoloc / parrain:
                 its name, when it went out, clients back, visits, CA
    Par visite   each visit FidClic counted: when, who, how much, where,
                 which message and how many days after it
    Par jour     the CA FidClic of each day, by source
    Export CSV   the visits, one line each

« Attendus de toute façon » are listed too, flagged, never in the total. The
detail's total is the card's: Analyses and the Tableau de bord say the same.

    cd api && python3 tests/test_impact_detail.py
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import sys
from zoneinfo import ZoneInfo

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from features import fidclic_impact as FI, analyses as A, dashboard_home as DH
    from features import impact_detail as ID, period as P, store_scope as S, role_perms as RP

    db = server.db
    A.init(db); DH.init(db); FI.init(db); ID.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    PARIS = ZoneInfo("Europe/Paris")
    # noon in Paris, so « N days ago » never crosses midnight whatever the run time
    now = dt.datetime.now(PARIS).replace(hour=12, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc)
    ago = lambda d, h=0: now - dt.timedelta(days=d, hours=h)

    # « attendus »: the client brain is not under test here — G's visit is the one it saw coming
    FI.expected_anyway = lambda tid, visits: {i for i, v in enumerate(visits) if v.get("customer_id") == "G"}

    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café"})
    db.tenants.insert_one({"id": "t2", "name": "Rival"})
    names = {"A": "Alice Martin", "B": "Bruno Petit", "C": "Chloé Plain", "D": "David Relance",
             "E": "Emma Geo", "F": "Fanny Filleule", "P": "Paul Parrain", "G": "Gaston Attendu",
             "X": "=HYPERLINK(\"http://evil\")", "Z": "Zoé Partie"}
    for cid, n in names.items():
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": n, "visits": 3,
                                 "created_at": ago(300), "last_visit_date": ago(1),
                                 **({"deleted_at": ago(0)} if cid == "Z" else {})})
    db.customers.insert_one({"id": "R1", "tenant_id": "t2", "name": "Rival Client", "visits": 1, "created_at": ago(300)})

    def visit(vid, cid, d, amount, h=0, tid="t1", branch=None):
        db.visits.insert_one({"id": vid, "tenant_id": tid, "customer_id": cid, "amount_paid": amount,
                              "visit_time": ago(d, h), **({"branch_id": branch} if branch else {})})

    def note(cid, kind, d, tid="t1", **extra):
        db.push_notifications.insert_one({"tenant_id": tid, "customer_id": cid, "type": kind,
                                          "title": extra.pop("title", "x"), "body": "x", "sent_at": ago(d), **extra})

    # a campaign to A and B, 5 days ago
    db.campaigns.insert_one({"id": "camp1", "tenant_id": "t1", "name": "Promo Noël", "status": "sent",
                             "sent_at": ago(5), "recipient_ids": ["A", "B"]})
    note("A", "campaign", 5, campaign_id="camp1", title="Promo Noël"); visit("vA", "A", 2, 20.0)
    note("B", "campaign", 5, campaign_id="camp1", title="Promo Noël"); visit("vB", "B", 3, 30.0)
    visit("vC", "C", 2, 99.0)                                            # a plain scan
    # an automation (relance) to D
    db.automations.insert_one({"id": "auto1", "tenant_id": "t1", "scenario": "inactive", "name": "Relance 30 jours"})
    note("D", "inactive", 4, automation_id="auto1", title="On vous attend"); visit("vD", "D", 1, 15.0)
    # a proximity push to E, an hour before the visit
    note("E", "proximity", 1, title="Vous passez devant !"); visit("vE", "E", 1, 7.0, h=-1)
    # F joined through P's card: both of F's visits are Parrainage
    db.referral_redemptions.insert_one({"tenant_id": "t1", "referrer_customer_id": "P", "referee_customer_id": "F"})
    visit("vF1", "F", 6, 12.0); visit("vF2", "F", 2, 8.0)
    # G came after an offer, at their usual rhythm: listed apart
    note("G", "offer", 3, title="-10 % ce week-end"); visit("vG", "G", 1, 50.0)
    # a client whose name could run a formula in a spreadsheet
    note("X", "campaign", 4, title="Flash"); visit("vX", "X", 1, 5.0)
    # a client since deleted: the visit stays, the name does not
    note("Z", "campaign", 4, title="Flash"); visit("vZ", "Z", 1, 4.0)
    # another shop's client, same day, same kind of message
    note("R1", "campaign", 4, tid="t2"); visit("vR", "R1", 1, 500.0, tid="t2")

    span = P.span(30, None, None, now)
    scope = S.resolve(TD())
    d = ID.detail("t1", scope, span, at=now)
    vis = {v["id"]: v for v in d["visits"]}
    acts = {a["key"]: a for a in d["actions"]}

    print("\nThe detail's total is the card's")
    a_imp = A.analyses(tab="vue", days=30, token_data=TD())["data"]["impact"]
    h_imp = DH.overview(days=30, token_data=TD())["impact"]
    check("same CA FidClic as Analyses", d["totals"]["revenue"] == a_imp["revenue"])
    check("same CA FidClic as the Tableau de bord", d["totals"]["revenue"] == h_imp["value"])
    check("same number of visits", d["totals"]["visits"] == a_imp["visits"])
    check("same split by source", all(d["totals"]["sources"][s["key"]]["revenue"] == s["revenue"]
                                      for s in a_imp["sources"]))
    check("same « attendus »", d["totals"]["attendus"] == a_imp["attendus"])
    check("the total is the sum of the counted visits",
          round(sum(v["amount"] for v in d["visits"] if not v["attendu"]), 2) == d["totals"]["revenue"])

    print("\nPar visite")
    check("a plain scan is not listed", "vC" not in vis)
    check("another shop's visit is never listed", "vR" not in vis)
    check("each counted visit says who", vis["vA"]["client"] == "Alice Martin" and vis["vA"]["client_id"] == "A")
    check("… how much", vis["vA"]["amount"] == 20.0)
    check("… which message", vis["vA"]["action_name"] == "Promo Noël" and vis["vA"]["source"] == "campagnes")
    check("… how many days after it (sent 5 days ago, came 2 days ago → 3)", vis["vA"]["days_after"] == 3)
    check("… when the message went out", vis["vA"]["sent_at"][:10] == ago(5).isoformat()[:10])
    check("… and where", vis["vA"]["store"] == "Le Petit Café")
    check("a visit the same day as the message is « 0 jour après »", vis["vE"]["days_after"] == 0)
    check("an automation is named by its own name", vis["vD"]["action_name"] == "Relance 30 jours")
    check("a filleul's visit names the parrain", "Paul Parrain" in vis["vF1"]["action_name"]
          and vis["vF1"]["source"] == "parrainage" and vis["vF1"]["days_after"] is None)
    check("an « attendu » is listed, flagged", vis["vG"]["attendu"] is True)
    check("… and every counted visit is not", not any(v["attendu"] for k, v in vis.items() if k != "vG"))
    check("a deleted client keeps the visit, not the name", vis["vZ"]["client"] == "Client supprimé")
    check("newest first", [v["at"] for v in d["visits"]] == sorted((v["at"] for v in d["visits"]), reverse=True))

    print("\nPar action")
    camp = acts.get("c:camp1") or {}
    check("the campaign by its name", camp.get("name") == "Promo Noël" and camp.get("source") == "campagnes")
    check("… with its clients back, visits and CA",
          camp.get("clients") == 2 and camp.get("visits") == 2 and camp.get("revenue") == 50.0)
    check("… and when it went out", (camp.get("first_sent") or "")[:10] == ago(5).isoformat()[:10])
    auto = acts.get("a:auto1") or {}
    check("the automation by its name", auto.get("name") == "Relance 30 jours" and auto.get("revenue") == 15.0)
    par = acts.get("p:P") or {}
    check("one line per parrain, all the filleuls' visits",
          "Paul Parrain" in (par.get("name") or "") and par.get("visits") == 2 and par.get("revenue") == 20.0)
    offer = [a for a in d["actions"] if a["source"] == "offres"]
    check("the « attendu » offer counts nothing, says what it set apart",
          offer and offer[0]["revenue"] == 0 and offer[0]["attendus"] == {"visits": 1, "revenue": 50.0})
    check("biggest CA first", [a["revenue"] for a in d["actions"]] == sorted((a["revenue"] for a in d["actions"]), reverse=True))
    check("the actions add up to the total", round(sum(a["revenue"] for a in d["actions"]), 2) == d["totals"]["revenue"])
    check("each visit points at its action", all(v["action"] in acts for v in d["visits"]))

    print("\nPar jour")
    days = {x["date"]: x for x in d["days"]}
    check("the days add up to the total", round(sum(x["total"] for x in d["days"]), 2) == d["totals"]["revenue"])
    day_a = ago(2).astimezone(PARIS).date().isoformat()
    check("a day says each source", days.get(day_a, {}).get("campagnes") == 20.0
          and days.get(day_a, {}).get("parrainage") == 8.0)
    day_g = ago(1).astimezone(PARIS).date().isoformat()
    check("the « attendus » of a day are apart", days.get(day_g, {}).get("attendus") == 50.0)

    print("\nOne establishment")
    db.visits.update_one({"id": "vB"}, {"$set": {"branch_id": "b2"}})
    one = ID.detail("t1", S.Scope(tenant_id="t1", ids=["b2"], allowed=["main", "b2"], all_ids=["main", "b2"],
                                  names={"main": "Le Petit Café", "b2": "Plumereau"}), span, at=now)
    check("only its visits", [v["id"] for v in one["visits"]] == ["vB"])
    check("named by its establishment", one["visits"][0]["store"] == "Plumereau")
    check("its total is its own", one["totals"]["revenue"] == 30.0)
    db.visits.update_one({"id": "vB"}, {"$unset": {"branch_id": ""}})

    print("\nA period")
    narrow = ID.detail("t1", scope, P.span(30, ago(2).astimezone(PARIS).date().isoformat(),
                                           ago(2).astimezone(PARIS).date().isoformat(), now), at=now)
    check("one day: that day's visits only", sorted(v["id"] for v in narrow["visits"]) == ["vA", "vF2"])
    empty = ID.detail("t1", scope, P.span(30, ago(200).astimezone(PARIS).date().isoformat(), ago(190).astimezone(PARIS).date().isoformat(), now), at=now)
    check("a period without visits: empty, no error",
          empty["visits"] == [] and empty["actions"] == [] and empty["totals"]["revenue"] == 0)

    print("\nA long list")
    old_cap = ID.MAX_VISITS
    ID.MAX_VISITS = 3
    cut = ID.detail("t1", scope, span, at=now)
    check("at most MAX_VISITS lines are sent, and it says so", len(cut["visits"]) == 3 and cut["truncated"] is True)
    check("… the totals still count them all", cut["totals"]["revenue"] == d["totals"]["revenue"])
    ID.MAX_VISITS = old_cap
    check("a normal list is not cut", d["truncated"] is False)

    print("\nExport CSV")
    resp = ID.analyses_export(days=30, token_data=TD())
    text = resp.body.decode("utf-8").lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text), delimiter=";" if text.count(";") > text.count(",") else ","))
    check("a header, then one line per listed visit", len(rows) == 1 + len(d["visits"]))
    check("the header names the columns", "Client" in rows[0] and "Message" in rows[0])
    flat = "\n".join(";".join(r) for r in rows)
    check("a formula in a client's name is not run by the spreadsheet", "\n=HYPERLINK" not in flat
          and not any(c.startswith("=") for r in rows for c in r))
    check("a CSV download", "text/csv" in resp.media_type and "attachment" in resp.headers.get("content-disposition", ""))

    print("\nThe routes")
    paths = {r.path for r in server.app.routes}
    check("from the Tableau de bord", "/api/owner/home/impact" in paths and "/api/owner/home/impact/export" in paths)
    check("from Analyses", "/api/owner/analyses/impact" in paths and "/api/owner/analyses/impact/export" in paths)
    check("each needs its own page's permission",
          RP.page_of("/api/owner/home/impact") == "dashboard" and RP.page_of("/api/owner/analyses/impact") == "analytics")
    h = ID.home_impact(days=30, token_data=TD())
    check("the route answers the same detail", h["totals"] == d["totals"] and len(h["visits"]) == len(d["visits"]))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
