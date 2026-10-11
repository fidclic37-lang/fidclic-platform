"""
Super admin › Plan Limits — built to the approved mockup, and the rules that
make every limit and switch real for the businesses.

What the user decided (2026-09-30):
- Prices 33 / 65 / 108 € HT (Starter / Pro / Pro AI), since 2026-10-03.
- What each plan unlocks follows the pricing grid (models.PLAN_FEATURES):
  Starter gets the card, wallet and rewards; CRM avancé, segmentation,
  campagnes, automatisations, géolocalisation, parrainage, analytics avancés
  and FIDCLIC AI are locked. Pro unlocks all but full AI (« analyses de
  base »), Pro AI everything (« analyses avancées »).
- A locked section stays visible to the merchant; opening it shows the
  upgrade prompt. The server refuses the section's calls (PlanGuard below),
  so the lock holds whatever the browser does.
- « Ajouter un plan »: the super admin can create plans (no online payment
  for them yet) and give them to businesses from the business's page.
- « Appliquer automatiquement les limites aux nouveaux commerces »: on, a
  change reaches every business at once; off, only businesses that join the
  plan afterwards get it — the ones already on it keep their limits until
  their next billing cycle (tenant.limits_pin, read by server.features_for).
- « Notifier les commerces quand ils approchent de leur limite »: a banner on
  the business's dashboard and one email per limit and month.
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import TokenData, require_role
from features.platform_access import require_admin

router = APIRouter(tags=["plans"])
_db = None
SETTINGS_KEY = "plan_limit_settings"
DEFAULT_SETTINGS = {
    "auto_apply": True,
    "notify_near_limit": True,
    "alert_threshold": 80,
    "alert_message": "Vous avez utilisé {pourcentage}% de votre limite de {fonctionnalité}.\n\n"
                     "Passez au plan supérieur pour continuer à profiter pleinement de FIDCLIC !",
}
OWNER = ["business_owner", "administrateur", "manager", "staff"]

# The rows of « Détail des limites par plan », in the mockup's order, then the
# other limits FidClic already had (nothing was removed).
ROWS = [
    {"key": "establishments", "label": "Nombre de commerces autorisés", "type": "int", "icon": "store",
     "help": "Établissements (points de vente) que le commerce peut gérer."},
    {"key": "new_cards_per_month", "label": "Nombre de cartes de fidélité (par mois)", "type": "int", "icon": "card",
     "help": "Nouvelles cartes données dans le mois. 0 = illimité."},
    {"key": "push_per_month", "label": "Nombre de notifications (par mois)", "type": "int", "icon": "bell",
     "help": "Notifications envoyées dans le mois. 0 = illimité."},
    {"key": "invite_emails_per_month", "label": "Emails d'invitation (par mois)", "type": "int", "icon": "mail",
     "help": "Emails « Ajoutez votre carte » aux clients importés, relances comprises. 0 = illimité."},
    {"key": "ai_level", "label": "Accès à l'IA (analyses de base/avancées)", "type": "ai", "icon": "sparkles",
     "help": "Non : pas d'IA. Base : IA limitée. Avancées : toute l'IA, sans limite par fonction."},
    {"key": "geo_proximity", "label": "Géolocalisation", "type": "bool", "icon": "pin",
     "help": "Carte des clients et notifications de proximité."},
    {"key": "wallet", "label": "Wallet (Apple/Google)", "type": "bool", "icon": "wallet",
     "help": "Les clients peuvent ajouter leur carte à Apple Wallet et Google Wallet."},
    {"key": "multi_branch", "label": "Multi-établissements", "type": "bool", "icon": "branches",
     "help": "Plusieurs points de vente dans un même compte."},
    {"key": "priority_support", "label": "Support prioritaire", "type": "bool", "icon": "headset",
     "help": "Les demandes de support du commerce passent en tête et vous alertent."},
    {"key": "campaigns", "label": "Accès aux campagnes", "type": "bool", "icon": "megaphone",
     "help": "Campagnes ciblées (page Campagnes)."},
    {"key": "advanced_analytics", "label": "Tableaux de bord avancés", "type": "bool", "icon": "chart",
     "help": "Pages Analyses et Insights."},
    {"key": "csv_export", "label": "Export des données (CSV)", "type": "bool", "icon": "download",
     "help": "Boutons « Exporter » du tableau de bord."},
    {"key": "api_access", "label": "API & Intégrations", "type": "bool", "icon": "plug",
     "help": "Clés API et intégrations (caisses, outils)."},
    {"key": "crm_advanced", "label": "CRM avancé", "type": "bool", "icon": "database",
     "help": "Segments, filtres avancés, filtres enregistrés et page Historique. Sans : liste simple des clients."},
    {"key": "segmentation", "label": "Segmentation clients", "type": "bool", "icon": "pie", "help": "Page Segmentation."},
    {"key": "automations", "label": "Automatisation marketing", "type": "bool", "icon": "zap", "help": "Page Automatisations et ses envois automatiques."},
    {"key": "referral", "label": "Parrainage", "type": "bool", "icon": "share", "help": "Programme de parrainage."},
    {"key": "max_customers", "label": "Cartes clients (clients actifs)", "type": "int", "icon": "users",
     "help": "Clients venus au moins une fois dans les 12 derniers mois."},
    {"key": "campaigns_per_month", "label": "Campagnes par mois", "type": "int", "icon": "megaphone", "help": "0 = illimité."},
    {"key": "staff_accounts", "label": "Comptes équipe", "type": "int", "icon": "users", "help": "Propriétaire compris."},
    {"key": "ai_queries_per_day", "label": "Requêtes IA par jour", "type": "int", "icon": "sparkles",
     "help": "Plafond de toutes les demandes IA de la journée."},
    {"key": "trial_duration_days", "label": "Durée de l'essai gratuit (jours)", "type": "int", "icon": "clock", "help": ""},
    {"key": "trial_reminder_days_before", "label": "Rappel avant la fin de l'essai (jours)", "type": "int", "icon": "clock", "help": ""},
]
ROW_KEYS = [r["key"] for r in ROWS]
FEATURE_LABEL = {r["key"]: r["label"] for r in ROWS}
FEATURE_LABEL.update({"ai": "FIDCLIC AI", "advanced_analytics": "Analytics avancés", "campaigns": "Campagnes ciblées",
                      "crm_advanced": "CRM avancé", "geo_proximity": "Géolocalisation", "csv_export": "l'export des données"})
TONES = {"silver": "#2F6BFF", "gold": "#10B981", "vip": "#8B5CF6", "franchise": "#F59E0B"}


def init(db):
    global _db
    _db = db
    try:
        _db.ai_usage.create_index([("tenant_id", 1), ("kind", 1), ("at", 1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def settings() -> Dict[str, Any]:
    doc = (_db.platform_settings.find_one({"key": SETTINGS_KEY}, {"_id": 0}) or {}).get("value") or {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in doc.items() if k in DEFAULT_SETTINGS}}


# ---------------------------------------------------------------------------
# What a business may use
# ---------------------------------------------------------------------------
def tenant_features(tenant_id: Optional[str]) -> Dict[str, Any]:
    import server as core
    t = _db.tenants.find_one({"id": tenant_id}, {"_id": 0}) if tenant_id else None
    return core.features_for(t or {})


def allows(features: Dict[str, Any], key: str) -> bool:
    if key == "ai":
        return (features.get("ai_level") or "none") != "none"
    v = features.get(key)
    return True if v is None and key not in ROW_KEYS else bool(v)


def allows_tenant(tenant_id: Optional[str], key: str) -> bool:
    try:
        return allows(tenant_features(tenant_id), key)
    except Exception:
        return True                        # a lookup failure never blocks a customer-facing path


def plans_catalog(active_only: bool = False) -> List[Dict[str, Any]]:
    """Every plan (the 3 self-serve ones, Franchise, then the super admin's),
    with its effective features."""
    import server as core
    import models
    out = []
    meta_all = {d["plan"]: d.get("meta") or {} for d in _db.plan_settings.find({}, {"_id": 0, "plan": 1, "meta": 1})}
    for key in ("silver", "gold", "vip", "franchise"):
        meta = meta_all.get(key, {})
        out.append({"key": key, "label": models.PLAN_LABELS.get(key, key),
                    "tagline": meta.get("tagline") or models.PLAN_TAGLINES.get(key, ""), "custom": False,
                    "on_quote": key == "franchise", "active": meta.get("active", True), "color": TONES.get(key),
                    "features": core.get_plan_features(key)})
    for key, c in core.custom_plans(refresh=True).items():
        out.append({"key": key, "label": c.get("label") or key, "tagline": c.get("tagline") or "", "custom": True,
                    "on_quote": False, "active": c.get("active", True), "color": c.get("color") or "#0EA5E9",
                    "features": core.get_plan_features(key)})
    return [p for p in out if p["active"] or not active_only]


def upgrade_for(features: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """The cheapest active plan (not on quote) that unlocks `key`."""
    price_now = float(features.get("price") or 0)
    best = None
    for p in plans_catalog(active_only=True):
        f = p["features"]
        if p["on_quote"] or not allows(f, key) or f.get("label") == features.get("label"):
            continue
        if key == "ai" and features.get("ai_level") == "basic" and f.get("ai_level") != "advanced":
            continue
        price = float(f.get("price") or 0)
        if price < price_now:
            continue
        if best is None or price < best["price"]:
            best = {"key": p["key"], "label": p["label"], "price": price}
    return best


def locked(features: Dict[str, Any], key: str) -> Dict[str, Any]:
    up = upgrade_for(features, key)
    label = FEATURE_LABEL.get(key, key)
    return {"code": "PLAN_FEATURE_DISABLED", "feature": key, "label": label, "plan": features.get("label"),
            "message": f"« {label} » n'est pas inclus dans votre offre {features.get('label') or ''}.".replace(" ».", " »."),
            "upgrade": up}


def require_feature(token_data: TokenData, key: str) -> Dict[str, Any]:
    """For endpoints: raise 403 when the business's plan does not include `key`."""
    if token_data is None or not token_data.tenant_id or token_data.role in ("super_admin", "fidclic_team", "commercial"):
        return {}
    f = tenant_features(token_data.tenant_id)
    if not allows(f, key):
        raise HTTPException(status_code=403, detail=locked(f, key))
    return f


# Owner API paths and the feature each needs. The first match wins.
PATH_RULES = [
    (re.compile(r"^/api/owner/campaigns/ai-draft"), "ai"),
    (re.compile(r"^/api/owner/campaigns/[^/]+/ai-analyze"), "ai"),
    (re.compile(r"^/api/owner/(copilot|ai/|ai-query)"), "ai"),
    (re.compile(r"^/api/owner/catalog/parse-menu"), "ai"),
    (re.compile(r"^/api/owner/insights/templates/"), "campaigns"),
    # The bell's alerts and the Google review link are not analytics.
    (re.compile(r"^/api/owner/(analyses|insights)(?!/(alerts|google-review))(/|$)"), "advanced_analytics"),
    (re.compile(r"^/api/owner/segmentation(/|$)"), "segmentation"),
    (re.compile(r"^/api/owner/segments(/|$)"), "crm_advanced"),
    (re.compile(r"^/api/owner/history(/|$)"), "crm_advanced"),
    (re.compile(r"^/api/owner/(campaigns|notifications/typed|notifications/re-enablement)(/|$)"), "campaigns"),
    (re.compile(r"^/api/owner/(auto-campaigns|push-wallet|automations)(/|$)"), "automations"),
    (re.compile(r"^/api/owner/referrals(/|$)"), "referral"),
    (re.compile(r"^/api/owner/geo(/|$)"), "geo_proximity"),
    (re.compile(r"^/api/owner/integrations(/|$)"), "api_access"),
    (re.compile(r"^/api/owner/.*(/export(/|$|\?)|/export\.(pdf|csv))"), "csv_export"),
]
# AI calls that cost a model request: counted against the plan.
AI_CALLS = [
    (re.compile(r"^/api/owner/copilot/chat$"), "copilot_question", ("POST",)),
    (re.compile(r"^/api/owner/campaigns/ai-draft$"), "ai_campaign", ("POST",)),
    (re.compile(r"^/api/owner/campaigns/[^/]+/ai-analyze$"), "ai_call", ("POST",)),
    (re.compile(r"^/api/owner/catalog/parse-menu$"), "ai_call", ("POST",)),
    (re.compile(r"^/api/owner/(ai-query|ai/ask)$"), "ai_call", ("POST",)),
]
KIND_LIMIT = {"copilot_question": ("copilot_questions_per_day", "day", "questions au Copilot"),
              "ai_campaign": ("ai_campaigns_per_month", "month", "campagnes rédigées par l'IA")}


def rule_for(path: str) -> Optional[str]:
    for rx, key in PATH_RULES:
        if rx.search(path):
            return key
    return None


def ai_call_kind(path: str, method: str) -> Optional[str]:
    for rx, kind, methods in AI_CALLS:
        if rx.search(path) and method in methods:
            return kind
    return None


def _since(period: str, now: datetime) -> datetime:
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day if period == "day" else day.replace(day=1)


def ai_quota(tenant_id: str, f: Dict[str, Any], kind: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """None when the call may go; else the 429 detail."""
    import models
    now = now or _now()
    level = f.get("ai_level") or "none"
    cap = int(f.get("ai_queries_per_day") or 0)
    if cap > 0 and _db.ai_usage.count_documents({"tenant_id": tenant_id, "at": {"$gte": _since("day", now)}}) >= cap:
        return {"code": "PLAN_QUOTA_REACHED", "feature": "ai_queries_per_day", "limit": cap,
                "message": f"Vous avez utilisé vos {cap} requêtes IA du jour. Elles reviennent demain.", "upgrade": upgrade_for(f, "ai")}
    if kind in KIND_LIMIT:
        field, period, what = KIND_LIMIT[kind]
        lim = (models.AI_LEVEL_LIMITS.get(level) or {}).get(field)
        if lim is not None:
            used = _db.ai_usage.count_documents({"tenant_id": tenant_id, "kind": kind, "at": {"$gte": _since(period, now)}})
            if used >= lim:
                when = "demain" if period == "day" else "le mois prochain"
                return {"code": "PLAN_QUOTA_REACHED", "feature": field, "limit": lim,
                        "message": f"Votre offre inclut {lim} {what} par {'jour' if period == 'day' else 'mois'}. La suite {when}.",
                        "upgrade": upgrade_for(f, "ai")}
    return None


def record_ai(tenant_id: str, kind: str) -> None:
    _db.ai_usage.insert_one({"id": uuid.uuid4().hex, "tenant_id": tenant_id, "kind": kind, "at": _now()})


def ai_recommendation_limit(tenant_id: Optional[str]) -> Optional[int]:
    import models
    f = tenant_features(tenant_id)
    return (models.AI_LEVEL_LIMITS.get(f.get("ai_level") or "none") or {}).get("recommendations")


async def guard(request: Request, call_next):
    """Middleware: an owner call into a section the plan does not include is
    refused with 403 PLAN_FEATURE_DISABLED; AI calls are counted."""
    path = request.url.path
    if not path.startswith("/api/owner/") or request.method == "OPTIONS":
        return await call_next(request)
    key = rule_for(path)
    kind = ai_call_kind(path, request.method)
    if not key and not kind:
        return await call_next(request)
    try:
        import auth
        td = await auth.get_current_user_data(request)
    except Exception:
        return await call_next(request)          # the endpoint answers 401 itself
    if not td.tenant_id or td.role in ("super_admin", "fidclic_team", "commercial"):
        return await call_next(request)
    try:
        f = tenant_features(td.tenant_id)
    except Exception:
        return await call_next(request)
    if key and not allows(f, key):
        return JSONResponse(status_code=403, content={"detail": locked(f, key)})
    if kind:
        over = ai_quota(td.tenant_id, f, kind)
        if over:
            return JSONResponse(status_code=429, content={"detail": over})
    response = await call_next(request)
    if kind and response.status_code < 400:
        try:
            record_ai(td.tenant_id, kind)
        except Exception:
            pass
    return response


def plan_bullets(f: Dict[str, Any]) -> List[str]:
    """What the plan includes, in the pricing grid's words — built from its
    switches, so the owner's « Abonnement » page never promises a locked one."""
    n = lambda x: f"{int(x):,}".replace(",", " ")          # noqa: E731
    out = ["Carte digitale personnalisée"]
    if f.get("wallet"):
        out.append("Apple Wallet & Google Wallet")
    out += ["Points & récompenses", f"{n(f.get('max_customers') or 0)} cartes clients" if f.get("max_customers") else "Cartes clients illimitées",
            f"{n(f['push_per_month'])} notifications / mois" if f.get("push_per_month") else "Notifications illimitées"]
    for key, label in (("crm_advanced", "CRM avancé"), ("segmentation", "Segmentation clients"), ("campaigns", "Campagnes ciblées"),
                       ("automations", "Automatisation marketing"), ("geo_proximity", "Géolocalisation"), ("referral", "Parrainage"),
                       ("advanced_analytics", "Analytics avancés")):
        if f.get(key):
            out.append(label)
    level = f.get("ai_level") or "none"
    if level != "none":
        out.append("FIDCLIC AI" + (" (analyses de base)" if level == "basic" else ""))
    for key, label in (("multi_branch", "Plusieurs établissements"), ("priority_support", "Support prioritaire"),
                       ("api_access", "API & Intégrations")):
        if f.get(key):
            out.append(label)
    return out


# ---------------------------------------------------------------------------
# Owner side: what is locked, and the near-limit banner
# ---------------------------------------------------------------------------
SECTIONS = {"analytics": "advanced_analytics", "insights": "advanced_analytics", "segmentation": "segmentation",
            "campaigns": "campaigns", "automations": "automations", "referral": "referral", "map": "geo_proximity",
            "ai-assistant": "ai", "history": "crm_advanced"}


@router.get("/api/owner/plan-access")
def plan_access(token_data: TokenData = Depends(require_role(OWNER))):
    import models
    f = tenant_features(token_data.tenant_id)
    keys = set(SECTIONS.values()) | {"csv_export", "wallet", "multi_branch", "priority_support", "api_access", "crm_advanced"}
    return {"plan": f.get("label"), "features": {k: allows(f, k) for k in sorted(keys)},
            "locked": {k: locked(f, k) for k in sorted(keys) if not allows(f, k)},
            "sections": {s: allows(f, k) for s, k in SECTIONS.items()},
            "ai_level": f.get("ai_level") or "none", "ai_limits": models.AI_LEVEL_LIMITS.get(f.get("ai_level") or "none"),
            "ai_queries_per_day": f.get("ai_queries_per_day")}


def _invites_this_month(tid: str, now: datetime) -> int:
    try:
        from features.client_import import invites_used_this_month
        return invites_used_this_month(tid, now)
    except Exception:
        return 0


def usage_of(tenant: Dict[str, Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The limits that count, with how much is used."""
    import server as core
    from features import plans_public as PP
    now = now or _now()
    f = core.features_for(tenant)
    tid = tenant["id"]
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = [("new_cards_per_month", "cartes de fidélité", _db.customers.count_documents({"tenant_id": tid, "created_at": {"$gte": month}})),
            ("push_per_month", "notifications", PP.push_used_this_month(tid, now)),
            ("invite_emails_per_month", "emails d'invitation", _invites_this_month(tid, now)),
            ("max_customers", "clients actifs", core.count_active_customers(tid, now))]
    if allows(f, "campaigns"):
        rows.append(("campaigns_per_month", "campagnes", PP.campaigns_used_this_month(tid)))
    out = []
    for key, what, used in rows:
        lim = int(f.get(key) or 0)
        if lim > 0:
            out.append({"key": key, "what": what, "used": used, "limit": lim, "pct": round(used / lim * 100)})
    return out


def _message(tpl: str, pct: int, what: str) -> str:
    return tpl.replace("{pourcentage}", str(pct)).replace("{fonctionnalité}", what).replace("{fonctionnalite}", what)


@router.get("/api/owner/limit-alerts")
def limit_alerts(token_data: TokenData = Depends(require_role(OWNER))):
    s = settings()
    if not s["notify_near_limit"] or not token_data.tenant_id:
        return {"alerts": []}
    t = _db.tenants.find_one({"id": token_data.tenant_id}, {"_id": 0})
    if not t:
        return {"alerts": []}
    import server as core
    f = core.features_for(t)
    alerts = []
    for u in usage_of(t):
        if u["pct"] >= s["alert_threshold"]:
            alerts.append({**u, "message": _message(s["alert_message"], min(u["pct"], 999), u["what"]),
                           "upgrade": _next_bigger(f, u["key"])})
    return {"alerts": alerts, "threshold": s["alert_threshold"]}


def _next_bigger(f: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """Cheapest active self-serve plan with a bigger `key` limit (0 = unlimited)."""
    mine = int(f.get(key) or 0)
    best = None
    for p in plans_catalog(active_only=True):
        pf = p["features"]
        if p["on_quote"] or pf.get("label") == f.get("label"):
            continue
        lim = int(pf.get(key) or 0)
        if mine and (lim == 0 or lim > mine):
            price = float(pf.get("price") or 0)
            if best is None or price < best["price"]:
                best = {"key": p["key"], "label": p["label"], "price": price}
    return best


def run_limit_alerts(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Daily cron: one email per business, limit and month once the threshold
    is reached (the banner shows it on the dashboard in the meantime)."""
    s = settings()
    if not s["notify_near_limit"]:
        return {"sent": 0, "skipped": "disabled"}
    now = now or _now()
    stamp = now.strftime("%Y-%m")
    sent = 0
    from services import mailer
    try:
        from features import preferences
    except Exception:
        preferences = None
    for t in _db.tenants.find({"is_active": {"$ne": False}, "suspended_at": {"$in": [None]}}, {"_id": 0}):
        done = t.get("limit_alerts_sent") or {}
        due = [u for u in usage_of(t, now) if u["pct"] >= s["alert_threshold"] and done.get(f"{stamp}:{u['key']}") is None]
        if not due:
            continue
        owner = _db.users.find_one({"tenant_id": t["id"], "role": "business_owner"}, {"_id": 0})
        if not owner or not owner.get("email"):
            continue
        if preferences is not None:
            try:
                if not preferences.wants_email(owner["email"], "billing"):
                    continue
            except Exception:
                pass
        n = lambda x: f"{x:,}".replace(",", " ")          # noqa: E731
        lines = "".join(f"<p>{_message(s['alert_message'], u['pct'], u['what']).replace(chr(10), '<br>')}</p>"
                        f"<p style='color:#64748B'>{n(u['used'])} / {n(u['limit'])} {u['what']}.</p>" for u in due)
        res = mailer.send(owner["email"], f"FidClic — vous approchez de votre limite ({due[0]['what']})",
                          f"<div style='font-family:Arial,sans-serif;font-size:14px;color:#0B1C3F'>"
                          f"<p>Bonjour {owner.get('first_name') or ''},</p>{lines}"
                          f"<p><a href='https://app.fidclic.com/dashboard/parametres/abonnement'>Voir mon abonnement</a></p></div>",
                          to_name=owner.get("first_name"))
        if res.get("sent"):
            sent += 1
            _db.tenants.update_one({"id": t["id"]}, {"$set": {f"limit_alerts_sent.{stamp}:{u['key']}": now for u in due}})
    return {"sent": sent}


# ---------------------------------------------------------------------------
# Super admin › Plan Limits
# ---------------------------------------------------------------------------
def _count_by_plan() -> Dict[str, int]:
    import server as core
    out: Dict[str, int] = {}
    for t in _db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0, "plan": 1}):
        k = core._canonical_plan(t.get("plan"))
        out[k] = out.get(k, 0) + 1
    return out


def _history(limit: int = 5) -> List[Dict[str, Any]]:
    import models
    rows = list(_db.audit_logs.find({"action": {"$regex": "^admin\\.plan"}}, {"_id": 0}).sort("ts", -1).limit(limit))
    names = {u["email"]: " ".join(x for x in (u.get("first_name"), (u.get("last_name") or "")[:1] + ("." if u.get("last_name") else "")) if x)
             for u in _db.users.find({"email": {"$in": list({r.get("actor") for r in rows})}}, {"_id": 0, "email": 1, "first_name": 1, "last_name": 1})}
    out = []
    for r in rows:
        m = r.get("meta") or {}
        plan = m.get("label") or models.PLAN_LABELS.get(r.get("target"), r.get("target"))
        a = r.get("action")
        text = {"admin.plan_update": f"Modification des limites — {plan}", "admin.plan_create": f"Création de l'offre {plan}",
                "admin.plan_meta": f"Modification de l'offre {plan}", "admin.plan_delete": f"Suppression de l'offre {plan}",
                "admin.plan_reset": "Limites réinitialisées aux valeurs par défaut",
                "admin.plan_settings": "Paramètres généraux des limites mis à jour",
                "admin.plan_change": "Changement d'offre d'un commerce"}.get(a, a)
        if a == "admin.plan_update" and m.get("changed"):
            text += " : " + ", ".join(FEATURE_LABEL.get(k, k) for k in m["changed"][:3]) + ("…" if len(m["changed"]) > 3 else "")
        ts = _aware(r.get("ts"))
        out.append({"text": text, "at": ts.isoformat() if ts else None, "by": names.get(r.get("actor")) or r.get("actor")})
    return out


@router.get("/api/admin/plan-limits")
def page(token_data: TokenData = Depends(require_admin("plan_limits"))):
    counts = _count_by_plan()
    total = sum(counts.values())
    plans = []
    for p in plans_catalog():
        n = counts.get(p["key"], 0)
        plans.append({**{k: v for k, v in p.items() if k != "features"}, "price": p["features"].get("price"),
                      "features": {k: p["features"].get(k) for k in ROW_KEYS}, "commerces": n,
                      "pct": round(n / total * 100) if total else 0})
    import models
    return {"plans": plans, "rows": ROWS, "settings": settings(), "history": _history(), "total": total,
            "defaults": {k: {r: models.PLAN_FEATURES[k].get(r) for r in ROW_KEYS if r in models.PLAN_FEATURES[k]}
                         for k in ("silver", "gold", "vip", "franchise")},
            "ai_levels": [{"key": "none", "label": "Non"}, {"key": "basic", "label": "Analyses de base"},
                          {"key": "advanced", "label": "Analyses avancées"}]}


@router.get("/api/admin/plan-limits/history")
def history(limit: int = 50, token_data: TokenData = Depends(require_admin("plan_limits"))):
    return {"rows": _history(max(1, min(200, int(limit))))}


def _clean(values: Dict[str, Any]) -> Dict[str, Any]:
    import models
    out = {}
    for r in ROWS:
        k = r["key"]
        if k not in values or values[k] is None:
            continue
        v = values[k]
        if r["type"] == "int":
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"« {r['label']} » doit être un nombre.")
            if v < 0 or v > 10_000_000:
                raise HTTPException(status_code=400, detail=f"« {r['label']} » : valeur hors limites.")
        elif r["type"] == "bool":
            v = bool(v)
        elif r["type"] == "ai":
            if v not in models.AI_LEVELS:
                raise HTTPException(status_code=400, detail="Niveau d'IA inconnu.")
        out[k] = v
    return out


def next_cycle(t: Dict[str, Any], now: datetime) -> datetime:
    """When this business's current billing period ends."""
    for k in ("subscription_period_end", "trial_ends_at"):
        d = _aware(t.get(k))
        if d and d > now:
            return d
    start = _aware(t.get("subscription_started_at")) or _aware(t.get("trial_ends_at")) or _aware(t.get("created_at")) or now
    d = start
    while d <= now:                                   # next monthly anniversary
        month = d.month % 12 + 1
        year = d.year + (1 if d.month == 12 else 0)
        day = min(start.day, 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31)
        d = d.replace(year=year, month=month, day=day)
    return d


def _apply_change(plan: str, before: Dict[str, Any], by: str) -> int:
    """« Appliquer automatiquement » off: businesses already on `plan` keep
    `before` until their next billing cycle. On: nobody keeps old limits."""
    import server as core
    legacy = [k for k, v in core._LEGACY_PLAN_MAP.items() if v == plan]
    match = {"plan": {"$in": [plan] + legacy}}
    if settings()["auto_apply"]:
        _db.tenants.update_many(match, {"$unset": {"limits_pin": ""}})
        return 0
    now = _now()
    n = 0
    for t in _db.tenants.find({**match, "is_active": {"$ne": False}}, {"_id": 0}):
        pin = t.get("limits_pin") or {}
        until = _aware(pin.get("until"))
        if pin.get("plan") == plan and until and until > now:
            continue                                   # already on its old limits until renewal
        _db.tenants.update_one({"id": t["id"]}, {"$set": {"limits_pin": {
            "plan": plan, "features": {k: before.get(k) for k in ROW_KEYS if k in before},
            "until": next_cycle(t, now), "set_at": now, "by": by}}})
        n += 1
    return n


class SettingsIn(BaseModel):
    auto_apply: bool
    notify_near_limit: bool
    alert_threshold: int = Field(..., ge=1, le=100)
    alert_message: str = Field(..., min_length=1, max_length=500)


@router.put("/api/admin/plan-limits/settings")
def save_settings(body: SettingsIn, token_data: TokenData = Depends(require_admin("plan_limits"))):
    import server as core
    _db.platform_settings.update_one({"key": SETTINGS_KEY}, {"$set": {"key": SETTINGS_KEY, "value": body.dict(), "updated_at": _now(),
                                                                      "updated_by": token_data.email}}, upsert=True)
    core.log_audit("admin.plan_settings", actor=token_data.email, actor_type="user", target="plans", meta=body.dict())
    return settings()


class LimitsIn(BaseModel):
    features: Dict[str, Any]


@router.put("/api/admin/plan-limits/{plan}")
def save_limits(plan: str, body: LimitsIn, token_data: TokenData = Depends(require_admin("plan_limits"))):
    import server as core
    import models
    custom = core.custom_plans(refresh=True).get(plan)
    if plan not in models.PLAN_FEATURES and not custom:
        raise HTTPException(status_code=404, detail="Offre introuvable.")
    values = _clean(body.features)
    before = core.get_plan_features(plan)
    changed = [k for k, v in values.items() if before.get(k) != v]
    if not changed:
        return {"ok": True, "changed": []}
    if custom:
        _db.plan_catalog.update_one({"key": plan}, {"$set": {**{f"features.{k}": v for k, v in values.items()},
                                                             "updated_at": _now(), "updated_by": token_data.email}})
    else:
        doc = _db.plan_settings.find_one({"plan": plan}) or {}
        ov = dict(doc.get("overrides") or {})
        base = dict(models.PLAN_FEATURES[plan])
        for k, v in values.items():
            if base.get(k) == v:
                ov.pop(k, None)                        # back to the default: no override kept
            else:
                ov[k] = v
        _db.plan_settings.update_one({"plan": plan}, {"$set": {"plan": plan, "overrides": ov, "updated_at": _now(),
                                                               "updated_by": token_data.email}}, upsert=True)
    core.custom_plans(refresh=True)
    kept = _apply_change(plan, before, token_data.email)
    core.log_audit("admin.plan_update", actor=token_data.email, actor_type="user", target=plan,
                   meta={"changed": changed, "values": {k: values[k] for k in changed}, "label": before.get("label"),
                         "kept_until_renewal": kept})
    return {"ok": True, "changed": changed, "kept_until_renewal": kept}


class MetaIn(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=40)
    tagline: Optional[str] = Field(None, max_length=120)
    price: Optional[float] = Field(None, ge=0, le=100000)
    active: Optional[bool] = None
    color: Optional[str] = Field(None, max_length=9)


@router.put("/api/admin/plan-limits/{plan}/meta")
def save_meta(plan: str, body: MetaIn, token_data: TokenData = Depends(require_admin("plan_limits"))):
    import server as core
    import models
    custom = core.custom_plans(refresh=True).get(plan)
    if plan not in models.PLAN_FEATURES and not custom:
        raise HTTPException(status_code=404, detail="Offre introuvable.")
    data = body.dict(exclude_unset=True)
    if custom:
        upd = {k: v for k, v in data.items() if k != "price"}
        if "price" in data:
            upd["features.price"] = data["price"]
        _db.plan_catalog.update_one({"key": plan}, {"$set": {**upd, "updated_at": _now()}})
    else:
        if "label" in data:
            raise HTTPException(status_code=400, detail="Le nom des offres Starter, Pro, Pro AI et Franchise ne change pas ici.")
        upd = {f"meta.{k}": v for k, v in data.items() if k in ("tagline", "active")}
        if "price" in data:
            upd["overrides.price"] = data["price"]
        if upd:
            _db.plan_settings.update_one({"plan": plan}, {"$set": {"plan": plan, **upd, "updated_at": _now()}}, upsert=True)
    core.custom_plans(refresh=True)
    core.log_audit("admin.plan_meta", actor=token_data.email, actor_type="user", target=plan,
                   meta={**data, "label": data.get("label") or core.plan_label(plan)})
    return {"ok": True}


class NewPlanIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=40)
    tagline: Optional[str] = Field("", max_length=120)
    price: float = Field(0, ge=0, le=100000)
    copy_from: str = "silver"
    color: Optional[str] = Field("#0EA5E9", max_length=9)


@router.post("/api/admin/plan-limits")
def create_plan(body: NewPlanIn, token_data: TokenData = Depends(require_admin("plan_limits"))):
    import server as core
    import unicodedata
    slug = unicodedata.normalize("NFKD", body.label).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:24] or "offre"
    key = f"plan-{slug}"
    existing = {p["key"] for p in plans_catalog()} | {p["label"].lower() for p in plans_catalog()}
    if body.label.strip().lower() in existing:
        raise HTTPException(status_code=409, detail="Une offre porte déjà ce nom.")
    while key in existing:
        key = f"plan-{slug}-{uuid.uuid4().hex[:4]}"
    base = core.get_plan_features(body.copy_from if body.copy_from in ("silver", "gold", "vip") else "silver")
    features = {k: base.get(k) for k in ROW_KEYS}
    features["price"] = body.price
    _db.plan_catalog.insert_one({"key": key, "label": body.label.strip(), "tagline": (body.tagline or "").strip(),
                                 "color": body.color, "active": True, "features": features, "created_at": _now(),
                                 "created_by": token_data.email})
    core.custom_plans(refresh=True)
    core.log_audit("admin.plan_create", actor=token_data.email, actor_type="user", target=key,
                   meta={"label": body.label, "price": body.price, "copy_from": body.copy_from})
    return {"key": key}


@router.delete("/api/admin/plan-limits/{plan}")
def delete_plan(plan: str, token_data: TokenData = Depends(require_admin("plan_limits"))):
    import server as core
    custom = core.custom_plans(refresh=True).get(plan)
    if not custom:
        raise HTTPException(status_code=400, detail="Seules les offres créées ici peuvent être supprimées.")
    if _count_by_plan().get(plan):
        raise HTTPException(status_code=409, detail="Des commerces sont sur cette offre : changez-les d'offre d'abord.")
    _db.plan_catalog.delete_one({"key": plan})
    core.custom_plans(refresh=True)
    core.log_audit("admin.plan_delete", actor=token_data.email, actor_type="user", target=plan, meta={"label": custom.get("label")})
    return {"ok": True}


@router.post("/api/admin/plan-limits/reset")
def reset(token_data: TokenData = Depends(require_admin("plan_limits"))):
    """Back to FidClic's default limits for Starter / Pro / Pro AI / Franchise
    (prices and names included). Offers created here are not touched."""
    import server as core
    for plan in ("silver", "gold", "vip", "franchise"):
        before = core.get_plan_features(plan)
        _db.plan_settings.update_one({"plan": plan}, {"$set": {"overrides": {}, "updated_at": _now()}, "$unset": {"meta": ""}})
        if any(before.get(k) != core.get_plan_features(plan).get(k) for k in ROW_KEYS):
            _apply_change(plan, before, token_data.email)
    core.log_audit("admin.plan_reset", actor=token_data.email, actor_type="user", target="plans", meta={})
    return {"ok": True}
