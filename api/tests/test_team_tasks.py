"""
Super admin › Suivi d'équipe (user, 2026-10-08): FidClic's team tasks.

Run: cd api && /usr/local/bin/python3 tests/test_team_tasks.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-team-tasks")
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
    from features import team_tasks as T, platform_access as PA
    db = server.db
    PA.forget()
    db.users.insert_many([
        {"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Akshansh", "last_name": "S"},
        {"email": "mahdi@fidclic.com", "role": "fidclic_team", "platform_role": "ops", "first_name": "Mahdi"},
        {"email": "meriem@fidclic.com", "role": "fidclic_team", "platform_role": "lecture", "first_name": "Meriem"},
        {"email": "sam@fidclic.com", "role": "fidclic_team", "platform_role": "analyste", "first_name": "Sam"},
    ])
    db.platform_roles.insert_many([
        {"id": "ops", "name": "Responsable", "perms": {"equipe": {"view": True, "edit": True}}},
        {"id": "lecture", "name": "Lecture", "perms": {"equipe": {"view": True, "edit": False}}},
    ])

    def tok(email, role):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role})}
    BOSS, MAHDI, MERIEM, SAM = (tok("boss@fidclic.com", "super_admin"), tok("mahdi@fidclic.com", "fidclic_team"),
                                tok("meriem@fidclic.com", "fidclic_team"), tok("sam@fidclic.com", "fidclic_team"))

    def http(method, url, h=BOSS, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=h, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    paris = T.PARIS
    now = dt.datetime.now(paris)
    today = now.date()

    def at(delta_h):
        # real hours, then read in Paris: adding to a Paris wall clock jumped an
        # hour on the night the clocks go back (25/10, 02:35 + 30 min = 03:05 CET)
        d = (now.astimezone(dt.timezone.utc) + dt.timedelta(hours=delta_h)).astimezone(paris)
        return d.date().isoformat(), f"{d.hour:02d}:{d.minute:02d}"

    def new(title, delta_h, who=("mahdi@fidclic.com",), h=BOSS, **kw):
        day, hm = at(delta_h)
        return http("POST", "/api/admin/equipe/tasks", h, json={"title": title, "assignees": list(who), "due_date": day,
                                                                 "due_time": hm, "priority": kw.pop("priority", "moyenne"), **kw})

    print("\nAccès (Sécurité › Rôles)")
    check("the module is in the roles list", any(k == "equipe" for k, _ in PA.MODULES))
    check("the super admin sees the board", http("GET", "/api/admin/equipe/board").status_code == 200)
    check("a role with Voir sees it", http("GET", "/api/admin/equipe/board", MERIEM).status_code == 200)
    check("…but cannot change anything", new("x", 2, h=MERIEM).status_code == 403)
    check("a role without it is refused", http("GET", "/api/admin/equipe/board", SAM).status_code == 403)

    print("\nÉquipe")
    cands = http("GET", "/api/admin/equipe/members/candidates").json()["rows"]
    check("candidates are FidClic's team users", {c["email"] for c in cands} >= {"mahdi@fidclic.com", "meriem@fidclic.com", "sam@fidclic.com"})
    check("…and say who has no access", next(c for c in cands if c["email"] == "sam@fidclic.com")["access"] is False)
    for e in ("mahdi@fidclic.com", "meriem@fidclic.com", "boss@fidclic.com"):
        http("POST", "/api/admin/equipe/members", json={"email": e})
    # a member from before the fonction list, with a free-text fonction
    db.team_board_members.update_one({"email": "meriem@fidclic.com"}, {"$set": {"fonction": "Administratrice"}})
    T.init(db)
    check("a non-team e-mail cannot join", http("POST", "/api/admin/equipe/members", json={"email": "x@y.fr"}).status_code == 400)
    check("a task goes only to the team", new("x", 2, who=("sam@fidclic.com",)).status_code == 400)
    check("a deadline needs an hour", http("POST", "/api/admin/equipe/tasks", json={"title": "x", "assignees": ["mahdi@fidclic.com"],
                                                                                    "due_date": today.isoformat(), "due_time": ""}).status_code == 400)

    print("\nStatuts — lus sur l'horloge")
    a = new("À faire plus tard", 3).json()["id"]
    b = new("Déjà en retard", -3).json()["id"]
    c = new("Finie à temps", 2, who=("mahdi@fidclic.com", "meriem@fidclic.com")).json()["id"]
    d = new("Finie en retard", -2).json()["id"]
    check("Mahdi ticks his task", http("POST", f"/api/admin/equipe/tasks/{c}/complete", MAHDI, json={"done": True}).json()["status"] == "terminee")
    check("finished after the deadline → terminée en retard",
          http("POST", f"/api/admin/equipe/tasks/{d}/complete", json={"done": True}).json()["status"] == "terminee_retard")
    det = {i: http("GET", f"/api/admin/equipe/tasks/{i}").json()["task"]["status"] for i in (a, b, c, d)}
    check(f"à faire / en retard / terminée / terminée en retard ({det})",
          det == {a: "a_faire", b: "en_retard", c: "terminee", d: "terminee_retard"})
    bd = http("GET", "/api/admin/equipe/board").json()
    k = bd["kpis"]
    check("En retard shows open-late and finished-late apart", k["late_open"] == 1 and k["late_done"] == 1 and k["late"] == 2)
    check("totals: 4 tasks, 2 finished, 1 à faire", k["total"] == 4 and k["done"] == 2 and k["todo"] == 1 and bd["progress"]["pct"] == 50)
    check("seven columns, Monday → Sunday", len(bd["days"]) == 7 and bd["days"][0]["name"] == "Lundi" and bd["days"][6]["name"] == "Dimanche")
    check("the « En retard » box holds both late kinds", bd["counts"]["status"]["en_retard"] == 2
          and bd["counts"]["status"]["terminee"] == 2)
    m = {x["email"]: x for x in bd["members"]}
    check("Équipe: assigned / done per person", m["mahdi@fidclic.com"]["assigned"] == 4 and m["mahdi@fidclic.com"]["done"] == 2
          and m["meriem@fidclic.com"]["assigned"] == 1 and m["meriem@fidclic.com"]["done"] == 1)
    check("untick a mistake: back to its clock status",
          http("POST", f"/api/admin/equipe/tasks/{c}/complete", json={"done": False}).json()["status"] == "a_faire")
    for i in range(30):
        new(f"Tâche {i}", 4)
    check("no limit on tasks per day", sum(x["total"] for x in http("GET", "/api/admin/equipe/board").json()["days"]) == 34)

    print("\nModifier · supprimer · historique de la tâche")
    day, hm = at(26)
    r = http("PUT", f"/api/admin/equipe/tasks/{a}", json={"due_date": day, "due_time": hm, "assignees": ["meriem@fidclic.com"]})
    t = http("GET", f"/api/admin/equipe/tasks/{a}").json()
    check("new day / hour and new person", r.status_code == 200 and t["task"]["due_date"] == day
          and [x["email"] for x in t["task"]["assignees"]] == ["meriem@fidclic.com"])
    check("its history says who did what", [e["kind"] for e in t["events"]] == ["created", "updated"]
          and "Meriem" in t["events"][1]["text"])
    http("POST", f"/api/admin/equipe/tasks/{a}/comments", json={"text": "Pense au devis"})
    t = http("GET", f"/api/admin/equipe/tasks/{a}").json()
    check("comments", t["comments"][0]["text"] == "Pense au devis" and t["task"]["comments"] == 1)
    http("DELETE", f"/api/admin/equipe/tasks/{b}")
    check("deleted: off the board", all(x["id"] != b for dd in http("GET", "/api/admin/equipe/board").json()["days"] for x in dd["tasks"]))

    print("\nCloche")
    al = {x["title"] for x in http("GET", "/api/admin/equipe/alerts", MERIEM).json()["alerts"]}
    check("the person a task goes to is told", any("Nouvelle tâche pour vous" in x for x in al))
    late = new("Bientôt en retard", -0.2).json()["id"]
    soon = new("Dans 30 min", 0.5).json()["id"]
    # its due time set to the instant itself: the night the clocks go back,
    # « 02:05 » names two moments and the form can only name the first
    T._db.team_tasks.update_one({"id": soon}, {"$set": {
        "due_at": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30), "reminder_sent": False}})
    http("GET", "/api/admin/equipe/alerts")
    mt = [x["title"] for x in http("GET", "/api/admin/equipe/alerts", MAHDI).json()["alerts"]]
    check("one hour before", any("moins d'une heure" in x and "Dans 30 min" in x for x in mt))
    check("when late, to its people", any("en retard" in x and "Bientôt en retard" in x for x in mt))
    bt = [x["title"] for x in http("GET", "/api/admin/equipe/alerts").json()["alerts"]]
    check("…and to the super admin", any("Bientôt en retard" in x for x in bt))
    http("GET", "/api/admin/equipe/alerts")
    check("each alert once", db.team_task_alerts.count_documents({"task_id": late, "kind": "late", "to": "mahdi@fidclic.com"}) == 1)

    print("\nRépétition")
    mon = today - dt.timedelta(days=today.weekday())
    r = http("POST", "/api/admin/equipe/tasks", json={"title": "Point hebdo", "assignees": ["mahdi@fidclic.com"],
                                                      "due_date": mon.isoformat(), "due_time": "09:00",
                                                      "recurrence": {"freq": "weekly", "weekdays": [0, 3]}})
    sid = r.json()["series_id"]
    far = (mon + dt.timedelta(days=70)).isoformat()
    week10 = http("GET", f"/api/admin/equipe/board?week={far}").json()
    hits = [x for dd in week10["days"] for x in dd["tasks"] if x["title"] == "Point hebdo"]
    check("written ahead as the weeks are opened: Monday and Thursday", len(hits) == 2
          and {x["due_date"] for x in hits} == {far, (dt.date.fromisoformat(far) + dt.timedelta(days=3)).isoformat()})
    check("says how it repeats", hits[0]["repeat"].startswith("Chaque semaine (lundi, jeudi)"))
    first = db.team_tasks.find_one({"series_id": sid}, sort=[("due_at", 1)])
    second = db.team_tasks.find({"series_id": sid}).sort("due_at", 1)[1]
    http("PUT", f"/api/admin/equipe/tasks/{second['id']}", json={"title": "Point d'équipe", "due_time": "10:30", "apply_to": "following"})
    later = list(db.team_tasks.find({"series_id": sid, "occurrence": {"$gt": second["occurrence"]}}))
    check("« et les suivantes »: text and hour follow, each keeps its day",
          later and all(x["title"] == "Point d'équipe" and T._paris(x["due_at"]).strftime("%H:%M") == "10:30" for x in later)
          and db.team_tasks.find_one({"id": first["id"]})["title"] == "Point hebdo")
    third = later[0]
    http("DELETE", f"/api/admin/equipe/tasks/{third['id']}?scope=following")
    http("GET", f"/api/admin/equipe/board?week={(mon + dt.timedelta(days=140)).isoformat()}")
    alive = db.team_tasks.count_documents({"series_id": sid, "deleted_at": None, "occurrence": {"$gte": third["occurrence"]}})
    check("delete « et les suivantes »: the series stops there", alive == 0)
    r = http("POST", "/api/admin/equipe/tasks", json={"title": "Caisse", "assignees": ["mahdi@fidclic.com"], "due_date": mon.isoformat(),
                                                      "due_time": "18:00", "recurrence": {"freq": "daily", "count": 3}})
    http("GET", f"/api/admin/equipe/board?week={(mon + dt.timedelta(days=21)).isoformat()}")
    check("« 3 fois » makes three", db.team_tasks.count_documents({"series_id": r.json()["series_id"]}) == 3)
    r = http("POST", "/api/admin/equipe/tasks", json={"title": "Loyer", "assignees": ["mahdi@fidclic.com"], "due_date": "2026-01-31",
                                                      "due_time": "09:00", "recurrence": {"freq": "monthly", "until": "2026-04-30"}})
    days = sorted(T._paris(x["due_at"]).date().isoformat() for x in db.team_tasks.find({"series_id": r.json()["series_id"]}))
    check(f"monthly on the 31st lands on each month's last day ({days})", days == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"])
    check("past repeats are not bell news", not db.team_task_alerts.find_one({"kind": "late", "task_id": {"$in": [
        x["id"] for x in db.team_tasks.find({"series_id": r.json()["series_id"]})]}}))

    print("\nHistorique")
    h = http("GET", "/api/admin/equipe/history?date_from=2026-01-01").json()
    check("every task that came due, newest first", h["total"] >= 8 and h["rows"][0]["due_at"] >= h["rows"][-1]["due_at"])
    late_only = http("GET", "/api/admin/equipe/history?date_from=2026-01-01&status=en_retard").json()["rows"]
    check("status filter « En retard » = open late + finished late",
          {x["status"] for x in late_only} <= {"en_retard", "terminee_retard"} and any(x["status"] == "terminee_retard" for x in late_only))
    gone = http("GET", "/api/admin/equipe/history?date_from=2026-01-01&status=supprimee").json()["rows"]
    check("deleted tasks are kept, as « Supprimée »", any(x["id"] == b for x in gone))
    check("search", all("hebdo" in x["title"].lower() for x in
                        http("GET", f"/api/admin/equipe/history?date_from=2026-01-01&date_to={far}&q=hebdo").json()["rows"]))
    csv = http("GET", "/api/admin/equipe/history/export?date_from=2026-01-01")
    check("CSV export", csv.status_code == 200 and "Terminée en retard" in csv.text and csv.text.startswith("﻿Tâche;"))

    print("\nDétail d'une personne")
    bk = http("GET", "/api/admin/equipe/members/mahdi@fidclic.com/breakdown").json()
    check("by status: done, late, to do", bk["counts"]["terminee_retard"] >= 1 and bk["counts"]["en_retard"] >= 1
          and {g["key"] for g in bk["groups"]} == {"en_retard", "a_faire", "terminee_retard", "terminee"})
    check("all time too", http("GET", "/api/admin/equipe/members/mahdi@fidclic.com/breakdown?scope=all").json()["counts"]["total"] >= bk["counts"]["total"] - 40)

    print("\nListes personnalisables (types, priorités, fonctions)")
    L = "/api/admin/equipe/lists"
    tid = http("POST", f"{L}/types", json={"name": "Produit", "color": "#E11D48"}).json()["id"]
    x = new("Typée", 5, type_id=tid).json()["id"]
    check("a new type is usable", http("GET", f"/api/admin/equipe/tasks/{x}").json()["task"]["type"]["name"] == "Produit")
    check("no two types with one name", http("POST", f"{L}/types", json={"name": "produit"}).status_code == 409)
    check("a type can be renamed and recoloured", http("PUT", f"{L}/types/{tid}", json={"name": "Produit & app", "color": "#0EA5E9"}).status_code == 200
          and http("GET", f"/api/admin/equipe/tasks/{x}").json()["task"]["type"]["color"] == "#0EA5E9")
    ids = [t["id"] for t in http("GET", "/api/admin/equipe/board").json()["types"]]
    http("PUT", f"{L}/types/order", json={"ids": [tid] + [i for i in ids if i != tid]})
    check("…and put first", http("GET", "/api/admin/equipe/board").json()["types"][0]["id"] == tid)
    use = http("GET", f"{L}/types/{tid}/usage").json()
    check("its tasks are listed before deleting", any(t["id"] == x for t in use["tasks"]))
    check("deleting a used type without saying where its tasks go is refused",
          http("POST", f"{L}/types/{tid}/delete", json={}).status_code == 400)
    check("…and to a type that does not exist too", http("POST", f"{L}/types/{tid}/delete", json={"to": "nope"}).status_code == 400)
    y = new("Typée 2", 6, type_id=tid).json()["id"]
    r = http("POST", f"{L}/types/{tid}/delete", json={"to": "marketing", "moves": {y: "stock"}})
    check("divided: each task where it was sent", r.status_code == 200
          and http("GET", f"/api/admin/equipe/tasks/{x}").json()["task"]["type"]["id"] == "marketing"
          and http("GET", f"/api/admin/equipe/tasks/{y}").json()["task"]["type"]["id"] == "stock")
    check("…and the task's history says so", any("Produit" in e["text"] and "supprimé" in e["text"]
                                                for e in http("GET", f"/api/admin/equipe/tasks/{x}").json()["events"]))
    check("seven types again", len(http("GET", "/api/admin/equipe/board").json()["types"]) == 7)

    bd = http("GET", "/api/admin/equipe/board").json()
    check("three priorities to start, Moyenne the default", [p["id"] for p in bd["priorities"]] == ["haute", "moyenne", "basse"]
          and next(p for p in bd["priorities"] if p["default"])["id"] == "moyenne")
    urg = http("POST", f"{L}/priorities", json={"name": "Urgente", "color": "#7C3AED"}).json()["id"]
    z = new("Urgent", 7, priority=urg).json()["id"]
    zt = http("GET", f"/api/admin/equipe/tasks/{z}").json()["task"]
    check("a custom priority, with its colour", zt["priority_label"] == "Urgente" and zt["priority_color"] == "#7C3AED")
    nd = http("POST", "/api/admin/equipe/tasks", json={"title": "Sans priorité choisie", "assignees": ["mahdi@fidclic.com"],
                                                       "due_date": today.isoformat(), "due_time": "23:59"}).json()["id"]
    check("no priority chosen → the default", http("GET", f"/api/admin/equipe/tasks/{nd}").json()["task"]["priority"] == "moyenne")
    http("PUT", f"{L}/priorities/{urg}", json={"name": "Urgente", "default": True})
    check("the default can change", next(p for p in http("GET", "/api/admin/equipe/board").json()["priorities"] if p["default"])["id"] == urg)
    check("the board counts the custom priority", http("GET", "/api/admin/equipe/board").json()["counts"]["priority"].get(urg) == 1)
    check("deleting it needs a destination", http("POST", f"{L}/priorities/{urg}/delete", json={}).status_code == 400)
    http("POST", f"{L}/priorities/{urg}/delete", json={"to": "haute"})
    check("…its task moved, and the default passed on", http("GET", f"/api/admin/equipe/tasks/{z}").json()["task"]["priority"] == "haute"
          and next(p for p in http("GET", "/api/admin/equipe/board").json()["priorities"] if p["default"])["id"] == "haute")

    fon = {f["name"]: f["id"] for f in bd["fonctions"]}
    check("fonctions: a list to pick from (old free text joined it)", "Responsable" in fon and "Administratrice" in fon)
    cm = http("POST", f"{L}/fonctions", json={"name": "Community manager"}).json()["id"]
    http("PUT", "/api/admin/equipe/members/meriem@fidclic.com", json={"email": "meriem@fidclic.com", "fonction_id": cm})
    row = lambda e: next(m for m in http("GET", "/api/admin/equipe/board").json()["members"] if m["email"] == e)   # noqa: E731
    check("a member takes a fonction from the list", row("meriem@fidclic.com")["fonction"] == "Community manager")
    http("PUT", f"{L}/fonctions/{cm}", json={"name": "Community manager senior"})
    check("renaming a fonction renames it on every member", row("meriem@fidclic.com")["fonction"] == "Community manager senior")
    check("deleting a fonction someone holds needs a replacement", http("POST", f"{L}/fonctions/{cm}/delete", json={}).status_code == 400)
    http("POST", f"{L}/fonctions/{cm}/delete", json={"to": fon["Marketing"]})
    check("…then they take it", row("meriem@fidclic.com")["fonction"] == "Marketing")

    print("\nÉquipe : ordre, retrait avec reprise des tâches")
    http("PUT", "/api/admin/equipe/members/order", json={"ids": ["meriem@fidclic.com", "mahdi@fidclic.com", "boss@fidclic.com"]})
    check("members can be reordered", [m["email"] for m in http("GET", "/api/admin/equipe/board").json()["members"]][0] == "meriem@fidclic.com")
    solo = new("À reprendre", 30, who=("meriem@fidclic.com",)).json()["id"]
    fin = new("Déjà finie", 31, who=("meriem@fidclic.com",)).json()["id"]
    http("POST", f"/api/admin/equipe/tasks/{fin}/complete", json={"done": True})
    duo = new("À deux", 30, who=("meriem@fidclic.com", "mahdi@fidclic.com")).json()["id"]
    u = http("GET", "/api/admin/equipe/members/meriem@fidclic.com/usage").json()
    check("before removing: what only they hold, and what they share", u["sole"] >= 1 and u["shared"] >= 1)
    check("removing without handing over is refused", http("POST", "/api/admin/equipe/members/meriem@fidclic.com/remove", json={}).status_code == 400)
    r = http("POST", "/api/admin/equipe/members/meriem@fidclic.com/remove", json={"to": ["boss@fidclic.com"], "moves": {solo: ["mahdi@fidclic.com"]}})
    check("handed over task by task; on a shared task she just steps out", r.status_code == 200
          and [a["email"] for a in http("GET", f"/api/admin/equipe/tasks/{solo}").json()["task"]["assignees"]] == ["mahdi@fidclic.com"]
          and [a["email"] for a in http("GET", f"/api/admin/equipe/tasks/{duo}").json()["task"]["assignees"]] == ["mahdi@fidclic.com"])
    check("she is off the board, her finished tasks keep her name",
          "meriem@fidclic.com" not in {m["email"] for m in http("GET", "/api/admin/equipe/board").json()["members"]}
          and "meriem@fidclic.com" in [a["email"] for a in http("GET", f"/api/admin/equipe/tasks/{fin}").json()["task"]["assignees"]])
    check("the new holder is told", any("À reprendre" in a["title"] for a in http("GET", "/api/admin/equipe/alerts", MAHDI).json()["alerts"]))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
