# FIDÉLITOUR / FIDCLIC — COMPLETE PROJECT HANDOFF
*Last updated: 2026-07-21 · Written for continuing development in a new Claude session*
*Read this ENTIRE file before making any change. It contains every decision, convention, and pending item.*

---

## 0. HOW TO USE THIS FILE (instructions for Claude in the new session)

1. This is the single source of truth for project state. Trust it over assumptions.
2. The workspace folder is `website_antiG/`. The live codebase is in `website_antiG/fidelitour-deploy/`.
3. Copy of this file also lives at `fidelitour-deploy/CLAUDE.md` — keep both in sync when updating.
4. Work on a feature branch → push → Vercel preview URL → user validates → merge to `main` (production). Never push straight to `main` for product changes.
5. User (yrrx / Akshansh) communicates in Hinglish — respond in Hinglish for discussions, English for code/commits.
6. User prefers: concise, direct, no unnecessary explanation. Detailed only when he asks "explain".
7. NEVER take autonomous product decisions — propose, let him decide. He says "don't take autonomous decisions."
8. He tests on the live Vercel deploy after every push. Cache issues are common — always remind hard-refresh (Cmd+Shift+R) if a change "doesn't show."

---

## 1. PROJECT IDENTITY

| Item | Value |
|---|---|
| Product name | **FidClic** — rebrand approved and applied 2026-09-18 (branch feat/rebrand-fidclic). Every user-visible string says FidClic. Internal identifiers deliberately kept: DB `fidelitour_db`, localStorage keys `fidelitour_access_token` / `fidelitour:last_card`, SW cache `fidelitour-meta`, logger names, seed emails `@fidelitour.com`. Do not rename those. |
| What it is | Loyalty-platform SaaS for French cafés/restaurants. Digital wallet card (PWA), push campaigns, analytics, AI copilot. |
| Local repo path | `website_antiG/fidelitour-deploy/` |
| GitHub | `https://github.com/fidclic37-lang/fidclic-platform` (official FidClic account; branch: main). The old personal repo `AKSHANSH-SHUKLA/fidelitour-loyalty-platform` is retired. |
| Git remote auth | **NEVER embed a token in the remote URL** (that leaked a PAT once). Remote is plain HTTPS; auth comes from `gh auth login` / GitHub Desktop keychain as `fidclic37-lang`. Commits are authored as `fidclic37-lang <fidclic37@gmail.com>` (global git identity — no per-repo override). |
| Deploy | Official Vercel team `fidclic`, project `fidclic-platform`, Git-connected to the official repo. Production = `main` → **https://app.fidclic.com** (CNAME at OVH). Preview URL per branch. The old personal project `fidelitour-deploy` is retired. |
| Vercel project | projectId `prj_v4iikwhAgcH4HABksyrQ9e5aYZn7`, orgId `team_ls8ri2DnKqRPK3LymOvyem0O` (in `.vercel/project.json`). Note: Vercel MCP token may lack scope for this team (403 seen). |
| User email | akshanshshukla963@gmail.com (platform admin) |
| Support inbox | shuklaakshansh38@gmail.com (receives support tickets; also seeded as test customer "Akshansh", barcode FT-AKSH0001, Tours 37000) |

## 2. TECH STACK

**Frontend:** Vite + React (JSX, no TS) + Tailwind (utility classes) + custom CSS in `src/index.css` (~1700 lines) + Recharts (charts) + lucide-react (icons) + qrcode.react (QR) + react-i18next (FR/EN/AR) + react-router-dom.

**Backend:** FastAPI single-file monolith `api/server.py` (~9000+ lines) + feature modules in `api/features/` + services in `api/services/` + MongoDB (pymongo). Deployed as Vercel Python function via `api/index.py`, rewrites in `vercel.json`.

**Push:** Web Push (VAPID) via service worker `public/sw.js`. NOT native Apple/Google Wallet — it's a PWA.

**AI:** Vision/LLM chain = NVIDIA NIM (primary, `integrate.api.nvidia.com/v1`, OpenAI-compatible) → Groq (model `meta-llama/llama-4-scout-17b-16e-instruct` — older llama-3.2 vision models are DEAD) → OpenRouter. Helpers return `(output, error)` tuples.

**SMS:** Twilio via `api/services/sms.py` — `send_sms(to, body)`, needs `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`.

**Email to customers:** DISABLED — `send_email_to_customer()` in server.py is a no-op shim returning False (client asked to remove email channel; push+SMS only).

**Support email:** Multi-channel chain in server.py: SMTP (needs `SUPPORT_SMTP_USER`+`SUPPORT_SMTP_PASS`, host default smtp.gmail.com:587) → Resend (`RESEND_API_KEY`) → Formsubmit.co fallback. Recipient: `SUPPORT_RECIPIENT_EMAIL` env or default shuklaakshansh38@gmail.com. Tickets ALWAYS stored in `support_tickets` collection regardless. **As of handoff, SMTP env vars NOT yet set in Vercel → user was given instructions (Gmail App Password) but hasn't confirmed.**

## 3. ENV VARS (Vercel)

Set: `MONGODB_URI`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (mailto:akshanshshukla963@gmail.com), `NVIDIA_API_KEY`, `GROQ_API_KEY`.
Probably set: `JWT_SECRET`, `OPENROUTER_API_KEY`.
NOT set (pending): `SUPPORT_SMTP_USER`, `SUPPORT_SMTP_PASS`, `TWILIO_*`, `RESEND_API_KEY`, `PUBLIC_APP_URL`, Stripe keys (billing not integrated).

## 4. SEED ACCOUNTS (local dev / e2e only — `api/server.py` mock_seed_data)

The seed runs locally only (never on Vercel). Its passwords live in the seed
code and never work on Vercel (`api/services/published_passwords.py`,
incident 2026-10-27: this table once listed them while the repo was public).

Roles: super_admin (/admin/*), business_owner (/dashboard/*), manager (subset), staff (/dashboard/scan only).
Seed gated off on Vercel since 2026-10-01; published passwords blocked there since 2026-10-27.

## 5. KEY FILE MAP

```
fidelitour-deploy/
├─ api/
│  ├─ server.py            # THE monolith. Auth, scan, campaigns, analytics, support, push-recovery, admin
│  ├─ models.py            # PLAN_FEATURES: silver €29/1000cust, gold €79/3000, vip €109/6000; PLAN_TRIAL_DAYS=28, reminder 1 day before (day 27)
│  ├─ services/sms.py      # Twilio send_sms
│  ├─ services/web_push.py # VAPID send_push, is_configured
│  └─ features/
│     ├─ push_subscriptions.py  # subscribe/unsubscribe, test-push, notification-status (missed offers)
│     ├─ auto_campaigns.py      # birthday+inactive automations, TEMPLATE-based (no LLM)
│     ├─ ai_birthday.py         # STUB — LLM birthday messages, not wired
│     └─ ai_brand_voice.py, business_hours.py, tier_definitions.py, registration_forms.py
├─ src/
│  ├─ index.css            # design tokens + av2-light-skin + dashboard reorder rules (~1700 lines)
│  ├─ lib/api.js           # axios client, baseURL '/api' — NEVER prefix paths with /api/ again (double-prefix bug happened)
│  ├─ lib/translator.js    # custom DOM translator (translate.googleapis.com gtx) for full-page i18n
│  ├─ lib/webpush.js       # ensureSubscribed, unsubscribe, isSupported
│  ├─ pages/
│  │  ├─ OwnerDashboard.jsx     # dashboard: KPIs, master time filter, charts, side rail (sources/tier/notif panels)
│  │  ├─ AnalyticsPageV2.jsx    # analytics: KPI strip→visits+channels→RFM+revenue+products→hours+weekday+NVR→automations, + LegacyAnalyticsPage below
│  │  ├─ AnalyticsPage.jsx      # legacy deep-dive (reviews & sentiment w/ demo fallback DEMO_REVIEW_ANALYTICS)
│  │  ├─ CampaignsPage.jsx      # composer + ReEnableNotificationsButton (SMS re-enable modal)
│  │  ├─ CustomersPage.jsx      # filters incl. 🔔 subscription filter; CSV export (joinedAt = created_at||join_date||member_since)
│  │  ├─ ScanPage.jsx           # staff scan + NotificationEnablePrompt (QR w/ ?notify=1)
│  │  ├─ MyWalletCardPage.jsx   # wallet card: per-card manifest, merged Offers feed, missed-offers banner, ?notify=1 auto-prompt, test-push button
│  │  ├─ CustomerMapPage.jsx    # quadrants w/ 0.001° tolerance + center bucket
│  │  ├─ RegisterPage.jsx       # IconField flex pattern (44px icon col — do NOT revert to pl-* padding hacks)
│  │  ├─ AdminPlansPage.jsx     # admin plan editor silver/gold/vip
│  │  └─ DashboardLayout.jsx    # shell: sidebar, Support item + SupportModal mount, isAnalyticsDark=false (dark theme dead)
│  └─ components/
│     ├─ SupportModal.jsx       # subject+message → /api/support/contact
│     ├─ BillingBanner.jsx      # trial countdown + plan picker (visual only — no Stripe)
│     ├─ PremiumLoyaltyCard.jsx # THE card component (shared designer+customer)
│     └─ analytics/*            # KpiCard, ChartCard, ChannelDonut, RfmHeatmap, HoursHeatmap, WeekdayBars, RightAiPanel, etc.
├─ public/sw.js             # push service worker
├─ index.html               # inline per-card manifest injection + PWA launch failsafe
└─ vercel.json              # rewrites + CACHE HEADERS (index.html max-age=0 must-revalidate; /assets/* immutable 1y)
```

## 6. DESIGN SYSTEM — "Saint-Germain" French elegance palette

Applied across dashboard+analytics (commit 07bcf7f). USE THESE, not the old electric purple:

| Token | Value | Use |
|---|---|---|
| Aubergine (primary) | hsl(285 45-50% 42-48%) → hsl(295 50-55% 32-36%) → hsl(310 50% 30%) | primary buttons (3-stop gradient), links, active states |
| Bleu de France | hsl(215 65% 48%) / hsl(208 55% 40%) | charts (visits bars) |
| Sauge | hsl(105 30% 38-42%) / hsl(95 32% 50%) | success, positive, green data |
| Bordeaux | hsl(355 60% 48%) / hsl(355 65% 60%) | negative, alerts |
| Or/brass | hsl(42 78% 52%) / hsl(32 80% 48%) | accents, insight strips, gold tier |
| Coral | hsl(8 75% 62%) | Instagram channel etc. |
| Cream bg | #FBF7EF with radial washes: gold top-right rgba(201,162,39,.06-.07), aubergine bottom-left rgba(107,46,90,.05) |
| Card surface | #FFFFFF, border #ECE3D2, shadow `0 1px 2px rgba(45,35,24,.04), 0 8px 24px -16px rgba(45,35,24,.12)` |
| Text | ink hsl(228 28% 14%), secondary hsl(228 14% 35%), muted hsl(228 11% 45%) |
| KPI delta pos | bg hsl(150 55% 40%/.14), color hsl(150 70% 26%), weight 700 |
| Fonts (guides) | Playfair Display (headings) + Inter (body) + JetBrains Mono (numbers) |

**Theme rules:** Dark theme is REMOVED (functionally dead). `.av2-light-skin` is the unified skin on BOTH OwnerDashboard and AnalyticsPageV2 (same-element selector `.av2-light-skin.fdt-dash` — descendant selector was a dead-rule bug, fixed). Leftover `[data-route-dark]` CSS rules are harmless dead code. `isAnalyticsDark = false` hard-coded in DashboardLayout.

## 7. CRITICAL CONVENTIONS (violating these caused real bugs)

1. **api.js baseURL is '/api'** → frontend calls use `/owner/...` NOT `/api/owner/...` (double-prefix = 404; happened in commit b9fb7eb fix).
2. **Demo-data fallback pattern** (used EVERYWHERE): real backend data ALWAYS wins; demo paints only when empty. For donuts: threshold is **< 2 segments** (1-segment donut looks broken). Existing demo sets: dashboard sources (Sur place 56/Google Maps 22/Instagram 16/Site Web 9/Autres 5), tiers (Bronze 87/Silver 42/Gold 18/VIP 9), heatmap (morning rush/lunch/dinner/weekend brunch, Mon quieter, Fri evening lift), AnalyticsV2 DEMO object (2450 visits/1280 customers/18.40 basket/45920 revenue/68% retention), DEMO_REVIEW_ANALYTICS in AnalyticsPage (184 reviews, 8.4/10, +62 sentiment, topic breakdown, 8 French review feed items).
3. **Reward cycle math:** visits NEVER decrement. `stamps_in_cycle = visits - visits_at_last_redemption` (server computes, ships `stamps_in_cycle`, `reward_threshold`, `reward_unlocked` in scan response). Tier from lifetime visits: bronze<10, silver≥10, gold≥20, vip≥40 (or ≥10 with avg ticket ≥60). Frontend NEVER computes stamps from raw visits.
4. **Icon+input fields:** use the RegisterPage `IconField` flex pattern (44px icon column + divider + borderless inner input). Padding-left hacks failed 7 times.
5. **Cache:** vercel.json now has index.html `max-age=0, must-revalidate`, assets immutable. If user reports "old version showing" → hard refresh / incognito test FIRST before debugging code.
6. **PWA/iOS:** per-card manifest at `/api/manifest/{barcode_id}` injected by inline script in index.html; iOS localStorage is isolated between Safari and standalone PWA — don't rely on localStorage crossing that boundary.
7. **Commit style:** detailed multi-paragraph messages explaining what+why. Co-author line: `Co-Authored-By: Claude <noreply@anthropic.com>`. Always push after commit.
8. **Validation before push:** `python3 -c "import ast; ast.parse(open('api/server.py').read())"` and `npx --no-install esbuild --bundle=false --loader:.jsx=jsx <file> --outfile=/tmp/x.js`. Local `npx vite build` works too (~3s).
9. **i18n:** react-i18next FR/EN/AR + custom translator.js for full-page. RTL was killed intentionally. Pluralization uses _one/_other suffixes.

## 8. EVERYTHING BUILT (feature inventory)

**Self-serve onboarding + social login (Sept 2026):** `/register` = step 1 (prénom, nom, email, téléphone, mot de passe, CGU+Confidentialité+DPA checkbox; auto-login) → `/onboarding/entreprise` = step 2 (raison sociale, nom commercial, secteur, activité, SIRET, adresse) → trial starts → `/modules`. Route guards (`needsOnboarding` in App.jsx) park any owner with `tenant.onboarding_status="company"` on step 2. Google/Apple: `src/components/SocialAuthButtons.jsx` + `api/features/oauth.py` (ID-token verification via JWKS, email = identity, existing accounts linked; env `GOOGLE_CLIENT_ID`, `APPLE_CLIENT_ID`, `APPLE_REDIRECT_URI` — a missing ID hides that button). OAuth users accept the CGU on step 2. Legal links → `src/lib/legal.js` (fidclic.com/cgu, /confidentialite, /dpa — pages must exist on the landing site). Tests: `api/tests/test_onboarding_oauth.py` (boots real server.py on mongomock). Local e2e runner: `scripts/dev_local.py` (dist + api on :8765, no Mongo).

**Core loyalty:** tenant/customer/visit model, QR wallet card (PWA), staff scan page (geo-fenced, catalog item picker, amount, reward unlock celebration, tier-up banner), tiers bronze/silver/gold/vip, points (per_visit or per_euro modes), reward redemption (no visit decrement + self-healing migration for old broken customers).

**Plans/billing:** silver €29 / gold €79 / vip €109, 28-day trial without card (`subscription_status='trialing'`, trial_started_at/ends_at — starts when onboarding step 2 completes), day-27 email reminder via cron (features/onboarding.py), BillingBanner with countdown + picker, Stripe Checkout/Portal/webhook coded in features/billing.py (keys to be added in Vercel at the end), admin plan editor (/admin/plans, get_plan_features() merges PLAN_FEATURES + db.plan_settings overrides), hard cap on /api/join/{slug}.

**Campaigns:** composer (name, message, image, audience builder, preview count, scheduled), typed notifications endpoint `/api/owner/notifications/typed` (supports filters: tier, customer_ids[], birthday_month), open tracking (pixel `/api/campaigns/{id}/pixel/{customerId}.png`), click tracking (`/track-click`), campaign attribution on scans (15-day window), AI campaign analyzer button (per campaign), quick-send panel.

**Automations (template-based, editable):** birthday (title/message/bonus_points), inactive relance (days trigger), welcome. `ai_birthday.py` is a stub for future LLM personalization.

**Push:** VAPID web push, sw.js (notification display, click→focus/navigate, pushsubscriptionchange flag), subscribe/unsubscribe endpoints, owner test-push, customer self test-push button on card, per-card manifest.

**Push-recovery suite (LATEST major work, commits ae94611+894280e+b9fb7eb):**
- Strategy 3: scan response includes `notification_status`; ScanPage shows NotificationEnablePrompt (yellow card + QR encoding cardURL?notify=1) for not_subscribed customers.
- Strategy 1: `GET /api/card/{bc}/notification-status` → {subscribed, missed_count(30d), since_days}; MyWalletCardPage shows dismissable missed-offers banner with count + enable CTA; `?notify=1` URL param auto-triggers permission prompt 800ms post-render.
- Strategy 2: `POST /api/owner/notifications/re-enablement` (SMS blast to non-subscribed w/ deep link, returns targeted/sent/skipped/cost); `GET /api/owner/notifications/subscription-stats` → {total, subscribed, not_subscribed, subscribed_pct}; CampaignsPage "Re-enable notifications" button + modal (stats, cost estimate €0.06/SMS, result screen).
- KPI: "Notifications activées" panel in dashboard right rail (progress ring, tone colors ≥80 green/60-80 amber/<60 red, "relancer par SMS →" deep link `?action=re-enable` — note: the deep-link param handler on CampaignsPage may not be wired to auto-open the modal; verify).
- Filter: CustomersPage "🔔 Notifications" dropdown (All/Subscribed/NotSubscribed) using `GET /api/owner/notifications/subscription-map` → {map:{customer_id:true}}.

**Analytics V2 page:** order = KPI strip (5 sparkline tiles) → visits chart 1.7fr + channel donut 1fr → RFM 1fr + revenue 1.4fr + top products 1fr → hours heatmap 1.4fr + weekday bars 1fr + new-vs-returning 1fr → automations strip; right rail RightAiPanel (loyalty score ring, 3 rule-based insights, quick actions, assistant input); LegacyAnalyticsPage rendered below a divider (lifetime KPIs, Activité tiles, Recovered, Reviews & sentiment, Rankings).

**Dashboard (OwnerDashboard):** welcome header + smart search (route synonyms FR/EN + barcode detection), 8 KPI tiles w/ deltas, master time filter (number input 1-999 + unit jours/semaines/mois/années + quick chips 7j/30j/90j/12mois/1an + "≈ N jours" readout; drives visitsTwin+uniquesTwin+acqWeekly via useTileMetric controlledDays), 2 big charts 50/50, customer-visit heatmap (7×13, demo-populated), CSS-order reorder (charts first, AI banner + action tiles last), right rail: Alertes, Résumé rapide, Filtre temps, Top sources donut panel, Répartition par palier panel (progress bars per tier), Notifications activées panel.

**Customers:** table w/ filters (search, tier, source, subscription, visits range, spend, postal), quick segments, saved segments, CSV export, customer drawer w/ history, campaign composer per segment/KPI.

**Customer Map:** geo dots, quadrant breakdown (0.001° ≈111m tolerance, center bucket, amber explainer when all-center).

**Card Designer:** brand fields (colors, strip, offer box) — `_serialize_card_payload` merges tpl.brand_fields into top level (bug fixed — designer and customer card are now the same PremiumLoyaltyCard component).

**Reviews & sentiment:** customer rates /10 from card, rule-based sentiment+topics (speed/cleanliness/staff/price/wait_time), analytics section (4 KPI cards, rating histogram, topic breakdown with per-topic sentiment bars, recent feed), demo fallback when 0 reviews.

**Support:** sidebar Support item (all roles) → SupportModal (subject+message+read-only email) → `/api/support/contact` (persist→SMTP→Resend→Formsubmit) → admin list `/api/admin/support/tickets`.

**i18n:** FR/EN/AR locales, custom DOM translator (batched, cached 2-tier, MutationObserver), language switcher.

**Misc:** OCR menu upload (vision LLM → catalog items), catalog + scan item picker, error boundary on card page, geo consent UX, PWA install prompt + iOS install help, proximity push on card open (geo radius), monthly report cron, daily triggers cron (vercel.json crons: `0 8 * * *` daily-triggers, `0 9 1 * *` monthly-report).

**Docs created (in website_antiG/, NOT in repo):** `fidelitour-platform-guide.html` (23-chapter full platform guide, SVG diagrams, Saint-Germain styling), `fidelitour-offers-guide.html` (offers/push walkthrough w/ funnel + phone mockups).

## 9. RECENT COMMIT LOG (newest first, for context)

```
b9fb7eb fix(campaigns): /api/api/ double-prefix in re-enable modal
894280e push-recovery: complete the loop with KPI tile + customer filter
ae94611 push-recovery: ship Strategies 1, 2, 3 (in-card banner + SMS + staff QR)
9864347 dashboard: populate "When Do Your Customers Come In?" heatmap with demo
c7573b4 dashboard: darker KPI deltas + smarter empty-state for side donuts
51dd3c1 dashboard: single master time filter above charts
3346d62 dashboard: move Sources + Tier panels to right rail, expand main charts
310126c deploy: forbid caching index.html (stale theme bug fix)
07bcf7f support: SMTP delivery + French elegance palette
645ae78 dashboard: support form, reviews demo, charts-first reorder
060845d theme: flip Analytics V2 + Dashboard to unified light skin
8ddddd9 analytics(v2): demo-aware fallback so empty tenants render like mockup
8c79dba analytics(v2): reorder layout to match mockup
```

## 10. OPEN ISSUE AT HANDOFF MOMENT

User reported "platform load nahi ho raha" (platform not loading). Diagnosis done: local `vite build` SUCCEEDS, all JSX compiles clean (esbuild), server.py parses. Fixed one real bug (the /api/api/ double-prefix, commit b9fb7eb — but that only broke the re-enable modal, not page load). Sandbox cannot reach the Vercel URL (proxy 403) so live check was impossible. **NEXT SESSION: ask user for (a) exact symptom — white page / infinite loader / Vercel 404 / browser error, (b) which page, (c) F12 console errors, (d) incognito test result.** Most likely: stale cache (pre-310126c HTML) or a Vercel build env issue — check Vercel dashboard build logs.

## 11. PENDING / DECIDED-BUT-NOT-BUILT WORK

### 11a. Protected token system for campaign composer (DECIDED — ready to build)
User confirmed ALL decisions:
- **Approach C (hybrid):** contenteditable div; tokens = atomic `<span contenteditable="false">` chips; backspace deletes whole token; typing inside blocked; serialize back to `{first_name}` strings for backend.
- Tokens in **subject line + body** both.
- **Custom owner-defined tokens** — structure code to allow (V2 delivery ok).
- **Live preview** with a real customer's data (pick a preview customer from tenant).
- **Emoji chips** (👤 First Name etc.).
- **100% mobile compatible** (44px hit areas, tap-to-delete).
- Backend `render_template()` in server.py already substitutes: {name} {first_name} {tier} {points} {points_remaining} {points_to_next_reward} {visits} {amount_paid} {business_name} {sector}.
- Wire into: CampaignsPage composer + Settings auto-campaign templates (birthday/inactive/welcome).
- Paste with plain {tokens} auto-converts to chips; copy-out exports readable text; undo/redo must work.
- Estimated 3 days: Day1 TokenEditor component, Day2 CampaignsPage wiring + toolbar + live preview, Day3 Settings templates.

### 11b. Multi-store / franchise architecture (DECIDED — plan finalized, NOT started)
All decisions locked:
- **Owner = full god-mode** (sees everything incl. per-store operations). Branch Manager = own branch only. Staff = scan only for own branch.
- Wallet card = **unified franchise brand** + "Dernière visite : X" line. Card works at ALL outlets.
- **Rewards = Model A franchise-wide** (Starbucks-style): stamps accumulate across stores, redeem anywhere, reset globally. Optional future tenant setting `reward_scope: franchise|branch` (~2h) only if requested.
- **home_branch_id REMOVED from design** — derive "primary branch" from visits at query time.
- Branch closure = **soft delete only** (`status: closed`), NEVER delete data.
- Manager transfer between branches = **franchise owner does it** from Settings.
- Manager temp cross-branch access = **V2** with expiry dates.
- Branch-specific catalog/hours = **branch-level overrides on franchise master** (fallback to master).
- Branch additions = **hybrid**: self-service within plan tier; sales conversation to cross tiers (or pure self-service V1 + admin notification — user hasn't final-picked, lean hybrid).
- Security code for branch login = **PIN (Option SC-1)** per-branch 4-6 digit, monthly rotation; TOTP later.
- New role: `branch_manager`. Every data endpoint needs automatic branch filter by role.
- Plan tiers idea: Franchise Starter 2-5 (€199), Growth 6-20 (€499), Enterprise 21+ (custom).
- Phases (4-5 weeks): 1) data model+backend filters, 2) owner franchise dashboard (aggregate + leaderboard + branch alerts), 3) manager dashboard (scoped reuse), 4) PIN login flow, 5) settings/billing/invite, 6) wallet card adaptation, 7) security audit.
- Edge cases documented: multi-branch visits (both count, no dedup cross-branch; same-branch 5-min dedup), same-day two-store visits legit, per-branch analytics = "visited here" not "registered here", merge-branches rare case (status: merged_into).

### 11c. Product gaps roadmap (from client's FidClic docs — explained to user, sprints proposed, NOT started)
Sprint order proposed: **Sprint 1 LEGAL/GDPR (1wk): consent proof, customer data export, customer self-delete (`/api/card/{bc}/forget-me`), EU hosting verify, audit logs. Sprint 2 ONBOARDING (10d): setup wizard (5-screen), industry templates, preconfigured first campaign, CSV customer import. Sprint 3 AI COPILOT REAL LLM (3wk): business summary, campaign generation, natural-language segmentation (infra already wired — NVIDIA/Groq; current "AI" insights are rule-based templates). Sprint 4 SMART MARKETING (2wk): geolocation walk-by push, coupon expiry reminders, best-send-time, per-customer churn score. Sprint 5 GROWTH (2wk): per-business landing pages, tablet/kiosk signup, "Powered by" virality, action buttons on every KPI, saved dynamic segments, custom tags, cohort analysis.**
Also open from way back: "How to read it" helper cards under every analytics chart (task #3, never done); native Apple Wallet .pkpass / Google Wallet (M3-6, needs Apple Dev license €99/yr); Stripe billing integration (plan picker currently visual-only); phone-only registration.

### 11d. Client business context (for product decisions)
- Client = established businessman, 4 profitable French businesses, Africa+Middle East connections. Registering a company for this platform. Offered user 15% equity, no salary (other founders also unsalaried; 3rd founder has 60%, client 40%, adjusting for user's 15%).
- Client paid €1,500 for development + 1 month website management. User plans: "revisions after payment cost extra" — advised to scope as "critical bug fixes only, 30 days, all else billed €400-500/day."
- Client's docs (in `mnt/uploads/`, 4 files): **FidClic** branding, pricing **Starter €34 / Pro €79 / Pro AI €139**, POS+API deferred to month 10+, Tours 30-day launch plan (targets: 245 prospects, 42 demos, 17 clients, €1.8k MRR), national 12-month plan, social media 30-day plan, product features "Top 1 France" doc (~55% already built; AI Copilot is biggest gap at ~20%).
- **If rebrand FidéliTour→FidClic and pricing €29/79/109→€34/79/139 is confirmed by user, that's a codebase-wide change (models.py PLAN_FEATURES, AdminPlansPage, BillingBanner, i18n strings, branding).** NOT yet approved — ask first.
- User is on French student visa (964h/yr work cap, can't be Directeur/President), Tours-based. Advised: auto-entrepreneur status + deliverables-based (not hours-based) contract + equity with 25-40% pre-vested for prior work + geographic expansion equity mirroring clause. (Personal context — affects timeline/availability, not code.)

## 12. DATA MODEL CHEAT SHEET (Mongo collections)

`users` (email unique, role, tenant_id, hashed_password) · `tenants` (id, slug, name, plan, subscription_status, trial_*, campaign_sender_name, geo lat/lng/radius) · `customers` (id, tenant_id, barcode_id FT-XXXX, name, email?, phone, postal_code, birthday MM-DD, tier, visits, points, total_amount_paid, visits_at_last_redemption, acquisition_source, branch_id?, created_at, last_visit_date) · `visits` (id, tenant_id, customer_id, branch_id?, amount_paid, points_awarded, items[], visit_time) · `campaigns` (recipient_ids, sent_at, opens/clicks, visits_from_campaign, attributed_visit_customer_ids) · `notifications` (per-customer log, types: campaign/offer/news/reward_unlocked/near_reward...) · `push_subscriptions` (endpoint unique, customer_id, tenant_id, subscription JSON) · `card_templates` (tenant_id, brand_fields, points_mode, reward_threshold_stamps, visits_per_stamp) · `support_tickets` · `plan_settings` (admin overrides) · `rewards_redeemed` · `reviews` (rating /10, text, sentiment, topics).

## 13. HOW TO START THE NEW SESSION (message template for user)

Paste this as your first message in the new chat (after selecting the `website_antiG` folder):

> "Read website_antiG/FIDELITOUR_HANDOFF.md completely — it's the full project handoff. Confirm you've absorbed: (1) current state & conventions, (2) the open 'platform not loading' issue, (3) pending work list. Then [YOUR TASK HERE]."

That's it. The handoff file gives Claude everything.
