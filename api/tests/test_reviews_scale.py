"""
Reviews — one collection, one scale, one shape.

`reviews` is written by two endpoints and read by four things (the owner's
list and its filters, /api/owner/reviews/stats, the Analyses page's "Avis
clients" tab, and the admin KPIs). Every one of them assumes a rating out of
TEN — the Review model says so in its own docstring.

`POST /api/customer/reviews` used to cap the rating at 5 and write no
sentiment and no topics, into that same collection. A 5 from it was
indistinguishable from a mediocre 5/10, and its rows could not be found by
any sentiment or topic filter.

This checks the two writers now agree, and that what reads them still adds up.
Run: /usr/local/bin/python3 api/tests/test_reviews_scale.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-for-reviews-scale")

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
    import features.reviews as R

    db = server.db
    R._db = db
    now = dt.datetime.now(dt.timezone.utc)

    class TD:
        email, role, tenant_id = "owner@shop.fr", "business_owner", "t1"

    db.tenants.insert_one({"id": "t1", "slug": "petit-cafe", "name": "Le Petit Café"})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Marie Dupont",
                             "barcode_id": "FT-MARIE01", "tier": "gold", "visits": 9})

    # ---- the scale --------------------------------------------------------------------------
    print("\nLa même échelle")
    ok = R.submit_review(R.ReviewSubmit(tenant_slug="petit-cafe", barcode_id="FT-MARIE01",
                                        rating=9, text="Excellent café, service rapide",
                                        visit_id="v1"))
    check("a 9/10 is accepted", ok["submitted"] is True)
    row = db.reviews.find_one({"id": ok["review_id"]})
    check("and stored as 9, not squeezed into five", row["rating"] == 9)

    for bad in (0, 11, -1):
        try:
            R.ReviewSubmit(tenant_slug="petit-cafe", rating=bad)
            refused = False
        except Exception:
            refused = True
        check(f"{bad} is outside the scale and refused", refused)
    check("10 is inside it", R.ReviewSubmit(tenant_slug="petit-cafe", rating=10).rating == 10)

    check("the other writer uses the same scale",
          "Rating must be between 1 and 10" in
          open(os.path.join(os.path.dirname(__file__), "..", "server.py")).read())

    # ---- the same shape ---------------------------------------------------------------------
    print("\nLa même forme")
    check("sentiment is filled in, so the owner's filter can find it",
          row.get("sentiment") in ("positive", "neutral", "negative"))
    check("topics are filled in too", isinstance(row.get("topics"), list))
    check("and the language, like the other path", "language" in row)

    ref = {"rating", "text", "sentiment", "sentiment_score", "topics",
           "topic_scores", "language", "created_at"}
    check("every field the readers need is present", ref <= set(row))

    found = server.list_owner_reviews(token_data=TD(), sentiment=row["sentiment"], limit=50)
    check("a row written here is findable by sentiment",
          any(x["id"] == row["id"] for x in found["reviews"]))
    if row["topics"]:
        by_topic = server.list_owner_reviews(token_data=TD(), topic=row["topics"][0], limit=50)
        check("and by topic", any(x["id"] == row["id"] for x in by_topic["reviews"]))
    else:
        check("and by topic (no topic detected in this text, skipped)", True)

    # ---- the stats --------------------------------------------------------------------------
    print("\nLes statistiques")
    db.reviews.delete_many({})
    for i, n in enumerate([2, 5, 6, 9, 10]):
        db.reviews.insert_one({"id": f"r{i}", "tenant_id": "t1", "rating": n,
                               "text": "", "created_at": now - dt.timedelta(days=1)})
    st = R.review_stats(token_data=TD(), days=30)
    check("all five are counted", st["count"] == 5)
    check("the average is on the same scale as the data", st["avg_rating"] == 6.4)
    check("there is a bucket for every point of the scale",
          sorted(st["distribution"]) == list(range(1, 11)))
    check("each bucket holds what it should",
          st["distribution"][10] == 1 and st["distribution"][2] == 1
          and st["distribution"][7] == 0)
    check("a 10/10 is no longer an unlabelled key grown on the fly",
          10 in st["distribution"] and st["distribution"][10] == 1)
    check("'needs a reply' is the bottom half of ten, not the bottom three",
          st["needs_response"] == 2 and R.NEEDS_RESPONSE_AT == 5)

    db.reviews.update_one({"id": "r0"}, {"$set": {"owner_response": "Merci, on corrige."}})
    check("an answered review stops asking for a reply",
          R.review_stats(token_data=TD(), days=30)["needs_response"] == 1)

    db.reviews.delete_many({})
    empty = R.review_stats(token_data=TD(), days=30)
    check("a shop with no reviews reads nothing, not zero stars",
          empty["count"] == 0 and empty["avg_rating"] is None)

    # ---- what reads them --------------------------------------------------------------------
    print("\nCe qui les lit")
    import features.analyses as A
    A._db = db
    db.visits.insert_one({"tenant_id": "t1", "customer_id": "c1", "amount_paid": 5.0,
                          "visit_time": now - dt.timedelta(days=1)})
    for i, n in enumerate([9, 10]):
        db.reviews.insert_one({"id": f"a{i}", "tenant_id": "t1", "rating": n, "text": "",
                               "created_at": now - dt.timedelta(days=1)})
    avis = A.analyses(tab="avis", days=30, token_data=TD())["data"]
    avg = next(s for s in avis["strip"] if s["key"] == "avg")
    check("the Analyses page halves the ten exactly once",
          avg["value"] == 4.8 and avg["unit"] == "/5")
    check("and it never shows more than five stars", avg["value"] <= 5)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
