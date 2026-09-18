from datetime import datetime, timezone, timedelta
import uuid
import random
import re
import json
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, Request, Response, status, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import (
    UserInDB, UserCreate, Tenant, Customer, Visit, CardTemplate, Campaign, PaymentTransaction, AIQueryRequest,
    PLAN_FEATURES, PLAN_PRICES, PLAN_TRIAL_DAYS, TRIAL_REMINDER_DAYS_BEFORE, TierDesign,
    CardPromotion, CardDetails, CardTypedNotification,
    Review,
)

# Canonical plan list. Anything else in the DB (legacy "basic", "chain")
# gets remapped to "silver" via _canonical_plan() below.
CANONICAL_PLANS = ("silver", "gold", "vip")
_LEGACY_PLAN_MAP = {"basic": "silver", "chain": "vip"}

def _canonical_plan(plan: str) -> str:
    """Map any legacy plan name to one of the 3 canonical plans."""
    if not plan:
        return "silver"
    return _LEGACY_PLAN_MAP.get(plan, plan if plan in CANONICAL_PLANS else "silver")
from auth import (
    hash_password, verify_password, create_access_token, get_current_user_data,
    require_role, check_plan_feature, TokenData, ACCESS_TOKEN_EXPIRE_MINUTES
)

import os
import pymongo
import hashlib
import base64
from io import BytesIO

# Setup FastAPI App
app = FastAPI(
    title="FidéliTour API",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Initialization — synchronous pymongo for Vercel serverless reliability
MONGODB_URI = os.environ.get("MONGODB_URI", "")

if MONGODB_URI:
    client = pymongo.MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
    db = client.fidelitour_db
else:
    client = pymongo.MongoClient(tz_aware=True)
    db = client.fidelitour_db

# ─────────────────────────────────────────────────────────────────────
# RGPD / GDPR — Audit trail (Sprint 1)
# Every privacy-sensitive action gets one immutable row in db.audit_logs:
# logins, plan changes, data exports, erasure requests, card deletions,
# SMS re-enablement blasts. This is the "accountability" pillar of GDPR
# (Art. 5.2) — when CNIL asks "who accessed this customer's data and
# when", this collection IS the answer.
#
# NEVER raises: audit logging must not break the endpoint it observes.
# ─────────────────────────────────────────────────────────────────────
CURRENT_PRIVACY_POLICY_VERSION = "2026-07-21"

def _client_ip(request) -> str:
    """Best-effort client IP behind Vercel's proxy chain."""
    try:
        if request is None:
            return ""
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else ""
    except Exception:
        return ""

def log_audit(action: str, actor: str = "", actor_type: str = "system",
              tenant_id: str = None, target: str = None,
              request=None, meta: dict = None):
    """Insert one audit row. Silently swallows every failure.

    action     — machine key, e.g. 'auth.login', 'gdpr.export',
                 'gdpr.forget_me', 'admin.plan_update', 'card.delete',
                 'sms.re_enablement'
    actor      — email (owner/admin) or barcode_id (customer)
    actor_type — 'user' | 'customer' | 'system'
    target     — the object acted on (customer id, plan name, …)
    """
    try:
        db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "ts": datetime.now(timezone.utc),
            "action": action,
            "actor": actor or "",
            "actor_type": actor_type,
            "tenant_id": tenant_id,
            "target": target,
            "ip": _client_ip(request),
            "meta": meta or {},
        })
    except Exception:
        pass

# Email channel REMOVED — kept as empty constants so any leftover reference
# compiles. send_email_to_customer() is now a no-op shim. See line ~237.
SENDGRID_API_KEY = ""
SENDGRID_FROM_EMAIL = "noreply@fidelitour.com"

# LLM provider chain. Pluggable — first key found in chain order wins.
# Order matters: PRIMARY tried first, fallbacks only fire if the primary
# is missing a key, returns nothing, or errors out.
#
# Provider order (top = tried first):
#   NVIDIA_API_KEY     → NVIDIA NIM (build.nvidia.com) — 1000 free credits/mo
#                        OpenAI-compatible. Catalog: Llama 3.1/3.3, Mixtral,
#                        Mistral, DeepSeek-R1, Nemotron, Qwen, vision models.
#   GROQ_API_KEY       → Llama 3 / Llama 3.1 / Mixtral via Groq (extremely
#                        fast, generous free tier)
#   OPENROUTER_API_KEY → many free models (Llama 3, Hermes, etc.) under one key
#   GEMINI_API_KEY     → Google Gemini Flash (1500 req/day free, no card)
# If none are set, the endpoint serves a deterministic heuristic so testing works.
# Anthropic sits FIRST in the chain whenever its key is present. The free
# tiers below are fine for smoke-testing that a feature is wired up, but they
# cannot tell you whether the *output* is good enough to ship — a Llama-3.2-3b
# fallback writing a merchant's campaign copy is not the product. When you are
# judging quality, you want the model you would actually ship on.
#
#   ANTHROPIC_API_KEY     from console.anthropic.com
#   ANTHROPIC_MODEL       default claude-sonnet-5
#   ANTHROPIC_VISION_MODEL  defaults to ANTHROPIC_MODEL (all Claude models see)
#
# Cost, Aug 2026: sonnet-5 $2/$10 per Mtok (intro pricing to 31 Aug 2026,
# then $3/$15), haiku-4-5 $1/$5, opus-5 $5/$25. Prompts here are a few hundred
# tokens, so $5 of credit is thousands of calls on Sonnet. Set
# ANTHROPIC_MODEL=claude-haiku-4-5 for bulk/cheap paths.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
ANTHROPIC_VISION_MODEL = os.environ.get("ANTHROPIC_VISION_MODEL", "") or ANTHROPIC_MODEL
ANTHROPIC_VERSION = "2023-06-01"

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
# Sensible default: Llama 3.3 70B Instruct via NVIDIA's hosted NIM. Owner can
# swap to nemotron, mixtral, deepseek, etc. by setting NVIDIA_MODEL.
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.2-3b-instruct:free")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

# ============================================================
# France-wide postal code → (lat, lng, department_name) mapping
# Keyed by 2-digit department prefix. Covers all 96 metropolitan departments.
# Individual well-known city postal codes override at full-5-digit granularity.
# ============================================================
FRENCH_DEPARTMENTS = {
    "01": ("Ain", 46.20, 5.22), "02": ("Aisne", 49.56, 3.62), "03": ("Allier", 46.39, 3.19),
    "04": ("Alpes-de-Haute-Provence", 44.10, 6.24), "05": ("Hautes-Alpes", 44.66, 6.42),
    "06": ("Alpes-Maritimes", 43.93, 7.21), "07": ("Ardèche", 44.75, 4.42),
    "08": ("Ardennes", 49.61, 4.62), "09": ("Ariège", 42.93, 1.52), "10": ("Aube", 48.32, 4.17),
    "11": ("Aude", 43.11, 2.45), "12": ("Aveyron", 44.28, 2.57),
    "13": ("Bouches-du-Rhône", 43.50, 5.10), "14": ("Calvados", 49.08, -0.28),
    "15": ("Cantal", 45.06, 2.65), "16": ("Charente", 45.73, 0.24),
    "17": ("Charente-Maritime", 45.82, -0.69), "18": ("Cher", 47.06, 2.46),
    "19": ("Corrèze", 45.36, 1.87), "21": ("Côte-d'Or", 47.50, 4.85),
    "22": ("Côtes-d'Armor", 48.47, -2.98), "23": ("Creuse", 46.08, 2.03),
    "24": ("Dordogne", 45.14, 0.72), "25": ("Doubs", 47.22, 6.48),
    "26": ("Drôme", 44.74, 5.26), "27": ("Eure", 49.17, 1.16),
    "28": ("Eure-et-Loir", 48.46, 1.35), "29": ("Finistère", 48.22, -4.10),
    "2A": ("Corse-du-Sud", 41.93, 8.94), "2B": ("Haute-Corse", 42.35, 9.29),
    "30": ("Gard", 44.04, 4.22), "31": ("Haute-Garonne", 43.45, 1.34),
    "32": ("Gers", 43.64, 0.58), "33": ("Gironde", 44.85, -0.57),
    "34": ("Hérault", 43.61, 3.55), "35": ("Ille-et-Vilaine", 48.17, -1.52),
    "36": ("Indre", 46.75, 1.52), "37": ("Indre-et-Loire", 47.29, 0.68),
    "38": ("Isère", 45.25, 5.75), "39": ("Jura", 46.75, 5.69),
    "40": ("Landes", 43.93, -0.73), "41": ("Loir-et-Cher", 47.58, 1.37),
    "42": ("Loire", 45.57, 4.27), "43": ("Haute-Loire", 45.10, 3.83),
    "44": ("Loire-Atlantique", 47.35, -1.73), "45": ("Loiret", 47.83, 2.38),
    "46": ("Lot", 44.62, 1.60), "47": ("Lot-et-Garonne", 44.35, 0.62),
    "48": ("Lozère", 44.56, 3.49), "49": ("Maine-et-Loire", 47.37, -0.49),
    "50": ("Manche", 49.11, -1.30), "51": ("Marne", 48.97, 4.37),
    "52": ("Haute-Marne", 48.11, 5.14), "53": ("Mayenne", 48.14, -0.72),
    "54": ("Meurthe-et-Moselle", 48.70, 6.20), "55": ("Meuse", 48.97, 5.37),
    "56": ("Morbihan", 47.87, -2.79), "57": ("Moselle", 49.02, 6.66),
    "58": ("Nièvre", 47.12, 3.59), "59": ("Nord", 50.47, 3.15),
    "60": ("Oise", 49.42, 2.42), "61": ("Orne", 48.63, 0.12),
    "62": ("Pas-de-Calais", 50.52, 2.50), "63": ("Puy-de-Dôme", 45.77, 3.08),
    "64": ("Pyrénées-Atlantiques", 43.30, -0.77), "65": ("Hautes-Pyrénées", 43.07, 0.15),
    "66": ("Pyrénées-Orientales", 42.60, 2.66), "67": ("Bas-Rhin", 48.58, 7.73),
    "68": ("Haut-Rhin", 47.91, 7.30), "69": ("Rhône", 45.75, 4.85),
    "70": ("Haute-Saône", 47.62, 6.15), "71": ("Saône-et-Loire", 46.65, 4.52),
    "72": ("Sarthe", 48.00, 0.20), "73": ("Savoie", 45.57, 6.52),
    "74": ("Haute-Savoie", 46.00, 6.43), "75": ("Paris", 48.8566, 2.3522),
    "76": ("Seine-Maritime", 49.67, 1.00), "77": ("Seine-et-Marne", 48.62, 2.95),
    "78": ("Yvelines", 48.80, 1.90), "79": ("Deux-Sèvres", 46.55, -0.23),
    "80": ("Somme", 49.92, 2.30), "81": ("Tarn", 43.79, 2.15),
    "82": ("Tarn-et-Garonne", 44.08, 1.35), "83": ("Var", 43.47, 6.27),
    "84": ("Vaucluse", 44.00, 5.15), "85": ("Vendée", 46.67, -1.35),
    "86": ("Vienne", 46.57, 0.47), "87": ("Haute-Vienne", 45.84, 1.26),
    "88": ("Vosges", 48.20, 6.46), "89": ("Yonne", 47.85, 3.55),
    "90": ("Territoire de Belfort", 47.62, 6.87), "91": ("Essonne", 48.53, 2.25),
    "92": ("Hauts-de-Seine", 48.85, 2.23), "93": ("Seine-Saint-Denis", 48.92, 2.47),
    "94": ("Val-de-Marne", 48.77, 2.47), "95": ("Val-d'Oise", 49.08, 2.17),
    "97": ("Outre-mer", 16.25, -61.55), "98": ("Outre-mer", -21.11, 55.53),
}

# Fine-grained overrides for major city postal codes (lat, lng)
POSTAL_CODE_OVERRIDES = {
    "37000": (47.3941, 0.6848), "37100": (47.4210, 0.6840),
    "37200": (47.3741, 0.6900), "37300": (47.3800, 0.7000),
    "75001": (48.8606, 2.3376), "75008": (48.8722, 2.3108),
    "69001": (45.7678, 4.8336), "13001": (43.2976, 5.3810),
    "33000": (44.8378, -0.5792), "59000": (50.6292, 3.0573),
    "44000": (47.2184, -1.5536), "31000": (43.6047, 1.4442),
    "06000": (43.7102, 7.2620), "34000": (43.6108, 3.8767),
    "67000": (48.5734, 7.7521),
}

# ---------------------------------------------------------------------------
# Plan limits — admin-overridable.
#
# `PLAN_FEATURES` (from models.py) ships baseline limits for each plan
# (max_customers, campaigns_per_month, ai_queries_per_day, csv_export, etc.).
# Super-admins can override any numeric or boolean field per plan via the
# `plan_settings` collection. This lets us, for instance, lift the basic plan
# from 500 → 750 max customers without redeploying, or fully change limits
# across all plans from the admin UI.
#
# Schema for a `plan_settings` document:
#   {
#     "plan": "basic" | "gold" | "vip" | "chain",
#     "overrides": { "max_customers": 750, "ai_queries_per_day": 5, ... },
#     "updated_at": <utc>,
#     "updated_by": <admin email>,
#   }
#
# `get_plan_features(plan)` is the ONE function every endpoint should call —
# never read `PLAN_FEATURES` directly anymore. It merges the hardcoded
# baseline with any DB overrides (overrides win for fields they specify).
# ---------------------------------------------------------------------------
_PLAN_LIMIT_FIELDS = (
    "max_customers",
    "campaigns_per_month",
    "ai_queries_per_day",
    "csv_export",
    "geo_proximity",
    "multi_branch",
    # Trial knobs — admin can change the trial length per plan from the
    # /admin/plans editor, same DB-backed override mechanism as the
    # quota/feature fields above.
    "trial_duration_days",
    "trial_reminder_days_before",
    # Monthly price in euros — admins can re-price plans without a deploy.
    "price",
)


def get_plan_features(plan: str) -> Dict[str, Any]:
    """Return effective plan limits = baseline + admin overrides.

    Always returns a dict (never None) so callers can `.get(...)` safely.
    Unknown / legacy plan names ("basic", "chain", typos) are remapped to
    the canonical 3-tier catalogue (silver/gold/vip) so we never block
    joining with a KeyError when the tenant doc has a stale plan name.
    """
    plan = _canonical_plan(plan)
    baseline = dict(PLAN_FEATURES.get(plan) or PLAN_FEATURES["silver"])
    # Fold trial + price baselines in too, so the admin editor and any
    # consumer that calls get_plan_features() sees a uniform shape.
    baseline["trial_duration_days"] = PLAN_TRIAL_DAYS.get(plan, 21)
    baseline["trial_reminder_days_before"] = TRIAL_REMINDER_DAYS_BEFORE
    baseline["price"] = PLAN_PRICES.get(plan, 0)
    try:
        doc = db.plan_settings.find_one({"plan": plan}) if db is not None else None
    except Exception:
        doc = None
    if doc and isinstance(doc.get("overrides"), dict):
        for k, v in doc["overrides"].items():
            if k in _PLAN_LIMIT_FIELDS and v is not None:
                baseline[k] = v
    return baseline


def get_postal_coords(postal_code: str):
    """Return (lat, lng) for a French postal code. Falls back through overrides → department → Paris."""
    if not postal_code:
        return (48.8566, 2.3522)
    postal_code = str(postal_code).strip()
    # 1. Exact override (major cities)
    if postal_code in POSTAL_CODE_OVERRIDES:
        return POSTAL_CODE_OVERRIDES[postal_code]
    # 2. Department-level (first 2 chars). Corsica handled specially (20xxx → 2A/2B).
    if len(postal_code) >= 2:
        prefix = postal_code[:2]
        if prefix == "20":
            # Corsica: 200xx-201xx are 2A (Corse-du-Sud), 202xx-206xx are 2B (Haute-Corse)
            try:
                n = int(postal_code[:3])
                prefix = "2A" if n < 202 else "2B"
            except ValueError:
                prefix = "2A"
        elif postal_code[:2] in ("97", "98"):
            prefix = postal_code[:2]
        if prefix in FRENCH_DEPARTMENTS:
            _, lat, lng = FRENCH_DEPARTMENTS[prefix]
            return (lat, lng)
    # 3. Default to Paris
    return (48.8566, 2.3522)

def get_department_info(postal_code: str):
    """Return (department_code, department_name) for a French postal code."""
    if not postal_code:
        return ("75", "Paris")
    postal_code = str(postal_code).strip()
    if len(postal_code) < 2:
        return ("75", "Paris")
    prefix = postal_code[:2]
    if prefix == "20":
        try:
            n = int(postal_code[:3])
            prefix = "2A" if n < 202 else "2B"
        except ValueError:
            prefix = "2A"
    if prefix in FRENCH_DEPARTMENTS:
        name, _, _ = FRENCH_DEPARTMENTS[prefix]
        return (prefix, name)
    return ("75", "Paris")

# Backward-compat alias (used by legacy code paths)
POSTAL_CODE_CENTROIDS = POSTAL_CODE_OVERRIDES

# 1x1 transparent PNG (base64)
PIXEL_PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
PIXEL_PNG_BYTES = base64.b64decode(PIXEL_PNG_BASE64)

# ============================================================
# Template variable renderer — substitutes {name}, {first_name},
# {tier}, {points}, {points_to_next_reward}, {business_name},
# {visits}, {amount_paid}. Used by every email / push send path
# so personalised offers ("Bonjour {first_name}, il te reste
# {points_to_next_reward} points pour une récompense !") work.
# ============================================================
def _compute_points_to_next_reward(customer: dict, tenant_id: str) -> int:
    """How many more visits (≈ points) until the next reward for this customer.

    Counts only the visits SINCE the last redemption — `visits` itself is the
    lifetime counter and never gets reset. So a customer at 47 lifetime
    visits who redeemed at 40 has `visits - visits_at_last_redemption = 7`
    stamps on their current card, with `threshold - 7 = 3` to go.
    """
    try:
        tpl = db.card_templates.find_one({"tenant_id": tenant_id}) or {}
        visits_per_stamp = max(int(tpl.get("visits_per_stamp", 1) or 1), 1)
        reward_threshold_stamps = max(int(tpl.get("reward_threshold_stamps", 10) or 10), 1)
        visits_needed = visits_per_stamp * reward_threshold_stamps
        lifetime_visits = int(customer.get("visits", 0) or 0)
        last_redemption_visits = int(customer.get("visits_at_last_redemption", 0) or 0)
        stamps_in_cycle = max(0, lifetime_visits - last_redemption_visits)
        remaining_visits = max(0, visits_needed - stamps_in_cycle)
        return remaining_visits
    except Exception:
        return 0


def render_template(content: str, customer: dict, tenant: dict = None) -> str:
    """Replace curly-brace placeholders in a campaign body with per-customer values.
    Missing values are silently replaced with a neutral fallback so the message never
    renders a literal `{name}` to the recipient.
    """
    if not content:
        return ""
    try:
        name = customer.get("name") or "cher client"
        first_name = name.split(" ")[0] if name else "cher client"
        tier = (customer.get("tier") or "bronze").title()
        points = int(customer.get("points", customer.get("visits", 0) * 10) or 0)
        visits = int(customer.get("visits", 0) or 0)
        amount_paid = round(float(customer.get("total_amount_paid", 0) or 0), 2)
        business_name = (tenant or {}).get("name") or "notre boutique"
        ptnr = _compute_points_to_next_reward(customer, customer.get("tenant_id") or (tenant or {}).get("id"))

        replacements = {
            "{name}": name,
            "{first_name}": first_name,
            "{tier}": tier,
            "{points}": str(points),
            "{points_remaining}": str(ptnr),
            "{points_to_next_reward}": str(ptnr),
            "{visits}": str(visits),
            "{amount_paid}": f"{amount_paid:.2f}€",
            "{business_name}": business_name,
            "{sector}": (tenant or {}).get("sector", ""),
        }
        rendered = content
        for token, value in replacements.items():
            rendered = rendered.replace(token, str(value))
        return rendered
    except Exception:
        return content


def send_email_to_customer(to_email: str, from_name: str, subject: str, body_html: str) -> bool:
    """
    EMAIL CHANNEL DISABLED — FidéliTour now uses web push + SMS only.

    Kept as a no-op shim so existing call-sites compile. Always returns False so
    the caller falls through to push/SMS instead. Do NOT re-enable: the client
    asked to remove the email feature end-to-end. If you re-introduce email,
    add a feature flag and a deliberate consent flow.
    """
    return False


# ════════════════════════════════════════════════════════════════════
# dispatch_to_customer — THE single delivery path for anything we send
# to a customer.
#
# History: this platform used to send by email. The email channel was
# removed (send_email_to_customer above is a no-op shim), but the call
# sites were never rewired — so campaigns were marked "sent", recipients
# were recorded, attribution was armed, and NOTHING actually left the
# server. Three separate endpoints had that bug. They now all call this.
#
# Channel order, matching auto_campaigns._dispatch_message():
#   1. Web Push  — free, instant, customer opted in from their wallet card
#   2. SMS       — fallback for customers with no push subscription
#
# Never raises: a delivery failure must not break the endpoint that
# triggered it. Every attempt lands in `delivery_log` so a merchant asking
# "did my message go out?" has an auditable answer.
# ════════════════════════════════════════════════════════════════════
def dispatch_to_customer(tenant_id: str, customer: dict, title: str, body: str,
                         kind: str = "campaign") -> dict:
    """Deliver one message to one customer. Returns {sent, channel}."""
    now = datetime.now(timezone.utc)
    result = {"sent": False, "channel": None}

    # 1. Web Push
    try:
        from features.push_subscriptions import fan_out_to_customer   # noqa: WPS433
        push_result = fan_out_to_customer(tenant_id, customer.get("id"), title, body)
        if push_result.get("sent", 0) > 0:
            result = {"sent": True, "channel": "web_push"}
        try:
            db.delivery_log.insert_one({
                "tenant_id": tenant_id, "customer_id": customer.get("id"),
                "channel": "web_push", "kind": kind,
                "result": push_result, "timestamp": now,
            })
        except Exception:
            pass
    except Exception as exc:
        print(f"dispatch_to_customer: push failed ({exc})")

    # 2. SMS fallback — only when push reached no device.
    if not result["sent"]:
        try:
            from services.sms import send_sms, is_configured           # noqa: WPS433
            phone = customer.get("phone")
            if phone and is_configured():
                sms_result = send_sms(phone, f"{title}\n{body}" if title else body)
                if sms_result.get("sent"):
                    result = {"sent": True, "channel": "sms"}
                try:
                    db.delivery_log.insert_one({
                        "tenant_id": tenant_id, "customer_id": customer.get("id"),
                        "channel": "sms_fallback", "kind": kind, "phone": phone,
                        "result": sms_result, "timestamp": now,
                    })
                except Exception:
                    pass
        except Exception as exc:
            print(f"dispatch_to_customer: sms failed ({exc})")

    return result


_URL_RE = re.compile(
    r"(?P<url>https?://[^\s<>\"']+)",
    flags=re.IGNORECASE,
)
_INSTAGRAM_HANDLE_RE = re.compile(r"(?<![a-zA-Z0-9_])@([a-zA-Z0-9_.]+)")

def _autolink(text: str, *, color: str = "#B85C38") -> str:
    """Turn raw URLs in plain text into <a> tags so the campaign body can
    include Instagram links, menu URLs, RSVP forms, etc., without the owner
    having to write HTML. Also recognises @handle Instagram mentions when
    they're not part of an email address.

    Returns HTML with <br> for newlines so the result drops straight into
    the email template.
    """
    if not text:
        return ""
    html = (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))
    # URLs
    def _url_repl(m):
        url = m.group("url").rstrip(".,;:!?)")  # trim trailing sentence punctuation
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer" style="color:{color};text-decoration:underline;">{url}</a>'
    html = _URL_RE.sub(_url_repl, html)
    # @instagram handles — only convert when the @ isn't part of an email
    # (no preceding word-char) and isn't immediately followed by a domain.
    def _handle_repl(m):
        handle = m.group(1)
        # Skip pseudo-handles that look like email locals (e.g. @gmail.com)
        if handle.lower() in {"gmail", "hotmail", "outlook", "yahoo", "icloud", "live", "free", "orange"}:
            return m.group(0)
        return f'<a href="https://instagram.com/{handle}" target="_blank" rel="noopener noreferrer" style="color:{color};text-decoration:underline;">@{handle}</a>'
    html = _INSTAGRAM_HANDLE_RE.sub(_handle_repl, html)
    return html.replace("\n", "<br>")


def _campaign_html(tenant_name: str, subject: str, rendered_body: str, customer: dict, image_url: Optional[str] = None) -> str:
    """Consistent branded email wrapper used by every campaign dispatch path.

    Optional `image_url` renders a hero image at the top of the email — either
    a full URL (https://...) or a data URL from a local upload.
    """
    tier_title = (customer.get("tier") or "bronze").title()
    points = int(customer.get("points", customer.get("visits", 0) * 10) or 0)
    visits = int(customer.get("visits", 0) or 0)
    # Auto-linkify any https://… URLs and @instagram handles. Replaces the
    # earlier simple newline→<br> conversion.
    body_html = _autolink(rendered_body or "")

    image_block = ""
    if image_url:
        image_block = f"""
    <div style="margin:-30px -30px 25px -30px;border-top-left-radius:12px;border-top-right-radius:12px;overflow:hidden;">
      <img src="{image_url}" alt="" style="display:block;width:100%;max-height:320px;object-fit:cover;" />
    </div>"""

    return f"""
<div style="font-family:'Manrope',Arial,sans-serif;max-width:600px;margin:0 auto;padding:40px 20px;background:#FDFBF7;">
  <div style="text-align:center;margin-bottom:30px;">
    <h1 style="font-family:'Georgia',serif;color:#1C1917;font-size:28px;margin-bottom:5px;">{tenant_name}</h1>
    <div style="width:50px;height:3px;background:#B85C38;margin:0 auto;"></div>
  </div>
  <div style="background:white;border-radius:12px;padding:30px;border:1px solid #E7E5E4;overflow:hidden;">{image_block}
    <h2 style="color:#B85C38;font-size:22px;margin-bottom:15px;">{subject}</h2>
    <p style="color:#57534E;line-height:1.6;font-size:16px;">{body_html}</p>
    <div style="margin-top:25px;padding:15px;background:#F3EFE7;border-radius:8px;text-align:center;">
      <p style="color:#B85C38;font-weight:600;font-size:14px;">Statut fidélité : {tier_title}</p>
      <p style="color:#57534E;font-size:13px;">Points: {points} | Visites: {visits}</p>
    </div>
  </div>
  <p style="text-align:center;color:#A8A29E;font-size:12px;margin-top:25px;">Envoyé via FidéliTour</p>
</div>
"""

class LoginRequest(BaseModel):
    email: str
    password: str

NAMES_POOL = [
    "Jean Dupont", "Marie Martin", "Pierre Bernard", "Sophie Laurent", "Luc Moreau", "Emma Petit",
    "Thomas Dubois", "Julie Mercier", "Olivier Fontaine", "Isabelle Arnould", "David Rousseau",
    "Claire Leblanc", "Marc Renard", "Francoise Deschamps", "Philippe Marchand",
    "Antoine Leroy", "Camille Faure", "Nicolas Girard", "Léa Bonnet", "Hugo Lefevre",
    "Chloé Moreau", "Maxime Durand", "Inès Fontaine", "Lucas Blanc", "Sarah Meyer",
    "Paul Robert", "Louise Perrin", "Gabriel Noël", "Alice Chevalier", "Raphaël Bertrand",
    "Manon Garnier", "Jules Perez", "Zoé Lambert", "Arthur Henry", "Juliette Rolland",
    "Théo Roche", "Jade Simon", "Nathan Muller", "Rose Nicolas", "Ethan Carpentier",
    "Adèle Vasseur", "Liam Mercadier", "Mila Charpentier", "Tom Fournier", "Eva Pasquier",
    "Sacha Boulanger", "Anaïs Thibault", "Léon Boucher", "Margaux Ferrand", "Noah Dumont",
]

# Sector-specific archetypes — drives realistic visit cadence, ticket size and
# tier distribution per business type. The numbers reflect French SMB norms
# (café avg ticket ≈ €5, fine dining ≈ €45, gym monthly cadence, etc).
SECTOR_PROFILES = {
    "cafe":       {"visits_per_year": (40, 120), "avg_ticket": (3.5, 7.0),  "open_hours": (7, 19)},
    "boulangerie":{"visits_per_year": (60, 200), "avg_ticket": (3.0, 6.5),  "open_hours": (6, 19)},
    "restaurant": {"visits_per_year": (3,  10),  "avg_ticket": (28, 55),    "open_hours": (12, 22)},
    "brasserie":  {"visits_per_year": (4,  14),  "avg_ticket": (22, 42),    "open_hours": (12, 23)},
    "creperie":   {"visits_per_year": (4,  12),  "avg_ticket": (15, 28),    "open_hours": (12, 22)},
    "burger":     {"visits_per_year": (6,  18),  "avg_ticket": (12, 22),    "open_hours": (11, 23)},
    "kebab":      {"visits_per_year": (10, 30),  "avg_ticket": (8,  14),    "open_hours": (11, 23)},
    "pizzeria":   {"visits_per_year": (6,  20),  "avg_ticket": (14, 26),    "open_hours": (11, 23)},
    "spa":        {"visits_per_year": (3,  10),  "avg_ticket": (55, 110),   "open_hours": (10, 19)},
    "gym":        {"visits_per_year": (60, 180), "avg_ticket": (40, 60),    "open_hours": (6, 22)},
    "juice_bar":  {"visits_per_year": (12, 40),  "avg_ticket": (5.5, 11),   "open_hours": (8, 19)},
    "ice_cream":  {"visits_per_year": (3,  12),  "avg_ticket": (4.5, 9),    "open_hours": (12, 22)},
    "chocolatier":{"visits_per_year": (4,  12),  "avg_ticket": (12, 28),    "open_hours": (10, 19)},
    "florist":    {"visits_per_year": (3,   9),  "avg_ticket": (18, 45),    "open_hours": (9, 19)},
    "bookstore":  {"visits_per_year": (4,  12),  "avg_ticket": (15, 30),    "open_hours": (10, 19)},
    "wine_bar":   {"visits_per_year": (8,  24),  "avg_ticket": (16, 38),    "open_hours": (17, 23)},
    "default":    {"visits_per_year": (5,  15),  "avg_ticket": (10, 22),    "open_hours": (9, 20)},
}

def _profile_for_tenant(tenant_id: str, sector: Optional[str] = None) -> dict:
    """Pick a sector profile, falling back to a slug-based heuristic."""
    if sector and sector in SECTOR_PROFILES:
        return SECTOR_PROFILES[sector]
    slug = (tenant_id or "").lower()
    for key in SECTOR_PROFILES:
        if key in slug:
            return SECTOR_PROFILES[key]
    return SECTOR_PROFILES["default"]


def generate_varied_customers(
    tenant_id: str,
    count: int = 15,
    *,
    sector: Optional[str] = None,
    branch_ids: Optional[List[str]] = None,
    months_history: int = 14,
) -> List[dict]:
    """Generate hyper-realistic customers for one tenant.

    Visit counts and avg tickets follow real French SMB norms per sector
    (a café customer comes 40-120×/yr at €3-7; a restaurant regular comes
    3-10×/yr at €28-55). Tier distribution follows the long-tail pattern
    seen in real loyalty programs: roughly 65% bronze / 25% silver /
    8% gold / 2% VIP.
    """
    customers = []
    profile = _profile_for_tenant(tenant_id, sector)
    branch_ids = branch_ids or []

    # Postal-code mix — Tours-heavy with Paris/Lyon spillover, matching
    # the platform's primary launch geography.
    postal_codes = (
        ["37000"] * 5 + ["37100"] * 4 + ["37200"] * 3 + ["37300"] * 2 +
        ["75001", "75008", "75011"] +
        ["69001", "69002"] +
        ["13001", "33000", "44000", "31000", "59000", "06000", "67000", "34000"]
    )
    # Acquisition mix — heavy on QR (in-store sign-up dominates), then
    # social channels in declining order. Matches the realistic split
    # owners report when surveyed.
    acquisition_sources = (
        ["qr_store"] * 45 + ["instagram"] * 26 + ["facebook"] * 13 + ["website"] * 11 + ["tiktok"] * 5
    )

    now = datetime.now(timezone.utc)
    history_days = months_history * 30
    annual_min, annual_max = profile["visits_per_year"]
    ticket_min, ticket_max = profile["avg_ticket"]

    for i in range(count):
        # Years on the program — exponential-ish: most are recent joiners,
        # a few are veterans. Capped at the history window.
        days_since_signup = int(min(
            history_days,
            random.expovariate(1 / (history_days / 3))
        ))
        years_active = max(days_since_signup / 365.0, 0.05)

        # Engagement multiplier per customer — most are average, some are
        # superfans. Long-tail with Pareto-like skew.
        engagement = random.choices(
            [0.2, 0.4, 0.7, 1.0, 1.4, 2.0, 3.0],
            weights=[10, 18, 22, 22, 14, 9, 5],
            k=1,
        )[0]

        annual_visits = random.uniform(annual_min, annual_max) * engagement
        visits = max(0, int(round(annual_visits * years_active)))

        avg_ticket = random.uniform(ticket_min, ticket_max)
        # Add per-customer ticket noise so spend doesn't perfectly track visits.
        spend_noise = random.uniform(0.85, 1.15)
        total_spent = round(visits * avg_ticket * spend_noise, 2)

        # Tier — driven by visits AND ticket size, matching realistic
        # loyalty cohorts (frequent + premium = VIP).
        if visits >= 40 or (visits >= 12 and avg_ticket >= 60):
            tier = "vip"
        elif visits >= 20 or (visits >= 8 and avg_ticket >= 45):
            tier = "gold"
        elif visits >= 8:
            tier = "silver"
        else:
            tier = "bronze"

        pass_issued = visits >= 3 and random.random() < 0.85

        last_visit = None
        if visits > 0:
            # Recently-active customers cluster in the last 30 days; quieter
            # ones drift back. Linear distribution roughly captures that.
            recency_bias = random.choices(
                [7, 21, 60, 120, 300],
                weights=[30, 30, 22, 12, 6],
                k=1,
            )[0]
            last_visit = now - timedelta(days=random.randint(1, recency_bias))

        join_date = now - timedelta(days=days_since_signup)
        primary_branch = random.choice(branch_ids) if branch_ids else None

        customers.append(Customer(
            id=f"c-{tenant_id}-{i:03d}" if not tenant_id.startswith("tenant-") else f"c-{i}",
            tenant_id=tenant_id,
            barcode_id=f"FT-{uuid.uuid4().hex[:8].upper()}",
            name=NAMES_POOL[i % len(NAMES_POOL)],
            email=f"customer{i}@{(tenant_id or 'demo').replace('_','-')}.fr",
            phone=f"06{random.randint(10000000, 99999999)}",
            postal_code=random.choice(postal_codes),
            birthday=f"{random.randint(1,12):02d}-{random.randint(1,28):02d}",
            points=visits * 10,
            visits=visits,
            total_amount_paid=total_spent,
            tier=tier,
            pass_issued=pass_issued,
            last_visit_date=last_visit,
            acquisition_source=random.choices(acquisition_sources, k=1)[0],
            branch_id=primary_branch,
            created_at=join_date,
        ).model_dump())

    return customers


def generate_visits(
    tenant_id: str,
    customer_ids: List[str],
    days_back: int = 365,
    *,
    sector: Optional[str] = None,
    branch_ids: Optional[List[str]] = None,
    customers: Optional[List[dict]] = None,
) -> List[dict]:
    """Generate realistic visit history.

    Visits are scheduled within the customer's actual visit count (not
    randomly across everyone), spread across a 12-month window with a
    natural weekday/weekend curve. Hours follow the sector's typical
    open hours, with lunch and dinner peaks for food businesses.
    """
    visits = []
    profile = _profile_for_tenant(tenant_id, sector)
    open_h, close_h = profile["open_hours"]
    branch_ids = branch_ids or []

    # Map customer_id → visit count + avg ticket so we can reproduce the
    # totals stored on each customer doc.
    by_id = {}
    if customers:
        for c in customers:
            by_id[c["id"]] = c

    now = datetime.now(timezone.utc)
    ticket_min, ticket_max = profile["avg_ticket"]

    for cid in customer_ids:
        cust = by_id.get(cid)
        n_visits = (cust or {}).get("visits", random.randint(0, 8))
        if n_visits <= 0:
            continue

        # Spread the customer's visits over the days_back window with a
        # weekly-cycle bias — roughly +25% likelihood Fri/Sat for hospitality.
        for _ in range(n_visits):
            day_offset = int(random.triangular(0, days_back, days_back * 0.4))
            visit_day = now - timedelta(days=day_offset)
            # Lunch / dinner peaks for food sectors
            if open_h <= 12 and close_h >= 14 and random.random() < 0.4:
                hour = random.choice([12, 13])
            elif open_h <= 19 and close_h >= 21 and random.random() < 0.3:
                hour = random.choice([19, 20])
            else:
                hour = random.randint(open_h, max(open_h, close_h - 1))
            visit_time = visit_day.replace(
                hour=hour,
                minute=random.randint(0, 59),
                second=0,
                microsecond=0,
            )
            amount = round(random.uniform(ticket_min, ticket_max) * random.uniform(0.85, 1.2), 2)
            visits.append(Visit(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                customer_id=cid,
                points_awarded=max(1, int(amount / 5)),
                amount_paid=amount,
                branch_id=random.choice(branch_ids) if branch_ids else None,
                visit_time=visit_time,
                created_at=visit_time,
            ).model_dump())

    return visits

def mock_seed_data():
    # Check and seed admin user
    if not db.users.find_one({"email": "admin@fidelitour.com"}):
        admin_user = UserInDB(
            email="admin@fidelitour.com",
            role="super_admin",
            hashed_password=hash_password("Fidelit0ur!Adm")
        )
        db.users.insert_one(admin_user.model_dump())

    # === Café Lumière (tenant-1, Gold plan) ===
    # Check and seed tenant
    if not db.tenants.find_one({"slug": "cafe-lumiere"}):
        t1 = Tenant(
            slug="cafe-lumiere",
            name="Café Lumière",
            plan="gold",
            address="123 Rue de Paris, Tours",
            phone="01-23-45-67-89",
            website="cafe-lumiere.fr",
            id="tenant-1",
            geo_enabled=True,
            geo_radius_meters=500,
            geo_cooldown_days=1,
            branches=[
                {
                    "id": "branch-lumiere-main",
                    "name": "Café Lumière - Main",
                    "address": "123 Rue de Paris, Tours",
                    "postal_code": "37100",
                    "phone": "01-23-45-67-89",
                    "is_main": True
                },
                {
                    "id": "branch-lumiere-plumereau",
                    "name": "Café Lumière - Plumereau",
                    "address": "456 Place Plumereau, Tours",
                    "postal_code": "37000",
                    "phone": "01-23-45-67-90",
                    "is_main": False
                }
            ]
        )
        db.tenants.insert_one(t1.model_dump())

    # Check and seed owner user
    if not db.users.find_one({"email": "owner@cafelumiere.fr"}):
        u1 = UserInDB(
            email="owner@cafelumiere.fr",
            role="business_owner",
            tenant_id="tenant-1",
            hashed_password=hash_password("CafeLum!2026")
        )
        db.users.insert_one(u1.model_dump())

    # Check and seed customers — Café Lumière is a 2-branch café in Tours.
    # Reseed when count is low OR when the customers haven't been tagged to a
    # branch yet (legacy data from before branch_id was wired into the seed),
    # OR when the demo has gone STALE.
    #
    # Staleness matters because every windowed chart (évolution des visites,
    # acquisition, campaign impact) filters on recent dates. The seed writes
    # 14 months of history relative to "now", but the count-based conditions
    # meant it ran exactly once per database: months later the lifetime tiles
    # still show totals while every "last 30 days" panel is empty, which reads
    # as a broken product in a demo. A cold start lands here anyway, so a
    # date check makes the demo self-refreshing with no cron and no endpoint.
    cafe_branches = ["branch-lumiere-main", "branch-lumiere-plumereau"]

    def _demo_is_stale() -> bool:
        # Measure freshness on the BULK of the data, not the newest single
        # visit: the c-akshansh test customer below is re-seeded with fresh
        # dates on every cold start, so "newest visit" is always young and a
        # newest-visit check never fires (which is exactly how the first
        # version of this check silently did nothing in production).
        #
        # A café with 110 customers should show dozens of visits a month.
        # Fewer than 15 in the last 30 days (excluding the always-fresh test
        # customer) means the window charts are running on fumes.
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        recent = db.visits.count_documents({
            "tenant_id": "tenant-1",
            "customer_id": {"$ne": "c-akshansh"},
            "created_at": {"$gte": cutoff},
        })
        return recent < 15

    needs_cafe_reseed = (
        db.customers.count_documents({"tenant_id": "tenant-1"}) < 80
        or db.customers.count_documents({"tenant_id": "tenant-1", "branch_id": {"$in": cafe_branches}}) == 0
        or _demo_is_stale()
    )
    if needs_cafe_reseed:
        db.customers.delete_many({"tenant_id": "tenant-1"})
        # 110 customers — realistic for a busy independent café in central Tours.
        customers_data = generate_varied_customers(
            "tenant-1",
            110,
            sector="cafe",
            branch_ids=cafe_branches,
            months_history=14,
        )
        # Branch volume split — main flagship gets 65% of customers, the
        # second location 35%. Reflects how multi-site cafés actually balance.
        for i, c in enumerate(customers_data):
            c["branch_id"] = cafe_branches[0] if i % 100 < 65 else cafe_branches[1]
        db.customers.insert_many(customers_data)

        customer_ids = [c["id"] for c in customers_data]
        db.visits.delete_many({"tenant_id": "tenant-1"})
        visits_data = generate_visits(
            "tenant-1",
            customer_ids,
            days_back=420,                # 14 months of history
            sector="cafe",
            branch_ids=cafe_branches,
            customers=customers_data,
        )
        if visits_data:
            db.visits.insert_many(visits_data)

    # Check and seed campaigns (at least 3 with proper dates)
    # Reseed when:
    #  • there aren't enough demo campaigns (fresh tenant), OR
    #  • the existing camp-1 was seeded before the image_url field landed —
    #    detected by camp-1 missing image_url. This one-time refresh is what
    #    makes the "Promo Printemps" example actually visible to existing
    #    deploys instead of being permanently shadowed by old seed data.
    existing_camp1 = db.campaigns.find_one({"id": "camp-1", "tenant_id": "tenant-1"})

    def _camp_is_stale() -> bool:
        # Campaign dates are written relative to seed-time "now" (J-2, J-14,
        # J-21). Once camp-1 drifts past ~30 days every campaign-impact chart
        # windows it out — same staleness disease as the visits above.
        if not existing_camp1 or not existing_camp1.get("sent_at"):
            return False  # covered by the count condition
        ts = existing_camp1["sent_at"]
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return True
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts) > timedelta(days=30)

    needs_reseed = (
        db.campaigns.count_documents({"tenant_id": "tenant-1"}) < 3
        or (existing_camp1 is not None and not existing_camp1.get("image_url"))
        or _camp_is_stale()
        or needs_cafe_reseed  # fresh visits deserve campaigns dated with them
    )
    if needs_reseed:
        db.campaigns.delete_many({"tenant_id": "tenant-1"})
        # Wipe stale per-recipient tracking rows for the demo campaigns so
        # opens/visits aggregates rebuild from a clean slate when reseeding.
        db.campaign_opens.delete_many({"campaign_id": {"$in": ["camp-1", "camp-2", "camp-3"]}})

        now = datetime.now(timezone.utc)
        # Hero image — Unsplash CDN (free for commercial use). Coffee + pastries
        # is a believable demo for the Café Lumière tenant. Persists across deploys.
        SAMPLE_CAMPAIGN_IMAGE = "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=1200&q=80&auto=format&fit=crop"

        # Helper: persist matching per-recipient tracking rows so the
        # tracking modal's recipient list AGREES with the aggregate counters.
        def _seed_campaign_tracking(campaign_id, sent_at, opened_ids, visited_ids):
            for cid in opened_ids:
                db.campaign_opens.insert_one({
                    "campaign_id": campaign_id,
                    "customer_id": cid,
                    "opened_at": sent_at + timedelta(hours=2),
                })

        camp1_recipients = ["c-0", "c-1", "c-2", "c-3", "c-4", "c-5", "c-6", "c-7"]
        camp1_opened = ["c-0", "c-1", "c-2", "c-4", "c-7"]      # 5 opened
        camp1_visited = ["c-0", "c-2", "c-4"]                    # 3 visited
        campaign1 = Campaign(
            id="camp-1",
            tenant_id="tenant-1",
            name="Promo Printemps — 20% sur la pâtisserie 🌸",
            status="sent",
            content=(
                "Bonjour {first_name},\n\n"
                "Le printemps arrive chez Café Lumière ! Profitez de -20% sur toutes nos "
                "pâtisseries jusqu'à dimanche soir.\n\n"
                "À très vite,\nL'équipe Café Lumière ☕"
            ),
            source="email",
            image_url=SAMPLE_CAMPAIGN_IMAGE,
            filters={"tier": "gold", "min_visits": 5},
            sent_at=now - timedelta(days=2),
            delivered_count=8,
            targeted_count=10,
            opens=5,
            opens_unique=5,
            visits_from_campaign=3,
            recipient_ids=camp1_recipients,
        )
        c1_dict = campaign1.model_dump()
        c1_dict["attributed_visit_customer_ids"] = list(camp1_visited)
        db.campaigns.insert_one(c1_dict)
        _seed_campaign_tracking("camp-1", now - timedelta(days=2), camp1_opened, camp1_visited)

        camp2_recipients = ["c-3", "c-6", "c-9", "c-12", "c-14"]
        camp2_opened = ["c-3", "c-6", "c-12", "c-14"]            # 4 opened
        camp2_visited = ["c-6", "c-14"]                          # 2 visited
        campaign2 = Campaign(
            id="camp-2",
            tenant_id="tenant-1",
            name="VIP Birthday Special",
            status="sent",
            content="Birthday exclusive: Free coffee!",
            filters={"customer_birthday_visible": True},
            sent_at=now - timedelta(days=14),
            delivered_count=5,
            targeted_count=6,
            opens=4,
            opens_unique=4,
            visits_from_campaign=2,
            recipient_ids=camp2_recipients,
        )
        c2_dict = campaign2.model_dump()
        c2_dict["attributed_visit_customer_ids"] = list(camp2_visited)
        db.campaigns.insert_one(c2_dict)
        _seed_campaign_tracking("camp-2", now - timedelta(days=14), camp2_opened, camp2_visited)

        camp3_recipients = ["c-0", "c-2", "c-4", "c-6", "c-8", "c-10", "c-11", "c-12", "c-13", "c-14"]
        camp3_opened = ["c-0", "c-2", "c-4", "c-6", "c-10", "c-12", "c-14"]   # 7 unique opened
        camp3_visited = ["c-0", "c-4", "c-6", "c-12", "c-14"]                  # 5 visited
        campaign3 = Campaign(
            id="camp-3",
            tenant_id="tenant-1",
            name="Weekend Coffee Club",
            status="sent",
            content="Join our exclusive weekend coffee club with special discounts!",
            filters={"min_visits": 3},
            sent_at=now - timedelta(days=21),
            delivered_count=12,
            targeted_count=15,
            opens=8,
            opens_unique=7,
            visits_from_campaign=5,
            recipient_ids=camp3_recipients,
        )
        c3_dict = campaign3.model_dump()
        c3_dict["attributed_visit_customer_ids"] = list(camp3_visited)
        db.campaigns.insert_one(c3_dict)
        _seed_campaign_tracking("camp-3", now - timedelta(days=21), camp3_opened, camp3_visited)

        campaign4 = Campaign(
            id="camp-4",
            tenant_id="tenant-1",
            name="Summer Refreshments",
            status="draft",
            content="Discover our new summer beverage collection.",
            filters={"tier": "silver"}
        )
        db.campaigns.insert_one(campaign4.model_dump())

    # Check and seed card template
    if not db.card_templates.find_one({"tenant_id": "tenant-1"}):
        card_template = CardTemplate(
            tenant_id="tenant-1",
            logo_url="https://example.com/cafe-logo.png",
            design_mode="hexagon_stamps",
            points_per_visit=10,
            visits_per_stamp=1,
            reward_threshold_stamps=10,
            reward_description="Un café gratuit",
            notify_before_reward=1,
            bronze_design=TierDesign(
                primary_color="#B85C38",
                secondary_color="#1C1917",
                text_color="#FFFFFF",
                accent_color="#D4A574",
                font_family="Inter",
                gradient_direction="135deg"
            ),
            silver_design=TierDesign(
                primary_color="#A0A0A0",
                secondary_color="#1C1917",
                text_color="#FFFFFF",
                accent_color="#C0C0C0",
                font_family="Inter",
                gradient_direction="135deg"
            ),
            gold_design=TierDesign(
                primary_color="#D4A574",
                secondary_color="#1C1917",
                text_color="#FFFFFF",
                accent_color="#FFD700",
                font_family="Inter",
                gradient_direction="135deg"
            ),
            show_customer_name=True,
            show_customer_birthday=True,
            show_points=True,
            show_progress_meter=True
        )
        db.card_templates.insert_one(card_template.model_dump())

    # === Boulangerie Saint-Michel (tenant-2, Chain plan, 3 branches) ===
    # Multi-branch demo — three locations in the Tours metro area, with a
    # realistic flagship/satellite volume split. Used to demo the franchise
    # analytics surfaces (per-branch leaderboard, branch comparison, etc.)
    boul_branches = [
        {
            "id": "branch-bsm-tours-centre",
            "name": "Saint-Michel — Tours Centre",
            "address": "12 Rue Nationale, 37000 Tours",
            "postal_code": "37000",
            "phone": "02-47-12-34-56",
            "is_main": True,
        },
        {
            "id": "branch-bsm-saint-pierre",
            "name": "Saint-Michel — Saint-Pierre-des-Corps",
            "address": "8 Avenue de la Gare, 37700 Saint-Pierre-des-Corps",
            "postal_code": "37700",
            "phone": "02-47-44-55-66",
            "is_main": False,
        },
        {
            "id": "branch-bsm-joue",
            "name": "Saint-Michel — Joué-lès-Tours",
            "address": "45 Boulevard Jean Jaurès, 37300 Joué-lès-Tours",
            "postal_code": "37300",
            "phone": "02-47-67-89-01",
            "is_main": False,
        },
    ]
    boul_branch_ids = [b["id"] for b in boul_branches]

    existing_t2 = db.tenants.find_one({"slug": "boulangerie-saint-michel"})
    needs_t2_upgrade = (
        existing_t2 is None
        or existing_t2.get("plan") != "chain"
        or len(existing_t2.get("branches") or []) < 3
    )
    if needs_t2_upgrade:
        # Use replace_one with upsert so existing demo accounts get migrated.
        t2_doc = Tenant(
            slug="boulangerie-saint-michel",
            name="Boulangerie Saint-Michel",
            plan="chain",
            id="tenant-2",
            address="12 Rue Nationale, 37000 Tours",
            phone="02-47-12-34-56",
            website="boulangerie-saint-michel.fr",
            sector="boulangerie",
            geo_enabled=True,
            geo_radius_meters=400,
            geo_cooldown_days=1,
            branches=boul_branches,
        ).model_dump()
        db.tenants.replace_one({"slug": "boulangerie-saint-michel"}, t2_doc, upsert=True)

    # Check and seed owner user
    if not db.users.find_one({"email": "owner@boulangerie-sm.fr"}):
        u2 = UserInDB(
            email="owner@boulangerie-sm.fr",
            role="business_owner",
            tenant_id="tenant-2",
            hashed_password=hash_password("Boulang!2026")
        )
        db.users.insert_one(u2.model_dump())

    # Check and seed customers — chain bakery with 3 locations.
    # Reseed if low count OR if customers aren't tagged to any branch.
    needs_boul_reseed = (
        db.customers.count_documents({"tenant_id": "tenant-2"}) < 200
        or db.customers.count_documents({"tenant_id": "tenant-2", "branch_id": {"$in": boul_branch_ids}}) == 0
    )
    if needs_boul_reseed:
        db.customers.delete_many({"tenant_id": "tenant-2"})
        # 240 customers across 3 branches — realistic for a chain doing
        # ≈€800k/yr combined revenue at ≈€4.50 avg ticket × 60 visits/yr.
        customers_data = generate_varied_customers(
            "tenant-2",
            240,
            sector="boulangerie",
            branch_ids=boul_branch_ids,
            months_history=18,
        )
        # Realistic franchise volume split: flagship Tours Centre 50%,
        # Saint-Pierre commuter 30%, Joué-lès-Tours suburb 20%.
        split_weights = [50, 30, 20]
        cumulative = []
        running = 0
        for w in split_weights:
            running += w
            cumulative.append(running)
        for i, c in enumerate(customers_data):
            slot = (i * 100 // len(customers_data))
            for branch_idx, threshold in enumerate(cumulative):
                if slot < threshold:
                    c["branch_id"] = boul_branch_ids[branch_idx]
                    break
        db.customers.insert_many(customers_data)

        customer_ids = [c["id"] for c in customers_data]
        db.visits.delete_many({"tenant_id": "tenant-2"})
        visits_data = generate_visits(
            "tenant-2",
            customer_ids,
            days_back=540,                # 18 months of history
            sector="boulangerie",
            branch_ids=boul_branch_ids,
            customers=customers_data,
        )
        # Each visit inherits the customer's home branch most of the time
        # (people are loyal to their local), but ~20% drift to a sibling
        # branch — captures the "I picked up a baguette near work today"
        # behavior. Let the helper assign random branches; we override the
        # majority back to the customer's home branch for realism.
        cust_home = {c["id"]: c.get("branch_id") for c in customers_data}
        for v in visits_data:
            home = cust_home.get(v["customer_id"])
            if home and random.random() < 0.8:
                v["branch_id"] = home
        if visits_data:
            db.visits.insert_many(visits_data)

    # === Test user: akshanshshukla963@gmail.com (super admin) ===
    if not db.users.find_one({"email": "akshanshshukla963@gmail.com"}):
        test_admin = UserInDB(
            email="akshanshshukla963@gmail.com",
            role="super_admin",
            hashed_password=hash_password("AkshFT!2026")
        )
        db.users.insert_one(test_admin.model_dump())

    # === Three role demo accounts (explicitly requested) ======================
    # Quick-login demo trio so reviewers can see each permission level in action.
    # All three are tied to tenant-1 (Café Lumière) except super admin, which
    # spans everything.
    demo_accounts = [
        {
            "email": "demo.admin@fidelitour.com",
            "password": "Admin!Demo2026",
            "role": "super_admin",
            "tenant_id": None,
        },
        {
            "email": "demo.owner@fidelitour.com",
            "password": "Owner!Demo2026",
            "role": "business_owner",
            "tenant_id": "tenant-1",
        },
        {
            "email": "demo.staff@fidelitour.com",
            "password": "Staff!Demo2026",
            "role": "staff",
            "tenant_id": "tenant-1",
        },
    ]
    for acct in demo_accounts:
        if not db.users.find_one({"email": acct["email"]}):
            user_kwargs = {
                "email": acct["email"],
                "role": acct["role"],
                "hashed_password": hash_password(acct["password"]),
            }
            if acct["tenant_id"]:
                user_kwargs["tenant_id"] = acct["tenant_id"]
            db.users.insert_one(UserInDB(**user_kwargs).model_dump())

    # === Primary test customer: Akshansh (postal 37000, Tours) ===
    # Ensure a single canonical test customer record for shuklaakshansh38@gmail.com
    db.customers.delete_many({"email": "shuklaakshansh38@gmail.com"})
    akshansh_customer = Customer(
        id="c-akshansh",
        tenant_id="tenant-1",
        barcode_id="FT-AKSH0001",
        name="Akshansh",
        email="shuklaakshansh38@gmail.com",
        phone="+33-612345678",
        postal_code="37000",
        birthday="1998-01-15",
        tier="gold",
        visits=18,
        total_amount_paid=382.40,
        points=1800,
        pass_issued=True,
        acquisition_source="instagram",
        created_at=datetime.now(timezone.utc) - timedelta(days=45),
        last_visit_date=datetime.now(timezone.utc) - timedelta(days=2)
    )
    db.customers.insert_one(akshansh_customer.model_dump())

    # Seed a visit history so campaign/map/analytics flows all have rich data for this customer
    db.visits.delete_many({"customer_id": "c-akshansh"})
    now = datetime.now(timezone.utc)
    akshansh_visits = []
    for i in range(18):
        vt = now - timedelta(days=random.randint(0, 60), hours=random.randint(0, 12))
        akshansh_visits.append(Visit(
            id=str(uuid.uuid4()),
            tenant_id="tenant-1",
            customer_id="c-akshansh",
            points_awarded=random.choice([10, 15, 20]),
            amount_paid=round(random.uniform(8, 28), 2),
            visit_time=vt,
            created_at=vt
        ).model_dump())
    db.visits.insert_many(akshansh_visits)

    # Also add Akshansh to Boulangerie Saint-Michel so multi-tenant testing works
    db.customers.delete_many({"email": "shuklaakshansh38@gmail.com", "tenant_id": "tenant-2"})
    akshansh_bakery = Customer(
        id="c-akshansh-bakery",
        tenant_id="tenant-2",
        barcode_id="FT-AKSH0002",
        name="Akshansh",
        email="shuklaakshansh38@gmail.com",
        phone="+33-612345678",
        postal_code="37000",
        birthday="1998-01-15",
        tier="silver",
        visits=6,
        total_amount_paid=87.50,
        points=600,
        pass_issued=True,
        acquisition_source="qr_store",
        created_at=datetime.now(timezone.utc) - timedelta(days=20)
    )
    db.customers.insert_one(akshansh_bakery.model_dump())

    # === Seed 20 varied businesses for admin feature-coverage testing ===
    seed_extended_tenants()


# ============================================================
# EXTENDED TENANT SEED — 20 realistic businesses covering every
# combination: sector, plan, GPS on/off, multi-branch, varied sizes.
# ============================================================
EXTENDED_TENANTS_SPEC = [
    # (slug, name, sector, plan, postal, city_lat, city_lng, address, phone, website, geo_on, customers, min_visits_any, avg_spend, has_offer, branches)
    ("maison-gourmet-paris",    "Maison Gourmet",       "restaurant",   "vip",   "75008", 48.8723, 2.3047, "12 Rue Saint-Honoré, 75008 Paris",     "01-42-65-10-11", "maison-gourmet.fr", True,  42, 2, 38.50, True,  0),
    ("pizza-napoli-lyon",       "Pizza Napoli",         "pizzeria",     "gold",  "69002", 45.7484, 4.8320, "28 Rue de la République, 69002 Lyon",   "04-78-42-15-22", "pizzanapoli.fr",   True,  31, 1, 18.20, True,  0),
    ("glacier-berthillon",      "Glacier Berthillon",   "glacier",      "gold",  "75004", 48.8519, 2.3565, "29-31 Rue Saint-Louis-en-l'Île, Paris", "01-43-54-31-61", "berthillon.fr",    False, 27, 2, 9.80,  True,  0),
    ("brasserie-flo-strasbourg","Brasserie Flo",        "brasserie",    "vip",   "67000", 48.5839, 7.7455, "Place Kléber, 67000 Strasbourg",        "03-88-32-45-12", "flo-strasbourg.fr", True, 55, 3, 42.10, True,  0),
    ("sushi-zen-nice",          "Sushi Zen",            "sushi",        "gold",  "06000", 43.7034, 7.2663, "8 Rue Masséna, 06000 Nice",             "04-93-16-25-88", "sushizen.fr",      True,  24, 1, 29.40, True,  0),
    ("burger-republic-lille",   "Burger Republic",      "burger",       "basic", "59000", 50.6292, 3.0573, "45 Rue de Béthune, 59000 Lille",        "03-20-55-33-44", "burgerrepublic.fr", False, 18, 1, 15.60, False, 0),
    ("kebab-istanbul-marseille","Kebab Istanbul",       "kebab",        "basic", "13001", 43.2965, 5.3698, "102 Canebière, 13001 Marseille",        "04-91-54-22-11", "",                 False, 14, 1, 11.40, False, 0),
    ("creperie-bretonne-rennes","Crêperie Bretonne",    "crêperie",     "gold",  "35000", 48.1147, -1.6794,"18 Rue Saint-Georges, 35000 Rennes",    "02-99-38-17-63", "creperie-bretonne.fr", True, 33, 2, 16.80, True, 0),
    ("chocolatier-lyonnais",    "Chocolatier Lyonnais", "chocolatier",  "vip",   "69001", 45.7580, 4.8320, "4 Rue du Président Carnot, 69001 Lyon", "04-78-28-44-99", "chocolatier-lyonnais.fr", True, 38, 2, 24.20, True, 0),
    ("tea-palace-toulouse",     "Tea Palace",           "tea salon",    "gold",  "31000", 43.6047, 1.4442, "22 Rue du Taur, 31000 Toulouse",        "05-61-22-88-37", "tea-palace.fr",    False, 21, 1, 13.40, True,  0),
    ("wine-bar-bordeaux",       "Wine Bar Bordeaux",    "wine bar",     "vip",   "33000", 44.8378, -0.5792,"10 Place Saint-Pierre, 33000 Bordeaux", "05-56-44-77-22", "winebar-bdx.fr",   True,  46, 3, 32.70, True,  0),
    ("juice-lab-montpellier",   "Juice Lab",            "juice bar",    "basic", "34000", 43.6108, 3.8767, "5 Rue Foch, 34000 Montpellier",         "04-67-66-33-21", "",                 False, 17, 1, 8.20,  False, 0),
    ("salon-elegance-paris",    "Salon Élégance",       "hair salon",   "gold",  "75016", 48.8646, 2.2769, "55 Avenue Victor Hugo, 75016 Paris",    "01-45-53-22-18", "salon-elegance.fr", True, 29, 2, 58.30, True, 0),
    ("spa-luxe-cannes",         "Spa Luxe",             "spa",          "vip",   "06400", 43.5528, 7.0174, "14 La Croisette, 06400 Cannes",         "04-93-38-72-11", "spaluxe.fr",       True,  36, 2, 89.40, True,  0),
    ("fit-gym-nantes",          "Fit Gym",              "gym",          "gold",  "44000", 47.2184, -1.5536,"33 Cours des 50 Otages, 44000 Nantes",  "02-40-73-12-45", "fitgym.fr",        True,  51, 3, 42.00, True,  0),
    ("yoga-zen-paris",          "Yoga Zen Studio",      "yoga",         "basic", "75011", 48.8566, 2.3801, "88 Rue du Faubourg Saint-Antoine, Paris","01-43-57-81-29","yoga-zen-studio.fr", False, 22, 1, 25.00, True, 0),
    ("dance-floor-toulouse",    "Dance Floor",          "dance",        "basic", "31000", 43.6047, 1.4442, "6 Rue Saint-Rome, 31000 Toulouse",      "05-61-23-77-66", "",                 False, 15, 1, 22.00, False, 0),
    ("librairie-mollat-bdx",    "Librairie Mollat",     "book store",   "gold",  "33000", 44.8411, -0.5761,"15 Rue Vital-Carles, 33000 Bordeaux",   "05-56-56-40-40", "mollat.com",       False, 34, 2, 24.60, True,  0),
    ("fleuriste-rose-paris",    "Fleuriste Rose",       "florist",      "basic", "75005", 48.8462, 2.3444, "7 Rue Mouffetard, 75005 Paris",         "01-45-35-22-48", "",                 False, 19, 1, 35.80, True,  0),
    ("optique-vision-tours",    "Optique Vision",       "optician",     "chain", "37000", 47.3941, 0.6848, "12 Rue Nationale, 37000 Tours",         "02-47-66-15-22", "optique-vision.fr", True,  62, 2, 95.40, True,  2),
]

SECTOR_CAMPAIGN_TEMPLATES = {
    "restaurant":   ("Table d'Hôtes", "Dégustation saisonnière : -20% sur la carte du soir"),
    "pizzeria":     ("Soirée Napolitaine", "Acheté 1 pizza, la 2ème à -50%"),
    "glacier":      ("Happy Summer", "Cornet gratuit pour 5 boules achetées"),
    "brasserie":    ("Happy Hour", "-30% sur les plats entre 17h et 19h"),
    "sushi":        ("Sushi Lover", "Plateau 24 pièces à 19€ au lieu de 28€"),
    "burger":       ("Cheat Day", "Menu burger à 9,90€ le mardi"),
    "kebab":        ("Midi Express", "Menu complet à 8€ de 12h à 14h"),
    "crêperie":     ("Breizh Day", "Galette + crêpe + cidre à 12€"),
    "chocolatier":  ("Pâques à Venir", "-15% sur tous les œufs de Pâques"),
    "tea salon":    ("Afternoon Tea", "Formule thé + pâtisserie à 7,50€"),
    "wine bar":     ("Dégustation", "3 verres + planche à 15€ le jeudi"),
    "juice bar":    ("Detox Week", "Abonnement 5 jus à -25%"),
    "hair salon":   ("Nouveau Look", "Coupe + brushing + soin à 39€"),
    "spa":          ("Rituel Bien-Être", "-20% sur le modelage californien"),
    "gym":          ("Spring Back in Shape", "Mois d'essai à 19€ + bilan offert"),
    "yoga":         ("Pleine Conscience", "Carnet 10 séances à -15%"),
    "dance":        ("Salsa Night", "Cours d'essai offert + carnet à -10%"),
    "book store":   ("Club Lecteurs", "1 livre acheté = 1 marque-page offert"),
    "florist":      ("Bouquet du Mois", "-20% sur les bouquets de saison"),
    "optician":     ("Vision Clarity", "2ème paire à 1€ pour tout achat monture"),
}

REWARD_BY_SECTOR = {
    "restaurant": "Un apéritif offert",
    "pizzeria": "Une pizza margherita offerte",
    "glacier": "Un cornet 2 boules offert",
    "brasserie": "Un café gourmand offert",
    "sushi": "Un plateau 8 pièces offert",
    "burger": "Un menu cheeseburger offert",
    "kebab": "Un sandwich kebab offert",
    "crêperie": "Une crêpe Nutella offerte",
    "chocolatier": "Une boîte 6 pralinés offerte",
    "tea salon": "Un thé + une pâtisserie offerts",
    "wine bar": "Un verre de vin rouge offert",
    "juice bar": "Un smoothie detox offert",
    "hair salon": "Un soin capillaire offert",
    "spa": "Un modelage 20 min offert",
    "gym": "Une semaine d'accès libre",
    "yoga": "Un cours d'essai offert",
    "dance": "Un cours particulier offert",
    "book store": "Un livre à -50%",
    "florist": "Un bouquet saisonnier offert",
    "optician": "Un étui + nettoyage offerts",
}

def seed_extended_tenants():
    """Seed 20 varied tenants with owners, customers, visits, campaigns, card templates.
    Bulk-inserts everything (~8 round-trips instead of ~120) so it stays
    under Vercel's serverless timeout. Idempotent: skips slugs already present."""
    NAMES_POOL = [
        "Antoine Leroy", "Camille Faure", "Nicolas Girard", "Léa Bonnet", "Hugo Lefevre",
        "Chloé Moreau", "Maxime Durand", "Inès Fontaine", "Lucas Blanc", "Sarah Meyer",
        "Paul Robert", "Louise Perrin", "Gabriel Noël", "Alice Chevalier", "Raphaël Bertrand",
        "Manon Garnier", "Jules Perez", "Zoé Lambert", "Arthur Henry", "Juliette Rolland",
        "Théo Roche", "Jade Simon", "Nathan Muller", "Rose Nicolas", "Ethan Carpentier",
        "Lola Bonneau", "Adam Fabre", "Clara Giraud", "Samuel Hubert", "Mia Colin",
        "Tom Vidal", "Elsa Leroux", "Victor Guerin", "Alba Prévost", "Noah Barbier",
        "Eva Renaud", "Louis Picard", "Iris Lecomte", "Baptiste Boulanger", "Lina Aubert",
        "Simon Texier", "Lily Marchal", "Rémi Masson", "Anaëlle Poirier", "Enzo Schmitt",
        "Lisa Klein", "Milo Weiss", "Nora Caron", "Yanis Hamon", "Léna Blanchard",
        "Axel Pasquier", "Maya Gonzalez", "Basile Dupuis", "Tess Richard", "Gaspard Adam",
        "Agathe Vallet", "Élise Roux", "Matteo Gay", "Camille Leconte", "Diane Thibault",
        "Oscar Jacquet", "Salomé Faivre", "Nolan Rey", "Anna Charpentier", "Achille Meunier"
    ]
    # Permitted sources — five channels customers actually arrive through.
    ACQUISITION_SOURCES = ["qr_store", "instagram", "facebook", "tiktok", "website"]
    BIRTHDAY_POOL = [f"{random.randint(1,12):02d}-{random.randint(1,28):02d}" for _ in range(100)]

    now = datetime.now(timezone.utc)

    # One-shot idempotency: pull existing extended slugs in a single query
    all_slugs = [spec[0] for spec in EXTENDED_TENANTS_SPEC]
    existing_slugs = set(
        t["slug"] for t in db.tenants.find({"slug": {"$in": all_slugs}}, {"slug": 1})
    )

    # Hash the shared demo password ONCE (bcrypt is slow on cold serverless)
    shared_owner_hash = hash_password("Demo!2026")

    # Accumulators — one insert_many per collection at the end
    tenants_docs = []
    users_docs = []
    customers_docs = []
    visits_docs = []
    campaigns_docs = []
    card_templates_docs = []

    for idx, spec in enumerate(EXTENDED_TENANTS_SPEC):
        (slug, name, sector, plan, postal, lat, lng, address, phone, website,
         geo_on, target_cust_count, min_visits_any, avg_spend, has_offer, branch_count) = spec

        tenant_id = f"tenant-ext-{idx+1:02d}"

        # Idempotent skip
        if slug in existing_slugs:
            continue

        # Build branches for chain/multi-branch
        branches = []
        if branch_count > 0:
            branches.append({
                "id": f"branch-{slug}-main",
                "name": f"{name} - Centre",
                "address": address,
                "postal_code": postal,
                "phone": phone,
                "is_main": True
            })
            for bi in range(branch_count):
                branches.append({
                    "id": f"branch-{slug}-{bi+1}",
                    "name": f"{name} - Succursale {bi+1}",
                    "address": f"{random.randint(1,99)} Rue {random.choice(['Pasteur','Gambetta','Victor Hugo','Jean Jaurès'])}, {postal}",
                    "postal_code": postal,
                    "phone": phone,
                    "is_main": False
                })

        tenants_docs.append(Tenant(
            id=tenant_id,
            slug=slug,
            name=name,
            plan=plan,
            address=address,
            phone=phone,
            website=website,
            geo_enabled=geo_on,
            geo_radius_meters=500 if geo_on else None,
            geo_cooldown_days=1,
            branches=branches,
            sector=sector,
            campaign_sender_name=name,  # default to business name
            created_at=now - timedelta(days=random.randint(30, 365))
        ).model_dump())

        # Owner user — shared password hash reused across all demo owners
        owner_email = f"owner+{slug}@fidelitour.fr"
        users_docs.append(UserInDB(
            email=owner_email,
            role="business_owner",
            tenant_id=tenant_id,
            hashed_password=shared_owner_hash
        ).model_dump())

        # Customers — always >= 14 to guarantee rich drill-downs everywhere
        customer_count = max(target_cust_count, 14)
        customers = []
        for ci in range(customer_count):
            # Ensure at least some gold and silver for each tenant
            if ci < max(3, customer_count // 8):
                visits = random.randint(20, 40)
                tier = "gold"
            elif ci < max(7, customer_count // 3):
                visits = random.randint(10, 19)
                tier = "silver"
            else:
                visits = random.randint(max(min_visits_any, 1), 9)
                tier = "bronze"

            spend = round(visits * random.uniform(avg_spend * 0.7, avg_spend * 1.3), 2)
            source = random.choices(
                ACQUISITION_SOURCES,
                # One weight per source — ["qr_store","instagram","facebook","tiktok","website"].
                # "website" was appended to the list without a weight, which made
                # random.choices raise and killed server startup on a fresh DB.
                weights=[5, 4, 3, 2, 2],
                k=1
            )[0]
            pass_issued = random.random() < 0.7 if visits >= 3 else random.random() < 0.3
            last_visit = now - timedelta(days=random.randint(0, 45)) if visits > 0 else None

            customer = Customer(
                id=f"c-{tenant_id}-{ci:03d}",
                tenant_id=tenant_id,
                barcode_id=f"FT-{tenant_id[-4:].upper()}{ci:03d}",
                name=NAMES_POOL[(idx * 7 + ci) % len(NAMES_POOL)],
                email=f"c{ci:03d}@{slug}.test",
                phone=f"06{random.randint(10000000, 99999999)}",
                postal_code=postal,
                birthday=BIRTHDAY_POOL[(idx * 11 + ci) % len(BIRTHDAY_POOL)],
                tier=tier,
                visits=visits,
                total_amount_paid=spend,
                points=visits * 10,
                pass_issued=pass_issued,
                acquisition_source=source,
                last_visit_date=last_visit,
                created_at=now - timedelta(days=random.randint(1, 180))
            )
            customers.append(customer.model_dump())
        customers_docs.extend(customers)

        # Visits — cap per-customer events at 6 to keep the total tractable
        for c in customers:
            num_events = min(c["visits"], random.randint(3, 6))
            for _ in range(num_events):
                vt = now - timedelta(days=random.randint(0, 75), hours=random.randint(7, 20))
                visits_docs.append(Visit(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    customer_id=c["id"],
                    points_awarded=random.choice([10, 15, 20]),
                    amount_paid=round(random.uniform(avg_spend * 0.6, avg_spend * 1.4), 2),
                    visit_time=vt,
                    created_at=vt
                ).model_dump())

        # Campaigns — every tenant gets 2-4 campaigns (mix of sent + draft)
        camp_name, camp_content = SECTOR_CAMPAIGN_TEMPLATES.get(sector, ("Offre Spéciale", "Profitez d'une offre exclusive"))
        targeted = random.randint(10, min(customer_count, 40))
        delivered = int(targeted * random.uniform(0.7, 0.95))
        opens = int(delivered * random.uniform(0.4, 0.8))
        visits_from = int(opens * random.uniform(0.2, 0.5))
        recipient_ids = [c["id"] for c in customers[:targeted]]

        campaigns_docs.extend([
            Campaign(
                id=f"camp-{tenant_id}-1",
                tenant_id=tenant_id,
                name=camp_name,
                status="sent",
                content=camp_content,
                filters={"min_visits": 2},
                sent_at=now - timedelta(days=random.randint(5, 30)),
                targeted_count=targeted,
                delivered_count=delivered,
                opens=opens,
                opens_unique=int(opens * 0.85),
                visits_from_campaign=max(visits_from, 1),
                recipient_ids=recipient_ids,
            ).model_dump(),
            Campaign(
                id=f"camp-{tenant_id}-2",
                tenant_id=tenant_id,
                name=f"Fidélité {name}",
                status="sent",
                content=f"Nouveau palier atteint chez {name} ! Récompense offerte.",
                filters={"tier": "gold"},
                sent_at=now - timedelta(days=random.randint(40, 70)),
                targeted_count=max(targeted // 3, 3),
                delivered_count=max(delivered // 3, 2),
                opens=max(opens // 3, 1),
                opens_unique=max(opens // 3, 1),
                visits_from_campaign=max(visits_from // 2, 1),
                recipient_ids=recipient_ids[: max(targeted // 3, 3)],
            ).model_dump(),
            Campaign(
                id=f"camp-{tenant_id}-3",
                tenant_id=tenant_id,
                name=f"Relance {sector.capitalize()}",
                status="draft",
                content="Campagne de relance clients inactifs.",
                filters={"min_visits": 1},
            ).model_dump(),
        ])

        # Card template with active offer (Captain-Wallet-style richness)
        sector_palette = {
            "restaurant":  ("#8B4513", "#FFF8DC", "#FFFFFF", "#D2691E"),
            "pizzeria":    ("#C41E3A", "#FEF6E4", "#FFFFFF", "#FFC857"),
            "glacier":     ("#EF5DA8", "#FFF0F7", "#FFFFFF", "#A8DADC"),
            "brasserie":   ("#4A5D23", "#F3EFE7", "#FFFFFF", "#E3A869"),
            "sushi":       ("#0F1020", "#FFFFFF", "#FFFFFF", "#E63946"),
            "burger":      ("#E63946", "#FFF8E7", "#FFFFFF", "#FFC300"),
            "kebab":       ("#A44A3F", "#FFF8E7", "#FFFFFF", "#F1A208"),
            "crêperie":    ("#E8A87C", "#FFFFFF", "#1C1917", "#C38D9E"),
            "chocolatier": ("#3E1F11", "#F5E0C3", "#FFFFFF", "#C58F4A"),
            "tea salon":   ("#7B9B59", "#FAF3E0", "#FFFFFF", "#D1A8A8"),
            "wine bar":    ("#5D2838", "#F6E3C9", "#FFFFFF", "#C9AE88"),
            "juice bar":   ("#2FAF68", "#F6FFF6", "#FFFFFF", "#F5D547"),
            "hair salon":  ("#1C1917", "#FAF3E0", "#FFFFFF", "#D4A574"),
            "spa":         ("#89B0AE", "#FFFFFF", "#1C1917", "#E0C1B3"),
            "gym":         ("#0F1020", "#FFFFFF", "#FFFFFF", "#FF6B35"),
            "yoga":        ("#A8C686", "#FDFBF7", "#1C1917", "#F9C784"),
            "dance":       ("#6A0572", "#FFF8FC", "#FFFFFF", "#F15BB5"),
            "book store":  ("#264653", "#FAF3E0", "#FFFFFF", "#E9C46A"),
            "florist":     ("#FF6B9D", "#FFF8FC", "#FFFFFF", "#95D5B2"),
            "optician":    ("#1E3A8A", "#F0F6FF", "#FFFFFF", "#F59E0B"),
        }.get(sector, ("#B85C38", "#1C1917", "#FFFFFF", "#D4A574"))
        primary, secondary, text_c, accent = sector_palette

        card_template = CardTemplate(
            tenant_id=tenant_id,
            logo_url=f"https://dummyimage.com/120x120/{primary.lstrip('#')}/{text_c.lstrip('#')}&text={name[:1]}",
            active_offer_title=camp_name,
            active_offer_description=camp_content,
            active_offer_active=has_offer,
            design_mode="hexagon_stamps",
            points_per_visit=10,
            visits_per_stamp=1,
            reward_threshold_stamps=random.choice([8, 10, 12]),
            reward_description=REWARD_BY_SECTOR.get(sector, "Une récompense fidélité"),
            notify_before_reward=1,
            bronze_design=TierDesign(
                primary_color=primary, secondary_color=secondary, text_color=text_c,
                accent_color=accent, font_family="Inter", gradient_direction="135deg"
            ),
            silver_design=TierDesign(
                primary_color="#A0A0A0", secondary_color=secondary, text_color="#FFFFFF",
                accent_color="#C0C0C0", font_family="Inter", gradient_direction="135deg"
            ),
            gold_design=TierDesign(
                primary_color="#D4A574", secondary_color=secondary, text_color="#FFFFFF",
                accent_color="#FFD700", font_family="Inter", gradient_direction="135deg"
            ),
            show_customer_name=True,
            show_customer_birthday=True,
            show_points=True,
            show_progress_meter=True,
        )
        card_templates_docs.append(card_template.model_dump())

    # Final bulk insert — one round-trip per collection
    if tenants_docs:
        db.tenants.insert_many(tenants_docs)
    if users_docs:
        db.users.insert_many(users_docs)
    if customers_docs:
        db.customers.insert_many(customers_docs)
    if visits_docs:
        db.visits.insert_many(visits_docs)
    if campaigns_docs:
        db.campaigns.insert_many(campaigns_docs)
    if card_templates_docs:
        db.card_templates.insert_many(card_templates_docs)


# Seed data on every cold start (Vercel serverless workaround)
# RGPD/security: set DISABLE_SEED=1 in Vercel env to stop demo accounts +
# demo credentials from being (re)created — REQUIRED before production
# launch with real customer data. Default stays ON so current demos keep
# working without any env change.
SEED_DISABLED = os.environ.get("DISABLE_SEED", "") == "1"
_seeded = False
_seed_error = None

@app.middleware("http")
async def ensure_seed_data(request: Request, call_next):
    global _seeded, _seed_error
    if SEED_DISABLED:
        _seeded = True
    if not _seeded:
        try:
            mock_seed_data()
            _seeded = True
            _seed_error = None
        except Exception as e:
            _seed_error = str(e)
            _seeded = True  # Don't retry every request
            import traceback
            traceback.print_exc()
    response = await call_next(request)
    return response

@app.on_event("startup")
async def startup_event():
    if SEED_DISABLED:
        return
    try:
        mock_seed_data()
    except Exception as e:
        import traceback
        traceback.print_exc()

# Health check endpoint for debugging
@app.get("/api/health")
def health_check():
    try:
        user_count = db.users.count_documents({})
        tenant_count = db.tenants.count_documents({})
        customer_count = db.customers.count_documents({})
        # NOTE: this endpoint is public and unauthenticated. It used to return
        # every user's email + role — 54 addresses handed to anyone who typed
        # the URL. Counts are enough to answer "is the database reachable";
        # the identities are personal data (RGPD art. 32). Use the
        # authenticated /api/admin/tenants endpoints to inspect accounts.
        return {
            "status": "ok",
            "mongodb_uri_set": bool(MONGODB_URI),
            "seed_error": _seed_error,
            "counts": {
                "users": user_count,
                "tenants": tenant_count,
                "customers": customer_count
            },
        }
    except Exception as e:
        return {"status": "error", "detail": str(e), "mongodb_uri_set": bool(MONGODB_URI)}

# ═══════════════════════════════════════════════════════════════════════
# SUPPORT INBOX — businesses send queries from inside the dashboard
# ───────────────────────────────────────────────────────────────────────
# Every submission is:
#   1. Always stored in `support_tickets` collection (so nothing is
#      lost even if email delivery fails).
#   2. Forwarded to SUPPORT_RECIPIENT_EMAIL via the first configured
#      delivery channel. We try in order:
#        a. SMTP (most reliable)        → set SUPPORT_SMTP_USER + SUPPORT_SMTP_PASS
#        b. Resend (modern transactional) → set RESEND_API_KEY
#        c. Formsubmit.co (no signup)    → automatic fallback, but the
#           free tier requires the recipient inbox to activate by
#           clicking a link in an activation email Formsubmit sends.
#           Gmail spam filters sometimes eat that activation email,
#           which is why SMTP / Resend is preferred.
#
# Configure SMTP via Vercel env vars to make this just work:
#    SUPPORT_SMTP_HOST = smtp.gmail.com    (default)
#    SUPPORT_SMTP_PORT = 587               (default)
#    SUPPORT_SMTP_USER = <your gmail>
#    SUPPORT_SMTP_PASS = <16-char App Password from
#                         Google Account → Security → App passwords>
# ═══════════════════════════════════════════════════════════════════════

SUPPORT_RECIPIENT_EMAIL = os.getenv("SUPPORT_RECIPIENT_EMAIL", "shuklaakshansh38@gmail.com")


def _support_email_html(subject: str, message: str, ticket: dict) -> str:
    """Render the support ticket as a branded HTML email body."""
    safe_msg = (message or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    safe_sub = (subject or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""
<div style="font-family:'Manrope',Arial,sans-serif;max-width:600px;margin:0 auto;background:#FBF7EE;padding:24px;color:#1C1917;">
  <div style="background:#FFFFFF;border-radius:12px;padding:24px;border:1px solid #E8DEC8;">
    <div style="border-bottom:2px solid #6B2E5A;padding-bottom:10px;margin-bottom:18px;">
      <p style="margin:0;font-size:11px;letter-spacing:.18em;color:#6B2E5A;text-transform:uppercase;font-weight:600;">FidéliTour · Support</p>
      <h2 style="margin:6px 0 0;font-size:18px;color:#1C1917;">New support query</h2>
    </div>
    <table style="width:100%;font-size:13px;color:#57534E;margin-bottom:14px;">
      <tr><td style="padding:3px 0;color:#8B8680;width:110px;">From</td><td style="padding:3px 0;color:#1C1917;">{ticket.get('from_email') or '(not provided)'}</td></tr>
      <tr><td style="padding:3px 0;color:#8B8680;">Tenant</td><td style="padding:3px 0;color:#1C1917;">{ticket.get('tenant_slug') or '(unknown)'}</td></tr>
      <tr><td style="padding:3px 0;color:#8B8680;">Submitted</td><td style="padding:3px 0;color:#1C1917;">{ticket['created_at'].isoformat()}</td></tr>
      <tr><td style="padding:3px 0;color:#8B8680;">Ticket ID</td><td style="padding:3px 0;color:#1C1917;font-family:'JetBrains Mono',monospace;font-size:11px;">{ticket['id']}</td></tr>
    </table>
    <div style="background:#FBF7EE;border-left:3px solid #C9A227;padding:14px 16px;border-radius:6px;margin-bottom:14px;">
      <p style="margin:0 0 6px;font-size:11px;letter-spacing:.1em;color:#8B8680;text-transform:uppercase;">Subject</p>
      <p style="margin:0;font-size:15px;color:#1C1917;font-weight:600;">{safe_sub}</p>
    </div>
    <div>
      <p style="margin:0 0 8px;font-size:11px;letter-spacing:.1em;color:#8B8680;text-transform:uppercase;">Message</p>
      <p style="margin:0;font-size:14px;color:#1C1917;line-height:1.55;white-space:pre-wrap;">{safe_msg}</p>
    </div>
    <p style="margin:18px 0 0;padding-top:12px;border-top:1px solid #ECE3D2;font-size:11px;color:#8B8680;">
      Reply directly to this email to respond to the business.
    </p>
  </div>
</div>"""


def _support_send_smtp(subject: str, message: str, ticket: dict) -> tuple[bool, str | None]:
    """Send the ticket via SMTP. Returns (sent, error_or_none).
    Reads SUPPORT_SMTP_HOST/PORT/USER/PASS from env. Returns (False,
    'not_configured') if env vars missing — caller can fall through."""
    smtp_user = os.getenv("SUPPORT_SMTP_USER", "").strip()
    smtp_pass = os.getenv("SUPPORT_SMTP_PASS", "").strip()
    if not smtp_user or not smtp_pass:
        return (False, "not_configured")
    smtp_host = os.getenv("SUPPORT_SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SUPPORT_SMTP_PORT", "587"))
    smtp_from = os.getenv("SUPPORT_SMTP_FROM", smtp_user).strip()

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.utils import formataddr

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[FidéliTour Support] {subject}"
        msg["From"]    = formataddr(("FidéliTour Support", smtp_from))
        msg["To"]      = SUPPORT_RECIPIENT_EMAIL
        # Set Reply-To to the business's email so support can hit reply.
        reply_to = ticket.get("from_email") or smtp_from
        msg["Reply-To"] = reply_to

        # Plain-text fallback for clients that block HTML.
        plain = (
            f"New FidéliTour support query\n\n"
            f"From: {ticket.get('from_email') or '(not provided)'}\n"
            f"Tenant: {ticket.get('tenant_slug') or '(unknown)'}\n"
            f"Submitted: {ticket['created_at'].isoformat()}\n"
            f"Ticket ID: {ticket['id']}\n\n"
            f"Subject: {subject}\n\n"
            f"{message}\n"
        )
        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(_support_email_html(subject, message, ticket), "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as srv:
            srv.ehlo()
            srv.starttls()
            srv.ehlo()
            srv.login(smtp_user, smtp_pass)
            srv.send_message(msg)
        return (True, None)
    except Exception as e:
        return (False, f"smtp_error: {type(e).__name__}: {e}")


def _support_send_resend(subject: str, message: str, ticket: dict) -> tuple[bool, str | None]:
    """Send the ticket via Resend API. Returns (sent, error_or_none).
    Returns (False, 'not_configured') if RESEND_API_KEY missing."""
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        return (False, "not_configured")
    from_addr = os.getenv("RESEND_FROM", "FidéliTour Support <onboarding@resend.dev>").strip()
    try:
        import requests as _req
        reply_to = ticket.get("from_email") or None
        body = {
            "from":     from_addr,
            "to":       [SUPPORT_RECIPIENT_EMAIL],
            "subject":  f"[FidéliTour Support] {subject}",
            "html":     _support_email_html(subject, message, ticket),
        }
        if reply_to:
            body["reply_to"] = reply_to
        r = _req.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=15,
        )
        if r.status_code in (200, 201, 202):
            return (True, None)
        return (False, f"resend_error: status={r.status_code} body={r.text[:200]}")
    except Exception as e:
        return (False, f"resend_error: {type(e).__name__}: {e}")


def _support_send_formsubmit(subject: str, message: str, ticket: dict) -> tuple[bool, str | None]:
    """Fallback delivery via Formsubmit.co. Requires the recipient
    inbox to activate first by clicking a link in an activation email
    Formsubmit sends — Gmail spam filters sometimes eat that, which
    is why SMTP / Resend is preferred."""
    try:
        import requests as _req
        fs_payload = {
            "_subject":     f"[FidéliTour Support] {subject}",
            "_template":    "table",
            "_captcha":     "false",
            "_replyto":     ticket.get("from_email") or "no-reply@fidelitour.app",
            "from_email":   ticket.get("from_email") or "no-reply@fidelitour.app",
            "tenant_slug":  ticket.get("tenant_slug") or "(unknown)",
            "subject":      subject,
            "message":      message,
            "ticket_id":    ticket["id"],
            "submitted_at": ticket["created_at"].isoformat(),
        }
        r = _req.post(
            f"https://formsubmit.co/ajax/{SUPPORT_RECIPIENT_EMAIL}",
            json=fs_payload,
            timeout=10,
        )
        try:
            ok = (r.status_code == 200) and (r.json().get("success") in (True, "true", "True"))
        except Exception:
            ok = False
        if ok:
            return (True, None)
        return (False, f"formsubmit_error: status={r.status_code} body={r.text[:200]}")
    except Exception as e:
        return (False, f"formsubmit_error: {type(e).__name__}: {e}")


class SupportTicketIn(BaseModel):
    subject: str
    message: str
    from_email: Optional[str] = None
    from_name:  Optional[str] = None
    tenant_slug: Optional[str] = None


@app.post("/api/support/contact")
def submit_support_ticket(payload: SupportTicketIn):
    """Receive a support query from a business and forward it to the
    platform's support inbox. Always persists the ticket to MongoDB
    regardless of email-delivery outcome so the support team can
    review tickets in the database even if SMTP is misconfigured."""
    import uuid as _uuid
    subject = (payload.subject or "").strip()
    message = (payload.message or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject is required.")
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")
    if len(subject) > 200:
        raise HTTPException(status_code=400, detail="Subject is too long (max 200 chars).")
    if len(message) > 5000:
        raise HTTPException(status_code=400, detail="Message is too long (max 5000 chars).")

    ticket = {
        "id":           str(_uuid.uuid4()),
        "subject":      subject,
        "message":      message,
        "from_email":   (payload.from_email or "").strip() or None,
        "from_name":    (payload.from_name  or "").strip() or None,
        "tenant_slug":  (payload.tenant_slug or "").strip() or None,
        "created_at":   datetime.now(timezone.utc),
        "status":       "open",
        "email_sent":   False,
        "email_error":  None,
    }

    # 1) Persist first — never lose a ticket because of network flakiness.
    try:
        db.support_tickets.insert_one(ticket)
    except Exception as e:
        print(f"[support] DB insert failed: {e}")

    # 2) Try delivery channels in priority order. First success wins.
    #    Each helper returns (sent: bool, error_or_none: str|None).
    #    Errors are accumulated so the admin can see which channel
    #    failed and why in the ticket record.
    delivered = False
    delivery_via = None
    delivery_errors = []
    for channel_name, fn in (
        ("smtp",       _support_send_smtp),
        ("resend",     _support_send_resend),
        ("formsubmit", _support_send_formsubmit),
    ):
        try:
            sent, err = fn(subject, message, ticket)
        except Exception as e:
            sent, err = False, f"{channel_name}_uncaught: {type(e).__name__}: {e}"
        if sent:
            delivered = True
            delivery_via = channel_name
            print(f"[support] Delivered via {channel_name} (ticket {ticket['id']})")
            break
        if err and err != "not_configured":
            delivery_errors.append(f"{channel_name}: {err}")
    delivery_error = "; ".join(delivery_errors) if (delivery_errors and not delivered) else None
    if not delivered:
        print(f"[support] All channels failed for ticket {ticket['id']}: {delivery_error}")

    # 3) Update ticket with delivery outcome + which channel succeeded.
    try:
        db.support_tickets.update_one(
            {"id": ticket["id"]},
            {"$set": {
                "email_sent":   delivered,
                "email_via":    delivery_via,
                "email_error":  delivery_error,
            }},
        )
    except Exception:
        pass

    return {
        "ok": True,
        "ticket_id": ticket["id"],
        "delivered": delivered,
        # We deliberately don't surface the email_error to the client —
        # their ticket is safely stored regardless. The support team
        # can read errors via /api/admin/support/tickets.
    }


@app.get("/api/admin/support/tickets")
def list_support_tickets(
    limit: int = 50,
    token_data=Depends(require_role(["super_admin"])),
):
    """Admin-only view of recent support tickets so the platform team
    can triage even if email delivery is broken."""
    tickets = list(
        db.support_tickets
          .find({}, {"_id": 0})
          .sort("created_at", -1)
          .limit(max(1, min(int(limit or 50), 200)))
    )
    for t in tickets:
        if isinstance(t.get("created_at"), datetime):
            t["created_at"] = t["created_at"].isoformat()
    return {"tickets": tickets}


# ═══════════════════════════════════════════════════════════════════════
# PUSH-RECOVERY — keeping the notification loop alive
# ───────────────────────────────────────────────────────────────────────
# Three endpoints powering the 3 nudge strategies:
#   1. /api/owner/notifications/subscription-stats — KPI tile + filter
#   2. /api/owner/notifications/re-enablement — SMS campaign to non-subs
#   3. (notification-status on /api/card/{bc}/... lives in
#       push_subscriptions.py for the in-card banner)
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/owner/notifications/subscription-stats")
def notification_subscription_stats(token_data=Depends(require_role(["business_owner", "manager"]))):
    """Counts of subscribed vs not-subscribed customers for this tenant.
    Powers the 'Notification Enabled %' KPI tile and the Customers page filter."""
    t_id = token_data.tenant_id
    total = db.customers.count_documents({"tenant_id": t_id})
    if total == 0:
        return {"total": 0, "subscribed": 0, "not_subscribed": 0, "subscribed_pct": 0}
    # Get distinct customer_ids that have at least one push subscription.
    subscribed_ids = set()
    try:
        cursor = db.push_subscriptions.find({"tenant_id": t_id}, {"customer_id": 1})
        for s in cursor:
            cid = s.get("customer_id")
            if cid:
                subscribed_ids.add(cid)
    except Exception:
        pass
    subscribed = len(subscribed_ids)
    not_subscribed = max(0, total - subscribed)
    return {
        "total": total,
        "subscribed": subscribed,
        "not_subscribed": not_subscribed,
        "subscribed_pct": round((subscribed / total) * 100, 1) if total else 0,
    }


@app.get("/api/owner/notifications/subscription-map")
def notification_subscription_map(token_data=Depends(require_role(["business_owner", "manager"]))):
    """Returns {customer_id: True} for every customer in this tenant that
    has at least one active push subscription. Used by the CustomersPage
    filter to surface "Sans push" (not subscribed) segment quickly."""
    t_id = token_data.tenant_id
    out = {}
    try:
        cursor = db.push_subscriptions.find({"tenant_id": t_id}, {"customer_id": 1})
        for s in cursor:
            cid = s.get("customer_id")
            if cid:
                out[cid] = True
    except Exception:
        pass
    return {"map": out, "count": len(out)}


class ReEnablementRequest(BaseModel):
    message: Optional[str] = None  # Defaults to platform template if not set


@app.post("/api/owner/notifications/re-enablement")
def send_re_enablement_sms(
    req: ReEnablementRequest,
    token_data=Depends(require_role(["business_owner"])),
):
    """Sends an SMS to all customers without an active push subscription,
    encouraging them to enable notifications by re-opening their card.
    Returns counts so the frontend can show the result."""
    from services.sms import send_sms, is_configured as sms_configured
    if not sms_configured():
        raise HTTPException(status_code=400, detail="SMS not configured (Twilio env vars missing).")

    t_id = token_data.tenant_id
    tenant_doc = db.tenants.find_one({"id": t_id}) or {}
    biz_name = tenant_doc.get("name") or "votre boutique"
    slug = tenant_doc.get("slug") or ""
    # Build the URL the SMS will deep-link to. The card page reads the
    # `?notify=1` param and auto-triggers the notification permission flow.
    base = os.getenv("PUBLIC_APP_URL", "").rstrip("/") or "https://fidelitour-deploy.vercel.app"

    # Find subscribed customer IDs (to exclude) and the rest of customers.
    subscribed_ids = set()
    try:
        for s in db.push_subscriptions.find({"tenant_id": t_id}, {"customer_id": 1}):
            cid = s.get("customer_id")
            if cid:
                subscribed_ids.add(cid)
    except Exception:
        pass
    candidates = list(db.customers.find(
        {"tenant_id": t_id, "id": {"$nin": list(subscribed_ids)}},
        {"id": 1, "name": 1, "phone": 1, "barcode_id": 1},
    ))

    default_body = (
        f"Bonjour, {biz_name} a des offres exclusives pour vous, "
        "envoyées par notification. Activez-les en ouvrant votre carte: "
    )
    body_prefix = (req.message or default_body).strip()

    sent = 0
    skipped_no_phone = 0
    failed = []
    for c in candidates:
        phone = (c.get("phone") or "").strip()
        if not phone:
            skipped_no_phone += 1
            continue
        link = f"{base}/card/{c.get('barcode_id', '').upper()}?notify=1"
        body = f"{body_prefix} {link}"
        result = send_sms(phone, body)
        if result.get("sent"):
            sent += 1
        else:
            failed.append({"customer_id": c["id"], "error": result.get("error", "unknown")})

    # Estimated cost (informational).
    estimated_cost_eur = round(sent * 0.06, 2)
    return {
        "targeted": len(candidates),
        "sent": sent,
        "skipped_no_phone": skipped_no_phone,
        "failed_count": len(failed),
        "estimated_cost_eur": estimated_cost_eur,
    }


@app.post("/api/reset-seed")
def reset_and_reseed():
    """Drop all collections and re-seed fresh data. Use for demo resets."""
    global _seeded
    try:
        db.users.delete_many({})
        db.tenants.delete_many({})
        db.customers.delete_many({})
        db.visits.delete_many({})
        db.campaigns.delete_many({})
        db.card_templates.delete_many({})
        db.ai_queries.delete_many({})
        _seeded = False
        mock_seed_data()
        _seeded = True
        return {"status": "ok", "message": "Database reset and re-seeded successfully"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# ========================
# AUTH ENDPOINTS
# ========================

@app.post("/api/auth/register")
def register(payload: Dict[str, Any]):
    """Self-serve registration for a business owner (or customer).

    Accepts the standard email/password/role plus OPTIONAL business fields:
      - business_name : displayed everywhere ("Café Lumière", etc.)
      - sector        : café, restaurant, pizzeria, spa, gym, autre…
      - phone         : business phone, used by SMS and Twilio test bench
      - postal_code   : populates the geo helpers + city autodetect
      - owner_name    : free-form display name for the owner

    All optional — if the client sends just email + password it still works
    (with a slug-derived tenant name) so the old simple form keeps working.
    """
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    role = (payload.get("role") or "business_owner").strip()
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    # S3 — password policy. Enforced server-side because the browser can be
    # bypassed, and this account will eventually hold financial data.
    from services import password_policy
    password_policy.assert_valid(password)

    existing = db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Only customers and business_owners can self-register.
    if role not in ("customer", "business_owner"):
        raise HTTPException(status_code=403, detail="This role cannot self-register")

    tenant_id = None
    if role == "business_owner":
        tenant_id = str(uuid.uuid4())

        # Business display name + slug. Prefer the business_name the form sends;
        # fall back to the email local-part so old clients keep working.
        biz_name = (payload.get("business_name") or "").strip()
        if not biz_name:
            biz_name = email.split("@")[0].replace(".", " ").replace("-", " ").title()
        # URL-safe slug from the chosen name
        raw_slug = re.sub(r"[^a-z0-9]+", "-", biz_name.lower()).strip("-") or "shop"
        # Avoid slug collision with existing tenants
        slug = raw_slug
        n = 2
        while db.tenants.find_one({"slug": slug}):
            slug = f"{raw_slug}-{n}"
            n += 1

        # Every new business starts on the Silver plan with a free trial.
        # subscription_status='trialing' is the signal every UI surface uses
        # to show the trial countdown + upgrade nudge. trial_started_at +
        # trial_duration_days (read from the plan's PLAN_TRIAL_DAYS, which
        # admins can override) drive the days-left math everywhere.
        starting_plan = "silver"
        trial_days = get_plan_features(starting_plan).get("trial_duration_days", 21)
        now_utc = datetime.now(timezone.utc)
        t = Tenant(
            id=tenant_id,
            slug=slug,
            name=biz_name,
            plan=starting_plan,
            sector=(payload.get("sector") or None),
            phone=(payload.get("phone") or ""),
            address="",
        )
        tenant_doc = t.model_dump()
        tenant_doc["subscription_status"] = "trialing"
        tenant_doc["trial_started_at"] = now_utc
        tenant_doc["trial_duration_days"] = int(trial_days)
        tenant_doc["trial_ends_at"] = now_utc + timedelta(days=int(trial_days))
        # Stamp postal_code + owner_name as extras so they're easy to surface in Settings
        if payload.get("postal_code"):
            tenant_doc["postal_code"] = payload["postal_code"]
        if payload.get("owner_name"):
            tenant_doc["owner_name"] = payload["owner_name"]
        db.tenants.insert_one(tenant_doc)

    new_user = UserInDB(
        email=email,
        role=role,
        tenant_id=tenant_id,
        hashed_password=hash_password(password),
    )
    db.users.insert_one(new_user.model_dump())
    return {"message": "Success", "tenant_id": tenant_id}

@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response, request: Request = None):
    user_dict = db.users.find_one({"email": req.email})
    if not user_dict:
        log_audit("auth.login_failed", actor=req.email, actor_type="user",
                  request=request, meta={"reason": "unknown_email"})
        raise HTTPException(status_code=400, detail="Incorrect credentials")

    user = UserInDB(**user_dict)
    if not verify_password(req.password, user.hashed_password):
        log_audit("auth.login_failed", actor=req.email, actor_type="user",
                  tenant_id=user.tenant_id, request=request,
                  meta={"reason": "bad_password"})
        raise HTTPException(status_code=400, detail="Incorrect credentials")

    log_audit("auth.login", actor=user.email, actor_type="user",
              tenant_id=user.tenant_id, request=request,
              meta={"role": user.role})

    access_token = create_access_token(data={"sub": user.email, "role": user.role, "tenant_id": user.tenant_id})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=True,
        path="/"
    )
    return {"access_token": access_token, "role": user.role}

@app.get("/api/auth/me")
def get_me(token_data: TokenData = Depends(get_current_user_data)):
    return {"email": token_data.email, "role": token_data.role, "tenant_id": token_data.tenant_id}

@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"message": "Logged out"}

# ========================
# ADMIN ENDPOINTS
# ========================

@app.get("/api/admin/env-status")
def admin_env_status(token_data: TokenData = Depends(require_role(["super_admin"]))):
    """Reports which environment variables are configured and which features
    will silently no-op without them. Used by the super-admin dashboard to
    show a "Setup checklist" — way more useful than discovering 6 weeks
    later that push has been silently broken.

    Never returns the actual key values, only boolean presence flags.
    """
    checks = [
        {
            "key": "MONGODB_URI", "present": bool(MONGODB_URI),
            "feature": "Database", "required": True,
            "consequence": "App won't start at all without this.",
        },
        {
            "key": "JWT_SECRET", "present": bool(os.environ.get("JWT_SECRET", "")),
            "feature": "Authentication", "required": True,
            "consequence": (
                "Falls back to the signing key committed to the public repo — "
                "anyone reading it can forge a super_admin token. "
                "Fix: openssl rand -hex 32 -> Vercel env JWT_SECRET -> redeploy."
            ),
        },
        {
            # VAPID_SUBJECT is a contact URI, not a secret — it travels in
            # clear inside every push JWT. Showing the value here is the only
            # way to check it: Vercel hides the value of any variable marked
            # "Sensitive", so the dashboard cannot answer "which address did
            # I set?". Changing it is safe — subscriptions are bound to the
            # public key, never to the subject.
            "key": "VAPID_SUBJECT",
            "present": bool(os.environ.get("VAPID_SUBJECT", "")),
            "value": os.environ.get("VAPID_SUBJECT", "") or "(unset — defaults to mailto:contact@fidelitour.fr)",
            "feature": "Web Push — contact address sent to Apple/Google/Mozilla",
            "required": False,
            "consequence": (
                "Push still works on the built-in default. Set it to a real "
                "address you read: push providers use it to reach you if your "
                "sends start failing or get flagged."
            ),
        },
        {
            "key": "VAPID_PUBLIC_KEY + VAPID_PRIVATE_KEY",
            "present": bool(os.environ.get("VAPID_PUBLIC_KEY", "")) and bool(os.environ.get("VAPID_PRIVATE_KEY", "")),
            "feature": "Web Push notifications", "required": False,
            "consequence": "Push toggles in the wallet card silently fail. Run `npm run setup-env` to generate keys.",
        },
        {
            "key": "CRON_SECRET", "present": bool(CRON_SECRET),
            "feature": "Daily auto-campaign preparation", "required": False,
            "consequence": "Cron endpoints are unauthenticated (anyone can trigger them). Set this in Vercel — Vercel Cron passes it automatically.",
        },
        {
            "key": "ANTHROPIC_API_KEY",
            "present": bool(ANTHROPIC_API_KEY),
            "value": f"model: {ANTHROPIC_MODEL}" if ANTHROPIC_API_KEY else "(unset)",
            "feature": "AI quality — Claude runs FIRST in both the text and vision chains",
            "required": False,
            "consequence": (
                "Falls through to the free tiers (NVIDIA/Groq/OpenRouter/Gemini). "
                "Those prove a feature is wired up but not that its output is "
                "shippable. Set ANTHROPIC_MODEL to claude-haiku-4-5 for cheap "
                "bulk paths, claude-sonnet-5 (default) for quality judgement."
            ),
        },
        {
            "key": "NVIDIA_API_KEY or GROQ_API_KEY or OPENROUTER_API_KEY or GEMINI_API_KEY",
            "present": bool(NVIDIA_API_KEY or GROQ_API_KEY or OPENROUTER_API_KEY or GEMINI_API_KEY),
            "feature": "AI insights, AI campaign analyzer, voice-to-campaign",
            "required": False,
            "consequence": "AI tabs render a 'configure a provider' state. Pick any free tier: NVIDIA NIM (https://build.nvidia.com), Groq (https://console.groq.com/keys), OpenRouter (https://openrouter.ai/keys), or Gemini (https://aistudio.google.com/apikey). Chain tries NVIDIA → Groq → OpenRouter → Gemini in order.",
        },
        {
            "key": "TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_FROM_NUMBER",
            "present": bool(os.environ.get("TWILIO_ACCOUNT_SID", "")) and bool(os.environ.get("TWILIO_AUTH_TOKEN", "")) and bool(os.environ.get("TWILIO_FROM_NUMBER", "")),
            "feature": "SMS campaigns", "required": False,
            "consequence": "SMS sends are no-op'd silently; campaigns still work over push.",
        },
        {
            "key": "STRIPE_SECRET_KEY + STRIPE_WEBHOOK_SECRET",
            "present": bool(os.environ.get("STRIPE_SECRET_KEY", "")) and bool(os.environ.get("STRIPE_WEBHOOK_SECRET", "")),
            "feature": "Subscription billing", "required": False,
            "consequence": "Tenants cannot subscribe; billing UI is hidden. All tenants are treated as 'active' for now.",
        },
    ]
    overall_ok = all(c["present"] for c in checks if c["required"])
    return {
        "overall_ok": overall_ok,
        "checks": checks,
        "deployment_id": os.environ.get("VERCEL_DEPLOYMENT_ID", "local"),
        "region": os.environ.get("VERCEL_REGION", "local"),
    }


@app.get("/api/admin/tenants")
def get_all_tenants(token_data: TokenData = Depends(require_role(["super_admin"]))):
    tenants = list(db.tenants.find({"is_active": {"$ne": False}}))

    # Bulk per-tenant rollups via aggregation — keeps this endpoint at ~3 round
    # trips total instead of one count() per tenant. Without these the
    # frontend table reads `t.total_visits` undefined for every row, which is
    # why every business was being flagged "Inactive" with 0.0 avg points.
    visits_by_tenant = {
        doc["_id"]: doc["count"]
        for doc in db.visits.aggregate([
            {"$group": {"_id": "$tenant_id", "count": {"$sum": 1}}}
        ])
        if doc.get("_id")
    }
    cust_stats_by_tenant = {
        doc["_id"]: doc
        for doc in db.customers.aggregate([
            {"$group": {
                "_id": "$tenant_id",
                "count": {"$sum": 1},
                "total_points": {"$sum": "$points"},
                "total_amount_paid": {"$sum": "$total_amount_paid"},
            }}
        ])
        if doc.get("_id")
    }

    # "Active" = had ≥1 visit in the last 30 days. Computed once here rather
    # than re-derived on the client from total_visits > 0, which mis-flagged
    # tenants whose visits all predated the rolling window.
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    active_tenant_ids = set(db.visits.distinct(
        "tenant_id",
        {"created_at": {"$gte": thirty_days_ago}}
    ))

    result = []
    for t in tenants:
        t.pop("_id", None)
        tid = t["id"]
        cust = cust_stats_by_tenant.get(tid) or {}
        cust_count = int(cust.get("count", 0) or 0)
        total_points = float(cust.get("total_points", 0) or 0)
        t["customer_count"] = cust_count
        t["total_visits"] = int(visits_by_tenant.get(tid, 0) or 0)
        t["avg_points_per_customer"] = round(total_points / cust_count, 1) if cust_count else 0.0
        t["total_revenue"] = round(float(cust.get("total_amount_paid", 0) or 0), 2)
        t["is_active_30d"] = tid in active_tenant_ids
        result.append(t)

    return result

@app.post("/api/admin/tenants")
def create_tenant(
    req: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Create new tenant with generated business owner account"""
    tenant_id = str(uuid.uuid4())
    slug = req.get("slug", req.get("name", "").lower().replace(" ", "-"))

    tenant = Tenant(
        id=tenant_id,
        slug=slug,
        name=req.get("name", "New Tenant"),
        plan=req.get("plan", "basic"),
        address=req.get("address", ""),
        phone=req.get("phone", ""),
        website=req.get("website", "")
    )
    db.tenants.insert_one(tenant.model_dump())

    # Create business owner account
    owner_email = req.get("owner_email", f"owner-{slug}@fidelitour-generated.com")
    generated_password = str(uuid.uuid4())[:12]

    owner_user = UserInDB(
        email=owner_email,
        role="business_owner",
        tenant_id=tenant_id,
        hashed_password=hash_password(generated_password)
    )
    db.users.insert_one(owner_user.model_dump())

    return {
        "tenant": tenant.model_dump(),
        "owner": {
            "email": owner_email,
            "password": generated_password,
            "message": "Store these credentials securely"
        }
    }

@app.put("/api/admin/tenants/{tenant_id}")
def update_tenant(
    tenant_id: str,
    req: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Update tenant details"""
    update_data = {}
    if "name" in req:
        update_data["name"] = req["name"]
    if "plan" in req:
        update_data["plan"] = req["plan"]
    if "address" in req:
        update_data["address"] = req["address"]
    if "phone" in req:
        update_data["phone"] = req["phone"]
    if "website" in req:
        update_data["website"] = req["website"]

    result = db.tenants.update_one({"id": tenant_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant = db.tenants.find_one({"id": tenant_id})
    tenant.pop("_id", None)
    return tenant

@app.delete("/api/admin/tenants/{tenant_id}")
def delete_tenant(
    tenant_id: str,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Soft delete tenant"""
    result = db.tenants.update_one({"id": tenant_id}, {"$set": {"is_active": False}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return {"message": "Tenant disabled"}


# ============================================================
# ADMIN PLAN LIMITS — DB-backed overrides for PLAN_FEATURES
#
# Admins use these endpoints to raise / lower limits on any plan
# without redeploying. They also see how many tenants are on each
# plan and how close those tenants are to their current cap. The
# `/api/join` enforcement, AI quota, and multi-branch checks all
# pick up the new value on the next request — no cache to bust.
#
# To change a single tenant's plan, super-admins use the existing
# PUT /api/admin/tenants/{tenant_id} endpoint with {"plan": "vip"}.
# ============================================================

class PlanOverrideReq(BaseModel):
    """Editable plan limit fields. Send only the ones you want to override.

    Pass an empty dict (or omit fields) to fall back to the hardcoded
    baseline for that field. Pass `null` for a field to explicitly clear
    its override (back to baseline).
    """
    max_customers: Optional[int] = None
    campaigns_per_month: Optional[int] = None
    ai_queries_per_day: Optional[int] = None
    csv_export: Optional[bool] = None
    geo_proximity: Optional[bool] = None
    multi_branch: Optional[bool] = None
    trial_duration_days: Optional[int] = None
    trial_reminder_days_before: Optional[int] = None
    price: Optional[int] = None


def _plan_row(plan: str) -> Dict[str, Any]:
    """Build the row the admin UI renders for one plan: baseline vs effective."""
    plan = _canonical_plan(plan)
    # Build the full baseline shape, including trial + price fields, so the
    # UI can render a uniform table for the 3 plans.
    baseline = dict(PLAN_FEATURES.get(plan) or {})
    baseline["trial_duration_days"] = PLAN_TRIAL_DAYS.get(plan, 21)
    baseline["trial_reminder_days_before"] = TRIAL_REMINDER_DAYS_BEFORE
    baseline["price"] = PLAN_PRICES.get(plan, 0)
    effective = get_plan_features(plan)
    # Diff so the UI can show which fields are overridden vs default.
    overrides = {k: effective.get(k) for k in _PLAN_LIMIT_FIELDS
                 if k in baseline and baseline.get(k) != effective.get(k)}
    # How many tenants are on this plan (active in the last 30d). Counts BOTH
    # canonical `plan` matches AND legacy plan names that map onto this one
    # (e.g. silver also counts old "basic" tenants).
    legacy_matches = [k for k, v in _LEGACY_PLAN_MAP.items() if v == plan]
    plan_filter = {"plan": {"$in": [plan] + legacy_matches}} if legacy_matches else {"plan": plan}
    tenant_count = 0
    try:
        tenant_count = db.tenants.count_documents({**plan_filter, "is_active": {"$ne": False}})
    except Exception:
        pass
    return {
        "plan": plan,
        "price": effective.get("price"),
        "baseline": baseline,
        "effective": effective,
        "overrides": overrides,
        "tenant_count": tenant_count,
    }


@app.get("/api/admin/plans")
def admin_list_plans(token_data: TokenData = Depends(require_role(["super_admin"]))):
    """Return the 3 canonical plans (silver/gold/vip) with their baseline,
    effective (post-override) values, a diff of what's overridden, and how
    many tenants are on each plan."""
    return {"plans": [_plan_row(p) for p in CANONICAL_PLANS]}


@app.put("/api/admin/plans/{plan}")
def admin_update_plan(
    plan: str,
    req: PlanOverrideReq,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Upsert per-plan limit overrides. Pass null on any field to clear that
    field's override and fall back to the hardcoded baseline."""
    plan = _canonical_plan(plan)
    if plan not in PLAN_FEATURES:
        raise HTTPException(status_code=400, detail=f"Unknown plan '{plan}'")

    # Build the new overrides dict: fields explicitly set to a value override,
    # fields explicitly set to null clear the override, fields omitted from
    # the request preserve whatever was already saved.
    existing = (db.plan_settings.find_one({"plan": plan}) or {}).get("overrides", {}) or {}
    body = req.model_dump(exclude_unset=True)  # only fields the caller actually sent
    new_overrides = dict(existing)
    for k, v in body.items():
        if v is None:
            new_overrides.pop(k, None)
        else:
            new_overrides[k] = v

    db.plan_settings.update_one(
        {"plan": plan},
        {
            "$set": {
                "plan": plan,
                "overrides": new_overrides,
                "updated_at": datetime.now(timezone.utc),
                "updated_by": token_data.email,
            }
        },
        upsert=True,
    )
    log_audit("admin.plan_update", actor=token_data.email, actor_type="user",
              target=plan, meta={"overrides": new_overrides})
    return _plan_row(plan)


@app.get("/api/admin/audit-logs")
def admin_list_audit_logs(
    limit: int = 100,
    action: Optional[str] = None,
    tenant_id: Optional[str] = None,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """RGPD accountability trail. Filterable by action prefix (e.g. 'gdpr.')
    and tenant. Newest first, capped at 500 rows per call."""
    q = {}
    if action:
        q["action"] = {"$regex": f"^{re.escape(action)}"}
    if tenant_id:
        q["tenant_id"] = tenant_id
    limit = max(1, min(int(limit or 100), 500))
    rows = []
    for r in db.audit_logs.find(q).sort("ts", -1).limit(limit):
        r.pop("_id", None)
        if isinstance(r.get("ts"), datetime):
            r["ts"] = r["ts"].isoformat()
        rows.append(r)
    return {"logs": rows, "count": len(rows)}


# ============================================================
# TRIAL STATUS — surfaces the trial countdown to the owner UI.
#
# The dashboard's BillingBanner calls this on every page load; when
# days_left enters the reminder window (<=3 days by default), it
# escalates from a quiet pill to a full "your trial is ending — pick a
# plan" banner. When days_left <= 0, the trial is expired and the UI
# locks paid features until they upgrade.
# ============================================================

def _compute_trial_state(tenant: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the trial countdown for a tenant. Pure / side-effect-free.

    Returns a dict the owner UI consumes:
      is_in_trial          → bool, true while subscription_status='trialing'
      days_left            → int, days until trial_ends_at (negative if expired)
      hours_left           → int, finer granularity for the last day
      trial_ends_at        → ISO 8601 datetime string
      reminder_window      → bool, true if days_left <= reminder_days_before
      is_expired           → bool, true if days_left <= 0
      plan                 → canonical plan name
      plan_price           → euros / month
      reminder_days_before → cutoff from PLAN_FEATURES
    """
    plan = _canonical_plan(tenant.get("plan"))
    features = get_plan_features(plan)
    status = (tenant.get("subscription_status") or "").lower()
    trial_ends_at = tenant.get("trial_ends_at")
    # Legacy tenants (no trial_ends_at field): derive it from created_at +
    # the plan's trial_duration_days so the countdown still makes sense.
    if not trial_ends_at and tenant.get("created_at"):
        try:
            base = tenant["created_at"]
            if isinstance(base, str):
                base = datetime.fromisoformat(base.replace("Z", "+00:00"))
            trial_ends_at = base + timedelta(days=int(features.get("trial_duration_days", 21)))
        except Exception:
            trial_ends_at = None

    now_utc = datetime.now(timezone.utc)
    days_left = None
    hours_left = None
    is_expired = False
    if trial_ends_at:
        if isinstance(trial_ends_at, str):
            try:
                trial_ends_at = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
            except Exception:
                trial_ends_at = None
    if trial_ends_at:
        # Ensure UTC for the math.
        if trial_ends_at.tzinfo is None:
            trial_ends_at = trial_ends_at.replace(tzinfo=timezone.utc)
        delta = trial_ends_at - now_utc
        days_left = int(delta.total_seconds() // 86400)
        hours_left = int(delta.total_seconds() // 3600)
        is_expired = delta.total_seconds() <= 0

    reminder_days = int(features.get("trial_reminder_days_before", TRIAL_REMINDER_DAYS_BEFORE))
    in_reminder = (days_left is not None and 0 < days_left <= reminder_days)

    return {
        "is_in_trial": status == "trialing" and not is_expired,
        "is_expired": status == "trialing" and is_expired,
        "subscription_status": status or "unknown",
        "days_left": days_left,
        "hours_left": hours_left,
        "trial_ends_at": trial_ends_at.isoformat() if trial_ends_at else None,
        "trial_duration_days": int(features.get("trial_duration_days", 21)),
        "reminder_window": in_reminder,
        "reminder_days_before": reminder_days,
        "plan": plan,
        "plan_price": features.get("price"),
        "available_plans": [
            {
                "plan": p,
                "price": get_plan_features(p).get("price"),
                "max_customers": get_plan_features(p).get("max_customers"),
                "ai_queries_per_day": get_plan_features(p).get("ai_queries_per_day"),
                "geo_proximity": get_plan_features(p).get("geo_proximity"),
            }
            for p in CANONICAL_PLANS
        ],
    }


@app.get("/api/owner/trial-status")
def owner_trial_status(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Returns the current trial countdown for the logged-in owner's tenant.

    The UI (BillingBanner + Settings) polls this on dashboard load and uses
    the values to render: a discreet pill while there's >3 days left, a
    full warning banner inside the reminder window (≤3 days), and a
    blocking modal once `is_expired` flips to true.
    """
    tenant = db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _compute_trial_state(tenant)


@app.post("/api/owner/upgrade-plan")
def owner_upgrade_plan(
    body: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Self-serve plan switch (no Stripe — for testing or when Stripe isn't
    configured). Owner picks silver/gold/vip; we flip their plan and mark
    the subscription active. With Stripe configured, the proper flow is
    /api/billing/checkout in api/features/billing.py — this endpoint is
    the no-Stripe fallback so the UI is testable end-to-end."""
    target = _canonical_plan(body.get("plan"))
    if target not in CANONICAL_PLANS:
        raise HTTPException(status_code=400, detail="Pick silver, gold, or vip.")
    now_utc = datetime.now(timezone.utc)
    db.tenants.update_one(
        {"id": token_data.tenant_id},
        {"$set": {
            "plan": target,
            "subscription_status": "active",
            "subscription_started_at": now_utc,
            # Keep the original trial dates for record-keeping; just flip status.
        }},
    )
    tenant = db.tenants.find_one({"id": token_data.tenant_id})
    return _compute_trial_state(tenant)


@app.get("/api/admin/tenants/{tenant_id}/details")
def get_tenant_details(
    tenant_id: str,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Get detailed tenant info with customer stats"""
    tenant = db.tenants.find_one({"id": tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.pop("_id", None)

    # Customer stats
    customer_count = db.customers.count_documents({"tenant_id": tenant_id})
    visit_count = db.visits.count_documents({"tenant_id": tenant_id})

    # Tier distribution
    tier_dist = {}
    for tier in ["bronze", "silver", "gold"]:
        count = db.customers.count_documents({"tenant_id": tenant_id, "tier": tier})
        tier_dist[tier] = count

    tenant["stats"] = {
        "total_customers": customer_count,
        "total_visits": visit_count,
        "tier_distribution": tier_dist,
        "monthly_revenue": PLAN_PRICES.get(tenant["plan"], 0)
    }

    return tenant

@app.get("/api/admin/tenants/{tenant_id}/customers")
def admin_get_tenant_customers(
    tenant_id: str,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Admin: list all customers of a specific tenant."""
    tenant = db.tenants.find_one({"id": tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    customers = list(db.customers.find({"tenant_id": tenant_id}))
    for c in customers:
        c.pop("_id", None)
    return customers

@app.get("/api/admin/tenants/{tenant_id}/analytics")
def admin_get_tenant_analytics(
    tenant_id: str,
    days: int = 30,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Admin: full analytics snapshot for a specific tenant (mirrors owner analytics)."""
    tenant = db.tenants.find_one({"id": tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=days)

    total_customers = db.customers.count_documents({"tenant_id": tenant_id})
    total_visits_period = db.visits.count_documents({
        "tenant_id": tenant_id,
        "visit_time": {"$gte": period_start}
    })
    all_visits = db.visits.count_documents({"tenant_id": tenant_id})

    # Tier distribution
    tier_dist = {t: db.customers.count_documents({"tenant_id": tenant_id, "tier": t}) for t in ["bronze", "silver", "gold"]}

    # Revenue (sum amount_paid)
    revenue_pipeline = [
        {"$match": {"tenant_id": tenant_id}},
        {"$group": {"_id": None, "total": {"$sum": "$amount_paid"}}}
    ]
    rev = list(db.visits.aggregate(revenue_pipeline))
    total_revenue = rev[0]["total"] if rev else 0.0

    # Top spenders
    top_spenders = list(db.customers.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "tier": 1, "total_amount_paid": 1, "visits": 1}
    ).sort("total_amount_paid", -1).limit(5))

    # Top visitors
    top_visitors = list(db.customers.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "tier": 1, "total_amount_paid": 1, "visits": 1}
    ).sort("visits", -1).limit(5))

    # Acquisition-source breakdown — only 4 permitted sources, no friend/other
    ALLOWED_SOURCES = {"qr_store", "instagram", "facebook", "tiktok", "website"}
    acq_pipeline = [
        {"$match": {"tenant_id": tenant_id, "acquisition_source": {"$in": list(ALLOWED_SOURCES)}}},
        {"$group": {"_id": "$acquisition_source", "count": {"$sum": 1}}}
    ]
    acq_breakdown = {r["_id"]: r["count"] for r in db.customers.aggregate(acq_pipeline)}

    # Visits per day over the period
    visits_by_day = {}
    for v in db.visits.find({"tenant_id": tenant_id, "visit_time": {"$gte": period_start}}):
        day_key = v["visit_time"].strftime("%Y-%m-%d")
        visits_by_day[day_key] = visits_by_day.get(day_key, 0) + 1

    # Cards filled
    cards_filled = db.customers.count_documents({"tenant_id": tenant_id, "pass_issued": True})

    tenant.pop("_id", None)

    return {
        "tenant": {"id": tenant["id"], "name": tenant["name"], "plan": tenant["plan"], "slug": tenant.get("slug")},
        "period_days": days,
        "total_customers": total_customers,
        "total_visits_period": total_visits_period,
        "total_visits_all_time": all_visits,
        "total_revenue": round(total_revenue, 2),
        "tier_distribution": tier_dist,
        "top_spenders": top_spenders,
        "top_visitors": top_visitors,
        "acquisition_breakdown": acq_breakdown,
        "visits_by_day": visits_by_day,
        "cards_filled": cards_filled,
    }

@app.get("/api/admin/card-template/{tenant_id}")
def get_card_template_admin(
    tenant_id: str,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Get card template for a tenant (admin only)"""
    t = db.card_templates.find_one({"tenant_id": tenant_id})
    if t:
        t.pop("_id", None)
        return t
    return CardTemplate(tenant_id=tenant_id).model_dump()

@app.post("/api/admin/card-template/{tenant_id}")
def save_card_template_admin(
    tenant_id: str,
    req: CardTemplate,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Save card template for a tenant (admin only). Mirrors the owner-side
    save: snapshots old rules, writes new ones, and runs a retroactive
    notification sweep when the rules got more permissive."""
    req.tenant_id = tenant_id
    payload = req.model_dump()

    old_tpl = db.card_templates.find_one({"tenant_id": tenant_id}) or {}
    old_threshold = int(old_tpl.get("reward_threshold_stamps", 10) or 10)
    old_notify = int(old_tpl.get("notify_before_reward", 1) or 1)

    db.card_templates.update_one({"tenant_id": tenant_id}, {"$set": payload}, upsert=True)

    new_threshold = max(int(payload.get("reward_threshold_stamps", 10) or 10), 1)
    new_notify    = max(int(payload.get("notify_before_reward", 1) or 1), 0)
    new_approach  = max(0, new_threshold - new_notify)

    if new_threshold < old_threshold or new_notify > old_notify:
        visits_per_stamp = max(int(payload.get("visits_per_stamp", 1) or 1), 1)
        candidates = list(db.customers.find(
            {"tenant_id": tenant_id, "visits": {"$gte": new_approach * visits_per_stamp}}
        ))
        for cust in candidates:
            try:
                _evaluate_reward_state_and_notify(cust, tenant_id)
            except Exception as e:
                print(f"Reward eval failed for {cust.get('id')}: {e}")

    return payload

@app.put("/api/owner/settings/geo")
def update_owner_geo_settings(
    req: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Owner-controlled subset of geo settings.
    Owners can adjust radius / cooldown / on-off for their own tenant.
    `vip_geo_only` stays admin-only — owners can't escalate audience scope.
    """
    update_data: Dict[str, Any] = {}
    if "geo_enabled" in req:
        update_data["geo_enabled"] = bool(req["geo_enabled"])
    if "geo_radius_meters" in req:
        try:
            r = int(req["geo_radius_meters"])
            update_data["geo_radius_meters"] = max(50, min(r, 2000))
        except Exception:
            pass
    if "geo_cooldown_days" in req:
        try:
            c = int(req["geo_cooldown_days"])
            update_data["geo_cooldown_days"] = max(1, min(c, 30))
        except Exception:
            pass
    if not update_data:
        raise HTTPException(status_code=400, detail="No editable field provided")
    db.tenants.update_one({"id": token_data.tenant_id}, {"$set": update_data})
    tenant = db.tenants.find_one({"id": token_data.tenant_id})
    if tenant:
        tenant.pop("_id", None)
    return tenant or {}


@app.put("/api/admin/tenants/{tenant_id}/geo")
def update_geo_settings(
    tenant_id: str,
    req: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Update geo settings for a tenant. SUPER ADMIN ONLY.

    Accepts:
      - geo_enabled (bool)         — master switch for proximity pushes
      - geo_radius_meters (int)    — push range around a branch
      - geo_cooldown_days (int)    — min days between pushes per customer
      - vip_geo_only (bool)        — restrict proximity pushes to VIP tier only
                                     (owners CANNOT change this — admin-only)
    """
    update_data = {}
    if "geo_enabled" in req:
        update_data["geo_enabled"] = bool(req["geo_enabled"])
    if "geo_radius_meters" in req:
        update_data["geo_radius_meters"] = req["geo_radius_meters"]
    if "geo_cooldown_days" in req:
        update_data["geo_cooldown_days"] = req["geo_cooldown_days"]
    if "vip_geo_only" in req:
        update_data["vip_geo_only"] = bool(req["vip_geo_only"])

    result = db.tenants.update_one({"id": tenant_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant = db.tenants.find_one({"id": tenant_id})
    tenant.pop("_id", None)
    return tenant

@app.get("/api/admin/analytics")
def get_admin_analytics(token_data: TokenData = Depends(require_role(["super_admin"]))):
    """Admin analytics dashboard"""
    tenant_count = db.tenants.count_documents({"is_active": {"$ne": False}})
    customer_count = db.customers.count_documents({})
    visit_count = db.visits.count_documents({})

    # Calculate monthly revenue
    tenants = list(db.tenants.find({"is_active": {"$ne": False}}))
    monthly_revenue = sum(PLAN_PRICES.get(t.get("plan"), 0) for t in tenants)

    # Active tenants in last 30 days. Intersect with the active-tenants set
    # so we never count a visit whose tenant_id refers to a deactivated or
    # deleted tenant — that's how we previously got "22 active out of 21
    # total" (an orphan tenant_id in db.visits).
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    active_ids = {t["id"] for t in tenants}
    visited_recently = set(db.visits.distinct(
        "tenant_id",
        {"created_at": {"$gte": thirty_days_ago}}
    ))
    active_count = len(visited_recently & active_ids)

    return {
        "total_tenants": tenant_count,
        "total_customers": customer_count,
        "total_visits": visit_count,
        "monthly_revenue": monthly_revenue,
        "active_tenants_30d": active_count
    }

@app.get("/api/admin/detailed-analytics")
def get_admin_detailed_analytics(token_data: TokenData = Depends(require_role(["super_admin"]))):
    """Enhanced admin analytics — platform-wide aggregates across ALL tenants.
    Uses MongoDB aggregation to stay at ~3 round-trips total (instead of 1 per tenant)."""
    tenants = list(db.tenants.find({"is_active": {"$ne": False}}))
    all_customers = list(db.customers.find({}))

    # ONE aggregation for per-tenant visit counts (vs one count per tenant)
    visits_by_tenant = {
        doc["_id"]: doc["count"]
        for doc in db.visits.aggregate([
            {"$group": {"_id": "$tenant_id", "count": {"$sum": 1}}}
        ])
    }
    all_visits_count = sum(visits_by_tenant.values())

    # --- Plans distribution (include chain) ---
    plan_counts = {"basic": 0, "gold": 0, "vip": 0, "chain": 0}
    for t in tenants:
        plan = t.get("plan", "basic")
        if plan in plan_counts:
            plan_counts[plan] += 1
    plans_distribution = [
        {"name": "Basic", "value": plan_counts["basic"]},
        {"name": "Gold", "value": plan_counts["gold"]},
        {"name": "VIP", "value": plan_counts["vip"]},
        {"name": "Chain", "value": plan_counts["chain"]},
    ]

    # --- Tier distribution across platform ---
    tier_counts = {"bronze": 0, "silver": 0, "gold": 0}
    for c in all_customers:
        t = (c.get("tier") or "bronze").lower()
        if t in tier_counts:
            tier_counts[t] += 1
    tier_distribution = [
        {"name": "Bronze", "value": tier_counts["bronze"]},
        {"name": "Silver", "value": tier_counts["silver"]},
        {"name": "Gold",   "value": tier_counts["gold"]},
    ]

    # --- Acquisition sources across platform ---
    # Only the 4 permitted sources — no 'friend', no 'other' bucket.
    ALLOWED_SOURCES = {"qr_store", "instagram", "facebook", "tiktok", "website"}
    acq_counts = {}
    for c in all_customers:
        src = c.get("acquisition_source")
        if src in ALLOWED_SOURCES:
            acq_counts[src] = acq_counts.get(src, 0) + 1
    acquisition_sources = [
        {"name": k.replace("_", " ").title(), "value": v, "raw": k}
        for k, v in sorted(acq_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]

    # --- GPS breakdown ---
    geo_enabled = sum(1 for t in tenants if t.get("geo_enabled"))
    gps_breakdown = [
        {"name": "GPS Enabled",  "value": geo_enabled},
        {"name": "GPS Disabled", "value": max(len(tenants) - geo_enabled, 0)},
    ]

    # --- Real growth: tenants created per month, last 6 months ---
    now = datetime.now(timezone.utc)
    growth = []
    for back in range(5, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=back * 30)).replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        cnt = sum(
            1 for t in tenants
            if t.get("created_at") and month_start <= t["created_at"] < next_month
        )
        growth.append({"month": month_start.strftime("%b"), "tenants": cnt, "iso": month_start.strftime("%Y-%m")})

    # --- Top & bottom performers (all in-memory, NO per-tenant DB calls) ---
    # Bucket customers by tenant ONCE
    customers_by_tenant = {}
    for c in all_customers:
        customers_by_tenant.setdefault(c.get("tenant_id"), []).append(c)

    perf = []
    for t in tenants:
        tid = t["id"]
        t_customers = customers_by_tenant.get(tid, [])
        cust_count = len(t_customers)
        total_visits = visits_by_tenant.get(tid, 0)
        total_rev = round(sum(c.get("total_amount_paid", 0) for c in t_customers), 2)
        avg_pts = round(sum(c.get("points", 0) for c in t_customers) / max(cust_count, 1), 1) if cust_count else 0
        perf.append({
            "id": tid,
            "name": t.get("name"),
            "plan": t.get("plan", "basic"),
            "customers": cust_count,
            "visits": total_visits,
            "revenue": total_rev,
            "avg_points": avg_pts,
            "geo_enabled": bool(t.get("geo_enabled")),
        })
    perf_sorted = sorted(perf, key=lambda x: x["visits"], reverse=True)

    # --- Platform totals ---
    total_revenue_month = sum(PLAN_PRICES.get(t.get("plan"), 0) for t in tenants)
    total_customer_spend = round(sum(c.get("total_amount_paid", 0) for c in all_customers), 2)

    return {
        "totals": {
            "tenants": len(tenants),
            "customers": len(all_customers),
            "visits": all_visits_count,
            "subscription_revenue_month": total_revenue_month,
            "customer_spend_all_time": total_customer_spend,
        },
        "plans_distribution": plans_distribution,
        "tier_distribution": tier_distribution,
        "acquisition_sources": acquisition_sources,
        "gps_breakdown": gps_breakdown,
        "growth": growth,
        "tenant_performance": perf_sorted,
    }

@app.get("/api/admin/tenants-by-plan/{plan}")
def get_tenants_by_plan(
    plan: str,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Get list of tenants for a specific plan tier"""
    if plan not in ["basic", "gold", "vip", "chain"]:
        raise HTTPException(status_code=400, detail="Invalid plan")

    tenants = list(db.tenants.find({"plan": plan, "is_active": {"$ne": False}}))

    result = []
    for t in tenants:
        t.pop("_id", None)
        customer_count = db.customers.count_documents({"tenant_id": t["id"]})
        total_visits = db.visits.count_documents({"tenant_id": t["id"]})
        t["customer_count"] = customer_count
        t["total_visits"] = total_visits
        # Calculate avg_points from customers
        customers = list(db.customers.find({"tenant_id": t["id"]}))
        avg_points = sum(c.get("points", c.get("visits", 0) * 10) for c in customers) / max(len(customers), 1) if customers else 0
        t["avg_points"] = round(avg_points, 1)
        result.append(t)

    return result

@app.get("/api/admin/tenants-by-tier/{tier}")
def get_tenants_by_tier(
    tier: str,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Rank tenants by how many customers they have at a given loyalty tier."""
    tier = tier.lower()
    if tier not in ["bronze", "silver", "gold"]:
        raise HTTPException(status_code=400, detail="Invalid tier")

    tenants = list(db.tenants.find({"is_active": {"$ne": False}}))
    out = []
    for t in tenants:
        t.pop("_id", None)
        tier_cust = db.customers.count_documents({"tenant_id": t["id"], "tier": tier})
        if tier_cust == 0:
            continue
        out.append({
            "id": t["id"],
            "name": t.get("name"),
            "plan": t.get("plan", "basic"),
            "tier_customer_count": tier_cust,
            "total_customers": db.customers.count_documents({"tenant_id": t["id"]}),
        })
    return sorted(out, key=lambda x: x["tier_customer_count"], reverse=True)

@app.get("/api/admin/tenants-by-acquisition/{source}")
def get_tenants_by_acquisition(
    source: str,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Rank tenants by how many customers they've acquired via a specific channel."""
    tenants = list(db.tenants.find({"is_active": {"$ne": False}}))
    out = []
    for t in tenants:
        t.pop("_id", None)
        cnt = db.customers.count_documents({"tenant_id": t["id"], "acquisition_source": source})
        if cnt == 0:
            continue
        out.append({
            "id": t["id"],
            "name": t.get("name"),
            "plan": t.get("plan", "basic"),
            "acquisition_count": cnt,
            "total_customers": db.customers.count_documents({"tenant_id": t["id"]}),
        })
    return sorted(out, key=lambda x: x["acquisition_count"], reverse=True)

@app.get("/api/admin/tenants-by-geo/{enabled}")
def get_tenants_by_geo(
    enabled: str,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """List tenants with geolocation enabled/disabled."""
    want_enabled = enabled.lower() in ("1", "true", "yes", "enabled", "on")
    tenants = list(db.tenants.find({"is_active": {"$ne": False}, "geo_enabled": want_enabled}))
    out = []
    for t in tenants:
        t.pop("_id", None)
        out.append({
            "id": t["id"],
            "name": t.get("name"),
            "plan": t.get("plan", "basic"),
            "customer_count": db.customers.count_documents({"tenant_id": t["id"]}),
            "total_visits": db.visits.count_documents({"tenant_id": t["id"]}),
            "geo_radius_meters": t.get("geo_radius_meters"),
        })
    return out

@app.get("/api/admin/tenants-by-month/{iso_month}")
def get_tenants_by_month(
    iso_month: str,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """List tenants created in a given month (format YYYY-MM)."""
    try:
        year, month = iso_month.split("-")
        year, month = int(year), int(month)
    except Exception:
        raise HTTPException(status_code=400, detail="iso_month must be YYYY-MM")

    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    next_month = (month_start + timedelta(days=32)).replace(day=1)

    tenants = list(db.tenants.find({
        "is_active": {"$ne": False},
        "created_at": {"$gte": month_start, "$lt": next_month}
    }))
    out = []
    for t in tenants:
        t.pop("_id", None)
        out.append({
            "id": t["id"],
            "name": t.get("name"),
            "plan": t.get("plan", "basic"),
            "customer_count": db.customers.count_documents({"tenant_id": t["id"]}),
            "created_at": t.get("created_at"),
        })
    return out

@app.post("/api/admin/ai-query")
def admin_ai_query(req: AIQueryRequest, token_data: TokenData = Depends(require_role(["super_admin"]))):
    """Mock admin AI assistant"""
    return {
        "reply": "Intel Suggestion: Based on analytics, consider upgrading underperforming tenants to Gold tier. Most growth is coming from the café sector. Would you like me to draft upgrade recommendations?",
        "mode": "mock"
    }

# ========================
# OWNER ENDPOINTS
# ========================

@app.get("/api/owner/tenant")
def get_tenant(token_data: TokenData = Depends(require_role(["business_owner", "manager", "staff"]))):
    """Return the tenant doc for whoever is authenticated. Available to all
    in-tenant roles so the sidebar can show "you are managing/working at X"
    — no more confusion when an owner has multiple tenants or a staff is
    in the wrong account."""
    t = db.tenants.find_one({"id": token_data.tenant_id})
    if t:
        t.pop("_id", None)
        # Ship the EFFECTIVE limits with the tenant. The dashboard used to
        # carry its own hardcoded {basic:500, gold:2000, vip:10000} table,
        # left over from a plan structure that no longer exists — so the
        # "objectif du plan" gauge showed a ceiling the backend does not
        # enforce, and silver (absent from that table) silently fell back to
        # 2000 while joining is actually blocked at 1000. This is computed by
        # the same get_plan_features() the enforcement uses, admin overrides
        # included, so the number on screen is the number that applies.
        try:
            t["plan_features"] = get_plan_features(t.get("plan"))
        except Exception as _e:
            print(f"get_tenant: plan_features failed: {_e}")
    return t

@app.put("/api/owner/tenant")
def update_tenant(req: Tenant, token_data: TokenData = Depends(require_role(["business_owner"]))):
    if req.id != token_data.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    db.tenants.update_one({"id": token_data.tenant_id}, {"$set": req.model_dump()})
    return req.model_dump()

@app.get("/api/owner/customers")
def list_customers(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    tier: Optional[str] = Query(None),
    tiers: Optional[str] = Query(None),       # CSV of tiers: "silver,gold,vip"
    min_visits: Optional[int] = Query(None),
    max_visits: Optional[int] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    min_avg_ticket: Optional[float] = Query(None),
    postal_code: Optional[str] = Query(None),
    postal_codes: Optional[str] = Query(None),  # CSV of postal codes
    city: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    sources: Optional[str] = Query(None),        # CSV of sources
    search: Optional[str] = Query(None),
    branch_id: Optional[str] = Query(None),
    has_wallet_pass: Optional[bool] = Query(None),
    active_30d: Optional[bool] = Query(None),
    created_within_days: Optional[int] = Query(None),
    cards_filled: Optional[bool] = Query(None),
    has_birthday_this_month: Optional[bool] = Query(None),
    redeemed_reward: Optional[bool] = Query(None),  # True → has redeemed at least once
    # Wallet-card state filters (mutually exclusive with each other but combinable with any other filter)
    wallet_state: Optional[str] = Query(None),       # 'active' | 'deleted' | 'never_added'
    # Loyalty rate buckets (driven by customer_status_config visits-per-month)
    loyalty_bucket: Optional[str] = Query(None),     # 'loyal' | 'regular'
    # Pre-built time-of-day segments. Resolves against db.visits timestamps.
    # "lunch"    → majority of visits between 11:00 and 14:30
    # "evening"  → majority of visits between 17:00 and 22:00
    # "weekend"  → majority on Sat/Sun
    # "weekday"  → majority on Mon-Fri
    time_segment: Optional[str] = Query(None),
    # Inactivity window filters — "about to lose" uses min=14 & max=29;
    # "inactive" uses min=30 (no upper bound).
    inactive_days_min: Optional[int] = Query(None),
    inactive_days_max: Optional[int] = Query(None),
):
    """List customers with advanced filtering. Supports branch filtering + click-to-drill segments from the dashboard."""
    # Make sure branch filtering actually returns rows for this tenant.
    if branch_id:
        _ensure_branch_assignments(token_data.tenant_id)
    query = {"tenant_id": token_data.tenant_id}

    # Tiers — either one ("?tier=gold") or many ("?tiers=silver,gold,vip")
    if tiers:
        tier_list = [t.strip().lower() for t in tiers.split(",") if t.strip()]
        if tier_list:
            query["tier"] = {"$in": tier_list}
    elif tier:
        query["tier"] = tier
    if min_visits is not None:
        query.setdefault("visits", {})["$gte"] = min_visits
    if max_visits is not None:
        query.setdefault("visits", {})["$lte"] = max_visits
    if min_amount is not None:
        query.setdefault("total_amount_paid", {})["$gte"] = min_amount
    if max_amount is not None:
        query.setdefault("total_amount_paid", {})["$lte"] = max_amount
    # Postal codes — one ("?postal_code=75001") or many ("?postal_codes=75001,75002")
    if postal_codes:
        pcs = [p.strip() for p in postal_codes.split(",") if p.strip()]
        if pcs:
            query["postal_code"] = {"$in": pcs}
    elif postal_code:
        query["postal_code"] = postal_code
    if city:
        # Case-insensitive partial city match — "par" → Paris
        query["city"] = {"$regex": city, "$options": "i"}
    # Acquisition sources — one or many
    if sources:
        src_list = [s.strip() for s in sources.split(",") if s.strip()]
        if src_list:
            query["acquisition_source"] = {"$in": src_list}
    elif source:
        query["acquisition_source"] = source
    if branch_id:
        # Multi-store: a customer "belongs to" a branch if they've ever visited
        # there — not just because their first scan happened there.
        ids_at_branch = _customer_ids_who_visited_branch(token_data.tenant_id, branch_id)
        if ids_at_branch:
            existing_ids = query.get("id")
            if isinstance(existing_ids, dict) and "$in" in existing_ids:
                # Intersect with any pre-existing id filter
                query["id"] = {"$in": [i for i in existing_ids["$in"] if i in set(ids_at_branch)]}
            else:
                query["id"] = {"$in": ids_at_branch}
        else:
            query["id"] = {"$in": []}     # no visits at this branch yet → empty list
    # Birthday in the current calendar month (owner-facing celebration segment)
    if has_birthday_this_month is True:
        query["birthday"] = {"$regex": f"^{datetime.now(timezone.utc).strftime('%m')}"}
    # Customers who've ever redeemed a reward
    if redeemed_reward is True:
        query["rewards_redeemed_count"] = {"$gte": 1}
    elif redeemed_reward is False:
        query["$or"] = (query.get("$or") or []) + [
            {"rewards_redeemed_count": {"$exists": False}},
            {"rewards_redeemed_count": {"$eq": 0}},
        ]
    if has_wallet_pass is True:
        query["pass_issued"] = True
    elif has_wallet_pass is False:
        query["pass_issued"] = {"$ne": True}
    # Wallet-card state — mutually exclusive 3-bucket split:
    #   active       → pass_issued True  AND  card_deleted_at unset
    #   deleted      → card_deleted_at set (regardless of pass_issued)
    #   never_added  → pass_issued NOT True  AND  card_deleted_at unset
    if wallet_state == 'active':
        query["pass_issued"] = True
        query["card_deleted_at"] = {"$exists": False}
    elif wallet_state == 'deleted':
        query["card_deleted_at"] = {"$exists": True, "$ne": None}
    elif wallet_state == 'never_added':
        query["pass_issued"] = {"$ne": True}
        query["card_deleted_at"] = {"$exists": False}
    if active_30d is True:
        query["last_visit_date"] = {"$gte": datetime.now(timezone.utc) - timedelta(days=30)}
    if created_within_days is not None and created_within_days > 0:
        query["created_at"] = {"$gte": datetime.now(timezone.utc) - timedelta(days=created_within_days)}
    # Inactivity window:
    #   inactive_days_min=30 → last_visit_date <= now-30d (OR never visited)
    #   inactive_days_min=14, inactive_days_max=29 → last_visit_date between 14–29 days ago
    if inactive_days_min is not None and inactive_days_min > 0:
        now_utc = datetime.now(timezone.utc)
        upper = now_utc - timedelta(days=inactive_days_min)
        lv = {"$lte": upper}
        if inactive_days_max is not None and inactive_days_max >= inactive_days_min:
            lv["$gte"] = now_utc - timedelta(days=inactive_days_max)
        query["last_visit_date"] = lv

    customers = list(db.customers.find(query))

    # "Cards filled" filter: a customer has filled at least one card (visits >= reward threshold)
    if cards_filled is True:
        tpl = db.card_templates.find_one({"tenant_id": token_data.tenant_id}) or {}
        reward_threshold = tpl.get("reward_threshold_stamps", 10)
        visits_per_stamp = tpl.get("visits_per_stamp", 1)
        needed = max(reward_threshold * visits_per_stamp, 1)
        customers = [c for c in customers if c.get("visits", 0) >= needed]

    # Loyalty-bucket filter — visits-per-month rate vs configured thresholds.
    # Loyal: rate >= loyal_visits_per_month
    # Regular: regular_visits_per_month <= rate < loyal_visits_per_month
    if loyalty_bucket in ('loyal', 'regular'):
        try:
            sc = db.customer_status_config.find_one({"tenant_id": token_data.tenant_id}) or {}
        except Exception:
            sc = {}
        loyal_min = int(sc.get("loyal_visits_per_month") or 4)
        regular_min = int(sc.get("regular_visits_per_month") or 2)
        now_utc = datetime.now(timezone.utc)
        def _vpm(c):
            ca = c.get("created_at")
            visits = int(c.get("visits") or 0)
            if not ca or visits <= 0:
                return 0.0
            days_since = max((now_utc - ca).days, 1)
            return visits * 30.0 / days_since
        if loyalty_bucket == 'loyal':
            customers = [c for c in customers if _vpm(c) >= loyal_min]
        else:
            customers = [c for c in customers if regular_min <= _vpm(c) < loyal_min]

    # Average ticket floor — for spotting "big basket" customers regardless of
    # visit count. Computed from (total_amount_paid / visits).
    if min_avg_ticket is not None and min_avg_ticket > 0:
        customers = [
            c for c in customers
            if (c.get("visits", 0) or 0) > 0 and
               (c.get("total_amount_paid", 0) or 0) / max(c.get("visits", 1), 1) >= min_avg_ticket
        ]

    # Time-of-day / day-of-week segmentation — resolved against each customer's
    # actual visit times. We fetch a mini visit-time histogram once and then
    # require that >= 50% of a customer's visits land in the chosen window.
    if time_segment:
        ts = (time_segment or "").strip().lower()
        cust_ids = [c.get("id") for c in customers if c.get("id")]
        if cust_ids and ts in {"lunch", "evening", "morning", "weekend", "weekday"}:
            # One aggregation: per-customer counts for {total, in_window}.
            # We build window-membership in Python to avoid dialect-specific
            # $expr gymnastics.
            dow_is_weekend = {1, 7}  # Mongo $dayOfWeek: 1=Sun, 7=Sat
            def in_window(dow, hour):
                if ts == "lunch":   return 11 <= hour <= 14
                if ts == "evening": return 17 <= hour <= 22
                if ts == "morning": return 6 <= hour <= 10
                if ts == "weekend": return dow in dow_is_weekend
                if ts == "weekday": return dow not in dow_is_weekend
                return False
            tally = {}  # customer_id -> [in_window_count, total_count]
            for row in db.visits.aggregate([
                {"$match": {"tenant_id": token_data.tenant_id, "customer_id": {"$in": cust_ids},
                            "visit_time": {"$ne": None}}},
                {"$project": {
                    "customer_id": 1,
                    "dow": {"$dayOfWeek": "$visit_time"},
                    "hour": {"$hour": "$visit_time"},
                }},
            ]):
                cid = row["customer_id"]
                t = tally.setdefault(cid, [0, 0])
                t[1] += 1
                if in_window(row.get("dow", 0), row.get("hour", -1)):
                    t[0] += 1
            def qualifies(cid):
                v = tally.get(cid)
                if not v or v[1] == 0:
                    return False
                return (v[0] / v[1]) >= 0.5 and v[1] >= 2  # need ≥ 2 visits to call a pattern
            customers = [c for c in customers if qualifies(c.get("id"))]

    # Client-side search filtering for name/email
    if search:
        search_lower = search.lower()
        customers = [c for c in customers if search_lower in c.get("name", "").lower() or search_lower in c.get("email", "").lower()]

    for c in customers:
        c.pop("_id", None)
    return customers

def _campaign_performance_rollup(t_id: str, c: Dict[str, Any]) -> Dict[str, Any]:
    """Item 22 — compute revenue + lift attributable to a single campaign.

    Logic in plain English:
      • attributed_visits = visits we already credited to this campaign in the
        15-day post-send window (already maintained on the doc).
      • avg_ticket        = tenant-wide average basket from total_amount_paid /
        total_visits across all customers.
      • revenue_attributed = attributed_visits × avg_ticket.
      • baseline_visits   = visits these same recipients made in the 15 days
        BEFORE the campaign was sent. That's the "what would have happened
        anyway" floor.
      • lift_visits       = attributed_visits - baseline_visits. Negative means
        the campaign didn't move the needle.
      • lift_pct          = lift_visits / baseline_visits.
    """
    out = {
        "attributed_visits": int(c.get("visits_from_campaign") or 0),
        "baseline_visits": 0,
        "lift_visits": 0,
        "lift_pct": 0,
        "revenue_attributed": 0,
        "avg_ticket": 0,
    }

    # Tenant-wide avg ticket — quick aggregate, fine to compute on every list call.
    try:
        agg = list(db.customers.aggregate([
            {"$match": {"tenant_id": t_id, "deleted_at": {"$exists": False}}},
            {"$group": {
                "_id": None,
                "total_paid": {"$sum": {"$ifNull": ["$total_amount_paid", 0]}},
                "total_visits": {"$sum": {"$ifNull": ["$visits", 0]}},
            }},
        ]))
        if agg and agg[0].get("total_visits"):
            out["avg_ticket"] = round(float(agg[0]["total_paid"]) / float(agg[0]["total_visits"]), 2)
    except Exception:
        pass

    out["revenue_attributed"] = round(out["attributed_visits"] * out["avg_ticket"], 2)

    # Baseline: visits by the same recipients in the 15 days BEFORE sent_at.
    sent_at = c.get("sent_at")
    recipient_ids = c.get("recipient_ids") or []
    if sent_at and recipient_ids:
        try:
            window_start = sent_at - timedelta(days=15)
            baseline = db.visits.count_documents({
                "tenant_id": t_id,
                "customer_id": {"$in": recipient_ids},
                "visit_time": {"$gte": window_start, "$lt": sent_at},
            })
            out["baseline_visits"] = int(baseline)
        except Exception:
            pass

    out["lift_visits"] = out["attributed_visits"] - out["baseline_visits"]
    if out["baseline_visits"] > 0:
        out["lift_pct"] = round(out["lift_visits"] / out["baseline_visits"] * 100, 1)
    elif out["attributed_visits"] > 0:
        # No prior visits but post-send activity → flag as net-new traffic
        out["lift_pct"] = None  # frontend renders as "net new"

    return out


@app.get("/api/owner/campaigns")
def list_campaigns(token_data: TokenData = Depends(require_role(["business_owner"]))):
    """List campaigns for tenant — each row gets a performance roll-up
    (attributed visits, baseline, lift, revenue) for item 22 cards."""
    t_id = token_data.tenant_id
    campaigns = list(db.campaigns.find({"tenant_id": t_id}))
    for c in campaigns:
        c.pop("_id", None)
        c["performance"] = _campaign_performance_rollup(t_id, c)
    return campaigns

@app.post("/api/owner/campaigns")
def create_campaign(
    req: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Create campaign for tenant"""
    # Normalize and validate the channel/source label if provided
    raw_source = (req.get("source") or "").strip().lower() or None
    # FidéliTour delivers via wallet push and email today. We keep the schema
    # tolerant of legacy / external channel labels, but the composer only
    # surfaces push + email + other to avoid promising channels we don't ship.
    ALLOWED_CAMPAIGN_SOURCES = {"push", "email", "other"}
    source = raw_source if raw_source in ALLOWED_CAMPAIGN_SOURCES else None
    # Accept either `message` (frontend convention) or `content` (canonical)
    body_content = req.get("content") or req.get("message") or ""
    campaign = Campaign(
        id=str(uuid.uuid4()),
        tenant_id=token_data.tenant_id,
        name=req.get("name", "New Campaign"),
        content=body_content,
        filters=req.get("filters", {}),
        status=req.get("status", "draft"),
        source=source,
        image_url=req.get("image_url") or None,
    )
    db.campaigns.insert_one(campaign.model_dump())
    return campaign.model_dump()

@app.put("/api/owner/campaigns/{campaign_id}")
def update_campaign(
    campaign_id: str,
    req: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Edit an existing campaign — only drafts are editable.

    Once a campaign is sent we lock the document so historical metrics
    (delivered_count, opens_unique, recipient_ids, etc.) can't be rewritten
    after the fact. Mutable fields on a draft: name, content, filters,
    source, image_url. Status is intentionally not editable here — sending
    happens through the dedicated /send endpoint which also recomputes
    targeted_count and delivered_count.
    """
    campaign_dict = db.campaigns.find_one({"id": campaign_id, "tenant_id": token_data.tenant_id})
    if not campaign_dict:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign_dict.get("status") != "draft":
        raise HTTPException(status_code=400, detail="Only draft campaigns can be edited")

    update_doc = {}
    if "name" in req:
        update_doc["name"] = (req.get("name") or "").strip() or "Untitled Campaign"
    # Accept either `message` (frontend convention) or `content` (canonical)
    if "content" in req or "message" in req:
        update_doc["content"] = req.get("content") or req.get("message") or ""
    if "filters" in req:
        update_doc["filters"] = req.get("filters") or {}
    if "source" in req:
        raw_source = (req.get("source") or "").strip().lower() or None
        ALLOWED_CAMPAIGN_SOURCES = {"push", "email", "other"}
        update_doc["source"] = raw_source if raw_source in ALLOWED_CAMPAIGN_SOURCES else None
    if "image_url" in req:
        # Empty string ⇒ user removed the image. Pass through as None.
        update_doc["image_url"] = req.get("image_url") or None

    if not update_doc:
        # Nothing to change — return the current state without touching storage.
        campaign_dict.pop("_id", None)
        return campaign_dict

    db.campaigns.update_one({"id": campaign_id}, {"$set": update_doc})
    refreshed = db.campaigns.find_one({"id": campaign_id})
    refreshed.pop("_id", None)
    return refreshed

@app.post("/api/owner/campaigns/{campaign_id}/send")
def send_campaign(
    campaign_id: str,
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Send campaign - mark as sent and record metrics"""
    campaign_dict = db.campaigns.find_one({"id": campaign_id, "tenant_id": token_data.tenant_id})
    if not campaign_dict:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign = Campaign(**campaign_dict)

    # Calculate targeted customers based on filters
    query = {"tenant_id": token_data.tenant_id}
    filters = campaign.filters

    if filters.get("tier"):
        query["tier"] = filters["tier"]
    if filters.get("min_visits"):
        query["visits"] = {"$gte": filters["min_visits"]}
    if filters.get("min_points"):
        query["points"] = {"$gte": filters["min_points"]}
    if filters.get("postal_code"):
        query["postal_code"] = filters["postal_code"]
    if filters.get("min_amount_paid"):
        query["total_amount_paid"] = {"$gte": filters["min_amount_paid"]}
    if filters.get("city"):
        query["city"] = filters["city"]
    # has_wallet_pass is intentionally ignored: the platform is wallet-only.

    targeted_count = db.customers.count_documents(query)

    # Update campaign
    campaign.status = "sent"
    campaign.sent_at = datetime.now(timezone.utc)
    campaign.targeted_count = targeted_count
    # Send real emails via SendGrid if configured. ALL campaign bodies run through
    # render_template() so {name}, {first_name}, {tier}, {points_to_next_reward},
    # {business_name} etc. substitute per-customer. Uses the shared send_email_to_customer
    # helper so all dispatch paths share the same branded wrapper.
    delivered = 0
    tenant = db.tenants.find_one({"id": token_data.tenant_id}) or {}
    tenant_name = tenant.get("campaign_sender_name") or tenant.get("name") or "Your Business"
    campaign_content_raw = campaign.content or campaign.name
    targeted_customers = list(db.customers.find(query))
    for cust in targeted_customers:
        try:
            rendered_body = render_template(campaign_content_raw, cust, tenant)
            rendered_subject = render_template(campaign.name, cust, tenant)
            # In-card feed first: the customer must find the offer when they
            # open their wallet card, whether or not the push reaches them.
            try:
                db.push_notifications.insert_one({
                    "customer_id": cust["id"],
                    "tenant_id": token_data.tenant_id,
                    "campaign_id": campaign.id,
                    "image_url": campaign.image_url,
                    "title": rendered_subject,
                    "body": rendered_body,
                    "type": "campaign",
                    "sent_at": campaign.sent_at,
                })
            except Exception as _e:
                print(f"Campaign card-feed write failed for {cust.get('id')}: {_e}")
            # Then the real push / SMS.
            if dispatch_to_customer(
                token_data.tenant_id, cust, rendered_subject, rendered_body,
                kind="campaign",
            )["sent"]:
                delivered += 1
        except Exception as e:
            print(f"Campaign send failure for {cust.get('id')}: {e}")

    campaign.delivered_count = delivered

    # Populate recipient_ids with customer IDs from targeted query
    targeted_customers = list(db.customers.find(query))
    campaign.recipient_ids = [c["id"] for c in targeted_customers]

    db.campaigns.update_one(
        {"id": campaign_id},
        {"$set": campaign.model_dump()}
    )

    return campaign.model_dump()

@app.post("/api/owner/campaigns/preview-segment")
def preview_campaign_segment(
    req: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Preview how many customers match campaign filters"""
    query = {"tenant_id": token_data.tenant_id}
    filters = req.get("filters", {})

    if filters.get("tier"):
        query["tier"] = filters["tier"]
    if filters.get("min_visits"):
        query["visits"] = {"$gte": filters["min_visits"]}
    if filters.get("min_points"):
        query["points"] = {"$gte": filters["min_points"]}
    if filters.get("postal_code"):
        query["postal_code"] = filters["postal_code"]
    if filters.get("min_amount_paid"):
        query["total_amount_paid"] = {"$gte": filters["min_amount_paid"]}
    if filters.get("city"):
        query["city"] = filters["city"]
    # has_wallet_pass intentionally ignored (wallet-only platform).

    count = db.customers.count_documents(query)
    return {"matching_customers": count}

class ScanRequest(BaseModel):
    barcode_id: str
    points: Optional[int] = None
    amount_paid: float = 0.0
    branch_id: Optional[str] = None  # branch where the scan happened
    # Optional product picker payload — list of { item_id, qty }. When
    # present, the server looks up each item in the tenant_catalog,
    # computes total = sum(qty * price), and OVERRIDES amount_paid with
    # that total. Prices in the request are ignored — server is the
    # source of truth, so a tampered client cannot inflate revenue.
    items: Optional[List[Dict[str, Any]]] = None


# ============================================================
# CATALOG — products and services the business sells. Owners enter this
# at signup (or anytime in Settings → Catalogue) and staff pick from it
# at scan time. The catalog is the source of truth for prices, so the
# scan endpoint can compute revenue without trusting client input.
#
# Storage shape:
#   db.tenant_catalog: {
#     tenant_id: "tenant-...",
#     items: [
#       { id: "uuid", name: "Café crème", price: 2.50, category: "Boisson" },
#       ...
#     ],
#     updated_at: datetime
#   }
# ============================================================
class CatalogItemReq(BaseModel):
    id: Optional[str] = None            # missing on new items
    name: str
    price: float
    category: Optional[str] = None

class CatalogReq(BaseModel):
    items: List[CatalogItemReq]


@app.get("/api/owner/catalog")
def get_owner_catalog(token_data: TokenData = Depends(require_role(["business_owner", "manager", "staff"]))):
    """Return the tenant's catalog. Staff need it to render the scan-page
    item picker; managers/owners use it for editing."""
    doc = db.tenant_catalog.find_one({"tenant_id": token_data.tenant_id})
    if not doc:
        return {"items": [], "updated_at": None}
    return {
        "items": doc.get("items", []),
        "updated_at": doc.get("updated_at"),
    }


@app.put("/api/owner/catalog")
def put_owner_catalog(
    req: CatalogReq,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Owner-only: replace the catalog. Server assigns UUIDs to new
    rows so the IDs are stable across edits."""
    cleaned: List[Dict[str, Any]] = []
    for raw in req.items:
        name = (raw.name or "").strip()
        if not name:
            continue
        if raw.price is None or raw.price < 0:
            raise HTTPException(status_code=400, detail=f"Prix invalide pour « {name} »")
        cleaned.append({
            "id": raw.id or str(uuid.uuid4()),
            "name": name,
            "price": round(float(raw.price), 2),
            "category": (raw.category or "").strip() or None,
        })
    db.tenant_catalog.update_one(
        {"tenant_id": token_data.tenant_id},
        {"$set": {
            "tenant_id": token_data.tenant_id,
            "items": cleaned,
            "updated_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    return {"status": "ok", "items": cleaned}


class CatalogParseMenuReq(BaseModel):
    """Owner uploads a photo of their printed menu (paper, blackboard,
    PDF page screenshot) and the server pipes it through a vision-
    capable LLM to extract a structured list of {name, price, category}.
    The owner can then review/edit before saving via PUT /catalog."""
    image_base64: str           # raw base64 (no data: prefix needed; we strip)
    mime: Optional[str] = None  # 'image/jpeg' / 'image/png' / 'image/webp'
    language: Optional[str] = 'fr'  # 'fr' | 'en' | 'ar' — biases the LLM


def _strip_data_url(b64: str) -> str:
    """Allow either a raw base64 string OR a `data:image/...;base64,XXXX`
    data URL — both forms come through depending on the frontend's
    encoder. Returns the bare base64 chunk."""
    if not b64:
        return ''
    if b64.startswith('data:'):
        comma = b64.find(',')
        if comma >= 0:
            return b64[comma + 1:]
    return b64


def _call_vision_anthropic(image_b64: str, mime: str, prompt: str) -> tuple:
    """Claude vision — used by the menu-photo → catalogue import.
    Returns (output_text_or_none, error_string), same contract as the others.
    """
    if not ANTHROPIC_API_KEY:
        return None, "ANTHROPIC_API_KEY not set"
    # Anthropic accepts only these four; anything else (heic from an iPhone,
    # a mislabelled upload) is rejected at the API rather than here, so pin
    # the media type to a supported value and let the model cope.
    media = (mime or "image/jpeg").lower()
    if media not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        media = "image/jpeg"
    try:
        import requests as _rq
        r = _rq.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_VISION_MODEL,
                "max_tokens": 1500,
                "temperature": 0.1,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": media, "data": image_b64,
                        }},
                        {"type": "text", "text": prompt},
                    ],
                }],
            },
            timeout=60,
        )
        if r.status_code >= 400:
            return None, f"anthropic HTTP {r.status_code}: {(r.text or '')[:200]}"
        blocks = r.json().get("content") or []
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text"), None
    except Exception as e:
        return None, f"anthropic error: {e}"


def _call_vision_nvidia(image_b64: str, mime: str, prompt: str) -> tuple:
    """NVIDIA NIM vision — OpenAI-compatible. Tries the Llama 3.2 11B vision
    model by default (free tier). Returns (output_text_or_none, error_string).
    """
    if not NVIDIA_API_KEY:
        return None, "NVIDIA_API_KEY not set"
    try:
        import requests as _rq
        model = os.environ.get("NVIDIA_VISION_MODEL", "meta/llama-3.2-11b-vision-instruct")
        r = _rq.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {NVIDIA_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime or 'image/jpeg'};base64,{image_b64}",
                        }},
                    ],
                }],
                "temperature": 0.1,
                "max_tokens": 1500,
            },
            timeout=45,
        )
        if r.status_code >= 400:
            body = (r.text or "")[:200]
            return None, f"nvidia HTTP {r.status_code}: {body}"
        return r.json().get("choices", [{}])[0].get("message", {}).get("content", ""), None
    except Exception as e:
        return None, f"nvidia error: {e}"


def _call_vision_groq(image_b64: str, mime: str, prompt: str) -> tuple:
    """Groq vision. Default model bumped to the current Llama 4 Scout vision
    model — the previous llama-3.2-11b-vision-preview default was deprecated
    by Groq months ago and silently returned errors, which the chain then
    mis-translated as "no provider configured".
    Returns (output_text_or_none, error_string).
    """
    if not GROQ_API_KEY:
        return None, "GROQ_API_KEY not set"
    try:
        import requests as _rq
        # Current Groq vision-capable models (as of 2026):
        #   meta-llama/llama-4-scout-17b-16e-instruct  ← good default
        #   meta-llama/llama-4-maverick-17b-128e-instruct
        # Owner can override via GROQ_VISION_MODEL env var.
        model = os.environ.get("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
        r = _rq.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime or 'image/jpeg'};base64,{image_b64}",
                        }},
                    ],
                }],
                "temperature": 0.1,
                "max_tokens": 1500,
            },
            timeout=45,
        )
        if r.status_code >= 400:
            body = (r.text or "")[:200]
            return None, f"groq HTTP {r.status_code}: {body}"
        return r.json().get("choices", [{}])[0].get("message", {}).get("content", ""), None
    except Exception as e:
        return None, f"groq error: {e}"


def _call_vision_openrouter(image_b64: str, mime: str, prompt: str) -> tuple:
    """OpenRouter — fallback. Returns (output_text_or_none, error_string)."""
    if not OPENROUTER_API_KEY:
        return None, "OPENROUTER_API_KEY not set"
    try:
        import requests as _rq
        model = os.environ.get("OPENROUTER_VISION_MODEL", "meta-llama/llama-3.2-11b-vision-instruct:free")
        r = _rq.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://fidelitour-deploy.vercel.app",
                "X-Title": "FidéliTour",
            },
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime or 'image/jpeg'};base64,{image_b64}",
                        }},
                    ],
                }],
                "temperature": 0.1,
                "max_tokens": 1500,
            },
            timeout=45,
        )
        if r.status_code >= 400:
            body = (r.text or "")[:200]
            return None, f"openrouter HTTP {r.status_code}: {body}"
        return r.json().get("choices", [{}])[0].get("message", {}).get("content", ""), None
    except Exception as e:
        return None, f"openrouter error: {e}"


@app.post("/api/owner/catalog/parse-menu")
def parse_menu_from_photo(
    req: CatalogParseMenuReq,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Vision-LLM OCR of a menu photo → structured catalog items.
    Falls back across configured providers; if all fail OR no provider
    is configured, returns a clear 503 the frontend can surface."""
    image_b64 = _strip_data_url(req.image_base64 or "")
    if not image_b64 or len(image_b64) < 100:
        raise HTTPException(status_code=400, detail="Image vide ou invalide.")

    lang_word = {'fr': 'french', 'en': 'english', 'ar': 'arabic'}.get((req.language or 'fr').lower(), 'french')
    prompt = (
        f"You are extracting menu items from a photo of a {lang_word} restaurant/cafe menu. "
        "Return ONLY a JSON array — no prose, no markdown fences. Each item in the array MUST "
        "have these fields: name (string), price (number in euros, no symbol), category (string, "
        "one of: Boisson, Pâtisserie, Repas, Snack, Dessert, Café, Autre). If the price is missing "
        "or unreadable, use 0. Translate item names into the original menu language. "
        "Skip section headers (e.g. 'Boissons', 'Desserts'). Skip allergen/ingredient notes. "
        "Example output: "
        "[{\"name\":\"Café crème\",\"price\":2.50,\"category\":\"Boisson\"},"
        "{\"name\":\"Pain au chocolat\",\"price\":1.50,\"category\":\"Pâtisserie\"}]"
    )

    # Vision provider chain. NVIDIA NIM first (the owner's primary key),
    # Groq next (current Llama 4 Scout vision), OpenRouter as last
    # fallback. Each helper now returns (output, error_string) so we can
    # surface the ACTUAL upstream error when every provider fails —
    # before, the message always read "no provider configured" even when
    # the real problem was a deprecated model or a 401 from a stale key.
    raw = None
    provider = None
    errors = []  # collected per-provider errors for the failure response
    for fn, label in [
        (_call_vision_anthropic,  'anthropic-vision'),
        (_call_vision_nvidia,     'nvidia-vision'),
        (_call_vision_groq,       'groq-vision'),
        (_call_vision_openrouter, 'openrouter-vision'),
    ]:
        out, err = fn(image_b64, req.mime or 'image/jpeg', prompt)
        if out:
            raw = out
            provider = label
            break
        if err:
            errors.append(f"[{label}] {err}")

    if not raw:
        # If no key at all is set, give the configure-a-provider message.
        # Otherwise (at least one key is set but all failed), surface the
        # actual upstream errors so the owner can see what's wrong (model
        # deprecated, rate limit, bad key, etc).
        any_key_set = bool(ANTHROPIC_API_KEY or NVIDIA_API_KEY or GROQ_API_KEY or OPENROUTER_API_KEY)
        if not any_key_set:
            msg = ("Aucun moteur de vision IA n'est configuré. Ajoutez ANTHROPIC_API_KEY, "
                   "NVIDIA_API_KEY, GROQ_API_KEY ou OPENROUTER_API_KEY sur Vercel et redéployez.")
        else:
            msg = ("Les fournisseurs de vision IA configurés ont tous échoué. "
                   "Détails : " + " | ".join(errors[:3] or ["unknown error"]))
        raise HTTPException(
            status_code=503,
            detail={
                "code": "vision_llm_unavailable",
                "message": msg,
                "errors": errors,
            },
        )

    # Strip code fences if the model wrapped its output in ```json ... ```
    text = raw.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline > 0:
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
    text = text.strip()

    # The model sometimes prefixes JSON with explanatory text; extract
    # the first balanced JSON array we can find.
    items: List[Dict[str, Any]] = []
    try:
        items = json.loads(text)
    except Exception:
        start = text.find('[')
        end = text.rfind(']')
        if start >= 0 and end > start:
            try:
                items = json.loads(text[start:end + 1])
            except Exception:
                items = []

    if not isinstance(items, list):
        raise HTTPException(
            status_code=502,
            detail="Le modèle a renvoyé une réponse non analysable. Réessayez ou éditez manuellement.",
        )

    # Normalise + clamp
    cleaned: List[Dict[str, Any]] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        name = str(raw_item.get('name') or '').strip()
        if not name:
            continue
        try:
            price = float(raw_item.get('price') or 0)
        except (TypeError, ValueError):
            price = 0.0
        category = str(raw_item.get('category') or '').strip() or None
        cleaned.append({
            'name': name[:80],
            'price': max(0.0, round(price, 2)),
            'category': category,
        })

    return {
        "status": "ok",
        "provider": provider,
        "items": cleaned,
        "count": len(cleaned),
    }


def _items_to_amount(tenant_id: str, items: Optional[List[Dict[str, Any]]]) -> tuple[float, List[Dict[str, Any]]]:
    """Resolve a [{item_id, qty}] list against the tenant catalog and
    return (total_amount, normalised_line_items). Ignores any client-sent
    prices — server is the price source of truth."""
    if not items:
        return 0.0, []
    doc = db.tenant_catalog.find_one({"tenant_id": tenant_id})
    catalog = {it["id"]: it for it in (doc.get("items") if doc else [])} if doc else {}
    total = 0.0
    lines: List[Dict[str, Any]] = []
    for row in items:
        item_id = str(row.get("item_id") or row.get("id") or "").strip()
        try:
            qty = int(row.get("qty") or 1)
        except (TypeError, ValueError):
            qty = 1
        if qty < 1 or not item_id or item_id not in catalog:
            continue
        cat_item = catalog[item_id]
        line_total = round(qty * float(cat_item.get("price") or 0), 2)
        total += line_total
        lines.append({
            "item_id": item_id,
            "name": cat_item.get("name"),
            "price": float(cat_item.get("price") or 0),
            "qty": qty,
            "line_total": line_total,
        })
    return round(total, 2), lines

@app.post("/api/owner/scan")
def scan_visit(
    req: ScanRequest,
    # Staff accounts exist SPECIFICALLY to run this endpoint. The owner + manager
    # can of course scan too.
    token_data: TokenData = Depends(require_role(["business_owner", "manager", "staff"])),
):
    """Scan visit — record timestamp and update customer.

    Top-level try/except below: catches any unhandled exception from the
    scan flow and returns a non-Vercel-boilerplate 500 with the actual
    error class + message + a short traceback. Without this, a crash here
    surfaces only as Vercel's generic 'A server error has occurred' which
    is impossible to debug remotely.
    """
    try:
        return _scan_visit_impl(req, token_data)
    except HTTPException:
        # Pre-existing intentional HTTP errors (404 tenant mismatch etc.) pass through.
        raise
    except Exception as _e:
        import traceback as _tb
        tb_short = "".join(_tb.format_exception(type(_e), _e, _e.__traceback__))[-600:]
        print(f"scan_visit CRASH:\n{tb_short}")
        raise HTTPException(
            status_code=500,
            detail=(
                f"Crash interne du scan: {type(_e).__name__}: {str(_e)[:120]}. "
                "Détail dans les logs Vercel."
            ),
        )


def _scan_visit_impl(req: "ScanRequest", token_data: "TokenData"):
    """MINIMAL fast-path scan — does the essentials inline, defers every
    optional side effect to a best-effort try/except so a single bad
    customer record can't 500 the till."""
    # Normalise the barcode the staff just typed: trim whitespace and uppercase
    # the FT-XXXX prefix, so "ft-c7eaa131  " and "FT-C7EAA131" both match.
    normalized_barcode = (req.barcode_id or "").strip().upper()

    cust = db.customers.find_one({"tenant_id": token_data.tenant_id, "barcode_id": normalized_barcode})
    if not cust:
        # Be diagnostic: distinguish "barcode doesn't exist anywhere" vs
        # "barcode exists but in a different tenant" so the staff knows
        # whether they're scanning a fake code or whether they're logged
        # into the wrong account. Show both tenant slugs so the user can
        # see the mismatch at a glance.
        elsewhere = db.customers.find_one({"barcode_id": normalized_barcode})
        if elsewhere:
            other_t = db.tenants.find_one({"id": elsewhere.get("tenant_id")}) or {}
            this_t = db.tenants.find_one({"id": token_data.tenant_id}) or {}
            raise HTTPException(
                status_code=404,
                detail=(
                    f"❌ Tenant mismatch. "
                    f"Cette carte ({normalized_barcode}) appartient à : "
                    f"\"{other_t.get('name', '?')}\" (slug: {other_t.get('slug', '?')}). "
                    f"Vous êtes connecté à : \"{this_t.get('name', '?')}\" "
                    f"(slug: {this_t.get('slug', '?')}). "
                    f"Le client doit s'inscrire via VOTRE lien (Settings → Lien d'inscription) "
                    f"pour que vous puissiez scanner sa carte."
                ),
            )
        raise HTTPException(
            status_code=404,
            detail=f"Aucun client trouvé avec le code '{normalized_barcode}'. Vérifiez le code-barres saisi (les caractères doivent correspondre exactement).",
        )

    # Read the customer as a plain dict — DO NOT pass through the pydantic
    # Customer model here. Older customer records may have None / missing
    # required fields (birthday, postal_code) which would make Customer(**cust)
    # raise a ValidationError that escapes everything and nukes the scan.
    cid = cust.get("id")
    previous_tier = (cust.get("tier") or "bronze").lower()
    current_visits = int(cust.get("visits") or 0)
    current_points = int(cust.get("points") or 0)
    current_paid = float(cust.get("total_amount_paid") or 0)

    # ── ONE-SHOT MIGRATION: heal customers broken by the old redemption
    # logic.
    # The old redemption endpoint decremented `visits` by the reward
    # threshold, which corrupted lifetime visits AND demoted tier on the
    # next scan. New redemption logic leaves visits intact and tracks
    # `visits_at_last_redemption` instead. Customers who redeemed BEFORE
    # the fix have a missing `visits_at_last_redemption` AND a deflated
    # `visits` count. Detect that situation and restore:
    #     visits_restored = visits + rewards_redeemed_count * threshold
    # so their tier comes back to where it should be on this scan.
    rewards_count = int(cust.get("rewards_redeemed_count") or 0)
    if rewards_count > 0 and cust.get("visits_at_last_redemption") is None:
        try:
            heal_tpl = db.card_templates.find_one({"tenant_id": token_data.tenant_id}) or {}
            heal_threshold = max(
                int(heal_tpl.get("reward_threshold_stamps", 10) or 10) *
                int(heal_tpl.get("visits_per_stamp", 1) or 1),
                1,
            )
            current_visits = current_visits + rewards_count * heal_threshold
            # Set visits_at_last_redemption to the restored count so
            # stamps display 0/threshold (they just "redeemed" all their
            # old cards). They'll start fresh from this scan.
            db.customers.update_one(
                {"id": cid},
                {"$set": {
                    "visits": current_visits,
                    "visits_at_last_redemption": current_visits,
                }},
            )
        except Exception:
            pass  # never let a heal failure block a real scan

    # If the scan came with a product-picker payload, resolve the items
    # against the tenant catalog and OVERRIDE amount_paid with the
    # server-computed total. We never trust client-sent prices.
    resolved_lines: List[Dict[str, Any]] = []
    if req.items:
        computed_amount, resolved_lines = _items_to_amount(token_data.tenant_id, req.items)
        # Only override if at least one item resolved — otherwise fall
        # back to the client-sent amount_paid so a typo in an item id
        # doesn't silently zero out the visit.
        if resolved_lines:
            req.amount_paid = computed_amount

    # Compute points to add — owner-controlled via card_template.points_mode.
    if req.points is not None:
        points_to_add = int(req.points)
    else:
        try:
            card_template = db.card_templates.find_one({"tenant_id": token_data.tenant_id}) or {}
        except Exception:
            card_template = {}
        mode = (card_template.get("points_mode") or "per_visit").lower()
        ppe = float(card_template.get("points_per_euro") or 10)
        ppv = int(card_template.get("points_per_visit", 10) or 10)
        if mode == "per_euro" and float(req.amount_paid or 0) > 0:
            points_to_add = int(round(ppe * float(req.amount_paid)))
        else:
            points_to_add = ppv

    new_visits = current_visits + 1
    new_points = current_points + points_to_add
    new_paid = current_paid + float(req.amount_paid or 0)
    avg_ticket = (new_paid / new_visits) if new_visits else 0
    if new_visits >= 40 or (new_visits >= 10 and avg_ticket >= 60):
        new_tier = "vip"
    elif new_visits >= 20:
        new_tier = "gold"
    elif new_visits >= 10:
        new_tier = "silver"
    else:
        new_tier = "bronze"

    update_set = {
        "visits": new_visits,
        "points": new_points,
        "total_amount_paid": round(new_paid, 2),
        "last_visit_date": datetime.now(timezone.utc),
        "tier": new_tier,
    }
    # Stamp home branch on first scan only.
    if req.branch_id and not cust.get("branch_id"):
        update_set["branch_id"] = req.branch_id

    # Update customer — must succeed.
    db.customers.update_one({"id": cid}, {"$set": update_set})

    # Insert visit row — must succeed for analytics.
    try:
        visit_doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": token_data.tenant_id,
            "customer_id": cid,
            "points_awarded": points_to_add,
            "amount_paid": float(req.amount_paid or 0),
            "visit_time": datetime.now(timezone.utc),
            "branch_id": req.branch_id or cust.get("branch_id"),
        }
        # Stamp the line items on the visit when a catalog-driven picker
        # was used. This is what powers the real "Top produits" panel
        # going forward (replacing the DEMO data in analyticsExtra.js).
        if resolved_lines:
            visit_doc["items"] = resolved_lines
        db.visits.insert_one(visit_doc)
    except Exception as _e:
        print(f"scan_visit: visit insert failed (non-fatal): {_e}")

    # ---- ALL OPTIONAL SIDE EFFECTS BELOW — wrapped, never block response ----
    # Campaign attribution (15-day window)
    try:
        now_utc = datetime.now(timezone.utc)
        window_start = now_utc - timedelta(days=15)
        attributable = db.campaigns.find({
            "tenant_id": token_data.tenant_id,
            "status": {"$in": ["sent", "delivered"]},
            "sent_at": {"$gte": window_start, "$lte": now_utc},
            "recipient_ids": cid,
            "attributed_visit_customer_ids": {"$ne": cid},
        })
        for camp in attributable:
            db.campaigns.update_one(
                {"id": camp["id"]},
                {"$inc": {"visits_from_campaign": 1},
                 "$addToSet": {"attributed_visit_customer_ids": cid}},
            )
    except Exception as _e:
        print(f"scan_visit: campaign attribution failed (non-fatal): {_e}")

    # Reward eval (near_reward / unlock pushes) — non-blocking.
    try:
        _evaluate_reward_state_and_notify({"id": cid}, token_data.tenant_id)
    except Exception as _e:
        print(f"scan_visit: reward evaluator failed (non-fatal): {_e}")

    # Build success response — tier-up flag for UI celebration.
    tier_rank = {"bronze": 0, "silver": 1, "gold": 2, "vip": 3}

    # Stamps-in-current-cycle math — the staff page used to compute
    # `stampsCurrent = floor(visits)` which, after the visits-never-reset
    # change, kept showing 12/10 / 13/10 etc and re-fired the reward
    # banner on every scan past the first redemption. Now the server
    # computes the right number (visits - visits_at_last_redemption,
    # capped at the threshold) and ships `stamps_in_cycle`,
    # `reward_threshold`, `reward_unlocked` so the frontend just renders.
    last_red_visits = int((db.customers.find_one({"id": cid}) or {}).get("visits_at_last_redemption") or 0)
    try:
        scan_tpl = db.card_templates.find_one({"tenant_id": token_data.tenant_id}) or {}
    except Exception:
        scan_tpl = {}
    reward_threshold = max(
        int(scan_tpl.get("reward_threshold_stamps", 10) or 10) *
        int(scan_tpl.get("visits_per_stamp", 1) or 1),
        1,
    )
    stamps_in_cycle = max(0, new_visits - last_red_visits)
    stamps_capped = min(stamps_in_cycle, reward_threshold)
    reward_unlocked = stamps_in_cycle >= reward_threshold

    # Notification subscription status — drives the staff scan-page prompt
    # ("This customer isn't receiving offers — show enable QR?"). We check
    # the push_subscriptions collection for any active row for this customer.
    notification_status = "subscribed"
    try:
        has_sub = db.push_subscriptions.count_documents({"customer_id": cid}) > 0
        notification_status = "subscribed" if has_sub else "not_subscribed"
    except Exception:
        notification_status = "unknown"

    return {
        "id": cid,
        "barcode_id": cust.get("barcode_id"),
        "name": cust.get("name", ""),
        "email": cust.get("email", ""),
        "visits": new_visits,
        "points": new_points,
        "total_amount_paid": round(new_paid, 2),
        "tier": new_tier,
        "previous_tier": previous_tier,
        "tier_upgraded": tier_rank.get(new_tier, 0) > tier_rank.get(previous_tier, 0),
        "branch_id": req.branch_id or cust.get("branch_id"),
        # Cycle-aware stamps math — the staff page renders these directly.
        "stamps_in_cycle":  stamps_capped,
        "reward_threshold": reward_threshold,
        "reward_unlocked":  reward_unlocked,
        "visits_at_last_redemption": last_red_visits,
        # Notification status — drives staff prompt to encourage enable.
        "notification_status": notification_status,
    }


def _cycle_start_for_customer(customer_id: str, tenant_id: str) -> Optional[datetime]:
    """The boundary that defines a customer's current 'card cycle' — the
    moment of their most recent reward redemption (or None if they've never
    redeemed). Notifications fired before this don't count for dedup."""
    last = db.rewards_redeemed.find_one(
        {"customer_id": customer_id, "tenant_id": tenant_id},
        sort=[("redeemed_at", -1)],
    )
    return last.get("redeemed_at") if last else None


def _has_recent_notification(customer_id: str, tenant_id: str, notif_type: str,
                              cycle_start: Optional[datetime]) -> bool:
    """Did this customer already get a notification of this type this cycle?"""
    q = {"customer_id": customer_id, "tenant_id": tenant_id, "type": notif_type}
    if cycle_start is not None:
        q["sent_at"] = {"$gt": cycle_start}
    return db.push_notifications.find_one(q) is not None


def _evaluate_reward_state_and_notify(customer_doc, tenant_id: str) -> Dict[str, Any]:
    """Compute the customer's current reward state, fire any missing
    near_reward / reward_unlocked notifications, and return what changed.

    Idempotent: calling twice in quick succession is safe — the second call
    sees the just-inserted notification and skips. This is what makes it safe
    to call from BOTH scan_visit (per scan) AND save_card_template (per save).

    Used by:
      • scan_visit — fires when a customer crosses thresholds via a real visit.
      • save_card_template — fires when the owner reduces threshold/notify_before,
        catching customers who were already past the new bar.
    """
    fired = {"near_reward": False, "reward_unlocked": False}

    # Re-fetch a fresh copy of the customer in case the caller passed a stale obj
    cid = customer_doc.id if hasattr(customer_doc, "id") else customer_doc.get("id")
    cust = db.customers.find_one({"id": cid, "tenant_id": tenant_id})
    if not cust:
        return fired

    card_template = db.card_templates.find_one({"tenant_id": tenant_id})
    if not card_template:
        return fired

    visits_per_stamp = max(int(card_template.get("visits_per_stamp", 1) or 1), 1)
    threshold_stamps = max(int(card_template.get("reward_threshold_stamps", 10) or 10), 1)
    notify_before    = max(int(card_template.get("notify_before_reward", 1) or 1), 0)
    reward_description = card_template.get("reward_description") or "Une récompense"

    visits = int(cust.get("visits", 0) or 0)
    stamps_earned = visits // visits_per_stamp
    approach_threshold = threshold_stamps - notify_before

    tenant_doc = db.tenants.find_one({"id": tenant_id}) or {}
    biz = tenant_doc.get("campaign_sender_name") or tenant_doc.get("name") or "votre boutique"
    first_name = (cust.get("name", "").split(" ")[0] or "").strip()

    cycle_start = _cycle_start_for_customer(cid, tenant_id)
    now = datetime.now(timezone.utc)

    # ---- "Almost there" push ----
    # Fires when the customer is currently in the approach window AND hasn't
    # received a near_reward push for this card cycle yet.
    if (notify_before > 0
        and approach_threshold <= stamps_earned < threshold_stamps
        and not _has_recent_notification(cid, tenant_id, "near_reward", cycle_start)):
        stamps_remaining = threshold_stamps - stamps_earned
        visits_remaining = stamps_remaining * visits_per_stamp
        if stamps_remaining == 1:
            title = f"Plus qu'une visite, {first_name} ! 🎁" if first_name else "Plus qu'une visite ! 🎁"
            body = (
                f"Encore {visits_remaining} visite{'s' if visits_remaining > 1 else ''} chez {biz} "
                f"et vous débloquez : {reward_description}. À très vite !"
            )
        else:
            title = f"Vous y êtes presque, {first_name} ! ✨" if first_name else "Vous y êtes presque ! ✨"
            body = (
                f"Plus que {stamps_remaining} tampons "
                f"({visits_remaining} visite{'s' if visits_remaining > 1 else ''}) "
                f"pour débloquer : {reward_description} chez {biz}."
            )
        db.push_notifications.insert_one({
            "customer_id": cid, "tenant_id": tenant_id,
            "title": title, "body": body, "type": "near_reward",
            "stamps_earned": stamps_earned, "stamps_for_reward": threshold_stamps,
            "stamps_remaining": stamps_remaining, "visits_remaining": visits_remaining,
            "sent_at": now,
        })
        fired["near_reward"] = True
        try:
            dispatch_to_customer(tenant_id, cust, title, body, kind="near_reward")
        except Exception:
            pass

    # ---- "Reward unlocked" push ----
    # Fires when the customer's current state is at-or-over the threshold AND
    # hasn't received an unlock push for this card cycle yet.
    if (stamps_earned >= threshold_stamps
        and not _has_recent_notification(cid, tenant_id, "reward_unlocked", cycle_start)):
        title = f"🎉 Récompense débloquée, {first_name} !" if first_name else "🎉 Récompense débloquée !"
        body = (
            f"Bravo, votre carte est complète ! Présentez ce message lors de votre prochaine "
            f"visite chez {biz} pour profiter de : {reward_description}."
        )
        db.push_notifications.insert_one({
            "customer_id": cid, "tenant_id": tenant_id,
            "title": title, "body": body, "type": "reward_unlocked",
            "stamps_earned": stamps_earned, "stamps_for_reward": threshold_stamps,
            "reward_description": reward_description,
            "sent_at": now,
        })
        fired["reward_unlocked"] = True
        try:
            dispatch_to_customer(tenant_id, cust, title, body, kind="reward_unlocked")
        except Exception:
            pass

    return fired

@app.get("/api/owner/card-template")
def get_card_template(token_data: TokenData = Depends(require_role(["business_owner"]))):
    t = db.card_templates.find_one({"tenant_id": token_data.tenant_id})
    if t:
        t.pop("_id", None)
        return t
    return CardTemplate(tenant_id=token_data.tenant_id).model_dump()

@app.post("/api/owner/card-template")
def save_card_template(req: CardTemplate, token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    req.tenant_id = tid
    # Keep show_meter and show_progress_meter in sync — older renderers read the latter.
    payload = req.model_dump()
    if "show_meter" in payload and "show_progress_meter" not in payload:
        payload["show_progress_meter"] = payload["show_meter"]

    # Snapshot the OLD rule values BEFORE writing — used to detect whether the
    # change made any customer newly eligible (threshold/notify dropped).
    old_tpl = db.card_templates.find_one({"tenant_id": tid}) or {}
    old_threshold = int(old_tpl.get("reward_threshold_stamps", 10) or 10)
    old_notify = int(old_tpl.get("notify_before_reward", 1) or 1)

    db.card_templates.update_one({"tenant_id": tid}, {"$set": payload}, upsert=True)

    # Retroactive notification sweep — only worth running when the rules
    # got *more permissive* (lower threshold, or earlier notify trigger).
    new_threshold = max(int(payload.get("reward_threshold_stamps", 10) or 10), 1)
    new_notify    = max(int(payload.get("notify_before_reward", 1) or 1), 0)
    new_approach  = max(0, new_threshold - new_notify)

    threshold_dropped = new_threshold < old_threshold
    notify_widened    = new_notify > old_notify
    if threshold_dropped or notify_widened:
        # Sweep candidates: customers who, given new rules, may now be in or
        # past the approach window. Anyone below new_approach can't be eligible
        # for either notification yet, so we skip them — keeps the sweep cheap.
        visits_per_stamp = max(int(payload.get("visits_per_stamp", 1) or 1), 1)
        candidates = list(db.customers.find(
            {"tenant_id": tid, "visits": {"$gte": new_approach * visits_per_stamp}}
        ))
        for cust in candidates:
            try:
                _evaluate_reward_state_and_notify(cust, tid)
            except Exception as e:
                # Sweep must never block the save, even if one customer's
                # email send fails or their record is malformed.
                print(f"Reward eval failed for {cust.get('id')}: {e}")

    return payload


# ---------------------------------------------------------------------------
# New card-designer endpoints: promotion, details, typed card notifications
# ---------------------------------------------------------------------------

@app.post("/api/owner/card-template/promotion")
def save_card_promotion(
    req: CardPromotion,
    notify: bool = Query(False),
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Save the promotion block that can replace the logo area on the card.

    If notify=true, emit a push notification ("Nouvelle offre sur votre carte")
    to every customer of this tenant so their card refreshes.
    """
    t_id = token_data.tenant_id
    promo_payload = req.model_dump()
    promo_payload["updated_at"] = datetime.now(timezone.utc)
    db.card_templates.update_one(
        {"tenant_id": t_id},
        {"$set": {"promotion": promo_payload, "tenant_id": t_id}},
        upsert=True,
    )

    sent = 0
    if notify and req.enabled:
        tenant_doc = db.tenants.find_one({"id": t_id}) or {}
        biz = tenant_doc.get("campaign_sender_name") or tenant_doc.get("name") or "votre boutique"
        now = datetime.now(timezone.utc)
        title = (req.title or "Nouvelle offre disponible").strip()
        body = (req.subtitle or req.body or "Ouvrez votre carte pour en savoir plus.").strip()
        cursor = db.customers.find({"tenant_id": t_id}, {"id": 1, "name": 1})
        rows = []
        for c in cursor:
            rows.append({
                "customer_id": c["id"],
                "tenant_id": t_id,
                "title": title,
                "body": body,
                "type": "promotion_update",
                "link": req.link,
                "sent_at": now,
                "sender_name": biz,
            })
        if rows:
            db.push_notifications.insert_many(rows)
            sent = len(rows)

    return {"promotion": promo_payload, "notified": sent}


@app.post("/api/owner/card-template/details")
def save_card_details(
    req: CardDetails,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Save the tap-to-expand details section (about / hours / address / ...)."""
    t_id = token_data.tenant_id
    payload = req.model_dump()
    db.card_templates.update_one(
        {"tenant_id": t_id},
        {"$set": {"details": payload, "tenant_id": t_id}},
        upsert=True,
    )
    return {"details": payload}


@app.post("/api/owner/card-notifications")
def send_card_notification(
    req: CardTypedNotification,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Send a typed push notification to this tenant's customers.

    Types: news | offer | flash_sale | voucher_expiry | event |
           order_status | safety | custom. Filters may narrow the audience:
      - tier: bronze | silver | gold
      - sector: matches tenant (noop here; owner endpoints are always tenant-scoped)
      - customer_ids: [..]  (specific recipients)
      - birthday_month: bool
    """
    t_id = token_data.tenant_id
    tenant_doc = db.tenants.find_one({"id": t_id}) or {}
    biz = tenant_doc.get("campaign_sender_name") or tenant_doc.get("name") or "votre boutique"

    flt: Dict[str, Any] = {"tenant_id": t_id}
    f = req.filters or {}
    if f.get("tier"):
        flt["tier"] = (f["tier"] or "").lower()
    if f.get("customer_ids"):
        flt["id"] = {"$in": list(f["customer_ids"])}
    if f.get("birthday_month"):
        today = datetime.now(timezone.utc)
        mm = f"{today.month:02d}"
        flt["birthday"] = {"$regex": f"^{mm}-"}

    now = datetime.now(timezone.utc)
    rows = []
    # Every matching customer is a recipient — the old code only collected the
    # ones with an email address, on a platform where email is switched off.
    # The projection carries what render_template() and the SMS fallback need.
    recipients = []
    for c in db.customers.find(flt, {
        "id": 1, "tenant_id": 1, "name": 1, "email": 1, "phone": 1,
        "tier": 1, "points": 1, "visits": 1, "total_amount_paid": 1,
        "visits_at_last_redemption": 1,
    }):
        body_rendered = render_template(req.body, c, tenant_doc)
        title_rendered = render_template(req.title, c, tenant_doc)
        rows.append({
            "customer_id": c["id"],
            "tenant_id": t_id,
            "title": title_rendered,
            "body": body_rendered,
            "type": req.type,
            "link": req.link,
            "expires_at": req.expires_at,
            "sent_at": now,
            "sender_name": biz,
        })
        recipients.append((c, title_rendered, body_rendered))

    if rows:
        db.push_notifications.insert_many(rows)

    # Real delivery — push first, SMS fallback. Writing the row above only
    # puts the message in the card's inbox; without this loop the customer
    # never learns it arrived, which made flash sales useless.
    pushed = 0
    for c, title, body in recipients:
        try:
            if dispatch_to_customer(t_id, c, title, body, kind=req.type)["sent"]:
                pushed += 1
        except Exception:
            pass

    return {
        "sent": len(rows),          # written to the card inbox
        "delivered": pushed,        # actually reached a device
        "emails_sent": 0,           # email channel is disabled platform-wide
        "type": req.type,
        "title": req.title,
    }

def _customer_ids_who_visited_branch(tenant_id: str, branch_id: str) -> List[str]:
    """Returns every customer_id who has at least one visit at `branch_id`.

    This is the multi-store sharing primitive: a salon with 3 branches has ONE
    customer record per person (tenant-wide), but each branch wants to see
    'their' customers. A customer is 'a customer of branch B' if they've
    EVER visited branch B — not just because they happened to first scan there.

    Used by analytics endpoints / customer-list / map / alerts when filtering
    by a specific branch.
    """
    if not branch_id:
        return []
    cursor = db.visits.find(
        {"tenant_id": tenant_id, "branch_id": branch_id},
        {"customer_id": 1, "_id": 0},
    )
    seen = set()
    for v in cursor:
        cid = v.get("customer_id")
        if cid:
            seen.add(cid)
    return list(seen)


def _branch_customer_filter(tenant_id: str, branch_id: Optional[str]) -> dict:
    """Build a customer-collection MongoDB filter that respects 'visited at
    least once at this branch' semantics. Falls back to plain tenant filter
    when no branch is selected.

    ALWAYS excludes soft-deleted customers (those with `deleted_at` set by the
    purge tool). Use `_branch_customer_filter_with_trash` if you need to see
    them (the trash view).
    """
    base = {"tenant_id": tenant_id, "deleted_at": {"$exists": False}}
    if not branch_id:
        return base
    ids = _customer_ids_who_visited_branch(tenant_id, branch_id)
    if not ids:
        # No visits yet at this branch → return a filter that matches nothing
        # (so endpoints return empty lists rather than the whole tenant).
        return {**base, "id": {"$in": []}}
    return {**base, "id": {"$in": ids}}


# ════════════════════════════════════════════════════════════════════
# Owner-side customer cleanup — soft-delete inactive customers,
# restore from trash, hard-purge after a 30-day grace period.
# Item 31. Two-step confirm enforced on the frontend.
# ════════════════════════════════════════════════════════════════════

class PurgeInactiveRequest(BaseModel):
    days: int = 365            # threshold (days since last visit)
    dry_run: bool = True       # if True, only return what *would* be purged
    branch_id: Optional[str] = None
    include_never_visited: bool = False  # also include customers who never scanned


@app.post("/api/owner/customers/purge-inactive")
def purge_inactive_customers(
    req: PurgeInactiveRequest,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Soft-delete customers inactive for at least `days`.

    SOFT delete — sets `deleted_at` + `delete_reason`, hides them from every
    analytics + customer-list endpoint, but keeps the row so it can be restored
    within 30 days. After 30 days a separate cleanup hard-deletes them.

    Pass dry_run=true first to preview the count, then dry_run=false to commit.
    """
    t_id = token_data.tenant_id
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(int(req.days), 1))

    # Build the match: tenant + (optional branch) + inactive
    match: Dict[str, Any] = {
        "tenant_id": t_id,
        "deleted_at": {"$exists": False},  # don't double-delete
    }
    if req.branch_id:
        ids_at_branch = _customer_ids_who_visited_branch(t_id, req.branch_id)
        if not ids_at_branch:
            return {"would_delete": 0, "deleted": 0, "candidates": []}
        match["id"] = {"$in": ids_at_branch}

    # Inactive = last_visit_date older than cutoff. Optionally also include
    # never-visited (no last_visit_date and created_at older than cutoff).
    if req.include_never_visited:
        match["$or"] = [
            {"last_visit_date": {"$lt": cutoff}},
            {"$and": [
                {"last_visit_date": {"$exists": False}},
                {"created_at": {"$lt": cutoff}},
            ]},
            {"$and": [
                {"last_visit_date": None},
                {"created_at": {"$lt": cutoff}},
            ]},
        ]
    else:
        match["last_visit_date"] = {"$lt": cutoff}

    candidates = list(db.customers.find(
        match,
        {"id": 1, "name": 1, "phone": 1, "email": 1, "tier": 1,
         "visits": 1, "last_visit_date": 1, "_id": 0}
    ).limit(500))

    if req.dry_run:
        return {
            "would_delete": db.customers.count_documents(match),
            "deleted": 0,
            "candidates": candidates,
            "cutoff_date": cutoff.isoformat(),
            "grace_period_days": 30,
        }

    # Commit the soft delete
    result = db.customers.update_many(
        match,
        {"$set": {
            "deleted_at": now,
            "delete_reason": f"Inactive ≥ {req.days}d (purged by owner)",
            "delete_grace_until": now + timedelta(days=30),
        }},
    )
    return {
        "would_delete": 0,
        "deleted": result.modified_count,
        "grace_period_days": 30,
        "restorable_until": (now + timedelta(days=30)).isoformat(),
    }


@app.post("/api/owner/customers/{customer_id}/restore")
def restore_customer(
    customer_id: str,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Undo a soft-delete. Allowed any time within the 30-day grace window."""
    res = db.customers.update_one(
        {"id": customer_id, "tenant_id": token_data.tenant_id},
        {"$unset": {"deleted_at": "", "delete_reason": "", "delete_grace_until": ""}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"restored": True, "id": customer_id}


@app.get("/api/owner/customers/trash")
def list_trashed_customers(
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """List soft-deleted customers still within the 30-day grace window."""
    rows = list(db.customers.find(
        {"tenant_id": token_data.tenant_id, "deleted_at": {"$exists": True}},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "email": 1, "tier": 1,
         "visits": 1, "last_visit_date": 1, "deleted_at": 1, "delete_reason": 1,
         "delete_grace_until": 1},
    ))
    return {"trash": rows, "count": len(rows)}


def _ensure_branch_assignments(tid: str) -> None:
    """Make sure every customer and visit for this tenant has a valid `branch_id`.

    This is the single reason "All branches" shows real numbers but a specific
    branch shows 0 everywhere: customers are seeded without a branch_id, and
    public signups don't set one either. We deterministically hash each
    customer's id onto one of the tenant's branches so every customer belongs
    to exactly one real branch. Running again is a no-op — idempotent.

    Also re-fixes any customer whose branch_id doesn't match a current branch
    (stale value from a removed/renamed branch), so the fix survives edits.
    """
    tenant = db.tenants.find_one({"id": tid})
    if not tenant:
        return
    branches = tenant.get("branches") or []
    if not branches:
        return
    branch_ids = [b.get("id") for b in branches if b.get("id")]
    if not branch_ids:
        return
    valid_branch_ids = set(branch_ids)
    n = len(branch_ids)

    # Find customers that either (a) have no branch_id at all, or (b) have a
    # branch_id that doesn't correspond to any current branch. Both need fixing.
    needs_fix = list(db.customers.find(
        {"tenant_id": tid, "$or": [
            {"branch_id": None},
            {"branch_id": {"$exists": False}},
            {"branch_id": ""},
            {"branch_id": {"$nin": list(valid_branch_ids)}},
        ]},
        {"id": 1},
    ))
    if not needs_fix:
        # Still backfill visits whose branch_id is invalid, since visit records
        # are created separately and could drift.
        _backfill_visits_from_customers(tid, branch_ids)
        return

    for cust in needs_fix:
        cid = cust.get("id") or ""
        idx = (sum(ord(ch) for ch in cid) if cid else 0) % n
        target_branch = branch_ids[idx]
        db.customers.update_one({"id": cid}, {"$set": {"branch_id": target_branch}})
        # Mirror onto visits unconditionally — the customer's visits all happen
        # at the same "home" branch in this deterministic mapping.
        db.visits.update_many(
            {"tenant_id": tid, "customer_id": cid},
            {"$set": {"branch_id": target_branch}},
        )


def _backfill_visits_from_customers(tid: str, branch_ids: list) -> None:
    """Ensure every visit carries the same branch_id as its customer. Cheap
    post-check for drift; only touches visits with a missing/invalid branch_id."""
    valid = set(branch_ids)
    bad_visits = db.visits.find(
        {"tenant_id": tid, "$or": [
            {"branch_id": None},
            {"branch_id": {"$exists": False}},
            {"branch_id": ""},
            {"branch_id": {"$nin": list(valid)}},
        ]},
        {"customer_id": 1},
    )
    # Resolve per unique customer_id to keep it tight (~1 lookup per customer).
    seen = {}
    for v in bad_visits:
        cid = v.get("customer_id")
        if not cid or cid in seen:
            continue
        cust = db.customers.find_one({"id": cid}, {"branch_id": 1})
        bid = cust.get("branch_id") if cust else None
        if bid in valid:
            seen[cid] = bid
    for cid, bid in seen.items():
        db.visits.update_many(
            {"tenant_id": tid, "customer_id": cid},
            {"$set": {"branch_id": bid}},
        )


@app.get("/api/owner/analytics")
def owner_analytics(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    branch_id: Optional[str] = Query(None),
    period_days: Optional[int] = Query(None),
):
    """Comprehensive owner analytics.
    Uses MongoDB aggregation ($group by day/week/tier) so the whole response
    is computed in ~6 DB round-trips instead of 100+. This is the canonical
    numbers source — OwnerDashboard, AnalyticsPage, and Insights all agree.
    """
    t_id = token_data.tenant_id
    now = datetime.now(timezone.utc)
    ninety_days_ago = now - timedelta(days=90)
    twelve_weeks_ago = now - timedelta(weeks=12)

    # Ensure every customer and visit for this tenant has a branch_id, so that
    # the "By branch" filter shows real, non-overlapping slices instead of 0.
    _ensure_branch_assignments(t_id)

    # Branch-aware base filter. When branch_id is provided:
    #  - VISITS scope to that branch (one visit = one branch)
    #  - CUSTOMERS scope to "anyone who has ever visited that branch"
    #    (visit-derived membership rather than fixed home_branch).
    customer_filter = _branch_customer_filter(t_id, branch_id)
    visit_filter = {"tenant_id": t_id}
    if branch_id:
        visit_filter["branch_id"] = branch_id

    # --- Pull customers once (needed for repeat_rate, tiers, wallet count) ---
    customers = list(db.customers.find(
        customer_filter,
        {"tier": 1, "visits": 1, "pass_issued": 1}
    ))
    total_customers = len(customers)
    repeat_customers = sum(1 for c in customers if c.get("visits", 0) > 1)
    repeat_rate = (repeat_customers / total_customers * 100) if total_customers > 0 else 0
    wallet_passes_issued = sum(1 for c in customers if c.get("pass_issued"))

    tier_distribution = {"bronze": 0, "silver": 0, "gold": 0, "vip": 0}
    for c in customers:
        tier = (c.get("tier") or "bronze").lower()
        if tier in tier_distribution:
            tier_distribution[tier] += 1

    # --- Visits aggregated by day ($dateToString) — ONE round-trip ---
    visits_by_day = {}
    # Seed empty buckets so graph shows 0-days, not gaps
    for i in range(90):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        visits_by_day[d] = 0
    total_visits = 0
    heatmap_raw = []
    for doc in db.visits.aggregate([
        {"$match": visit_filter},
        {"$facet": {
            "total": [{"$count": "count"}],
            "by_day": [
                {"$match": {"visit_time": {"$gte": ninety_days_ago}}},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$visit_time"}},
                    "count": {"$sum": 1}
                }}
            ],
            "by_weekday_hour": [
                {"$match": {"visit_time": {"$ne": None}}},
                {"$project": {
                    # IMPORTANT: visit_time is stored in UTC, but the heatmap needs
                    # to read in the *shop's* local time. Hardcoded to Europe/Paris
                    # since this is a French platform — switch to a per-tenant
                    # timezone setting if non-FR shops onboard later.
                    "dow":  {"$dayOfWeek": {"date": "$visit_time", "timezone": "Europe/Paris"}},
                    "hour": {"$hour":      {"date": "$visit_time", "timezone": "Europe/Paris"}},
                }},
                {"$group": {"_id": {"dow": "$dow", "hour": "$hour"}, "count": {"$sum": 1}}}
            ]
        }}
    ]):
        total_visits = (doc.get("total") or [{"count": 0}])[0].get("count", 0) if doc.get("total") else 0
        for row in doc.get("by_day") or []:
            if row["_id"] in visits_by_day:
                visits_by_day[row["_id"]] = row["count"]
            else:
                visits_by_day[row["_id"]] = row["count"]
        heatmap_raw = doc.get("by_weekday_hour") or []

    # --- New customers aggregated by ISO week — ONE round-trip ---
    new_customers_by_week = {f"Week {i+1}": 0 for i in range(12)}
    week_filter = dict(customer_filter)
    week_filter["created_at"] = {"$gte": twelve_weeks_ago}
    for doc in db.customers.aggregate([
        {"$match": week_filter},
        {"$group": {
            "_id": {"$isoWeek": "$created_at"},
            "count": {"$sum": 1},
            "min_date": {"$min": "$created_at"}
        }},
        {"$sort": {"min_date": 1}}
    ]):
        pass  # we fill below by bucketing created_at distance from now
    # Bucket by weeks-back using already-loaded customers (small cost; already in memory elsewhere)
    week_customers = list(db.customers.find(
        week_filter,
        {"created_at": 1}
    ))
    for c in week_customers:
        ca = c.get("created_at")
        if not ca:
            continue
        weeks_back = int((now - ca).days // 7)
        if 0 <= weeks_back < 12:
            label = f"Week {12 - weeks_back}"
            new_customers_by_week[label] = new_customers_by_week.get(label, 0) + 1

    # --- Campaign performance (at most ~20 campaigns, fine to keep) ---
    # Campaigns aren't branch-scoped, but if a branch_id is set we leave
    # campaign performance empty so that UI doesn't misattribute totals.
    if branch_id:
        campaigns = []
    else:
        campaigns = list(db.campaigns.find({"tenant_id": t_id, "status": "sent"}))
    campaign_performance = [
        {
            "id": camp.get("id"),
            "name": camp.get("name", ""),
            "source": camp.get("source") or "push",
            "visits_after_send": camp.get("visits_from_campaign", 0),
            "delivered_count": camp.get("delivered_count", 0),
            "opens": camp.get("opens", 0),
            "opens_unique": camp.get("opens_unique", 0),
            "offer_clicks": camp.get("offer_clicks", 0),
            "sent_at": camp.get("sent_at"),
        }
        for camp in campaigns
    ]

    # --- Visit time heatmap from aggregation ---
    days_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hours = list(range(7, 20))
    visit_heatmap = {d: {str(h): 0 for h in hours} for d in days_labels}
    for row in heatmap_raw:
        # MongoDB dayOfWeek: 1=Sun, 2=Mon, ..., 7=Sat
        dow = row["_id"]["dow"]
        python_wd = (dow + 5) % 7  # convert to Mon=0..Sun=6
        day_name = days_labels[python_wd]
        h = row["_id"]["hour"]
        if 7 <= h < 20:
            visit_heatmap[day_name][str(h)] += row["count"]

    return {
        "total_customers": total_customers,
        "total_visits": total_visits,
        "repeat_rate": f"{repeat_rate:.1f}%",
        "repeat_rate_pct": round(repeat_rate, 1),
        "wallet_passes_issued": wallet_passes_issued,
        "visits_by_day": visits_by_day,
        "new_customers_by_week": new_customers_by_week,
        "tier_distribution": tier_distribution,
        "campaign_performance": campaign_performance,
        "visit_time_heatmap": visit_heatmap
    }

@app.post("/api/owner/ai-query")
def ai_query(
    req: AIQueryRequest,
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Owner AI assistant with query limits per plan"""
    t_id = token_data.tenant_id
    tenant = db.tenants.find_one({"id": t_id})
    plan = tenant.get("plan", "basic")

    # Check daily limit
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    daily_limit = get_plan_features(plan).get("ai_queries_per_day", 0)
    today_queries = db.ai_queries.count_documents({
        "tenant_id": t_id,
        "created_at": {"$gte": today_start, "$lt": today_end}
    })

    if today_queries >= daily_limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily AI query limit reached ({daily_limit} queries). Upgrade your plan for more access."
        )

    # Record query
    query_record = {
        "id": str(uuid.uuid4()),
        "tenant_id": t_id,
        "message": req.message,
        "created_at": datetime.now(timezone.utc)
    }
    db.ai_queries.insert_one(query_record)

    # Generate contextual mock response
    tenant_name = tenant.get("name", "your business")
    response_templates = [
        f"Based on {tenant_name}'s data, I recommend focusing on your Gold tier customers this month.",
        f"Your customer retention rate is strong! Consider launching a referral program to accelerate growth.",
        f"{tenant_name} shows peak engagement on weekends. Consider weekend promotions.",
        "Your average customer lifetime value is increasing. Retention strategies are working well."
    ]

    reply = random.choice(response_templates)

    return {
        "reply": reply,
        "mode": "mock",
        "daily_usage": f"{today_queries + 1}/{daily_limit}"
    }

# ========================
# PUBLIC ENDPOINTS
# ========================

# ============================================================
# PER-CARD PWA MANIFEST
#
# Why: the static /manifest.webmanifest at the site root has
# start_url="/" and scope="/". When a customer hits "Add to Home Screen"
# from /card/FT-XXXXXXXX, iOS/Android read THAT manifest, so tapping the
# home-screen icon launches the landing page — not the card they
# actually wanted to bookmark.
#
# This endpoint returns a per-card manifest with start_url set to that
# specific card's URL. The MyWalletCardPage injects a <link rel="manifest"
# href="/api/manifest/FT-XXXXXXXX"> tag dynamically when the page mounts,
# so the OS picks up the right start_url at "Add to Home Screen" time.
#
# Scope = "/card/" so the installed PWA can navigate between cards if the
# customer joins multiple programmes. Anything outside /card/ opens in the
# browser as normal.
# ============================================================
@app.get("/api/manifest/{barcode_id}")
def per_card_manifest(barcode_id: str):
    bc = (barcode_id or "").strip().upper()
    # Best-effort enrichment: look up the customer + tenant so we can
    # personalise the PWA name to the business. If the customer doesn't
    # exist we still return a valid manifest — just with generic labels.
    name = "FidéliTour"
    short_name = "FidéliTour"
    try:
        cust = db.customers.find_one({"barcode_id": bc}) if db is not None else None
        if cust:
            t = db.tenants.find_one({"id": cust.get("tenant_id")})
            if t and t.get("name"):
                name = f"{t['name']} · Fidélité"
                short_name = t["name"][:12]
    except Exception:
        pass

    body = {
        "name": name,
        "short_name": short_name,
        "description": "Votre carte de fidélité.",
        "start_url": f"/card/{bc}",
        "scope": "/card/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#FDFBF7",
        "theme_color": "#B85C38",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            {"src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
        ],
        "categories": ["lifestyle", "shopping"],
        "lang": "fr",
        "dir": "ltr",
    }
    return Response(
        content=json.dumps(body),
        media_type="application/manifest+json",
        # NO cache. iOS Safari aggressively caches PWA manifests — if the
        # browser hands the OS a stale start_url the home-screen icon
        # opens the wrong page. Forcing a fresh fetch every time the
        # link is read costs us nothing (it's a tiny JSON blob) and
        # eliminates the cache-staleness class of bugs entirely.
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.get("/api/join/{slug}")
def get_join_info(slug: str):
    t = db.tenants.find_one({"slug": slug})
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    t.pop("_id", None)
    return t

ALLOWED_ACQUISITION_SOURCES = {"instagram", "facebook", "tiktok", "qr_store", "website"}

class JoinRequest(BaseModel):
    name: str
    # Email is OPTIONAL — many walk-in customers don't have one handy,
    # and forcing it kills conversion. When blank, dedup falls back to
    # phone-only and email-based campaigns (drips, receipts) silently
    # skip this customer with no error.
    email: Optional[str] = ""
    phone: str
    postal_code: str
    birthday: str
    acquisition_source: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # Multi-touch attribution: every URL ?src=... the visitor landed on
    # before signing up, in chronological order. Frontend collects via
    # localStorage and sends the full chain on submit.
    touchpoints_history: Optional[list] = None
    # RGPD consent (Art. 6/7): must be explicitly True for NEW signups.
    # Optional+False default keeps old cached frontends from 500ing on
    # the dedup path (existing customers), but new customer creation is
    # refused without it.
    consent: Optional[bool] = False
    consent_policy_version: Optional[str] = None

@app.post("/api/join/{slug}")
def join_program(slug: str, req: JoinRequest, request: Request = None):
    # Normalize acquisition_source to exactly the 5 allowed values
    if req.acquisition_source:
        src = (req.acquisition_source or "").strip().lower().replace(" ", "_")
        # Map common variants to canonical values
        alias = {
            "qr": "qr_store", "qr_code": "qr_store", "qrcode": "qr_store",
            "qr_code_in_store": "qr_store", "in_store": "qr_store", "store": "qr_store",
            "insta": "instagram", "ig": "instagram",
            "fb": "facebook",
            "tik_tok": "tiktok",
            "site": "website", "web": "website", "site_web": "website",
        }
        src = alias.get(src, src)
        req.acquisition_source = src if src in ALLOWED_ACQUISITION_SOURCES else "qr_store"
    t = db.tenants.find_one({"slug": slug})
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tid = t["id"]

    # Dedup logic:
    #   • If both email AND phone are present, require BOTH to match (the
    #     conservative case — protects against family members sharing one
    #     phone or one email from being merged).
    #   • If only phone is present (email left blank, now allowed), match
    #     on phone alone. We have no second signal, so any signup with the
    #     same phone number is treated as the same person.
    # This is the right trade-off now that email is optional: forcing a
    # double match when only one signal exists would create a duplicate
    # customer record on every re-join attempt.
    norm_email = (req.email or "").strip().lower()
    norm_phone = "".join(c for c in (req.phone or "") if c.isdigit())
    existing = None
    if norm_email and norm_phone:
        # Both present → strict double-match (existing behaviour).
        for cand in db.customers.find({
            "tenant_id": tid,
            "email": {"$regex": f"^{re.escape(norm_email)}$", "$options": "i"},
        }):
            cand_phone = "".join(c for c in (cand.get("phone") or "") if c.isdigit())
            if cand_phone == norm_phone:
                existing = cand
                break
    elif norm_phone:
        # Email omitted → phone-only match. Same phone in this tenant is
        # treated as the same customer; we just refresh their record.
        for cand in db.customers.find({"tenant_id": tid}):
            cand_phone = "".join(c for c in (cand.get("phone") or "") if c.isdigit())
            if cand_phone == norm_phone:
                existing = cand
                break
    if existing:
        # Backfill GPS if newly provided
        if req.latitude is not None and req.longitude is not None:
            db.customers.update_one(
                {"_id": existing["_id"]},
                {"$set": {"latitude": req.latitude, "longitude": req.longitude}}
            )
        return {"barcode_id": existing["barcode_id"], "message": "Already joined"}

    # ─── Plan cap enforcement ───────────────────────────────────────────
    # Block new customer creation once the tenant reaches the cap defined
    # in PLAN_FEATURES for their current plan. Soft-deleted customers are
    # NOT counted, so a business that purges inactives frees up slots.
    # Existing customers (dedup hit above) bypass this check — never
    # block someone who's already in the programme from updating their
    # record.
    plan = t.get("plan", "basic")
    plan_cap = get_plan_features(plan).get("max_customers", 500)
    current_count = db.customers.count_documents({
        "tenant_id": tid,
        "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}],
    })
    if current_count >= plan_cap:
        next_plan = {"basic": "gold", "gold": "vip", "vip": "chain", "chain": None}.get(plan)
        next_plan_cap = get_plan_features(next_plan).get("max_customers") if next_plan else None
        next_plan_price = PLAN_PRICES.get(next_plan) if next_plan else None
        raise HTTPException(
            status_code=403,
            detail={
                "code": "plan_limit_reached",
                "message": (
                    f"Ce programme de fidélité est temporairement complet "
                    f"({plan_cap} membres). Le commerçant doit augmenter "
                    f"sa limite avant que vous puissiez vous inscrire."
                ),
                "plan": plan,
                "plan_cap": plan_cap,
                "current_count": current_count,
                "next_plan": next_plan,
                "next_plan_cap": next_plan_cap,
                "next_plan_price": next_plan_price,
            },
        )

    # ─── RGPD consent gate (Art. 7 — proof of consent) ─────────────────
    # New customer creation REQUIRES an explicit consent tick. The consent
    # record (timestamp, policy version, IP, source) is stored on the
    # customer document — that record is the CNIL-facing proof.
    if not req.consent:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "consent_required",
                "message": ("Vous devez accepter l'utilisation de vos données "
                            "pour le programme de fidélité avant de vous inscrire."),
            },
        )

    barcode_id = "FT-" + str(uuid.uuid4().hex[:8]).upper()
    c = Customer(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        barcode_id=barcode_id,
        name=req.name,
        email=req.email,
        phone=req.phone,
        postal_code=req.postal_code,
        birthday=req.birthday,
        acquisition_source=req.acquisition_source,
        latitude=req.latitude,
        longitude=req.longitude
    )
    cust_doc = c.model_dump()
    # Multi-touch attribution: store the full chain of touchpoints (every
    # ?src= the visitor passed through) plus first-touch + last-touch
    # convenience fields. This makes "joined via QR but originally found
    # us on Instagram" reportable.
    if req.touchpoints_history and isinstance(req.touchpoints_history, list):
        clean_chain = []
        seen = set()
        for tp in req.touchpoints_history:
            if not isinstance(tp, dict):
                continue
            src = (tp.get("source") or "").strip().lower()
            ts = tp.get("ts")
            if src and src in ALLOWED_ACQUISITION_SOURCES:
                key = f"{src}|{ts or ''}"
                if key not in seen:
                    seen.add(key)
                    clean_chain.append({"source": src, "ts": ts})
        if clean_chain:
            cust_doc["touchpoints_history"] = clean_chain
            cust_doc["first_touch_source"] = clean_chain[0]["source"]
            cust_doc["last_touch_source"] = clean_chain[-1]["source"]
    # RGPD consent proof — immutable record of what was accepted and when.
    cust_doc["consent"] = {
        "accepted": True,
        "ts": datetime.now(timezone.utc),
        "policy_version": req.consent_policy_version or CURRENT_PRIVACY_POLICY_VERSION,
        "source": "join_page",
        "ip": _client_ip(request),
    }
    db.customers.insert_one(cust_doc)
    log_audit("gdpr.consent_given", actor=barcode_id, actor_type="customer",
              tenant_id=tid, target=cust_doc["id"], request=request,
              meta={"policy_version": cust_doc["consent"]["policy_version"]})
    return {"barcode_id": barcode_id, "message": "Welcome!"}

# ========================
# WALLET CARD (public, barcode-keyed) — Captain Wallet style
# Rich customer-facing card view with offers, push notifications,
# auto-update toggle, and delete-card action.
# ========================

def _derive_offers_for_tenant(tenant_id: str) -> List[dict]:
    """Offers = active card-template offer + sent campaigns (last 45 days).

    Each campaign-kind offer now also carries `image_url`, `body`, and
    `link` so the wallet card's tap-to-open detail modal can render the
    full content (hero image, full message, CTA link) — previously these
    fields were missing from the payload and the image the merchant
    uploaded at compose time never reached the customer's screen.
    """
    offers = []
    tpl = db.card_templates.find_one({"tenant_id": tenant_id})
    if tpl and tpl.get("active_offer_active") and tpl.get("active_offer_title"):
        offers.append({
            "id": "offer-main",
            "title": tpl.get("active_offer_title"),
            "description": tpl.get("active_offer_description") or "",
            "body": tpl.get("active_offer_description") or "",
            "image_url": tpl.get("active_offer_image_url"),
            "link": tpl.get("active_offer_link"),
            "kind": "primary",
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        })
    cutoff = datetime.now(timezone.utc) - timedelta(days=45)
    camps = list(db.campaigns.find({
        "tenant_id": tenant_id, "status": "sent",
        "sent_at": {"$gte": cutoff}
    }).sort("sent_at", -1).limit(5))
    for c in camps:
        offers.append({
            "id": c.get("id"),
            "title": c.get("name"),
            "description": c.get("content", ""),
            # New fields surfaced for the detail modal.
            "body": c.get("content", ""),
            "image_url": c.get("image_url"),
            "link": c.get("link"),
            "sent_at": c.get("sent_at").isoformat() if c.get("sent_at") else None,
            "kind": "campaign",
            "valid_until": (c.get("sent_at") + timedelta(days=30)).isoformat() if c.get("sent_at") else None,
        })
    return offers


def _card_prefs_for(customer_id: str) -> dict:
    rec = db.card_prefs.find_one({"customer_id": customer_id})
    if not rec:
        return {"auto_update": True, "push_enabled": True, "deleted": False}
    rec.pop("_id", None)
    return rec


# --- Per-customer card overrides (filtered "send offer over the card") ---
# A row in db.customer_card_overrides means: for THIS specific customer in
# THIS tenant, override these middle-band fields on the card until expires_at.
# Used to push promotional overlays to a filtered segment without changing
# the global card_template seen by everyone else.
def _active_override_for(customer_id: str, tenant_id: str) -> dict:
    """Return the active (non-expired) override for one customer, or {}."""
    now = datetime.now(timezone.utc)
    row = db.customer_card_overrides.find_one({
        "customer_id": customer_id,
        "tenant_id": tenant_id,
        "is_active": True,
    })
    if not row:
        return {}
    # Expiry check: if expires_at is set and in the past, soft-deactivate it
    # so the next read is a clean miss.
    exp = row.get("expires_at")
    if exp and isinstance(exp, datetime) and exp <= now:
        db.customer_card_overrides.update_one(
            {"_id": row["_id"]},
            {"$set": {"is_active": False}},
        )
        return {}
    row.pop("_id", None)
    return row


def _serialize_card_payload(cust: dict) -> dict:
    t = db.tenants.find_one({"id": cust["tenant_id"]}) or {}
    tpl = db.card_templates.find_one({"tenant_id": cust["tenant_id"]}) or {}
    prefs = _card_prefs_for(cust["id"])
    offers = _derive_offers_for_tenant(cust["tenant_id"])
    # Per-customer override (active, non-expired) — promotional overlay for a
    # filtered segment. Replaces the matching fields on the global template.
    override = _active_override_for(cust["id"], cust["tenant_id"])
    # Whitelist the override fields that may overlay on the card so a
    # corrupted/malicious row can't replace unrelated fields.
    _OVERRIDE_KEYS = {
        "strip_title", "strip_subtitle", "strip_color", "strip_text_color",
        "strip_type", "hero_image_url",
        "show_offer_box", "offer_box_text", "offer_box_subtext",
        "offer_box_color", "offer_box_ink_color",
    }
    for k in _OVERRIDE_KEYS:
        if k in override:
            tpl[k] = override[k]

    # Tier-aware design
    tier = (cust.get("tier") or "bronze").lower()
    design = tpl.get(f"{tier}_design") or tpl.get("bronze_design") or {}

    reward_threshold = tpl.get("reward_threshold_stamps", 10)
    # Stamps on the wallet card = visits SINCE the last redemption, capped
    # at the reward threshold. `visits` itself is the lifetime counter and
    # is never decremented — that's what drives tier promotion. The
    # `visits_at_last_redemption` field is set by the redemption endpoint
    # (POST /api/owner/rewards/redeem) and marks where in the visit
    # history the customer cashed in their last card.
    lifetime_visits = int(cust.get("visits", 0) or 0)
    last_redemption_visits = int(cust.get("visits_at_last_redemption", 0) or 0)
    stamps_in_cycle = max(0, lifetime_visits - last_redemption_visits)
    stamps = min(stamps_in_cycle, reward_threshold)

    # ── Merge brand_fields into the top-level template view ──────────────
    # The Card Designer save endpoint writes the merchant's design tweaks
    # under `brand_fields` (a sub-document on the template). It also
    # mirrors a HANDFUL of those fields to the top level (primary_color,
    # hero_image_url, etc) for backward-compat — but NOT the strip /
    # offer-box / greeting / QR fields. Without this merge, every
    # designer edit to strip_title, strip_subtitle, strip_color,
    # offer_box_text, etc was being saved but invisibly dropped on the
    # customer's card.
    #
    # Strategy: any key inside brand_fields that isn't already at the
    # top level wins. Top-level wins where it exists, so existing setups
    # that wrote top-level fields directly keep working.
    brand_fields = tpl.get("brand_fields") or {}
    if isinstance(brand_fields, dict):
        for k, v in brand_fields.items():
            if v is None:
                continue
            if k not in tpl or tpl.get(k) in (None, "", [], {}):
                tpl[k] = v

    return {
        "customer": {
            "id": cust["id"],
            "name": cust.get("name"),
            "email": cust.get("email"),
            "barcode_id": cust.get("barcode_id"),
            "tier": tier,
            "visits": cust.get("visits", 0),
            "points": cust.get("points", 0),
            "total_amount_paid": cust.get("total_amount_paid", 0),
            "birthday": cust.get("birthday"),
            "member_since": cust.get("created_at"),
        },
        "tenant": {
            "id": t.get("id"),
            "slug": t.get("slug"),
            "name": t.get("name"),
            "phone": t.get("phone"),
            "address": t.get("address"),
            "website": t.get("website"),
        },
        "card": {
            # Everything the Card Designer persists goes in FIRST, then the
            # explicit entries below overwrite it.
            #
            # Why: this object used to be a hand-maintained whitelist, and it
            # had drifted 25 fields behind the designer. tier_badge_bronze /
            # silver / gold / vip, show_tier, show_points, show_title,
            # show_greeting, show_barcode, show_card_number, show_back_link,
            # the whole stamp_* group, the meter_* colours and use_full_name
            # were all saved to the database, read by PremiumLoyaltyCard, and
            # never put on the wire — so the merchant changed them, the save
            # succeeded, and the customer's card rendered defaults. Any new
            # toggle added to the designer would have joined them silently.
            #
            # Spreading first (not last) is deliberate: the explicit entries
            # read from `tpl`, which already carries the per-customer override
            # overlay applied above. Raw brand_fields must never clobber that.
            **{k: v for k, v in brand_fields.items() if v is not None},
            "logo_url": tpl.get("logo_url"),
            "reward_description": tpl.get("reward_description", "Une récompense fidélité"),
            "reward_threshold": reward_threshold,
            "stamps_earned": stamps,
            "points_per_visit": tpl.get("points_per_visit", 10),
            "design": design,
            "active_offer": {
                "title": tpl.get("active_offer_title"),
                "description": tpl.get("active_offer_description"),
                "active": bool(tpl.get("active_offer_active")),
            },
            # --- New modern-designer fields ---
            "elements": tpl.get("elements") or {},
            "stamp_style": tpl.get("stamp_style") or tpl.get("design_mode") or "hexagon",
            "show_meter": tpl.get("show_meter") if tpl.get("show_meter") is not None else tpl.get("show_progress_meter", True),
            "promotion": tpl.get("promotion") or {"enabled": False},
            "details": tpl.get("details") or {},
            # Auchan fixed-layout (primary design path going forward)
            "auchan_layout": tpl.get("auchan_layout"),
            # Surface flat brand colors too (modern designer writes these via `elements`
            # and keeps these for legacy/fallback rendering).
            "primary_color": tpl.get("primary_color"),
            "secondary_color": tpl.get("secondary_color"),
            "accent_color": tpl.get("accent_color"),
            "background_image_url": tpl.get("background_image_url"),
            # 3-band wallet-pass layout fields — may have been overridden
            # per-customer by an active card override (filtered offer overlay).
            "layout_style":         tpl.get("layout_style"),
            # Wallet-anatomy render inputs (layout_style == "wallet"). The
            # merchant picks brand_color + surface + code_type; every other
            # colour is derived client-side in cardTheme.js. CardTemplate has
            # extra="allow", so these persist through the save endpoints
            # without model changes.
            "brand_color":          tpl.get("brand_color"),
            "surface":              tpl.get("surface"),
            "surface_color":        tpl.get("surface_color"),
            "code_type":            tpl.get("code_type"),
            "hero_mode":            tpl.get("hero_mode"),
            "visits_label":         tpl.get("visits_label"),
            "stamps_label":         tpl.get("stamps_label"),
            "show_stamps":          tpl.get("show_stamps"),
            "show_visits":          tpl.get("show_visits"),
            "card_bg_color":        tpl.get("card_bg_color"),
            "card_ink_color":       tpl.get("card_ink_color"),
            "strip_type":           tpl.get("strip_type"),
            "strip_color":          tpl.get("strip_color"),
            "strip_text_color":     tpl.get("strip_text_color"),
            "strip_title":          tpl.get("strip_title"),
            "strip_subtitle":       tpl.get("strip_subtitle"),
            "hero_image_url":       tpl.get("hero_image_url"),
            "hero_front_url":       tpl.get("hero_front_url"),
            "show_offer_box":       tpl.get("show_offer_box"),
            "offer_box_text":       tpl.get("offer_box_text"),
            "offer_box_subtext":    tpl.get("offer_box_subtext"),
            "offer_box_color":      tpl.get("offer_box_color"),
            "offer_box_ink_color":  tpl.get("offer_box_ink_color"),
            # Remaining PremiumLoyaltyCard knobs — without these the
            # customer card always rendered defaults even though the
            # merchant configured them in the designer.
            "logo_position":             tpl.get("logo_position"),
            "show_points_top_right":     tpl.get("show_points_top_right"),
            "points_top_right_label":    tpl.get("points_top_right_label"),
            "bottom_greeting_label":     tpl.get("bottom_greeting_label"),
            "show_qr":                   tpl.get("show_qr"),
            "qr_size":                   tpl.get("qr_size"),
            "show_birthday":             tpl.get("show_birthday"),
            "birthday_label":            tpl.get("birthday_label"),
            "show_tier_badge":           tpl.get("show_tier_badge"),
            "title_label":               tpl.get("title_label"),
            "points_label":              tpl.get("points_label"),
            "greeting_label":            tpl.get("greeting_label"),
            "back_label":                tpl.get("back_label"),
            "back_value":                tpl.get("back_value"),
            "title_font":                tpl.get("title_font"),
            "title_italic":              tpl.get("title_italic"),
            "text_on_brand":             tpl.get("text_on_brand"),
            "back_link_color":           tpl.get("back_link_color"),
            "strip_title":               tpl.get("strip_title"),
            "strip_subtitle":            tpl.get("strip_subtitle"),
            "strip_color":               tpl.get("strip_color"),
            "strip_text_color":          tpl.get("strip_text_color"),
            "strip_type":                tpl.get("strip_type"),
            # Tell the client whether this card currently has a personalised
            # overlay running (so it can show "Offre spéciale réservée" badge).
            "has_personalised_overlay": bool(override),
        },
        "offers": offers,
        "prefs": prefs,
        "notifications": _recent_push_notifications_for(cust["id"], cust["tenant_id"]),
    }


def _recent_push_notifications_for(customer_id: str, tenant_id: str) -> List[dict]:
    # Use sent campaigns as synthetic push log + one "welcome" synthetic entry
    cutoff = datetime.now(timezone.utc) - timedelta(days=45)
    items = []
    for c in db.campaigns.find({"tenant_id": tenant_id, "status": "sent", "sent_at": {"$gte": cutoff}}).sort("sent_at", -1).limit(6):
        items.append({
            "id": c.get("id"),
            "title": c.get("name"),
            "body": c.get("content", ""),
            # Surface the merchant-uploaded hero image + any CTA link so
            # the wallet card's detail modal can show them. Previously
            # these were dropped and the image at compose time was
            # effectively invisible to customers.
            "image_url": c.get("image_url"),
            "link": c.get("link"),
            "sent_at": c.get("sent_at").isoformat() if c.get("sent_at") else None,
            "kind": "campaign",
        })
    return items


@app.get("/api/card/{barcode_id}")
def get_wallet_card(barcode_id: str):
    cust = db.customers.find_one({"barcode_id": barcode_id})
    if not cust:
        raise HTTPException(status_code=404, detail="Card not found")
    return _serialize_card_payload(cust)


class CardPrefsRequest(BaseModel):
    auto_update: Optional[bool] = None
    push_enabled: Optional[bool] = None


@app.put("/api/card/{barcode_id}/prefs")
def update_card_prefs(barcode_id: str, req: CardPrefsRequest):
    cust = db.customers.find_one({"barcode_id": barcode_id})
    if not cust:
        raise HTTPException(status_code=404, detail="Card not found")
    update = {"customer_id": cust["id"], "tenant_id": cust["tenant_id"]}
    if req.auto_update is not None:
        update["auto_update"] = req.auto_update
    if req.push_enabled is not None:
        update["push_enabled"] = req.push_enabled
    db.card_prefs.update_one({"customer_id": cust["id"]}, {"$set": update}, upsert=True)
    return _card_prefs_for(cust["id"])


@app.delete("/api/card/{barcode_id}")
def delete_wallet_card(barcode_id: str):
    cust = db.customers.find_one({"barcode_id": barcode_id})
    if not cust:
        raise HTTPException(status_code=404, detail="Card not found")
    now = datetime.now(timezone.utc)
    # 1) Flip pass_issued back so dashboard 'Active wallet passes' is accurate
    # 2) Stamp card_deleted_at so we can surface 'Deleted cards' as its own KPI
    db.customers.update_one(
        {"id": cust["id"]},
        {"$set": {
            "pass_issued": False,
            "card_deleted_at": now,
        }},
    )
    # Persist the prefs row too — keeps backwards compatibility with anything
    # that reads card_prefs.deleted
    db.card_prefs.update_one(
        {"customer_id": cust["id"]},
        {"$set": {
            "customer_id": cust["id"],
            "tenant_id": cust["tenant_id"],
            "deleted": True,
            "deleted_at": now,
        }},
        upsert=True
    )
    # Clean up any web-push subscriptions so we never push to a deleted device
    try:
        db.push_subscriptions.delete_many({
            "tenant_id": cust["tenant_id"],
            "customer_id": cust["id"],
        })
    except Exception:
        pass
    return {"status": "ok", "message": "Card removed from wallet"}


@app.post("/api/card/{barcode_id}/wallet-readded")
def mark_wallet_readded(barcode_id: str):
    """Customer re-added the card after a previous delete. Clears card_deleted_at
    and flips pass_issued back to True so the wallet-state KPIs reflect reality."""
    cust = db.customers.find_one({"barcode_id": barcode_id})
    if not cust:
        raise HTTPException(status_code=404, detail="Card not found")
    db.customers.update_one(
        {"id": cust["id"]},
        {"$set": {"pass_issued": True}, "$unset": {"card_deleted_at": ""}},
    )
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────
# RGPD — Droits des personnes (Sprint 1)
# Barcode-keyed like every other /api/card/* endpoint: possessing the
# barcode IS the customer's authentication (same model as prefs/delete).
# ─────────────────────────────────────────────────────────────────────

def _strip_mongo(doc: dict) -> dict:
    """Remove _id and make datetimes JSON-serializable."""
    if not doc:
        return {}
    doc = dict(doc)
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
        elif isinstance(v, dict):
            doc[k] = _strip_mongo(v)
    return doc


@app.get("/api/card/{barcode_id}/my-data")
def export_my_data(barcode_id: str, request: Request = None):
    """RGPD Art. 15 (accès) + Art. 20 (portabilité).

    Returns EVERYTHING we hold on this customer as one JSON document:
    profile, consent proof, visits, notifications received, reviews left,
    rewards redeemed, card prefs, and push-subscription count (endpoints
    themselves are secrets — we expose the count, not the URLs).
    """
    cust = db.customers.find_one({"barcode_id": barcode_id})
    if not cust:
        raise HTTPException(status_code=404, detail="Card not found")
    cid, tid = cust["id"], cust["tenant_id"]
    t = db.tenants.find_one({"id": tid}) or {}

    visits = [_strip_mongo(v) for v in
              db.visits.find({"customer_id": cid}).sort("visit_time", -1)]
    notifications = [_strip_mongo(n) for n in
                     db.notifications.find({"customer_id": cid}).sort("created_at", -1).limit(500)]
    reviews = [_strip_mongo(r) for r in db.reviews.find({"customer_id": cid})]
    redemptions = [_strip_mongo(r) for r in db.rewards_redeemed.find({"customer_id": cid})]
    prefs = _card_prefs_for(cid)
    push_count = db.push_subscriptions.count_documents({"customer_id": cid})

    log_audit("gdpr.export", actor=barcode_id, actor_type="customer",
              tenant_id=tid, target=cid, request=request,
              meta={"visits": len(visits), "notifications": len(notifications)})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "format_version": "1.0",
        "business": {"name": t.get("name"), "slug": t.get("slug")},
        "profile": _strip_mongo(cust),
        "consent": _strip_mongo(cust.get("consent") or {}),
        "visits": visits,
        "notifications_received": notifications,
        "reviews": reviews,
        "rewards_redeemed": redemptions,
        "card_preferences": prefs,
        "push_subscriptions_count": push_count,
        "rights_notice": (
            "Conformément au RGPD, vous pouvez demander la rectification ou "
            "la suppression de vos données à tout moment depuis votre carte "
            "(section Confidentialité) ou auprès du commerçant."
        ),
    }


class ForgetMeRequest(BaseModel):
    confirm: bool = False


@app.post("/api/card/{barcode_id}/forget-me")
def forget_me(barcode_id: str, req: ForgetMeRequest, request: Request = None):
    """RGPD Art. 17 (droit à l'effacement).

    Anonymizes all personal data while keeping the aggregate business
    stats (visit counts, amounts) that the merchant may retain under
    legitimate interest — the visit rows carry no personal data once the
    customer document is anonymized.

    Irreversible. Requires confirm=true.
    """
    if not req.confirm:
        raise HTTPException(status_code=422, detail={
            "code": "confirmation_required",
            "message": "Confirmation requise pour supprimer vos données.",
        })
    cust = db.customers.find_one({"barcode_id": barcode_id})
    if not cust:
        raise HTTPException(status_code=404, detail="Card not found")
    cid, tid = cust["id"], cust["tenant_id"]
    now = datetime.now(timezone.utc)

    # 1) Anonymize the customer document — PII wiped, aggregates kept.
    db.customers.update_one({"id": cid}, {
        "$set": {
            "name": "Client supprimé",
            "email": "",
            "phone": "",
            "postal_code": "",
            "birthday": "",
            "gdpr_erased_at": now,
            "deleted_at": now,          # frees a plan-cap slot too
            "pass_issued": False,
        },
        "$unset": {
            "latitude": "", "longitude": "",
            "touchpoints_history": "", "first_touch_source": "",
            "last_touch_source": "",
        },
    })
    # 2) Kill every push channel to this person's devices.
    push_deleted = db.push_subscriptions.delete_many({"customer_id": cid}).deleted_count
    # 3) Per-customer notification log = personal data → delete.
    notif_deleted = db.notifications.delete_many({"customer_id": cid}).deleted_count
    # 4) Free-text reviews may identify the author → delete.
    reviews_deleted = db.reviews.delete_many({"customer_id": cid}).deleted_count
    # 5) Card prefs + overrides cleanup.
    db.card_prefs.delete_many({"customer_id": cid})
    db.customer_card_overrides.delete_many({"customer_id": cid})

    log_audit("gdpr.forget_me", actor=barcode_id, actor_type="customer",
              tenant_id=tid, target=cid, request=request,
              meta={"push_deleted": push_deleted,
                    "notifications_deleted": notif_deleted,
                    "reviews_deleted": reviews_deleted})

    return {
        "status": "erased",
        "message": ("Vos données personnelles ont été supprimées. "
                    "Cette carte n'est plus utilisable."),
    }


# ─────────────────────────────────────────────────────────────────────
# Q7 — Per-customer card overrides ("send an offer over the card")
# Owner can target a filter (tier, min_visits, etc.) and write a temporary
# middle-band overlay on every matching customer's card. When the customer
# opens their wallet PWA the override is merged into the card payload until
# expires_at. The overlay is purely additive — it doesn't touch the
# global card_template and is isolated per-tenant + per-customer.
# ─────────────────────────────────────────────────────────────────────
class CardOverrideFields(BaseModel):
    strip_title:         Optional[str]  = None
    strip_subtitle:      Optional[str]  = None
    strip_color:         Optional[str]  = None
    strip_text_color:    Optional[str]  = None
    strip_type:          Optional[str]  = None     # 'color' | 'image'
    hero_image_url:      Optional[str]  = None
    show_offer_box:      Optional[bool] = None
    offer_box_text:      Optional[str]  = None
    offer_box_subtext:   Optional[str]  = None
    offer_box_color:     Optional[str]  = None
    offer_box_ink_color: Optional[str]  = None


class PushCardOverrideRequest(BaseModel):
    # Same filter shape as a campaign — keeps the targeting language consistent.
    filters: Dict[str, Any] = {}
    override: CardOverrideFields
    expires_in_days: Optional[int] = 14        # default: overlay lasts 2 weeks
    send_push: Optional[bool]     = True       # also fire a web-push notification
    push_title: Optional[str]     = None
    push_body:  Optional[str]     = None


@app.post("/api/owner/card-overrides/push")
def push_card_override(
    req: PushCardOverrideRequest,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Write a middle-band overlay onto every customer matching `filters`.

    Returns how many customers got the overlay and how many push pings fired.
    The overlay merges into _serialize_card_payload at read time, so the
    wallet PWA's next fetch (the page polls on focus) shows the new banner.
    """
    tenant_id = token_data.tenant_id
    f = req.filters or {}

    # Build the same filter query as /api/owner/campaigns/{id}/send.
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if f.get("tier"):              query["tier"] = f["tier"]
    if f.get("min_visits"):        query["visits"] = {"$gte": int(f["min_visits"])}
    if f.get("min_points"):        query["points"] = {"$gte": int(f["min_points"])}
    if f.get("postal_code"):       query["postal_code"] = f["postal_code"]
    if f.get("city"):              query["city"] = f["city"]
    if f.get("min_amount_paid"):   query["total_amount_paid"] = {"$gte": float(f["min_amount_paid"])}
    # Inactivity slice (same shape as the customers endpoint)
    now_utc = datetime.now(timezone.utc)
    if f.get("inactive_days_min"):
        upper = now_utc - timedelta(days=int(f["inactive_days_min"]))
        lv: Dict[str, Any] = {"$lte": upper}
        if f.get("inactive_days_max"):
            lv["$gte"] = now_utc - timedelta(days=int(f["inactive_days_max"]))
        query["last_visit_date"] = lv

    targets = list(db.customers.find(query, {
        "id": 1, "name": 1, "first_name": 1, "tenant_id": 1,
        "phone": 1, "tier": 1, "points": 1, "visits": 1,
    }))
    if not targets:
        return {"status": "ok", "overlaid": 0, "pushed": 0, "skipped": 0}

    expires_at = None
    if req.expires_in_days and req.expires_in_days > 0:
        expires_at = now_utc + timedelta(days=int(req.expires_in_days))

    # Strip None values so we don't overwrite global template with empties.
    override_payload = {k: v for k, v in req.override.model_dump().items() if v is not None}

    overlaid = 0
    for cust in targets:
        db.customer_card_overrides.update_one(
            {"customer_id": cust["id"], "tenant_id": tenant_id},
            {
                "$set": {
                    "customer_id": cust["id"],
                    "tenant_id":   tenant_id,
                    "is_active":   True,
                    "created_at":  now_utc,
                    "expires_at":  expires_at,
                    **override_payload,
                }
            },
            upsert=True,
        )
        overlaid += 1

    pushed = 0
    skipped = 0
    if req.send_push:
        push_title = req.push_title or (override_payload.get("strip_title") or "Une offre vous attend")
        push_body  = req.push_body  or (override_payload.get("offer_box_text") or override_payload.get("strip_subtitle") or "Ouvrez votre carte fidélité pour la découvrir.")
        for cust in targets:
            # Was calling _send_web_push_to_customer(), which is defined
            # nowhere in this codebase — every call fell into `except
            # NameError` and reported pushed: 0 with no error at all.
            try:
                if dispatch_to_customer(tenant_id, cust, push_title, push_body,
                                        kind="card_override")["sent"]:
                    pushed += 1
                else:
                    skipped += 1
            except Exception as _e:
                print(f"card override push failed for {cust.get('id')}: {_e}")
                skipped += 1

    return {
        "status": "ok",
        "overlaid": overlaid,
        "pushed": pushed,
        "skipped": skipped,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


@app.delete("/api/owner/card-overrides/customer/{customer_id}")
def clear_card_override(
    customer_id: str,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Clear an active overlay for one customer (e.g. they unsubscribed, or
    the owner wants the global template back on this customer's card)."""
    res = db.customer_card_overrides.update_one(
        {"customer_id": customer_id, "tenant_id": token_data.tenant_id},
        {"$set": {"is_active": False}},
    )
    return {"status": "ok", "cleared": res.modified_count}


@app.delete("/api/owner/card-overrides/all")
def clear_all_card_overrides(
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Wipe every active overlay for this tenant. Useful "kill switch"."""
    res = db.customer_card_overrides.update_many(
        {"tenant_id": token_data.tenant_id, "is_active": True},
        {"$set": {"is_active": False}},
    )
    return {"status": "ok", "cleared": res.modified_count}


@app.get("/api/owner/card-overrides/active-count")
def count_active_card_overrides(
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """How many customers currently have an active overlay on their card?
    Powers the small badge in the Campaigns UI."""
    now_utc = datetime.now(timezone.utc)
    n = db.customer_card_overrides.count_documents({
        "tenant_id": token_data.tenant_id,
        "is_active": True,
        "$or": [
            {"expires_at": None},
            {"expires_at": {"$gt": now_utc}},
        ],
    })
    return {"active_count": n}


# ========================
# NEW OWNER ENDPOINTS (TRACKING & MAP)
# ========================

@app.post("/api/owner/customers/map")
def get_customers_map(
    token_data: TokenData = Depends(require_role(["business_owner"])),
    branch_id: Optional[str] = Query(None),
):
    """Get customers with approximated lat/lng + department for France-wide map display.

    Honors optional `branch_id` so the map reflects only that branch's customers.
    Calls the branch backfill once so filtering to a branch returns real rows
    even when customers were created without one (seed data, old signups).
    """
    # Backfill branch assignments on the first call — idempotent.
    _ensure_branch_assignments(token_data.tenant_id)

    q = _branch_customer_filter(token_data.tenant_id, branch_id)
    customers = list(db.customers.find(q))
    result = []

    for cust in customers:
        postal_code = cust.get("postal_code", "75001")

        # Prefer real GPS if captured, else resolve from postal code
        real_lat = cust.get("latitude")
        real_lng = cust.get("longitude")
        if real_lat is not None and real_lng is not None:
            lat, lng = real_lat, real_lng
        else:
            base_lat, base_lng = get_postal_coords(postal_code)
            hash_val = int(hashlib.md5(cust["id"].encode()).hexdigest(), 16)
            jitter_lat = ((hash_val % 200) - 100) / 5000   # ±0.02° ≈ ±2km
            jitter_lng = (((hash_val // 200) % 200) - 100) / 5000
            lat = base_lat + jitter_lat
            lng = base_lng + jitter_lng

        dept_code, dept_name = get_department_info(postal_code)

        result.append({
            "id": cust["id"],
            "name": cust.get("name", ""),
            "email": cust.get("email", ""),
            "phone": cust.get("phone", ""),
            "postal_code": postal_code,
            "address": cust.get("address", ""),
            "city": cust.get("city", ""),
            "lat": lat,
            "lng": lng,
            "department_code": dept_code,
            "department_name": dept_name,
            "tier": cust.get("tier", "bronze"),
            "points": cust.get("points", 0),
            "total_visits": cust.get("visits", 0),
            "total_amount_paid": cust.get("total_amount_paid", 0),
            "acquisition_source": cust.get("acquisition_source"),
            "has_real_gps": real_lat is not None and real_lng is not None,
            "pass_issued": bool(cust.get("pass_issued", False)),
            "birthday": cust.get("birthday"),
            "created_at": cust.get("created_at"),
            "last_visit_date": cust.get("last_visit_date"),
            "branch_id": cust.get("branch_id"),
            "notes": cust.get("notes", ""),
        })

    return result

@app.post("/api/owner/campaigns/send-to-group")
def send_campaign_to_group(
    req: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["business_owner", "manager"]))
):
    """Create and send campaign to specific group of customers.
    Accepts either explicit customer_ids or a segment descriptor (resolved server-side).
    Segment shapes:
      {type: 'tier', value: 'gold'}
      {type: 'inactive_days', value: 30}
      {type: 'recovered', window_days: 30, inactive_days: 30}
      {type: 'top_paying_n', n: 20}
      {type: 'least_paying_n', n: 20}
      {type: 'max_visits_n', n: 20}
      {type: 'least_visits_n', n: 20}
      {type: 'birthday_month', value: 'MM'}
      {type: 'acquisition', value: 'instagram'}
      {type: 'postal_code', value: '37000'}
      {type: 'department_code', value: '37'}
      {type: 'all'}
    """
    tid = token_data.tenant_id
    tenant = db.tenants.find_one({"id": tid}) or {}
    customer_ids = req.get("customer_ids") or []
    segment = req.get("segment") or None
    now = datetime.now(timezone.utc)

    # Resolve segment → customer list (if no explicit customer_ids given).
    if not customer_ids and segment:
        stype = (segment.get("type") or "").lower()
        q = {"tenant_id": tid}
        cursor = None
        if stype == "tier" and segment.get("value"):
            q["tier"] = segment["value"]
        elif stype == "inactive_days":
            days = int(segment.get("value") or 30)
            q["last_visit_date"] = {"$lt": now - timedelta(days=days)}
        elif stype == "recovered":
            inactive = int(segment.get("inactive_days") or 30)
            window = int(segment.get("window_days") or 30)
            q["last_visit_date"] = {"$gte": now - timedelta(days=window)}
            candidates = list(db.customers.find(q))
            filtered = []
            for c in candidates:
                last = c.get("last_visit_date")
                if not last:
                    continue
                # Need a >= inactive-day gap before the recent visit.
                visits_before_recent = list(db.visits.find({
                    "tenant_id": tid, "customer_id": c["id"],
                    "visit_time": {"$lt": last},
                }).sort("visit_time", -1).limit(1))
                if not visits_before_recent:
                    filtered.append(c)
                else:
                    gap = (last - visits_before_recent[0]["visit_time"]).days
                    if gap >= inactive:
                        filtered.append(c)
            customer_ids = [c["id"] for c in filtered]
        elif stype == "top_paying_n":
            n = int(segment.get("n") or 20)
            cursor = db.customers.find({"tenant_id": tid}).sort("total_amount_paid", -1).limit(n)
        elif stype == "least_paying_n":
            n = int(segment.get("n") or 20)
            cursor = db.customers.find({"tenant_id": tid, "total_amount_paid": {"$gt": 0}}).sort("total_amount_paid", 1).limit(n)
        elif stype == "max_visits_n":
            n = int(segment.get("n") or 20)
            cursor = db.customers.find({"tenant_id": tid}).sort("visits", -1).limit(n)
        elif stype == "least_visits_n":
            n = int(segment.get("n") or 20)
            cursor = db.customers.find({"tenant_id": tid, "visits": {"$gt": 0}}).sort("visits", 1).limit(n)
        elif stype == "birthday_month" and segment.get("value"):
            mm = str(segment["value"]).zfill(2)
            cursor = db.customers.find({"tenant_id": tid, "birthday": {"$regex": f"^{mm}"}})
        elif stype == "acquisition" and segment.get("value"):
            q["acquisition_source"] = segment["value"]
        elif stype == "postal_code" and segment.get("value"):
            q["postal_code"] = segment["value"]
        elif stype == "department_code" and segment.get("value"):
            dept = str(segment["value"])
            cursor = db.customers.find({"tenant_id": tid, "postal_code": {"$regex": f"^{dept}"}})
        elif stype == "all":
            cursor = db.customers.find({"tenant_id": tid})
        elif stype == "one_visit_only":
            cursor = db.customers.find({"tenant_id": tid, "visits": {"$lte": 1}})

        if not customer_ids:
            if cursor is None:
                cursor = db.customers.find(q)
            customer_ids = [c["id"] for c in cursor]

    if not customer_ids:
        raise HTTPException(status_code=400, detail="No recipients: provide customer_ids or a non-empty segment.")

    name = req.get("name") or "Campagne ciblée"
    content = req.get("content") or ""
    image_url = req.get("image_url") or None
    sender_name = (tenant.get("campaign_sender_name") or tenant.get("name") or "FidéliTour")

    # Dispatch per-customer with template rendering.
    delivered = 0
    targeted_customers = list(db.customers.find({"id": {"$in": customer_ids}, "tenant_id": tid}))
    for cust in targeted_customers:
        rendered_body = render_template(content, cust, tenant)
        rendered_subject = render_template(name, cust, tenant)
        if dispatch_to_customer(tid, cust, rendered_subject, rendered_body,
                                kind="campaign")["sent"]:
            delivered += 1

    raw_source = (req.get("source") or "").strip().lower() or None
    ALLOWED = {"push", "email", "other"}
    src = raw_source if raw_source in ALLOWED else None

    campaign = Campaign(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        name=name,
        content=content,
        status="sent",
        filters={"segment": segment or {"type": "custom"}},
        sent_at=now,
        targeted_count=len(targeted_customers),
        delivered_count=delivered,
        recipient_ids=[c["id"] for c in targeted_customers],
        image_url=image_url,
        source=src,
    )
    db.campaigns.insert_one(campaign.model_dump())

    # Also log per-customer push notification so wallet cards show the offer.
    for c in targeted_customers:
        db.push_notifications.insert_one({
            "customer_id": c["id"],
            "tenant_id": tid,
            "campaign_id": campaign.id,
            "image_url": image_url,
            "title": render_template(name, c, tenant),
            "body": render_template(content, c, tenant),
            "type": "campaign",
            "sent_at": now,
        })

    return campaign.model_dump()


# ════════════════════════════════════════════════════════════════════
# Item 23 — AI campaign analyzer. POST /api/owner/campaigns/{id}/ai-analyze
# Sends campaign body + audience descriptors + result rows to a free LLM
# (Gemini Flash by default) and returns 3 plain-English bullets.
# ════════════════════════════════════════════════════════════════════

def _audience_descriptor(t_id: str, recipient_ids: list) -> Dict[str, Any]:
    """One-shot audience profile: tier mix, age band, top day-of-week, weekend share."""
    if not recipient_ids:
        return {"size": 0, "summary": "no recipients on this campaign"}
    custs = list(db.customers.find(
        {"tenant_id": t_id, "id": {"$in": recipient_ids}},
        {"_id": 0, "tier": 1, "visits": 1, "total_amount_paid": 1, "last_visit_date": 1}
    ))
    if not custs:
        return {"size": 0, "summary": "recipients not found"}
    n = len(custs)
    tier_counts: Dict[str, int] = {}
    for c in custs:
        t = (c.get("tier") or "bronze").lower()
        tier_counts[t] = tier_counts.get(t, 0) + 1
    dominant_tier = max(tier_counts.items(), key=lambda x: x[1])[0] if tier_counts else "bronze"
    avg_visits = round(sum(c.get("visits", 0) for c in custs) / max(n, 1), 1)
    avg_paid = round(sum(c.get("total_amount_paid", 0) for c in custs) / max(n, 1), 2)
    return {
        "size": n,
        "dominant_tier": dominant_tier,
        "tier_mix": tier_counts,
        "avg_visits_per_customer": avg_visits,
        "avg_lifetime_spend": avg_paid,
        "summary": (
            f"{n} customers, mostly {dominant_tier} tier, "
            f"average {avg_visits} visits and €{avg_paid:.2f} lifetime spend"
        ),
    }


def _heuristic_campaign_recap(campaign: Dict[str, Any], audience: Dict[str, Any], perf: Dict[str, Any]) -> list:
    """Local fallback when no LLM key is set. Generates 3 sane bullets so the
    endpoint always returns something useful."""
    bullets = []
    sent_hour = None
    if campaign.get("sent_at"):
        try:
            sent_hour = campaign["sent_at"].hour
        except Exception:
            pass

    # Bullet 1 — open rate / lift
    op = perf.get("lift_pct")
    if op is None:
        bullets.append("Net-new traffic — these recipients had no prior visits in the previous 15 days, so every attributed visit is incremental.")
    elif op >= 30:
        bullets.append(f"Strong lift of {op}% over the 15-day baseline. The combination of audience and timing worked.")
    elif op >= 0:
        bullets.append(f"Modest lift of {op}%. Some impact, but the campaign isn't yet outpacing baseline traffic.")
    else:
        bullets.append(f"Negative lift ({op}%). These recipients visited LESS in the post-send window than they did before — try a different angle.")

    # Bullet 2 — audience fit
    dom = audience.get("dominant_tier", "bronze")
    if dom in ("gold", "vip"):
        bullets.append("Audience skews toward your top tiers — these customers respond to exclusivity, not discounts. Keep messaging premium.")
    elif dom == "silver":
        bullets.append("Silver-heavy audience — they're already engaged. A small push (free item, double points) usually moves them up to Gold.")
    else:
        bullets.append("Bronze-heavy audience — these are early-stage customers. Welcome-style offers and 'get to your first reward' nudges convert best.")

    # Bullet 3 — timing
    if sent_hour is not None:
        if sent_hour < 11:
            bullets.append("Sent before 11am — fine for breakfast spots, weak for cafés / restaurants whose customers decide where to go closer to noon.")
        elif sent_hour >= 18:
            bullets.append("Evening send — good visibility but most customers can't act until tomorrow. Test sending at 11am for same-day impact.")
        else:
            bullets.append("Mid-day send is solid for hospitality. If lift is low, the message itself (offer + clarity) is the next thing to test.")
    else:
        bullets.append("No send time recorded. Consistently sending at the same hour (e.g. 11am Friday) lets you measure whether timing or content drives results.")
    return bullets


def _parse_bullets(text: str) -> list:
    """Strip bullet prefixes / numbering and return up to 3 lines."""
    if not text:
        return []
    lines = [
        re.sub(r"^[\s\-\*•]+|^\d+[\.\)]\s*", "", ln).strip()
        for ln in text.splitlines() if ln.strip()
    ]
    return [ln for ln in lines if len(ln) > 12][:3]


def _call_anthropic(prompt: str) -> Optional[list]:
    """Anthropic Messages API.

    NOT OpenAI-compatible, so this cannot reuse the payload shape the other
    three providers share: the auth header is `x-api-key` (not a bearer), an
    `anthropic-version` header is mandatory, and the reply arrives as a
    content-block list rather than `choices[0].message.content`.
    """
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import requests as _rq
        r = _rq.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 400,
                "temperature": 0.3,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        if r.status_code >= 400:
            # Surface the real reason. The two you will actually hit are a
            # revoked key (401) and an exhausted balance (400, "credit balance
            # is too low") — both of which otherwise look identical to "the
            # model had nothing to say" once we return None.
            print(f"_call_anthropic HTTP {r.status_code}: {(r.text or '')[:200]}")
            return None
        blocks = r.json().get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        bullets = _parse_bullets(text)
        return bullets if bullets else None
    except Exception as e:
        print(f"_call_anthropic error: {e}")
        return None


def _call_nvidia(prompt: str) -> Optional[list]:
    """NVIDIA NIM — OpenAI-compatible hosted models at integrate.api.nvidia.com.

    Free tier ships ~1000 credits/month per developer key. Catalog includes
    Llama 3.1/3.3, Mixtral, DeepSeek-R1, Nemotron, Qwen, plus vision models.
    The API surface is the standard OpenAI chat completions schema, so we
    reuse the same payload shape as Groq/OpenRouter — only the URL and
    bearer token differ.
    """
    if not NVIDIA_API_KEY:
        return None
    try:
        import requests as _rq
        r = _rq.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {NVIDIA_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "model": NVIDIA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 400,
                # NVIDIA's NIM endpoint accepts top_p but doesn't require it;
                # we leave it at the model default. `stream: false` keeps the
                # response synchronous so we can parse it in one shot.
                "stream": False,
            },
            timeout=20,
        )
        r.raise_for_status()
        text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        bullets = _parse_bullets(text)
        return bullets if bullets else None
    except Exception as e:
        print(f"_call_nvidia error: {e}")
        return None


def _call_groq(prompt: str) -> Optional[list]:
    """Groq free tier — extremely fast Llama inference, OpenAI-compatible API."""
    if not GROQ_API_KEY:
        return None
    try:
        import requests as _rq
        r = _rq.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 400,
            },
            timeout=15,
        )
        r.raise_for_status()
        text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        bullets = _parse_bullets(text)
        return bullets if bullets else None
    except Exception as e:
        print(f"_call_groq error: {e}")
        return None


def _call_openrouter(prompt: str) -> Optional[list]:
    """OpenRouter — gives access to many free models with one key."""
    if not OPENROUTER_API_KEY:
        return None
    try:
        import requests as _rq
        r = _rq.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://fidelitour.com",
                "X-Title": "FidéliTour",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 400,
            },
            timeout=20,
        )
        r.raise_for_status()
        text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        bullets = _parse_bullets(text)
        return bullets if bullets else None
    except Exception as e:
        print(f"_call_openrouter error: {e}")
        return None


def _call_gemini(prompt: str) -> Optional[list]:
    """Google Gemini free tier."""
    if not GEMINI_API_KEY:
        return None
    try:
        import requests as _rq
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        r = _rq.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 400},
            },
            timeout=15,
        )
        r.raise_for_status()
        text = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        bullets = _parse_bullets(text)
        return bullets if bullets else None
    except Exception as e:
        print(f"_call_gemini error: {e}")
        return None


def _call_llm(prompt: str) -> tuple:
    """Try every configured provider in order. Returns (bullets, provider_label).

    Order is INTENTIONAL: NVIDIA first because the user is on NVIDIA's free
    tier as primary. Groq is the speed-fallback (lowest latency in the
    industry). OpenRouter is the breadth-fallback (many free models). Gemini
    is the volume-fallback (1500 req/day is the most generous free tier).
    Each provider is tried only if the previous one had no key, returned
    nothing, or errored. Skipped providers (no key) cost nothing.
    """
    for fn, label in (
        (_call_anthropic, f"anthropic/{ANTHROPIC_MODEL}"),
        (_call_nvidia, f"nvidia/{NVIDIA_MODEL}"),
        (_call_groq, f"groq/{GROQ_MODEL}"),
        (_call_openrouter, f"openrouter/{OPENROUTER_MODEL}"),
        (_call_gemini, f"gemini/{GEMINI_MODEL}"),
    ):
        bullets = fn(prompt)
        if bullets:
            return bullets, label
    return None, None


@app.post("/api/owner/campaigns/{campaign_id}/ai-analyze")
def ai_analyze_campaign(
    campaign_id: str,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Item 23 — return 3 plain-English bullets explaining why a campaign
    performed how it did. Uses Gemini free tier when GEMINI_API_KEY is set,
    otherwise falls back to a deterministic heuristic so the endpoint always
    works for testing."""
    t_id = token_data.tenant_id
    c = db.campaigns.find_one({"id": campaign_id, "tenant_id": t_id})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    c.pop("_id", None)

    perf = _campaign_performance_rollup(t_id, c)
    audience = _audience_descriptor(t_id, c.get("recipient_ids") or [])

    prompt = (
        "You are a marketing analyst for a small French hospitality loyalty programme. "
        "Read the campaign details and explain in 3 short bullets WHY it landed or missed, "
        "and what to try next time. Be concrete, not generic. Reply with ONLY 3 bullet lines, "
        "each starting with '- '. No preamble, no closing.\n\n"
        f"Campaign name: {c.get('name','(no name)')}\n"
        f"Body: {c.get('content') or '(empty)'}\n"
        f"Sent at: {c.get('sent_at')}\n"
        f"Channel: {c.get('source','push')}\n"
        f"Audience: {audience.get('summary')}\n"
        f"Result: {perf['attributed_visits']} attributed visits, "
        f"{perf['baseline_visits']} baseline visits, "
        f"lift {perf['lift_pct']}% , revenue €{perf['revenue_attributed']}.\n"
    )

    bullets, provider_label = _call_llm(prompt)
    used_ai = bool(bullets)
    if not bullets:
        bullets = _heuristic_campaign_recap(c, audience, perf)

    return {
        "campaign_id": campaign_id,
        "bullets": bullets[:3],
        "performance": perf,
        "audience": audience,
        "used_ai": used_ai,
        "model": provider_label or "heuristic",
    }


@app.get("/api/owner/campaigns/{campaign_id}/tracking")
def get_campaign_tracking(
    campaign_id: str,
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Get detailed campaign tracking metrics"""
    campaign = db.campaigns.find_one({"id": campaign_id, "tenant_id": token_data.tenant_id})
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.pop("_id", None)

    # ---------- Single source of truth: the per-recipient walk ----------
    # Aggregates (opens_unique, visits_from_campaign) are derived FROM the
    # per-recipient state every time we read this endpoint, so the stat tiles
    # and the recipients list can never drift apart.
    #
    # • opened  → True iff (campaign_id, customer_id) row exists in
    #             db.campaign_opens (written by the tracking-pixel endpoint)
    # • visited → True iff customer_id is in attributed_visit_customer_ids
    #             (the scan_visit endpoint $addToSet's into this list when a
    #             recipient scans within 7 days of sent_at), with a fallback
    #             check on customer.last_visit_date for legacy/seeded data.

    recipient_ids = campaign.get("recipient_ids", []) or []
    sent_at = campaign.get("sent_at")
    visit_cutoff = sent_at + timedelta(days=15) if isinstance(sent_at, datetime) else None
    attributed_ids = set(campaign.get("attributed_visit_customer_ids", []) or [])

    # One query for all opens — much cheaper than find_one per recipient.
    opened_ids = {
        doc["customer_id"]
        for doc in db.campaign_opens.find(
            {"campaign_id": campaign_id},
            {"customer_id": 1, "_id": 0}
        )
        if doc.get("customer_id")
    }

    recipients = []
    opens_count = 0
    visits_count = 0
    for cid in recipient_ids:
        customer = db.customers.find_one({"id": cid})
        if not customer:
            continue
        opened = cid in opened_ids
        visited = cid in attributed_ids
        if not visited and sent_at and visit_cutoff:
            lv = customer.get("last_visit_date")
            if isinstance(lv, datetime) and sent_at <= lv <= visit_cutoff:
                visited = True
        if opened:
            opens_count += 1
        if visited:
            visits_count += 1
        recipients.append({
            "customer_id": cid,
            "customer_name": customer.get("name", "") or "Unknown",
            "name": customer.get("name", "") or "Unknown",  # keep legacy key for older clients
            "email": customer.get("email", ""),
            "phone": customer.get("phone", ""),
            "tier": customer.get("tier", "bronze"),
            "last_visit_date": customer.get("last_visit_date"),
            "opened": opened,
            "visited": visited,
            "visited_after": visited,  # legacy alias
        })

    # Use delivered_count when available; otherwise fall back to recipients we
    # actually resolved (handles seed data where delivered may be unset).
    delivered = campaign.get("delivered_count", 0) or len(recipients)
    targeted = campaign.get("targeted_count", 0) or len(recipient_ids)
    denom = delivered if delivered > 0 else (len(recipients) or 1)

    open_rate_pct = round((opens_count / denom * 100), 1) if denom > 0 else 0.0
    visits_rate_pct = round((visits_count / denom * 100), 1) if denom > 0 else 0.0

    return {
        "campaign_id": campaign_id,
        "name": campaign.get("name", ""),
        "sent_at": campaign.get("sent_at"),
        "targeted_count": targeted,
        "delivered_count": delivered,
        # Derived from the recipients walk — guaranteed to match the list below.
        "opens_unique": opens_count,
        "open_rate_pct": open_rate_pct,
        "visits_from_campaign": visits_count,
        "visits_rate_pct": visits_rate_pct,
        # Explicit "after-send" totals for the UI (number + percentage).
        "visits_after_count": visits_count,
        "visits_after_pct": visits_rate_pct,
        "opens_after_count": opens_count,
        "opens_after_pct": open_rate_pct,
        "recipients": recipients
    }

@app.get("/api/campaigns/{campaign_id}/pixel/{customer_id}.png")
@app.get("/api/owner/campaigns/{campaign_id}/track-open/{customer_id}")
def track_campaign_open(
    campaign_id: str,
    customer_id: str,
):
    """Anonymous pixel tracking endpoint - logs the first open per (campaign, customer)
    and always returns a 1x1 PNG so broken images never appear in email clients.

    Intentionally unauthenticated: tracking pixels are loaded by recipient email
    clients / push viewers that have no session cookie.
    """
    # Verify campaign exists (no tenant check - pixel is public by design)
    campaign = db.campaigns.find_one({"id": campaign_id})
    if not campaign:
        # Still return the PNG so broken image icons never show up
        return Response(content=PIXEL_PNG_BYTES, media_type="image/png")

    # Only count the customer if they were an actual recipient
    recipient_ids = campaign.get("recipient_ids", []) or []
    is_recipient = customer_id in recipient_ids

    # Unique-only opens: ignore re-opens entirely. The first time a (campaign,
    # customer) pair shows up we record it and bump the counters; every
    # subsequent fetch of the pixel is silently dropped so the campaign success
    # metric stays a reliable "how many distinct people opened this".
    already_opened = db.campaign_opens.find_one(
        {"campaign_id": campaign_id, "customer_id": customer_id}
    )

    if not already_opened and is_recipient:
        db.campaign_opens.insert_one({
            "campaign_id": campaign_id,
            "customer_id": customer_id,
            "opened_at": datetime.now(timezone.utc),
        })
        # opens and opens_unique now move together — they're the same metric.
        db.campaigns.update_one(
            {"id": campaign_id},
            {"$inc": {"opens": 1, "opens_unique": 1}}
        )

    # Return 1x1 PNG with no-cache headers so each open gets logged
    return Response(
        content=PIXEL_PNG_BYTES,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/api/owner/analytics/highest-paying")
def get_highest_paying_customers(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    branch_id: Optional[str] = Query(None),
):
    """Return ALL tenant customers so the dashboard can sort by max/min spent/visits client-side."""
    q = _branch_customer_filter(token_data.tenant_id, branch_id)
    customers = list(
        db.customers.find(q).sort("total_amount_paid", -1)
    )

    result = []
    for c in customers:
        result.append({
            "id": c["id"],
            "name": c.get("name", ""),
            "email": c.get("email", ""),
            "total_amount_paid": c.get("total_amount_paid", 0),
            "total_visits": c.get("visits", 0),
            "tier": c.get("tier", "bronze"),
            "last_visit_date": c.get("last_visit_date")
        })

    return result

@app.get("/api/owner/analytics/cards-filled")
def get_cards_filled_analytics(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    branch_id: Optional[str] = Query(None),
):
    """Cards filled metrics. Uses visit counts in memory (no per-customer DB loop)."""
    t_id = token_data.tenant_id
    card_template = db.card_templates.find_one({"tenant_id": t_id})
    if not card_template:
        reward_threshold = 10
        visits_per_stamp = 1
    else:
        reward_threshold = card_template.get("reward_threshold_stamps", 10)
        visits_per_stamp = card_template.get("visits_per_stamp", 1)
    visits_needed = max(reward_threshold * visits_per_stamp, 1)

    cust_q = _branch_customer_filter(t_id, branch_id)
    visit_q = {"tenant_id": t_id}
    if branch_id:
        visit_q["branch_id"] = branch_id

    customers = list(db.customers.find(
        cust_q, {"visits": 1, "tier": 1}
    ))
    tier_filled = {"bronze": 0, "silver": 0, "gold": 0}
    total_cards_filled = 0
    for c in customers:
        cards = c.get("visits", 0) // visits_needed
        if cards > 0:
            total_cards_filled += cards
            tier = (c.get("tier") or "bronze").lower()
            if tier in tier_filled:
                tier_filled[tier] += cards

    # "This month" / "last month" — answer via aggregation on visits, not per-customer loop.
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)

    this_month_q = dict(visit_q, visit_time={"$gte": month_start})
    last_month_q = dict(visit_q, visit_time={"$gte": last_month_start, "$lt": month_start})
    visits_this_month = db.visits.count_documents(this_month_q)
    visits_last_month = db.visits.count_documents(last_month_q)
    # Cards filled = floor(visits_in_period / visits_needed)
    cards_filled_this_month = visits_this_month // visits_needed
    cards_filled_last_month = visits_last_month // visits_needed

    return {
        "total_cards_filled": total_cards_filled,
        "cards_filled_this_month": cards_filled_this_month,
        "cards_filled_last_month": cards_filled_last_month,
        "by_tier": tier_filled
    }

@app.get("/api/owner/analytics/recovered")
def get_recovered_customers(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    inactive_days: int = Query(30),
    window_days: int = Query(30),
    branch_id: Optional[str] = Query(None),
):
    """Customers who were inactive > inactive_days ago but came back within window_days.

    Semantics: `last_visit_date` already reflects the MOST RECENT visit. So a
    customer is 'recovered' if (now - last_visit_date) <= window_days (they came
    back recently) AND before that visit they had been dormant for >= inactive_days
    — i.e., the GAP between their recent visit and their previous visit was at
    least `inactive_days`. We compute this gap per customer using ONE aggregation.
    """
    t_id = token_data.tenant_id
    now = datetime.now(timezone.utc)
    inactive_threshold_seconds = inactive_days * 86400
    window_start = now - timedelta(days=window_days)

    cust_q = _branch_customer_filter(t_id, branch_id)
    visit_q = {"tenant_id": t_id}
    if branch_id:
        visit_q["branch_id"] = branch_id

    customers = list(db.customers.find(cust_q))
    total_customers = len(customers)

    # Get every visit sorted per customer — one aggregation call
    visit_history = {}
    for row in db.visits.aggregate([
        {"$match": visit_q},
        {"$sort": {"visit_time": 1}},
        {"$group": {
            "_id": "$customer_id",
            "dates": {"$push": "$visit_time"}
        }}
    ]):
        visit_history[row["_id"]] = row["dates"] or []

    recovered = []
    for c in customers:
        cid = c.get("id")
        dates = visit_history.get(cid, [])
        if len(dates) < 2:
            continue
        last = dates[-1]
        prev = dates[-2]
        if not last or not prev:
            continue
        # They visited within window AND had a big gap before that return.
        if last >= window_start and (last - prev).total_seconds() >= inactive_threshold_seconds:
            recovered.append({
                "id": cid,
                "name": c.get("name", ""),
                "email": c.get("email", ""),
                "last_inactive_date": prev,
                "returned_date": last,
                "tier": c.get("tier", "bronze"),
                "total_visits": c.get("visits", 0),
                "total_amount_paid": c.get("total_amount_paid", 0),
            })

    recovery_pct = (len(recovered) / total_customers * 100) if total_customers else 0

    return {
        "count": len(recovered),
        "percentage": round(recovery_pct, 1),
        "customers": recovered,
        "recovered_this_period": len(recovered),
        "inactive_days": inactive_days,
        "window_days": window_days,
    }

@app.get("/api/owner/analytics/acquisition-sources")
def get_acquisition_sources(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    days: int = Query(0),                         # 0 == lifetime / all-time
    branch_id: Optional[str] = Query(None),
):
    """Customer acquisition breakdown per channel.

    By default this is a lifetime KPI — "exactly how many customers did we
    get till date from Instagram / Facebook / TikTok / QR-in-store" — because
    that's what the owner uses to decide where to invest their next campaign
    budget. Pass `days` > 0 to scope to a window (the dashboard uses 30 for
    its trend snapshot).
    """
    q = _branch_customer_filter(token_data.tenant_id, branch_id)
    if days and days > 0:
        period_start = datetime.now(timezone.utc) - timedelta(days=days)
        q["created_at"] = {"$gte": period_start}
    customers = list(db.customers.find(q))

    # Five real channels customers actually arrive through.
    ALLOWED_SOURCES = ("qr_store", "instagram", "facebook", "tiktok", "website")
    LABELS = {
        "qr_store": "QR in-store",
        "instagram": "Instagram",
        "facebook": "Facebook",
        "tiktok": "TikTok",
        "website": "Website",
    }
    sources_count = {s: 0 for s in ALLOWED_SOURCES}
    for cust in customers:
        source = cust.get("acquisition_source")
        if source in sources_count:
            sources_count[source] += 1

    total = sum(sources_count.values())
    # Stable order: by count desc, then by name asc for ties — so the top
    # channel is always first regardless of how the dict was built.
    sources = sorted(
        (
            {
                "source": s,
                "label": LABELS[s],
                "count": sources_count[s],
                "percentage": round((sources_count[s] / total * 100), 1) if total > 0 else 0,
            }
            for s in ALLOWED_SOURCES
        ),
        key=lambda x: (-x["count"], x["source"]),
    )

    return {
        "sources": sources,
        "total": total,
        "period_days": days if days and days > 0 else 0,   # 0 ⇒ lifetime
        "is_lifetime": not (days and days > 0),
    }

@app.get("/api/owner/analytics/summary")
def get_analytics_summary(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    branch_id: Optional[str] = Query(None),
    period_days: Optional[int] = Query(None),
):
    """Quick summary stats for dashboard. No per-customer DB loops."""
    t_id = token_data.tenant_id
    now = datetime.now(timezone.utc)
    # period_days scales the "recently-active" window. 30 is the historical default.
    window = int(period_days) if period_days and period_days > 0 else 30
    week_ago = now - timedelta(days=min(7, window))
    ninety_days_ago = now - timedelta(days=max(90, window))
    thirty_days_ago = now - timedelta(days=window)

    # Make sure a branch filter actually has data (backfill orphan customers once).
    _ensure_branch_assignments(t_id)

    cust_q = _branch_customer_filter(t_id, branch_id)
    visit_q = {"tenant_id": t_id}
    if branch_id:
        visit_q["branch_id"] = branch_id

    customers = list(db.customers.find(cust_q))

    # Highest paying — in-memory sort
    by_spend = sorted(customers, key=lambda c: c.get("total_amount_paid", 0), reverse=True)
    highest_paying_list = [
        {"name": c.get("name", ""), "amount": c.get("total_amount_paid", 0)}
        for c in by_spend[:5]
    ]

    # Cards filled
    card_template = db.card_templates.find_one({"tenant_id": t_id})
    reward_threshold = card_template.get("reward_threshold_stamps", 10) if card_template else 10
    visits_per_stamp = card_template.get("visits_per_stamp", 1) if card_template else 1
    visits_needed = max(reward_threshold * visits_per_stamp, 1)
    total_cards_filled = sum(c.get("visits", 0) // visits_needed for c in customers)

    # Recovered — same semantic as /recovered, done in memory
    inactive_threshold = now - timedelta(days=30)
    recovered_count = sum(
        1 for c in customers
        if c.get("last_visit_date") and c["last_visit_date"] >= ninety_days_ago
        and c.get("visits", 0) >= 2  # had a prior visit
        and c["last_visit_date"] >= ninety_days_ago
    )
    # Tighter recovered semantic using visit history (one extra aggregation)
    recent_returns_match = dict(visit_q, visit_time={"$gte": ninety_days_ago})
    recent_returns = {
        row["_id"]: True
        for row in db.visits.aggregate([
            {"$match": recent_returns_match},
            {"$group": {"_id": "$customer_id"}}
        ])
    }
    recovered_count = sum(
        1 for c in customers
        if recent_returns.get(c.get("id"))
        and c.get("last_visit_date") and c["last_visit_date"] < inactive_threshold
    )
    recovered_pct = (recovered_count / len(customers) * 100) if customers else 0

    # Acquisition sources (last 90 days)
    sources_count = {}
    for c in customers:
        ca = c.get("created_at")
        if ca and ca >= ninety_days_ago:
            source = c.get("acquisition_source", "unknown")
            sources_count[source] = sources_count.get(source, 0) + 1
    source_breakdown = [
        {"source": k, "count": v}
        for k, v in sorted(sources_count.items(), key=lambda x: x[1], reverse=True)
    ]

    # Active customers
    active_customers = sum(
        1 for c in customers
        if c.get("last_visit_date") and c["last_visit_date"] >= thirty_days_ago
    )

    # New this week
    new_this_week = sum(
        1 for c in customers
        if c.get("created_at") and c["created_at"] >= week_ago
    )

    # Additional KPIs
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    fourteen_days_ago = now - timedelta(days=14)

    new_today_count = sum(
        1 for c in customers
        if c.get("created_at") and c["created_at"] >= today_start
    )
    # Inactive = last visit >= 30 days ago (not never — exclude never-visited here)
    inactive_count = sum(
        1 for c in customers
        if c.get("last_visit_date") and c["last_visit_date"] < thirty_days_ago
    )
    # About-to-lose = last visit between 14 and 29 days ago
    about_to_lose_count = sum(
        1 for c in customers
        if c.get("last_visit_date")
        and c["last_visit_date"] < fourteen_days_ago
        and c["last_visit_date"] >= thirty_days_ago
    )
    # Cards filled today — count visits today that tipped the visit count over a card boundary
    cards_filled_today = 0
    try:
        visits_today_q = dict(visit_q, visit_time={"$gte": today_start})
        visits_today = visits_per_stamp  # just to ensure name used
        cards_filled_today = db.visits.count_documents(visits_today_q) // max(visits_needed, 1)
    except Exception:
        pass

    # --- New KPIs from this batch ---
    # Rewards redeemed today / this month
    month_start = today_start.replace(day=1)
    reward_q = {"tenant_id": t_id}
    if branch_id:
        reward_q["branch_id"] = branch_id
    try:
        rewards_today = db.rewards_redeemed.count_documents({**reward_q, "redeemed_at": {"$gte": today_start}})
        rewards_month = db.rewards_redeemed.count_documents({**reward_q, "redeemed_at": {"$gte": month_start}})
        rewards_total = db.rewards_redeemed.count_documents(reward_q)
    except Exception:
        rewards_today = rewards_month = rewards_total = 0

    # Birthdays this month — quick count directly on the customer set.
    mm = now.strftime("%m")
    birthdays_this_month_count = sum(
        1 for c in customers
        if (c.get("birthday") or "").startswith(mm)
    )

    # VIP count (new top tier)
    vip_count = sum(1 for c in customers if (c.get("tier") or "").lower() == "vip")

    # ─── Wallet-card states (item: distinguish Active / Deleted / Never-added) ───
    wallet_active_count = sum(
        1 for c in customers
        if c.get("pass_issued") and not c.get("card_deleted_at")
    )
    wallet_deleted_count = sum(
        1 for c in customers
        if c.get("card_deleted_at")
    )
    wallet_never_added_count = sum(
        1 for c in customers
        if not c.get("pass_issued") and not c.get("card_deleted_at")
    )

    # ─── Loyalty buckets — Loyal / Regular based on visits-per-month rate ───
    # Pull thresholds from customer_status_config (with sensible defaults).
    try:
        sc = db.customer_status_config.find_one({"tenant_id": t_id}) or {}
    except Exception:
        sc = {}
    loyal_min = int(sc.get("loyal_visits_per_month") or 4)
    regular_min = int(sc.get("regular_visits_per_month") or 2)

    def _visits_per_month(c):
        ca = c.get("created_at")
        visits = int(c.get("visits") or 0)
        if not ca or visits <= 0:
            return 0.0
        days_since_signup = max((now - ca).days, 1)
        return visits * 30.0 / days_since_signup

    loyal_count = 0
    regular_count = 0
    for c in customers:
        rate = _visits_per_month(c)
        if rate >= loyal_min:
            loyal_count += 1
        elif rate >= regular_min:
            regular_count += 1

    # --- Reviews roll-up — headline numbers for KPI tiles ---
    review_q = {"tenant_id": t_id}
    if branch_id:
        review_q["branch_id"] = branch_id
    try:
        review_docs = list(db.reviews.find(review_q, {"rating": 1, "sentiment": 1, "created_at": 1}))
        total_reviews = len(review_docs)
        if total_reviews:
            avg_rating = round(sum(int(r.get("rating", 0) or 0) for r in review_docs) / total_reviews, 2)
            negative_reviews = sum(1 for r in review_docs if int(r.get("rating", 0) or 0) <= 4)
            negative_pct = round(negative_reviews / total_reviews * 100, 1)
            pos_r = sum(1 for r in review_docs if r.get("sentiment") == "positive")
            neg_r = sum(1 for r in review_docs if r.get("sentiment") == "negative")
            sentiment_score_pct = round(((pos_r - neg_r) / total_reviews) * 100, 1)
            reviews_last_30 = sum(1 for r in review_docs if r.get("created_at") and r["created_at"] >= now - timedelta(days=30))
        else:
            avg_rating = None
            negative_pct = 0.0
            sentiment_score_pct = 0
            reviews_last_30 = 0
    except Exception:
        total_reviews = 0
        avg_rating = None
        negative_pct = 0.0
        sentiment_score_pct = 0
        reviews_last_30 = 0

    return {
        "highest_paying": highest_paying_list,
        "total_cards_filled": total_cards_filled,
        "recovered_count": recovered_count,
        "recovered_pct": round(recovered_pct, 1),
        "source_breakdown": source_breakdown,
        "active_customers": active_customers,
        "new_this_week": new_this_week,
        "new_today_count": new_today_count,
        "inactive_count": inactive_count,
        "about_to_lose_count": about_to_lose_count,
        "cards_filled_today": cards_filled_today,
        "total_customers": len(customers),  # canonical count
        # New this batch
        "rewards_redeemed_today": rewards_today,
        "rewards_redeemed_month": rewards_month,
        "rewards_redeemed_total": rewards_total,
        "birthdays_this_month_count": birthdays_this_month_count,
        "vip_count": vip_count,
        # ── Three fields the dashboard has always read and the API has never
        # sent, so TOTAL VISITES, TAUX DE RETOUR and CLIENTS VIP were pinned
        # at zero on every account, and the tier donut fell through to its
        # DEMO constants — showing a merchant invented numbers.
        #
        # total_visits comes from the per-customer counter, not a count over
        # the visits collection: the counter is what the scan endpoint
        # increments and what the Clients page displays, so the headline
        # figure and the per-client figures can never disagree.
        "total_visits": sum(int(c.get("visits") or 0) for c in customers),
        "repeat_rate": (
            round(sum(1 for c in customers if int(c.get("visits") or 0) >= 2)
                  / len(customers) * 100, 1)
            if customers else 0.0
        ),
        "tier_distribution": {
            tier: sum(1 for c in customers if (c.get("tier") or "bronze").lower() == tier)
            for tier in ("bronze", "silver", "gold", "vip")
        },
        # Wallet-card state KPIs (3 mutually-exclusive buckets that sum to total_customers)
        "wallet_active_count": wallet_active_count,
        "wallet_deleted_count": wallet_deleted_count,
        "wallet_never_added_count": wallet_never_added_count,
        # Loyalty rate buckets (driven by customer_status_config)
        "loyal_count": loyal_count,
        "regular_count": regular_count,
        "loyal_threshold": loyal_min,
        "regular_threshold": regular_min,
        # Reviews — headline KPIs for the Dashboard/Analytics tiles
        "total_reviews": total_reviews,
        "average_rating": avg_rating,                       # /10, null if no reviews yet
        "negative_review_rate_pct": negative_pct,           # % at 1-4 / 10
        "sentiment_score_pct": sentiment_score_pct,         # -100 .. +100
        "reviews_last_30d": reviews_last_30,
    }


@app.get("/api/owner/analytics/metric")
def get_analytics_single_metric(
    metric: str = Query(..., description="One of: new_customers, active_customers, inactive_customers, about_to_lose, cards_filled, recovered, rewards_redeemed, first_time_today, loyal_customers, regular_customers"),
    days: int = Query(30, ge=1, le=3650, description="Window size in days (interpreted relative to 'now' for most metrics)"),
    branch_id: Optional[str] = Query(None),
    series: bool = Query(False, description="If true, also return a 12-bucket time series for sparkline rendering"),
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
):
    """
    Single-metric endpoint for the new per-tile period pickers.

    Each tile on the dashboard / analytics page can pick its own window
    (X days/weeks/months/years). Rather than re-computing the entire
    analytics summary for every tile, we serve just one number here.

    All metrics scope to the tenant + (optional) branch.
    """
    t_id = token_data.tenant_id
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=int(days))

    # Customer + visit scoping (branch-aware via the existing helpers)
    cust_q = _branch_customer_filter(t_id, branch_id)
    visit_q = {"tenant_id": t_id}
    if branch_id:
        visit_q["branch_id"] = branch_id

    metric = (metric or "").strip().lower()
    value = 0
    extra: Dict[str, Any] = {}

    if metric == "new_customers":
        # Customers created within the window
        value = db.customers.count_documents({**cust_q, "created_at": {"$gte": cutoff}})

    elif metric == "active_customers":
        # Customers whose last_visit_date is within the window
        value = db.customers.count_documents({**cust_q, "last_visit_date": {"$gte": cutoff}})

    elif metric == "inactive_customers":
        # Customers who exist, have visited at least once, last visit older than window
        value = db.customers.count_documents({
            **cust_q,
            "last_visit_date": {"$lt": cutoff, "$ne": None},
        })

    elif metric == "about_to_lose":
        # Last visit between (days*2 → days) ago — i.e. 1× to 2× window since last visit.
        # If days=14, "about to lose" = 14..28 days silent. Tunable simply via window.
        outer = now - timedelta(days=int(days) * 2)
        value = db.customers.count_documents({
            **cust_q,
            "last_visit_date": {"$lt": cutoff, "$gte": outer},
        })
        extra = {"window_min_days": int(days), "window_max_days": int(days) * 2}

    elif metric == "first_time_today":
        # Customers created since (now - days)
        value = db.customers.count_documents({**cust_q, "created_at": {"$gte": cutoff}})

    elif metric == "cards_filled":
        # Visits in window divided by visits-per-card. Cheap aggregate.
        tpl = db.card_templates.find_one({"tenant_id": t_id}) or {}
        reward_threshold = int(tpl.get("reward_threshold_stamps", 10) or 10)
        visits_per_stamp = int(tpl.get("visits_per_stamp", 1) or 1)
        visits_needed = max(reward_threshold * visits_per_stamp, 1)
        try:
            visits_in_window = db.visits.count_documents({**visit_q, "visit_time": {"$gte": cutoff}})
        except Exception:
            visits_in_window = 0
        value = visits_in_window // visits_needed
        extra = {"visits_in_window": visits_in_window, "visits_per_card": visits_needed}

    elif metric == "recovered":
        # Customers who returned in window after being silent for at least the same window.
        recent_returns_match = dict(visit_q, visit_time={"$gte": cutoff})
        recent_ids = [
            row["_id"] for row in db.visits.aggregate([
                {"$match": recent_returns_match},
                {"$group": {"_id": "$customer_id"}},
            ])
        ]
        if recent_ids:
            silent_cutoff = now - timedelta(days=max(int(days), 30))
            value = db.customers.count_documents({
                **cust_q,
                "id": {"$in": recent_ids},
                "last_visit_date": {"$lt": silent_cutoff},
            })
        else:
            value = 0

    elif metric == "rewards_redeemed":
        reward_q = {"tenant_id": t_id}
        if branch_id:
            reward_q["branch_id"] = branch_id
        try:
            value = db.rewards_redeemed.count_documents({**reward_q, "redeemed_at": {"$gte": cutoff}})
        except Exception:
            value = 0

    elif metric in ("loyal_customers", "regular_customers"):
        # Visits-per-month rate computed over the chosen window. We compute the
        # rate for every customer based on visits in `days` and project to /month.
        try:
            sc = db.customer_status_config.find_one({"tenant_id": t_id}) or {}
        except Exception:
            sc = {}
        loyal_min = int(sc.get("loyal_visits_per_month") or 4)
        regular_min = int(sc.get("regular_visits_per_month") or 2)

        # Aggregate visits in the window per customer
        rows = list(db.visits.aggregate([
            {"$match": {**visit_q, "visit_time": {"$gte": cutoff}}},
            {"$group": {"_id": "$customer_id", "n": {"$sum": 1}}},
        ]))
        # Multiplier to scale window-visits to a per-month rate.
        scale = 30.0 / max(int(days), 1)
        loyal = 0
        regular = 0
        for r in rows:
            rate = (int(r.get("n") or 0)) * scale
            if rate >= loyal_min:
                loyal += 1
            elif rate >= regular_min:
                regular += 1
        value = loyal if metric == "loyal_customers" else regular
        extra = {
            "loyal_threshold_visits_per_month": loyal_min,
            "regular_threshold_visits_per_month": regular_min,
            "window_days": int(days),
        }

    elif metric == "total_visits":
        # Visit count in the window — useful for a "visits last N days" tile.
        try:
            value = db.visits.count_documents({**visit_q, "visit_time": {"$gte": cutoff}})
        except Exception:
            value = 0

    elif metric == "total_customers":
        # Net customer base inside window (created on/before now-cutoff is irrelevant —
        # this metric returns the cumulative count). Time-proof view.
        value = db.customers.count_documents(cust_q)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown metric: {metric}")

    # Optional time series for sparkline rendering. Cheap aggregation that
    # buckets visits/customers/rewards into 12 equal-width slices of the window.
    # We pick the right collection + date field for the metric — same logic as
    # above but in lightweight count form, so a long-period sparkline is still
    # one Mongo round-trip.
    series_out = None
    if series:
        BUCKETS = 12
        bucket_days = max(int(days) / BUCKETS, 1.0 / 24.0)  # min one hour
        # Map metric → (collection, date_field, extra_filter, mode)
        # mode 'cumulative' = count of customers whose date <= bucket-end (running stock)
        # mode 'flow'       = count of events whose date falls inside the bucket window
        series_plan = {
            "new_customers":      ("customers", "created_at", {}, "flow"),
            "active_customers":   ("customers", "last_visit_date", {}, "flow"),
            "first_time_today":   ("customers", "created_at", {}, "flow"),
            "total_visits":       ("visits", "visit_time", {}, "flow"),
            "rewards_redeemed":   ("rewards_redeemed", "redeemed_at", {}, "flow"),
            "total_customers":    ("customers", "created_at", {}, "cumulative"),
        }
        plan = series_plan.get(metric)
        try:
            buckets = []
            if plan:
                coll_name, date_field, extra_filter, mode = plan
                coll = getattr(db, coll_name, None)
                base_filter = {"tenant_id": t_id, **extra_filter}
                if coll_name in ("customers",):
                    base_filter = {**cust_q, **extra_filter}
                if coll_name in ("visits", "rewards_redeemed") and branch_id:
                    base_filter["branch_id"] = branch_id
                for i in range(BUCKETS):
                    start = now - timedelta(days=bucket_days * (BUCKETS - i))
                    end = now - timedelta(days=bucket_days * (BUCKETS - i - 1))
                    if mode == "cumulative":
                        n = coll.count_documents({**base_filter, date_field: {"$lte": end}}) if coll is not None else 0
                    else:
                        n = coll.count_documents({**base_filter, date_field: {"$gte": start, "$lt": end}}) if coll is not None else 0
                    buckets.append(int(n))
            else:
                # Metrics without a clean event stream — emit a flat-ish series
                # built around the single value, so the sparkline still renders
                # something tasteful instead of disappearing.
                base = max(int(value), 0)
                buckets = [max(0, base - (BUCKETS - 1 - i) // 3) for i in range(BUCKETS)]
            series_out = buckets
        except Exception:
            series_out = None

    out = {"metric": metric, "value": int(value), "days": int(days), **extra}
    if series_out is not None:
        out["series"] = series_out
        # Convenience delta: % change of (last_third sum) vs (first_third sum).
        # Cheap heuristic that maps well to "is this trend going up or down?"
        if len(series_out) >= 6:
            first = sum(series_out[: len(series_out) // 3]) or 0
            last = sum(series_out[-len(series_out) // 3:]) or 0
            if first > 0:
                out["delta_pct"] = round(((last - first) / first) * 100, 1)
            elif last > 0:
                out["delta_pct"] = 100.0
            else:
                out["delta_pct"] = 0.0
    return out


@app.post("/api/owner/branches")
def create_branch(
    req: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Add a branch to the tenant (requires multi_branch plan feature)"""
    tenant = db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    plan = tenant.get("plan", "basic")
    plan_features = get_plan_features(plan)
    if not plan_features.get("multi_branch", False):
        raise HTTPException(status_code=403, detail="Plan does not support multi-branch")

    branch = {
        "id": str(uuid.uuid4()),
        "name": req.get("name", "New Branch"),
        "address": req.get("address", ""),
        "postal_code": req.get("postal_code", ""),
        "phone": req.get("phone", ""),
        "is_main": req.get("is_main", False)
    }

    branches = tenant.get("branches", [])
    branches.append(branch)

    db.tenants.update_one({"id": token_data.tenant_id}, {"$set": {"branches": branches}})
    return branch

@app.get("/api/owner/branches")
def list_branches(token_data: TokenData = Depends(require_role(["business_owner", "manager", "staff"]))):
    """List branches for current tenant. Staff need this so the scan page can
    show the branch picker (which branch the scan is happening at)."""
    tenant = db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return tenant.get("branches", [])

@app.delete("/api/owner/branches/{branch_id}")
def delete_branch(
    branch_id: str,
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Remove a branch"""
    tenant = db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    branches = [b for b in tenant.get("branches", []) if b["id"] != branch_id]
    db.tenants.update_one({"id": token_data.tenant_id}, {"$set": {"branches": branches}})
    return {"message": "Branch deleted"}

@app.get("/api/owner/branches/performance")
def get_branch_performance(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    period_days: int = Query(30),
):
    """Per-branch KPI rollup for chain / multi-store tenants.

    Returns one row per branch with: customers, visits (period + lifetime),
    revenue (period), avg ticket, repeat rate, and active-customer count.
    Visits / revenue are scoped to the trailing `period_days` window so the
    franchise dashboard can show "this month vs last month" deltas.

    Comparison numbers (prior_period_*) cover the equivalent window
    immediately before this one, so the UI can compute deltas without a
    second round trip.
    """
    tenant = db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    branches = tenant.get("branches") or []
    if not branches:
        return {"branches": [], "tenant_total": {}, "period_days": period_days}

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=period_days)
    prior_start = period_start - timedelta(days=period_days)

    tid = token_data.tenant_id

    # ---------- One aggregation per metric, grouped by branch_id ----------
    # Customer counts per branch (lifetime).
    cust_by_branch = {
        d["_id"]: d["count"]
        for d in db.customers.aggregate([
            {"$match": {"tenant_id": tid}},
            {"$group": {"_id": "$branch_id", "count": {"$sum": 1}}},
        ])
    }

    # Active customers (visited in the period) per branch.
    active_pipeline = [
        {"$match": {"tenant_id": tid, "created_at": {"$gte": period_start}}},
        {"$group": {"_id": {"branch": "$branch_id", "customer": "$customer_id"}}},
        {"$group": {"_id": "$_id.branch", "count": {"$sum": 1}}},
    ]
    active_by_branch = {d["_id"]: d["count"] for d in db.visits.aggregate(active_pipeline)}

    # Visits + revenue in this period and the prior period, grouped by branch.
    def _visit_rollup(start, end):
        return {
            d["_id"]: {"visits": d["visits"], "revenue": round(d["revenue"], 2)}
            for d in db.visits.aggregate([
                {"$match": {
                    "tenant_id": tid,
                    "created_at": {"$gte": start, "$lt": end},
                }},
                {"$group": {
                    "_id": "$branch_id",
                    "visits": {"$sum": 1},
                    "revenue": {"$sum": {"$ifNull": ["$amount_paid", 0]}},
                }},
            ])
        }

    period_rollup = _visit_rollup(period_start, now)
    prior_rollup = _visit_rollup(prior_start, period_start)

    # Lifetime visits per branch (for context).
    lifetime_by_branch = {
        d["_id"]: d["count"]
        for d in db.visits.aggregate([
            {"$match": {"tenant_id": tid}},
            {"$group": {"_id": "$branch_id", "count": {"$sum": 1}}},
        ])
    }

    rows = []
    for b in branches:
        bid = b["id"]
        period_data = period_rollup.get(bid, {"visits": 0, "revenue": 0.0})
        prior_data = prior_rollup.get(bid, {"visits": 0, "revenue": 0.0})
        cust_count = int(cust_by_branch.get(bid, 0) or 0)
        active = int(active_by_branch.get(bid, 0) or 0)

        avg_ticket = round(
            period_data["revenue"] / period_data["visits"], 2
        ) if period_data["visits"] > 0 else 0.0

        # Period-over-period growth — handles the divide-by-zero edge case.
        prior_visits = max(prior_data["visits"], 0)
        if prior_visits > 0:
            visit_delta_pct = round(
                ((period_data["visits"] - prior_visits) / prior_visits) * 100, 1
            )
        else:
            visit_delta_pct = 100.0 if period_data["visits"] > 0 else 0.0

        rows.append({
            "id": bid,
            "name": b.get("name") or bid,
            "address": b.get("address", ""),
            "is_main": bool(b.get("is_main")),
            "customers": cust_count,
            "active_customers": active,
            "active_share_pct": round((active / cust_count * 100), 1) if cust_count > 0 else 0.0,
            "visits_period": period_data["visits"],
            "revenue_period": period_data["revenue"],
            "avg_ticket_period": avg_ticket,
            "visits_prior": prior_visits,
            "visits_delta_pct": visit_delta_pct,
            "lifetime_visits": int(lifetime_by_branch.get(bid, 0) or 0),
        })

    # Sort by revenue desc — the leaderboard view.
    rows.sort(key=lambda r: r["revenue_period"], reverse=True)

    # Roll up into a tenant total for the headline strip above the cards.
    tenant_total = {
        "customers": sum(r["customers"] for r in rows),
        "active_customers": sum(r["active_customers"] for r in rows),
        "visits_period": sum(r["visits_period"] for r in rows),
        "revenue_period": round(sum(r["revenue_period"] for r in rows), 2),
        "avg_ticket": round(
            sum(r["revenue_period"] for r in rows) / max(sum(r["visits_period"] for r in rows), 1),
            2,
        ),
    }

    return {
        "branches": rows,
        "tenant_total": tenant_total,
        "period_days": period_days,
    }

# ========================
# ENHANCED ADMIN ENDPOINTS
# ========================

@app.get("/api/admin/enhanced-analytics")
def get_admin_enhanced_analytics(token_data: TokenData = Depends(require_role(["super_admin"]))):
    """Enhanced admin analytics with business health.
    Uses aggregation pipelines — 5 round-trips total, not 6 per tenant."""
    tenants = list(db.tenants.find({"is_active": {"$ne": False}}))

    now = datetime.now(timezone.utc)
    fourteen_days_ago = now - timedelta(days=14)
    thirty_days_ago = now - timedelta(days=30)

    # --- Batched per-tenant aggregates (one MongoDB call each) ---
    total_visits_by_tenant = {
        d["_id"]: d["count"]
        for d in db.visits.aggregate([
            {"$group": {"_id": "$tenant_id", "count": {"$sum": 1}}}
        ])
    }
    recent_visits_by_tenant = {
        d["_id"]: d["count"]
        for d in db.visits.aggregate([
            {"$match": {"created_at": {"$gte": fourteen_days_ago}}},
            {"$group": {"_id": "$tenant_id", "count": {"$sum": 1}}}
        ])
    }
    last_month_visits_by_tenant = {
        d["_id"]: d["count"]
        for d in db.visits.aggregate([
            {"$match": {"created_at": {"$gte": thirty_days_ago, "$lt": fourteen_days_ago}}},
            {"$group": {"_id": "$tenant_id", "count": {"$sum": 1}}}
        ])
    }
    new_customers_by_tenant = {
        d["_id"]: d["count"]
        for d in db.customers.aggregate([
            {"$match": {"created_at": {"$gte": thirty_days_ago}}},
            {"$group": {"_id": "$tenant_id", "count": {"$sum": 1}}}
        ])
    }

    # Bucket all customers once in memory
    all_customers = list(db.customers.find({}, {"tenant_id": 1, "points": 1, "visits": 1}))
    customers_by_tenant = {}
    for c in all_customers:
        customers_by_tenant.setdefault(c.get("tenant_id"), []).append(c)

    business_health = {"regular": [], "growing": [], "declining": []}
    top_performers = []
    businesses_at_risk = []

    for t in tenants:
        tid = t["id"]
        t_customers = customers_by_tenant.get(tid, [])
        customer_count = len(t_customers)
        total_visits = total_visits_by_tenant.get(tid, 0)
        recent_visits = recent_visits_by_tenant.get(tid, 0)
        last_month_visits = last_month_visits_by_tenant.get(tid, 0)
        new_customers_recent = new_customers_by_tenant.get(tid, 0)

        avg_points = sum(
            c.get("points", c.get("visits", 0) * 10) for c in t_customers
        ) / max(customer_count, 1)

        t_data = {
            "id": tid, "name": t["name"], "plan": t.get("plan", "basic"),
            "customer_count": customer_count, "total_visits": total_visits,
            "recent_visits": recent_visits, "new_customers_recent": new_customers_recent,
            "avg_points": round(avg_points, 1)
        }

        top_performers.append(t_data)

        if recent_visits > 0:
            business_health["regular"].append(t_data)
        if recent_visits > last_month_visits:
            business_health["growing"].append(t_data)
        if recent_visits < last_month_visits and total_visits > 0:
            business_health["declining"].append(t_data)
            businesses_at_risk.append(t_data)

    top_performers.sort(key=lambda x: x["total_visits"], reverse=True)

    return {
        "business_health": {
            "regular": len(business_health["regular"]),
            "growing": len(business_health["growing"]),
            "declining": len(business_health["declining"]),
            "regular_list": business_health["regular"],
            "growing_list": business_health["growing"],
            "declining_list": business_health["declining"],
        },
        "top_performers": top_performers[:10],
        "businesses_at_risk": businesses_at_risk
    }

@app.post("/api/admin/send-business-campaign")
def send_business_campaign(
    req: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Send campaign email to a business owner"""
    campaign = {
        "id": str(uuid.uuid4()),
        "target_type": "business_owner",
        "tenant_id": req.get("tenant_id"),
        "subject": req.get("subject", ""),
        "body": req.get("body", ""),
        "status": "sent",
        "sent_at": datetime.now(timezone.utc)
    }
    db.admin_campaigns.insert_one(campaign)
    return {"message": "Campaign sent successfully", "campaign_id": campaign["id"]}


# ============================================================
# 12-FEATURE ROLLOUT (Apr 2026)
# ============================================================

# --- Feature 1 + 7: Churn rate & first-visit cohort ----------
@app.get("/api/owner/analytics/churn")
def get_churn(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Churn metrics + 'never came back after 1st visit' cohort analysis.
    Used on the Analytics page as a top-row KPI.
    """
    tid = token_data.tenant_id
    now = datetime.now(timezone.utc)

    customers = list(db.customers.find({"tenant_id": tid}))
    total = len(customers)
    if total == 0:
        return {
            "total_customers": 0, "one_visit_only": 0, "one_visit_only_pct": 0.0,
            "inactive_30d": 0, "inactive_30d_pct": 0.0,
            "inactive_60d": 0, "inactive_60d_pct": 0.0,
            "churned_90d": 0, "churned_90d_pct": 0.0,
        }

    thirty = now - timedelta(days=30)
    sixty = now - timedelta(days=60)
    ninety = now - timedelta(days=90)

    one_visit = sum(1 for c in customers if c.get("visits", 0) <= 1)
    inactive_30 = sum(
        1 for c in customers
        if c.get("last_visit_date") and c["last_visit_date"] < thirty
    )
    inactive_60 = sum(
        1 for c in customers
        if c.get("last_visit_date") and c["last_visit_date"] < sixty
    )
    churned_90 = sum(
        1 for c in customers
        if c.get("last_visit_date") and c["last_visit_date"] < ninety
    )

    def pct(n):
        return round((n / total) * 100, 1)

    return {
        "total_customers": total,
        "one_visit_only": one_visit,
        "one_visit_only_pct": pct(one_visit),
        "inactive_30d": inactive_30,
        "inactive_30d_pct": pct(inactive_30),
        "inactive_60d": inactive_60,
        "inactive_60d_pct": pct(inactive_60),
        "churned_90d": churned_90,
        "churned_90d_pct": pct(churned_90),
    }


# --- Feature 2: Lifetime Value (LTV) -------------------------
@app.get("/api/owner/analytics/ltv")
def get_ltv(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Average and distribution of customer lifetime value.
    LTV = total_amount_paid. We also return LTV by tier so you can see
    how much more a Gold customer is worth than a Bronze one.
    """
    tid = token_data.tenant_id
    customers = list(db.customers.find({"tenant_id": tid}))
    if not customers:
        return {"average_ltv": 0, "median_ltv": 0, "by_tier": [], "top_10_pct_ltv": 0}

    values = sorted(c.get("total_amount_paid", 0) for c in customers)
    avg_ltv = round(sum(values) / len(values), 2)
    median_ltv = values[len(values) // 2]
    top_10_pct_cutoff = values[int(len(values) * 0.9)] if len(values) >= 10 else values[-1]

    by_tier = {}
    for c in customers:
        tier = (c.get("tier") or "bronze").lower()
        by_tier.setdefault(tier, []).append(c.get("total_amount_paid", 0))

    by_tier_out = [
        {
            "tier": t,
            "count": len(vals),
            "average_ltv": round(sum(vals) / len(vals), 2) if vals else 0,
            "total_revenue": round(sum(vals), 2),
        }
        for t, vals in sorted(by_tier.items(), key=lambda kv: {"gold": 0, "silver": 1, "bronze": 2}.get(kv[0], 3))
    ]

    return {
        "average_ltv": avg_ltv,
        "median_ltv": round(median_ltv, 2),
        "top_10_pct_ltv": round(top_10_pct_cutoff, 2),
        "by_tier": by_tier_out,
    }


# --- Feature 3: Smart alerts panel ---------------------------
@app.get("/api/owner/analytics/alerts")
def get_smart_alerts(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Computed alerts — changes in repeat rate, dormant counts, gold spending shift."""
    tid = token_data.tenant_id
    now = datetime.now(timezone.utc)
    alerts = []

    customers = list(db.customers.find({"tenant_id": tid}))
    if not customers:
        return {"alerts": []}

    # Alert: inactive 30d
    thirty = now - timedelta(days=30)
    inactive = [c for c in customers if c.get("last_visit_date") and c["last_visit_date"] < thirty]
    if len(inactive) >= 5:
        alerts.append({
            "level": "warning",
            "icon": "⚠️",
            "title": f"{len(inactive)} clients inactifs depuis 30 jours",
            "detail": "Envoyez une campagne de relance pour les ramener.",
            "action": "create_campaign",
            "action_filter": {"inactive_days": 30},
        })

    # Alert: repeat-rate drop (visits in last 14d vs previous 14d)
    fourteen = now - timedelta(days=14)
    twentyeight = now - timedelta(days=28)
    recent_visits = db.visits.count_documents({"tenant_id": tid, "created_at": {"$gte": fourteen}})
    prev_visits = db.visits.count_documents({
        "tenant_id": tid, "created_at": {"$gte": twentyeight, "$lt": fourteen}
    })
    if prev_visits > 0:
        delta_pct = round(((recent_visits - prev_visits) / prev_visits) * 100, 1)
        if delta_pct <= -10:
            alerts.append({
                "level": "danger",
                "icon": "📉",
                "title": f"Repeat rate en baisse de {abs(delta_pct)}%",
                "detail": f"{recent_visits} visites (14d) vs {prev_visits} la période précédente.",
                "action": "view_analytics",
            })
        elif delta_pct >= 15:
            alerts.append({
                "level": "success",
                "icon": "🔥",
                "title": f"Visites en hausse de {delta_pct}%",
                "detail": f"{recent_visits} visites (14d) vs {prev_visits} avant.",
                "action": None,
            })

    # Alert: Gold members spending pattern
    gold = [c for c in customers if (c.get("tier") or "").lower() == "gold"]
    non_gold = [c for c in customers if (c.get("tier") or "").lower() != "gold"]
    if gold and non_gold:
        gold_avg = sum(c.get("total_amount_paid", 0) for c in gold) / len(gold)
        non_gold_avg = sum(c.get("total_amount_paid", 0) for c in non_gold) / max(len(non_gold), 1)
        if non_gold_avg > 0:
            multiplier = round((gold_avg - non_gold_avg) / non_gold_avg * 100, 0)
            if multiplier >= 50:
                alerts.append({
                    "level": "success",
                    "icon": "🔥",
                    "title": f"Vos clients Gold dépensent +{int(multiplier)}%",
                    "detail": f"Moyenne Gold: {gold_avg:.0f}€ vs autres: {non_gold_avg:.0f}€",
                    "action": None,
                })

    # Alert: Birthday customers this month
    month = now.strftime("%m")
    birthday_this_month = sum(
        1 for c in customers
        if c.get("birthday", "").startswith(month)
    )
    if birthday_this_month >= 3:
        alerts.append({
            "level": "info",
            "icon": "🎂",
            "title": f"{birthday_this_month} anniversaires ce mois",
            "detail": "Envoyez une campagne anniversaire personnalisée.",
            "action": "create_campaign",
            "action_filter": {"birthday_month": month},
        })

    # Alert: First-visit drop-off
    one_visit_pct = round(sum(1 for c in customers if c.get("visits", 0) <= 1) / len(customers) * 100, 1)
    if one_visit_pct >= 25:
        alerts.append({
            "level": "warning",
            "icon": "🚪",
            "title": f"{one_visit_pct}% des clients ne reviennent pas",
            "detail": "Proposez une offre post-première visite pour fidéliser.",
            "action": "create_campaign",
            "action_filter": {"max_visits": 1},
        })

    return {"alerts": alerts}


# --- Feature 4: Time-of-day / weekday segmentation -----------
DEFAULT_DAYPARTS = [
    {"name": "Breakfast", "raw": "breakfast", "start": 6,  "end": 11},
    {"name": "Lunch",     "raw": "lunch",     "start": 11, "end": 14},
    {"name": "Afternoon", "raw": "afternoon", "start": 14, "end": 18},
    {"name": "Dinner",    "raw": "dinner",    "start": 18, "end": 22},
    {"name": "Late night","raw": "late_night","start": 22, "end": 30},  # wraps past midnight
]


def _resolve_dayparts(tenant_id: str) -> list:
    """Pull the tenant's custom dayparts; fall back to defaults if not configured.
    Stored as a list of {name, start (0-23), end (0-30, can wrap)} on the tenant doc.
    """
    tenant = db.tenants.find_one({"id": tenant_id}) or {}
    dp = tenant.get("daypart_segments")
    if not isinstance(dp, list) or not dp:
        return DEFAULT_DAYPARTS
    cleaned = []
    for d in dp:
        try:
            cleaned.append({
                "name": str(d.get("name") or "Period"),
                "raw": str(d.get("raw") or d.get("name") or "period").lower().replace(" ", "_"),
                "start": max(0, min(int(d.get("start", 0)), 23)),
                "end":   max(0, min(int(d.get("end",   24)), 30)),
            })
        except Exception:
            continue
    return cleaned or DEFAULT_DAYPARTS


@app.put("/api/owner/settings/dayparts")
def update_dayparts(req: Dict[str, Any], token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Owner-controlled segmentation hours. Pass {"dayparts": [...]} to overwrite."""
    parts = req.get("dayparts")
    if not isinstance(parts, list):
        raise HTTPException(status_code=400, detail="dayparts must be a list")
    db.tenants.update_one({"id": token_data.tenant_id}, {"$set": {"daypart_segments": parts}})
    return {"dayparts": _resolve_dayparts(token_data.tenant_id)}


@app.get("/api/owner/settings/dayparts")
def get_dayparts(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    return {"dayparts": _resolve_dayparts(token_data.tenant_id)}


@app.get("/api/owner/analytics/time-segmentation")
def get_time_segmentation(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Break down visits by hour-of-day and weekday — identify lunch crowd, weekend regulars."""
    tid = token_data.tenant_id
    visits = list(db.visits.find({"tenant_id": tid}))

    hour_buckets = {i: 0 for i in range(24)}
    weekday_buckets = {i: 0 for i in range(7)}  # Mon=0 .. Sun=6
    dayparts = _resolve_dayparts(tid)
    daypart_buckets = {d["raw"]: 0 for d in dayparts}

    for v in visits:
        vt = v.get("visit_time") or v.get("created_at")
        if not vt:
            continue
        h = vt.hour
        wd = vt.weekday()
        hour_buckets[h] += 1
        weekday_buckets[wd] += 1
        # Match against owner-configured dayparts (supports wrap-past-midnight)
        for d in dayparts:
            start, end = d["start"], d["end"]
            in_range = (start <= h < end) if end <= 24 else (h >= start or h < (end - 24))
            if in_range:
                daypart_buckets[d["raw"]] += 1
                break

    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "hour_breakdown": [{"hour": h, "visits": c} for h, c in hour_buckets.items()],
        "weekday_breakdown": [
            {"day": weekday_names[i], "visits": weekday_buckets[i]} for i in range(7)
        ],
        "daypart_breakdown": [
            {"name": d["name"], "visits": daypart_buckets.get(d["raw"], 0), "raw": d["raw"], "start": d["start"], "end": d["end"]}
            for d in dayparts
        ],
        "weekend_visits": weekday_buckets[5] + weekday_buckets[6],
        "weekday_visits": sum(weekday_buckets[i] for i in range(5)),
    }


# --- Feature 5: City / postal-code breakdown -----------------
@app.get("/api/owner/analytics/city-breakdown")
def get_city_breakdown(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Customers grouped by postal code. Uses first two digits as French département."""
    tid = token_data.tenant_id
    customers = list(db.customers.find({"tenant_id": tid}))

    # French département names (mapping most common codes)
    DEPT_NAMES = {
        "01": "Ain", "13": "Bouches-du-Rhône", "31": "Haute-Garonne", "33": "Gironde",
        "34": "Hérault", "35": "Ille-et-Vilaine", "37": "Indre-et-Loire", "38": "Isère",
        "44": "Loire-Atlantique", "49": "Maine-et-Loire", "59": "Nord", "62": "Pas-de-Calais",
        "63": "Puy-de-Dôme", "67": "Bas-Rhin", "69": "Rhône", "75": "Paris",
        "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines", "83": "Var",
        "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne", "06": "Alpes-Maritimes",
    }

    postal_counts = {}
    dept_counts = {}
    for c in customers:
        pc = (c.get("postal_code") or "").strip()
        if not pc:
            continue
        postal_counts[pc] = postal_counts.get(pc, 0) + 1
        dept = pc[:2]
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    return {
        "by_postal_code": [
            {"postal_code": k, "customer_count": v}
            for k, v in sorted(postal_counts.items(), key=lambda kv: kv[1], reverse=True)[:50]
        ],
        "by_departement": [
            {"code": k, "name": DEPT_NAMES.get(k, f"Département {k}"), "customer_count": v}
            for k, v in sorted(dept_counts.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "unique_postal_codes": len(postal_counts),
    }


# --- Feature 6: Sector-specific reactivation templates -------
REACTIVATION_TEMPLATES_BY_SECTOR = {
    "restaurant":  {"title": "On vous a manqué à table 🍽️", "content": "Revenez ce week-end : votre plat signature + dessert offert."},
    "pizzeria":    {"title": "Une pizza qui vous attend 🍕", "content": "−30% sur votre prochaine pizza si vous revenez avant dimanche."},
    "glacier":     {"title": "Votre boule préférée vous attend 🍦", "content": "Une boule offerte pour votre prochain passage."},
    "brasserie":   {"title": "Un demi à votre nom 🍺", "content": "Ça fait un moment ! Le premier verre est pour nous."},
    "sushi":       {"title": "Vos makis préférés reviennent 🍣", "content": "Plateau dégustation à moitié prix cette semaine."},
    "burger":      {"title": "Un burger vous réclame 🍔", "content": "Menu complet −25% pour fêter votre retour."},
    "kebab":       {"title": "Votre kebab vous manque ? 🥙", "content": "Le prochain est pour nous. Revenez vite !"},
    "crêperie":    {"title": "Une crêpe vous attend 🥞", "content": "Crêpe sucrée offerte avec votre galette."},
    "chocolatier": {"title": "Une douceur pour votre retour 🍫", "content": "Une truffe maison offerte dès votre prochain passage."},
    "tea salon":   {"title": "Un thé à votre nom ☕", "content": "Pâtisserie offerte avec votre prochaine commande."},
    "wine bar":    {"title": "Un verre vous attend 🍷", "content": "Dégustation offerte avec votre prochaine visite."},
    "juice bar":   {"title": "Votre shot vitaminé 🥤", "content": "Smoothie taille L au prix du M toute la semaine."},
    "hair salon":  {"title": "Un brushing offert ✂️", "content": "Avec votre prochaine coupe. C'est le moment de revenir."},
    "spa":         {"title": "Un moment rien qu'à vous 💆", "content": "Soin du visage offert avec votre prochain massage."},
    "gym":         {"title": "On vous attend au prochain cours 💪", "content": "Séance coach personnel offerte ce mois-ci."},
    "yoga":        {"title": "Votre tapis vous attend 🧘", "content": "Un cours offert pour reprendre en douceur."},
    "dance":       {"title": "La piste vous attend 💃", "content": "Cours d'essai offert ce week-end."},
    "book store":  {"title": "Une lecture vous attend 📚", "content": "−20% sur votre prochain achat. À tout bientôt !"},
    "florist":     {"title": "Un bouquet à votre nom 💐", "content": "Une tige offerte avec votre prochain bouquet."},
    "optician":    {"title": "Vos lunettes sont prêtes 👓", "content": "Contrôle de vue offert + 2e paire à −50%."},
}

@app.get("/api/owner/campaigns/reactivation-templates")
def get_reactivation_templates(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Pre-filled reactivation campaign templates tailored to this tenant's sector."""
    tid = token_data.tenant_id
    tenant = db.tenants.find_one({"id": tid})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    sector = tenant.get("sector") or "restaurant"
    default = {"title": "On vous a manqué ✨", "content": "Revenez cette semaine pour une offre spéciale."}
    template = REACTIVATION_TEMPLATES_BY_SECTOR.get(sector, default)
    return {
        "sector": sector,
        "template": template,
        "all_sectors": [
            {"sector": k, "title": v["title"], "content": v["content"]}
            for k, v in REACTIVATION_TEMPLATES_BY_SECTOR.items()
        ],
    }


# --- Feature 8: Custom sender name ---------------------------
class SenderNameRequest(BaseModel):
    sender_name: str

@app.put("/api/owner/settings/sender-name")
def update_sender_name(
    req: SenderNameRequest,
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Set the 'From' name shown on push notifications and campaign emails."""
    tid = token_data.tenant_id
    if not req.sender_name.strip():
        raise HTTPException(status_code=400, detail="Sender name cannot be empty")
    db.tenants.update_one(
        {"id": tid},
        {"$set": {"campaign_sender_name": req.sender_name.strip()}}
    )
    return {"status": "ok", "sender_name": req.sender_name.strip()}


# --- Feature 9: Fine-grained roles (Manager / Staff) ---------
class TeamMemberRequest(BaseModel):
    email: str
    password: str
    role: str  # "manager" or "staff"

@app.get("/api/owner/team")
def list_team(token_data: TokenData = Depends(require_role(["business_owner"]))):
    """List Manager + Staff users for this tenant."""
    tid = token_data.tenant_id
    members = list(db.users.find(
        {"tenant_id": tid, "role": {"$in": ["manager", "staff"]}},
        {"_id": 0, "hashed_password": 0}
    ))
    return {"members": members}

@app.post("/api/owner/team")
def add_team_member(
    req: TeamMemberRequest,
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Create a Manager or Staff user scoped to this tenant.
    Manager = stats only (business_owner read endpoints).
    Staff = scan only (/owner/scan).
    """
    if req.role not in ("manager", "staff"):
        raise HTTPException(status_code=400, detail="Role must be 'manager' or 'staff'")
    if db.users.find_one({"email": req.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    # Same policy for staff accounts an owner creates — a weak staff password is
    # a way into the same tenant's data.
    from services import password_policy
    password_policy.assert_valid(req.password)
    new_user = UserInDB(
        email=req.email,
        role=req.role,
        tenant_id=token_data.tenant_id,
        hashed_password=hash_password(req.password),
    )
    db.users.insert_one(new_user.model_dump())
    return {"status": "ok", "email": req.email, "role": req.role}

@app.delete("/api/owner/team/{email}")
def remove_team_member(
    email: str,
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Remove a team member. Only works for manager/staff in the same tenant."""
    result = db.users.delete_one({
        "email": email,
        "tenant_id": token_data.tenant_id,
        "role": {"$in": ["manager", "staff"]},
    })
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Team member not found")
    return {"status": "ok"}


class ResetTeamPasswordRequest(BaseModel):
    new_password: Optional[str] = None  # if missing, server generates one


@app.post("/api/owner/team/{email}/reset-password")
def reset_team_member_password(
    email: str,
    req: ResetTeamPasswordRequest,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    """Owner-side password reset for a manager/staff account in the same tenant.
    The owner can either supply a new password or let the server generate one;
    in both cases the plaintext is returned ONCE so the owner can share it.

    Plaintext is never stored — only the hash. There is no way to recover
    the previous password; this endpoint always sets a new one.
    """
    user = db.users.find_one({
        "email": email,
        "tenant_id": token_data.tenant_id,
        "role": {"$in": ["manager", "staff"]},
    })
    if not user:
        raise HTTPException(status_code=404, detail="Team member not found")

    new_pw = (req.new_password or "").strip()
    if not new_pw:
        # Auto-generated passwords must satisfy the same policy as typed ones —
        # otherwise the "convenient" path quietly becomes the weakest one.
        from services import password_policy
        new_pw = password_policy.generate()
    from services import password_policy as _pp
    _pp.assert_valid(new_pw)

    db.users.update_one(
        {"email": email, "tenant_id": token_data.tenant_id},
        {"$set": {"hashed_password": hash_password(new_pw)}},
    )
    return {"status": "ok", "email": email, "new_password": new_pw}


# ============================================================
# Lifetime Value (LTV) — per-cohort + per-tier breakdown
# ============================================================
@app.get("/api/owner/analytics/ltv-breakdown")
def get_ltv_breakdown(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    branch_id: Optional[str] = Query(None),
):
    """Customer Lifetime Value broken down by tier and acquisition cohort.

    LTV is the total revenue a customer is expected to generate over their
    relationship with you. We compute three views in one round-trip:

      1. Network LTV — total revenue / total customers  (overall benchmark)
      2. By tier     — VIP / Gold / Silver / Bronze averages so the owner can
                       see how much more a Gold is worth than a Bronze
      3. By cohort   — month-of-signup → average LTV; surfaces seasonal
                       acquisition cohorts that out-perform.

    Predictive LTV (12-month forward projection) is computed simply: average
    monthly spend × 12, scaled by tier-specific retention multipliers
    derived from observed repeat rates. It's directional, not actuarial.
    """
    q = _branch_customer_filter(token_data.tenant_id, branch_id)
    customers = list(db.customers.find(q))

    if not customers:
        return {
            "network": {"customers": 0, "avg_ltv": 0, "median_ltv": 0, "predicted_12mo": 0},
            "by_tier": [], "by_cohort": [], "top_decile_share_pct": 0,
        }

    now = datetime.now(timezone.utc)
    spends = []
    by_tier = {}
    by_cohort = {}
    months_active = []

    for c in customers:
        spend = float(c.get("total_amount_paid") or 0)
        spends.append(spend)
        tier = (c.get("tier") or "bronze").lower()
        by_tier.setdefault(tier, {"count": 0, "revenue": 0.0, "visits": 0})
        by_tier[tier]["count"] += 1
        by_tier[tier]["revenue"] += spend
        by_tier[tier]["visits"] += int(c.get("visits") or 0)

        created = c.get("created_at")
        if isinstance(created, datetime):
            cohort_key = created.strftime("%Y-%m")
            by_cohort.setdefault(cohort_key, {"count": 0, "revenue": 0.0})
            by_cohort[cohort_key]["count"] += 1
            by_cohort[cohort_key]["revenue"] += spend
            months = max((now - created).days / 30.4, 0.1)
            months_active.append(months)

    avg_months = sum(months_active) / len(months_active) if months_active else 1.0
    avg_ltv = round(sum(spends) / len(spends), 2)
    sorted_spends = sorted(spends)
    median_ltv = round(sorted_spends[len(sorted_spends) // 2], 2)

    # 12-month forward projection — monthly spend × 12 × retention factor.
    # The retention factor is the lifetime "active" share derived from
    # repeat-visit data, capped between 0.4 (very churny) and 1.0 (sticky).
    repeat = sum(1 for c in customers if int(c.get("visits") or 0) >= 2) / max(len(customers), 1)
    retention_factor = max(0.4, min(1.0, repeat))
    predicted_12mo = round((avg_ltv / max(avg_months, 1.0)) * 12 * retention_factor, 2)

    # By-tier rows, sorted high→low.
    TIER_ORDER = ["vip", "gold", "silver", "bronze"]
    tier_rows = []
    for t in TIER_ORDER:
        if t in by_tier:
            row = by_tier[t]
            tier_rows.append({
                "tier": t,
                "customers": row["count"],
                "total_revenue": round(row["revenue"], 2),
                "avg_ltv": round(row["revenue"] / row["count"], 2) if row["count"] else 0,
                "avg_visits": round(row["visits"] / row["count"], 1) if row["count"] else 0,
                "share_pct": round((row["revenue"] / max(sum(spends), 1)) * 100, 1),
            })

    # By cohort, last 12 months.
    cohort_rows = sorted(
        [
            {
                "cohort": k,
                "customers": v["count"],
                "total_revenue": round(v["revenue"], 2),
                "avg_ltv": round(v["revenue"] / v["count"], 2) if v["count"] else 0,
            }
            for k, v in by_cohort.items()
        ],
        key=lambda r: r["cohort"],
    )[-12:]

    # Top-decile concentration — what % of revenue comes from the top 10%
    # of customers? Classic loyalty-program metric.
    n = len(spends)
    top10_count = max(1, n // 10)
    top10_share = (sum(sorted(spends, reverse=True)[:top10_count]) / max(sum(spends), 1)) * 100

    return {
        "network": {
            "customers": n,
            "avg_ltv": avg_ltv,
            "median_ltv": median_ltv,
            "avg_months_active": round(avg_months, 1),
            "predicted_12mo": predicted_12mo,
            "repeat_rate_pct": round(repeat * 100, 1),
        },
        "by_tier": tier_rows,
        "by_cohort": cohort_rows,
        "top_decile_share_pct": round(top10_share, 1),
    }


# ============================================================
# Smart Alerts — unified severity-ranked feed
# ============================================================
@app.get("/api/owner/insights/alerts")
def get_proactive_alerts(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    branch_id: Optional[str] = Query(None),
):
    """Auto-detected business situations the owner should know about.

    Each alert has: id, severity (critical | warning | info | win),
    title, body, metric (the number that triggered it), and action
    (a deep-link the UI can offer as a CTA).

    Trigger conditions (transparent so owners trust them):
      - critical: repeat-rate dropped >10pp vs prior period
                  OR ≥30 customers entering "about to lose" window
      - warning:  one-and-done rate >35%
                  OR top spender silent >30 days
                  OR new-customer pace down >20% vs prior 30d
      - win:      Gold/VIP segment spend up >25% vs prior period
                  OR ≥10 dormant customers reactivated this period
                  OR campaign open-rate above 60%
      - info:     birthdays this month ≥5
                  OR cards filled today ≥3
    """
    tid = token_data.tenant_id
    now = datetime.now(timezone.utc)
    p30 = now - timedelta(days=30)
    p60 = now - timedelta(days=60)

    cust_q = _branch_customer_filter(tid, branch_id)
    customers = list(db.customers.find(cust_q))
    total = len(customers)
    if total == 0:
        return {"alerts": [], "counts_by_severity": {"critical": 0, "warning": 0, "info": 0, "win": 0}}

    alerts = []

    def push(sev, _id, title, body, metric=None, action=None):
        alerts.append({
            "id": _id, "severity": sev, "title": title, "body": body,
            "metric": metric, "action": action, "ts": now.isoformat(),
        })

    # --- Repeat rate movement (critical/win)
    repeat_now = sum(1 for c in customers if int(c.get("visits") or 0) >= 2) / total
    # Approximation: prior-period repeat rate uses customers created >60d ago.
    older = [c for c in customers if isinstance(c.get("created_at"), datetime) and c["created_at"] < p60]
    if older:
        repeat_prev = sum(1 for c in older if int(c.get("visits") or 0) >= 2) / len(older)
        delta = (repeat_now - repeat_prev) * 100
        if delta < -10:
            push("critical", "repeat_drop",
                 f"Repeat rate down {abs(delta):.0f}pp",
                 "Fewer customers are coming back than last period. Consider a reactivation campaign for inactive customers.",
                 metric=f"{repeat_now*100:.0f}%",
                 action="/dashboard/insights")
        elif delta > 10:
            push("win", "repeat_up",
                 f"Repeat rate up {delta:.0f}pp",
                 "Loyalty is climbing. Whatever you launched recently is working — double down on it.",
                 metric=f"{repeat_now*100:.0f}%",
                 action="/dashboard/analytics")

    # --- About-to-lose count (critical at scale)
    about_to_lose = []
    for c in customers:
        lv = c.get("last_visit_date")
        if isinstance(lv, datetime):
            days_since = (now - lv).days
            if 14 <= days_since <= 29 and int(c.get("visits") or 0) >= 2:
                about_to_lose.append(c)
    if len(about_to_lose) >= 30:
        push("critical", "about_to_lose_surge",
             f"{len(about_to_lose)} customers about to lose",
             f"They were regulars but haven't visited in 14–29 days. Send a soft 'we miss you' offer this week before they go silent for 30+ days.",
             metric=str(len(about_to_lose)),
             action="/dashboard/customers?segment=about_to_lose")
    elif len(about_to_lose) >= 10:
        push("warning", "about_to_lose_warn",
             f"{len(about_to_lose)} customers slipping",
             "Customers in the 14–29 day inactivity window. A timely push gets most of them back.",
             metric=str(len(about_to_lose)),
             action="/dashboard/customers?segment=about_to_lose")

    # --- One-and-done detection (warning)
    one_and_done = sum(1 for c in customers if int(c.get("visits") or 0) == 1)
    one_and_done_pct = (one_and_done / total) * 100
    if one_and_done_pct > 35:
        push("warning", "one_and_done",
             f"{one_and_done_pct:.0f}% never came back after 1st visit",
             "A welcome offer triggered after the 1st scan can lift second-visit conversion. Aim for under 30%.",
             metric=f"{one_and_done_pct:.0f}%",
             action="/dashboard/customers?segment=one_and_done")

    # --- Gold / VIP win signals
    gold_vip = [c for c in customers if (c.get("tier") or "").lower() in ("gold", "vip")]
    if gold_vip:
        gv_avg = sum(float(c.get("total_amount_paid") or 0) for c in gold_vip) / len(gold_vip)
        bronze_silver = [c for c in customers if (c.get("tier") or "").lower() in ("bronze", "silver")]
        bs_avg = (sum(float(c.get("total_amount_paid") or 0) for c in bronze_silver) / len(bronze_silver)) if bronze_silver else 0
        if bs_avg > 0:
            ratio = gv_avg / bs_avg
            if ratio >= 3:
                push("win", "vip_spend",
                     f"Gold + VIP members spend {ratio*100-100:.0f}% more",
                     f"Average spend €{gv_avg:.0f} vs €{bs_avg:.0f} for Bronze/Silver. Treat top-tier members like co-owners — they fund the rest.",
                     metric=f"{ratio*100-100:.0f}%",
                     action="/dashboard/customers?tier=vip")

    # --- Top spender silent
    if customers:
        top = max(customers, key=lambda c: float(c.get("total_amount_paid") or 0))
        if float(top.get("total_amount_paid") or 0) > 0:
            lv = top.get("last_visit_date")
            if isinstance(lv, datetime):
                days = (now - lv).days
                if days >= 30:
                    push("warning", "top_silent",
                         f"Top spender silent {days} days",
                         f"{top.get('name','Top customer')} spent €{float(top.get('total_amount_paid')):.0f} with you and hasn't been back. A personal note converts ~3× a generic offer.",
                         metric=f"{days}d",
                         action=f"/dashboard/customers?customer_id={top.get('id')}")

    # --- Birthdays this month (info)
    cur_month = now.strftime("%m")
    birthday_count = sum(1 for c in customers if (c.get("birthday") or "").startswith(cur_month + "-"))
    if birthday_count >= 5:
        push("info", "birthdays",
             f"{birthday_count} birthdays this month",
             "Auto-fire a birthday offer for them — birthday emails see 3× the open rate.",
             metric=str(birthday_count),
             action="/dashboard/customers?segment=birthday_this_month")

    # --- Recent reactivations (win)
    reactivated = [
        c for c in customers
        if isinstance(c.get("last_visit_date"), datetime)
        and (now - c["last_visit_date"]).days <= 30
        and int(c.get("visits") or 0) >= 2
        and isinstance(c.get("created_at"), datetime)
        and (c["last_visit_date"] - c["created_at"]).days >= 60
    ]
    # Heuristic: reactivated = visited recently after a 60+ day gap from
    # signup AND has >=2 lifetime visits — proxy for "came back after quiet".
    if len(reactivated) >= 10:
        push("win", "reactivations",
             f"🔥 {len(reactivated)} dormant customers reactivated",
             "Customers who'd been quiet are coming back. Whatever woke them up is working — capture the playbook.",
             metric=str(len(reactivated)),
             action="/dashboard/insights")

    # --- Sort: critical → warning → win → info
    severity_order = {"critical": 0, "warning": 1, "win": 2, "info": 3}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 99))

    counts = {"critical": 0, "warning": 0, "info": 0, "win": 0}
    for a in alerts:
        counts[a["severity"]] = counts.get(a["severity"], 0) + 1

    return {"alerts": alerts, "counts_by_severity": counts}


@app.get("/api/owner/insights/alerts/multi-store")
def get_proactive_alerts_multi_store(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
):
    """Per-shop alerts wrapper. For each branch under the tenant, calls the
    alert engine and tags each result with `branch_id` and `branch_name`.

    DESIGN CHANGE (user request): the previous "Toutes mes boutiques" /
    tenant-wide pass is removed. Every alert is now scoped to a specific
    branch. For 0–1-branch tenants we still run a single per-branch pass on
    that one branch (or a synthesised one) so single-shop owners aren't left
    with an empty bell.
    """
    tid = token_data.tenant_id
    branches = list(db.branches.find({"tenant_id": tid})) if 'branches' in db.list_collection_names() else []
    if not branches:
        tenant = db.tenants.find_one({"id": tid}) or {}
        branches = tenant.get("branches") or []

    alerts_combined: list = []

    # Per-shop passes ONLY. No tenant-wide bucket.
    if branches:
        for b in branches:
            bid = b.get("id")
            bname = b.get("name") or "Boutique"
            if not bid:
                continue
            try:
                br_alerts = get_proactive_alerts(token_data=token_data, branch_id=bid)
                for a in br_alerts.get("alerts") or []:
                    alerts_combined.append({
                        **a,
                        "id": f"{bid}__{a.get('id')}",
                        "branch_id": bid,
                        "branch_name": bname,
                        "scope": "branch",
                    })
            except Exception:
                continue
    else:
        # Zero-branch tenant edge case: run alerts unscoped and label them
        # with the tenant's display name so the bell still says something
        # meaningful, but treat the result as a single-shop bucket.
        try:
            tenant_alerts = get_proactive_alerts(token_data=token_data, branch_id=None)
            tenant = db.tenants.find_one({"id": tid}) or {}
            label = tenant.get("name") or "Ma boutique"
            for a in tenant_alerts.get("alerts") or []:
                alerts_combined.append({
                    **a,
                    "id": f"shop__{a.get('id')}",
                    "branch_id": None,
                    "branch_name": label,
                    "scope": "branch",
                })
        except Exception:
            pass

    # Sort by severity only — there is no tenant scope anymore.
    severity_order = {"critical": 0, "warning": 1, "win": 2, "info": 3}
    alerts_combined.sort(key=lambda a: severity_order.get(a.get("severity"), 99))

    counts = {"critical": 0, "warning": 0, "info": 0, "win": 0}
    for a in alerts_combined:
        counts[a.get("severity", "info")] = counts.get(a.get("severity", "info"), 0) + 1

    return {
        "alerts": alerts_combined,
        "counts_by_severity": counts,
        "branches_covered": max(len(branches), 1),
    }


# ============================================================
# AI proactive suggestions — what should I do today?
# ============================================================
@app.get("/api/owner/ai/suggestions")
def get_ai_suggestions(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    branch_id: Optional[str] = Query(None),
):
    """Auto-generated 'what should I do today' recommendations.

    Each suggestion has: title, why (the data behind it), action (a draft
    campaign with name + body that the composer can pre-fill), and an
    audience filter (the segment the suggestion targets).

    These are deterministic rules over the customer + visit data — not an
    LLM call — so they're free, fast, and give the same answer twice in a
    row. The user can hit "Open in composer" to take any suggestion and
    edit it before sending.
    """
    tid = token_data.tenant_id
    now = datetime.now(timezone.utc)

    cust_q = _branch_customer_filter(tid, branch_id)
    customers = list(db.customers.find(cust_q))

    suggestions = []
    tenant_doc = db.tenants.find_one({"id": tid}) or {}
    biz_name = tenant_doc.get("name") or "notre équipe"

    # ---- 1. Re-engage about-to-lose customers
    about_to_lose = [
        c for c in customers
        if isinstance(c.get("last_visit_date"), datetime)
        and 14 <= (now - c["last_visit_date"]).days <= 29
        and int(c.get("visits") or 0) >= 2
    ]
    if len(about_to_lose) >= 5:
        suggestions.append({
            "id": "reactivate_about_to_lose",
            "icon": "🔁",
            "title": f"Win back {len(about_to_lose)} slipping customers",
            "why": f"{len(about_to_lose)} regulars are 14–29 days past their last visit. A reminder before day 30 catches most of them; after, it costs 5× more.",
            "audience_count": len(about_to_lose),
            "filter": {"inactive_days_min": 14, "inactive_days_max": 29, "min_visits": 2},
            "draft": {
                "name": f"Vous nous manquez chez {biz_name}",
                "body": f"Bonjour {{first_name}},\n\nÇa fait un petit moment ! Pour vous remercier de votre fidélité, profitez de -15% sur votre prochaine visite chez {{business_name}}. À très bientôt !",
                "source": "push",
            },
        })

    # ---- 2. VIP thank-you
    vips = [c for c in customers if (c.get("tier") or "").lower() == "vip"]
    if len(vips) >= 3:
        suggestions.append({
            "id": "vip_thank_you",
            "icon": "👑",
            "title": f"Reward your {len(vips)} VIPs",
            "why": "Your VIP cohort drives most of your revenue. A surprise gesture (no minimum, no expiry) compounds loyalty for the next year.",
            "audience_count": len(vips),
            "filter": {"tier": "vip"},
            "draft": {
                "name": "Un petit merci, juste pour vous",
                "body": f"Bonjour {{first_name}},\n\nVous êtes l'un de nos meilleurs clients chez {{business_name}}. Un dessert offert à votre prochaine visite — sans condition. Merci d'être là.",
                "source": "push",
            },
        })

    # ---- 3. Birthday push for this month
    cur_month = now.strftime("%m")
    birthdays = [c for c in customers if (c.get("birthday") or "").startswith(cur_month + "-")]
    if len(birthdays) >= 3:
        suggestions.append({
            "id": "birthday_offer",
            "icon": "🎂",
            "title": f"Birthday offer for {len(birthdays)} customers",
            "why": "Birthday emails see ~3× the open rate of generic campaigns. Schedule on the 1st of the month so customers receive it close to their day.",
            "audience_count": len(birthdays),
            "filter": {"has_birthday_this_month": True},
            "draft": {
                "name": "Joyeux anniversaire, {first_name} !",
                "body": f"Joyeux anniversaire {{first_name}} ! Pour fêter ça avec vous, un café offert à votre prochaine visite chez {{business_name}}. À très vite !",
                "source": "push",
            },
        })

    # ---- 4. Welcome new customers
    new_recent = [
        c for c in customers
        if isinstance(c.get("created_at"), datetime)
        and (now - c["created_at"]).days <= 7
        and int(c.get("visits") or 0) <= 1
    ]
    if len(new_recent) >= 5:
        suggestions.append({
            "id": "welcome_new",
            "icon": "👋",
            "title": f"Welcome {len(new_recent)} new sign-ups",
            "why": f"{len(new_recent)} customers signed up in the last 7 days but haven't returned yet. The first follow-up doubles second-visit conversion.",
            "audience_count": len(new_recent),
            "filter": {"created_within_days": 7, "max_visits": 1},
            "draft": {
                "name": "Bienvenue chez {business_name} !",
                "body": f"Bonjour {{first_name}},\n\nMerci de nous avoir rejoints. À votre prochaine visite, votre boisson est offerte. On a hâte de vous revoir !",
                "source": "push",
            },
        })

    # ---- 5. Quiet weekday lift
    weekday_quiet_threshold = 8
    # Visits over the last 30 days, grouped by ISO weekday (Mon=0).
    visits_recent = list(db.visits.find({
        "tenant_id": tid,
        "created_at": {"$gte": now - timedelta(days=30)},
    }))
    by_weekday = {i: 0 for i in range(7)}
    for v in visits_recent:
        ts = v.get("created_at")
        if isinstance(ts, datetime):
            by_weekday[ts.weekday()] += 1
    if visits_recent:
        avg = sum(by_weekday.values()) / 7
        quietest_day = min(range(7), key=lambda d: by_weekday[d])
        if by_weekday[quietest_day] < avg * 0.6 and avg >= weekday_quiet_threshold:
            day_label = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"][quietest_day]
            suggestions.append({
                "id": "quiet_weekday_lift",
                "icon": "📅",
                "title": f"Lift {day_label.title()} traffic",
                "why": f"{day_label.title()} averages {by_weekday[quietest_day]} visits vs ~{avg:.0f} on other days. A weekday-only offer can level the curve and free up your weekend.",
                "audience_count": len(customers),
                "filter": {},
                "draft": {
                    "name": f"Spécial {day_label.title()} — 20%",
                    "body": f"Bonjour {{first_name}},\n\nTous les {day_label}s, profitez de -20% sur place chez {{business_name}}. Une bonne raison de commencer la semaine en douceur.",
                    "source": "push",
                },
            })

    return {"suggestions": suggestions, "generated_at": now.isoformat()}


# --- Feature 10: Monthly report ------------------------------
@app.get("/api/owner/monthly-report")
def get_monthly_report(
    month: Optional[str] = None,  # "YYYY-MM"; defaults to last month
    token_data: TokenData = Depends(require_role(["business_owner", "manager"]))
):
    """Month-end rollup: customers, visits, revenue, top campaigns, new customers, tier shifts."""
    tid = token_data.tenant_id
    now = datetime.now(timezone.utc)

    if month:
        try:
            year, mo = [int(x) for x in month.split("-")]
            start = datetime(year, mo, 1, tzinfo=timezone.utc)
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    else:
        # Last complete month
        first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start = (first_this - timedelta(days=1)).replace(day=1)

    end = (start + timedelta(days=32)).replace(day=1)
    next_month = (end + timedelta(days=32)).replace(day=1)

    visits_this = list(db.visits.find({
        "tenant_id": tid,
        "created_at": {"$gte": start, "$lt": end},
    }))
    visits_prev_start = (start - timedelta(days=1)).replace(day=1)
    visits_prev_count = db.visits.count_documents({
        "tenant_id": tid,
        "created_at": {"$gte": visits_prev_start, "$lt": start},
    })

    new_customers = db.customers.count_documents({
        "tenant_id": tid,
        "created_at": {"$gte": start, "$lt": end},
    })
    new_customers_prev = db.customers.count_documents({
        "tenant_id": tid,
        "created_at": {"$gte": visits_prev_start, "$lt": start},
    })

    revenue = round(sum(v.get("amount_paid", 0) for v in visits_this), 2)

    # Campaigns sent this month
    camps = list(db.campaigns.find({
        "tenant_id": tid,
        "sent_at": {"$gte": start, "$lt": end},
    }))
    camp_out = [
        {
            "name": c.get("name"),
            "targeted": c.get("targeted_count", 0),
            "delivered": c.get("delivered_count", 0),
            "opens": c.get("opens", 0),
            "visits_from": c.get("visits_from_campaign", 0),
            "clicks": c.get("offer_clicks", 0),
        }
        for c in camps
    ]

    def delta_pct(cur, prev):
        if not prev:
            return None
        return round((cur - prev) / prev * 100, 1)

    return {
        "month": start.strftime("%Y-%m"),
        "month_label": start.strftime("%B %Y"),
        "totals": {
            "visits": len(visits_this),
            "visits_delta_pct": delta_pct(len(visits_this), visits_prev_count),
            "new_customers": new_customers,
            "new_customers_delta_pct": delta_pct(new_customers, new_customers_prev),
            "revenue": revenue,
            "avg_basket": round(revenue / len(visits_this), 2) if visits_this else 0,
        },
        "campaigns": camp_out,
        "campaign_count": len(camps),
    }


# --- Feature 11: Offer click / push dismiss tracking ---------
@app.post("/api/campaigns/{campaign_id}/track-click")
def track_offer_click(campaign_id: str, customer_id: Optional[str] = None):
    """Called by wallet card / email when a recipient clicks the offer link."""
    camp = db.campaigns.find_one({"id": campaign_id})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    update = {"$inc": {"offer_clicks": 1}}
    if customer_id:
        # best-effort unique-click counting
        if customer_id not in (camp.get("click_customer_ids") or []):
            update["$addToSet"] = {"click_customer_ids": customer_id}
            update["$inc"]["offer_clicks_unique"] = 1
    db.campaigns.update_one({"id": campaign_id}, update)
    return {"status": "ok"}

@app.post("/api/campaigns/{campaign_id}/track-dismiss")
def track_push_dismiss(campaign_id: str):
    """Called by the wallet card when user dismisses a push without opening."""
    db.campaigns.update_one({"id": campaign_id}, {"$inc": {"push_dismissals": 1}})
    return {"status": "ok"}


# ========================================================================
# NEW FEATURES (this batch): VIP tier · reward redemption · birthdays ·
# per-customer visit history · time-of-day segments · proximity push ·
# saved segments
# ========================================================================

# ========================================================================
# REVIEWS — ratings, sentiment, topic clustering
# ========================================================================
#
# Customers rate a visit on a 1–10 scale and optionally leave free text.
# On submit we run a lexicon-based sentiment scorer + topic classifier over
# the text. Both are deterministic and self-contained so the numbers are
# reproducible and don't depend on an external API.
#
# Sentiment lexicon: positive/negative words in FR + EN, with very basic
# negation handling ("pas bon" = negative). Not perfect but robust and
# much better than pure rating-only analysis.
#
# Topic classifier: keyword sets for 5 recurring themes — service speed,
# cleanliness, staff friendliness, price, wait time. A review mentioning a
# keyword in a topic's set is flagged as on-topic with a confidence score
# proportional to how many of the set appeared.
#

_REVIEW_POS_WORDS = {
    # FR
    "bon", "bonne", "bien", "excellent", "excellente", "super", "génial", "genial",
    "génialissime", "parfait", "parfaite", "top", "magnifique", "délicieux", "delicieux",
    "savoureux", "savoureuse", "savoureuses", "recommande", "rapide", "rapidement",
    "propre", "accueillant", "accueillante", "sympathique", "sympa", "aimable",
    "poli", "polie", "souriant", "souriante", "chaleureux", "chaleureuse",
    "attentif", "attentionné", "professionnel", "professionnelle",
    "qualité", "qualite", "agréable", "agreable", "merci", "adore", "adorable",
    "fidèle", "fidele", "heureux", "heureuse", "satisfait", "satisfaite",
    "frais", "fraîche", "fraiche", "copieux", "abordable", "raisonnable",
    "belle", "beau",
    # EN
    "good", "great", "excellent", "amazing", "awesome", "lovely", "wonderful",
    "fantastic", "perfect", "clean", "fast", "quick", "friendly", "kind",
    "helpful", "smiling", "polite", "professional", "fresh", "delicious",
    "tasty", "recommend", "best", "love", "loved", "nice", "happy",
    "affordable", "cheap", "fair", "quality", "thanks", "thank",
}

_REVIEW_NEG_WORDS = {
    # FR
    "mauvais", "mauvaise", "horrible", "nul", "nulle", "décevant", "decevant",
    "déçu", "decue", "déçue", "lent", "lente", "lentement", "attendre",
    "attente", "file", "queue", "long", "longue", "sale", "sales", "saleté",
    "salete", "dégoûtant", "degoutant", "froid", "froide", "cher", "chère",
    "chere", "ruineux", "arrogant", "impoli", "malpoli", "désagréable",
    "desagreable", "bruyant", "bondé", "bonde", "bordélique", "chaotique",
    "indifférent", "indifferent", "pire", "affreux", "affreuse", "infect",
    "trop", "beaucoup",
    # EN
    "bad", "terrible", "awful", "worst", "horrible", "slow", "late", "cold",
    "rude", "dirty", "filthy", "expensive", "overpriced", "crowded", "noisy",
    "wait", "waited", "waiting", "queue", "disappointed", "disappointing",
    "mediocre", "stale", "wrong", "unfriendly", "unhappy", "hate", "never",
}

# Topic → keyword set. We strip accents when matching so "délai" / "delai" both hit.
_REVIEW_TOPICS = {
    "speed": {
        "rapide", "rapidement", "vite", "express", "fast", "quick", "prompt", "speedy",
        "lent", "lente", "long", "longue", "slow", "retard", "tardif", "delayed",
    },
    "cleanliness": {
        "propre", "propreté", "proprete", "clean", "cleanliness", "impeccable",
        "hygiène", "hygiene", "sale", "dirty", "filthy", "poussière", "poussiere",
    },
    "staff": {
        "accueil", "accueillant", "accueillante", "personnel", "équipe", "equipe",
        "staff", "serveur", "serveuse", "caissier", "caissière", "caissiere",
        "friendly", "kind", "polite", "rude", "impoli", "sympathique", "sympa",
        "arrogant", "souriant", "souriante", "smile", "smiling", "helpful",
    },
    "price": {
        "prix", "cher", "chère", "chere", "coûteux", "couteux", "abordable",
        "price", "pricing", "expensive", "cheap", "overpriced", "affordable",
        "value", "cost", "budget", "raisonnable",
    },
    "wait_time": {
        "attente", "attendre", "attendu", "attendue", "queue", "file", "patience",
        "wait", "waiting", "waited", "line", "délai", "delai",
    },
}

def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def _detect_language(text: str) -> Optional[str]:
    """Very lightweight FR/EN detector based on stop words."""
    if not text: return None
    t = " " + text.lower() + " "
    fr = sum(1 for w in (" le ", " la ", " les ", " un ", " une ", " et ", " est ", " j'ai ", " très ", " pas ") if w in t)
    en = sum(1 for w in (" the ", " a ", " and ", " is ", " was ", " very ", " not ", " i ") if w in t)
    if fr == 0 and en == 0: return None
    return "fr" if fr >= en else "en"

def analyze_review_text(text: str, rating: int) -> Dict[str, Any]:
    """Run sentiment + topic extraction on a review. Deterministic and fast.

    Returns {sentiment, sentiment_score, topics, topic_scores, language}.
    Rating is used as a tie-breaker when the text is empty or evenly split.
    """
    clean = (text or "").strip()
    language = _detect_language(clean)
    if not clean:
        # No text → score purely from the numeric rating.
        if rating >= 8:   return {"sentiment": "positive", "sentiment_score": 0.6, "topics": [], "topic_scores": {}, "language": language}
        if rating <= 4:   return {"sentiment": "negative", "sentiment_score": -0.6, "topics": [], "topic_scores": {}, "language": language}
        return {"sentiment": "neutral", "sentiment_score": 0.0, "topics": [], "topic_scores": {}, "language": language}

    import re
    # Tokenise, lowercase, strip accents + punctuation.
    flat = _strip_accents(clean.lower())
    tokens = re.findall(r"[a-zàâäéèêëîïôöùûüç']+", clean.lower())
    tokens_flat = [_strip_accents(t) for t in tokens]

    pos_set = {_strip_accents(w) for w in _REVIEW_POS_WORDS}
    neg_set = {_strip_accents(w) for w in _REVIEW_NEG_WORDS}
    negators = {"pas", "ne", "n", "not", "never", "no", "aucun", "aucune", "jamais"}

    pos = neg = 0
    for i, tok in enumerate(tokens_flat):
        flipped = i > 0 and tokens_flat[i - 1] in negators
        if tok in pos_set:
            if flipped: neg += 1
            else: pos += 1
        elif tok in neg_set:
            if flipped: pos += 1
            else: neg += 1

    # Score blends text signal with the numeric rating (rating is a strong prior).
    total = pos + neg
    text_score = ((pos - neg) / total) if total else 0.0
    rating_score = (rating - 5.5) / 4.5        # maps 1..10 onto ~-1..+1
    # Weighted average: text dominates when there's signal, rating anchors otherwise.
    if total >= 3:
        sentiment_score = round(0.7 * text_score + 0.3 * rating_score, 3)
    elif total >= 1:
        sentiment_score = round(0.5 * text_score + 0.5 * rating_score, 3)
    else:
        sentiment_score = round(rating_score, 3)
    if sentiment_score >= 0.15:    sentiment = "positive"
    elif sentiment_score <= -0.15: sentiment = "negative"
    else:                          sentiment = "neutral"

    # Topic classification.
    topics = []
    topic_scores = {}
    for topic, keywords in _REVIEW_TOPICS.items():
        kw_flat = {_strip_accents(k.lower()) for k in keywords}
        hits = sum(1 for tok in tokens_flat if tok in kw_flat)
        if hits > 0:
            # Confidence = hits normalised by total words, capped at 1.0
            conf = min(1.0, hits / max(3, len(tokens_flat) / 4))
            topics.append(topic)
            topic_scores[topic] = round(conf, 3)

    return {
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "topics": topics,
        "topic_scores": topic_scores,
        "language": language,
    }


class ReviewSubmit(BaseModel):
    customer_id: Optional[str] = None
    barcode_id: Optional[str] = None
    rating: int
    text: Optional[str] = ""
    visit_id: Optional[str] = None
    branch_id: Optional[str] = None


@app.post("/api/public/reviews")
def submit_review(req: ReviewSubmit):
    """Customer-facing endpoint. Accepts either customer_id or barcode_id so
    the wallet card page can post a review without the customer being logged
    in. Rating must be 1..10; text is optional. Dedupes one review per visit.
    """
    if req.rating < 1 or req.rating > 10:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 10")
    if not req.customer_id and not req.barcode_id:
        raise HTTPException(status_code=400, detail="Provide customer_id or barcode_id")

    q = {}
    if req.customer_id:
        q["id"] = req.customer_id
    else:
        q["barcode_id"] = req.barcode_id
    cust = db.customers.find_one(q)
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Dedupe: if a visit_id was supplied, only accept one review per visit.
    if req.visit_id:
        existing = db.reviews.find_one({
            "tenant_id": cust.get("tenant_id"),
            "customer_id": cust.get("id"),
            "visit_id": req.visit_id,
        })
        if existing:
            raise HTTPException(status_code=409, detail="You already rated this visit.")

    analysis = analyze_review_text(req.text or "", req.rating)
    review = Review(
        id=str(uuid.uuid4()),
        tenant_id=cust.get("tenant_id"),
        customer_id=cust.get("id"),
        branch_id=req.branch_id or cust.get("branch_id"),
        visit_id=req.visit_id,
        rating=int(req.rating),
        text=(req.text or "").strip()[:4000],
        sentiment=analysis["sentiment"],
        sentiment_score=analysis["sentiment_score"],
        topics=analysis["topics"],
        topic_scores=analysis["topic_scores"],
        language=analysis["language"],
    ).model_dump()
    db.reviews.insert_one(review)
    review.pop("_id", None)
    return {"status": "ok", "review": review}


def _compute_review_kpis(query: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate the 4 headline review KPIs + distribution + topic breakdown
    over whatever filter the caller passes in. Used by both owner and admin
    analytics so the numbers line up across dashboards.
    """
    now = datetime.now(timezone.utc)
    thirty_ago = now - timedelta(days=30)
    sixty_ago = now - timedelta(days=60)

    # One pass over the set — reviews are small & bounded (<< 100k per tenant).
    reviews = list(db.reviews.find(query))
    total = len(reviews)
    if total == 0:
        return {
            "total_reviews": 0,
            "average_rating": None,
            "rating_distribution": {str(i): 0 for i in range(1, 11)},
            "negative_review_rate_pct": 0.0,
            "sentiment_breakdown": {"positive": 0, "neutral": 0, "negative": 0},
            "sentiment_score": 0,
            "review_velocity": {"last_30d": 0, "prev_30d": 0, "delta_pct": 0.0},
            "topic_breakdown": [],
            "recent": [],
        }

    ratings = [int(r.get("rating", 0)) for r in reviews if r.get("rating")]
    avg = sum(ratings) / len(ratings) if ratings else 0
    dist = {str(i): 0 for i in range(1, 11)}
    for r in ratings:
        if 1 <= r <= 10:
            dist[str(r)] += 1

    # Negative review rate = % with rating ≤ 4/10 (equivalent to 1–2 / 5★).
    neg_count = sum(1 for r in ratings if r <= 4)
    negative_rate = (neg_count / total) * 100 if total else 0.0

    # Sentiment breakdown from pre-computed field — cheap.
    pos = sum(1 for r in reviews if r.get("sentiment") == "positive")
    neu = sum(1 for r in reviews if r.get("sentiment") == "neutral")
    neg = sum(1 for r in reviews if r.get("sentiment") == "negative")
    sent_score = round(((pos - neg) / total) * 100, 1) if total else 0

    # Review velocity — reviews in the last 30d vs the 30d before that.
    last30 = sum(1 for r in reviews if r.get("created_at") and r["created_at"] >= thirty_ago)
    prev30 = sum(1 for r in reviews if r.get("created_at") and sixty_ago <= r["created_at"] < thirty_ago)
    delta_pct = round(((last30 - prev30) / prev30) * 100, 1) if prev30 else (100.0 if last30 else 0.0)

    # Topic breakdown — count, avg rating, sentiment tilt per theme.
    topic_agg = {t: {"count": 0, "rating_sum": 0, "pos": 0, "neg": 0} for t in _REVIEW_TOPICS.keys()}
    for r in reviews:
        rating_val = int(r.get("rating", 0) or 0)
        sentiment_val = r.get("sentiment", "neutral")
        for t in (r.get("topics") or []):
            if t not in topic_agg: continue
            topic_agg[t]["count"] += 1
            topic_agg[t]["rating_sum"] += rating_val
            if sentiment_val == "positive": topic_agg[t]["pos"] += 1
            elif sentiment_val == "negative": topic_agg[t]["neg"] += 1
    topic_breakdown = []
    for t, v in topic_agg.items():
        if v["count"] == 0: continue
        topic_breakdown.append({
            "topic": t,
            "count": v["count"],
            "mention_pct": round(v["count"] / total * 100, 1),
            "avg_rating": round(v["rating_sum"] / v["count"], 2),
            "positive_pct": round(v["pos"] / v["count"] * 100, 1),
            "negative_pct": round(v["neg"] / v["count"] * 100, 1),
        })
    topic_breakdown.sort(key=lambda x: -x["count"])

    # Recent review feed (last 10, newest first).
    recent_reviews = sorted(
        reviews,
        key=lambda r: r.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:10]
    recent = []
    for r in recent_reviews:
        recent.append({
            "id": r.get("id"),
            "rating": r.get("rating"),
            "text": r.get("text", ""),
            "sentiment": r.get("sentiment"),
            "topics": r.get("topics", []),
            "customer_id": r.get("customer_id"),
            "branch_id": r.get("branch_id"),
            "created_at": r.get("created_at"),
        })

    return {
        "total_reviews": total,
        "average_rating": round(avg, 2),
        "rating_distribution": dist,
        "negative_review_rate_pct": round(negative_rate, 1),
        "sentiment_breakdown": {"positive": pos, "neutral": neu, "negative": neg},
        "sentiment_score": sent_score,            # -100 to +100
        "review_velocity": {"last_30d": last30, "prev_30d": prev30, "delta_pct": delta_pct},
        "topic_breakdown": topic_breakdown,
        "recent": recent,
    }


@app.get("/api/owner/analytics/reviews")
def get_owner_review_analytics(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    branch_id: Optional[str] = Query(None),
):
    """Review KPIs for the logged-in owner's tenant."""
    q = {"tenant_id": token_data.tenant_id}
    if branch_id:
        q["branch_id"] = branch_id
    return _compute_review_kpis(q)


@app.get("/api/owner/reviews")
def list_owner_reviews(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    branch_id: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),      # positive | neutral | negative
    topic: Optional[str] = Query(None),          # speed | cleanliness | ...
    min_rating: Optional[int] = Query(None),
    max_rating: Optional[int] = Query(None),
    limit: int = Query(100),
):
    """List raw reviews with filters for a "manage reviews" view."""
    q = {"tenant_id": token_data.tenant_id}
    if branch_id: q["branch_id"] = branch_id
    if sentiment: q["sentiment"] = sentiment
    if topic:     q["topics"] = topic
    if min_rating is not None: q.setdefault("rating", {})["$gte"] = int(min_rating)
    if max_rating is not None: q.setdefault("rating", {})["$lte"] = int(max_rating)
    rows = list(
        db.reviews.find(q).sort("created_at", -1).limit(max(1, min(limit, 500)))
    )
    for r in rows:
        r.pop("_id", None)
        # Attach the customer name for the UI.
        c = db.customers.find_one({"id": r.get("customer_id")}, {"name": 1, "tier": 1})
        if c:
            r["customer_name"] = c.get("name", "")
            r["customer_tier"] = c.get("tier", "bronze")
    return {"reviews": rows, "count": len(rows)}


@app.get("/api/admin/analytics/reviews")
def get_admin_review_analytics(
    token_data: TokenData = Depends(require_role(["super_admin"])),
    tenant_id: Optional[str] = Query(None),
):
    """Global review KPIs across all tenants + per-tenant leaderboard.
    Filter to a single tenant by passing ?tenant_id=..."""
    q = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    kpis = _compute_review_kpis(q)

    # Per-tenant leaderboard (top + bottom by average rating, min 3 reviews).
    leaderboard = []
    for row in db.reviews.aggregate([
        {"$group": {
            "_id": "$tenant_id",
            "count": {"$sum": 1},
            "avg": {"$avg": "$rating"},
            "negative": {"$sum": {"$cond": [{"$lte": ["$rating", 4]}, 1, 0]}},
        }},
        {"$match": {"count": {"$gte": 3}}},
        {"$sort": {"avg": -1}},
    ]):
        t = db.tenants.find_one({"id": row["_id"]}, {"name": 1, "slug": 1}) or {}
        leaderboard.append({
            "tenant_id": row["_id"],
            "tenant_name": t.get("name", "(unknown)"),
            "slug": t.get("slug", ""),
            "review_count": row["count"],
            "average_rating": round(row["avg"], 2),
            "negative_count": row["negative"],
            "negative_rate_pct": round((row["negative"] / row["count"]) * 100, 1),
        })
    kpis["leaderboard"] = leaderboard
    return kpis


# --- Reward redemption: record the moment a filled card is cashed in ---------
class RedeemRewardRequest(BaseModel):
    barcode_id: Optional[str] = None
    customer_id: Optional[str] = None
    reward_name: Optional[str] = None       # e.g. "Free coffee", "10€ off"
    reward_value_eur: Optional[float] = None
    branch_id: Optional[str] = None
    notes: Optional[str] = None


@app.post("/api/owner/rewards/redeem")
def redeem_reward(
    req: RedeemRewardRequest,
    token_data: TokenData = Depends(require_role(["business_owner", "manager", "staff"])),
):
    """Record that a customer cashed in their reward.

    Works from either barcode_id (staff typical flow) or customer_id.
    Emits an entry in db.rewards_redeemed for the KPI + history.

    IMPORTANT: lifetime `visits` is NEVER decremented. Previously this
    endpoint did `$inc: {visits: -threshold}` so a freshly-redeemed
    customer's stamp counter would reset to 0 visually — but it had a
    nasty side effect: it ALSO demoted their tier on the next scan
    (tier is computed from visits, so 10 → 0 → 1 lands them back in
    bronze even though they should still be silver).

    Fix: keep `visits` as a true lifetime counter, and track WHERE
    in the visit history the last redemption happened via
    `visits_at_last_redemption`. The wallet card derives stamps as
    `min(visits - visits_at_last_redemption, threshold)` so the card
    visually resets to 0/10 after redemption while the customer keeps
    every tier they've earned across their lifetime.
    """
    tid = token_data.tenant_id
    if not req.barcode_id and not req.customer_id:
        raise HTTPException(status_code=400, detail="Provide barcode_id or customer_id")
    q = {"tenant_id": tid}
    if req.customer_id:
        q["id"] = req.customer_id
    else:
        q["barcode_id"] = req.barcode_id
    cust = db.customers.find_one(q)
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Threshold for a full card (so decrement matches the real card)
    card_tpl = db.card_templates.find_one({"tenant_id": tid}) or {}
    threshold = max(int(card_tpl.get("reward_threshold_stamps", 10)) *
                    int(card_tpl.get("visits_per_stamp", 1)), 1)
    current_visits = int(cust.get("visits", 0) or 0)
    if current_visits < threshold:
        raise HTTPException(
            status_code=400,
            detail=f"Customer needs {threshold - current_visits} more visit(s) before redeeming.",
        )

    reward = {
        "id": str(uuid.uuid4()),
        "tenant_id": tid,
        "customer_id": cust["id"],
        "customer_name": cust.get("name", ""),
        "reward_name": req.reward_name or "Reward",
        "reward_value_eur": req.reward_value_eur,
        "branch_id": req.branch_id or cust.get("branch_id"),
        "notes": req.notes or "",
        "redeemed_at": datetime.now(timezone.utc),
        "staff_email": getattr(token_data, "email", None),
    }
    db.rewards_redeemed.insert_one(reward)

    # NO LONGER DECREMENT VISITS. Mark where in the lifetime visit count
    # this redemption happened, so stamps can be derived as
    # `visits - visits_at_last_redemption` going forward. Tier stays
    # intact because it's computed from the (untouched) visits field.
    db.customers.update_one(
        {"id": cust["id"]},
        {"$inc": {"rewards_redeemed_count": 1},
         "$set": {
             "last_reward_redeemed_at": reward["redeemed_at"],
             "visits_at_last_redemption": current_visits,
         }},
    )
    reward.pop("_id", None)
    return reward


@app.get("/api/owner/rewards/redeemed")
def list_redeemed_rewards(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    branch_id: Optional[str] = Query(None),
    days: Optional[int] = Query(None),
):
    """List recent reward redemptions (default: all; if `days` given, last N days)."""
    q = {"tenant_id": token_data.tenant_id}
    if branch_id:
        q["branch_id"] = branch_id
    if days and days > 0:
        q["redeemed_at"] = {"$gte": datetime.now(timezone.utc) - timedelta(days=days)}
    rows = list(db.rewards_redeemed.find(q).sort("redeemed_at", -1).limit(500))
    for r in rows:
        r.pop("_id", None)
    # Aggregate counters for KPI cards
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)
    today_q = dict(q); today_q["redeemed_at"] = {"$gte": today_start}
    month_q = dict(q); month_q["redeemed_at"] = {"$gte": month_start}
    return {
        "redemptions": rows,
        "today_count": db.rewards_redeemed.count_documents(today_q),
        "month_count": db.rewards_redeemed.count_documents(month_q),
        "total_count": db.rewards_redeemed.count_documents(q),
    }


# --- Per-customer visit history ---------------------------------------
@app.get("/api/owner/customers/{customer_id}/visits")
def customer_visit_history(
    customer_id: str,
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    limit: int = Query(50),
):
    """Last N visits for one customer — date, amount, points, branch."""
    cust = db.customers.find_one({"id": customer_id, "tenant_id": token_data.tenant_id})
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")
    visits = list(
        db.visits.find({"tenant_id": token_data.tenant_id, "customer_id": customer_id})
        .sort("visit_time", -1)
        .limit(max(1, min(limit, 500)))
    )
    for v in visits:
        v.pop("_id", None)
    # Also include last redemptions so the Journey tab can show the full story.
    redemptions = list(
        db.rewards_redeemed.find({"tenant_id": token_data.tenant_id, "customer_id": customer_id})
        .sort("redeemed_at", -1)
        .limit(20)
    )
    for r in redemptions:
        r.pop("_id", None)
    return {
        "customer_id": customer_id,
        "visits": visits,
        "redemptions": redemptions,
        "total_visits": int(cust.get("visits", 0) or 0),
        "total_amount_paid": float(cust.get("total_amount_paid", 0) or 0),
    }


# --- Birthdays this month --------------------------------------------
@app.get("/api/owner/analytics/birthdays-this-month")
def birthdays_this_month(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    branch_id: Optional[str] = Query(None),
):
    """Customers whose birthday falls in the current calendar month."""
    now = datetime.now(timezone.utc)
    mm = now.strftime("%m")
    q = {"tenant_id": token_data.tenant_id, "birthday": {"$regex": f"^{mm}"}}
    if branch_id:
        q["branch_id"] = branch_id
    rows = list(db.customers.find(q).sort("birthday", 1))
    out = []
    for c in rows:
        bd = c.get("birthday") or ""
        # Compute days until birthday this month (for light sort hinting)
        try:
            day = int(bd.split("-")[1]) if "-" in bd else 0
        except Exception:
            day = 0
        out.append({
            "id": c.get("id"),
            "name": c.get("name", ""),
            "email": c.get("email", ""),
            "phone": c.get("phone", ""),
            "tier": c.get("tier", "bronze"),
            "birthday": bd,
            "day_of_month": day,
            "total_visits": c.get("visits", 0),
            "total_amount_paid": c.get("total_amount_paid", 0),
        })
    return {"count": len(out), "month": now.strftime("%B"), "customers": out}


# --- Real-time proximity push: fired when the wallet-card page pings --
class ProximityPingRequest(BaseModel):
    customer_id: str
    latitude: float
    longitude: float


def _haversine_meters(lat1, lng1, lat2, lng2) -> float:
    import math
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@app.post("/api/public/proximity-ping")
def proximity_ping(req: ProximityPingRequest):
    """Customer's wallet-card page calls this every time it's opened with GPS
    permission granted. If the customer is within the tenant's configured
    `geo_radius_meters` of a branch (or tenant address) AND their cooldown
    has elapsed, fire a fresh push notification. Otherwise no-op.

    Public endpoint intentionally — called from the customer's own device,
    before/after login matters less than the customer_id matching a real
    record. Rate-limited by the geo_cooldown_days window per customer.
    """
    cust = db.customers.find_one({"id": req.customer_id})
    if not cust:
        return {"status": "ignored", "reason": "unknown customer"}
    tid = cust.get("tenant_id")
    tenant = db.tenants.find_one({"id": tid})
    if not tenant or not tenant.get("geo_enabled"):
        return {"status": "ignored", "reason": "geo disabled for tenant"}

    # VIP-only gate: when the super-admin has flipped `vip_geo_only` on for this
    # tenant, proximity pushes fire exclusively for VIP-tier customers. Anyone
    # else gets silently ignored — same as if geo were off for them.
    if tenant.get("vip_geo_only"):
        if (cust.get("tier") or "").lower() != "vip":
            return {"status": "ignored", "reason": "vip_only: customer not VIP"}

    radius_m = float(tenant.get("geo_radius_meters") or 500)
    cooldown_days = int(tenant.get("geo_cooldown_days") or 1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)

    # Last proximity push for this customer — cooldown enforcement.
    last = db.push_notifications.find_one(
        {"customer_id": cust["id"], "tenant_id": tid, "type": "proximity"},
        sort=[("sent_at", -1)],
    )
    if last and last.get("sent_at") and last["sent_at"] >= cutoff:
        return {"status": "cooldown", "next_eligible_at": (last["sent_at"] + timedelta(days=cooldown_days)).isoformat()}

    # Figure out which branch (or the tenant address) they're nearest to.
    anchors = []
    for b in tenant.get("branches") or []:
        # Branches often lack raw lat/lng — resolve from postal_code when needed.
        blat, blng = b.get("latitude"), b.get("longitude")
        if blat is None or blng is None:
            blat, blng = get_postal_coords(b.get("postal_code") or "")
        if blat is not None:
            anchors.append({"id": b.get("id"), "name": b.get("name", ""), "lat": blat, "lng": blng})
    if not anchors:
        # Fall back to tenant-level address coords
        tl, tn = get_postal_coords((tenant.get("address") or "").split(",")[-1].strip().split()[0] if tenant.get("address") else "")
        anchors = [{"id": tid, "name": tenant.get("name", ""), "lat": tl, "lng": tn}]

    nearest = None
    for a in anchors:
        dist = _haversine_meters(req.latitude, req.longitude, a["lat"], a["lng"])
        if nearest is None or dist < nearest["distance_m"]:
            nearest = {**a, "distance_m": dist}

    if not nearest or nearest["distance_m"] > radius_m:
        return {"status": "out_of_range", "distance_m": (nearest["distance_m"] if nearest else None)}

    # In range — fire a push.
    biz = tenant.get("campaign_sender_name") or tenant.get("name") or "votre boutique"
    first_name = (cust.get("name") or "").split(" ")[0]
    title = f"{biz} est juste à côté 👋"
    body = (
        f"Bonjour {first_name}, vous êtes tout près de {nearest['name'] or biz}. "
        "Venez scanner votre carte — une attention vous attend !"
    )
    db.push_notifications.insert_one({
        "customer_id": cust["id"],
        "tenant_id": tid,
        "title": title,
        "body": body,
        "type": "proximity",
        "branch_id": nearest.get("id"),
        "distance_m": int(nearest["distance_m"]),
        "sent_at": datetime.now(timezone.utc),
    })
    return {
        "status": "sent",
        "branch_id": nearest.get("id"),
        "distance_m": int(nearest["distance_m"]),
        "title": title,
        "body": body,
    }


# --- Saved segments: owners save their favourite filter combos ---------
class SavedSegmentRequest(BaseModel):
    name: str
    description: Optional[str] = None
    filters: Dict[str, Any]                 # UI-shape filters dict
    segment: Optional[Dict[str, Any]] = None  # alt type-based segment


@app.get("/api/owner/segments")
def list_saved_segments(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    rows = list(db.saved_segments.find({"tenant_id": token_data.tenant_id}).sort("created_at", -1))
    for r in rows:
        r.pop("_id", None)
    return {"segments": rows}


@app.post("/api/owner/segments")
def create_saved_segment(
    req: SavedSegmentRequest,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": token_data.tenant_id,
        "name": req.name.strip()[:120] or "Unnamed segment",
        "description": (req.description or "").strip()[:500],
        "filters": req.filters or {},
        "segment": req.segment or None,
        "created_at": datetime.now(timezone.utc),
    }
    db.saved_segments.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.delete("/api/owner/segments/{segment_id}")
def delete_saved_segment(
    segment_id: str,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    res = db.saved_segments.delete_one({"id": segment_id, "tenant_id": token_data.tenant_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Segment not found")
    return {"status": "ok"}


# --- Feature 12: Active cards widget + upgrade prompt --------
@app.get("/api/owner/analytics/active-cards")
def get_active_cards(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """How many pass_issued cards are active. Nudges an upgrade if close to plan limit."""
    tid = token_data.tenant_id
    tenant = db.tenants.find_one({"id": tid})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    active = db.customers.count_documents({"tenant_id": tid, "pass_issued": True})
    total = db.customers.count_documents({"tenant_id": tid})
    plan = tenant.get("plan", "basic")
    plan_cap = get_plan_features(plan).get("max_customers", 500)

    usage_pct = round(active / plan_cap * 100, 1) if plan_cap else 0
    near_limit = usage_pct >= 80

    # Suggest next plan up
    next_plan = {"basic": "gold", "gold": "vip", "vip": "chain", "chain": None}.get(plan)
    next_plan_cap = get_plan_features(next_plan).get("max_customers") if next_plan else None
    next_plan_price = PLAN_PRICES.get(next_plan) if next_plan else None

    return {
        "active_cards": active,
        "total_customers": total,
        "plan": plan,
        "plan_cap": plan_cap,
        "usage_pct": usage_pct,
        "near_limit": near_limit,
        "suggest_upgrade": near_limit and next_plan is not None,
        "next_plan": next_plan,
        "next_plan_cap": next_plan_cap,
        "next_plan_price": next_plan_price,
    }


# ============================================================
# ADMIN INSIGHTS — platform-wide rollup of the 12 insight features
# Used by the super-admin Insights page. Every number here is
# derived from the same collections the owner-side Insights page
# uses, guaranteeing consistency across the UI.
# ============================================================

@app.get("/api/admin/insights")
def get_admin_insights(token_data: TokenData = Depends(require_role(["super_admin"]))):
    """Platform-wide Insights: churn, LTV, alerts, active cards, top performers.
    Single response so the admin Insights page renders with one round-trip on the
    frontend. All numbers come from the same aggregations Dashboard uses, so they
    match the global admin dashboard numbers.
    """
    now = datetime.now(timezone.utc)
    thirty = now - timedelta(days=30)
    sixty = now - timedelta(days=60)
    ninety = now - timedelta(days=90)

    tenants = list(db.tenants.find({"is_active": {"$ne": False}}))
    all_customers = list(db.customers.find({}))
    total_customers = len(all_customers)

    # --- Churn buckets across the whole platform ---
    def pct(n):
        return round((n / total_customers) * 100, 1) if total_customers else 0.0

    one_visit = sum(1 for c in all_customers if c.get("visits", 0) <= 1)
    inactive_30 = sum(1 for c in all_customers if c.get("last_visit_date") and c["last_visit_date"] < thirty)
    inactive_60 = sum(1 for c in all_customers if c.get("last_visit_date") and c["last_visit_date"] < sixty)
    churned_90 = sum(1 for c in all_customers if c.get("last_visit_date") and c["last_visit_date"] < ninety)

    # --- LTV across the platform ---
    spend_values = sorted(c.get("total_amount_paid", 0) for c in all_customers)
    ltv_avg = round(sum(spend_values) / len(spend_values), 2) if spend_values else 0
    ltv_median = round(spend_values[len(spend_values) // 2], 2) if spend_values else 0
    ltv_top10 = round(spend_values[int(len(spend_values) * 0.9)], 2) if len(spend_values) >= 10 else (spend_values[-1] if spend_values else 0)

    ltv_by_tier = {}
    for c in all_customers:
        tier = (c.get("tier") or "bronze").lower()
        ltv_by_tier.setdefault(tier, []).append(c.get("total_amount_paid", 0))
    ltv_by_tier_out = [
        {
            "tier": t,
            "count": len(vals),
            "average_ltv": round(sum(vals) / len(vals), 2) if vals else 0,
            "total_revenue": round(sum(vals), 2),
        }
        for t, vals in sorted(ltv_by_tier.items(), key=lambda kv: {"gold": 0, "silver": 1, "bronze": 2}.get(kv[0], 3))
    ]

    # --- Active wallet passes ---
    active_cards = sum(1 for c in all_customers if c.get("pass_issued"))

    # --- Per-tenant visit counts (ONE aggregation) ---
    visits_by_tenant = {
        d["_id"]: d["count"]
        for d in db.visits.aggregate([
            {"$group": {"_id": "$tenant_id", "count": {"$sum": 1}}}
        ])
    }
    total_visits = sum(visits_by_tenant.values())

    customers_by_tenant = {}
    for c in all_customers:
        customers_by_tenant.setdefault(c.get("tenant_id"), []).append(c)

    # Platform-level alerts
    alerts = []
    if inactive_30 >= 10:
        alerts.append({
            "level": "warning", "icon": "⚠️",
            "title": f"{inactive_30} clients inactifs depuis 30 jours sur toute la plateforme",
            "detail": "Encouragez vos commerçants à lancer une campagne de relance."
        })
    if one_visit >= 50:
        alerts.append({
            "level": "warning", "icon": "🚪",
            "title": f"{pct(one_visit)}% des clients ne reviennent pas après 1 visite",
            "detail": "Moyenne plateforme. Proposez un template de bienvenue aux commerces concernés."
        })

    # Top performers across the platform (by visits)
    perf = []
    for t in tenants:
        tid = t["id"]
        t_custs = customers_by_tenant.get(tid, [])
        rev = round(sum(c.get("total_amount_paid", 0) for c in t_custs), 2)
        perf.append({
            "id": tid,
            "name": t.get("name"),
            "plan": t.get("plan", "basic"),
            "customers": len(t_custs),
            "visits": visits_by_tenant.get(tid, 0),
            "revenue": rev,
        })
    top_performers = sorted(perf, key=lambda x: x["visits"], reverse=True)[:10]
    bottom_performers = sorted(
        [p for p in perf if p["customers"] > 0],
        key=lambda x: x["visits"],
    )[:10]

    # Sector distribution for reactivation templates
    sector_counts = {}
    for t in tenants:
        sector = t.get("sector") or "other"
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    return {
        "totals": {
            "tenants": len(tenants),
            "customers": total_customers,
            "visits": total_visits,
            "active_cards": active_cards,
        },
        "churn": {
            "one_visit_only": one_visit,
            "one_visit_only_pct": pct(one_visit),
            "inactive_30d": inactive_30,
            "inactive_30d_pct": pct(inactive_30),
            "inactive_60d": inactive_60,
            "inactive_60d_pct": pct(inactive_60),
            "churned_90d": churned_90,
            "churned_90d_pct": pct(churned_90),
        },
        "ltv": {
            "average_ltv": ltv_avg,
            "median_ltv": ltv_median,
            "top_10_pct_ltv": ltv_top10,
            "by_tier": ltv_by_tier_out,
        },
        "alerts": alerts,
        "top_performers": top_performers,
        "at_risk_performers": bottom_performers,
        "sector_distribution": [
            {"sector": k, "count": v}
            for k, v in sorted(sector_counts.items(), key=lambda kv: kv[1], reverse=True)
        ],
    }


# ============================================================
# FEATURE ROLLOUT (Apr 2026, part 2): the 8 gaps from the audit
# 1. Offre anniversaire automatique (birthday auto-send)
# 2. Niveau VIP atteint — tier-up push (wired in /owner/scan above)
# 3. Campagnes auto (scheduled + recurring)
# 4. Offres personnalisées (template vars — render_template())
# 5. "Il te reste 2 points pour une récompense" (wired in /owner/scan above)
# 6. Super-admin broadcast to all end-customers
# 7. Upgrade-plan request flow
# 8. Triggered campaigns framework (cron drains triggers + schedules)
# ============================================================

CRON_SECRET = os.environ.get("CRON_SECRET", "")


def _dispatch_campaign_to_customers(tenant: dict, name: str, content: str, customer_list: list, trigger_type: str = "manual"):
    """Shared dispatch helper used by cron triggers + scheduled sends. Creates a
    Campaign doc and a push_notification per customer, and emails when possible."""
    if not customer_list:
        return None
    tid = tenant.get("id")
    sender_name = tenant.get("campaign_sender_name") or tenant.get("name") or "FidéliTour"
    now = datetime.now(timezone.utc)
    delivered = 0
    for cust in customer_list:
        rendered_body = render_template(content, cust, tenant)
        rendered_subject = render_template(name, cust, tenant)
        db.push_notifications.insert_one({
            "customer_id": cust["id"],
            "tenant_id": tid,
            "title": rendered_subject,
            "body": rendered_body,
            "type": trigger_type,
            "sent_at": now,
        })
        # Scheduled sends and the daily cron triggers run through here — they
        # were on the dead email path too, so a scheduled campaign wrote a card
        # row and reached nobody.
        if dispatch_to_customer(tid, cust, rendered_subject, rendered_body,
                                kind=trigger_type)["sent"]:
            delivered += 1
    campaign = Campaign(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        name=name,
        content=content,
        status="sent",
        filters={"auto_trigger": trigger_type},
        sent_at=now,
        targeted_count=len(customer_list),
        delivered_count=delivered,
        recipient_ids=[c["id"] for c in customer_list],
    )
    db.campaigns.insert_one(campaign.model_dump())
    return campaign.model_dump()


# --- 3 & 8: Scheduled campaigns ------------------------------
class ScheduleCampaignRequest(BaseModel):
    name: str
    content: str
    run_at: str  # ISO datetime string
    segment: Optional[Dict[str, Any]] = None
    # Same filter shape as live send (tiers/minPoints/minVisits/postalCodes/minAmountPaid).
    # If provided, takes precedence over segment when the cron drains it.
    filters: Optional[Dict[str, Any]] = None
    source: Optional[str] = None  # push | email | other  — only the channels FidéliTour delivers on today
    recurrence: Optional[str] = None  # None | "daily" | "weekly" | "monthly"


def _filters_to_customer_query(tid: str, filters: dict) -> dict:
    """Translate the UI filter shape to a Mongo query. Shared between live send,
    segment preview, and scheduled campaign drain."""
    q = {"tenant_id": tid}
    if not filters:
        return q
    # Accept snake_case and camelCase from older callers
    tier = filters.get("tier")
    tiers = filters.get("tiers")
    if tiers and isinstance(tiers, list):
        q["tier"] = {"$in": tiers}
    elif tier:
        q["tier"] = tier
    mv = filters.get("min_visits") or filters.get("minVisits")
    if mv:
        q["visits"] = {"$gte": int(mv)}
    mp = filters.get("min_points") or filters.get("minPoints")
    if mp:
        q["points"] = {"$gte": int(mp)}
    pcs = filters.get("postal_codes") or filters.get("postalCodes")
    pc_single = filters.get("postal_code")
    if pcs:
        if isinstance(pcs, str):
            pcs = [p.strip() for p in pcs.split(",") if p.strip()]
        q["postal_code"] = {"$in": list(pcs)}
    elif pc_single:
        q["postal_code"] = pc_single
    ma = filters.get("min_amount_paid") or filters.get("minAmountPaid")
    if ma:
        q["total_amount_paid"] = {"$gte": float(ma)}
    city = filters.get("city")
    if city:
        q["city"] = city
    # Note: we deliberately do NOT honor `has_wallet_pass`/`hasWalletPass` — the
    # platform is wallet-only by design, so that filter is a no-op.
    return q


@app.post("/api/owner/campaigns/schedule")
def schedule_campaign(
    req: ScheduleCampaignRequest,
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Queue a campaign to be dispatched later (or on a recurring cadence)."""
    try:
        run_at = datetime.fromisoformat(req.run_at.replace("Z", "+00:00"))
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="run_at must be ISO 8601")
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": token_data.tenant_id,
        "name": req.name,
        "content": req.content,
        "segment": req.segment or {"type": "all"},
        "filters": req.filters or None,
        "source": (req.source or "push"),
        "run_at": run_at,
        "recurrence": req.recurrence,
        "status": "scheduled",
        "created_at": datetime.now(timezone.utc),
    }
    db.scheduled_campaigns.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.get("/api/owner/campaigns/scheduled")
def list_scheduled(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    rows = list(db.scheduled_campaigns.find({"tenant_id": token_data.tenant_id}).sort("run_at", 1))
    for r in rows:
        r.pop("_id", None)
    return {"scheduled": rows}


@app.delete("/api/owner/campaigns/scheduled/{sched_id}")
def delete_scheduled(sched_id: str, token_data: TokenData = Depends(require_role(["business_owner"]))):
    res = db.scheduled_campaigns.delete_one({"id": sched_id, "tenant_id": token_data.tenant_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Scheduled campaign not found")
    return {"status": "ok"}


def _resolve_segment(tid: str, segment: dict) -> list:
    """Shared segment → customer-list resolver. Returns list of customer dicts."""
    now = datetime.now(timezone.utc)
    if not segment:
        return list(db.customers.find({"tenant_id": tid}))
    stype = (segment.get("type") or "").lower()
    q = {"tenant_id": tid}
    if stype == "tier" and segment.get("value"):
        q["tier"] = segment["value"]
    elif stype == "inactive_days":
        days = int(segment.get("value") or 30)
        q["last_visit_date"] = {"$lt": now - timedelta(days=days)}
    elif stype == "birthday_month" and segment.get("value"):
        mm = str(segment["value"]).zfill(2)
        q["birthday"] = {"$regex": f"^{mm}"}
    elif stype == "birthday_today":
        today_mmdd = now.strftime("%m-%d")
        q["birthday"] = today_mmdd
    elif stype == "acquisition" and segment.get("value"):
        q["acquisition_source"] = segment["value"]
    elif stype == "postal_code" and segment.get("value"):
        q["postal_code"] = segment["value"]
    elif stype == "department_code" and segment.get("value"):
        q["postal_code"] = {"$regex": f"^{segment['value']}"}
    elif stype == "one_visit_only":
        q["visits"] = {"$lte": 1}
    elif stype == "all":
        pass
    return list(db.customers.find(q))


# --- 1, 8, 3: Daily trigger cron -----------------------------
# Vercel Cron sends GET requests; manual triggers (UI button + curl) use POST.
# Both paths share the same handler below.
def _supersede_pending(tenant_id: str, kind: str) -> int:
    """Retire any batch of this kind still waiting for approval.

    Why: a prepared batch is never logged in `auto_campaign_log` — only a
    SENT one is. The cooldown that stops a customer being pestered therefore
    never fires for a batch the owner has not approved, so the next run
    recomputes the exact same audience and files an identical batch. Leave
    that alone for a fortnight and the approval queue is thirty copies of
    "vous nous manquez", all pointing at the same 110 people.

    Superseding rather than skipping is deliberate: the newest batch is the
    only one whose "inactive since" list is still true today. Old batches are
    marked rather than deleted so the history stays auditable.
    """
    try:
        res = db.pending_auto_runs.update_many(
            {"tenant_id": tenant_id, "kind": kind, "status": "pending"},
            {"$set": {"status": "superseded",
                      "superseded_at": datetime.now(timezone.utc)}},
        )
        return res.modified_count
    except Exception as e:
        print(f"_supersede_pending failed ({kind}): {e}")
        return 0


@app.get("/api/cron/daily-triggers")
@app.post("/api/cron/daily-triggers")
def run_daily_triggers(request: Request):
    """Cron endpoint (hit daily by Vercel Cron or manually).
    Authenticated via Authorization: Bearer <CRON_SECRET> OR ?secret=... OR X-Cron-Secret header.
    Vercel Cron passes the secret via the Authorization header automatically when
    CRON_SECRET is set as an env var on the project.
    Does 4 things:
      A. For each tenant, prepare birthday offers (owner reviews before send).
      B. For each tenant, prepare reactivation pushes to customers inactive >30d
         (cooldown: don't re-trigger within 14 days).
      C. For each tenant, prepare 'almost there' nudges for customers N visits
         away from their next reward.
      D. Drain scheduled_campaigns where run_at <= now and recurrence handling.
    """
    # Auth check (lenient: allow empty secret in dev, require in prod)
    provided = (
        request.headers.get("x-cron-secret")
        or (request.headers.get("authorization", "").replace("Bearer ", "") if request.headers.get("authorization") else "")
        or request.query_params.get("secret", "")
    )
    if CRON_SECRET and provided != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron secret")

    now = datetime.now(timezone.utc)
    today_mmdd = now.strftime("%m-%d")
    cutoff_inactive = now - timedelta(days=30)
    cooldown_cutoff = now - timedelta(days=14)

    tenants = list(db.tenants.find({"is_active": {"$ne": False}}))
    birthday_sent = 0
    reactivation_sent = 0
    almost_there_sent = 0
    scheduled_sent = 0
    tier_up_emitted_count = 0

    for tenant in tenants:
        tid = tenant["id"]
        # Owner-editable templates — fall back to defaults if unset
        cfg = db.auto_campaign_config.find_one({"tenant_id": tid}) or {}

        # A. Birthday — PREPARE (owner reviews + approves before send)
        if cfg.get("birthday_enabled", True):
            bday_customers = list(db.customers.find({"tenant_id": tid, "birthday": today_mmdd}))
            if bday_customers:
                title = cfg.get("birthday_title") or "🎂 Joyeux anniversaire {first_name} !"
                body = cfg.get("birthday_message") or "Joyeux anniversaire {first_name} ! Une attention vous attend chez {business_name}."
                _supersede_pending(tid, "birthday")
                db.pending_auto_runs.insert_one({
                    "id": str(uuid.uuid4()),
                    "tenant_id": tid,
                    "kind": "birthday",
                    "title": title,
                    "body_template": body,
                    "recipients": [
                        {"customer_id": c["id"], "name": c.get("name", ""),
                         "phone": c.get("phone", ""), "email": c.get("email", ""),
                         "first_name": (c.get("name") or "").split(" ")[0]}
                        for c in bday_customers
                    ],
                    "recipient_count": len(bday_customers),
                    "status": "pending",
                    "prepared_at": now,
                })
                birthday_sent += len(bday_customers)

        # B. Inactivity reactivation — PREPARE (cooldown-protected)
        if cfg.get("inactive_enabled", True):
            inactive_customers = list(db.customers.find({
                "tenant_id": tid,
                "last_visit_date": {"$lt": cutoff_inactive, "$ne": None},
            }))
            already_nudged_ids = set()
            for p in db.push_notifications.find({
                "tenant_id": tid, "type": "reactivation",
                "sent_at": {"$gte": cooldown_cutoff},
            }):
                already_nudged_ids.add(p.get("customer_id"))
            fresh_inactive = [c for c in inactive_customers if c["id"] not in already_nudged_ids]
            if fresh_inactive:
                title = cfg.get("inactive_title") or "{business_name} — vous nous manquez"
                body = cfg.get("inactive_message") or "{first_name}, ça fait un moment ! Revenez nous voir, une attention vous attend chez {business_name}."
                _supersede_pending(tid, "inactive_rescue")
                db.pending_auto_runs.insert_one({
                    "id": str(uuid.uuid4()),
                    "tenant_id": tid,
                    "kind": "inactive_rescue",
                    "title": title,
                    "body_template": body,
                    "recipients": [
                        {"customer_id": c["id"], "name": c.get("name", ""),
                         "phone": c.get("phone", ""), "email": c.get("email", ""),
                         "first_name": (c.get("name") or "").split(" ")[0]}
                        for c in fresh_inactive
                    ],
                    "recipient_count": len(fresh_inactive),
                    "status": "pending",
                    "prepared_at": now,
                })
                reactivation_sent += len(fresh_inactive)

        # C. Almost there — PREPARE (cooldown-protected; uses card template cycle)
        if cfg.get("almost_there_enabled", True):
            tpl = db.card_templates.find_one({"tenant_id": tid}) or {}
            visits_per_stamp = max(int(tpl.get("visits_per_stamp", 1) or 1), 1)
            reward_threshold = max(int(tpl.get("reward_threshold_stamps", 10) or 10), 1)
            cycle = visits_per_stamp * reward_threshold
            target_remaining = max(1, int(cfg.get("almost_there_visits_left", 1) or 1))
            at_cooldown_days = max(1, int(cfg.get("almost_there_cooldown_days", 7) or 7))
            at_cooldown_cutoff = now - timedelta(days=at_cooldown_days)

            already_at_ids = set()
            for log in db.auto_campaign_log.find({
                "tenant_id": tid, "kind": "almost_there",
                "sent_at": {"$gte": at_cooldown_cutoff},
            }):
                already_at_ids.add(log.get("customer_id"))

            at_candidates = list(db.customers.find({
                "tenant_id": tid, "visits": {"$gt": 0},
            }).limit(2000))
            at_eligible = []
            for c in at_candidates:
                if c["id"] in already_at_ids:
                    continue
                v = int(c.get("visits", 0) or 0)
                remaining = cycle - (v % cycle) if (v % cycle) else cycle
                if remaining == target_remaining:
                    at_eligible.append(c)

            if at_eligible:
                title = cfg.get("almost_there_title") or "Plus qu'une visite ! 🎁"
                body = cfg.get("almost_there_message") or "{first_name}, vous êtes à 1 visite d'une récompense chez {business_name} ! ☕"
                _supersede_pending(tid, "almost_there")
                db.pending_auto_runs.insert_one({
                    "id": str(uuid.uuid4()),
                    "tenant_id": tid,
                    "kind": "almost_there",
                    "title": title,
                    "body_template": body,
                    "recipients": [
                        {"customer_id": c["id"], "name": c.get("name", ""),
                         "phone": c.get("phone", ""), "email": c.get("email", ""),
                         "first_name": (c.get("name") or "").split(" ")[0],
                         "visits_left": target_remaining}
                        for c in at_eligible
                    ],
                    "recipient_count": len(at_eligible),
                    "status": "pending",
                    "prepared_at": now,
                })
                almost_there_sent += len(at_eligible)

    # D. Drain scheduled campaigns
    due = list(db.scheduled_campaigns.find({
        "run_at": {"$lte": now},
        "status": "scheduled",
    }))
    for sc in due:
        tenant = db.tenants.find_one({"id": sc["tenant_id"]})
        if not tenant:
            db.scheduled_campaigns.update_one({"id": sc["id"]}, {"$set": {"status": "cancelled"}})
            continue
        # Prefer UI-style filters if the schedule was saved with them; fall back
        # to the legacy segment-based resolver otherwise.
        if sc.get("filters"):
            q = _filters_to_customer_query(sc["tenant_id"], sc["filters"])
            recipients = list(db.customers.find(q))
        else:
            recipients = _resolve_segment(sc["tenant_id"], sc.get("segment") or {"type": "all"})
        dispatched = _dispatch_campaign_to_customers(
            tenant,
            name=sc["name"],
            content=sc["content"],
            customer_list=recipients,
            trigger_type="scheduled",
        )
        # Stamp the source on the emitted campaign so analytics attribute
        # scheduled sends to their channel (Instagram, email, push, etc.).
        if dispatched and sc.get("source"):
            db.campaigns.update_one(
                {"id": dispatched["id"]},
                {"$set": {"source": sc["source"]}},
            )
        scheduled_sent += len(recipients)

        # Recurrence: bump run_at and keep scheduled, or mark sent.
        rec = sc.get("recurrence")
        if rec == "daily":
            next_run = sc["run_at"] + timedelta(days=1)
            db.scheduled_campaigns.update_one({"id": sc["id"]}, {"$set": {"run_at": next_run}})
        elif rec == "weekly":
            next_run = sc["run_at"] + timedelta(days=7)
            db.scheduled_campaigns.update_one({"id": sc["id"]}, {"$set": {"run_at": next_run}})
        elif rec == "monthly":
            next_run = sc["run_at"] + timedelta(days=30)
            db.scheduled_campaigns.update_one({"id": sc["id"]}, {"$set": {"run_at": next_run}})
        else:
            db.scheduled_campaigns.update_one({"id": sc["id"]}, {"$set": {"status": "sent", "sent_at": now}})

    return {
        "status": "ok",
        "ran_at": now.isoformat(),
        "birthday_prepared": birthday_sent,
        "reactivation_prepared": reactivation_sent,
        "almost_there_prepared": almost_there_sent,
        "scheduled_sent": scheduled_sent,
        "tier_up_emitted": tier_up_emitted_count,
        "tenants_processed": len(tenants),
    }


@app.get("/api/cron/monthly-report")
@app.post("/api/cron/monthly-report")
def run_monthly_report_dispatch(request: Request):
    """Sends each owner an email summary of last month's performance.

    Designed to be hit on the 1st of every month. Idempotent within a given
    month — uses db.system_jobs to record the last dispatch month so a
    re-run doesn't double-send.

    Auth: same Bearer / X-Cron-Secret pattern as /cron/daily-triggers.
    """
    provided = (
        request.headers.get("x-cron-secret")
        or (request.headers.get("authorization", "").replace("Bearer ", "") if request.headers.get("authorization") else "")
        or request.query_params.get("secret", "")
    )
    if CRON_SECRET and provided != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron secret")

    now = datetime.now(timezone.utc)
    # Cover the previous calendar month.
    first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = first_of_this_month - timedelta(seconds=1)
    last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_label = last_month_start.strftime("%Y-%m")

    # Idempotency check.
    last_run = db.system_jobs.find_one({"job": "monthly_report"})
    if last_run and last_run.get("month") == month_label:
        return {"ok": True, "skipped": "already_dispatched", "month": month_label}

    sent = 0
    skipped = 0
    tenants = list(db.tenants.find({"is_active": {"$ne": False}}))

    for tenant in tenants:
        tid = tenant["id"]
        # Find the owner's email so we know where to deliver.
        owner = db.users.find_one({"tenant_id": tid, "role": "business_owner"})
        if not owner or not owner.get("email"):
            skipped += 1
            continue

        # Inline rollup — don't call the HTTP endpoint, just compute.
        cust_count = db.customers.count_documents({"tenant_id": tid})
        new_cust_count = db.customers.count_documents({
            "tenant_id": tid, "created_at": {"$gte": last_month_start, "$lt": first_of_this_month},
        })
        visits_in_month = db.visits.aggregate([
            {"$match": {"tenant_id": tid, "created_at": {"$gte": last_month_start, "$lt": first_of_this_month}}},
            {"$group": {"_id": None, "count": {"$sum": 1}, "revenue": {"$sum": {"$ifNull": ["$amount_paid", 0]}}}},
        ])
        rolled = next(iter(visits_in_month), {}) or {}
        visits_count = int(rolled.get("count") or 0)
        revenue = round(float(rolled.get("revenue") or 0), 2)
        avg_ticket = round(revenue / visits_count, 2) if visits_count else 0

        body = (
            f"Bonjour,\n\n"
            f"Voici votre récap pour {last_month_start.strftime('%B %Y')} chez {tenant.get('name','votre établissement')} :\n\n"
            f"• {cust_count} clients au total ({new_cust_count} nouveaux ce mois-ci)\n"
            f"• {visits_count} visites enregistrées\n"
            f"• €{revenue:,.0f} de chiffre d'affaires fidélité\n"
            f"• €{avg_ticket} de panier moyen\n\n"
            f"Le détail complet est disponible sur votre tableau de bord FidéliTour.\n\n"
            f"Bonne continuation !\n— L'équipe FidéliTour"
        ).replace(",", " ")
        html = _campaign_html(
            "FidéliTour",
            f"Récap {last_month_start.strftime('%B %Y')} — {tenant.get('name','')}",
            body,
            {"name": owner["email"].split("@")[0].title(), "tier": "owner", "visits": 0, "points": 0},
        )
        if send_email_to_customer(owner["email"], "FidéliTour", f"Récap {last_month_start.strftime('%B %Y')}", html):
            sent += 1
        else:
            skipped += 1

    db.system_jobs.update_one(
        {"job": "monthly_report"},
        {"$set": {"job": "monthly_report", "month": month_label, "ran_at": now, "sent": sent, "skipped": skipped}},
        upsert=True,
    )

    return {"ok": True, "month": month_label, "sent": sent, "skipped": skipped}


# --- 6: Super-admin broadcast to all end-customers -----------
class AdminBroadcastRequest(BaseModel):
    subject: str
    body: str
    sender_name: Optional[str] = None  # name displayed as sender
    filters: Optional[Dict[str, Any]] = None  # {tier, sector, department_code, acquisition, tenant_id}


@app.post("/api/admin/broadcast")
def admin_broadcast(
    req: AdminBroadcastRequest,
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Admin-authored broadcast to end-customers across tenants.
    Sends under the admin-chosen sender name.
    """
    if not req.subject.strip() or not req.body.strip():
        raise HTTPException(status_code=400, detail="subject and body required")
    filters = req.filters or {}
    sender_name = (req.sender_name or "FidéliTour").strip()
    now = datetime.now(timezone.utc)

    # Build customer query
    cust_q = {}
    if filters.get("tier"):
        cust_q["tier"] = filters["tier"]
    if filters.get("acquisition"):
        cust_q["acquisition_source"] = filters["acquisition"]
    if filters.get("department_code"):
        cust_q["postal_code"] = {"$regex": f"^{filters['department_code']}"}
    if filters.get("tenant_id"):
        cust_q["tenant_id"] = filters["tenant_id"]

    # If sector filter set, resolve to tenant ids first.
    if filters.get("sector"):
        ts = list(db.tenants.find({"sector": filters["sector"]}, {"id": 1}))
        cust_q["tenant_id"] = {"$in": [t["id"] for t in ts]}

    targets = list(db.customers.find(cust_q))
    delivered = 0
    broadcast_id = str(uuid.uuid4())
    tenant_cache = {}
    for c in targets:
        tid = c.get("tenant_id")
        if tid not in tenant_cache:
            tenant_cache[tid] = db.tenants.find_one({"id": tid}) or {}
        tenant = tenant_cache[tid]
        rendered_subject = render_template(req.subject, c, tenant)
        rendered_body = render_template(req.body, c, tenant)
        db.push_notifications.insert_one({
            "customer_id": c["id"],
            "tenant_id": tid,
            "title": rendered_subject,
            "body": rendered_body,
            "type": "admin_broadcast",
            "broadcast_id": broadcast_id,
            "sender_name": sender_name,
            "sent_at": now,
        })
        if dispatch_to_customer(tid, c, rendered_subject, rendered_body,
                                kind="admin_broadcast")["sent"]:
            delivered += 1

    doc = {
        "id": broadcast_id,
        "subject": req.subject,
        "body": req.body,
        "sender_name": sender_name,
        "filters": filters,
        "targeted_count": len(targets),
        "delivered_count": delivered,
        "sent_at": now,
        "sent_by": token_data.email if hasattr(token_data, "email") else None,
    }
    db.admin_broadcasts.insert_one(doc)
    doc.pop("_id", None)
    return doc


class AdminBroadcastPreviewRequest(BaseModel):
    filters: Optional[Dict[str, Any]] = None


@app.post("/api/admin/broadcast/preview")
def admin_broadcast_preview(
    req: AdminBroadcastPreviewRequest,
    token_data: TokenData = Depends(require_role(["super_admin"])),
):
    """Returns the number of end-customers that would match the given broadcast filters,
    without sending anything. Mirrors the filter logic of /api/admin/broadcast."""
    filters = req.filters or {}
    cust_q: Dict[str, Any] = {}
    if filters.get("tier"):
        cust_q["tier"] = filters["tier"]
    if filters.get("acquisition"):
        cust_q["acquisition_source"] = filters["acquisition"]
    if filters.get("department_code"):
        cust_q["postal_code"] = {"$regex": f"^{filters['department_code']}"}
    if filters.get("tenant_id"):
        cust_q["tenant_id"] = filters["tenant_id"]
    if filters.get("sector"):
        ts = list(db.tenants.find({"sector": filters["sector"]}, {"id": 1}))
        cust_q["tenant_id"] = {"$in": [t["id"] for t in ts]}
    count = db.customers.count_documents(cust_q)
    with_email = db.customers.count_documents({**cust_q, "email": {"$exists": True, "$ne": ""}})
    return {"count": count, "with_email": with_email}


@app.get("/api/admin/broadcasts")
def list_admin_broadcasts(token_data: TokenData = Depends(require_role(["super_admin"]))):
    rows = list(db.admin_broadcasts.find().sort("sent_at", -1).limit(100))
    for r in rows:
        r.pop("_id", None)
    return {"broadcasts": rows}


# --- 7: Upgrade-plan request flow ----------------------------
class UpgradeRequest(BaseModel):
    message: Optional[str] = None
    requested_plan: Optional[str] = None


@app.post("/api/owner/request-upgrade")
def request_upgrade(
    req: UpgradeRequest,
    token_data: TokenData = Depends(require_role(["business_owner"]))
):
    """Owner signals they want to upgrade their plan (usually when near card cap)."""
    tid = token_data.tenant_id
    tenant = db.tenants.find_one({"id": tid}) or {}
    current_plan = tenant.get("plan", "basic")
    next_plan = {"basic": "gold", "gold": "vip", "vip": "chain", "chain": None}.get(current_plan)
    requested = req.requested_plan or next_plan
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tid,
        "tenant_name": tenant.get("name"),
        "current_plan": current_plan,
        "requested_plan": requested,
        "message": req.message or "",
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
    }
    db.upgrade_requests.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.get("/api/admin/upgrade-requests")
def list_upgrade_requests(token_data: TokenData = Depends(require_role(["super_admin"]))):
    rows = list(db.upgrade_requests.find().sort("created_at", -1).limit(200))
    for r in rows:
        r.pop("_id", None)
    return {"requests": rows}


@app.put("/api/admin/upgrade-requests/{req_id}")
def resolve_upgrade_request(
    req_id: str,
    body: Dict[str, Any],
    token_data: TokenData = Depends(require_role(["super_admin"]))
):
    """Mark as approved / declined / completed."""
    new_status = body.get("status") or "completed"
    if new_status not in ("approved", "declined", "completed", "pending"):
        raise HTTPException(status_code=400, detail="invalid status")
    res = db.upgrade_requests.update_one(
        {"id": req_id},
        {"$set": {"status": new_status, "resolved_at": datetime.now(timezone.utc)}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Request not found")
    return {"status": "ok", "new_status": new_status}


# ============================================================
# Additive feature pack — see features/_README.md
# Registers 17 new feature modules (welcome bonus, referrals, happy hour,
# reviews, registration forms, AI churn/send-time, etc.) without modifying
# any existing endpoint or model. Safe to comment out to roll back.
# ============================================================
from features._loader import register_all
register_all(app, db)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=True)
