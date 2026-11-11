"""
Super admin › Notifications (user, 2026-11-11): FidClic's team writes to ONE
business, several, or all of them — never only « all ». The message reaches
the business's own people (owner, administrateur, manager) in their bell, and
by e-mail when asked. Their customers are never written to from here: the
team reaches them through the business's own account (view-as).

The old « broadcast » (a push to every end customer of every shop when no
filter was set — Royal Trim's and Green Smoke's too) is closed.

Run: cd api && python3 -u tests/test_admin_notices.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-admin-notices")
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
    from features import admin_notices as N, platform_access as PA
    from services import mailer

    db = server.db
    NOW = dt.datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
    N._now = lambda: NOW
    PA.forget()

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def tok(email, role, tid=None):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tid})}

    db.tenants.insert_many([
        {"id": "rt", "slug": "rt", "name": "ROYAL TRIM", "is_active": True, "plan": "vip", "subscription_status": "active",
         "city": "Tours", "branches": [{"id": "main", "name": "LIBÉRTÉ", "is_main": True}, {"id": "b2", "name": "PALISSY"}]},
        {"id": "gs", "slug": "gs", "name": "Green Smoke", "is_active": True, "plan": "gold", "subscription_status": "trialing",
         "trial_ends_at": NOW + dt.timedelta(days=10)},
        {"id": "quiet", "slug": "quiet", "name": "Café Calme", "is_active": True, "plan": "silver"},
        {"id": "gone", "slug": "gone", "name": "Fermé", "is_active": False, "plan": "silver"},
    ])
    db.users.insert_many([
        {"email": "boss@fidclic.com", "role": "super_admin"},
        {"email": "writer@fidclic.com", "role": "fidclic_team", "platform_role": "comm"},
        {"email": "reader@fidclic.com", "role": "fidclic_team", "platform_role": "lecture"},
        {"email": "other@fidclic.com", "role": "fidclic_team", "platform_role": "rien"},
        {"email": "own@rt.fr", "role": "business_owner", "tenant_id": "rt"},
        {"email": "mgr@rt.fr", "role": "manager", "tenant_id": "rt"},
        {"email": "staff@rt.fr", "role": "staff", "tenant_id": "rt"},
        {"email": "own@gs.fr", "role": "business_owner", "tenant_id": "gs"},
        {"email": "own@quiet.fr", "role": "business_owner", "tenant_id": "quiet"},
        {"email": "own@gone.fr", "role": "business_owner", "tenant_id": "gone"},
    ])
    db.platform_roles.insert_many([
        {"id": "comm", "name": "Comm", "perms": {"notifications": {"view": True, "edit": True}}},
        {"id": "lecture", "name": "Lecture", "perms": {"notifications": {"view": True, "edit": False}}},
        {"id": "rien", "name": "Rien", "perms": {"support": {"view": True, "edit": True}}},
    ])
    db.customers.insert_many([{"id": f"c{i}", "tenant_id": t, "name": f"Client {i}"} for i, t in enumerate(["rt", "rt", "gs"])])
    BOSS, WRITER, READER, OTHER = (tok("boss@fidclic.com", "super_admin"), tok("writer@fidclic.com", "fidclic_team"),
                                   tok("reader@fidclic.com", "fidclic_team"), tok("other@fidclic.com", "fidclic_team"))
    OWN_RT, MGR_RT, STAFF_RT = tok("own@rt.fr", "business_owner", "rt"), tok("mgr@rt.fr", "manager", "rt"), tok("staff@rt.fr", "staff", "rt")
    OWN_GS, OWN_Q = tok("own@gs.fr", "business_owner", "gs"), tok("own@quiet.fr", "business_owner", "quiet")
    sent_mail = []
    mailer.send_batch = lambda msgs, sender_name=None: (sent_mail.extend(msgs), [{"sent": True} for _ in msgs])[1]
    URL = "/api/admin/notices"

    # ------------------------------------------------------------------ who may
    print("Qui peut")
    check("a business owner cannot write to businesses",
          http("POST", URL, headers=OWN_RT, json={"title": "x", "body": "y", "tenant_ids": ["gs"]}).status_code == 403)
    check("…nor read the team's list", http("GET", URL, headers=OWN_RT).status_code == 403)
    check("no token → 401/403", http("GET", URL).status_code in (401, 403))
    check("a team member without « Notifications » sees nothing (403)", http("GET", URL, headers=OTHER).status_code == 403)
    check("« Voir » only: the history yes", http("GET", URL, headers=READER).status_code == 200)
    check("« Voir » only: sending no (403)",
          http("POST", URL, headers=READER, json={"title": "x", "body": "y", "tenant_ids": ["rt"]}).status_code == 403)

    # ------------------------------------------------------------------ the businesses to pick from
    print("\nLes commerces à choisir")
    r = http("GET", URL + "/targets", headers=READER)
    rows = {t["id"]: t for t in (r.json().get("businesses") or [])}
    check("every open business is offered", r.status_code == 200 and set(rows) == {"rt", "gs", "quiet"}, sorted(rows))
    check("…never a deleted one", "gone" not in rows)
    check("…with its name, plan, status and number of boutiques",
          rows["rt"]["name"] == "ROYAL TRIM" and rows["rt"]["plan"] == "vip" and rows["rt"]["status"] == "abonne"
          and rows["rt"]["stores"] == 2 and rows["gs"]["status"] == "essai", rows.get("rt"))
    check("…and whether it has an e-mail to write to", rows["rt"]["has_email"] is True)
    check("no client data in the list (no customer id, no phone)", "c0" not in r.text and "phone" not in r.text)

    # ------------------------------------------------------------------ what is refused
    print("\nCe qui est refusé")
    bad = [
        ({"title": "", "body": "Bonjour", "tenant_ids": ["rt"]}, "an empty title"),
        ({"title": "Info", "body": "  ", "tenant_ids": ["rt"]}, "an empty message"),
        ({"title": "Info", "body": "Bonjour"}, "no business chosen"),
        ({"title": "Info", "body": "Bonjour", "tenant_ids": []}, "an empty choice"),
        ({"title": "Info", "body": "Bonjour", "tenant_ids": ["nope"]}, "a made-up business"),
        ({"title": "Info", "body": "Bonjour", "tenant_ids": ["gone"]}, "a deleted business"),
        ({"title": "x" * 121, "body": "Bonjour", "tenant_ids": ["rt"]}, "a title over 120 characters"),
        ({"title": "Info", "body": "x" * 2001, "tenant_ids": ["rt"]}, "a message over 2 000 characters"),
        ({"title": "Info", "body": "Bonjour", "tenant_ids": ["rt"], "link": "javascript:alert(1)"}, "a javascript: link"),
        ({"title": "Info", "body": "Bonjour", "tenant_ids": ["rt"], "link": "https://evil.example"}, "a link out of FidClic"),
        ({"title": "Info", "body": "Bonjour", "tenant_ids": ["rt"], "link": "//evil.example/x"}, "a protocol-relative link"),
        ({"title": "Info", "body": "Bonjour", "tenant_ids": ["rt"], "level": "panic"}, "an unknown level"),
        ({"title": "Info", "body": "Bonjour", "tenant_ids": "rt"}, "a business id not in a list"),
    ]
    for body, label in bad:
        code = http("POST", URL, headers=WRITER, json=body).status_code
        check(f"{label} → refused", code in (400, 422), code)
    check("nothing was stored by the refusals", db.platform_notices.count_documents({}) == 0)

    # ------------------------------------------------------------------ one business, several, all
    print("\nUn, plusieurs, tous")
    r = http("POST", URL, headers=WRITER, json={"title": "Maintenance ce soir", "body": "<b>Coupure</b> de 22:00 à 22:30.\nMerci !",
                                                 "tenant_ids": ["rt", "gs"], "level": "important", "email": True,
                                                 "link": "/dashboard/aide"})
    j = r.json()
    check("two chosen businesses → sent to 2", r.status_code == 200 and j.get("businesses") == 2, j)
    check("the e-mail went to each business's owner, once", sorted(m["to"] for m in sent_mail) == ["own@gs.fr", "own@rt.fr"],
          [m["to"] for m in sent_mail])
    check("…and says how many left", j.get("emailed") == 2, j)
    check("the message's HTML is shown as text in the e-mail, never run",
          sent_mail and "&lt;b&gt;Coupure&lt;/b&gt;" in sent_mail[0]["html"] and "<b>Coupure</b>" not in sent_mail[0]["html"],
          sent_mail[0]["html"][:300] if sent_mail else None)
    check("…the e-mail carries the FidClic link", sent_mail and "/dashboard/aide" in sent_mail[0]["html"])
    nid = j.get("id")

    bell = lambda h: http("GET", "/api/owner/notices", headers=h)          # noqa: E731
    rt_b = bell(OWN_RT).json().get("alerts") or []
    check("Royal Trim's owner finds it in the bell", len(rt_b) == 1 and rt_b[0]["title"] == "Maintenance ce soir", rt_b)
    check("…as FidClic's word, with its level and date",
          rt_b and rt_b[0]["severity"] == "warning" and rt_b[0]["created_at"].startswith("2026-11-11") and rt_b[0].get("from") == "FidClic",
          rt_b)
    check("…its link opens the page given", rt_b and (rt_b[0].get("action") or {}).get("href") == "/dashboard/aide", rt_b)
    check("…its text kept as written (the app shows it as text)", rt_b and rt_b[0]["body"].startswith("<b>Coupure</b>"))
    check("Royal Trim's manager finds it too", len(bell(MGR_RT).json().get("alerts") or []) == 1)
    check("a till account (staff) is not given the bell (403)", bell(STAFF_RT).status_code == 403)
    check("Green Smoke's owner finds it", len(bell(OWN_GS).json().get("alerts") or []) == 1)
    check("Café Calme, not chosen, finds nothing", bell(OWN_Q).json().get("alerts") == [])
    check("the team cannot read a business's bell route", bell(BOSS).status_code == 403)

    sent_mail.clear()
    r = http("POST", URL, headers=BOSS, json={"title": "Nouveauté", "body": "Les boutiques arrivent.", "all": True})
    j = r.json()
    check("« all » is a choice made on purpose → every open business (3)", r.status_code == 200 and j.get("businesses") == 3, j)
    check("…no e-mail unless asked", sent_mail == [] and j.get("emailed") == 0, j)
    check("…the deleted business is not written to", db.platform_notices.find_one({"id": j["id"]})["tenant_ids"].count("gone") == 0)
    db.tenants.insert_one({"id": "late", "slug": "late", "name": "Arrivé après", "is_active": True})
    db.users.insert_one({"email": "own@late.fr", "role": "business_owner", "tenant_id": "late"})
    check("a business that joins later does not receive what was sent before it",
          bell(tok("own@late.fr", "business_owner", "late")).json().get("alerts") == [])
    check("Café Calme now has the « all » message only", [a["title"] for a in bell(OWN_Q).json()["alerts"]] == ["Nouveauté"])
    check("newest first in the bell", [a["title"] for a in bell(OWN_RT).json()["alerts"]] == ["Nouveauté", "Maintenance ce soir"]
          or len({a["created_at"] for a in bell(OWN_RT).json()["alerts"]}) == 1)

    # ------------------------------------------------------------------ the history
    print("\nL'historique")
    h = http("GET", URL, headers=READER).json()
    items = h.get("notices") or []
    check("both messages, newest first", [n["title"] for n in items][:2] in (["Nouveauté", "Maintenance ce soir"],
                                                                            ["Maintenance ce soir", "Nouveauté"]) and len(items) == 2, items)
    first = next(n for n in items if n["id"] == nid)
    check("…each says who sent it, to whom (names) and how many",
          first["by"] == "writer@fidclic.com" and sorted(first["to_names"]) == ["Green Smoke", "ROYAL TRIM"] and first["businesses"] == 2,
          first)
    check("…the « all » one says so", next(n for n in items if n["id"] != nid)["all"] is True)
    check("every send is in the journal", db.audit_logs.count_documents({"action": "platform.notice_send"}) == 2)

    # ------------------------------------------------------------------ withdraw
    print("\nRetirer")
    check("« Voir » only cannot withdraw (403)", http("DELETE", f"{URL}/{nid}", headers=READER).status_code == 403)
    r = http("DELETE", f"{URL}/{nid}", headers=WRITER)
    check("withdrawn by a member with « Modifier »", r.status_code == 200, r.text)
    check("…gone from Royal Trim's bell", [a["title"] for a in bell(OWN_RT).json()["alerts"]] == ["Nouveauté"])
    check("…still in the history, marked withdrawn",
          next(n for n in http("GET", URL, headers=BOSS).json()["notices"] if n["id"] == nid).get("withdrawn_at"))
    check("…and in the journal", db.audit_logs.count_documents({"action": "platform.notice_withdraw"}) == 1)
    check("withdrawing a made-up id → 404", http("DELETE", f"{URL}/nope", headers=BOSS).status_code == 404)

    # ------------------------------------------------------------------ the old broadcast is closed
    print("\nL'ancien broadcast aux clients finaux")
    before = db.notifications.count_documents({})
    r = http("POST", "/api/admin/broadcast", headers=BOSS, json={"subject": "Promo", "body": "Venez !", "filters": {}})
    check("sending to every shop's customers is closed (410)", r.status_code == 410, r.status_code)
    check("…and says to write from the business's own account", "compte" in (r.json().get("detail") or ""), r.text[:200])
    check("…nobody was written to", db.notifications.count_documents({}) == before)
    check("…with a filter too", http("POST", "/api/admin/broadcast", headers=BOSS,
                                     json={"subject": "P", "body": "V", "filters": {"tenant_id": "rt"}}).status_code == 410)
    check("…its preview too", http("POST", "/api/admin/broadcast/preview", headers=BOSS,
                                   json={"subject": "P", "body": "V", "filters": {}}).status_code == 410)

    # ------------------------------------------------------------------ edges
    print("\nCas limites")
    many = [f"t{i}" for i in range(60)]
    db.tenants.insert_many([{"id": t, "slug": t, "name": f"Shop {t}", "is_active": True} for t in many])
    r = http("POST", URL, headers=BOSS, json={"title": "Grand envoi", "body": "Bonjour", "tenant_ids": many + ["rt", "rt"]})
    check("60 businesses + a duplicate → 61 written to, once each", r.status_code == 200 and r.json()["businesses"] == 61, r.text[:200])
    r = http("POST", URL, headers=BOSS, json={"title": "  Espaces  ", "body": "  Bonjour  ", "tenant_ids": ["quiet"]})
    check("spaces around the title and the message are trimmed",
          db.platform_notices.find_one({"id": r.json()["id"]})["title"] == "Espaces")
    check("a business with no owner e-mail is skipped in the e-mail count, not an error",
          http("POST", URL, headers=BOSS, json={"title": "E", "body": "B", "tenant_ids": many[:2], "email": True}).json().get("emailed") == 0)
    old = db.platform_notices.insert_one({"id": "old", "title": "Vieux", "body": "x", "level": "info", "tenant_ids": ["quiet"],
                                          "created_at": NOW - dt.timedelta(days=91), "by": "boss@fidclic.com"})
    check("a message older than 90 days leaves the bell", "Vieux" not in [a["title"] for a in bell(OWN_Q).json()["alerts"]])

    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
