# Architecture

What runs today. For the file map and design system see `CLAUDE.md`, and check the
code when the two disagree: parts of that handoff predate later work.

## Request flow

```
Phone or browser
  -> React app (Vite, src/)         served by Vercel
  -> /api/* (src/lib/api.js)        baseURL is already '/api'
  -> FastAPI (api/index.py -> api/server.py, api/features/*, api/services/*)
  -> MongoDB
```

Locally, `scripts/dev_local.py` serves `dist/` and the API on one port against
in-memory mongomock.

## Boundaries

- **Login and rights:** `api/auth.py`, `api/features/auth_reset.py`, `api/features/oauth.py`,
  `api/features/role_perms.py`.
- **Tenant isolation:** every owner and staff query must be limited to their own shop
  and store. Treat a missing limit as a security bug.
- **Seed accounts:** the demo seed does not run on Vercel unless `FORCE_SEED` is set.

## Things that reach outside

| Side effect | Where | Why it matters |
|---|---|---|
| Web push | `api/services/web_push.py`, `public/sw.js` | Reaches real phones |
| SMS | `api/services/sms.py` | Costs money, reaches real people |
| Wallet passes | `api/features/wallet_*.py`, `push_wallet.py` | Changes the card on real phones |
| Scheduled jobs | `crons` in `vercel.json`, `api/features/cron.py` | Runs with nobody watching |
| Billing and invoices | `billing.py`, `agent_billing.py`, `invoices.py`, `fec.py` | Money and legal records |
| AI providers | `api/features/ai_*`, `copilot*` | Paid calls, answers graded by the golden set |

## Environments

`main` is production at `app.fidclic.com`. Every branch gets a Vercel preview, and
**previews use the production database**. See `docs/verification.md`.

## Planned, not built

`CLAUDE.md` section 11 lists decided-but-unbuilt work, and it is old. Verify in the
code before treating anything there as missing or present.
