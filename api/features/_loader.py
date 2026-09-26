"""
Single wire-up for all feature modules.

Usage — add these two lines at the very bottom of `server.py`:

    from features._loader import register_all
    register_all(app, db)

Comment any module in MODULES below to disable it cleanly.
Nothing else in the codebase changes.
"""

import importlib
import logging

logger = logging.getLogger("fidelitour.features")

# Order doesn't matter functionally; grouped by domain for readability.
MODULES = [
    # Loyalty rules / config
    "features.welcome_bonus",
    "features.referrals",
    "features.happy_hour",
    "features.reviews",
    "features.registration_forms",
    # Owner workflow & visibility
    "features.history",                 # past campaigns + push notifications
    # Historique — every activity (scans, rewards, signups, messages, card
    # edits) merged into one filterable, paginated, exportable feed.
    "features.activity_history",
    # Géolocalisation clients — catchment rings + travel-time bands over the
    # merchant's own clients, with the commune breakdown behind both.
    "features.geolocation",
    # Analyses — eight tabs over one window, one tab answered per request.
    "features.analyses",
    # Tableau de bord — the home page's eleven panels, read off one month of
    # visits in a single pass, plus the merchant's monthly revenue goal.
    "features.dashboard_home",
    # Clients — the page's four figures, its eight quick segments and its
    # paginated table. Sits beside /api/owner/customers, which is untouched.
    "features.clients_page",
    # FidClic IA Copilote — recommendations, growth potential, forecast
    # (history + weather + local events), a 7-day plan with Autopilot, and a chat
    # grounded on the shop's own figures.
    "features.copilot",
    # Insights — « Faites grandir votre commerce » : opportunités, actions,
    # idées de campagnes et conseils, ranked on the shop's own data and sector.
    "features.insights_page",
    # Segmentation — the segments, what a campaign at each could bring in,
    # and the builder behind them.
    "features.segmentation",
    # Campagnes — the composer, its audience, and what the last sends did.
    # Delivers on two channels at once: web push and the wallet card's offer.
    "features.campaigns_page",
    "features.analytics_history",       # extended weekly/daily/monthly history
    "features.customer_status",         # configurable active/inactive definition
    "features.tier_definitions",        # custom tier thresholds + big-spender rule
    "features.auto_campaigns",          # auto birthday + inactive rescue messages
    # Automatisations · Push Wallet — scenarios that fire on their own and land
    # on the customer's Apple/Google Wallet pass. Run daily by /cron/daily-triggers.
    "features.push_wallet",
    "features.push_subscriptions",      # web push subscriptions + dispatch helper
    "features.business_hours",          # weekly schedule + French public holidays + annual closures
    # AI / predictive — fully implemented (math-based)
    "features.ai_send_time",
    "features.ai_churn",
    # AI / predictive — stubs with spec
    "features.ai_anomaly",
    # "features.ai_voice_campaign",   # ⚠ disabled — code preserved, route unmounted
    "features.ai_birthday",
    "features.ai_translate",
    "features.ai_brand_voice",
    "features.ai_conversational",
    # "features.ai_staffing",         # ⚠ disabled — code preserved, route unmounted
    # "features.ai_competitive",      # ⚠ disabled — code preserved, route unmounted
    "features.ai_newsletter",
    "features.tier_optimizer",
    # Billing — Stripe Checkout + Customer Portal + webhook handler.
    # Boots safely (no-ops) when STRIPE_SECRET_KEY isn't set.
    "features.billing",
    # Native wallet passes — Apple .pkpass + Google Wallet. No-ops (503) until
    # APPLE_PASS_* / GOOGLE_WALLET_* are set in Vercel.
    "features.wallet_passes",
    # Carte de fidélité — design, programme rules, tiers and the page's figures.
    "features.loyalty_card",
    # Besoin d'aide ? — FAQ knowledge base + the support assistant that answers
    # from it. Answers from the KB even with no LLM key configured.
    "features.support_assistant",
    # Facturation électronique (French e-invoicing) — second product module.
    # Gated: only tenants with facturation_enabled=True reach any route.
    # PA-agnostic via services.pdp_connector (Mock by default; B2Brouter via env).
    "features.facturation",
    # Cabinet multi-dossier — accountant (comptable) control tower over clients.
    "features.cabinet",
    # Audit log — append-only "who did what, when". Compliance + the data source
    # behind the cabinet's live activity view. Must load AFTER cabinet.
    "features.audit",
    # Cabinet OS — the firm as an organisation: memberships, roles, assignment.
    "features.cabinet_os",
    # Exception Centre — every failure becomes an owned, dated, closable case.
    # Loads after cabinet_os because it resolves scope through memberships.
    "features.exceptions_centre",
    # Grille de répartition (S9) — task-level assignment per dossier.
    "features.grille",
    # Agent capability #1 (S12) — document collection with adaptive relances.
    "features.agent_collect",
    # Agent capability #2 (S13) — recurring billing from standing instructions.
    "features.agent_billing",
    # Agent capability #3 — OCR ingestion of supplier invoices (Chapter 4).
    "features.agent_ocr",
    # Agent capability #4 — Saisie: proposes the purchase entry from OCR.
    "features.agent_saisie",
    # La Mémoire + Le Conseiller (Chapter 8) — dossier memory + advisory drafts.
    "features.conseiller",
    # Agent capability #6 — TVA/CA3 draft declaration.
    "features.agent_tva",
    # Agent capability #7 — Le Lettrage (rapprochement bancaire).
    "features.agent_lettrage",
    # Agent capability #8 — Le Gardien (points de vigilance / anomalies).
    "features.agent_gardien",
    # Agent capability #9 — Le Réviseur (revue avant validation).
    "features.agent_reviseur",
    # The agent's alarm clock — Vercel Cron hits this daily.
    "features.cron",
    # Password reset by email (magic link) — S3 finale.
    "features.auth_reset",
    # Self-serve onboarding step 2 (company details) + 28-day trial lifecycle
    # (day-27 reminder). Loads after auth_reset; needs nothing else.
    "features.onboarding",
    # Sign in with Google / Apple — ID-token verification, account linking.
    # Boots as "not configured" until GOOGLE_CLIENT_ID / APPLE_CLIENT_ID exist.
    "features.oauth",
    # Export FEC — the 18-column accounting file every French tool imports.
    "features.fec",
    # Imports — bulk clients (CSV), invoices (CSV/FEC), bank (CSV/OFX).
    "features.data_import",
    # Ticket numérique — B2C e-receipt to the customer (email + push rail).
    "features.receipts",
    # Coefficients sectoriels — the simulated DGFiP reconstitution (defaults +
    # self-learned medians from the cabinet's own dossiers).
    "features.coefficients",
    # NOTE on A/B testing: there's no dedicated module for auto-A/B testing.
    # It was a planned/described feature in the docs but never had its own
    # backend module mounted. So there's nothing to disable here.
]


def register_all(app, db) -> None:
    """Import each feature module, run its optional init(db), and mount its router.

    Failures are logged but never raised — a broken feature module must not
    take down the whole server.
    """
    # Shared services that need the database before any feature uses them.
    try:
        from services import communes
        communes.init(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("commune resolver unavailable: %s", exc)
    for dotted_path in MODULES:
        try:
            module = importlib.import_module(dotted_path)
            if hasattr(module, "init"):
                module.init(db)
            if hasattr(module, "router"):
                app.include_router(module.router)
                logger.info("feature loaded: %s", dotted_path)
            else:
                logger.warning("feature %s has no router; skipping", dotted_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("feature %s failed to load: %s", dotted_path, exc)
