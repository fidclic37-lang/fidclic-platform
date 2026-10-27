#!/usr/bin/env python3
"""
Seed 20 realistic French test customers into the demo tenant (Café Lumière).

USE CASE
    You want to test SMS / analytics / churn / heatmap with real French names
    and phone numbers — so your phone actually rings when you trigger a
    birthday auto-message, and the analytics charts show meaningful data.

USAGE
    # 1. Get your MongoDB URI from Vercel env vars (or your local dev setup)
    export MONGODB_URI="mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/fidelitour_db"

    # 2. Run with comma-separated phone numbers (E.164 format)
    python scripts/seed_test_customers.py \\
        --phones=+33612345678,+33687654321,+33645678912,+33623456789

    # 3. (Optional) Clear all previous test customers first
    python scripts/seed_test_customers.py --wipe-first --phones=+33612345678,...

WHAT GETS CREATED
    - 20 customers in tenant `tenant-1` (Café Lumière) with IDs `test-00`..`test-19`
    - Each gets a realistic French name, a postal code, a birthday, a tier
      (bronze/silver/gold/vip based on visits)
    - The first N customers (where N = number of phones you supply) get YOUR
      real phone numbers; the rest get placeholder French mobile numbers
    - A visit history is generated so the analytics, churn predictions, and
      heatmap have real data to work with
    - First customer's birthday is set to TODAY so you can immediately test
      the birthday auto-message → real SMS to your phone

TIPS
    - Make sure Twilio is wired (`TWILIO_*` env vars on Render) before relying
      on real SMS delivery.
    - Verify the recipient phone in your Twilio console first if you're on
      the free trial — Twilio refuses to send to unverified numbers in trial.

REQUIRES
    pip install pymongo
"""
from __future__ import annotations
import argparse
import os
import random
import re
import sys
import uuid
from datetime import datetime, timezone, timedelta

try:
    import pymongo
except ImportError:
    print("ERROR: pymongo not installed.  Run:  pip install pymongo", file=sys.stderr)
    sys.exit(1)


REAL_FRENCH_NAMES = [
    "Sophie Dupont",     "Pierre Martin",   "Marie Bernard",   "Jean Petit",
    "Camille Robert",    "Lucas Richard",   "Léa Durand",      "Hugo Moreau",
    "Emma Laurent",      "Théo Simon",      "Chloé Michel",    "Antoine Lefebvre",
    "Manon Garcia",      "Nathan Roux",     "Alice Vincent",   "Maxime Fournier",
    "Juliette Girard",   "Tom Bonnet",      "Inès Dubois",     "Léo Mercier",
]

POSTAL_CODES = [
    "75001", "75002", "75003", "75004", "75005", "75006", "75007", "75008",
    "75011", "75014", "75015", "75016", "75017", "75018",
    "92100", "93100", "94000", "69001", "69002", "13001",
]


def normalize_phone(p: str) -> str:
    p = re.sub(r"[\s\-\.\(\)]", "", str(p))
    if p.startswith("+"):
        return p
    if p.startswith("00"):
        return "+" + p[2:]
    if p.startswith("0") and len(p) == 10:
        return "+33" + p[1:]
    return p


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed real-data test customers into tenant-1.")
    parser.add_argument("--phones", default="",
                        help="Comma-separated phone numbers (E.164 or French local). "
                             "First N customers get these; rest get placeholders.")
    parser.add_argument("--mongo-uri", default=os.environ.get("MONGODB_URI", ""),
                        help="MongoDB connection string (defaults to MONGODB_URI env var).")
    parser.add_argument("--tenant-id", default="tenant-1",
                        help="Target tenant ID (default: tenant-1, i.e. Café Lumière).")
    parser.add_argument("--wipe-first", action="store_true",
                        help="Delete all previous test-* customers + their visits before seeding.")
    args = parser.parse_args()

    if not args.mongo_uri:
        print("ERROR: MONGODB_URI is not set. Pass --mongo-uri or set the env var.", file=sys.stderr)
        sys.exit(2)

    real_phones = [normalize_phone(p) for p in args.phones.split(",") if p.strip()]
    if real_phones:
        print(f"Will assign these real phones to the first {len(real_phones)} customers:")
        for p in real_phones:
            print(f"   {p}")
    else:
        print("No real phones provided — all customers will get placeholder numbers.")

    client = pymongo.MongoClient(args.mongo_uri, serverSelectionTimeoutMS=8000)
    db = client.fidelitour_db

    tenant = db.tenants.find_one({"id": args.tenant_id})
    if not tenant:
        print(f"ERROR: Tenant '{args.tenant_id}' not found in fidelitour_db.tenants.",
              file=sys.stderr)
        print("       Make sure the backend has run its initial seed at least once.",
              file=sys.stderr)
        sys.exit(3)
    print(f"Target tenant: {tenant.get('name')}  (slug: {tenant.get('slug')})")

    if args.wipe_first:
        d1 = db.customers.delete_many({"tenant_id": args.tenant_id, "id": {"$regex": "^test-"}})
        d2 = db.visits.delete_many({"tenant_id": args.tenant_id, "customer_id": {"$regex": "^test-"}})
        print(f"Wiped {d1.deleted_count} test customers and {d2.deleted_count} visits.")

    now = datetime.now(timezone.utc)
    today_mmdd = now.strftime("%m-%d")

    customers = []
    for i, name in enumerate(REAL_FRENCH_NAMES):
        # Vary visit counts so we get every tier represented
        visits = (
            random.randint(40, 70) if i % 5 == 0 else      # vip cohort
            random.randint(20, 39) if i % 5 == 1 else      # gold cohort
            random.randint(10, 19) if i % 5 == 2 else      # silver cohort
            random.randint(0, 9)                           # bronze cohort
        )
        if visits >= 40:
            tier = "vip"
        elif visits >= 20:
            tier = "gold"
        elif visits >= 10:
            tier = "silver"
        else:
            tier = "bronze"

        # First customer's birthday = today (so the birthday auto-message
        # immediately has a target). Others get random birthdays.
        if i == 0:
            birthday = today_mmdd
        else:
            birthday = f"{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"

        # Real phone for the first N, placeholder for the rest
        if i < len(real_phones):
            phone = real_phones[i]
        else:
            phone = f"+336{random.randint(10000000, 99999999)}"

        last_visit = now - timedelta(days=random.randint(0, 60)) if visits > 0 else None
        joined = now - timedelta(days=random.randint(30, 365))

        customers.append({
            "id": f"test-{i:02d}",
            "tenant_id": args.tenant_id,
            "barcode_id": f"FT-TEST-{i:04d}",
            "name": name,
            "email": f"{name.lower().replace(' ', '.')}+test@example.com",
            "phone": phone,
            "postal_code": random.choice(POSTAL_CODES),
            "birthday": birthday,
            "points": visits * 10,
            "visits": visits,
            "total_amount_paid": round(visits * random.uniform(8, 18), 2),
            "tier": tier,
            "is_big_spender": visits >= 30,
            "pass_issued": visits >= 3,
            "last_visit_date": last_visit,
            "created_at": joined,
        })

    db.customers.insert_many(customers)

    # Generate a visit history so analytics, churn, heatmap have real data
    visits_docs = []
    for c in customers:
        for _ in range(c["visits"]):
            t = now - timedelta(days=random.randint(0, 90))
            t = t.replace(
                hour=random.choice([8, 9, 10, 12, 12, 12, 13, 13, 13, 14, 17, 18]),
                minute=random.randint(0, 59),
            )
            visits_docs.append({
                "id": str(uuid.uuid4()),
                "tenant_id": args.tenant_id,
                "customer_id": c["id"],
                "points_awarded": 10,
                "amount_paid": round(random.uniform(5, 25), 2),
                "visit_time": t,
                "created_at": t,
            })
    if visits_docs:
        db.visits.insert_many(visits_docs)

    # ---- Summary ----
    print()
    print("✓ Seed complete.")
    print(f"   Customers created: {len(customers)}")
    print(f"   Visits generated:  {len(visits_docs)}")
    print()
    print("Birthday-today customer (use this to test SMS):")
    print(f"   Name:     {customers[0]['name']}")
    print(f"   Phone:    {customers[0]['phone']}")
    print(f"   Birthday: {customers[0]['birthday']}  (today)")
    print()
    print("Next steps:")
    print("   1. Log in as the Café Lumière owner (local seed account)")
    print("   2. Settings → 'Automatic messages' → 'Run birthdays now'")
    print("   3. Your real phone should receive an SMS within seconds.")
    print()


if __name__ == "__main__":
    main()
