"""
Super admin › FIDCLIC AI Intelligence — built to the approved mockup.

Every answer is an analysis computed from the platform's real data, so the
figures are exact; the language model (services.llm, when configured) only
understands a free question and, for questions outside the analyses, answers
from the platform's aggregated figures. Without a model, questions are
understood by their keywords.

Analyses (« Analyses rapides »): commerces à risque, proches de leur limite,
opportunités d'upgrade, secteurs les plus performants, commerces sans
campagne, commerces inactifs (30 jours), comparaison par secteur,
recommandations stratégiques. Each returns a sentence, a table, three charts
and a CSV export; any analysis can be saved (« Analyses sauvegardées ») and
emailed on a schedule (« Rapports automatiques », daily cron).

« Commerce à risque » (decided here, shown in the answer): signals over the
chosen period against the one before — visits down, new customers down, no
notification delivered, no campaign sent, cards barely used — scored; Élevé
from 4 points, Moyen 2–3, Faible 1.
"""
from __future__ import annotations

import csv
import html as _html
from services import safe_csv
import io
import json
import re
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import TokenData
from features.platform_access import require_admin
from features import admin_commerces as AC
from features import admin_dashboard as AD

router = APIRouter(tags=["admin"])
_db = None
LIVE = AC.LIVE

ANALYSES = [
    ("risque", "Commerces à risque", "Quels commerces risquent de partir ?"),
    ("limite", "Commerces proches de leur limite", "Quels clients approchent de leur limite ?"),
    ("upgrade", "Opportunités d'upgrade", "Quels commerces pourraient passer au plan supérieur ?"),
    ("secteurs", "Secteurs les plus performants", "Quels secteurs utilisent le plus FIDCLIC ?"),
    ("sans_campagne", "Commerces sans campagne", "Quels commerces n'utilisent pas les campagnes ?"),
    ("inactifs", "Commerces inactifs (30 jours)", "Donne-moi les commerces inactifs depuis 30 jours."),
    ("comparaison", "Comparaison par secteur", "Analyse les performances des restaurants par rapport aux barbers."),
    ("recommandations", "Recommandations stratégiques", "Montre-moi les opportunités d'upgrade."),
]
TITLES = {k: t for k, t, _ in ANALYSES}
SUGGESTIONS = ["Quels commerces risquent de partir ?", "Quels clients approchent de leur limite ?",
               "Quels commerces pourraient passer au plan supérieur ?", "Quels secteurs utilisent le plus FIDCLIC ?",
               "Quels commerces n'utilisent pas les campagnes ?", "Donne-moi les commerces inactifs depuis 30 jours.",
               "Analyse les performances des restaurants par rapport aux barbers.", "Montre-moi les opportunités d'upgrade.",
               "Quelles sont tes recommandations stratégiques ?", "Compare les cafés et les boulangeries.",
               "Quels commerces n'envoient plus de notifications ?", "Quel secteur génère le plus de chiffre d'affaires ?"]
# Keyword routing, most specific first (accents removed, lower case).
ROUTES = [
    ("comparaison", ("compar", " vs ", "par rapport", "versus", "contre les")),
    ("sans_campagne", ("pas les campagnes", "sans campagne", "aucune campagne", "n'utilisent pas les campagnes", "pas de campagne",
                       "n envoient plus", "n'envoient plus", "plus de notification")),
    ("inactifs", ("inactif", "inactive", "dormant", "sans activite", "plus actif")),
    ("risque", ("risque", "partir", "resili", "churn", "perdre", "quitter")),
    ("limite", ("limite", "quota", "approch", "plafond")),
    ("upgrade", ("upgrade", "plan superieur", "passer au plan", "monter en gamme", "offre superieure", "opportunit")),
    ("recommandations", ("recommand", "strateg", "conseil", "que faire", "priorit")),
    ("secteurs", ("secteur", "performant", "chiffre d'affaires", "genere le plus")),
]


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _plain(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("’", "'")


def route(question: str) -> Optional[str]:
    q = " " + _plain(question) + " "
    for key, words in ROUTES:
        if any(w in q for w in words):
            return key
    return None


# ---------------------------------------------------------------------------
# Facts, read once per question
# ---------------------------------------------------------------------------
class Facts:
    def __init__(self, start: datetime, end: datetime):
        import server as core
        self.start, self.end = start, end
        self.now = _now()
        self.span = end - start
        self.prev = start - self.span
        self.tenants = [t for t in _db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0}) if not t.get("suspended_at")]
        self.snap = {s["id"]: s for s in AC.snapshot(self.now)}
        self.days = max(1, int(round(self.span.total_seconds() / 86400)))
        self.visits_cur: Dict[str, int] = defaultdict(int)
        self.visits_prev: Dict[str, int] = defaultdict(int)
        self.revenue: Dict[str, float] = defaultdict(float)
        self.daily: Dict[str, List[int]] = defaultdict(lambda: [0] * self.days)
        for v in _db.visits.find({"visit_time": {"$gte": self.prev, "$lt": end}}, {"_id": 0, "tenant_id": 1, "visit_time": 1, "amount_paid": 1}):
            at = AC._aware(v.get("visit_time"))
            if not at:
                continue
            tid = v.get("tenant_id")
            if at >= start:
                self.visits_cur[tid] += 1
                self.revenue[tid] += float(v.get("amount_paid") or 0)
                i = min(self.days - 1, int((at - start).total_seconds() // 86400))
                self.daily[tid][i] += 1
            else:
                self.visits_prev[tid] += 1
        self.new_cur = AC._count_by_tenant("customers", {**LIVE, "created_at": {"$gte": start, "$lt": end}})
        self.new_prev = AC._count_by_tenant("customers", {**LIVE, "created_at": {"$gte": self.prev, "$lt": start}})
        self.clients = AC._count_by_tenant("customers", LIVE)
        self.last_notif = {r["_id"]: AC._aware(r["at"]) for r in _db.delivery_log.aggregate([
            {"$match": {"result.sent": {"$gt": 0}}}, {"$group": {"_id": "$tenant_id", "at": {"$max": "$timestamp"}}}])}
        self.last_camp = {r["_id"]: AC._aware(r["at"]) for r in _db.campaigns.aggregate([
            {"$match": {"sent_at": {"$ne": None}}}, {"$group": {"_id": "$tenant_id", "at": {"$max": "$sent_at"}}}])}
        month = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        self.cards_month = AC._count_by_tenant("customers", {"created_at": {"$gte": month}})
        self.features = {t["id"]: core.features_for(t) for t in self.tenants}
        self.label = core.plan_label

    def row_base(self, t: Dict[str, Any]) -> Dict[str, Any]:
        s = self.snap.get(t["id"], {})
        return {"tenant_id": t["id"], "name": t.get("name") or "—", "logo": s.get("logo"), "sector": s.get("sector") or "",
                "city": t.get("city") or "", "plan": s.get("plan") or {"key": t.get("plan"), "label": self.label(t.get("plan"))},
                "last_activity": s.get("last_activity")}

    def change(self, cur: float, old: float) -> Optional[int]:
        return round((cur - old) / old * 100) if old else None

    def since(self, at: Optional[datetime], created: Optional[datetime]) -> Optional[int]:
        ref = at or created
        return (self.now - ref).days if ref else None


def _trend(series: List[int]) -> List[int]:
    """7-day rolling visits as % of the period's best week (100 = best)."""
    roll = [sum(series[max(0, i - 6): i + 1]) for i in range(len(series))]
    top = max(roll) if roll and max(roll) else 0
    return [round(x / top * 100) if top else 0 for x in roll]


def _sector_bars(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    c: Dict[str, int] = defaultdict(int)
    for r in rows:
        c[r.get("sector") or "Autres"] += 1
    return [{"label": k, "count": v} for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))][:6]


def _lines(F: Facts, rows: List[Dict[str, Any]], title: str) -> Dict[str, Any]:
    picked = rows[:5]
    days = [(F.start + timedelta(days=i)).date().isoformat() for i in range(F.days)]
    return {"title": title, "days": days, "series": [{"name": r["name"], "values": _trend(F.daily.get(r["tenant_id"], [0] * F.days))} for r in picked]}


# ---------------------------------------------------------------------------
# The analyses
# ---------------------------------------------------------------------------
def a_risque(F: Facts, q: str = "") -> Dict[str, Any]:
    out, faible = [], 0
    for t in F.tenants:
        created = AC._aware(t.get("created_at"))
        if created and created > F.prev:
            continue                                            # too young to compare two periods
        tid = t["id"]
        dv = F.change(F.visits_cur[tid], F.visits_prev[tid])
        dc = F.change(F.new_cur.get(tid, 0), F.new_prev.get(tid, 0))
        no_notif = F.since(F.last_notif.get(tid), created)
        no_camp = F.since(F.last_camp.get(tid), created)
        lim = int(F.features[tid].get("new_cards_per_month") or 0)
        usage = round(F.cards_month.get(tid, 0) / lim * 100) if lim else None
        reasons: List[tuple] = []
        score = 0
        if not F.visits_cur[tid]:
            last = AC._aware(F.snap.get(tid, {}).get("last_activity"))
            days = F.since(last, created)
            score += 3; reasons.append((4, f"Aucune visite depuis {days} jours" if last else "Aucune visite enregistrée"))
        elif dv is not None and dv <= -20:
            w = 3 if dv <= -50 else 2 if dv <= -30 else 1
            score += w; reasons.append((w, f"{dv} % de visites"))
        if dc is not None and dc <= -25:
            w = 2 if dc <= -40 else 1
            score += w; reasons.append((w, f"{dc} % de nouveaux clients"))
        if no_notif is not None and no_notif >= 30:
            w = 2 if no_notif >= 45 else 1
            score += w; reasons.append((w, f"Aucune notification ({no_notif} jours)"))
        if no_camp is not None and no_camp >= 30:
            score += 1; reasons.append((1, f"Pas de campagne ({no_camp} jours)"))
        if usage is not None and usage < 25 and F.visits_prev[tid]:
            score += 1; reasons.append((1, f"Utilisation faible (cartes : {usage} %)"))
        if not score:
            continue
        level = "eleve" if score >= 4 else "moyen" if score >= 2 else "faible"
        if level == "faible":
            faible += 1
            continue
        reasons.sort(key=lambda r: -r[0])
        out.append({**F.row_base(t), "level": level, "level_label": "Élevé" if level == "eleve" else "Moyen", "score": score,
                    "reasons": [r[1] for r in reasons[:2]], "trend": F.daily.get(tid, [0] * F.days),
                    "action": "Contacter" if level == "eleve" else "Relancer", "action_kind": "contact" if level == "eleve" else "relance"})
    out.sort(key=lambda r: (-r["score"], r["name"].lower()))
    el = sum(1 for r in out if r["level"] == "eleve")
    n = len(out)
    return {"headline": f"J'ai analysé les données de votre plateforme et identifié {n} commerce{'s' if n != 1 else ''} à risque de résiliation."
            if n else "Bonne nouvelle : aucun commerce ne présente de risque de résiliation sur la période.",
            "detail": "Ces commerces présentent une baisse significative d'activité, une faible utilisation des fonctionnalités et/ou une diminution des clients finaux."
            if n else "Visites, nouveaux clients, notifications et campagnes sont stables pour tous les commerces.",
            "columns": ["#", "Commerce", "Plan", "Risque", "Raisons", "Dernière activité", "Tendance", "Action recommandée"], "rows": out,
            "charts": {"donut": {"title": "Répartition des commerces à risque", "center": n, "sub": "commerces",
                                 "rows": [{"label": "Élevé", "count": el, "color": "#F43F5E"}, {"label": "Moyen", "count": n - el, "color": "#F59E0B"},
                                          {"label": "Faible", "count": faible, "color": "#10B981"}]},
                       "bars": {"title": "Répartition par secteur", "rows": _sector_bars(out)},
                       "lines": _lines(F, out, f"Évolution de l'activité ({F.days} derniers jours)")}}


def a_limite(F: Facts, q: str = "") -> Dict[str, Any]:
    from features import plan_limits as PL
    thr = PL.settings()["alert_threshold"]
    out = []
    for t in F.tenants:
        for u in PL.usage_of(t, F.now):
            if u["pct"] >= thr:
                up = PL._next_bigger(F.features[t["id"]], u["key"])
                out.append({**F.row_base(t), "limit": u["what"], "used": u["used"], "cap": u["limit"], "pct": u["pct"],
                            "action": f"Proposer l'offre {up['label']}" if up else "Revoir ses conditions", "action_kind": "contact",
                            "level": "eleve" if u["pct"] >= 100 else "moyen"})
    out.sort(key=lambda r: -r["pct"])
    kinds: Dict[str, int] = defaultdict(int)
    for r in out:
        kinds[r["limit"]] += 1
    n = len({r["tenant_id"] for r in out})
    return {"headline": f"{n} commerce{'s' if n != 1 else ''} approche{'nt' if n != 1 else ''} de {'leurs limites' if n != 1 else 'sa limite'} (seuil : {thr} %)."
            if n else f"Aucun commerce n'a atteint {thr} % d'une de ses limites.",
            "detail": "Cartes de fidélité et notifications du mois, clients actifs et campagnes, comparés aux limites de leur offre.",
            "columns": ["#", "Commerce", "Plan", "Limite", "Utilisation", "Dernière activité", "Action recommandée"], "rows": out,
            "charts": {"donut": {"title": "Limites atteintes", "center": len(out), "sub": "alertes",
                                 "rows": [{"label": k.capitalize(), "count": v} for k, v in kinds.items()]},
                       "bars": {"title": "Répartition par secteur", "rows": _sector_bars(out)},
                       "lines": _lines(F, out, f"Activité ({F.days} derniers jours)")}}


def a_upgrade(F: Facts, q: str = "") -> Dict[str, Any]:
    from features import admin_insights as AI
    data = AI._compute(F.start.date(), (F.end - timedelta(seconds=1)).date())
    out, gain = [], 0.0
    seen = set()
    for r in data["rows"]:
        if r["type"] not in ("upgrade", "opportunite") or r["tenant_id"] in seen:
            continue
        seen.add(r["tenant_id"])
        t = next((x for x in F.tenants if x["id"] == r["tenant_id"]), None)
        if not t:
            continue
        import server as core
        f = F.features[t["id"]]
        nxt = core.NEXT_PLAN.get(core._canonical_plan(t.get("plan")))     # the plan named in the recommendation
        delta = float(core.get_plan_features(nxt).get("price") or 0) - float(f.get("price") or 0) if nxt and nxt != "franchise" else 0.0
        gain += max(0.0, delta)
        out.append({**F.row_base(t), "details": r["details"], "action": r["recommendation"], "action_kind": "contact",
                    "level": r["priority"], "level_label": r["priority_label"], "gain": round(delta, 2)})
    n = len(out)
    return {"headline": f"{n} commerce{'s' if n != 1 else ''} pourrai{'ent' if n != 1 else 't'} passer au plan supérieur — jusqu'à +€{round(gain):,} de MRR.".replace(",", " ")
            if n else "Aucune opportunité d'upgrade pour le moment.",
            "detail": "Commerces qui utilisent 60 % ou plus de leurs cartes, ou 80 % d'un quota (règles de la page Insights).",
            "columns": ["#", "Commerce", "Plan", "Détails", "Gain MRR", "Priorité", "Action recommandée"], "rows": out,
            "charts": {"donut": {"title": "Par plan actuel", "center": n, "sub": "commerces",
                                 "rows": [{"label": k, "count": v} for k, v in _count(out, lambda r: r["plan"]["label"]).items()]},
                       "bars": {"title": "Répartition par secteur", "rows": _sector_bars(out)},
                       "lines": _lines(F, out, f"Activité ({F.days} derniers jours)")}}


def _count(rows, key) -> Dict[str, int]:
    c: Dict[str, int] = defaultdict(int)
    for r in rows:
        c[key(r)] += 1
    return dict(c)


def _sector_table(F: Facts, only: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    agg: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in F.tenants:
        sec = F.row_base(t)["sector"] or "Autres"
        if only and sec not in only:
            continue
        a = agg[sec]
        tid = t["id"]
        a["commerces"] += 1
        a["clients"] += F.clients.get(tid, 0)
        a["visites"] += F.visits_cur[tid]
        a["visites_prev"] += F.visits_prev[tid]
        a["ca"] += F.revenue[tid]
    rows = []
    for sec, a in agg.items():
        n = a["commerces"] or 1
        rows.append({"name": sec, "sector": sec, "commerces": int(a["commerces"]), "clients": int(a["clients"]),
                     "visites": int(a["visites"]), "ca": round(a["ca"], 2), "visites_par_commerce": round(a["visites"] / n, 1),
                     "clients_par_commerce": round(a["clients"] / n, 1), "panier": round(a["ca"] / a["visites"], 2) if a["visites"] else 0,
                     "evolution": F.change(a["visites"], a["visites_prev"])})
    rows.sort(key=lambda r: (-r["visites"], r["name"]))
    return rows


def a_secteurs(F: Facts, q: str = "") -> Dict[str, Any]:
    rows = _sector_table(F)
    best = rows[0] if rows else None
    return {"headline": f"« {best['name']} » est le secteur qui utilise le plus FIDCLIC : {best['visites']:,} visites sur la période.".replace(",", " ")
            if best and best["visites"] else "Pas encore assez d'activité pour classer les secteurs.",
            "detail": "Visites, clients, chiffre d'affaires et panier moyen par secteur, avec l'évolution des visites vs la période précédente.",
            "columns": ["#", "Secteur", "Commerces", "Clients", "Visites", "Visites / commerce", "Chiffre d'affaires", "Panier moyen", "Évolution"],
            "rows": rows, "kind": "sectors",
            "charts": {"donut": {"title": "Commerces par secteur", "center": sum(r["commerces"] for r in rows), "sub": "commerces",
                                 "rows": [{"label": r["name"], "count": r["commerces"]} for r in rows[:6]]},
                       "bars": {"title": "Visites par secteur", "rows": [{"label": r["name"], "count": r["visites"]} for r in rows[:6]]},
                       "lines": None}}


def a_comparaison(F: Facts, q: str = "") -> Dict[str, Any]:
    all_rows = _sector_table(F)
    # « restaurants » / « barbers » match « Restauration / Fast-food » / « Barbier » through the
    # words of the label and the sector as the business typed it.
    aliases: Dict[str, set] = defaultdict(set)
    for t in F.tenants:
        label = F.row_base(t)["sector"] or "Autres"
        for w in re.split(r"[\s/&,-]+", _plain(f"{label} {t.get('sector') or ''}")):
            if len(w) >= 4:
                aliases[label].add(w[:5])
    words = re.split(r"[^a-z]+", _plain(q))
    wanted = [r["name"] for r in all_rows if any(any(w.startswith(a) for w in words if len(w) >= 4) for a in aliases.get(r["name"], ()))]
    if len(wanted) == 1:                        # one named sector has no business on FIDCLIC
        only = [r for r in all_rows if r["name"] == wanted[0]]
        return {"headline": f"Je n'ai trouvé que « {wanted[0]} » parmi les secteurs nommés : l'autre n'a aucun commerce sur FIDCLIC.",
                "detail": "Voici ses chiffres ; nommez un secteur présent sur la plateforme pour comparer.", "columns": [], "rows": only,
                "kind": "sectors", "charts": None}
    rows = [r for r in all_rows if r["name"] in wanted] if len(wanted) >= 2 else all_rows
    if len(rows) >= 2:
        a, b = rows[0], rows[1]
        head = (f"Comparaison {' / '.join(r['name'] for r in rows[:4])} : « {a['name']} » fait {a['visites_par_commerce']} visites par commerce, "
                f"« {b['name']} » {b['visites_par_commerce']}.")
    else:
        head = "Pas assez de secteurs à comparer pour le moment."
    return {"headline": head, "detail": "Moyennes par commerce sur la période (visites, clients, panier) et évolution des visites."
            + ("" if len(wanted) >= 2 else " Nommez deux secteurs pour les comparer (ex. « restaurants par rapport aux barbers »)."),
            "columns": ["#", "Secteur", "Commerces", "Clients", "Visites", "Visites / commerce", "Chiffre d'affaires", "Panier moyen", "Évolution"],
            "rows": rows, "kind": "sectors",
            "charts": {"donut": {"title": "Commerces", "center": sum(r["commerces"] for r in rows), "sub": "commerces",
                                 "rows": [{"label": r["name"], "count": r["commerces"]} for r in rows[:6]]},
                       "bars": {"title": "Visites par commerce", "rows": [{"label": r["name"], "count": r["visites_par_commerce"]} for r in rows[:6]]},
                       "lines": None}}


def a_sans_campagne(F: Facts, q: str = "") -> Dict[str, Any]:
    out = []
    for t in F.tenants:
        created = AC._aware(t.get("created_at"))
        last = F.last_camp.get(t["id"])
        if created and created > F.now - timedelta(days=30):
            continue
        if last and last > F.now - timedelta(days=30):
            continue
        days = F.since(last, created)
        out.append({**F.row_base(t), "last_campaign": last.isoformat() if last else None, "days": days, "clients": F.clients.get(t["id"], 0),
                    "action": "Relancer", "action_kind": "relance", "level": "moyen" if last else "eleve",
                    "reasons": [f"Aucune campagne ({days} jours)" if last else "Jamais de campagne"]})
    out.sort(key=lambda r: -(r["days"] or 0))
    n = len(out)
    return {"headline": f"{n} commerce{'s' if n != 1 else ''} n'{'ont' if n != 1 else 'a'} envoyé aucune campagne depuis 30 jours." if n
            else "Tous les commerces ont envoyé une campagne ces 30 derniers jours.",
            "detail": "Les campagnes font revenir les clients : ces commerces ont le plus à gagner d'une relance.",
            "columns": ["#", "Commerce", "Plan", "Dernière campagne", "Clients", "Dernière activité", "Tendance", "Action recommandée"], "rows": out,
            "charts": {"donut": {"title": "Par plan", "center": n, "sub": "commerces",
                                 "rows": [{"label": k, "count": v} for k, v in _count(out, lambda r: r["plan"]["label"]).items()]},
                       "bars": {"title": "Répartition par secteur", "rows": _sector_bars(out)},
                       "lines": _lines(F, out, f"Évolution de l'activité ({F.days} derniers jours)")}}


def a_inactifs(F: Facts, q: str = "") -> Dict[str, Any]:
    since = F.now - timedelta(days=30)
    out = []
    for t in F.tenants:
        created = AC._aware(t.get("created_at"))
        if created and created > since:
            continue
        last = AC._aware(F.snap.get(t["id"], {}).get("last_activity"))
        if last and last >= since:
            continue
        out.append({**F.row_base(t), "days": F.since(last, created), "clients": F.clients.get(t["id"], 0), "action": "Contacter",
                    "action_kind": "contact", "level": "eleve", "reasons": ["Aucune visite depuis 30 jours" if last else "Aucune visite enregistrée"]})
    out.sort(key=lambda r: -(r["days"] or 0))
    n = len(out)
    return {"headline": f"{n} commerce{'s' if n != 1 else ''} inactif{'s' if n != 1 else ''} depuis 30 jours : aucune visite enregistrée." if n
            else "Aucun commerce inactif : tous ont enregistré des visites ces 30 derniers jours.",
            "detail": "Un commerce sans visite depuis un mois n'utilise plus FIDCLIC au comptoir.",
            "columns": ["#", "Commerce", "Plan", "Inactif depuis", "Clients", "Dernière activité", "Action recommandée"], "rows": out,
            "charts": {"donut": {"title": "Par plan", "center": n, "sub": "commerces",
                                 "rows": [{"label": k, "count": v} for k, v in _count(out, lambda r: r["plan"]["label"]).items()]},
                       "bars": {"title": "Répartition par secteur", "rows": _sector_bars(out)}, "lines": None}}


def a_recommandations(F: Facts, q: str = "") -> Dict[str, Any]:
    r, l, u, c, i = a_risque(F), a_limite(F), a_upgrade(F), a_sans_campagne(F), a_inactifs(F)
    rows = []
    el = [x for x in r["rows"] if x["level"] == "eleve"]
    if el:
        rows.append({"name": f"Appeler les {len(el)} commerce{'s' if len(el) > 1 else ''} à risque élevé", "level": "eleve", "count": len(el),
                     "impact": f"€{round(sum(F.features[x['tenant_id']].get('price') or 0 for x in el))} de MRR protégé", "target": "risque"})
    if u["rows"]:
        gain = round(sum(x["gain"] for x in u["rows"]))
        rows.append({"name": f"Proposer l'offre supérieure à {len(u['rows'])} commerce{'s' if len(u['rows']) > 1 else ''}", "level": "eleve",
                     "count": len(u["rows"]), "impact": f"+€{gain} de MRR possible", "target": "upgrade"})
    if l["rows"]:
        rows.append({"name": f"Prévenir les commerces proches de leur limite ({len({x['tenant_id'] for x in l['rows']})})", "level": "moyen",
                     "count": len(l["rows"]), "impact": "Éviter un blocage et préparer l'upgrade", "target": "limite"})
    if c["rows"]:
        rows.append({"name": f"Relancer {len(c['rows'])} commerce{'s' if len(c['rows']) > 1 else ''} sans campagne depuis 30 jours", "level": "moyen",
                     "count": len(c["rows"]), "impact": "Plus de visites pour leurs clients", "target": "sans_campagne"})
    if i["rows"]:
        rows.append({"name": f"Réactiver {len(i['rows'])} commerce{'s' if len(i['rows']) > 1 else ''} inactif{'s' if len(i['rows']) > 1 else ''}", "level": "eleve",
                     "count": len(i["rows"]), "impact": "Éviter les résiliations", "target": "inactifs"})
    sectors = [x for x in _sector_table(F) if x["evolution"] is not None and x["evolution"] <= -20]
    if sectors:
        rows.append({"name": f"Accompagner le secteur « {sectors[0]['name']} » ({sectors[0]['evolution']} % de visites)", "level": "moyen",
                     "count": sectors[0]["commerces"], "impact": "Campagne sectorielle / modèles dédiés", "target": "secteurs"})
    rows.sort(key=lambda x: (x["level"] != "eleve", -x["count"]))
    return {"headline": f"{len(rows)} action{'s' if len(rows) != 1 else ''} prioritaire{'s' if len(rows) != 1 else ''} pour la plateforme." if rows
            else "Rien d'urgent : la plateforme se porte bien sur la période.",
            "detail": "Classées par impact : chaque ligne ouvre l'analyse détaillée.", "kind": "reco",
            "columns": ["#", "Recommandation", "Priorité", "Commerces", "Impact", "Voir"], "rows": rows,
            "charts": {"donut": {"title": "Commerces à risque", "center": len(r["rows"]), "sub": "commerces", "rows": r["charts"]["donut"]["rows"]},
                       "bars": {"title": "Opportunités par secteur", "rows": _sector_bars(u["rows"])}, "lines": r["charts"]["lines"]}}


RUNNERS = {"risque": a_risque, "limite": a_limite, "upgrade": a_upgrade, "secteurs": a_secteurs, "sans_campagne": a_sans_campagne,
           "inactifs": a_inactifs, "comparaison": a_comparaison, "recommandations": a_recommandations}


def run(key: str, start: datetime, end: datetime, question: str = "") -> Dict[str, Any]:
    F = Facts(start, end)
    out = RUNNERS[key](F, question)
    return {"key": key, "title": TITLES[key], "question": question or next(q for k, _, q in ANALYSES if k == key),
            "period": {"from": AC._iso(start), "to": AC._iso(end)}, "at": _now().isoformat(), **out}


def _period(date_from: Optional[str], date_to: Optional[str]):
    return AD._period(date_from if isinstance(date_from, str) else None, date_to if isinstance(date_to, str) else None)


def _general_answer(question: str, start: datetime, end: datetime) -> Dict[str, Any]:
    """A question outside the analyses: the model answers from the figures."""
    from services import llm
    F = Facts(start, end)
    facts = {"commerces": len(F.tenants), "clients_finaux": sum(F.clients.values()), "visites_periode": sum(F.visits_cur.values()),
             "visites_periode_precedente": sum(F.visits_prev.values()), "chiffre_affaires_periode": round(sum(F.revenue.values()), 2),
             "nouveaux_clients": sum(F.new_cur.values()), "secteurs": _sector_table(F)[:8],
             "commerces_par_plan": _count(F.tenants, lambda t: F.label(t.get("plan")))}
    text = llm.complete("Tu es FIDCLIC AI, l'assistant du super admin de FIDCLIC (programme de fidélité pour commerces). "
                        "Réponds en français, en 3 à 5 phrases, uniquement à partir des chiffres fournis. N'invente aucun chiffre ; "
                        "si l'information manque, dis-le et propose une des analyses disponibles.",
                        f"Chiffres de la plateforme (JSON) : {json.dumps(facts, ensure_ascii=False, default=str)}\n\nQuestion : {question}",
                        max_tokens=320, temperature=0.3, feature="admin_ai")
    return {"key": "general", "title": "Réponse", "question": question, "period": {"from": AC._iso(start), "to": AC._iso(end)},
            "at": _now().isoformat(), "headline": text or "", "detail": "", "columns": [], "rows": [], "charts": None, "source": "llm"}


class AskIn(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)


@router.get("/api/admin/ai/page")
def page(token_data: TokenData = Depends(require_admin("ai"))):
    from services import llm
    u = _db.users.find_one({"email": token_data.email}, {"_id": 0, "first_name": 1}) or {}
    name = u.get("first_name") or (token_data.email or "").split("@")[0].split(".")[0].capitalize()
    return {"first_name": name, "analyses": [{"key": k, "label": l, "question": q} for k, l, q in ANALYSES],
            "suggestions": SUGGESTIONS, "llm": llm.is_configured()}


@router.post("/api/admin/ai/ask")
def ask(body: AskIn, date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
        token_data: TokenData = Depends(require_admin("ai"))):
    start, end = _period(date_from, date_to)
    key = route(body.question)
    source = "rules"
    if not key:
        from services import llm
        if llm.is_configured():
            pick = llm.complete("Classe la question du super admin dans UNE de ces analyses et réponds uniquement par sa clé, "
                                "ou « aucune » : " + ", ".join(f"{k} ({t})" for k, t, _ in ANALYSES),
                                body.question, max_tokens=10, temperature=0, feature="admin_ai") or ""
            pick = pick.strip().strip("«»\"' .").lower()
            if pick in RUNNERS:
                key, source = pick, "llm"
            else:
                return _general_answer(body.question, start, end)
        else:
            return {"key": "unknown", "title": "Je n'ai pas compris", "question": body.question, "at": _now().isoformat(),
                    "headline": "Je n'ai pas trouvé d'analyse qui réponde à cette question.",
                    "detail": "Essayez une des questions proposées ou une des analyses rapides.", "columns": [], "rows": [], "charts": None,
                    "suggestions": SUGGESTIONS[:6]}
    return {**run(key, start, end, body.question), "source": source}


@router.get("/api/admin/ai/analysis/{key}")
def analysis(key: str, question: str = "", date_from: Optional[str] = Query(None, alias="from"),
             date_to: Optional[str] = Query(None, alias="to"), token_data: TokenData = Depends(require_admin("ai"))):
    if key not in RUNNERS:
        raise HTTPException(status_code=404, detail="Analyse inconnue.")
    start, end = _period(date_from, date_to)
    return run(key, start, end, question)


def _csv_rows(res: Dict[str, Any]) -> List[List[Any]]:
    k = res["key"]
    rows = res["rows"]
    if res.get("kind") == "sectors":
        return [["Secteur", "Commerces", "Clients", "Visites", "Visites / commerce", "Chiffre d'affaires (€)", "Panier moyen (€)", "Évolution (%)"]] + [
            [r["name"], r["commerces"], r["clients"], r["visites"], r["visites_par_commerce"], r["ca"], r["panier"], r["evolution"] if r["evolution"] is not None else ""]
            for r in rows]
    if res.get("kind") == "reco":
        return [["Recommandation", "Priorité", "Commerces", "Impact"]] + [[r["name"], "Élevée" if r["level"] == "eleve" else "Moyenne", r["count"], r["impact"]] for r in rows]
    head = ["Commerce", "Secteur", "Ville", "Plan"]
    extra = {"risque": (["Risque", "Raisons"], lambda r: [r["level_label"], " ; ".join(r["reasons"])]),
             "limite": (["Limite", "Utilisé", "Limite du plan", "%"], lambda r: [r["limit"], r["used"], r["cap"], r["pct"]]),
             "upgrade": (["Détails", "Gain MRR (€)", "Priorité"], lambda r: [r["details"], r["gain"], r["level_label"]]),
             "sans_campagne": (["Jours sans campagne", "Clients"], lambda r: [r["days"] if r["days"] is not None else "", r["clients"]]),
             "inactifs": (["Inactif depuis (jours)", "Clients"], lambda r: [r["days"] if r["days"] is not None else "", r["clients"]])}[k]
    return [head + extra[0] + ["Action recommandée"]] + [[r["name"], r["sector"], r["city"], r["plan"]["label"]] + extra[1](r) + [r["action"]] for r in rows]


@router.get("/api/admin/ai/export/{key}")
def export(key: str, question: str = "", date_from: Optional[str] = Query(None, alias="from"),
           date_to: Optional[str] = Query(None, alias="to"), token_data: TokenData = Depends(require_admin("ai"))):
    if key not in RUNNERS:
        raise HTTPException(status_code=404, detail="Analyse inconnue.")
    start, end = _period(date_from, date_to)
    buf = io.StringIO()
    safe_csv.writer(buf).writerows(_csv_rows(run(key, start, end, question)))
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="fidclic-ai-{key}.csv"'})


# ---------------------------------------------------------------------------
# Analyses sauvegardées
# ---------------------------------------------------------------------------
class SaveIn(BaseModel):
    key: str
    question: str = Field("", max_length=500)
    title: Optional[str] = Field(None, max_length=120)
    days: int = Field(30, ge=1, le=366)


def _saved_out(s: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": s["id"], "key": s["key"], "title": s.get("title") or TITLES.get(s["key"]), "question": s.get("question") or "",
            "days": s.get("days", 30), "created_at": AC._iso(s.get("created_at")), "created_by": s.get("created_by"),
            "last_headline": s.get("last_headline"), "last_count": s.get("last_count"), "last_run_at": AC._iso(s.get("last_run_at"))}


@router.get("/api/admin/ai/saved")
def list_saved(token_data: TokenData = Depends(require_admin("ai"))):
    return {"rows": [_saved_out(s) for s in _db.ai_saved.find({}, {"_id": 0}).sort("created_at", -1)]}


@router.post("/api/admin/ai/saved", status_code=201)
def save(body: SaveIn, token_data: TokenData = Depends(require_admin("ai"))):
    if body.key not in RUNNERS:
        raise HTTPException(status_code=400, detail="Analyse inconnue.")
    end = _now()
    res = run(body.key, end - timedelta(days=body.days), end, body.question)
    s = {"id": uuid.uuid4().hex, "key": body.key, "question": body.question, "title": (body.title or "").strip() or TITLES[body.key],
         "days": body.days, "created_at": end, "created_by": token_data.email, "last_headline": res["headline"],
         "last_count": len(res["rows"]), "last_run_at": end}
    _db.ai_saved.insert_one(dict(s))
    return _saved_out(s)


@router.post("/api/admin/ai/saved/{sid}/run")
def run_saved(sid: str, token_data: TokenData = Depends(require_admin("ai"))):
    s = _db.ai_saved.find_one({"id": sid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Analyse introuvable.")
    end = _now()
    res = run(s["key"], end - timedelta(days=int(s.get("days") or 30)), end, s.get("question") or "")
    _db.ai_saved.update_one({"id": sid}, {"$set": {"last_headline": res["headline"], "last_count": len(res["rows"]), "last_run_at": end}})
    return res


@router.delete("/api/admin/ai/saved/{sid}")
def delete_saved(sid: str, token_data: TokenData = Depends(require_admin("ai"))):
    if not _db.ai_saved.delete_one({"id": sid}).deleted_count:
        raise HTTPException(status_code=404, detail="Analyse introuvable.")
    _db.ai_reports.delete_many({"saved_id": sid})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Rapports automatiques
# ---------------------------------------------------------------------------
EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ReportIn(BaseModel):
    saved_id: str
    frequency: str = "weekly"                  # weekly | monthly
    weekday: int = Field(0, ge=0, le=6)        # Monday = 0
    monthday: int = Field(1, ge=1, le=28)
    recipients: List[str]
    active: bool = True


def _check_report(body: ReportIn) -> List[str]:
    if body.frequency not in ("weekly", "monthly"):
        raise HTTPException(status_code=400, detail="Fréquence : hebdomadaire ou mensuelle.")
    if not _db.ai_saved.find_one({"id": body.saved_id}, {"_id": 1}):
        raise HTTPException(status_code=400, detail="Choisissez une analyse sauvegardée.")
    rcpt = [e.strip().lower() for e in body.recipients if e.strip()]
    if not rcpt or any(not EMAIL_RX.match(e) for e in rcpt) or len(rcpt) > 10:
        raise HTTPException(status_code=400, detail="De 1 à 10 adresses email valides.")
    return list(dict.fromkeys(rcpt))


def _report_out(r: Dict[str, Any]) -> Dict[str, Any]:
    s = _db.ai_saved.find_one({"id": r["saved_id"]}, {"_id": 0}) or {}
    return {"id": r["id"], "saved_id": r["saved_id"], "title": s.get("title") or TITLES.get(s.get("key"), "Analyse supprimée"),
            "frequency": r["frequency"], "weekday": r.get("weekday", 0), "monthday": r.get("monthday", 1), "recipients": r["recipients"],
            "active": bool(r.get("active")), "last_sent_at": AC._iso(r.get("last_sent_at")), "last_error": r.get("last_error"),
            "next_at": _next_run(r).isoformat()}


def _next_run(r: Dict[str, Any], now: Optional[datetime] = None) -> datetime:
    now = now or _now()
    day = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if r["frequency"] == "weekly":
        d = day + timedelta(days=(int(r.get("weekday", 0)) - day.weekday()) % 7)
        return d if d > now else d + timedelta(days=7)
    d = day.replace(day=int(r.get("monthday", 1)))
    if d <= now:
        d = (d.replace(day=1) + timedelta(days=32)).replace(day=int(r.get("monthday", 1)))
    return d


@router.get("/api/admin/ai/reports")
def list_reports(token_data: TokenData = Depends(require_admin("ai"))):
    return {"rows": [_report_out(r) for r in _db.ai_reports.find({}, {"_id": 0}).sort("created_at", -1)],
            "saved": [_saved_out(s) for s in _db.ai_saved.find({}, {"_id": 0}).sort("created_at", -1)]}


@router.post("/api/admin/ai/reports", status_code=201)
def create_report(body: ReportIn, token_data: TokenData = Depends(require_admin("ai"))):
    rcpt = _check_report(body)
    r = {**body.dict(), "recipients": rcpt, "id": uuid.uuid4().hex, "created_at": _now(), "created_by": token_data.email}
    _db.ai_reports.insert_one(dict(r))
    return _report_out(r)


@router.put("/api/admin/ai/reports/{rid}")
def edit_report(rid: str, body: ReportIn, token_data: TokenData = Depends(require_admin("ai"))):
    rcpt = _check_report(body)
    if not _db.ai_reports.update_one({"id": rid}, {"$set": {**body.dict(), "recipients": rcpt}}).matched_count:
        raise HTTPException(status_code=404, detail="Rapport introuvable.")
    return _report_out(_db.ai_reports.find_one({"id": rid}, {"_id": 0}))


@router.delete("/api/admin/ai/reports/{rid}")
def delete_report(rid: str, token_data: TokenData = Depends(require_admin("ai"))):
    if not _db.ai_reports.delete_one({"id": rid}).deleted_count:
        raise HTTPException(status_code=404, detail="Rapport introuvable.")
    return {"ok": True}


def _email_html(res: Dict[str, Any]) -> str:
    rows = _csv_rows(res) if res["rows"] else []
    # shop names and sectors are typed by owners: escaped, never markup in the mail
    e = lambda v: _html.escape("" if v is None else str(v))  # noqa: E731
    head = "".join(f"<th style='text-align:left;padding:6px 8px;border-bottom:1px solid #E2E8F0;color:#64748B'>{e(h)}</th>" for h in (rows[0] if rows else []))
    body = "".join("<tr>" + "".join(f"<td style='padding:6px 8px;border-bottom:1px solid #F1F5F9'>{e(c)}</td>" for c in r) + "</tr>" for r in rows[1:51])
    table = f"<table style='border-collapse:collapse;font-size:13px'>{'<tr>' + head + '</tr>' if head else ''}{body}</table>" if rows else ""
    return (f"<div style='font-family:Arial,sans-serif;color:#0B1C3F'><h2 style='margin:0 0 4px'>FIDCLIC AI — {e(res['title'])}</h2>"
            f"<p style='font-size:15px'>{e(res['headline'])}</p><p style='color:#64748B'>{e(res['detail'])}</p>{table}"
            f"<p><a href='https://app.fidclic.com/admin/ai'>Ouvrir FIDCLIC AI</a></p></div>")


def send_report(r: Dict[str, Any]) -> Dict[str, Any]:
    from services import mailer
    s = _db.ai_saved.find_one({"id": r["saved_id"]}, {"_id": 0})
    if not s:
        return {"sent": 0, "error": "Analyse supprimée"}
    end = _now()
    res = run(s["key"], end - timedelta(days=int(s.get("days") or 30)), end, s.get("question") or "")
    sent, err = 0, None
    for to in r["recipients"]:
        out = mailer.send(to, f"FIDCLIC AI — {s.get('title') or res['title']}", _email_html(res))
        if out.get("sent"):
            sent += 1
        else:
            err = out.get("reason") or out.get("error") or "envoi impossible"
    _db.ai_reports.update_one({"id": r["id"]}, {"$set": {"last_sent_at": end if sent else r.get("last_sent_at"), "last_error": None if sent else err}})
    return {"sent": sent, "error": None if sent else err}


@router.post("/api/admin/ai/reports/{rid}/send")
def send_now(rid: str, token_data: TokenData = Depends(require_admin("ai"))):
    r = _db.ai_reports.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Rapport introuvable.")
    out = send_report(r)
    if not out["sent"]:
        raise HTTPException(status_code=502, detail=f"Envoi impossible : {out['error']}. Vérifiez la configuration email (Brevo).")
    return out


def run_due_reports(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Daily cron: the reports whose day has come (once per day)."""
    now = now or _now()
    n = 0
    for r in list(_db.ai_reports.find({"active": True}, {"_id": 0})):
        due = (r["frequency"] == "weekly" and now.weekday() == int(r.get("weekday", 0))) or \
              (r["frequency"] == "monthly" and now.day == int(r.get("monthday", 1)))
        last = AC._aware(r.get("last_sent_at"))
        if due and not (last and last.date() == now.date()):
            n += bool(send_report(r)["sent"])
    return {"sent": n}
