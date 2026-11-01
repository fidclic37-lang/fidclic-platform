"""
FidClic IA — QA F05 (2026-10-08): « aujourd'hui ? » and « les 7 derniers
jours ? » were both answered « Sur 30 jours », 12,50 € read « 12 € », « 1
visites », and a failing Groq never handed over to NVIDIA.

Run: cd api && /usr/local/bin/python3 tests/test_copilot_period.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-copilot-period")
os.environ.setdefault("DISABLE_SEED", "1")
for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY", "LLM_PROVIDER", "LLM_MODEL"):
    os.environ.pop(k, None)
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    import features.copilot as K
    import features.insights_page as E
    from services import llm
    db = server.db
    K._db = db
    E._db = db
    now = dt.datetime(2026, 10, 8, 14, 30, tzinfo=dt.timezone.utc)      # 16:30 in Paris, a Thursday
    K._now = lambda: now
    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "Le Petit Café", "sector": "cafe", "plan": "vip"})
    db.customers.insert_many([{"id": f"c{i}", "tenant_id": "t1", "name": f"C{i}", "visits": 3,
                               "created_at": now - dt.timedelta(days=60)} for i in range(3)])
    visits = [(dt.timedelta(hours=2), 12.5, "c0"),                           # today
              (dt.timedelta(days=1, hours=1), 20.0, "c1"),                   # yesterday, same time-ish
              (dt.timedelta(days=3), 30.0, "c1"), (dt.timedelta(days=5), 8.25, "c2"),
              (dt.timedelta(days=20), 40.0, "c2")]
    for i, (ago, amount, cid) in enumerate(visits):
        db.visits.insert_one({"id": f"v{i}", "tenant_id": "t1", "customer_id": cid, "amount_paid": amount,
                              "visit_time": now - ago})

    class T:
        email, role, tenant_id = "o@x", "business_owner", "t1"

    print("\nLa période de la question")
    lab = lambda q: K.period_of(q, now)["label"]          # noqa: E731
    check("aujourd'hui", lab("Comment ça va aujourd'hui ?") == "aujourd'hui")
    check("hier", lab("et hier ?") == "hier")
    check("les 7 derniers jours", lab("Résume les 7 derniers jours") == "les 7 derniers jours")
    check("cette semaine (since Monday)", lab("cette semaine ?") == "cette semaine"
          and K.period_of("cette semaine", now)["start"].astimezone(K.PARIS).strftime("%a %H:%M") == "Mon 00:00")
    check("ce mois-ci, compared with the same days of last month", lab("ce mois") == "ce mois-ci"
          and K.period_of("ce mois", now)["prev_start"].astimezone(K.PARIS).strftime("%d/%m") == "01/09")
    check("le mois dernier (a calendar month)", lab("le mois dernier") == "le mois dernier"
          and K.period_of("le mois dernier", now)["start"].astimezone(K.PARIS).strftime("%d/%m %H:%M") == "01/09 00:00")
    check("3 mois", lab("sur 3 mois") == "les 3 derniers mois")
    check("nothing said: 30 days, and not « explicit »", lab("mes chiffres") == "les 30 derniers jours"
          and not K.period_of("mes chiffres", now)["explicit"])
    today = K.period_of("aujourd'hui", now)
    check("today is from midnight in Paris, against yesterday at the same hour",
          today["start"].astimezone(K.PARIS).strftime("%H:%M") == "00:00"
          and (today["end"] - today["prev_end"]) == dt.timedelta(days=1))

    print("\nLes chiffres et leur écriture")
    f = K.period_figures("t1", today)
    check(f"today: 1 visit, 12.50 € ({f['visits']}, {f['revenue']})", f["visits"] == 1 and f["revenue"] == 12.5)
    check("12,50 € written to the cent", K._eur_exact(12.5) == "12,50 €" and K._eur_exact(1234.1) == "1 234,10 €")
    check("1 visite, 2 visites", K._pl(1, "visite", "visites") == "1 visite" and K._pl(2, "visite", "visites") == "2 visites")

    print("\nLe chat sans modèle (réponse des données)")
    llm._force_complete = None
    out = K.chat(K.ChatIn(message="Et aujourd'hui ?"), token_data=T())
    check(f"« aujourd'hui » answered for today ({out['reply']!r})",
          out["source"] == "facts" and out["reply"].startswith("Aujourd'hui : 1 visite et 12,50 €"))
    check("…not « Sur 30 jours »", "30 jours" not in out["reply"])
    out = K.chat(K.ChatIn(message="Mes résultats des 7 derniers jours"), token_data=T())
    check(f"« 7 derniers jours » → 4 visits, 70,75 € ({out["reply"]!r})",
          out["reply"].startswith("Les 7 derniers jours : 4 visites et 70,75 €"))
    check("…with the real average basket", "panier moyen 17,69 €" in out["reply"])
    check("the analytics button comes with it", out["actions"] and out["actions"][0].get("to") == "/dashboard/analytics")

    print("\nLe chat avec le modèle")
    seen = {}

    def model(system, user):
        seen["s"], seen["u"] = system, user
        return "Aujourd'hui : 1 visite."
    llm._force_complete = model
    K.chat(K.ChatIn(message="Comment s'est passée la journée d'aujourd'hui ?"), token_data=T())
    check("the model gets the asked period and its figures",
          '"periode_demandee"' in seen["u"] and '"libelle": "aujourd\'hui"' in seen["u"] and '"chiffre_affaires_eur": 12.5' in seen["u"])
    check("and is told to answer for it, to the cent, with plurals",
          "periode_demandee" in seen["s"] and "12,50 €" in seen["s"] and "1 visite" in seen["s"])
    llm._force_complete = None

    print("\nUn fournisseur qui échoue passe la main")
    os.environ["GROQ_API_KEY"], os.environ["NVIDIA_API_KEY"] = "x", "y"
    calls = []
    real = llm._call

    def fake(name, model, system, user, max_tokens, temperature, *meter):
        calls.append(name)
        return (None, "HTTP 500") if name == "groq" else (f"réponse de {name}", None)
    llm._call = fake
    check("Groq fails → NVIDIA answers", llm.complete("s", "u") == "réponse de nvidia" and calls == ["groq", "nvidia"])
    calls.clear()
    os.environ.pop("NVIDIA_API_KEY")
    check("a provider without a key is skipped, and nothing answering is None",
          llm.complete("s", "u") is None and calls == ["groq"])
    check("any key counts as configured", llm.is_configured())
    os.environ.pop("GROQ_API_KEY")
    check("no key at all: not configured", not llm.is_configured())
    os.environ["ANTHROPIC_API_KEY"], os.environ["LLM_MODEL"] = "z", "meta-llama/llama-4-scout-17b-16e-instruct"
    calls.clear()
    seen_models = []

    def fake2(name, model, system, user, max_tokens, temperature, *meter):
        seen_models.append((name, model))
        return "ok", None
    llm._call = fake2
    llm.complete("s", "u")
    check("a Groq model left in LLM_MODEL is not sent to Claude", seen_models == [("anthropic", "claude-sonnet-5-5")])
    seen_models.clear()
    os.environ["LLM_MODEL"] = "claude-old-name"

    def fake3(name, model, system, user, max_tokens, temperature, *meter):
        seen_models.append(model)
        return (None, "HTTP 404") if model == "claude-old-name" else ("ok", None)
    llm._call = fake3
    check("a chosen model that fails is retried once with the default",
          llm.complete("s", "u") == "ok" and seen_models == ["claude-old-name", "claude-sonnet-5-5"])
    for k in ("ANTHROPIC_API_KEY", "LLM_MODEL"):
        os.environ.pop(k, None)
    llm._call = real

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
