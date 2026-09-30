"""
CRM › Vue d'ensemble › Pilotage commercial — the eight « À traiter » lines
and their lists, the sales team figures, and the pipeline health (conversion,
days in stage, idle prospects, expected signatures).

Run: cd api && /usr/local/bin/python3 tests/test_crm_pilotage.py
"""
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from fastapi import HTTPException
    from models import TokenData
    from features import crm as C, crm_pilotage as P

    db = server.db
    C.init(db); P.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    d = lambda n: now - dt.timedelta(days=n)                  # noqa: E731
    db.users.insert_many([{"email": "sofia@fidclic.com", "role": "commercial", "first_name": "Sofia", "last_name": "R."},
                          {"email": "karim@fidclic.com", "role": "commercial", "first_name": "Karim", "last_name": "D."}])
    Pr = lambda pid, stage, who=None, last=2, **kw: {"id": pid, "name": pid.title(), "stage": stage, "assigned_to": who,  # noqa: E731
                                                      "created_at": d(90), "last_activity_at": d(last), **kw}
    db.crm_prospects.insert_many([
        Pr("alpha", "contacte", "sofia@fidclic.com"), Pr("beta", "rdv", "sofia@fidclic.com"),
        Pr("gamma", "proposition", "karim@fidclic.com", last=10), Pr("delta", "essai", "karim@fidclic.com", tenant_id="tx"),
        Pr("eps", "a_contacter", None, last=40), Pr("zeta", "signe", "sofia@fidclic.com"), Pr("eta", "perdu", "karim@fidclic.com"),
    ])
    db.tenants.insert_one({"id": "tx", "name": "Delta", "trial_ends_at": now + dt.timedelta(days=3)})
    db.crm_tasks.insert_many([
        {"id": "t1", "prospect_id": "alpha", "title": "Rappeler", "type": "appel", "status": "a_faire", "due_at": d(2), "assigned_to": "sofia@fidclic.com"},
        {"id": "t2", "prospect_id": "beta", "title": "RDV", "type": "rdv", "status": "a_faire", "confirm_status": "a_confirmer",
         "due_at": now + dt.timedelta(days=2), "assigned_to": "sofia@fidclic.com"},
        {"id": "t3", "prospect_id": "gamma", "title": "Suivi", "type": "suivi", "status": "terminee", "due_at": d(5)},
    ])
    act = lambda pid, frm, to, days: {"id": f"{pid}-{to}", "prospect_id": pid, "type": "stage", "text": "Étape", "at": d(days),  # noqa: E731
                                      "meta": {"from": frm, "to": to}}
    db.crm_activities.insert_many([
        act("alpha", "a_contacter", "contacte", 20), act("beta", "contacte", "rdv", 15), act("gamma", "rdv", "proposition", 12),
        act("delta", "proposition", "essai", 6), act("zeta", "contacte", "rdv", 25), act("zeta", "rdv", "proposition", 20),
        act("zeta", "proposition", "signe", 10), act("eta", "proposition", "perdu", 8),
    ])
    db.crm_calls.insert_many([{"id": "c1", "prospect_id": "alpha", "by": "sofia@fidclic.com", "at": d(1)},
                              {"id": "c2", "prospect_id": "gamma", "by": "karim@fidclic.com", "at": d(3)}])
    db.crm_email_sends.insert_one({"id": "m1", "prospect_id": "gamma", "status": "sent", "replied_at": d(1)})

    r = P.pilotage(token_data=ADMIN)
    a = {x["key"]: x["count"] for x in r["attention"]}
    print("\nÀ traiter maintenant")
    check("tâches en retard", a["overdue"] == 1)
    check("rendez-vous à confirmer dans 7 jours", a["rdv_confirm"] == 1)
    check("sans prochaine action (gamma's task is done, delta/eps have none)", a["no_next"] == 3)
    check("sans commercial", a["unassigned"] == 1)
    check("proposition sans nouvelles depuis 7 jours", a["quiet_proposals"] == 1)
    check("essai qui se termine dans 7 jours", a["trials_ending"] == 1)
    check("inactif depuis 30 jours", a["idle"] == 1)
    check("réponse email reçue", a["replies"] == 1)
    lst = P.attention_list("no_next", token_data=ADMIN)
    check("a line opens its prospects", lst["kind"] == "prospects" and {x["id"] for x in lst["rows"]} == {"gamma", "delta", "eps"})
    tl = P.attention_list("overdue", token_data=ADMIN)
    check("task lines open the tasks", tl["kind"] == "tasks" and tl["rows"][0]["id"] == "t1" and tl["rows"][0]["status"] == "en_retard")
    try:
        P.attention_list("nope", token_data=ADMIN); check("unknown list refused", False)
    except HTTPException as e:
        check("unknown list refused", e.status_code == 404)

    print("\nÉquipe commerciale")
    t = {x["email"]: x for x in r["team"]}
    check("Sofia: 2 active, 1 signed in the period, 1 call, 1 overdue",
          t["sofia@fidclic.com"]["active"] == 2 and t["sofia@fidclic.com"]["signed_period"] == 1 and t["sofia@fidclic.com"]["calls"] == 1
          and t["sofia@fidclic.com"]["overdue"] == 1 and t["sofia@fidclic.com"]["name"] == "Sofia R.")
    check("conversion = signés / assignés", t["sofia@fidclic.com"]["conversion"] == 33 and t["karim@fidclic.com"]["conversion"] == 0)
    check("unassigned prospects shown last", r["team"][-1]["email"] == "none" and r["team"][-1]["active"] == 1)

    print("\nSanté du pipeline")
    h = {s["key"]: s for s in r["health"]["stages"]}
    check("counts per stage", h["proposition"]["count"] == 1 and h["signe"]["count"] == 1 and h["essai"]["count"] == 1)
    check("rdv → proposition: 3 of the 4 who reached rdv went on", h["rdv"]["conversion"] == 75)
    check("average days in a stage (zeta 10 days in proposition, gamma 12 so far)", h["proposition"]["avg_days"] is not None)
    check("expected signatures from propositions and trials", r["health"]["forecast"] >= 0 and r["health"]["forecast_basis"]["proposition"] == 33)
    check("win rate = signés / (signés + perdus)", r["health"]["win_rate"] == 50)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
