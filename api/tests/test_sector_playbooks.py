"""
Sector playbooks — advice per « Activité précise » (user, 2026-10-26: a café
was getting salon advice; « jahaan jahaan possible and important ho »).

  · every activity of services/activities.py has a complete playbook;
  · a figure is shown only with its real source (name, year, link) — no
    « estimation courante du secteur » anywhere any more;
  · Insights, the Copilote and the Tableau de bord read the same playbook;
  · the old food flag is fixed: « boulangerie », « café » are food shops.

Run: /usr/local/bin/python3 api/tests/test_sector_playbooks.py
"""
import asyncio
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-for-playbooks")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0
HERE = os.path.dirname(__file__)
IMAGES = {f[:-5] for f in os.listdir(os.path.join(HERE, "..", "..", "public", "insights")) if f.endswith(".webp")}


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}")


def main():
    import server
    import auth
    import httpx
    import features.insights_page as I
    import features.copilot as C
    import features.dashboard_home as DH
    from services import activities as A
    from services import playbooks as PB

    db = server.db
    for mod in (I, C, DH):
        mod._db = db

    # ---- 1. every activity has a complete playbook -------------------------------------------
    print("\nUn playbook par activité")
    keys = [a["key"] for a in A.ACTIVITIES]
    plays = {k: PB.of({"activity_key": k}) for k in keys}
    check(f"all {len(keys)} activities resolve to their own playbook",
          all(p["key"] == k for k, p in plays.items()))
    bad = [k for k, p in plays.items() if not (
        isinstance(p["food"], bool) and isinstance(p["drinks"], bool) and isinstance(p["meals"], bool)
        and len(p["items"]) == 2 and all(isinstance(w, str) and w for w in p["items"])
        and isinstance(p["offer"], str) and 0 < len(p["offer"]) <= 40 and p["label"])]
    check(f"each says food / drinks / meals, its words and its offer {bad}", bad == [])
    check("drinks and meals are only for food shops",
          all(p["food"] for p in plays.values() if p["drinks"] or p["meals"]))
    no_levers = [k for k, p in plays.items() if not p["levers"] and k not in ("autre", "autre_commerce")]
    check(f"every precise trade carries advice of its own {no_levers}", no_levers == [])

    shelves, cats = {"opportunite", "idee"}, set(I.CATEGORIES)
    broken = []
    for k, p in plays.items():
        seen = set()
        for lv in p["levers"]:
            ok = (lv["key"] not in seen and lv["shelf"] in shelves and lv["category"] in cats
                  and lv["title"] and lv["body"] and lv["image"] in IMAGES
                  and all(1 <= m <= 12 for m in lv.get("months") or [])
                  and (lv.get("template") or lv.get("to")))
            seen.add(lv["key"])
            t = lv.get("template")
            if t:
                ok = ok and t["key"].startswith("pb:") and 0 < len(t["title"]) <= 50 and 0 < len(t["message"]) <= 160
            if lv["shelf"] == "idee":
                ok = ok and bool(lv.get("months")) and bool(t)
            if not ok:
                broken.append(f"{k}.{lv['key']}")
    check(f"every lever is well formed (shelf, category, image, months, push limits) {broken[:5]}", broken == [])

    # ---- 2. only sourced numbers --------------------------------------------------------------
    print("\nSeulement des chiffres sourcés")
    facts = [f for p in plays.values() for f in p["facts"].values()]
    check("there are sourced figures", len(facts) >= 6)
    check("each figure has its source, year and link",
          all(f["source"] and f["url"].startswith("https://") and 2000 <= f["year"] <= 2026 and f["short"]
              for f in facts))
    dangling = [f"{k}.{lv['key']}" for k, p in plays.items() for lv in p["levers"]
                if lv.get("fact") and lv["fact"] not in p["facts"]]
    check(f"a lever only names a figure that exists {dangling}", dangling == [])
    stats = re.compile(r"\d+\s?%")
    loose = [f"{k}.{lv['key']}" for k, p in plays.items() for lv in p["levers"]
             if stats.search(lv["title"] + " " + lv["body"]) and not lv.get("fact")]
    check(f"no percentage in a lever's advice without a source {loose}", loose == [])
    check("the made-up sector estimate is gone from the engine", not hasattr(I, "BENCHMARK"))

    # ---- 3. which playbook a shop gets ---------------------------------------------------------
    print("\nQuel playbook pour quel commerce")
    check("legacy sector « boulangerie » is a food shop (the old flag said salon)",
          PB.of({"sector": "boulangerie"})["key"] == "boulangerie" and PB.of({"sector": "boulangerie"})["food"])
    check("legacy « café » sells drinks", PB.of({"sector": "café"})["drinks"] is True)
    check("« bakery » with no activity reads as a boulangerie", PB.of({"sector": "bakery"})["key"] == "boulangerie")
    check("a barbier is a service shop", PB.of({"sector": "salon", "activity_key": "barbier"})["food"] is False)
    check("the activity chosen wins over the sector",
          PB.of({"sector": "cafe", "activity_key": "fleuriste"})["key"] == "fleuriste")
    check("an unknown activity falls back on the sector",
          PB.of({"sector": "salon", "activity_key": "zzz<script>"})["key"] == "coiffure_mixte")
    check("no tenant at all → the neutral playbook", PB.of(None)["key"] == "autre" and PB.of({})["key"] == "autre")
    check("a playbook handed out is a copy (callers cannot change the catalogue)",
          PB.of({"activity_key": "cafe"}) is not PB.of({"activity_key": "cafe"}))
    tobacco = re.compile(r"tabac|cigarette|puff|vapot", re.I)
    leaks = [k for k in ("tabac_presse", "bar_tabac") for lv in plays[k]["levers"]
             if lv.get("template") and tobacco.search(lv["template"]["title"] + lv["template"]["message"])]
    check(f"no message ever promotes tobacco (loi Évin) {leaks}",
          leaks == [] and not tobacco.search(plays["tabac_presse"]["offer"] + plays["bar_tabac"]["offer"]))
    health = re.compile(r"soign|guéri|anxi|sommeil|douleur|thérap", re.I)
    check("a CBD shop never makes a health claim",
          not any(health.search(lv["body"] + json.dumps(lv.get("template") or {}, ensure_ascii=False))
                  for lv in plays["cbd"]["levers"]))
    check("months are a real calendar", all(set(lv.get("months") or []) <= set(range(1, 13))
                                             for p in plays.values() for lv in p["levers"]))

    # ---- 4. Insights, per shop -----------------------------------------------------------------
    print("\nInsights selon l'activité")
    now = dt.datetime(2026, 9, 26, 15, 0, tzinfo=dt.timezone.utc)
    shops = {
        "cafe": {"sector": "cafe"}, "boul": {"sector": "boulangerie"},
        "barb": {"sector": "salon", "activity_key": "barbier"},
        "opt": {"sector": "retail", "activity_key": "opticien"},
        "fleur": {"sector": "retail", "activity_key": "fleuriste"},
        "choco": {"sector": "bakery", "activity_key": "chocolatier"},
        "bar": {"sector": "bar"}, "gym": {"sector": "gym"}, "blank": {},
    }
    for tid, extra in shops.items():
        db.tenants.insert_one({"id": tid, "slug": tid, "name": tid.title(), "is_active": True, "plan": "vip",
                               "subscription_status": "active", **extra})
        db.users.insert_one({"email": f"o@{tid}", "role": "business_owner", "tenant_id": tid})
        # a few clients, so the computed shelves have something to read
        for i in range(6):
            db.customers.insert_one({"id": f"{tid}-c{i}", "tenant_id": tid, "name": f"C{i}", "visits": 3 + i,
                                     "total_amount_paid": 25.0 * (3 + i), "barcode_id": f"{tid}-{i}",
                                     "created_at": now - dt.timedelta(days=200),
                                     "last_visit_date": now - dt.timedelta(days=10 + 25 * i)})
            db.visits.insert_one({"tenant_id": tid, "customer_id": f"{tid}-c{i}", "amount_paid": 25.0,
                                  "visit_time": now - dt.timedelta(days=3 + i)})

    pay = {tid: I._payload(tid, now) for tid in shops}

    def keys_of(p, shelf):
        return {x["key"] for x in p[shelf]["all"]}

    def text(p):
        return json.dumps(p, ensure_ascii=False, default=str)

    check("the page says which activity it advises", pay["barb"]["activity"] == {"key": "barbier", "label": "Barbier"})
    check("the boulangerie is now a food shop", pay["boul"]["food"] is True)
    check("… without a Happy Hour on drinks it does not sell", "happy_hour" not in keys_of(pay["boul"], "ideas"))
    check("a bar keeps its Happy Hour", "happy_hour" in keys_of(pay["bar"], "ideas"))
    check("… but is not told to write a menu du jour", "menu_du_jour" not in keys_of(pay["bar"], "actions"))
    check("a café still gets its Happy Hour", "happy_hour" in keys_of(pay["cafe"], "ideas"))
    check("a barbier never hears of drinks", "boisson" not in text(pay["barb"]).lower())
    check("… speaks of prestations", "prestation" in text(pay["barb"]["opportunities"]))
    barb_levers = {lv["key"] for lv in plays["barbier"]["levers"] if lv["shelf"] == "opportunite"}
    check("the barbier's own advice is on its opportunities shelf",
          barb_levers and barb_levers <= keys_of(pay["barb"], "opportunities"))
    check("… and one of it is in the three shown",
          any(o["key"] in barb_levers for o in pay["barb"]["opportunities"]["shown"]))
    check("a café, a barbier and an opticien are not given the same advice",
          len({frozenset(keys_of(pay[t], "opportunities")) for t in ("cafe", "barb", "opt")}) == 3)

    impacts = [x["impact"] for t in shops for s in ("opportunities", "actions")
               for x in pay[t][s]["all"] if "impact" in x]
    check("no « estimation courante du secteur » left on any page",
          not any("estimation courante" in text(p) for p in pay.values()))
    check("every impact is calculated, sourced or plain advice",
          all(i["kind"] in ("calcule", "source", "conseil") for i in impacts))
    check("a sourced figure carries its source and its link",
          all(i["basis"] and i["url"].startswith("https://") for i in impacts if i["kind"] == "source"))
    check("plain advice shows no number", all(i["euros"] is None and not re.search(r"\d", i["label"])
                                              for i in impacts if i["kind"] == "conseil"))
    check("the opticien sees the 2-year renewal rule with its source",
          any(i["kind"] == "source" and "ameli" in i["url"] for x in pay["opt"]["opportunities"]["all"]
              for i in [x["impact"]]))
    check("the impact note no longer mentions sector estimates",
          "estimation" not in pay["cafe"]["impact_note"].lower() and "source" in pay["cafe"]["impact_note"].lower())

    print("\nLes temps forts de l'activité")
    may, jan, mar = (dt.datetime(2026, m, 3, 10, tzinfo=dt.timezone.utc) for m in (5, 1, 3))
    fm = I._payload("fleur", may)["ideas"]["shown"][0]
    check(f"a fleuriste in May opens on the Fête des mères ({fm['key']})", "meres" in fm["key"])
    check("… with its sourced figure (FFAF)", "FFAF" in (fm.get("fact") or {}).get("source", "")
          or "Fleuristes" in (fm.get("fact") or {}).get("source", ""))
    check("out of season it is not shown",
          not any("meres" in i["key"] for i in pay["fleur"]["ideas"]["shown"]))
    check("a boulangerie in January opens on the galette",
          "galette" in I._payload("boul", jan)["ideas"]["shown"][0]["key"])
    check("a chocolatier in March opens on Easter",
          "paques" in I._payload("choco", mar)["ideas"]["shown"][0]["key"])
    check("a seasonal idea is never shown twice", all(
        len([i["key"] for i in I._payload(t, d)["ideas"]["shown"]]) ==
        len({i["key"] for i in I._payload(t, d)["ideas"]["shown"]})
        for t in shops for d in (may, jan, mar, now)))

    # ---- 5. through the real endpoints ---------------------------------------------------------
    print("\nPar les vraies routes")

    def H(tid):
        return {"Authorization": "Bearer " + auth.create_access_token(
            {"sub": f"o@{tid}", "role": "business_owner", "tenant_id": tid})}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    r = http("GET", "/api/owner/insights/page", headers=H("barb"))
    check(f"GET /insights/page answers ({r.status_code})", r.status_code == 200)
    check("… with the barbier's playbook", r.status_code == 200 and r.json()["activity"]["key"] == "barbier")
    lever = next(lv for lv in plays["barbier"]["levers"] if lv.get("template"))
    tk = lever["template"]["key"]
    r = http("GET", f"/api/owner/insights/templates/{tk}", headers=H("barb"))
    check(f"its campaign opens in the composer ({r.status_code})",
          r.status_code == 200 and r.json()["title"] == lever["template"]["title"])
    r = http("GET", f"/api/owner/insights/templates/{tk}", headers=H("cafe"))
    check("a café cannot open the barbier's template (404)", r.status_code == 404)
    r = http("GET", "/api/owner/insights/templates/pb:..%2F..%2Fx", headers=H("barb"))
    check("a forged template key is refused", r.status_code == 404)
    r = http("GET", "/api/owner/insights/page")
    check("no token, no page", r.status_code in (401, 403))

    print("\nCopilote et Tableau de bord")
    shop = I.Shop("barb", now)
    recs = C.recommendations(shop)
    sector = [x for x in recs if x["key"].startswith("pb_")]
    check("the Copilote offers the barbier's own advice", bool(sector))
    check("… as a suggestion with no invented number",
          all(x["kind"] == "suggestion" and x["metrics"] == [] and x["detail"] for x in sector))
    check("the café's Copilote has none of the barbier's",
          not any(x["key"] in {s["key"] for s in sector} for x in C.recommendations(I.Shop("cafe", now))))
    r = http("GET", "/api/owner/copilot/page", headers=H("barb"))
    check(f"GET /copilot/page answers ({r.status_code})", r.status_code == 200)

    goal = {"is_set": True}
    camp = {"sent": 3}
    prod = [{"name": "Dégradé", "sales": 12}]
    dh = DH._recommendations({"inactive": 0}, camp, prod, goal, PB.of({"activity_key": "barbier"}))
    check("the dashboard says « prestation » to a barbier",
          any("prestation" in x["body"] for x in dh if x["key"] == "promote"))
    check("… and adds the barbier's top advice", any(x["key"].startswith("pb_") for x in dh))
    dc = DH._recommendations({"inactive": 0}, camp, prod, goal, PB.of({"sector": "cafe"}))
    check("a café still reads « produit »", any("produit" in x["body"] for x in dc if x["key"] == "promote"))
    check("never more than three", len(DH._recommendations({"inactive": 5}, {"sent": 0}, prod, {"is_set": False},
                                                           PB.of({"activity_key": "barbier"}))) <= 3)
    r = http("GET", "/api/owner/home/overview", headers=H("barb"))
    check(f"GET /home/overview answers ({r.status_code})", r.status_code == 200)
    check("… with the barbier's advice in it", r.status_code == 200 and any(
        x["key"].startswith("pb_") or "prestation" in x["body"] for x in r.json()["recommendations"]))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
