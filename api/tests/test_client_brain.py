"""
Client brain (FidClic IA « Comprendre », user 2026-10-24): what each client's
visits say — usual products, weekday and slot, basket, rhythm pulled to the
shop's usual one, the window of the next visit, À l'heure / En retard /
Décroche, a profile and the one offer worth sending. Learned at every scan,
shown in « Profil client » and to the till, usable in Segmentation, and the
only definition of « Clients qui décrochent ».

Run: cd api && /usr/local/bin/python3 tests/test_client_brain.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-client-brain")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def visits_every(start, gap_days, n, hour_utc=15, items=None, amount=25.0, cid="c1", tid="t1", branch=None):
    out = []
    for i in range(n):
        out.append({"id": f"{cid}-v{i}", "tenant_id": tid, "customer_id": cid, "amount_paid": amount,
                    "visit_time": (start + dt.timedelta(days=gap_days * i)).replace(hour=hour_utc, minute=10),
                    "items": [{"name": x, "qty": 1, "price": 10, "line_total": 10} for x in (items or [])],
                    "branch_id": branch})
    return out


def pure_tests():
    from features import client_brain as CB
    print("pure: the brain of one client")
    # a Thursday, 15:10 UTC = 17:10 Paris (summer time)
    start = dt.datetime(2026, 6, 4, tzinfo=UTC)
    v = visits_every(start, 21, 7, items=["Coupe", "Barbe"])
    v[3]["items"] = [{"name": "Coupe"}]
    v[5]["amount_paid"] = 32.0
    v[1]["amount_paid"] = 20.0
    # a second scan the same day: a visit, not a rhythm of zero days
    v.append({**v[-1], "id": "dup", "visit_time": v[-1]["visit_time"] + dt.timedelta(minutes=20)})
    at = v[-1]["visit_time"] + dt.timedelta(days=5)
    b = CB.build(v, 35.0, "secteur", at)
    check("8 visits counted, 6 gaps on distinct days", b["visits_n"] == 8 and b["n_gaps"] == 6)
    check("own gap 21 days", b["own_gap"] == 21.0)
    check("rhythm pulled to the usual one: (6×21 + 2×35)/8 = 24.5", b["gap_days"] == 24.5)
    check("usual items in order, with their share", b["top_items"][0]["name"] == "Coupe" and b["top_items"][0]["share"] == 1.0
          and b["top_items"][1]["name"] == "Barbe" and b["top_items"][1]["share"] == round(7 / 8, 2))
    check("weekday: jeudi", b["weekday"]["label"] == "jeudi" and b["weekday"]["share"] == 1.0)
    check("two-hour window 17:00–19:00 Paris", b["hours"]["from"] == 17 and b["hours"]["to"] == 19)
    check("slot: l'après-midi (14:00–18:00)", b["slot"]["key"] == "apres_midi")
    check("basket: median 25 €, range kept", b["basket"] == 25.0 and b["basket_low"] <= 25 <= b["basket_high"])
    check("confidence between 5 and 95", 5 <= b["confidence"] <= 95)
    check("caisse line", CB.caisse_line(b) == "D'habitude : Coupe + Barbe · ~25 € · tous les 24 jours"
          or CB.caisse_line(b).startswith("D'habitude : Coupe + Barbe · ~25 €"))

    print("pure: rythme read with the clock")
    last = v[-1]["visit_time"]
    r = CB.rythme(b, last + dt.timedelta(days=10))
    check("10 days after: À l'heure, window after the last visit", r["key"] == "a_l_heure" and r["next_from"] > last)
    r = CB.rythme(b, last + dt.timedelta(days=36))
    check("36 days after: En retard, with the late days", r["key"] == "en_retard" and r["late_days"] == 11)
    r = CB.rythme(b, last + dt.timedelta(days=60))
    check("60 days after (> 2 × rhythm and > 45 days): Décroche", r["key"] == "decroche")
    two = CB.build(visits_every(start, 10, 2), 35.0)
    check("2 visits: Trop tôt pour savoir", CB.rythme(two, start + dt.timedelta(days=12))["key"] == "trop_tot")
    same = [{"visit_time": start + dt.timedelta(minutes=10 * i), "amount_paid": 10} for i in range(3)]
    sb = CB.build(same, 35.0)
    check("3 scans on one afternoon, joined today: Nouveau client, but no second-visit offer",
          CB.profil(sb, start, start) == "nouveau"
          and CB.suggest("t", {"id": "x"}, sb, CB.rythme(sb, start), "nouveau", start)["kind"] == "rien")
    check("3 scans on one afternoon: no rhythm yet (one day)", not CB.known(sb)
          and CB.rythme(sb, start + dt.timedelta(days=1))["key"] == "trop_tot" and CB.caisse_line(sb) == "D'habitude : ~10 €")
    check("1 visit, joined 5 days ago: Nouveau client",
          CB.profil(CB.build(visits_every(start, 1, 1), 35.0), start, start + dt.timedelta(days=5)) == "nouveau")
    check("no visit: Inscrit, jamais venu", CB.profil(CB.build([], 35.0), start, start) == "jamais")
    check("regular rhythm, on time: Habitué régulier",
          CB.profil(b, start, last + dt.timedelta(days=10)) == "regulier")

    print("pure: trend")
    gaps = [7, 7, 7, 7, 14, 14, 14]
    t, rows = start, []
    for i, g in enumerate([0] + gaps):
        t = t + dt.timedelta(days=g)
        rows.append({"visit_time": t, "amount_paid": 10, "customer_id": "x"})
    tb = CB.build(rows, 10.0)
    check("recent gaps twice the earlier ones: vient moins souvent", tb["trend"] == "baisse")
    check("« Vient moins souvent qu'avant » tag", "Vient moins souvent qu'avant" in CB.tags(tb, None))
    check("weeks wording", CB._when(21) == "toutes les 3 semaines" and CB._when(7) == "toutes les semaines"
          and CB._when(10) == "tous les 10 jours")


def main():
    pure_tests()
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import client_brain as CB
    from features import clients_page as CP
    from features import segmentation as SEG

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(UTC)
    db.tenants.insert_many([
        {"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active",
         "is_active": True, "sector": "salon",
         "branches": [{"id": "lib", "name": "LIBERTÉ", "is_main": True}, {"id": "pal", "name": "PALISSY"}]},
        {"id": "t2", "slug": "other", "name": "Other", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10})
    db.tenant_catalog.insert_one({"tenant_id": "t1", "items": [
        {"id": "i1", "name": "Coupe", "price": 18}, {"id": "i2", "name": "Barbe", "price": 10},
        {"id": "i3", "name": "Soin", "price": 15}]})
    db.users.insert_many([
        {"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
        {"email": "p@x.fr", "role": "administrateur", "tenant_id": "t1", "active": True, "branch_ids": ["pal"]},
        {"email": "s@x.fr", "role": "staff", "tenant_id": "t1", "active": True},
    ])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H = tok("o@x.fr", "business_owner")

    base = now - dt.timedelta(days=200)
    # late: every 21 days, last visit 40 days ago
    late = visits_every(now - dt.timedelta(days=40 + 21 * 5), 21, 6, items=["Coupe"], cid="late", branch="lib")
    # on time: every 21 days, last visit 5 days ago
    ontime = visits_every(now - dt.timedelta(days=5 + 21 * 5), 21, 6, items=["Coupe"], cid="ontime", branch="lib")
    # peers: take Coupe AND Soin — « Faire découvrir Soin » to « ontime »
    peers = []
    for k in range(4):
        peers += visits_every(base + dt.timedelta(days=k), 30, 3, items=["Coupe", "Soin"], cid=f"peer{k}", branch="lib")
    # gone: every 10 days, last visit 90 days ago (old rule: 2×10 and > 45 → at risk too)
    gone = visits_every(now - dt.timedelta(days=90 + 10 * 4), 10, 5, cid="gone", branch="lib")
    # once: one visit 3 days ago; never: none
    once = visits_every(now - dt.timedelta(days=3), 1, 1, cid="once", branch="pal")
    db.visits.insert_many(late + ontime + peers + gone + once)

    def cust(cid, visits, branch="lib", **kw):
        times = [v["visit_time"] for v in visits]
        return {"id": cid, "tenant_id": "t1", "name": cid.capitalize(), "barcode_id": f"FT-{cid.upper()}",
                "branch_id": branch, "visits": len(visits), "deleted_at": None,
                "created_at": (min(times) if times else now) - dt.timedelta(days=1),
                "last_visit_date": max(times) if times else None,
                "total_amount_paid": sum(v["amount_paid"] for v in visits), **kw}
    db.customers.insert_many([cust("late", late), cust("ontime", ontime), cust("gone", gone),
                              cust("once", once, "pal"), cust("never", [], "pal")]
                             + [cust(f"peer{k}", [v for v in peers if v["customer_id"] == f"peer{k}"]) for k in range(4)])

    print("old clients get their brain (tick)")
    check("before: no brain", db.customers.count_documents({"brain": {"$exists": True}}) == 0)
    # the old rule says « late » is not at risk (40 < 45 days) — and the brain agrees: En retard, not Décroche
    out = server.tick_pass()
    check("the tick fills every client", out.get("client_brain", {}).get("t1") == 9
          and db.customers.count_documents({"brain.v": CB.VERSION}) == 9)
    check("a second tick has nothing to do", server.tick_pass().get("client_brain") == {})

    print("« Clients qui décrochent » = the brain")
    rows = {c["id"]: c for c in db.customers.find({"tenant_id": "t1"}, {"_id": 0})}
    check("gone: décroche", CP.is_at_risk(rows["gone"], now))
    check("late (40 days, rhythm 21): en retard, not décroche", not CP.is_at_risk(rows["late"], now)
          and CB.rythme(rows["late"]["brain"], now)["key"] == "en_retard")
    # a stale brain falls back to the old rule
    stale = {**rows["gone"], "brain": {"v": 0}}
    check("older brain version: old rule still answers", CP.is_at_risk(stale, now))

    print("Profil client")
    r = http("GET", "/api/owner/clients/late/profil", headers=H)
    p = r.json()
    check("200", r.status_code == 200)
    check("status En retard, with late days", p["status"]["key"] == "en_retard" and p["status"]["late_days"] >= 15)
    check("habits: Coupe 6 fois sur 6", p["habits"]["items"][0]["name"] == "Coupe" and p["habits"]["items"][0]["visits"] == 6)
    check("rhythm text and confidence", "jours" in p["rhythm"]["text"] or "semaines" in p["rhythm"]["text"])
    check("next window present", p["next"] and p["next"]["from"] < p["next"]["to"])
    check("offer: relance on Coupe, with a template", p["offer"]["kind"] == "relance" and "Coupe" in p["offer"]["label"]
          and p["offer"]["template"] == "brain:late")
    check("store named (two stores)", p["store"] == "LIBERTÉ")
    o = http("GET", "/api/owner/clients/ontime/profil", headers=H).json()
    check("on time: À l'heure", o["status"]["key"] == "a_l_heure")
    check("on time: « Faire découvrir Soin » (peers take Coupe + Soin)",
          o["offer"]["kind"] == "decouverte" and "Soin" in o["offer"]["label"] and "%" in o["offer"]["why"])
    n = http("GET", "/api/owner/clients/never/profil", headers=H).json()
    check("never came: Inscrit, jamais venu + first-visit offer",
          n["profile"]["key"] == "jamais" and n["offer"]["kind"] == "premiere" and n["next"] is None)
    w = http("GET", "/api/owner/clients/once/profil", headers=H).json()
    check("one visit: Nouveau client, second-visit offer", w["profile"]["key"] == "nouveau" and w["offer"]["kind"] == "deuxieme")
    check("staff: refused", http("GET", "/api/owner/clients/late/profil", headers=tok("s@x.fr", "staff")).status_code == 403)
    check("another store's admin: refused",
          http("GET", "/api/owner/clients/late/profil",
               headers={**tok("p@x.fr", "administrateur"), "X-FidClic-Store": "pal"}).status_code in (403, 404))
    check("another account: not found",
          http("GET", "/api/owner/clients/late/profil", headers=tok("z@x.fr", "business_owner", "t2")).status_code == 404)

    print("Préparer le message")
    t = http("GET", "/api/owner/insights/templates/brain:late", headers=H).json()
    check("template: the client's words, one recipient", t["audience"]["ids"] == ["late"] and "Coupe" in t["message"]
          and len(t["title"]) <= 50 and len(t["message"]) <= 160)

    print("learned at the scan, shown to the till")
    db.customers.update_one({"id": "never"}, {"$unset": {"brain": ""}})
    s = http("POST", "/api/owner/scan", headers=H, json={"barcode_id": "FT-NEVER", "amount_paid": 21, "branch_id": "pal",
                                                          "items": [{"item_id": "i1", "qty": 1}]})
    check("scan ok", s.status_code == 200 or print(s.status_code, s.text[:300]))
    b = db.customers.find_one({"id": "never"})["brain"]
    check("the scan wrote the brain: 1 visit, Coupe", b["visits_n"] == 1 and b["top_item"] == "Coupe")
    from features import scan_page as SP
    from models import TokenData
    c = SP.card(barcode="FT-LATE", token_data=TokenData(sub="o@x.fr", role="business_owner", tenant_id="t1"))
    check("till line for a regular", (c["customer"]["habit"] or "").startswith("D'habitude : Coupe · ~25 €"))
    c = SP.card(barcode="FT-NEVER", token_data=TokenData(sub="o@x.fr", role="business_owner", tenant_id="t1"))
    check("one visit: nothing worth saying yet (no rhythm, one item, one amount)", c["customer"]["habit"] is None)

    print("Segmentation")
    prev = lambda rules: http("POST", "/api/owner/segmentation/preview", headers=H, json={"rules": rules}).json()  # noqa: E731
    ids = lambda rules: sorted(c["id"] for c in SEG.evaluate("t1", rules))  # noqa: E731
    # the peers (3 visits, silent 140 days) are late too: « Décroche » asks 4 visits, as « Clients qui décrochent » always did
    check("Rythme = En retard → late + the 3-visit peers", prev([{"field": "rythme", "op": "eq", "value": "en_retard"}])["count"] == 5
          and "late" in ids([{"field": "rythme", "op": "eq", "value": "en_retard"}]))
    check("Rythme = Décroche → gone", prev([{"field": "rythme", "op": "eq", "value": "decroche"}])["count"] == 1)
    check("Produit préféré Coupe", prev([{"field": "produit", "op": "eq", "value": "Coupe"}])["count"] >= 6)
    check("Produit jamais pris Soin (with a brain)", prev([{"field": "produit", "op": "never", "value": "Soin"}])["count"] >= 2)
    check("Prochaine visite dans moins de 30 jours → ontime, never the overdue",
          ids([{"field": "next_visit", "op": "lt", "value": 30}]) == ["ontime"])
    page = http("GET", "/api/owner/segmentation/page", headers=H).json()
    f = {x["key"]: x for x in page["fields"]}
    check("builder offers the shop's products", [c["key"] for c in f["produit"]["choices"]] == ["Barbe", "Coupe", "Soin"])
    check("seven FidClic IA fields", all(k in f for k in ("rythme", "next_visit", "produit", "jour", "creneau", "tendance", "profil")))
    check("summary sentence", SEG.describe([{"field": "produit", "op": "never", "value": "Soin"}])[0]["text"]
          == "Produit / service : jamais pris : Soin")
    saved = http("POST", "/api/owner/segmentation/segments", headers=H,
                 json={"name": "En retard", "rules": [{"field": "rythme", "op": "eq", "value": "en_retard"}]})
    check("a FidClic IA segment can be saved", saved.status_code in (200, 201))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
