"""
Segmentation — the rules, what a segment is worth, and the builder.

Boots the real server.py on mongomock. The arithmetic behind "Potentiel de CA"
is checked against figures derived from the fixture rather than hand-computed,
because that estimate is the one number on the page a merchant cannot verify
for themselves.

Run: /usr/local/bin/python3 api/tests/test_segmentation.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-for-segmentation")

passed = failed = 0


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
    import features.segmentation as S

    db = server.db
    S._db = db
    now = dt.datetime.now(dt.timezone.utc)

    class TD:
        email, role, tenant_id = "owner@shop.fr", "business_owner", "t1"

    class Rival:
        email, role, tenant_id = "o@rival.fr", "business_owner", "t2"

    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café", "monthly_revenue_goal": 2500.0,
                           "latitude": 47.3941, "longitude": 0.6848})
    db.tenants.insert_one({"id": "t2", "name": "Rival"})

    # id, visits, spend, last visit (days), joined (days), tier
    CAST = [
        ("vip1", 20, 1200.0, 2, 400, "vip"),        # basket 60, seen this month
        ("vip2", 15,  900.0, 5, 380, "vip"),        # basket 60
        ("reg1",  8,  160.0, 20, 200, "gold"),      # basket 20
        ("reg2",  6,   90.0, 45, 150, "silver"),    # basket 15, cooling
        ("old1",  4,  100.0, 120, 300, "bronze"),   # basket 25, dormant
        ("old2",  2,   30.0, 200, 320, "bronze"),   # basket 15, dormant
        ("new1",  1,   18.0, 10, 12, "bronze"),     # basket 18, new
        ("zero",  0,    0.0, None, 5, "bronze"),    # never bought
    ]
    for cid, visits, spend, last, joined, tier in CAST:
        doc = {"id": cid, "tenant_id": "t1", "name": f"Client {cid}", "visits": visits,
               "total_amount_paid": spend, "tier": tier, "barcode_id": f"FT-{cid.upper()}",
               "created_at": now - dt.timedelta(days=joined), "postal_code": "37000"}
        if last is not None:
            doc["last_visit_date"] = now - dt.timedelta(days=last)
        db.customers.insert_one(doc)
    db.customers.insert_one({"id": "x1", "tenant_id": "t2", "name": "Rival client",
                             "visits": 99, "total_amount_paid": 9999.0, "tier": "vip",
                             "last_visit_date": now, "created_at": now})

    # Twelve weeks of takings, so the badge has a week to measure against.
    for i in range(84):
        db.visits.insert_one({"tenant_id": "t1", "customer_id": "vip1", "amount_paid": 10.0,
                              "visit_time": now - dt.timedelta(days=i)})

    ids = lambda rules: {c["id"] for c in S.evaluate("t1", S._clean_rules(rules), at=now)}

    # ---- the six criteria of the design ------------------------------------------------------
    print("\nLes six critères")
    check("the builder offers exactly the six of the mockup",
          [f["key"] for f in S.FIELDS] ==
          ["last_visit", "visits", "spend", "distance", "tier", "joined"])
    check("and each names itself as the design does",
          [f["label"] for f in S.FIELDS] ==
          ["Dernière visite", "Nombre d'achats", "Montant dépensé",
           "Distance du magasin", "Statut fidélité", "Date d'inscription"])
    check("a distance is 'inférieure', a montant is 'inférieur'",
          S.FIELD_BY_KEY["distance"]["ops"][0]["label"] == "est inférieure à"
          and S.FIELD_BY_KEY["spend"]["ops"][0]["label"] == "est inférieur à")

    check("dernière visite : il y a plus de 30 jours",
          ids([{"field": "last_visit", "op": "gt", "value": 30}]) == {"reg2", "old1", "old2", "zero"})
    check("a client who never came counts as 'plus de 30 jours'",
          "zero" in ids([{"field": "last_visit", "op": "gt", "value": 30}]))
    check("but never as 'moins de 30 jours'",
          "zero" not in ids([{"field": "last_visit", "op": "lt", "value": 30}]))

    check("nombre d'achats : égal à 0", ids([{"field": "visits", "op": "eq", "value": 0}]) == {"zero"})
    check("nombre d'achats : supérieur à 5",
          ids([{"field": "visits", "op": "gt", "value": 5}]) == {"vip1", "vip2", "reg1", "reg2"})

    check("montant dépensé is the AVERAGE basket, as the mockup words it",
          ids([{"field": "spend", "op": "gt", "value": 20}]) == {"vip1", "vip2", "old1"})
    check("someone who spent nothing is below any threshold",
          "zero" in ids([{"field": "spend", "op": "lt", "value": 20}]))

    check("statut fidélité : VIP", ids([{"field": "tier", "op": "eq", "value": "vip"}]) == {"vip1", "vip2"})
    check("'Non membre' means nobody has ever bought, not a tier name",
          ids([{"field": "tier", "op": "eq", "value": "non_membre"}]) == {"zero"})

    check("date d'inscription : il y a moins de 30 jours",
          ids([{"field": "joined", "op": "lt", "value": 30}]) == {"new1", "zero"})

    check("several conditions are ANDed, never ORed",
          ids([{"field": "visits", "op": "gt", "value": 5},
               {"field": "last_visit", "op": "lt", "value": 30}]) == {"vip1", "vip2", "reg1"})
    check("no condition at all is everybody, not nobody",
          ids([]) == {c[0] for c in CAST})
    check("and never another shop's clients", "x1" not in ids([]))

    # ---- rules that cannot be trusted are dropped, not half-applied --------------------------
    print("\nCe que le constructeur refuse")
    check("an unknown field is dropped", S._clean_rules([{"field": "astro", "op": "gt", "value": 1}]) == [])
    check("an operator the field does not offer is dropped",
          S._clean_rules([{"field": "tier", "op": "gt", "value": "vip"}]) == [])
    check("a tier nobody has is dropped",
          S._clean_rules([{"field": "tier", "op": "eq", "value": "platine"}]) == [])
    check("a value that is not a number is dropped",
          S._clean_rules([{"field": "visits", "op": "gt", "value": "beaucoup"}]) == [])
    check("a negative threshold is dropped",
          S._clean_rules([{"field": "visits", "op": "gt", "value": -3}]) == [])
    check("good rules beside a bad one survive",
          len(S._clean_rules([{"field": "visits", "op": "gt", "value": 5},
                              {"field": "astro", "op": "gt", "value": 1}])) == 1)

    # ---- the summary panel --------------------------------------------------------------------
    print("\nLe résumé des critères")
    lines = [x["text"] for x in S.describe(S._clean_rules([
        {"field": "last_visit", "op": "gt", "value": 30},
        {"field": "visits", "op": "eq", "value": 0},
        {"field": "spend", "op": "lt", "value": 20},
        {"field": "distance", "op": "lt", "value": 5},
        {"field": "tier", "op": "eq", "value": "non_membre"},
        {"field": "joined", "op": "gt", "value": 90},
    ]))]
    for want in ("Dernière visite : il y a plus de 30 jours",
                 "Nombre d'achats : égal à 0",
                 "Montant dépensé : inférieur à 20 €",
                 "Distance du magasin : moins de 5 km",
                 "Statut fidélité : Non membre",
                 "Date d'inscription : il y a plus de 90 jours"):
        check(f"« {want} »", want in lines)

    # ---- potentiel de CA ----------------------------------------------------------------------
    print("\nPotentiel de CA")
    baskets = {c[0]: (c[2] / c[1] if c[1] else None) for c in CAST}
    shop_avg = sum(b for b in baskets.values() if b is not None) / len([b for b in baskets.values() if b is not None])

    def expect(cids):
        """The user's formula, applied to the fixture rather than to memory."""
        total = 0.0
        for cid in cids:
            row = next(c for c in CAST if c[0] == cid)
            basket = baskets[cid] if baskets[cid] is not None else shop_avg
            days = row[3]
            p = 0.08 if days is None else (0.30 if days < 30 else 0.18 if days < 60
                                           else 0.12 if days < 90 else 0.08)
            total += basket * p
        return round(total + 1e-9, 2)

    vips = S.evaluate("t1", S._clean_rules([{"field": "tier", "op": "eq", "value": "vip"}]), at=now)
    pot = S.potential(vips, shop_avg, now)
    check("a segment's potential is its own baskets times its own recency",
          pot["amount"] == expect(["vip1", "vip2"]))
    check("it reports the average basket it used", pot["avg_basket"] == 60.0)
    check("and the average conversion it assumed", pot["avg_conversion"] == 30)

    dormant = S.evaluate("t1", S._clean_rules([{"field": "last_visit", "op": "gt", "value": 90}]), at=now)
    check("a dormant segment is valued at the dormant rate",
          S.potential(dormant, shop_avg, now)["amount"] == expect([c["id"] for c in dormant]))
    check("and that segment is the two dormant clients plus the one who never came",
          {c["id"] for c in dormant} == {"old1", "old2", "zero"})
    check("a client who never bought is valued at the shop's average basket",
          S.potential([next(c for c in db.customers.find({"id": "zero"}))], shop_avg, now)["amount"]
          == round(shop_avg * 0.08 + 1e-9, 2))
    check("an empty segment is worth nothing, and does not divide by zero",
          S.potential([], shop_avg, now) == {"amount": 0.0, "clients": 0,
                                             "avg_basket": 0.0, "avg_conversion": 0})

    weekly = S._weekly_revenue("t1", now)
    check("a week of revenue is twelve weeks divided by twelve", weekly == 70.0)
    for share, want in ((0.35, "Très élevé"), (0.20, "Élevé"), (0.08, "Moyen"), (0.01, "Faible")):
        check(f"{round(share * 100)} % of a week reads « {want} »",
              S._badge(weekly * share, weekly)["label"] == want)
    check("the badge says what it was measured against",
          "semaine" in S._badge(weekly * 0.2, weekly)["basis"])
    check("a shop with no week yet ranks its segments against each other",
          S._badge(50.0, 0.0, [10.0, 20.0, 30.0, 40.0, 50.0])["label"] == "Très élevé"
          and "autres segments" in S._badge(50.0, 0.0, [10.0, 20.0, 30.0, 40.0, 50.0])["basis"])
    check("and a shop with neither says so rather than claiming a level",
          S._badge(50.0, 0.0, [])["basis"] == "pas encore assez d'historique")

    # ---- the page ------------------------------------------------------------------------------
    print("\nLa page")
    p = S.page(token_data=TD())
    strip = {s["key"]: s for s in p["strip"]}
    check("the four figures of the design are there", len(p["strip"]) == 4)
    check("'Clients total' counts this shop only", strip["clients"]["value"] == len(CAST))
    check("'Segments actifs' counts the ones that hold somebody",
          strip["segments"]["value"] == len([s for s in p["segments"] if s["count"] > 0]))
    check("'Meilleur segment' is the one worth the most",
          strip["best"]["text"] == max(p["segments"], key=lambda s: s["potential"]["amount"])["name"])

    check("the five models of the design are offered", len(p["models"]) == 5)
    check("and each carries a live count of real clients",
          all("count" in m for m in p["models"])
          and next(m for m in p["models"] if m["key"] == "inactifs")["count"] ==
          len(ids([{"field": "last_visit", "op": "gt", "value": 30}])))

    by_name = {s["name"]: s for s in p["segments"]}
    row = by_name["Clients inactifs"]
    check("every row has the columns the design shows",
          all(k in row for k in ("name", "description", "count", "share", "potential", "last_used_at")))
    check("the share is of this shop's base", row["share"] == round(row["count"] / len(CAST) * 100))
    check("and the potential carries its badge", row["potential"]["badge"]["label"] in
          ("Faible", "Moyen", "Élevé", "Très élevé"))
    check("the page prints how the estimate was reached",
          "panier moyen" in p["potential_note"] and "30 %" in p["potential_note"])

    check("the tips point at segments that really exist",
          all(t["segment_id"] in {s["id"] for s in p["segments"]} for t in p["tips"]))
    check("there are three of them, as the design shows", len(p["tips"]) == 3)

    check("the goal is the one the Tableau de bord tracks",
          p["goal"]["target"] == 2500.0 and p["goal"]["is_set"] is True)
    check("and it counts this month's takings against it", p["goal"]["reached"] > 0)

    empty = S.page(token_data=Rival())
    check("a shop with one client still renders", empty["total_clients"] == 1)

    # ---- the builder ---------------------------------------------------------------------------
    print("\nLe constructeur")
    pv = S.preview(S.Preview(rules=[{"field": "last_visit", "op": "gt", "value": 30},
                                    {"field": "visits", "op": "eq", "value": 0}]),
                   token_data=TD())
    check("the preview counts what the rules match", pv["count"] == 1 and pv["total"] == len(CAST))
    check("and says what share of the base that is", pv["share"] == round(1 / len(CAST) * 100))
    check("it echoes the summary the panel shows", len(pv["summary"]) == 2)
    check("a rule it had to drop is reported, not hidden",
          S.preview(S.Preview(rules=[{"field": "astro", "op": "gt", "value": 1}]),
                    token_data=TD())["dropped"] == 1)
    check("no rules previews the whole base",
          S.preview(S.Preview(rules=[]), token_data=TD())["count"] == len(CAST))

    made = S.create(S.SegmentIn(name="Clients à réactiver",
                                rules=[{"field": "last_visit", "op": "gt", "value": 30},
                                       {"field": "visits", "op": "eq", "value": 0}]),
                    token_data=TD())
    check("a segment is created with its count", made["count"] == 1)
    check("and appears on the page", "Clients à réactiver" in {s["name"] for s in S.page(token_data=TD())["segments"]})
    try:
        S.create(S.SegmentIn(name="Clients à réactiver", rules=[]), token_data=TD())
        dup = False
    except Exception as exc:
        dup = getattr(exc, "status_code", None) == 409
    check("the same name twice is refused", dup)
    try:
        S.create(S.SegmentIn(name="   ", rules=[]), token_data=TD())
        unnamed = False
    except Exception as exc:
        unnamed = getattr(exc, "status_code", None) == 400
    check("a segment with no name is refused", unnamed)

    from_model = S.create(S.SegmentIn(name="", model="gros_paniers"), token_data=TD())
    check("'Utiliser ce segment' creates a real, editable segment",
          from_model["name"] == "Gros paniers" and from_model["rules"])
    check("and it counts the same as the model did",
          from_model["count"] == next(m for m in p["models"] if m["key"] == "gros_paniers")["count"])

    S.update(made["id"],
             S.SegmentIn(name="Réactivation", rules=[{"field": "visits", "op": "eq", "value": 0}]),
             token_data=TD())
    fresh = db.saved_segments.find_one({"id": made["id"]})
    check("a segment can be renamed and re-ruled", fresh["name"] == "Réactivation"
          and len(fresh["rules"]) == 1)

    mem = S.members(made["id"], token_data=TD())
    check("its members can be listed", mem["ids"] == ["zero"] and mem["count"] == 1)
    check("and reading it stamps when it was last used",
          db.saved_segments.find_one({"id": made["id"]})["last_used_at"] is not None)
    model_mem = S.members("model:inactifs", token_data=TD())
    check("a model can be read the same way",
          set(model_mem["ids"]) == ids([{"field": "last_visit", "op": "gt", "value": 30}]))

    S.remove(made["id"], token_data=TD())
    check("and deleted", db.saved_segments.find_one({"id": made["id"]}) is None)
    try:
        S.remove("nope", token_data=TD())
        gone = False
    except Exception as exc:
        gone = getattr(exc, "status_code", None) == 404
    check("deleting something that is not there is a 404", gone)

    # ---- wiring ---------------------------------------------------------------------------------
    print("\nLe câblage")
    paths = {r.path for r in server.app.routes if hasattr(r, "methods")}
    for want in ("/api/owner/segmentation/page", "/api/owner/segmentation/preview",
                 "/api/owner/segmentation/segments",
                 "/api/owner/segmentation/segments/{segment_id}",
                 "/api/owner/segmentation/segments/{segment_id}/clients"):
        check(f"{want} is mounted", want in paths)
    check("the module is registered with the loader",
          "features.segmentation" in open(os.path.join(
              os.path.dirname(__file__), "..", "features", "_loader.py")).read())

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
