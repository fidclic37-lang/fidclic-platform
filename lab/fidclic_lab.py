"""
FidClic Lab — learn from one shop's anonymous export, on a laptop
(user, 2026-10-29: « Royal Trim Liberté ka data se seekhna … production pe
nahi, read-only export pe »; what is learned may improve every barber).

    1. Super admin › Commerces › the shop › ⋯ › « Export anonymisé (FidClic Lab) »
       saves fidclic-lab-<activity>-<date>.json (api/features/lab_export.py).
    2. Put it in lab/data/ (git ignores it), then:
           /usr/local/bin/python3 lab/fidclic_lab.py lab/data/<file>.json
    3. Read lab/out/<activity>-<date>/report.md; proposals.json holds the
       numbers a later PR may put into services/activities.py for the trade.

Nothing here touches a database: the export is read from the file, the
brain's own code (features/client_brain, brain_journal) replays it in memory.

WHAT IT MEASURES
    health      clients, regulars (3 visit days or more), visits, stores, span
    rhythm      each regular's own rhythm (median of their gaps between Paris
                days), then the shop's median and quantiles; by store; by the
                service a client usually takes (« Coupe », « Coupe + Barbe »)
    prior_grid  the brain's backtest replayed with several starting rhythms:
                which start predicts the next visit best (median error, % in
                the window) — beside today's figure for the activity
    windows     « client actif » = 80 % of regulars' rhythms, « inactif » = 90 %
    busy        visits by weekday and hour, Paris time
    campaigns   came back within 15 days: messaged vs témoin, in points
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, "..", "api")
PARIS = ZoneInfo("Europe/Paris")
MIN_REGULARS = 5            # fewer: numbers are shown, nothing is proposed
MIN_ITEM_CLIENTS = 5        # a service needs this many regulars to get its own rhythm
HABIT_SHARE = 0.4           # the service in 4 visits in 10 is the client's usual one
WINDOW_DAYS = 15            # « came back after a message » (CA FidClic)
GRID = (0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0)


def _brain():
    """The brain's own code, without a database."""
    if API not in sys.path:
        sys.path.insert(0, API)
    os.environ.setdefault("JWT_SECRET", "fidclic-lab-local")
    from features import brain_journal as BJ
    from features import client_brain as CB
    from services import activities as A
    return CB, BJ, A


def _at(v: Any) -> Optional[datetime]:
    if not isinstance(v, str) or not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _q(vals: List[float], p: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def _days(visits: List[datetime]) -> List[datetime]:
    """One visit per Paris day (the first), in order."""
    out: List[datetime] = []
    for t in sorted(visits):
        if not out or t.astimezone(PARIS).date() != out[-1].astimezone(PARIS).date():
            out.append(t)
    return out


def _gaps(days: List[datetime]) -> List[float]:
    return [(days[i].astimezone(PARIS).date() - days[i - 1].astimezone(PARIS).date()).days
            for i in range(1, len(days))]


# ---------------------------------------------------------------------------
def analyse(data: Dict[str, Any], at: Optional[datetime] = None) -> Dict[str, Any]:
    at = at or _at(data.get("exported_at")) or datetime.now(timezone.utc)
    shop = data.get("shop") or {}
    activity = shop.get("activity") or "autre"
    customers = {c["c"]: c for c in data.get("customers") or [] if isinstance(c, dict) and c.get("c")}

    # the visits, by client (broken rows skipped)
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for v in data.get("visits") or []:
        t = _at((v or {}).get("at"))
        if t and v.get("c"):
            by[v["c"]].append({**v, "t": t})
    n_visits = sum(len(x) for x in by.values())

    # each regular's own rhythm
    own: Dict[str, float] = {}
    for c, vs in by.items():
        g = _gaps(_days([v["t"] for v in vs]))
        if len(g) >= 2:
            own[c] = float(median(g))
    rh = list(own.values())
    rhythm = {"regulars": len(rh), "median": (round(median(rh), 1) if rh else None),
              **{k: _q(rh, p) for k, p in (("p25", .25), ("p75", .75), ("p80", .8), ("p90", .9))}}

    def store_of(c: str) -> Optional[str]:
        s = (customers.get(c) or {}).get("store")
        if s:
            return s
        most = Counter(v.get("store") for v in by.get(c, []) if v.get("store")).most_common(1)
        return most[0][0] if most else None

    per_store: Dict[str, List[float]] = defaultdict(list)
    per_item: Dict[str, List[float]] = defaultdict(list)
    for c, g in own.items():
        s = store_of(c)
        if s:
            per_store[s].append(g)
        with_items = [v for v in by[c] if v.get("items")]
        if with_items:
            # each service counted once per visit
            names = Counter(n for v in with_items
                            for n in {str(i["name"]) for i in v["items"] if isinstance(i, dict) and i.get("name")})
            top = names.most_common(1)
            if top and top[0][1] / len(with_items) >= HABIT_SHARE:
                per_item[top[0][0]].append(g)
    rhythm_by_store = {s: {"median": round(median(g), 1), "clients": len(g)} for s, g in per_store.items()}
    rhythm_by_item = {k: {"median": round(median(g), 1), "clients": len(g)}
                      for k, g in per_item.items() if len(g) >= MIN_ITEM_CLIENTS}

    # which starting rhythm the brain predicts best from (its own backtest)
    CB, BJ, A = _brain()
    current = float((A.BY_KEY.get(activity) or A.BY_KEY["autre"])["gap"])
    grid: List[Dict[str, Any]] = []
    if rh:
        cands = sorted({max(2, round(current * f)) for f in GRID} | {round(rhythm["median"])})
        rule = int(shop.get("rule_days") or 30)
        for prior in cands:
            hist = {c: [{"visit_time": v["t"], "amount_paid": v.get("amount"), "branch_id": v.get("store"),
                         "items": [{"name": i.get("name"), "qty": i.get("qty") or 1} for i in v.get("items") or []
                                   if isinstance(i, dict)]} for v in vs] for c, vs in by.items()}
            rows, _counts = BJ._replay("lab", str(shop.get("sector") or "other"), float(prior), rule, hist, at)
            s = BJ.summarise(rows)
            if s["checked"]:
                grid.append({"prior": prior, "checked": s["checked"], "median_error": s["brain"]["median_error"],
                             "in_window": s["in_window"], "near": s["brain"]["near"]})
    best = min(grid, key=lambda g: (g["median_error"], -(g["in_window"] or 0)))["prior"] if grid else None

    windows = {"active_days": round(rhythm["p80"]) if rh else None,
               "inactive_after_days": round(rhythm["p90"]) if rh else None}

    wd, hr = Counter(), Counter()
    for vs in by.values():
        for v in vs:
            p = v["t"].astimezone(PARIS)
            wd[p.weekday()] += 1
            hr[p.hour] += 1
    busy = {"weekday": [wd.get(i, 0) for i in range(7)], "hour": [hr.get(i, 0) for i in range(24)],
            "top_weekday": wd.most_common(1)[0][0] if wd else None, "top_hour": hr.most_common(1)[0][0] if hr else None}

    campaigns = _campaigns(data.get("campaigns") or [], by)

    proposals = None
    if len(rh) >= MIN_REGULARS:
        proposals = {"activity": activity, "basis": "données", "gap_days": round(rhythm["median"]),
                     "today_gap_days": current, "best_start_days": best,
                     "active_days": windows["active_days"], "inactive_after_days": windows["inactive_after_days"],
                     "gap_by_item": {k: round(v["median"]) for k, v in rhythm_by_item.items()},
                     "send": {"weekday": busy["top_weekday"], "hour": busy["top_hour"]},
                     "evidence": {"regulars": len(rh), "visits": n_visits, "stores": len(rhythm_by_store),
                                  "exported_at": data.get("exported_at")}}

    return {"activity": activity, "at": at.isoformat(),
            "health": {"clients": len(customers), "regulars": len(rh), "visits": n_visits,
                       "stores": len(shop.get("stores") or []) or len(per_store),
                       "first": min((v["t"] for vs in by.values() for v in vs), default=None),
                       "last": max((v["t"] for vs in by.values() for v in vs), default=None)},
            "rhythm": rhythm, "rhythm_by_store": rhythm_by_store, "rhythm_by_item": rhythm_by_item,
            "current": {"activity_gap": current}, "prior_grid": grid, "best_prior": best,
            "windows": windows, "busy": busy, "campaigns": campaigns, "proposals": proposals}


def _campaigns(rows: List[Dict[str, Any]], by: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    out = []
    pool = {"sent": [0, 0], "held": [0, 0]}
    for c in rows:
        sent_at = _at((c or {}).get("sent_at"))
        if not sent_at:
            continue
        end = sent_at + timedelta(days=WINDOW_DAYS)

        def came(ids):
            return sum(1 for x in ids if any(sent_at < v["t"] <= end for v in by.get(x, [])))
        s_ids, h_ids = list(c.get("recipients") or []), list(c.get("holdout") or [])
        s_came, h_came = came(s_ids), came(h_ids)
        sp = round(100 * s_came / len(s_ids)) if s_ids else None
        hp = round(100 * h_came / len(h_ids)) if h_ids else None
        out.append({"id": c.get("id"), "kind": c.get("kind"), "sent": len(s_ids), "held": len(h_ids),
                    "sent_pct": sp, "held_pct": hp,
                    "uplift_pts": (sp - hp) if sp is not None and hp is not None else None})
        if h_ids:
            pool["sent"][0] += s_came; pool["sent"][1] += len(s_ids)
            pool["held"][0] += h_came; pool["held"][1] += len(h_ids)
    tot = None
    if pool["held"][1] and pool["sent"][1]:
        tot = round(100 * pool["sent"][0] / pool["sent"][1]) - round(100 * pool["held"][0] / pool["held"][1])
    return {"rows": out, "uplift_pts": tot, "measured": sum(1 for r in out if r["uplift_pts"] is not None)}


# ---------------------------------------------------------------------------
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _md(rep: Dict[str, Any]) -> str:
    h, r, p = rep["health"], rep["rhythm"], rep["proposals"]
    fmt = lambda v, u=" j": "—" if v is None else f"{v}{u}"  # noqa: E731
    lines = [f"# FidClic Lab — {rep['activity']}", "",
             f"Export du {(h['last'] or rep['at'])!s:.10}. {h['clients']} clients, {h['regulars']} habitués "
             f"(3 jours de visite ou plus), {h['visits']} visites, {h['stores']} établissement(s).", "",
             "## Rythme des habitués", "",
             f"Médiane {fmt(r['median'])} · p25 {fmt(r['p25'])} · p75 {fmt(r['p75'])} · p80 {fmt(r['p80'])} · p90 {fmt(r['p90'])}",
             f"Chiffre actuel de l'activité : {fmt(rep['current']['activity_gap'])}.", ""]
    if rep["rhythm_by_item"]:
        lines += ["Par prestation habituelle :", ""] + [f"- {k} : {fmt(v['median'])} ({v['clients']} habitués)"
                                                         for k, v in sorted(rep["rhythm_by_item"].items())] + [""]
    if rep["rhythm_by_store"]:
        lines += ["Par établissement (codes de l'export) :", ""] + [f"- {k} : {fmt(v['median'])} ({v['clients']} habitués)"
                                                                     for k, v in sorted(rep["rhythm_by_store"].items())] + [""]
    lines += ["## Point de départ du cerveau (backtest)", "",
              "| Départ | Vérifiées | Erreur médiane | Dans la fenêtre | ±3 j |", "|---|---|---|---|---|"]
    lines += [f"| {g['prior']} j{' ✓' if g['prior'] == rep['best_prior'] else ''} | {g['checked']} | {fmt(g['median_error'])} "
              f"| {fmt(g['in_window'], ' %')} | {fmt(g['near'], ' %')} |" for g in rep["prior_grid"]]
    w, b = rep["windows"], rep["busy"]
    lines += ["", "## Fenêtres", "", f"Client actif : {fmt(w['active_days'])} (80 % des habitués) · "
              f"inactif après {fmt(w['inactive_after_days'])} (90 %).", "", "## Moments", "",
              f"Jour le plus chargé : {JOURS[b['top_weekday']] if b['top_weekday'] is not None else '—'} · "
              f"heure : {fmt(b['top_hour'], ' h')} (heure de Paris).", "", "## Campagnes et groupe témoin", ""]
    rows = rep["campaigns"]["rows"]
    if rows:
        lines += ["| Campagne | Envoyés | Témoin | Revenus (15 j) | Témoin revenus | Écart |", "|---|---|---|---|---|---|"]
        gap = lambda c: "non mesuré" if c["uplift_pts"] is None else f"{c['uplift_pts']:+d} pts"  # noqa: E731
        lines += [f"| {c['kind'] or '—'} | {c['sent']} | {c['held']} | {fmt(c['sent_pct'], ' %')} | {fmt(c['held_pct'], ' %')} "
                  f"| {gap(c)} |" for c in rows]
    else:
        lines.append("Aucune campagne envoyée.")
    lines += ["", "## Propositions", ""]
    lines.append("Pas assez d'habitués pour proposer des chiffres." if not p else
                 "```json\n" + json.dumps(p, ensure_ascii=False, indent=2, default=str) + "\n```")
    return "\n".join(lines) + "\n"


def write(rep: Dict[str, Any], out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(_md(rep))
    with open(os.path.join(out_dir, "proposals.json"), "w", encoding="utf-8") as f:
        json.dump(rep["proposals"] or {}, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(out_dir, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2, default=str)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="FidClic Lab: learn from an anonymous export")
    ap.add_argument("export")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    with open(a.export, encoding="utf-8") as f:
        data = json.load(f)
    rep = analyse(data)
    out = a.out or os.path.join(HERE, "out", f"{rep['activity']}-{rep['at'][:10]}")
    write(rep, out)
    p = rep["proposals"] or {}
    print(f"{rep['health']['regulars']} habitués · rythme {rep['rhythm']['median']} j "
          f"(aujourd'hui {rep['current']['activity_gap']} j) · meilleur départ {rep['best_prior']} j → {out}")
    if not p:
        print("Pas assez d'habitués pour proposer des chiffres.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
