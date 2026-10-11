"""
Campagnes QA (2026-10-08): a draft can be reopened, changed, sent or deleted
(F02); a draft shows no « Envoyées » or open rate (F03); « Ajouter un lien »
accepts only a web address (UX09); and that link now reaches the customer's
card (the composer saved link_url, the card read link).

Run: cd api && /usr/local/bin/python3 tests/test_campaign_drafts_links.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-campaign-drafts")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    import auth
    import httpx
    db = server.db
    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "s", "name": "S", "plan": "vip", "subscription_status": "active"})
    db.tenants.insert_one({"id": "t2", "slug": "o", "name": "O", "plan": "vip", "subscription_status": "active"})
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "p@x.fr", "role": "business_owner", "tenant_id": "t2"}])
    for i in range(3):
        db.customers.insert_one({"id": f"c{i}", "tenant_id": "t1", "barcode_id": f"FT-0000000{i}", "name": f"C{i}",
                                 "visits": 1, "created_at": now})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    H2 = {"Authorization": "Bearer " + auth.create_access_token({"sub": "p@x.fr", "role": "business_owner", "tenant_id": "t2"})}

    def http(method, url, headers=H, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def compose(**kw):
        body = {"title": "Menu d'automne", "message": "Venez goûter", "segment": "all", **kw}
        return http("POST", "/api/owner/campaigns/compose", json=body)

    def row(cid):
        return next((r for r in http("GET", "/api/owner/campaigns/page").json()["recent"] if r["id"] == cid), None)

    print("\nLien (UX09)")
    r = compose(draft=True, link_url="not-a-url")
    check(f"« not-a-url » is refused with a sentence ({r.status_code})",
          r.status_code == 400 and "Lien invalide" in r.json()["detail"])
    check("javascript: is refused", compose(draft=True, link_url="javascript:alert(1)").status_code == 400)
    r = compose(draft=True, link_url="monsite.fr/menu")
    d = db.campaigns.find_one({"id": r.json()["id"]})
    check("« monsite.fr/menu » gets its https://", d["link_url"] == "https://monsite.fr/menu")
    check("no link is fine", compose(draft=True, link_url="  ").status_code == 200)

    print("\nBrouillon (F02 / F03)")
    did = r.json()["id"]
    rw = row(did)
    check("a draft shows no « Envoyées » and no open rate", rw["sent"] is None and rw["open_rate"] is None
          and rw["audience_count"] == 3)
    g = http("GET", f"/api/owner/campaigns/drafts/{did}").json()
    check("« Reprendre » gets the draft as saved", g["title"] == "Menu d'automne" and g["link_url"] == "https://monsite.fr/menu"
          and g["segment"] == "all" and g["push"] and g["wallet"])
    check("another shop cannot open it", http("GET", f"/api/owner/campaigns/drafts/{did}", headers=H2).status_code == 404)
    n = db.campaigns.count_documents({"tenant_id": "t1"})
    r = compose(draft=True, draft_id=did, title="Menu d'hiver")
    check("saving it again changes it, no second campaign",
          r.json()["id"] == did and db.campaigns.count_documents({"tenant_id": "t1"}) == n
          and db.campaigns.find_one({"id": did})["name"] == "Menu d'hiver")
    r = compose(draft_id=did, title="Menu d'hiver", link_url="https://monsite.fr/hiver")
    sent = db.campaigns.find_one({"id": did})
    check(f"sending it sends that campaign ({r.json().get('status')})",
          r.json()["id"] == did and sent["status"] == "sent" and sent["sent_at"] and db.campaigns.count_documents({"tenant_id": "t1"}) == n)
    check("…to its audience, on every card", db.push_notifications.count_documents({"campaign_id": did}) == 3)
    rw = row(did)
    check("a sent campaign shows its count and rate", rw["sent"] == 3 and rw["open_rate"] == 0)
    check("a sent campaign is no longer a draft", compose(draft_id=did).status_code == 409
          and http("DELETE", f"/api/owner/campaigns/drafts/{did}").status_code == 409)

    other = compose(draft=True, title="À jeter").json()["id"]
    check("another shop cannot delete it", http("DELETE", f"/api/owner/campaigns/drafts/{other}", headers=H2).status_code == 404)
    check("« Supprimer » deletes the draft", http("DELETE", f"/api/owner/campaigns/drafts/{other}").json()["deleted"]
          and not db.campaigns.find_one({"id": other}))

    print("\nCampagne planifiée : modifier, annuler")
    later = (now + dt.timedelta(days=2)).isoformat()
    pid = compose(title="Brunch", schedule_at=later).json()["id"]
    check("a planned campaign shows no count either", row(pid)["sent"] is None and row(pid)["status"] == "scheduled")
    g = http("GET", f"/api/owner/campaigns/drafts/{pid}").json()
    check("« Modifier » opens it with its day and hour", g["status"] == "scheduled" and g["scheduled_for"]
          and g["title"] == "Brunch")
    later2 = (now + dt.timedelta(days=3)).isoformat()
    r = compose(draft_id=pid, title="Brunch du dimanche", schedule_at=later2)
    d = db.campaigns.find_one({"id": pid})
    check("changed and planned again: the same campaign, the new text and day",
          r.json()["status"] == "scheduled" and d["name"] == "Brunch du dimanche"
          and abs((d["scheduled_for"].replace(tzinfo=dt.timezone.utc) if d["scheduled_for"].tzinfo is None else d["scheduled_for"])
                  - dt.datetime.fromisoformat(later2)).total_seconds() < 2
          and db.campaigns.count_documents({"name": {"$regex": "^Brunch"}}) == 1)
    check("a planned campaign is not deleted directly", http("DELETE", f"/api/owner/campaigns/drafts/{pid}").status_code == 409)
    check("another shop cannot cancel it",
          http("POST", f"/api/owner/campaigns/drafts/{pid}/cancel-schedule", headers=H2).status_code == 404)
    r = http("POST", f"/api/owner/campaigns/drafts/{pid}/cancel-schedule")
    d = db.campaigns.find_one({"id": pid})
    # redesign (2026-10-10): a cancelled plan is listed under « Annulées »
    check("« Annuler l'envoi »: it stays, « Annulée », its message kept", r.json()["status"] == "cancelled"
          and d["status"] == "cancelled" and d["name"] == "Brunch du dimanche")
    import features.campaigns_page as CPG
    CPG.run_due(now + dt.timedelta(days=4))
    check("…and the scheduler never sends it", db.campaigns.find_one({"id": pid})["status"] == "cancelled"
          and not db.push_notifications.count_documents({"campaign_id": pid}))
    check("cancelling a draft is refused", http("POST", f"/api/owner/campaigns/drafts/{pid}/cancel-schedule").status_code == 409)
    pid2 = compose(title="Goûter", schedule_at=later).json()["id"]
    CPG.run_due(now + dt.timedelta(days=4))
    check("once the scheduler sent it, it can no longer be changed or cancelled",
          compose(draft_id=pid2, title="x").status_code == 409
          and http("POST", f"/api/owner/campaigns/drafts/{pid2}/cancel-schedule").status_code == 409)

    print("\nLe lien arrive sur la carte")
    card = http("GET", "/api/card/FT-00000000", headers={"X-Card-Key": __import__("services.card_owner", fromlist=["x"]).key_for("FT-00000000")}).json()
    feed = (card.get("offers") or []) + (card.get("notifications") or [])
    hit = [o for o in feed if o.get("id") == did]
    check("the card's offer carries the campaign's link", hit and all(o.get("link") == "https://monsite.fr/hiver" for o in hit))
    db.campaigns.insert_one({"id": "old", "tenant_id": "t1", "name": "Ancienne", "content": "x", "status": "sent",
                             "sent_at": now, "link": "javascript:alert(1)",
                             # a card lists only the campaigns sent to it (2026-10-09)
                             "recipient_ids": [db.customers.find_one({"barcode_id": "FT-00000000"})["id"]]})
    card = http("GET", "/api/card/FT-00000000", headers={"X-Card-Key": __import__("services.card_owner", fromlist=["x"]).key_for("FT-00000000")}).json()
    bad = [o for o in (card.get("offers") or []) + (card.get("notifications") or []) if o.get("id") == "old"]
    check("a stored non-web link never reaches the card", bad and all(o.get("link") is None for o in bad))

    print("\nL'ancien envoi")
    check("the old « send » refuses a Campagnes campaign (it would reach every customer)",
          http("POST", f"/api/owner/campaigns/{compose(draft=True).json()['id']}/send").status_code == 409)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
