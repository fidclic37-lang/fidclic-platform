"""
FidClic Lab — what the lab learns from an anonymous export (lab/fidclic_lab.py),
run on a laptop, never on production (user, 2026-10-29).

Built on a made-up barber whose answers are known: « Coupe » clients come
back every 21 days, « Coupe + Barbe » every 14, mostly on Saturdays; a
campaign brought 60 % of its clients back against 30 % of its témoin.

Run: cd api && /usr/local/bin/python3 tests/test_lab_runner.py
"""
import datetime as dt
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "lab"))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-lab-runner")
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", show)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def iso(d):
    return d.astimezone(UTC).isoformat()


def made_up(at):
    """60 regulars over ~10 months, 2 stores, one campaign with a témoin."""
    customers, visits = [], []
    sat = at - dt.timedelta(days=(at.weekday() - 5) % 7)          # last Saturday
    sat = sat.replace(hour=9, minute=0, second=0, microsecond=0)   # 10:00 / 11:00 Paris
    for i in range(60):
        beard = i >= 40
        gap = 14 if beard else 21
        item = "Coupe + Barbe" if beard else "Coupe"
        store = "S1" if i % 2 else "S2"
        customers.append({"c": f"k{i}", "store": store, "created_at": iso(at - dt.timedelta(days=320)),
                          "source": "qr", "age": 30, "gender": "homme"})
        # back from the newest visit, every `gap` days, sometimes a day off
        t = sat - dt.timedelta(days=7 * (i % 3))
        for n in range(12 if beard else 9):
            jitter = (0, 0, 1, 0, -1)[(i + n) % 5]      # 3 visits in 5 on the Saturday
            visits.append({"c": f"k{i}", "store": store, "at": iso(t + dt.timedelta(days=jitter)),
                           "amount": 25.0 if beard else 18.0,
                           "items": [{"id": "x", "name": item, "qty": 1, "price": 25.0 if beard else 18.0}]})
            t -= dt.timedelta(days=gap)
    # a campaign 40 days ago: 20 messaged (12 came within 15 days), 10 témoin (3 came)
    sent_at = at - dt.timedelta(days=40)
    rec = [f"z{i}" for i in range(20)]
    hold = [f"h{i}" for i in range(10)]
    for j, c in enumerate(rec + hold):
        customers.append({"c": c, "store": "S1", "created_at": iso(at - dt.timedelta(days=300))})
        came = (j < 12) if j < 20 else (j - 20 < 3)
        visits.append({"c": c, "store": "S1", "at": iso(sent_at - dt.timedelta(days=60)), "amount": 18.0, "items": []})
        if came:
            visits.append({"c": c, "store": "S1", "at": iso(sent_at + dt.timedelta(days=5)), "amount": 20.0, "items": []})
    camp = {"id": "cA", "kind": "offre", "template": "ia", "status": "sent", "sent_at": iso(sent_at),
            "recipients": rec, "holdout": hold, "content": "Bonjour {prénom}"}
    return {"format": "fidclic-lab/1", "exported_at": iso(at),
            "shop": {"activity": "barbier", "sector": "salon", "programme": "stamps",
                     "stores": [{"id": "S1"}, {"id": "S2"}], "rule_days": 30},
            "customers": customers, "visits": visits, "campaigns": [camp], "automation_log": [], "push": []}


def main():
    import fidclic_lab as LAB

    at = dt.datetime(2026, 10, 20, 12, tzinfo=UTC)
    data = made_up(at)
    rep = LAB.analyse(data, at=at)

    print("Santé des données")
    h = rep["health"]
    check("clients, regulars, visits and stores counted",
          h["clients"] == 90 and h["regulars"] == 60 and h["visits"] == len(data["visits"]) and h["stores"] == 2, h)

    print("\nLe rythme")
    r = rep["rhythm"]
    check("the regulars' rhythm: median 21 days", abs(r["median"] - 21) <= 1, r)
    check("quantiles ordered (p25 ≤ median ≤ p75 ≤ p80 ≤ p90)",
          r["p25"] <= r["median"] <= r["p75"] <= r["p80"] <= r["p90"], r)
    by_item = rep["rhythm_by_item"]
    check("« Coupe » ≈ 21 days, « Coupe + Barbe » ≈ 14 days",
          abs(by_item["Coupe"]["median"] - 21) <= 1 and abs(by_item["Coupe + Barbe"]["median"] - 14) <= 1
          and by_item["Coupe"]["clients"] == 40 and by_item["Coupe + Barbe"]["clients"] == 20, by_item)
    check("per store too", set(rep["rhythm_by_store"]) == {"S1", "S2"})

    print("\nLe meilleur point de départ (backtest)")
    grid = rep["prior_grid"]
    check("each candidate is replayed and judged", len(grid) >= 5 and all(g["checked"] > 0 for g in grid), grid[:2])
    check("the best start lies among the candidates", rep["best_prior"] in [g["prior"] for g in grid])
    best = min(grid, key=lambda g: (g["median_error"], -g["in_window"]))
    check("…and it is the one with the smallest error", rep["best_prior"] == best["prior"])
    check("today's figure for the activity is shown beside it (Barbier: 21)", rep["current"]["activity_gap"] == 21)

    print("\nFenêtres et moments")
    w = rep["windows"]
    check("« client actif » covers 80 % of returns, « inactif » 90 %",
          w["active_days"] == round(r["p80"]) and w["inactive_after_days"] == round(r["p90"]), w)
    check("busiest weekday: Saturday (Paris)", rep["busy"]["top_weekday"] == 5, rep["busy"])
    check("busiest hours in Paris time (10–11 h)", rep["busy"]["top_hour"] in (10, 11), rep["busy"]["top_hour"])

    print("\nCampagnes et témoin")
    c = rep["campaigns"]["rows"][0]
    check("came back within 15 days: 60 % messaged vs 30 % témoin → +30 points",
          c["sent_pct"] == 60 and c["held_pct"] == 30 and c["uplift_pts"] == 30, c)
    check("a campaign without témoin says « non mesuré »",
          LAB.analyse({**data, "campaigns": [{**data["campaigns"][0], "holdout": []}]}, at=at)["campaigns"]["rows"][0]["uplift_pts"] is None)

    print("\nPropositions")
    p = rep["proposals"]
    check("proposals for the activity: rhythm, windows, per service, best moment",
          p["activity"] == "barbier" and p["gap_days"] == round(r["median"]) and p["active_days"] == w["active_days"]
          and p["gap_by_item"]["Coupe + Barbe"] == round(by_item["Coupe + Barbe"]["median"]) and p["send"]["weekday"] == 5, p)
    check("each proposal says how many regulars it stands on", p["evidence"]["regulars"] == 60)

    print("\nFichiers")
    out = tempfile.mkdtemp()
    LAB.write(rep, out)
    md = open(os.path.join(out, "report.md"), encoding="utf-8").read()
    pj = json.load(open(os.path.join(out, "proposals.json"), encoding="utf-8"))
    check("report.md and proposals.json written", "Rythme" in md and pj["activity"] == "barbier")
    check("no client code in the report", not re.search(r"\bk\d+\b", md))
    src = os.path.join(out, "export.json")
    json.dump(data, open(src, "w", encoding="utf-8"))
    out2 = os.path.join(out, "run2")
    check("the command line runs on a file", LAB.main([src, "--out", out2]) == 0
          and os.path.exists(os.path.join(out2, "proposals.json")))

    print("\nCas limites")
    empty = LAB.analyse({"shop": {"activity": "barbier"}, "customers": [], "visits": [], "campaigns": []}, at=at)
    check("an empty export: zeros and no proposal, no crash",
          empty["health"]["visits"] == 0 and empty["proposals"] is None and empty["prior_grid"] == [])
    one = LAB.analyse({"shop": {"activity": "barbier"}, "customers": [{"c": "a"}],
                       "visits": [{"c": "a", "at": iso(at)}], "campaigns": []}, at=at)
    check("one client, one visit: no rhythm, no crash", one["rhythm"]["median"] is None and one["proposals"] is None)
    # DST: 23:30 UTC on 28/03 is 00:30 Paris on the 29th, the same Paris day as 09:00 UTC on the 29th
    dst = [{"c": "d", "at": "2026-03-28T23:30:00+00:00"}, {"c": "d", "at": "2026-03-29T09:00:00+00:00"},
           {"c": "d", "at": "2026-04-19T09:00:00+00:00"}, {"c": "d", "at": "2026-05-10T09:00:00+00:00"}]
    d = LAB.analyse({"shop": {"activity": "barbier"}, "customers": [{"c": "d"}], "visits": dst, "campaigns": []}, at=at)
    check("visit days are Paris days (summer time night): 3 days, rhythm 21", d["health"]["regulars"] == 1
          and d["rhythm"]["median"] == 21, d["rhythm"])
    bad = LAB.analyse({"shop": {}, "customers": [], "visits": [{"c": "x", "at": "pas une date"}, {"c": None, "at": None}],
                       "campaigns": [{"id": "q", "sent_at": None}]}, at=at)
    check("broken rows are skipped, not fatal", bad["health"]["visits"] == 0)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
