"""
Tests — Super admin › remise à zéro (features/platform_reset.py).
Run:  cd api && python3 tests/test_platform_reset.py
"""
import sys, os, gzip, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import mongomock

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.pop("MONGODB_URI", None)
_patch = mongomock.patch(servers=(("localhost", 27017),))
_patch.start()
import server as S                       # noqa: E402
import features.platform_reset as PR     # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}{('  → ' + str(extra)) if extra and not cond else ''}")


def expect(name, code, fn):
    try:
        fn()
        check(name, False, f"no error (expected {code})")
    except Exception as e:
        check(name, getattr(e, "status_code", None) == code, e)


async def body_of(resp):
    if not hasattr(resp, "body_iterator"):          # sent in one piece since 2026-10-15
        return resp.body
    out = b""
    async for chunk in resp.body_iterator:
        out += chunk if isinstance(chunk, bytes) else chunk.encode()
    return out


db = S.db
PR.init(db)
for n in db.list_collection_names():
    db[n].delete_many({})
now = datetime.now(timezone.utc)
db.users.insert_many([
    {"email": "boss@fidclic.com", "role": "super_admin", "tenant_id": None},
    {"email": "admin@fidelitour.com", "role": "super_admin"},
    {"email": "demo.admin@fidelitour.com", "role": "super_admin"},
    {"email": "owner@cafelumiere.fr", "role": "business_owner", "tenant_id": "tenant-1"},
    {"email": "sales@fidclic.com", "role": "commercial"},
])
db.tenants.insert_many([{"id": "tenant-1", "name": "Café Lumière"}, {"id": "t-real", "name": "Royal Trim"}])
db.user_sessions.insert_many([{"sid": "s-boss", "email": "boss@fidclic.com"}, {"sid": "s-owner", "email": "owner@cafelumiere.fr"}])
db.customers.insert_many([{"id": f"c{i}", "tenant_id": "tenant-1", "barcode_id": f"FT-{i}", "created_at": now} for i in range(5)])
db.visits.insert_many([{"id": f"v{i}", "tenant_id": "tenant-1", "customer_id": "c1", "visit_time": now} for i in range(7)])
db.campaigns.insert_one({"id": "k1", "tenant_id": "tenant-1"})
db.pass_registrations.insert_one({"serial": "FT-1", "device_id": "d"})
db.crm_prospects.insert_one({"id": "p1", "name": "Boulangerie Tours"})
db.platform_settings.insert_one({"key": "security", "max_failed": 5})
db.plan_settings.insert_one({"plan": "vip", "overrides": {"price": 108}})
db.platform_roles.insert_one({"id": "r1", "name": "Commercial"})

BOSS = SimpleNamespace(email="boss@fidclic.com", role="super_admin", tenant_id=None)

print("\nAperçu")
pv = PR.preview(include_crm=True, token_data=BOSS)
check("counts the businesses, customers and other logins", pv["businesses"] == 2 and pv["customers"] == 5
      and pv["logins_deleted"] == 4 and pv["collections"]["visits"] == 7)
KEEP = ["admin@fidelitour.com", "owner@cafelumiere.fr"]
pk = PR.preview(include_crm=True, keep=KEEP, token_data=BOSS)
check("the super admins are listed, you first-class", {x["email"] for x in pk["super_admins"]} ==
      {"boss@fidclic.com", "admin@fidelitour.com", "demo.admin@fidelitour.com"})
check("a ticked super admin is kept; a merchant login can never be", pk["kept_logins"] == ["admin@fidelitour.com", "boss@fidclic.com"]
      and pk["logins_deleted"] == 3)
check("settings are not in the list", "platform_settings" not in pv["collections"]
      and "plan_settings" not in pv["collections"] and "platform_roles" not in pv["collections"])
check("the CRM is counted when ticked", pv["collections"].get("crm_prospects") == 1)
check("and left out when not", "crm_prospects" not in PR.preview(include_crm=False, token_data=BOSS)["collections"])

print("\nLes garde-fous")
expect("no backup token → 400", 400, lambda: PR.reset(PR.ResetIn(token="nope", confirm="SUPPRIMER"), None, BOSS))
resp = PR.backup(include_crm=True, keep=KEEP, token_data=BOSS)
token = resp.headers["x-reset-token"]
raw = gzip.decompress(asyncio.run(body_of(resp)))
from bson import json_util
dump = json_util.loads(raw)
check("the backup holds everything that will go", dump["meta"]["counts"]["visits"] == 7
      and dump["meta"]["counts"]["users"] == 3 and len(dump["collections"]["customers"]) == 5)
expect("a different list of kept logins than the backup's → 400", 400,
       lambda: PR.reset(PR.ResetIn(token=token, confirm="SUPPRIMER", keep=[]), None, BOSS))
check("but not the super admin running it", all(u["email"] != "boss@fidclic.com" for u in dump["collections"]["users"]))
expect("wrong phrase → 400", 400, lambda: PR.reset(PR.ResetIn(token=token, confirm="supprimer ?", keep=KEEP), None, BOSS))
expect("backup taken for another scope → 400", 400,
       lambda: PR.reset(PR.ResetIn(token=token, confirm="SUPPRIMER", include_crm=False, keep=KEEP), None, BOSS))
TEAM = SimpleNamespace(email="sales@fidclic.com", role="commercial", tenant_id=None)
expect("a team member is refused (not super admin)", 403,
       lambda: PR.reset(PR.ResetIn(token=token, confirm="SUPPRIMER"), None,
                        SimpleNamespace(email="sales@fidclic.com", role="super_admin", tenant_id=None)))
old = PR.backup(include_crm=True, token_data=BOSS).headers["x-reset-token"]
db.platform_reset_tokens.update_one({"token": old}, {"$set": {"expires_at": now - timedelta(minutes=1)}})
expect("an expired backup token → 400", 400, lambda: PR.reset(PR.ResetIn(token=old, confirm="SUPPRIMER"), None, BOSS))

print("\nRemise à zéro")
out = PR.reset(PR.ResetIn(token=token, confirm="SUPPRIMER", include_crm=True, keep=KEEP), None, BOSS)
check("reports what it deleted", out["ok"] and out["deleted"]["visits"] == 7 and out["deleted"]["tenants"] == 2)
check("no business, customer, visit, campaign or pass left",
      sum(db[n].count_documents({}) for n in ("tenants", "customers", "visits", "campaigns", "pass_registrations", "crm_prospects")) == 0)
check("only the kept super admins can still log in (demo.admin and the merchant are gone)",
      sorted(u["email"] for u in db.users.find({})) == ["admin@fidelitour.com", "boss@fidclic.com"])
check("and stays signed in (their session is kept, the others' are not)",
      [x["sid"] for x in db.user_sessions.find({})] == ["s-boss"])
check("settings untouched", db.platform_settings.count_documents({}) == 1
      and db.plan_settings.count_documents({}) == 1 and db.platform_roles.count_documents({}) == 1)
expect("the token works once", 400, lambda: PR.reset(PR.ResetIn(token=token, confirm="SUPPRIMER", keep=KEEP), None, BOSS))
check("the new journal starts with the reset", db.audit_logs.count_documents({"action": "platform.reset"}) +
      db.audit_log.count_documents({"action": "platform.reset"}) >= 1)

print("\nLa sauvegarde permet de revenir en arrière")
for name, docs in dump["collections"].items():
    if docs:
        db[name].insert_many(docs)
check("restoring the file brings everything back", db.visits.count_documents({}) == 7
      and db.customers.count_documents({}) == 5 and db.users.count_documents({}) == 5
      and db.user_sessions.count_documents({}) == 2)

_patch.stop()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
