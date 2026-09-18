# `features/` — additive-only feature package

This folder adds new functionality to FidClic **without modifying any existing
file, endpoint, model, or page**. Every feature is a standalone module that
registers its own routes and (optionally) initialises its own MongoDB collection.

## Architectural rules

1. **No edits to `server.py`, `models.py`, or `auth.py`** beyond adding ONE line at the very bottom of `server.py` to wire up the loader.
2. Each feature lives in its own `*.py` file inside this folder.
3. Each feature exposes a module-level `router: APIRouter` and an optional `init(db)` function.
4. Each feature uses its own MongoDB collection (`earn_rules`, `referrals`, `happy_hour_rules`, etc.) so it never touches existing collections except by **read**.
5. Features that need to run on existing events (signup, scan, campaign send) do so via **explicit endpoints the frontend calls after the existing flow**, not by intercepting/modifying existing endpoints.

## Wire-up (the one-line change)

Add this at the very end of `server.py`, just before `if __name__ == "__main__":`:

```python
from features._loader import register_all
register_all(app, db)
```

That's it. To disable any feature, comment it out in `_loader.py`. To roll back the entire package, comment out the two lines above. Nothing else changes.

## Module status

| Module | Status | Public endpoints |
|---|---|---|
| `welcome_bonus.py` | ✅ Implemented | `/api/owner/earn-rules`, `/api/customer/welcome-bonus/claim` |
| `referrals.py` | ✅ Implemented | `/api/owner/referrals/*`, `/api/customer/referral/*` |
| `happy_hour.py` | ✅ Implemented | `/api/owner/happy-hour/*` |
| `reviews.py` | ✅ Implemented | `/api/customer/reviews`, `/api/owner/reviews/*` |
| `registration_forms.py` | ✅ Implemented | `/api/owner/registration-form`, `/api/join-form/{slug}` |
| `ai_send_time.py` | ✅ Implemented (math-based) | `/api/owner/ai/send-time/*` |
| `ai_churn.py` | ✅ Implemented (math-based) | `/api/owner/ai/churn/*` |
| `ai_anomaly.py` | 🟡 Stub w/ spec | `/api/owner/ai/anomaly/*` |
| `ai_voice_campaign.py` | 🟡 Stub w/ spec | `/api/owner/ai/voice-campaign` |
| `ai_birthday.py` | 🟡 Stub w/ spec | `/api/owner/ai/birthday/*` |
| `ai_translate.py` | 🟡 Stub w/ spec | `/api/owner/ai/translate` |
| `ai_brand_voice.py` | 🟡 Stub w/ spec | `/api/owner/ai/brand-voice/*` |
| `ai_conversational.py` | 🟡 Stub w/ spec | `/api/owner/ai/ask` |
| `ai_staffing.py` | 🟡 Stub w/ spec | `/api/owner/ai/staffing/*` |
| `ai_competitive.py` | 🟡 Stub w/ spec | `/api/owner/ai/competitive/*` |
| `ai_newsletter.py` | 🟡 Stub w/ spec | `/api/owner/ai/newsletter/*` |
| `tier_optimizer.py` | 🟡 Stub w/ spec | `/api/owner/ai/tier-optimizer/*` |

🟡 stubs return realistic mock data so the frontend can be developed against them. Each stub carries a `# TODO:` block explaining the production implementation, model choices, and estimated build time.

## Frontend integration

The new endpoints are **invisible** to existing pages. The frontend integrates them by adding new pages/sections under new routes (e.g. `/dashboard/earn-rules`, `/dashboard/happy-hour`, `/dashboard/reviews`). Existing pages stay untouched.

A frontend integration guide lives at `fidelitour-deploy/src/features/_README.md` (to be added in the same additive style).
