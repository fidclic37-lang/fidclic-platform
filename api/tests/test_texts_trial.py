"""
Text fixes — QA 2026-10-08:
  UX06  the trial banner and its plan picker were in English
  UX07  the banner said 26 days left, the Abonnement page 27; the scanner
        showed « build 2026-05-07d · jsQR camera »
  F08   in Arabic the business « ok » was translated (« حسنا »)

Run: cd api && /usr/local/bin/python3 tests/test_texts_trial.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-texts")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    from features import invoices as INV
    from zoneinfo import ZoneInfo
    paris = ZoneInfo("Europe/Paris")
    db = server.db
    now = dt.datetime.now(dt.timezone.utc)
    ends = now + dt.timedelta(days=26, hours=20)            # 26.8 days away
    db.tenants.insert_one({"id": "t1", "name": "ok", "plan": "vip", "subscription_status": "trialing", "trial_ends_at": ends})
    want = (ends.astimezone(paris).date() - now.astimezone(paris).date()).days

    print("\nLes jours d'essai (UX07)")
    st = server._compute_trial_state(db.tenants.find_one({"id": "t1"}))
    check(f"the banner counts calendar days in France ({st['days_left']} = {want}), not floored hours (26)",
          st["days_left"] == want and want >= 26)

    class T:
        email, role, tenant_id = "o@x.fr", "business_owner", "t1"
    ov = INV.billing_overview(token_data=T())
    check(f"the Abonnement page says the same ({ov.get('days_left')})", ov.get("days_left") == st["days_left"])
    db.tenants.update_one({"id": "t1"}, {"$set": {"trial_ends_at": now + dt.timedelta(hours=3)}})
    st = server._compute_trial_state(db.tenants.find_one({"id": "t1"}))
    same_day = (now + dt.timedelta(hours=3)).astimezone(paris).date() == now.astimezone(paris).date()
    check("3 hours left the same day: 0 days, still in trial", (st["days_left"] == 0) == same_day and st["is_in_trial"])
    db.tenants.update_one({"id": "t1"}, {"$set": {"trial_ends_at": now - dt.timedelta(hours=1)}})
    st = server._compute_trial_state(db.tenants.find_one({"id": "t1"}))
    check("ended an hour ago: expired, never « 0 days left »", st["is_expired"] and st["days_left"] <= 0)
    check("the plans carry their names, not « silver / gold / vip »",
          all(p.get("label") and p["label"] != p["plan"] for p in st["available_plans"] if p["plan"] in ("silver", "gold", "vip")))

    print("\nLe bandeau en français (UX06)")
    banner = open(os.path.join(ROOT, "src", "components", "BillingBanner.jsx")).read()
    for english in ("left in your free trial", "Free trial ended", "Pick a plan", "View plans", "Unlock now",
                    "Up to ", "Geolocation campaigns", "Test/staging", "/mo<", "Current plan"):
        check(f"no « {english} »", english not in banner)
    check("prices are HT per month", "HT / mois" in banner)

    print("\nScanner (UX07)")
    scan = open(os.path.join(ROOT, "src", "pages", "ScanPage.jsx")).read()
    check("no « build … jsQR camera » line", "jsQR camera" not in scan and "build 2026-05-07" not in scan)

    print("\nLes noms ne se traduisent pas (F08)")
    tr = open(os.path.join(ROOT, "src", "lib", "translator.js")).read()
    lay = open(os.path.join(ROOT, "src", "pages", "DashboardLayout.jsx")).read()
    check("the translator skips protected names", "PROTECTED.has(trimmed.toLowerCase())" in tr and "export function protectNames" in tr)
    check("the layout protects the business, its establishments and the person", "protectNames([t.name" in lay and "myBranches" in lay)
    for page, mark in (("ClientsPage.jsx", "{r.name}"), ("HistoryPage.jsx", "{r.customer_name}"), ("CataloguePage.jsx", "{p.name}")):
        s = open(os.path.join(ROOT, "src", "pages", page)).read()
        check(f"{page}: the name cell is marked translate=\"no\"", any('translate="no"' in l and mark in l for l in s.splitlines()))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
