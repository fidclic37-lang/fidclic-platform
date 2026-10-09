"""
Règles clients — how FidClic sorts a shop's clients into kinds.

Mounts at: /api/owner/customer-rules
Collections:
  - `customer_status_config` (one doc per tenant): the rule list lives in its
    `rules` field. The older flat fields of that document (active_within_days,
    dormant_after_days, about_to_lose_days, regular_visits_per_month,
    loyal_visits_per_month) are still read elsewhere — the loyalty-bucket
    filter in server.py and the inactive rescue in auto_campaigns.py — so every
    save writes them back from the built-in rules. One source of truth, and the
    older readers keep agreeing with it.
  - `customers` (read-only).

The page shows seven built-in rules and lets the owner add their own. A rule
is a name, an icon, a colour, one to three conditions (all must hold), a
description and an on/off switch.

A client can satisfy several rules at once — a VIP is also active. Where the
product needs ONE word for a client (the Statut column of the Clients page),
`primary()` picks it: losing a client is said first (dormant, bientôt perdu),
then the owner's own rules, then the strongest frequency rule, then nouveau,
then actif. A client who matches nothing but has been in reads "Inactif".
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_role, TokenData
from features import settings_versions as SV   # « Réinitialiser » (Paramètres)

router = APIRouter(tags=["customer-rules"])
_db = None


def init(db):
    global _db
    _db = db


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------
# One entry per kind of condition. `builtin_only` conditions carry a meaning
# that depends on another built-in rule and cannot be offered to the owner.
CRITERIA: Dict[str, Dict[str, Any]] = {
    "visited_within":   {"label": "A effectué une visite dans les X derniers jours",
                         "unit": "jours", "min": 1, "max": 3650},
    "at_risk_since":    {"label": "N'a pas visité depuis X jours (mais pas encore dormant)",
                         "unit": "jours", "min": 1, "max": 3650, "builtin_only": True},
    "not_visited_since": {"label": "N'a pas visité depuis X jours",
                          "unit": "jours", "min": 1, "max": 3650},
    "visits_max":       {"label": "Moins de X visites (total)",
                         "unit": "visite", "min": 0, "max": 100000},
    "visits_min":       {"label": "Nombre minimum de visites (au total)",
                         "unit": "visites", "min": 1, "max": 100000},
    "visits_per_month": {"label": "Visites par mois",
                         "unit": "visites/mois", "min": 0.1, "max": 100},
    "spent_min":        {"label": "A dépensé au moins X € (au total)",
                         "unit": "€", "min": 1, "max": 1000000},
    "avg_basket_min":   {"label": "Panier moyen d'au moins X €",
                         "unit": "€", "min": 1, "max": 100000},
    "joined_within":    {"label": "Inscrit depuis moins de X jours",
                         "unit": "jours", "min": 1, "max": 3650},
}

ICONS = ["users", "clock", "moon", "user-plus", "bar-chart", "star", "crown",
         "heart", "gift", "tag", "zap", "coffee", "shopping-bag", "trending-up"]
TONES = ["green", "orange", "rose", "blue", "violet", "amber", "slate"]

MAX_CONDITIONS = 3
MAX_CUSTOM = 20
NAME_MAX = 40
DESCRIPTION_MAX = 200

BUILTINS: List[Dict[str, Any]] = [
    {"key": "actif", "name": "Client actif", "icon": "users", "tone": "green",
     "conditions": [{"type": "visited_within", "value": 30}],
     "description": "Client qui a visité récemment votre commerce."},
    {"key": "bientot_perdu", "name": "Client bientôt perdu", "icon": "clock", "tone": "orange",
     "conditions": [{"type": "at_risk_since", "value": 31}],
     "description": "Client inactif depuis plus de X jours mais qui n'est pas encore "
                    "considéré comme dormant."},
    {"key": "dormant", "name": "Client dormant", "icon": "moon", "tone": "rose",
     "conditions": [{"type": "not_visited_since", "value": 90}],
     "description": "Client inactif depuis longtemps."},
    {"key": "nouveau", "name": "Nouveau client", "icon": "user-plus", "tone": "blue",
     "conditions": [{"type": "visits_max", "value": 1}],
     "description": "Client qui a effectué sa première visite."},
    {"key": "regulier", "name": "Client régulier", "icon": "bar-chart", "tone": "violet",
     "conditions": [{"type": "visits_min", "value": 3}, {"type": "visits_per_month", "value": 2}],
     "description": "Client qui visite régulièrement votre commerce."},
    {"key": "fidele", "name": "Client fidèle", "icon": "star", "tone": "blue",
     "conditions": [{"type": "visits_per_month", "value": 4}],
     "description": "Client qui visite souvent votre commerce."},
    # Not « Client VIP » any more (QA F21, user 2026-10-09): VIP is the top
    # palier of the loyalty card; this rule is about how often they come.
    {"key": "vip", "name": "Client très actif", "icon": "crown", "tone": "amber",
     "conditions": [{"type": "visits_per_month", "value": 8}],
     "description": "Vient très souvent. À ne pas confondre avec le palier VIP de la carte de fidélité."},
]
BUILTIN_KEYS = [b["key"] for b in BUILTINS]

# The word the Clients page shows, in the order it is looked for. Custom rules
# slot in after the two "losing them" rules.
PRIMARY_BEFORE_CUSTOM = ["dormant", "bientot_perdu"]
PRIMARY_AFTER_CUSTOM = ["vip", "fidele", "regulier", "nouveau", "actif"]

FALLBACK_INACTIVE = {"key": "inactif", "name": "Inactif", "tone": "rose"}
FALLBACK_NONE = {"key": "aucun", "name": "Sans statut", "tone": "slate"}

DEFAULT_ACTIVE_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _builtin(key: str) -> Dict[str, Any]:
    return copy.deepcopy(next(b for b in BUILTINS if b["key"] == key))


def _fresh_builtin(key: str, order: int) -> Dict[str, Any]:
    b = _builtin(key)
    return {"id": key, "key": key, "name": b["name"], "icon": b["icon"], "tone": b["tone"],
            "conditions": b["conditions"], "description": b["description"],
            "enabled": True, "order": order}


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------
def _from_legacy(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """First visit to the page: start from the built-ins, carrying over any
    figure the owner had already set on the older status card."""
    rules = [_fresh_builtin(k, i) for i, k in enumerate(BUILTIN_KEYS)]
    by_key = {r["key"]: r for r in rules}
    active = int(doc.get("active_within_days") or 0)
    dormant = int(doc.get("dormant_after_days") or 0)
    at_risk = int(doc.get("about_to_lose_days") or 0)
    if active:
        by_key["actif"]["conditions"][0]["value"] = active
    if dormant:
        by_key["dormant"]["conditions"][0]["value"] = dormant
    # The old card's "about to lose" sat INSIDE the active window (21 < 30).
    # Here it starts where active ends, so an old value that would overlap is
    # moved to the first day after it.
    a = by_key["actif"]["conditions"][0]["value"]
    d = by_key["dormant"]["conditions"][0]["value"]
    risk = at_risk if at_risk > a else a + 1
    if risk < d:
        by_key["bientot_perdu"]["conditions"][0]["value"] = risk
    if doc.get("regular_visits_per_month"):
        by_key["regulier"]["conditions"][1]["value"] = _num(doc["regular_visits_per_month"])
    if doc.get("loyal_visits_per_month"):
        by_key["fidele"]["conditions"][0]["value"] = _num(doc["loyal_visits_per_month"])
    return rules


def _stored(tid: str) -> Dict[str, Any]:
    return _db.customer_status_config.find_one({"tenant_id": tid}) or {}


def defaults() -> List[Dict[str, Any]]:
    return _from_legacy({})


def load(tid: str) -> List[Dict[str, Any]]:
    """The tenant's rules in display order (deleted built-ins left out)."""
    if _db is None:
        return defaults()
    doc = _stored(tid)
    if "rules" not in doc:
        return _from_legacy(doc)
    rules = [dict(r) for r in doc.get("rules") or []]
    for r in rules:
        # saved before the rename: the old default name and wording follow it
        if r.get("key") == "vip" and r.get("name") == "Client VIP":
            r["name"] = "Client très actif"
            if r.get("description") == "Client très actif et à forte valeur.":
                r["description"] = _builtin("vip")["description"]
    rules.sort(key=lambda r: r.get("order", 0))
    return rules


def deleted_builtins(tid: str) -> List[str]:
    doc = _stored(tid)
    if "rules" not in doc:
        return []
    present = {r.get("key") for r in doc.get("rules") or []}
    return [k for k in BUILTIN_KEYS if k not in present]


def _legacy_fields(rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    by_key = {r.get("key"): r for r in rules if r.get("key")}

    def val(key, i=0):
        r = by_key.get(key)
        try:
            return r["conditions"][i]["value"] if r else None
        except (IndexError, KeyError):
            return None

    pairs = [("active_within_days", val("actif")), ("about_to_lose_days", val("bientot_perdu")),
             ("dormant_after_days", val("dormant")),
             ("regular_visits_per_month", val("regulier", 1)),
             ("loyal_visits_per_month", val("fidele"))]
    for field, v in pairs:
        if v is not None:
            out[field] = int(round(v)) if field.endswith("_days") else max(1, int(round(v)))
    return out


def _save(tid: str, rules: List[Dict[str, Any]]) -> None:
    for i, r in enumerate(rules):
        r["order"] = i
    _db.customer_status_config.update_one(
        {"tenant_id": tid},
        {"$set": {"tenant_id": tid, "rules": rules, "rules_updated_at": _now(),
                  "updated_at": _now(), **_legacy_fields(rules)}},
        upsert=True)


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------
def visits_per_month(cust: Dict[str, Any], at: datetime) -> float:
    """Average monthly visits since the client joined. The first month counts
    as a whole month, so a client who came once yesterday reads 1 visit a
    month, not 30."""
    visits = int(cust.get("visits") or 0)
    if visits <= 0:
        return 0.0
    joined = _aware(cust.get("created_at"))
    days = (at - joined).days if joined else 30
    return visits / max(days / 30.0, 1.0)


def _days_since(cust: Dict[str, Any], at: datetime) -> Optional[float]:
    """Days since the last visit — or since signing up for a client who has
    never come, so a card taken a year ago and never used reads as dormant."""
    ref = _aware(cust.get("last_visit_date")) or _aware(cust.get("created_at"))
    return (at - ref).total_seconds() / 86400.0 if ref else None


def _context(rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    dormant = next((r for r in rules if r.get("key") == "dormant" and r.get("enabled", True)), None)
    return {"dormant_days": dormant["conditions"][0]["value"] if dormant else None}


def _holds(cond: Dict[str, Any], cust: Dict[str, Any], at: datetime, ctx: Dict[str, Any]) -> bool:
    kind, value = cond.get("type"), _num(cond.get("value"))
    visits = int(cust.get("visits") or 0)
    if kind == "visited_within":
        last = _aware(cust.get("last_visit_date"))
        return bool(visits > 0 and last and (at - last).total_seconds() / 86400.0 < value + 1)
    if kind in ("not_visited_since", "at_risk_since"):
        days = _days_since(cust, at)
        if days is None or days < value:
            return False
        if kind == "at_risk_since":
            if visits <= 0:
                return False
            dormant = ctx.get("dormant_days")
            return dormant is None or days < dormant
        return True
    if kind == "visits_max":
        return visits <= value
    if kind == "visits_min":
        return visits >= value
    if kind == "visits_per_month":
        return visits_per_month(cust, at) >= value
    if kind == "spent_min":
        return _num(cust.get("total_amount_paid")) >= value
    if kind == "avg_basket_min":
        return visits > 0 and _num(cust.get("total_amount_paid")) / visits >= value
    if kind == "joined_within":
        joined = _aware(cust.get("created_at"))
        return bool(joined and (at - joined).days < value)
    return False


def matches(rule: Dict[str, Any], cust: Dict[str, Any], at: datetime,
            ctx: Optional[Dict[str, Any]] = None) -> bool:
    if not rule.get("enabled", True):
        return False
    conds = rule.get("conditions") or []
    if not conds:
        return False
    ctx = ctx if ctx is not None else {}
    return all(_holds(c, cust, at, ctx) for c in conds)


def primary(cust: Dict[str, Any], at: datetime, rules: List[Dict[str, Any]],
            ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The one kind a client is shown as. Returns the rule, or a fallback."""
    ctx = ctx if ctx is not None else _context(rules)
    by_key = {r.get("key"): r for r in rules if r.get("key")}
    custom = [r for r in rules if not r.get("key")]
    ordered = ([by_key[k] for k in PRIMARY_BEFORE_CUSTOM if k in by_key] + custom
               + [by_key[k] for k in PRIMARY_AFTER_CUSTOM if k in by_key])
    for r in ordered:
        if matches(r, cust, at, ctx):
            return r
    return FALLBACK_INACTIVE if int(cust.get("visits") or 0) > 0 else FALLBACK_NONE


def status_key(rule: Dict[str, Any]) -> str:
    return rule.get("key") or rule.get("id")


def statuses(rules: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Everything the Statut filter can offer, in display order."""
    out = [{"key": status_key(r), "label": r["name"], "tone": r.get("tone") or "blue"}
           for r in rules if r.get("enabled", True)]
    out.append({"key": FALLBACK_INACTIVE["key"], "label": FALLBACK_INACTIVE["name"],
                "tone": FALLBACK_INACTIVE["tone"]})
    out.append({"key": FALLBACK_NONE["key"], "label": FALLBACK_NONE["name"],
                "tone": FALLBACK_NONE["tone"]})
    return out


def active_days(rules: List[Dict[str, Any]]) -> int:
    """The "Client actif" window — what the rest of the product calls recent.
    Kept even while the rule is switched off; the default if it was deleted."""
    r = next((r for r in rules if r.get("key") == "actif"), None)
    try:
        return int(r["conditions"][0]["value"]) if r else DEFAULT_ACTIVE_DAYS
    except (KeyError, IndexError, TypeError, ValueError):
        return DEFAULT_ACTIVE_DAYS


def rule(rules: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    return next((r for r in rules if r.get("key") == key), None)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
class Condition(BaseModel):
    type: str
    value: float


class RuleIn(BaseModel):
    id: Optional[str] = None
    key: Optional[str] = None
    name: str
    icon: str = "users"
    tone: str = "blue"
    conditions: List[Condition]
    description: str = ""
    enabled: bool = True


class RulesIn(BaseModel):
    rules: List[RuleIn]


def _clean(body: RulesIn) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen_keys, seen_ids = set(), set()
    custom = 0
    for r in body.rules:
        name = (r.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Chaque règle a besoin d'un nom.")
        if len(name) > NAME_MAX:
            raise HTTPException(status_code=400, detail=f"« {name[:20]}… » : {NAME_MAX} caractères maximum.")
        description = (r.description or "").strip()
        if len(description) > DESCRIPTION_MAX:
            raise HTTPException(status_code=400,
                                detail=f"« {name} » : description limitée à {DESCRIPTION_MAX} caractères.")
        if r.icon not in ICONS or r.tone not in TONES:
            raise HTTPException(status_code=400, detail=f"« {name} » : icône ou couleur inconnue.")
        if not r.conditions or len(r.conditions) > MAX_CONDITIONS:
            raise HTTPException(status_code=400,
                                detail=f"« {name} » : entre 1 et {MAX_CONDITIONS} critères.")
        conds = []
        for c in r.conditions:
            spec = CRITERIA.get(c.type)
            if not spec:
                raise HTTPException(status_code=400, detail=f"« {name} » : critère inconnu.")
            if spec.get("builtin_only") and r.key != "bientot_perdu":
                raise HTTPException(status_code=400, detail=f"« {name} » : critère réservé.")
            if not (spec["min"] <= c.value <= spec["max"]):
                raise HTTPException(status_code=400,
                                    detail=f"« {name} » : la valeur doit être entre "
                                           f"{spec['min']:g} et {spec['max']:g} {spec['unit']}.")
            if c.type == "visits_per_month":
                value: Any = round(float(c.value), 1)
            elif c.type in ("spent_min", "avg_basket_min"):
                value = round(float(c.value), 2)
            else:
                value = int(round(c.value))
            conds.append({"type": c.type, "value": value})
        if r.key:
            if r.key not in BUILTIN_KEYS or r.key in seen_keys:
                raise HTTPException(status_code=400, detail="Règle de base inconnue ou en double.")
            expected = [c["type"] for c in _builtin(r.key)["conditions"]]
            if [c["type"] for c in conds] != expected:
                raise HTTPException(status_code=400,
                                    detail=f"« {name} » : les critères d'une règle de base ne changent pas.")
            seen_keys.add(r.key)
            rid = r.key
        else:
            custom += 1
            rid = r.id if (r.id and r.id.startswith("r_") and r.id not in seen_ids) else f"r_{uuid.uuid4().hex[:10]}"
        seen_ids.add(rid)
        out.append({"id": rid, "key": r.key, "name": name, "icon": r.icon, "tone": r.tone,
                    "conditions": conds, "description": description, "enabled": bool(r.enabled)})
    if custom > MAX_CUSTOM:
        raise HTTPException(status_code=400, detail=f"{MAX_CUSTOM} règles personnalisées maximum.")
    _check_ladders(out)
    return out


def _check_ladders(rules: List[Dict[str, Any]]) -> None:
    """The built-ins describe one line of time and one line of frequency —
    they must not cross, or a client would be both at once."""
    by_key = {r["key"]: r for r in rules if r.get("key")}

    def v(key, i=0):
        r = by_key.get(key)
        return r["conditions"][i]["value"] if r else None

    active, risk, dormant = v("actif"), v("bientot_perdu"), v("dormant")
    if active is not None and risk is not None and risk <= active:
        raise HTTPException(status_code=400,
                            detail=f"« Client bientôt perdu » doit commencer après les {active} jours "
                                   f"de « Client actif ».")
    if risk is not None and dormant is not None and dormant <= risk:
        raise HTTPException(status_code=400,
                            detail=f"« Client dormant » doit commencer après les {risk} jours "
                                   f"de « Client bientôt perdu ».")
    if active is not None and dormant is not None and dormant <= active:
        raise HTTPException(status_code=400,
                            detail=f"« Client dormant » doit commencer après les {active} jours "
                                   f"de « Client actif ».")
    ladder = [(k, v(k, 1) if k == "regulier" else v(k)) for k in ("regulier", "fidele", "vip")]
    ladder = [(k, x) for k, x in ladder if x is not None]
    names = {"regulier": "Client régulier", "fidele": "Client fidèle", "vip": "Client très actif"}
    for (k1, x1), (k2, x2) in zip(ladder, ladder[1:]):
        if x2 <= x1:
            raise HTTPException(status_code=400,
                                detail=f"« {names[k2]} » doit demander plus de visites par mois que "
                                       f"« {names[k1]} » ({x1:g}).")


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
def _payload(tid: str) -> Dict[str, Any]:
    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1}) or {}
    return {
        "shop": tenant.get("name") or "",
        "rules": load(tid),
        "deleted_builtins": [{"key": k, "name": _builtin(k)["name"]} for k in deleted_builtins(tid)],
        "criteria": [{"type": k, "label": v["label"], "unit": v["unit"], "min": v["min"],
                      "max": v["max"], "builtin_only": bool(v.get("builtin_only"))}
                     for k, v in CRITERIA.items()],
        "icons": ICONS, "tones": TONES,
        "limits": {"conditions": MAX_CONDITIONS, "custom": MAX_CUSTOM,
                   "name": NAME_MAX, "description": DESCRIPTION_MAX},
    }


@router.get("/api/owner/customer-rules")
def get_rules(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    return _payload(token_data.tenant_id)


@router.put("/api/owner/customer-rules")
@SV.records("regles-clients")
def put_rules(body: RulesIn, token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    _save(tid, _clean(body))
    return _payload(tid)


@router.post("/api/owner/customer-rules/restore")
@SV.records("regles-clients")
def restore_builtins(token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Brings back the built-in rules the owner deleted, at their usual place,
    with their usual figures. Rules still present are left as they are."""
    tid = token_data.tenant_id
    rules = load(tid)
    present = {r.get("key") for r in rules}
    for i, key in enumerate(BUILTIN_KEYS):
        if key in present:
            continue
        pos = next((j for j, r in enumerate(rules)
                    if r.get("key") in BUILTIN_KEYS[i + 1:]), len(rules))
        rules.insert(pos, _fresh_builtin(key, pos))
    try:
        _check_ladders(rules)
    except HTTPException:
        # A restored default can collide with a figure the owner moved; put
        # the whole time line back to its defaults rather than refuse.
        for r in rules:
            if r.get("key") in ("actif", "bientot_perdu", "dormant", "regulier", "fidele", "vip"):
                r["conditions"] = _builtin(r["key"])["conditions"]
    _save(tid, rules)
    return _payload(tid)
