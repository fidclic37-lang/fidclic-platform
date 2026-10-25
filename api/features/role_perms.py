"""
Rôles et permissions par page (user, 2026-10-13, Paramètres › Équipe & accès):
  • a role is a NAME and a TEMPLATE of permissions — the four built-in roles
    (their template editable by the owner) and any role the owner creates;
  • each sidebar page has two switches, « Voir » and « Modifier » (Modifier
    implies Voir) — levels "none" | "view" | "edit";
  • an account gets its role's template when it is created, then its own
    permissions, set separately for each of its establishments;
  • only the Propriétaire defines roles; he is always full and locked.

Enforcement (auth.require_role → check()): every /api request of a team
account is matched to the page it belongs to (PATH_MAP); a read (GET) needs
« Voir » there, anything else « Modifier », in the establishment chosen in the
menu (X-FidClic-Store). A request that belongs to no page keeps the old rule
(the endpoint's role list). Accounts that never got permissions of their own,
in a role whose template the owner never changed, also keep the old rules —
nothing changes for them until the owner decides.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

_db = None

LEVELS = ("none", "view", "edit")
RANKV = {"none": 0, "view": 1, "edit": 2}
CUSTOM_ROLE = "membre"            # the system role of an account in a role the owner created
BUILTIN = ("administrateur", "manager", "staff")

# one row per sidebar page, in the sidebar's order
PAGES: List[Dict[str, Any]] = [
    {"key": "dashboard", "label": "Tableau de bord", "to": "/dashboard"},
    {"key": "scan", "label": "Enregistrer une visite", "to": "/dashboard/scan"},
    {"key": "analytics", "label": "Analyses", "to": "/dashboard/analytics"},
    {"key": "customers", "label": "Clients", "to": "/dashboard/customers"},
    {"key": "campaigns", "label": "Campagnes", "to": "/dashboard/campaigns"},
    {"key": "card", "label": "Carte de fidélité", "to": "/dashboard/card"},
    {"key": "automations", "label": "Automatisations", "to": "/dashboard/automations"},
    {"key": "segmentation", "label": "Segmentation", "to": "/dashboard/segmentation"},
    {"key": "referral", "label": "Parrainage", "to": "/dashboard/referral"},
    {"key": "geolocation", "label": "Géolocalisation", "to": "/dashboard/map"},
    {"key": "catalogue", "label": "Catalogue produits", "to": "/dashboard/catalogue"},
    {"key": "insights", "label": "Insights", "to": "/dashboard/insights"},
    {"key": "ai", "label": "FidClic IA", "to": "/dashboard/ai-assistant"},
    {"key": "history", "label": "Historique", "to": "/dashboard/history"},
    {"key": "settings", "label": "Paramètres", "to": "/dashboard/parametres"},
    {"key": "milestones", "label": "Objectifs et récompenses", "to": "/dashboard/parametres/objectifs"},
    {"key": "team", "label": "Équipe & accès", "to": "/dashboard/parametres/equipe"},
    # « Liens d'inscription par employé » (2026-10-16): `view` sees their own
    # link, their QR and the whole leaderboard; `edit` writes the records and
    # sends the e-mails. Its own page, so an employee can have it without
    # Paramètres.
    {"key": "employee_links", "label": "Liens d'inscription par employé",
     "to": "/dashboard/parametres/lien-inscription"},
    {"key": "billing", "label": "Abonnement & facturation", "to": "/dashboard/parametres/abonnement"},
    # Créer des rôles et changer leurs permissions (user, 2026-10-22) — only the
    # roles BELOW one's own (role tree below): an owner gives it on purpose
    {"key": "roles", "label": "Créer et modifier les rôles", "to": None, "edit_only": True},
    {"key": "email_change", "label": "Changer l'adresse e-mail du compte", "to": None, "edit_only": True},
    {"key": "delete", "label": "Supprimer le compte", "to": None, "edit_only": True},
]
PAGE_KEYS = [p["key"] for p in PAGES]
EDIT_ONLY = {p["key"] for p in PAGES if p.get("edit_only")}
LABEL = {p["key"]: p["label"] for p in PAGES}


def _all(level: str, **over) -> Dict[str, str]:
    return {**{k: level for k in PAGE_KEYS}, **over}


# The built-in roles' templates, as they worked before (what each one's sidebar showed)
DEFAULT_TEMPLATES: Dict[str, Dict[str, str]] = {
    "administrateur": _all("edit", billing="none", delete="none", email_change="none", roles="none"),
    "manager": _all("none", scan="edit", analytics="view", insights="view", ai="edit", customers="edit",
                    campaigns="edit", segmentation="edit", geolocation="view", history="view", team="edit"),
    "staff": _all("none", scan="edit"),
}
BUILTIN_LABELS = {"administrateur": "Administrateur", "manager": "Manager", "staff": "Employé"}

# Which page a request belongs to — the longest matching prefix wins.
_PREFIX: List[Tuple[str, str]] = [
    ("/api/owner/home", "dashboard"), ("/api/owner/monthly-report", "dashboard"),
    ("/api/owner/brain/detectors", "dashboard"),     # FidClic IA « a repéré » (Tableau de bord)
    ("/api/owner/scan", "scan"), ("/api/owner/rewards", "scan"), ("/api/owner/receipts", "scan"),
    ("/api/owner/card-readd", "scan"), ("/api/owner/offers", "scan"), ("/api/owner/defis/rewards", "scan"),
    ("/api/owner/happy-hour/active-now", "scan"),
    ("/api/owner/analytics", "analytics"), ("/api/owner/analyses", "analytics"),
    ("/api/owner/big-spenders", "analytics"),
    ("/api/owner/customers", "customers"), ("/api/owner/clients", "customers"),
    ("/api/owner/customer-status", "customers"), ("/api/owner/card-overrides", "customers"),
    ("/api/owner/reviews", "customers"), ("/api/owner/notifications/subscription-map", "customers"),
    ("/api/owner/notifications/subscription-stats", "customers"),
    ("/api/owner/notifications/re-enablement", "customers"),
    ("/api/owner/campaigns", "campaigns"), ("/api/campaigns", "campaigns"),
    ("/api/owner/campaign-reports", "campaigns"), ("/api/owner/autopilot", "campaigns"),
    ("/api/owner/defis", "campaigns"), ("/api/owner/happy-hour", "campaigns"),
    ("/api/owner/card-notifications", "campaigns"), ("/api/owner/push", "campaigns"),
    ("/api/owner/card", "card"), ("/api/owner/card-template", "card"), ("/api/owner/wallet", "card"),
    ("/api/owner/tier-definitions", "card"), ("/api/owner/earn-rules", "card"),
    ("/api/owner/automations", "automations"), ("/api/owner/auto-campaigns", "automations"),
    ("/api/owner/push-wallet", "automations"), ("/api/owner/auto-messages", "automations"),
    ("/api/owner/segmentation", "segmentation"), ("/api/owner/segments", "segmentation"),
    ("/api/owner/referrals", "referral"),
    ("/api/owner/geo", "geolocation"), ("/api/owner/settings/geo", "geolocation"),
    ("/api/owner/catalogue", "catalogue"), ("/api/owner/catalog", "catalogue"),
    ("/api/owner/insights", "insights"),
    ("/api/owner/ai", "ai"), ("/api/owner/ai-query", "ai"), ("/api/owner/copilot", "ai"),
    ("/api/owner/history", "history"),
    ("/api/owner/milestones", "milestones"),
    ("/api/owner/settings", "settings"), ("/api/owner/settings-versions", "settings"),
    ("/api/owner/etablissement", "settings"), ("/api/owner/join-link", "settings"),
    ("/api/owner/stores", "settings"), ("/api/owner/privacy", "settings"),
    ("/api/owner/integrations", "settings"), ("/api/owner/customer-rules", "settings"),
    ("/api/owner/registration-form", "settings"), ("/api/owner/notifications/overview", "settings"),
    ("/api/owner/notifications/rules", "settings"), ("/api/owner/tenant", "settings"),
    ("/api/owner/branches", "settings"),
    ("/api/owner/team-access", "team"), ("/api/owner/team", "team"),
    ("/api/owner/signup-agents", "employee_links"),
    ("/api/owner/billing", "billing"), ("/api/billing", "billing"), ("/api/owner/invoices", "billing"),
    ("/api/owner/facturation", "billing"), ("/api/owner/upgrade-plan", "billing"),
    ("/api/owner/request-upgrade", "billing"),
    ("/api/security/account", "delete"),
    ("/api/security/email", "email_change"),
]
_PREFIX.sort(key=lambda x: -len(x[0]))

# Reads every account of the shop needs whatever its pages (the menu, the plan,
# its own security and preferences, help).
_COMMON_READ = ("/api/owner/branches", "/api/owner/tenant", "/api/owner/plan-access", "/api/owner/trial-status",
                "/api/owner/usage", "/api/owner/limit-alerts", "/api/onboarding/status")
# « Cet appareil est la caisse » marks the account's OWN session, like the rest
# of /api/security — it only sits outside /sessions/ because that path ends in
# a session id and swallowed « caisse » (features/security_page). Being common
# exempts it from the PAGE permissions, not from its own role check: the
# endpoint still answers only the owner and an administrateur.
# « Masquer » on the trial banner is the account's own choice, like its
# preferences — not a page permission (the endpoint still answers only an
# owner or a manager).
_COMMON_ANY = ("/api/owner/support", "/api/me/", "/api/security/2fa", "/api/security/activity",
               "/api/security/overview", "/api/security/password", "/api/security/sessions",
               "/api/security/caisse", "/api/owner/trial-status/")

# A few reads that other pages need for their own work (never a page's list):
# the scan reads the card's rules and the product picker, a campaign reads the
# segments and the card for its preview… Exact prefixes, reads only.
SHARED_READS: List[Tuple[str, Tuple[str, ...]]] = [
    ("/api/owner/card-template", ("scan", "campaigns", "automations", "referral", "customers", "dashboard")),
    ("/api/owner/card/settings", ("scan", "campaigns", "automations", "referral", "customers")),
    ("/api/owner/catalog", ("scan", "campaigns")),
    ("/api/owner/catalogue/page", ("scan", "campaigns")),
    ("/api/owner/segments", ("campaigns", "customers", "automations")),
    ("/api/owner/segmentation", ("campaigns", "customers", "automations")),
    ("/api/owner/tier-definitions", ("customers", "campaigns", "automations", "scan")),
]


def init(db) -> None:
    global _db
    _db = db
    try:
        import auth
        auth.set_perm_check(check)
    except Exception as exc:          # noqa: BLE001
        print(f"role_perms: not wired ({exc})")


def page_of(path: str) -> Optional[str]:
    for pre, page in _PREFIX:
        if path == pre or path.startswith(pre + "/"):
            return page
    return None


def is_common(path: str, method: str) -> bool:
    if path.startswith(_COMMON_ANY):
        return True
    return method in ("GET", "HEAD", "OPTIONS") and any(path == p or path.startswith(p + "/") for p in _COMMON_READ)


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------
def clean_perms(raw: Any) -> Dict[str, str]:
    """{page: level} with every page, unknown keys refused; « delete » has no « Voir »."""
    from fastapi import HTTPException
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Permissions invalides.")
    out = {}
    for k in PAGE_KEYS:
        v = raw.get(k, "none")
        if isinstance(v, dict):                   # {"view": bool, "edit": bool}
            v = "edit" if v.get("edit") else ("view" if v.get("view") else "none")
        if v not in LEVELS:
            raise HTTPException(status_code=400, detail=f"Permission invalide : {LABEL[k]}.")
        if k in EDIT_ONLY and v == "view":
            v = "none"
        out[k] = v
    unknown = [k for k in raw if k not in PAGE_KEYS]
    if unknown:
        raise HTTPException(status_code=400, detail="Page inconnue dans les permissions.")
    return out


def templates(tid: str) -> Dict[str, Dict[str, Any]]:
    """Every role of the shop: the built-in ones (with the owner's changes) and
    the ones the owner created."""
    t = (_db.tenants.find_one({"id": tid}, {"_id": 0, "role_defs": 1}) or {}) if _db is not None else {}
    defs = t.get("role_defs") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for r in BUILTIN:
        mine = defs.get(r) or {}
        out[r] = {"key": r, "label": BUILTIN_LABELS[r], "builtin": True,
                  "customized": bool(mine.get("perms")),
                  "perms": {**DEFAULT_TEMPLATES[r], **(mine.get("perms") or {})}}
    for k, d in defs.items():
        if k in BUILTIN or not isinstance(d, dict) or d.get("deleted"):
            continue
        out[k] = {"key": k, "label": d.get("label") or "Rôle", "builtin": False, "customized": True,
                  "description": d.get("description") or "",
                  "perms": {**_all("none"), **(d.get("perms") or {})}}
    return out


# ---------------------------------------------------------------------------
# the role tree (user, 2026-10-22): « proprietaire sabka kar sakta,
# administrateur keval apne niche waale ka… and so on ». Each role has a
# parent — the role of whoever created it; the built-in ones: Propriétaire >
# Administrateur > Manager > Employé. An account manages the roles BELOW its
# own (any depth) and the accounts in them — never its own role, a sibling's
# or one above. The Propriétaire manages everything.
# ---------------------------------------------------------------------------
OWNER_KEY = "proprietaire"
BUILTIN_PARENT = {"administrateur": OWNER_KEY, "manager": "administrateur", "staff": "manager"}


def my_key(user: Dict[str, Any]) -> str:
    if (user or {}).get("role") in ("business_owner", "super_admin"):
        return OWNER_KEY
    return role_key(user or {}) or ""


def _defs(tid: str) -> Dict[str, Any]:
    t = (_db.tenants.find_one({"id": tid}, {"_id": 0, "role_defs": 1}) or {}) if _db is not None else {}
    return t.get("role_defs") or {}


def parent_of(tid: str, key: str, defs: Optional[Dict[str, Any]] = None) -> str:
    if key in BUILTIN_PARENT:
        return BUILTIN_PARENT[key]
    d = (defs if defs is not None else _defs(tid)).get(key) or {}
    if d.get("parent"):
        return d["parent"]
    # a role made before the tree: its creator's role, the owner's by default
    creator = _db.users.find_one({"email": d.get("created_by")}, {"_id": 0, "role": 1, "custom_role": 1})         if (_db is not None and d.get("created_by")) else None
    return my_key(creator) if creator else OWNER_KEY


def below(tid: str, key: str) -> List[str]:
    """Every role under `key`, at any depth (the owner: every role)."""
    keys = [k for k in templates(tid)]
    if key == OWNER_KEY:
        return keys
    defs = _defs(tid)
    out = []
    for k in keys:
        p, seen = parent_of(tid, k, defs), {k}
        while p and p not in seen and p != OWNER_KEY:
            if p == key:
                out.append(k)
                break
            seen.add(p)
            p = parent_of(tid, p, defs)
    return out


def can_define_roles(token_or_user) -> bool:
    role = getattr(token_or_user, "role", None) or (token_or_user or {}).get("role")
    if role in ("business_owner", "super_admin"):
        return True
    if hasattr(token_or_user, "email"):
        return may(token_or_user, "roles", "edit")
    perms = effective(token_or_user)
    return perms is not None and all(p.get("roles") == "edit" for p in perms.values()) and bool(perms)


def manageable_roles(user: Dict[str, Any]) -> List[str]:
    """The role DEFINITIONS this account may change: below its own, if it has
    « Créer et modifier les rôles »."""
    if not can_define_roles(user):
        return []
    return below(user.get("tenant_id"), my_key(user))


def role_key(user: Dict[str, Any]) -> Optional[str]:
    return user.get("custom_role") if user.get("role") == CUSTOM_ROLE else user.get("role")


def new_role_key() -> str:
    return "r_" + uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# what an account may do
# ---------------------------------------------------------------------------
def user_stores(user: Dict[str, Any], all_ids: List[str]) -> List[str]:
    if "branch_ids" not in user:
        return list(all_ids)
    return [b for b in user.get("branch_ids") or [] if b in all_ids]


def per_store(user: Dict[str, Any]) -> Optional[Dict[str, Dict[str, str]]]:
    """{store: {page: level}} for this account, or None: the old rules (an
    account without permissions of its own, in a built-in role whose template
    the owner never changed)."""
    if not user or user.get("role") in ("business_owner", "super_admin"):
        return None
    from features import team_access as TA
    tid = user.get("tenant_id")
    all_ids = [s["id"] for s in TA.stores(tid)]
    stores = user_stores(user, all_ids)
    own = user.get("perms") if isinstance(user.get("perms"), dict) else None
    tpl = templates(tid).get(role_key(user) or "")
    if own is None and tpl is None and user.get("role") == CUSTOM_ROLE:
        return {s: _all("none") for s in stores}           # a role deleted since: nothing
    # Every team account follows its permissions — its own, else its role's
    # template (user, 2026-10-22: « based on permissions… sections accessible
    # hona chahiye ») — even a built-in role the owner never changed.
    base = (tpl or {}).get("perms") or _all("none")
    out = {}
    for s in stores:
        mine = (own or {}).get(s)
        out[s] = {**_all("none"), **(mine if isinstance(mine, dict) else base)}
    return out


def level_in(perms: Dict[str, Dict[str, str]], page: str, store: Optional[str]) -> str:
    """The level in the establishment chosen in the menu; without one, the
    lowest of its establishments (never more than everywhere)."""
    if not perms:
        return "none"
    if store and store in perms:
        return perms[store].get(page, "none")
    vals = [p.get(page, "none") for p in perms.values()]
    return min(vals, key=lambda v: RANKV[v]) if vals else "none"


def can_read(perms, page: str, store: Optional[str], path: str = "") -> bool:
    if RANKV[level_in(perms, page, store)] >= 1:
        return True
    for pre, pages in SHARED_READS:
        if path == pre or path.startswith(pre + "/"):
            return any(RANKV[level_in(perms, other, store)] >= 1 for other in pages)
    return False


def _store_of(request) -> Optional[str]:
    v = (request.headers.get("x-fidclic-store") or "").strip() if request is not None else ""
    if not v and request is not None:
        v = (request.query_params.get("store") or "").strip()
    return v or None


def strict(user: Dict[str, Any]) -> bool:
    """Permissions alone decide (refusals included) for an account with its own
    switches, or in a role the owner edited or created. An account in a
    built-in role the owner never changed is GIVEN what its template allows
    and otherwise keeps its role's old rules — a page it always used never
    closes on it by surprise."""
    if isinstance(user.get("perms"), dict) or user.get("role") == CUSTOM_ROLE:
        return True
    tpl = templates(user.get("tenant_id")).get(role_key(user) or "") or {}
    return bool(tpl.get("customized"))


def may_everywhere(token, page: str, level: str = "edit") -> bool:
    """« Modifier » on that page in EVERY establishment of the shop — what a
    shop-wide change (e.g. a push-wallet scenario for all stores) asks."""
    if getattr(token, "role", None) in ("business_owner", "super_admin"):
        return True
    if _db is None:
        return False
    user = _db.users.find_one({"email": token.email}, {"_id": 0, "hashed_password": 0}) or {}
    perms = effective(user)
    if not perms:
        return False
    from features import team_access as TA
    all_ids = [s["id"] for s in TA.stores(user.get("tenant_id"))]
    return all(RANKV[(perms.get(sid) or {}).get(page, "none")] >= RANKV.get(level, 2) for sid in all_ids)


def may(token, page: str, level: str = "edit", request=None) -> bool:
    """May this account « Voir » (level="view") or « Modifier » (« edit ») this
    page, in the establishment chosen in the menu? The owner always may. The
    one question every « only the owner » test inside a page now asks."""
    if token is None:
        return False
    if getattr(token, "role", None) in ("business_owner", "super_admin"):
        return True
    if _db is None:
        return False
    user = _db.users.find_one({"email": token.email}, {"_id": 0, "hashed_password": 0}) or {}
    if user.get("tenant_id") != getattr(token, "tenant_id", None):
        return False
    perms = effective(user)
    if perms is None:
        return True
    return RANKV[level_in(perms, page, _store_of(request))] >= RANKV.get(level, 2)


def check(token, request, roles) -> Optional[bool]:
    """auth.require_role asks: True = allowed, False = refused (403 with the
    page's name), None = no say (the endpoint's role list decides, as before)."""
    if token is None or token.role in ("business_owner", "super_admin") or request is None or _db is None:
        return None
    path, method = request.url.path, request.method.upper()
    user = _db.users.find_one({"email": token.email}, {"_id": 0, "hashed_password": 0}) or {}
    if user.get("tenant_id") != token.tenant_id:
        return None
    perms = per_store(user)
    if perms is None:
        return None
    if is_common(path, method):              # the menu, the plan, one's own security
        # no page's right: an account on its role's template keeps the
        # endpoint's own role list (a staff account opened no support ticket)
        return True if strict(user) else None
    page = page_of(path)
    if page is None:
        return False if user.get("role") == CUSTOM_ROLE else None
    store = _store_of(request)
    if method in ("GET", "HEAD", "OPTIONS"):
        ok = can_read(perms, page, store, path)
    else:
        ok = level_in(perms, page, store) == "edit"
    if not ok:
        if not strict(user):
            return None                      # never granted here: the role's old rule decides
        request.state.perm_denied = page
    return ok


def denied_message(page: Optional[str], method: str) -> str:
    what = "voir" if method in ("GET", "HEAD", "OPTIONS") else "modifier"
    return f"Accès non autorisé : vous ne pouvez pas {what} « {LABEL.get(page or '', 'cette page')} »."


def nav_for(user: Dict[str, Any]) -> Optional[Dict[str, Dict[str, str]]]:
    """For the sidebar: the account's levels per establishment (None: old menu)."""
    try:
        return per_store(user)
    except Exception:
        return None


def effective(user: Dict[str, Any]) -> Optional[Dict[str, Dict[str, str]]]:
    """Like per_store, but an account on the old rules gets its role's
    template (what it can do today). None: the owner (everything)."""
    if not user or user.get("role") in ("business_owner", "super_admin"):
        return None
    p = per_store(user)
    if p is not None:
        return p
    from features import team_access as TA
    all_ids = [s["id"] for s in TA.stores(user.get("tenant_id"))]
    base = (templates(user.get("tenant_id")).get(role_key(user) or "") or {}).get("perms") or _all("none")
    return {s: dict(base) for s in user_stores(user, all_ids)}


def max_of(a: str, b: str) -> str:
    return a if RANKV[a] >= RANKV[b] else b


def within(granted: Dict[str, Dict[str, str]], mine: Optional[Dict[str, Dict[str, str]]]) -> Optional[str]:
    """None if every level granted is at most the creator's own in that
    establishment (an owner: anything), else the page that goes beyond."""
    if mine is None:
        return None
    for s, pages in granted.items():
        for k, v in pages.items():
            if RANKV[v] > RANKV[(mine.get(s) or {}).get(k, "none")]:
                return k
    return None


SLUG = re.compile(r"[^a-z0-9]+")
