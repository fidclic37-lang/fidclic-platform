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
import os
from datetime import datetime, timezone

logger = logging.getLogger("fidelitour.features")

# Order doesn't matter functionally; grouped by domain for readability.
MODULES = [
    # Loyalty rules / config
    "features.welcome_bonus",
    "features.auto_messages",
    "features.automations",               # Automatisations redesign (2026-10-11)
    "features.geo_automation",            # Géolocalisation: Wallet lock screen + card (2026-10-11)
    "features.etablissement",
    "features.send_rules",
    "features.settings_versions",
    "features.invoices",
    "features.privacy_page",
    "features.security_page",
    "features.scan_page",               # « Enregistrer une visite » — la carte scannée
    "features.account_email",           # Sécurité › changer l'adresse e-mail du compte
    "features.preferences",
    "features.platform_access",
    "features.platform_reset",
    "features.signup_agents",            # Lien d'inscription par employé (2026-10-16)
    "features.signup_verify",            # sign-up code by e-mail or SMS          # Super admin › remise à zéro (fresh start)
    "features.platform_security",
    "features.crm",
    "features.crm_pilotage",
    "features.crm_calls",
    "features.crm_email",
    "features.franchise",
    "features.admin_commerces",
    "features.admin_dashboard",
    "features.admin_insights",
    "features.admin_analytics",
    "features.analytics_usage",
    "features.analytics_deep",
    "features.support_center",
    # Clients › « Modifier la fiche » / « Ajuster points / tampons » (QA UX04)
    "features.customer_edit",
    "features.card_status",          # card active / deleted, and getting it back
    "features.google_wallet_callbacks",  # Google Wallet tells us of saves and deletions
    # Super admin › Suivi d'équipe — FidClic's own team tasks (week board,
    # history, repeats, comments, bell). Rights: the « equipe » module.
    "features.team_tasks",
    "features.admin_ai",
    "features.plan_limits",
    "features.merchant_api",
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
    # Produits qui font revenir — which products bring clients back (weekly, in ai_jobs).
    "features.product_return",
    # Tableau de bord — the home page's eleven panels, read off one month of
    # visits in a single pass, plus the merchant's monthly revenue goal.
    "features.dashboard_home",
    # Clients — the page's four figures, its eight quick segments and its
    # paginated table. Sits beside /api/owner/customers, which is untouched.
    "features.clients_page",
    # FidClic IA « Comprendre »: each client's habits, rhythm and next visit (2026-10-24)
    "features.client_brain",
    # long FidClic IA work (backtest, brain-v2's learning) in the tick's slices (2026-10-26)
    "features.ai_jobs",
    # what FidClic IA predicted, and what really happened (2026-10-25)
    "features.brain_journal",
    # the Précision page's tallies: always live, never the whole journal (2026-10-26)
    "features.journal_stats",
    # « roz ka hisaab »: each finished day's visits summed once (2026-10-28)
    "features.visit_days",
    # brain-v2: learns its window and its sector rhythms from the network (2026-10-25)
    "features.brain_v2",
    # FidClic IA « a repéré »: late regulars, no 2nd visit, slowing down (2026-10-25)
    "features.brain_detectors",
    "features.temoin",                 # groupe témoin: what FidClic really brings in
    "features.lab_export",             # FidClic Lab: one shop's history, anonymous (super admin)
    "features.reco_journal",           # the journal of ideas: shown, opened, sent, € (témoin)
    "features.reco_ranking",           # the ranking that learns from the journal (no router)
    # FidClic IA Copilote — recommendations, growth potential, forecast
    # (history + weather + local events), a 7-day plan with Autopilot, and a chat
    # grounded on the shop's own figures.
    "features.copilot_memory",
    "features.copilot_tools",          # the Copilote's read-only tools (no router)         # the Copilote's memory: every message kept, facts, summary
    "features.copilot",
    # Insights — « Faites grandir votre commerce » : opportunités, actions,
    # idées de campagnes et conseils, ranked on the shop's own data and sector.
    "features.insights_page",
    # Segmentation — the segments, what a campaign at each could bring in,
    # and the builder behind them.
    "features.segmentation",
    "features.catalogue_page",          # Catalogue produits (products, categories, what sells)
    # Campagnes — the composer, its audience, and what the last sends did.
    # Delivers on two channels at once: web push and the wallet card's offer.
    "features.campaigns_page",
    "features.defis",                  # Campagnes › Défi: progress, « Défi réussi », rewards to hand over
    "features.resend_guard",           # « déjà contactés » check before a send
    "features.campaign_learning",      # « Ce qui marche chez vous » — learns from sent campaigns
    "features.autopilot",              # Autopilot: daily + weekly campaigns, owner validates
    "features.campaign_report",        # Rapport mensuel des campagnes (Pro AI)
    "features.client_import",          # Clients › Importer + invitation emails
    "features.analytics_history",       # extended weekly/daily/monthly history
    "features.customer_status",         # configurable active/inactive definition
    "features.customer_rules",          # Paramètres › Règles clients (drives the Clients page statuses)
    "features.team_access",             # Paramètres › Équipe & accès (roles, establishments, accounts)
    "features.role_perms",              # rôles et permissions par page (Voir / Modifier, par établissement)
    "features.store_scope",             # which establishments a request is about (the logo dropdown)
    "features.join_link",               # Paramètres › Lien d'inscription & QR (+ signup-page visits)
    "features.store_links",             # each establishment's link + QR, the client's home store (multi-store)
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
    # Plan catalogue (public) + live usage counters — the marketing site
    # builds its pricing table from /api/public/plans.
    "features.plans_public",
    # Native wallet passes — Apple .pkpass + Google Wallet. No-ops (503) until
    # APPLE_PASS_* / GOOGLE_WALLET_* are set in Vercel.
    "features.wallet_passes",
    "features.pass_identity_admin",       # one Apple Pass Type ID per business
    "features.pass_designer",           # Apple Pass Designer templates as the card's design
    # Carte de fidélité — design, programme rules, tiers and the page's figures.
    "features.loyalty_card",
    "features.milestones",              # Objectifs et récompenses (paliers que le commerce se fixe)
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
    # Self-serve onboarding step 2 (company details) + plan step + 30-day trial lifecycle
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


INDEX_MARKER = "indexes_build"


def _build_id() -> str:
    """The deployment's commit — empty outside Vercel (local runs, tests)."""
    return os.environ.get("VERCEL_GIT_COMMIT_SHA") or os.environ.get("VERCEL_DEPLOYMENT_ID") or ""


def _index_spec(captured) -> str:
    """A fingerprint of every index the modules ask for: it changes only when an
    index is added or changed — not at every deployment, as the commit did."""
    import hashlib
    import json
    rows = []
    for coll, keys, a, k in captured:
        rows.append([getattr(coll, "name", str(coll)), repr(keys), repr(a), repr(sorted(k.items()))])
    rows.sort()
    return "idx-" + hashlib.sha1(json.dumps(rows).encode()).hexdigest()[:16]


def _indexes_done(db, build: str) -> bool:
    if not build:
        return False
    try:
        doc = db.platform_settings.find_one({"key": INDEX_MARKER}, {"_id": 0, "value": 1})
        return bool(doc and doc.get("value") == build)
    except Exception:  # noqa: BLE001
        return False


def register_all(app, db) -> None:
    """Import each feature module, run its optional init(db), and mount its router.

    Failures are logged but never raised — a broken feature module must not
    take down the whole server.

    Speed (2026-10-01): the modules' init() ask MongoDB for ~120 indexes.
    On Vercel the indexes asked for by the modules are only created when
    their set changed (the marker in platform_settings holds its
    fingerprint), in the background, so a start never waits for them.
    """
    Collection = type(db.platform_settings)      # pymongo's, or mongomock's in tests
    # Speed (2026-10-17): a cold start took 17 s — 13.5 s of it the first one
    # of each deployment asking Atlas for ~150 indexes, one round trip each,
    # and there were ~20 deployments that day. The indexes the modules ask
    # for are now only written down while they start; their fingerprint is
    # compared with the one saved, and only a NEW set is created — in the
    # background on Vercel, so no visitor waits for it.
    on_vercel = bool(_build_id())
    captured = []
    original = Collection.create_index
    if on_vercel:
        Collection.create_index = lambda self, keys, *a, **k: captured.append((self, keys, a, k))   # noqa: E731
    failed = False
    try:
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
                failed = True
                logger.exception("feature %s failed to load: %s", dotted_path, exc)
    finally:
        Collection.create_index = original
    if not on_vercel or not captured:
        return                                   # local runs and tests: created as they were asked
    spec = _index_spec(captured)
    if failed or _indexes_done(db, spec):
        return

    def build_indexes():
        ok = True
        for coll, keys, a, k in captured:
            try:
                original(coll, keys, *a, **k)
            except Exception as exc:  # noqa: BLE001 — one index never stops the others
                ok = False
                logger.warning("index on %s not created: %s", getattr(coll, "name", "?"), exc)
        if ok:
            try:
                db.platform_settings.update_one(
                    {"key": INDEX_MARKER},
                    {"$set": {"key": INDEX_MARKER, "value": spec, "at": datetime.now(timezone.utc)}}, upsert=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("index marker not saved: %s", exc)

    import threading
    threading.Thread(target=build_indexes, name="fidclic-indexes", daemon=True).start()
