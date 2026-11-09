"""
Golden set de FidClic IA — the REAL model (user, 2026-11-03).

Boots the API on an in-memory database (never a real one, never a real
merchant), seeds the demo shops, asks every question through the real
endpoints as its account, grades each answer and writes:

    <out>/golden-report.json   what Super admin › FIDCLIC AI › Golden set shows
    <out>/summary.md           the score per type and every failed question

Exit 0 only at 100 % (user: « Sab 100 % »). The run's own AI meter stops it
at GOLDEN_MAX_EUR (8 € by default: about 6 € with the Copilote on Opus).

Run (a key in the environment, the same model as production):
    ANTHROPIC_API_KEY=… LLM_MODEL=… python3 scripts/golden_run.py [--only chiffres-01,pieges-03] [--out golden-report]
    python3 scripts/golden_run.py --fake        # the runner itself, with a fake model: costs nothing
CI: .github/workflows/golden-set.yml (a PR labelled « ai », or « Lancer »).
"""
import argparse
import asyncio
import contextlib
import io
import json
import os
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import mongomock  # noqa: E402
import pymongo  # noqa: E402

pymongo.MongoClient = mongomock.MongoClient        # never a real database
os.environ.pop("MONGODB_URI", None)
os.environ.setdefault("JWT_SECRET", secrets.token_hex(16))
os.environ["DISABLE_SEED"] = "1"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="question ids, comma separated")
    ap.add_argument("--out", default="golden-report")
    ap.add_argument("--fake", action="store_true", help="a fake model giving the right answers: checks the runner, costs nothing")
    ap.add_argument("--real", action="store_true",
                    help="also the shops' own data, anonymized (GOLDEN_SNAPSHOT_KEY; reported without a figure)")
    a = ap.parse_args()

    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import httpx
    from features import golden_set as GS
    from services import llm

    if a.fake:
        llm._force_complete = GS.fake_model
    elif not llm.is_configured():
        print("Aucune clé d'IA (ANTHROPIC_API_KEY, GROQ_API_KEY…) : le golden set a besoin du vrai modèle.")
        return 2
    cap = float(os.environ.get("GOLDEN_MAX_EUR") or 8)
    server.db.platform_settings.update_one({"key": "ai_meter"}, {"$set": {
        "cap_mode": "fixed", "global_day_eur": cap, "shop_day_eur": cap, "user_per_min": 100000,
        "plan_budgets": {"silver": cap, "gold": cap, "vip": cap, "franchise": cap}}}, upsert=True)

    from features import ai_routing
    ai_routing.apply_routes(os.environ.get("GOLDEN_ROUTES"))    # « Lancer »: the table production is on

    loop = asyncio.new_event_loop()

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://golden",
                                         timeout=180) as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return loop.run_until_complete(run())

    only = [x.strip() for x in a.only.split(",") if x.strip()] or None
    rep = GS.run_all(http, only=only)
    real_md, real_ok = "", True
    if a.real and not only:
        real_md, real_ok, rep["real"] = _real(server, http)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "golden-report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    md = GS.markdown(rep) + ("\n" + real_md if real_md else "")
    with open(os.path.join(a.out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    return 0 if rep["ok"] and real_ok else 1


def _real(server, http):
    """The shops' own data (features/golden_real): downloaded with GitHub's key,
    loaded in this in-memory database, never written to disk, reported without
    a figure — this repository and its Actions are public."""
    import gzip
    import urllib.request
    from features import golden_real as GR
    key = (os.environ.get("GOLDEN_SNAPSHOT_KEY") or "").strip()
    base = (os.environ.get("GOLDEN_SNAPSHOT_URL") or "https://app.fidclic.com").rstrip("/")
    if not key:
        return "_Données réelles : pas de clé GOLDEN_SNAPSHOT_KEY, non testées._\n", True, None

    def get(path):
        req = urllib.request.Request(base + path, headers={"X-Golden-Key": key, "User-Agent": "fidclic-golden-set"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    try:
        shops = json.loads(get("/api/golden/real"))["shops"]
        loaded = [GR.load(server.db, json.loads(gzip.decompress(get(f"/api/golden/real/{s['sid']}"))), i + 1)
                  for i, s in enumerate(shops)]
    except Exception as exc:                      # noqa: BLE001 — said, and the run fails: a real test that did not happen
        return f"❌ Données réelles : téléchargement impossible ({type(exc).__name__}).\n", False, None
    if not loaded:
        return "_Données réelles : aucun commerce prêt (le fichier se fait la nuit)._\n", True, None
    rep = GR.run(http, server.db, loaded)
    return GR.markdown(rep), rep["ok"], GR.public(rep)


if __name__ == "__main__":
    sys.exit(main())
