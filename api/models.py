from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from uuid import uuid4

# Three-tier plan catalogue. Silver is the entry tier every new business
# starts on (post-trial). Each row defines BOTH the quota caps and the
# feature toggles — the admin /admin/plans editor can override any field
# on any plan, live, without redeploying (see get_plan_features() in
# api/server.py). PLAN_PRICES is the monthly euro price shown in the UI.
#
# Trial: every new tenant starts with `subscription_status="trialing"` on
# TRIAL_PLAN (Pro AI, every feature) for trial_duration_days = the value in
# PLAN_TRIAL_DAYS below (30 days, no card). On day 29
# (TRIAL_REMINDER_DAYS_BEFORE = 1) the owner gets an email + in-app banner
# asking them to pick a plan; on day 30 the trial expires and paid features
# lock until they subscribe.
PLAN_FEATURES = {
    # Internal keys stay silver/gold/vip — every tenant row, Stripe price and
    # admin override already references them. PLAN_LABELS below carries the
    # commercial names shown to merchants (Starter / Pro / Pro AI), so a
    # rename never has to touch the database.
    "silver": {                         # Starter — 33 € HT
        # The cap counts ACTIVE customers — those who came at least once in
        # the last 12 months. A client who stopped coming two years ago stays
        # in the merchant's database, stays visible, and costs them nothing.
        "max_customers": 1500,
        "new_cards_per_month": 500,
        "push_per_month": 2000,         # 0 = unlimited; counted from delivery_log
        # « Ajoutez votre carte » emails to imported clients (Clients › Importer).
        "invite_emails_per_month": 200,
        "campaigns_per_month": 20,      # counted only where « campaigns » is on
        "staff_accounts": 2,            # owner + 1 collaborator
        "establishments": 1,
        "ai_queries_per_day": 0,        # AI disabled on Starter
        "csv_export": True,             # importing/exporting your own customers
        "geo_proximity": False,
        "multi_branch": False,
        # What the plan unlocks (pricing grid, 2026-09-30). A locked section
        # stays visible to the merchant; opening it shows the upgrade prompt.
        # ai_level: "none" | "basic" | "advanced" — see AI_LEVEL_LIMITS.
        "ai_level": "none",
        "priority_support": False,
        "advanced_analytics": False,
        "crm_advanced": False,
        "segmentation": False,
        "campaigns": False,
        "automations": False,
        "referral": False,
        "wallet": True,
        "api_access": False,
    },
    "gold": {                           # Pro — 65 € HT
        "max_customers": 4500,
        "new_cards_per_month": 1500,
        "push_per_month": 6000,
        "invite_emails_per_month": 1000,
        "campaigns_per_month": 100,
        "staff_accounts": 6,
        "establishments": 1,
        "ai_queries_per_day": 20,
        "csv_export": True,
        "geo_proximity": True,
        "multi_branch": False,
        "ai_level": "basic",
        "priority_support": True,
        "advanced_analytics": True,
        "crm_advanced": True,
        "segmentation": True,
        "campaigns": True,
        "automations": True,
        "referral": True,
        "wallet": True,
        "api_access": False,
    },
    "vip": {                            # Pro AI — 108 € HT
        "max_customers": 15000,
        "new_cards_per_month": 4000,
        "push_per_month": 0,            # unlimited
        "invite_emails_per_month": 3000,
        "campaigns_per_month": 0,       # unlimited
        "staff_accounts": 15,
        "establishments": 3,
        "ai_queries_per_day": 50,
        "csv_export": True,
        "geo_proximity": True,
        "multi_branch": True,
        "ai_level": "advanced",
        "priority_support": True,
        "advanced_analytics": True,
        "crm_advanced": True,
        "segmentation": True,
        "campaigns": True,
        "automations": True,
        "referral": True,
        "wallet": True,
        "api_access": True,
    },
    # Franchise — sur devis (decided with the user): every network has its own
    # number of stores, so there is no public price. These are the defaults;
    # the super admin sets each franchise's own price and limits on its tenant
    # (tenant.franchise_terms, see server.features_for()).
    "franchise": {
        "max_customers": 50000,
        "new_cards_per_month": 20000,
        "push_per_month": 0,
        "invite_emails_per_month": 10000,
        "campaigns_per_month": 0,
        "staff_accounts": 50,
        "establishments": 10,
        "ai_queries_per_day": 100,
        "csv_export": True,
        "geo_proximity": True,
        "multi_branch": True,
        "ai_level": "advanced",
        "priority_support": True,
        "advanced_analytics": True,
        "crm_advanced": True,
        "segmentation": True,
        "campaigns": True,
        "automations": True,
        "referral": True,
        "wallet": True,
        "api_access": True,
    },
}

# The switches of the plan grid, shown on Super admin › Plan Limits and
# enforced by features/plan_limits.py (owner API guard + engines).
PLAN_SWITCHES = ("priority_support", "advanced_analytics", "crm_advanced", "segmentation", "campaigns", "automations",
                 "referral", "wallet", "api_access", "csv_export", "geo_proximity", "multi_branch")
AI_LEVELS = ("none", "basic", "advanced")
# Per-feature AI allowances by level (None = no limit). Placeholder numbers
# decided 2026-09-30 until the user sets the exact ones after testing. On top
# of these, ai_queries_per_day caps every AI call of the day.
AI_LEVEL_LIMITS = {
    "none": {"copilot_questions_per_day": 0, "recommendations": 0, "ai_campaigns_per_month": 0},
    "basic": {"copilot_questions_per_day": 5, "recommendations": 3, "ai_campaigns_per_month": 5},
    "advanced": {"copilot_questions_per_day": None, "recommendations": None, "ai_campaigns_per_month": None},
}
# One line under each plan's name (Plan Limits cards).
PLAN_TAGLINES = {
    "silver": "L'essentiel pour commencer",
    "gold": "Plus de possibilités pour développer",
    "vip": "L'IA au service de votre fidélisation",
    "franchise": "Réseaux et franchises, sur devis",
}

# Commercial names + order, shared with the marketing site through
# GET /api/public/plans. fidclic.com/tarifs reads THIS, never its own copy.
PLAN_LABELS = {
    "silver": "Starter",
    "gold": "Pro",
    "vip": "Pro AI",
    "franchise": "Franchise",
}
# Self-serve plans, in order. Franchise is not in it: it is sold on quote.
PLAN_ORDER = ("silver", "gold", "vip")
QUOTE_PLANS = ("franchise",)

# Monthly prices, HT (user, 2026-10-03). HT everywhere in the app and on
# fidclic.com; the TTC (TVA 20 %) only at payment and on the invoice.
PLAN_PRICES = {
    "silver": 33,
    "gold": 65,
    "vip": 108,
    "franchise": 0,      # sur devis — the real price is tenant.franchise_terms.price
}

# A customer counts against max_customers while they have visited within this
# window. Dormant customers are kept, shown and campaignable — just not billed.
ACTIVE_WINDOW_DAYS = 365

# Annual billing: 20 % off (≈ 2 months free), same discount on every plan.
ANNUAL_DISCOUNT = 0.20

PLAN_TRIAL_DAYS = {
    "silver": 30,
    "gold": 30,
    "vip": 30,
    "franchise": 30,
}

# The plan every free trial runs on (user, 2026-10-04): the sign-up shows the
# three plans side by side, then every new business tries Pro AI — all of
# it — and picks the plan it pays for when the trial ends.
TRIAL_PLAN = "vip"

# A sign-up that stops before the plan step is a hidden draft (never listed in
# the super admin) and is deleted after this many days by the daily cron.
DRAFT_SIGNUP_TTL_DAYS = 7

# Number of days BEFORE trial_end that we surface the "your trial is ending
# — pick a plan" reminder (email via the daily cron + dashboard banner).
# 1 = the reminder lands on day 29 of a 30-day trial. Admin-overridable.
TRIAL_REMINDER_DAYS_BEFORE = 1

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    tenant_id: Optional[str] = None
    sid: Optional[str] = None          # the login session (features/security_page.py)
    view_by: Optional[str] = None      # « Accéder au compte »: the super admin in this account
    view_only: bool = False            # …read-only (a team member without « Modifier » on Commerces)

class UserBase(BaseModel):
    email: str
    role: str
    tenant_id: Optional[str] = None
    # Captured at self-serve signup (step 1). Optional so every pre-existing
    # user document (email + password only) still validates.
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    # "password" | "google" | "apple" — how the account was first created.
    # A password user can later link Google/Apple; see features/oauth.py.
    auth_provider: Optional[str] = "password"
    # CGU + Politique de confidentialité + DPA acceptance. Stamped once at
    # signup; the version string lets us re-prompt if the legal texts change.
    terms_accepted_at: Optional[datetime] = None
    terms_version: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserInDB(UserBase):
    # Optional: Google/Apple accounts have no password. Login with a password
    # against such an account is refused (see /api/auth/login).
    hashed_password: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TenantBase(BaseModel):
    slug: str
    name: str
    plan: str
    address: Optional[str] = ""
    phone: Optional[str] = ""
    website: Optional[str] = ""
    geo_radius_meters: Optional[int] = None
    geo_cooldown_days: Optional[int] = 1
    geo_enabled: bool = False
    branches: List[Dict[str, Any]] = []
    parent_tenant_id: Optional[str] = None
    sector: Optional[str] = None  # restaurant, pizzeria, spa, gym, etc. — drives reactivation templates
    activity: Optional[str] = None  # free-text precision ("Boulangerie artisanale bio")
    postal_code: Optional[str] = None
    city: Optional[str] = None
    # Self-serve onboarding progress. "company" = the owner created their
    # personal account (step 1) but has not filled the company details yet
    # (step 2); "plan" = company done, the plan step (3) is next. Until
    # "done" the tenant is a hidden draft (is_active=False) that the UI parks
    # on the right step. Defaults to "done" so every legacy tenant is
    # unaffected.
    onboarding_status: str = "done"
    campaign_sender_name: Optional[str] = None  # custom "from" name for push notifications/emails
    # --- Facturation module (French e-invoicing). All optional / default-off so
    #     existing loyalty-only tenants are completely unaffected. A tenant only
    #     sees the Facturation module when facturation_enabled is True (set when
    #     they buy it — standalone or as an add-on to CRM+Loyalty). ---
    facturation_enabled: bool = False
    facturation_plan: Optional[str] = None      # "standalone" | "addon" | None
    # Legal identity used for e-invoicing (captured at onboarding, editable in Settings)
    legal_name: Optional[str] = None
    siren: Optional[str] = None                 # 9 digits
    siret: Optional[str] = None                 # 14 digits (head establishment)
    vat_number: Optional[str] = None            # FR + 2-digit key + SIREN
    naf_code: Optional[str] = None              # 2-digit NAF/APE (drives DGFiP process code)
    enterprise_size: Optional[str] = None       # "micro" | "pme" | "eti" | "ge"
    # VAT regime drives the e-reporting calendar frequency (decade/monthly/bimonthly)
    vat_regime: Optional[str] = None            # "reel_normal_mensuel" | "rsi" | "franchise" | ...
    # DGFiP / PA activation state (set when compliance is activated via PdpConnector)
    dgfip_activated: bool = False
    dgfip_start_date: Optional[str] = None       # ISO date the obligation starts
    annuaire_status: Optional[str] = None        # None | "pending" | "registered"
    pdp_account_id: Optional[str] = None         # the PA-side account id for this tenant

class Tenant(TenantBase):
    id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True

class CustomerBase(BaseModel):
    name: str
    email: str
    phone: str
    postal_code: str
    birthday: str

class Customer(CustomerBase):
    model_config = ConfigDict(extra="allow")
    id: str
    tenant_id: str
    barcode_id: str
    points: int = 0
    visits: int = 0
    total_amount_paid: float = 0.0
    tier: str = "bronze"
    pass_issued: bool = False
    last_visit_date: Optional[datetime] = None
    acquisition_source: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    branch_id: Optional[str] = None      # primary branch the customer is tied to
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Visit(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    tenant_id: str
    customer_id: str
    points_awarded: int
    amount_paid: float = 0.0
    branch_id: Optional[str] = None      # where this scan happened
    visit_time: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Review(BaseModel):
    """Customer review left after a visit. Rating is out of 10.

    Sentiment + topics are computed server-side on submit using a French/
    English lexicon, so the score stays consistent and doesn't need an
    external API. Re-running the analyser on the same text is idempotent.
    """
    model_config = ConfigDict(extra="allow")
    id: str
    tenant_id: str
    customer_id: str
    branch_id: Optional[str] = None
    visit_id: Optional[str] = None        # the scan this review attaches to
    rating: int                            # 1..10
    text: str = ""
    sentiment: str = "neutral"             # "positive" | "neutral" | "negative"
    sentiment_score: float = 0.0           # -1.0 .. +1.0
    topics: List[str] = []                 # ["speed", "cleanliness", ...]
    topic_scores: Dict[str, float] = {}    # per-topic confidence 0..1
    language: Optional[str] = None         # "fr" | "en" | None if unknown
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TierDesign(BaseModel):
    primary_color: str = "#B85C38"
    secondary_color: str = "#1C1917"
    text_color: str = "#FFFFFF"
    accent_color: str = "#D4A574"
    font_family: str = "Inter"
    gradient_direction: str = "135deg"
    background_image_url: Optional[str] = None
    hexagon_color: str = "#D4A574"
    hexagon_filled_color: str = "#B85C38"


class CardElementStyle(BaseModel):
    """Per-element styling placed on a card.

    `id` identifies which field the element represents. Known ids:
    logo, business_name, customer_name, points, tier, birthday, barcode,
    progress_meter, offer_banner. Unknown ids are rendered as free text.
    """
    model_config = ConfigDict(extra="allow")
    visible: bool = True
    x_pct: float = 50.0  # 0..100, element anchor x as % of card width
    y_pct: float = 50.0  # 0..100, element anchor y as % of card height
    width_pct: Optional[float] = None  # optional box width constraint
    font_family: str = "Inter"
    font_size: int = 14  # px
    font_weight: str = "normal"  # normal | bold
    font_style: str = "normal"  # normal | italic
    text_decoration: str = "none"  # none | underline
    color: str = "#FFFFFF"
    align: str = "left"  # left | center | right
    text: Optional[str] = None  # optional override / free-text; supports {name}, {tier}, etc.


class CardPromotionElement(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str = ""
    x_pct: float = 50.0
    y_pct: float = 50.0
    font_family: str = "Inter"
    font_size: int = 14
    font_weight: str = "normal"
    font_style: str = "normal"
    text_decoration: str = "none"
    color: str = "#FFFFFF"
    align: str = "center"
    link: Optional[str] = None  # optional clickable link on this element


class CardPromotion(BaseModel):
    """Optional promotion block that replaces the logo area when enabled."""
    model_config = ConfigDict(extra="allow")
    enabled: bool = False
    title: str = ""
    subtitle: str = ""
    body: str = ""
    link: Optional[str] = None
    link_label: str = "En savoir plus"
    expires_at: Optional[datetime] = None
    background_color: str = "#B85C38"
    text_color: str = "#FFFFFF"
    image_url: Optional[str] = None
    elements: List[CardPromotionElement] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CardDetailsSection(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = ""
    body: str = ""


class CardDetails(BaseModel):
    """Expandable info section shown when customer taps the card."""
    model_config = ConfigDict(extra="allow")
    about: str = ""
    hours: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    instagram: str = ""
    facebook: str = ""
    custom_sections: List[CardDetailsSection] = Field(default_factory=list)


class CardTemplate(BaseModel):
    # Allow legacy fields (primary_color, secondary_color, text_content, font_family, etc.)
    # to flow through and persist, so the new designer and any older clients coexist.
    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    logo_url: Optional[str] = None
    active_offer_url: Optional[str] = None
    active_offer_title: Optional[str] = None
    active_offer_description: Optional[str] = None
    active_offer_active: bool = False
    design_mode: str = "hexagon_stamps"
    # New: richer stamp style catalogue.
    # hexagon | classic_dots | bar | circles | stars | squares | none
    stamp_style: str = "hexagon"
    show_meter: bool = True  # alias of show_progress_meter (new name, kept in sync)
    points_per_visit: int = 10
    # When set (>0), points_per_euro is the rate used in 'per_euro' mode.
    # Default 10 = "1 € spent → 10 points".
    points_per_euro: float = 10.0
    # How points are awarded on a scan. The OWNER picks this in Settings.
    #   'per_visit' → flat points_per_visit per scan (default — independent of amount)
    #   'per_euro'  → amount_paid × points_per_euro
    points_mode: str = "per_visit"
    visits_per_stamp: int = 1
    reward_threshold_stamps: int = 10
    reward_description: str = "Une récompense offerte"   # replaced by the sector's (services/sector_rewards)
    notify_before_reward: int = 1
    bronze_design: TierDesign = Field(default_factory=TierDesign)
    silver_design: TierDesign = Field(default_factory=lambda: TierDesign(primary_color="#A0A0A0", accent_color="#C0C0C0"))
    gold_design: TierDesign = Field(default_factory=lambda: TierDesign(primary_color="#D4A574", accent_color="#FFD700"))
    show_customer_name: bool = True
    show_customer_birthday: bool = True
    show_points: bool = True
    show_progress_meter: bool = True
    # --- New fields for the modern card designer ---
    elements: Dict[str, CardElementStyle] = Field(default_factory=dict)
    promotion: CardPromotion = Field(default_factory=CardPromotion)
    details: CardDetails = Field(default_factory=CardDetails)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CardTypedNotification(BaseModel):
    """Typed push notification that attaches to a customer's wallet card.

    Types: news | offer | flash_sale | voucher_expiry | event |
           order_status | safety | custom
    """
    model_config = ConfigDict(extra="allow")
    type: str = "news"
    title: str
    body: str
    link: Optional[str] = None
    expires_at: Optional[datetime] = None
    filters: Dict[str, Any] = Field(default_factory=dict)

class Campaign(BaseModel):
    id: str
    tenant_id: str
    name: str
    status: str = "draft"
    content: str
    filters: Dict[str, Any] = {}
    sent_at: Optional[datetime] = None
    delivered_count: int = 0
    targeted_count: int = 0
    opens: int = 0
    opens_unique: int = 0
    visits_from_campaign: int = 0
    recipient_ids: List[str] = []
    # Feature 11: offer interaction tracking
    offer_clicks: int = 0
    offer_clicks_unique: int = 0
    push_dismissals: int = 0  # number of recipients who dismissed the push without opening
    sender_name: Optional[str] = None  # snapshot of tenant.campaign_sender_name when sent
    # Distribution channel this campaign was published on — used for per-channel performance analysis.
    # Allowed values: 'push' (wallet push), 'email', 'other' — the channels FidClic delivers on
    # today. Social-channel publishing (Instagram/Facebook/TikTok) and SMS are not yet wired to a
    # publishing pipeline, so they are intentionally not part of the picker.
    source: Optional[str] = None
    # Optional hero image — appears at the top of the email and as a visual on
    # the campaign card. Stored as a URL or base64 data URL (uploaded from device).
    image_url: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AIQueryRequest(BaseModel):
    message: str

class PaymentTransaction(BaseModel):
    session_id: str
    tenant_id: str
    plan: str
    status: str = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ===========================================================================
# FACTURATION ÉLECTRONIQUE (French e-invoicing) — new module models.
# All are PA-agnostic (they never carry a vendor's raw fields); the
# PdpConnector maps to/from the actual PA. Mongo collections:
#   fact_invoices · fact_received_invoices · fact_ereports ·
#   fact_credit_notes · fact_coherence_checks
# `extra="allow"` everywhere so we can evolve without migrations.
# ===========================================================================

class FactLine(BaseModel):
    """One line of an invoice."""
    model_config = ConfigDict(extra="allow")
    description: str
    quantity: float = 1
    unit_price: float = 0.0            # HT (before VAT)
    vat_rate: float = 20.0             # percent
    vat_category: str = "S"            # S=standard, E=exempt, O=out-of-scope
    line_total_ht: float = 0.0         # quantity * unit_price (server recomputes)


class FactParty(BaseModel):
    """A seller or buyer on an invoice."""
    model_config = ConfigDict(extra="allow")
    name: str = ""
    siren: Optional[str] = None
    siret: Optional[str] = None
    vat_number: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "fr"
    email: Optional[str] = None
    is_company: bool = True            # False => B2C (routes to e-reporting, not e-invoicing)


class FactInvoice(BaseModel):
    """An issued invoice. `state` uses the PdpConnector normalized vocabulary
    (draft/sent/received/accepted/refused/paid/error)."""
    model_config = ConfigDict(extra="allow")
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    number: str                         # human invoice number (unique per tenant → idempotency key)
    buyer: FactParty
    lines: List[FactLine] = Field(default_factory=list)
    date: Optional[str] = None          # ISO issue date
    due_date: Optional[str] = None
    total_ht: float = 0.0
    total_vat: float = 0.0
    total_ttc: float = 0.0
    state: str = "draft"
    channel: str = "e-invoicing"        # "e-invoicing" (B2B) | "e-reporting" (B2C)
    pdp_invoice_id: Optional[str] = None  # id returned by the PA
    reject_code: Optional[str] = None     # AFNOR-ish code if refused/error
    reject_reason: Optional[str] = None   # plain-French message for the UI
    lifecycle: List[Dict[str, Any]] = Field(default_factory=list)  # [{state, at}]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FactReceivedInvoice(BaseModel):
    """A supplier invoice that arrived for this tenant (feeds the purchases side
    of the Fiscal Shield coherence check)."""
    model_config = ConfigDict(extra="allow")
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    supplier: FactParty
    number: Optional[str] = None
    total_ht: float = 0.0
    total_vat: float = 0.0
    total_ttc: float = 0.0
    state: str = "received"             # received | accepted | refused | paid
    pdp_invoice_id: Optional[str] = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FactEReport(BaseModel):
    """A B2C / cross-border e-reporting transmission (aggregated by VAT rate)."""
    model_config = ConfigDict(extra="allow")
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    totals_by_vat: Dict[str, float] = Field(default_factory=dict)  # {"20": 5000.0, "10": 2000.0}
    state: str = "pending"             # pending | queued | sent | registered | error
    pdp_report_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FactCreditNote(BaseModel):
    """A credit note (avoir) that corrects/cancels a prior invoice."""
    model_config = ConfigDict(extra="allow")
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    original_invoice_id: str            # the FactInvoice being corrected
    number: str
    amount_ht: float = 0.0              # negative or the amount being credited
    amount_vat: float = 0.0
    reason: Optional[str] = None
    state: str = "draft"
    pdp_invoice_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FactCoherenceCheck(BaseModel):
    """A stored result of the Fiscal Shield / Bouclier Fiscal coherence run.
    NOTE: this is an informational consistency indicator, NOT tax advice / not
    an ECF (Examen de Conformité Fiscale) — the UI must carry that disclaimer."""
    model_config = ConfigDict(extra="allow")
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    period: Optional[str] = None
    score: int = 100                    # 0..100 (paired with the colour band)
    band: str = "green"                # "green" | "amber" | "red"
    alerts: List[Dict[str, Any]] = Field(default_factory=list)  # [{level, message, fix_action}]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
