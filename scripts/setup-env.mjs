#!/usr/bin/env node
/**
 * setup-env.mjs — one-shot environment bootstrapper.
 *
 * Generates VAPID keys for Web Push and prints the full set of env vars the
 * platform needs, in the exact format you'd paste into Vercel → Project →
 * Settings → Environment Variables.
 *
 * Usage:
 *   node scripts/setup-env.mjs                # print everything to stdout
 *   node scripts/setup-env.mjs --write .env   # write to .env (no overwrite)
 *
 * What this DOES:
 *   - Generates a fresh VAPID public/private keypair (web-push compatible).
 *   - Generates random secrets for JWT_SECRET, CRON_SECRET, COOKIE_SECRET.
 *   - Prints stub placeholders for everything else (Stripe, Twilio, LLM keys,
 *     Mongo URI), with a one-line note explaining what each one is for and
 *     where to get it.
 *
 * What this DOESN'T do:
 *   - Create accounts at third-party services (Stripe / Twilio / OpenRouter /
 *     Groq / MongoDB Atlas). You still have to sign up for those and paste
 *     the resulting keys into the placeholders.
 *
 * NOTE: VAPID keys are tied to the push subscriptions you've already issued.
 * If you regenerate them, every existing browser subscription becomes
 * invalid and clients will silently re-subscribe on next page load. So
 * generate ONCE per environment and never rotate without a clear plan.
 */

import { generateKeyPairSync, randomBytes } from 'node:crypto';
import { writeFileSync, existsSync } from 'node:fs';

// -- VAPID keypair generation (matches web-push library output exactly) ----
//
// VAPID is just an EC P-256 keypair, base64url-encoded with no padding. The
// `web-push` library would do this for us, but we don't want to add it as a
// devDependency just for the setup script. So we use Node's built-in crypto.
function urlBase64FromBuffer(buf) {
  return buf.toString('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
}

function generateVapid() {
  // EC P-256 raw uncompressed point: 65 bytes (0x04 | X(32) | Y(32))
  const { publicKey, privateKey } = generateKeyPairSync('ec', { namedCurve: 'P-256' });
  const pubRaw = publicKey.export({ format: 'jwk' });
  const privRaw = privateKey.export({ format: 'jwk' });
  const x = Buffer.from(pubRaw.x.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(pubRaw.x.length / 4) * 4, '='), 'base64');
  const y = Buffer.from(pubRaw.y.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(pubRaw.y.length / 4) * 4, '='), 'base64');
  const d = Buffer.from(privRaw.d.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(privRaw.d.length / 4) * 4, '='), 'base64');
  // Public key as raw uncompressed point.
  const pubPoint = Buffer.concat([Buffer.from([0x04]), x, y]);
  return {
    publicKey: urlBase64FromBuffer(pubPoint),
    privateKey: urlBase64FromBuffer(d),
  };
}

const vapid = generateVapid();
const jwtSecret = randomBytes(48).toString('base64url');
const cronSecret = randomBytes(32).toString('base64url');
const cookieSecret = randomBytes(32).toString('base64url');

const envOutput = `# ─────────────────────────────────────────────────────────────────────
# FidéliTour environment variables
# Generated: ${new Date().toISOString()}
#
# Paste this entire block into Vercel → Project → Settings → Environment
# Variables. Apply to: Production AND Preview AND Development.
# Replace every "REPLACE_ME" with the real value from the linked vendor.
# ─────────────────────────────────────────────────────────────────────

# ---- Database ---------------------------------------------------------
# MongoDB Atlas connection string. Get one from
# https://cloud.mongodb.com → cluster → Connect → Drivers → copy the URI.
MONGODB_URI=mongodb+srv://USER:PASSWORD@cluster0.example.mongodb.net/fidelitour?retryWrites=true&w=majority

# ---- Auth -------------------------------------------------------------
# JWT signing secret (used for owner + staff tokens). Already generated.
JWT_SECRET=${jwtSecret}


# Cron auth: Vercel Cron passes this in the Authorization header automatically
# when set as a project env var. Used by /api/cron/daily-triggers and
# /api/cron/monthly-report.
CRON_SECRET=${cronSecret}

# ---- Web Push (VAPID) -------------------------------------------------
# These two are a fresh keypair generated just now. Together they sign every
# push notification the platform sends. NEVER rotate these without
# re-subscribing all customers — existing browser subscriptions become
# invalid the moment the public key changes.
VAPID_PUBLIC_KEY=${vapid.publicKey}
VAPID_PRIVATE_KEY=${vapid.privateKey}
VAPID_SUBJECT=mailto:contact@fidclic.com


# ---- LLM providers (at least ONE required for AI features) ------------
# AI insights, AI campaign analyzer, voice-to-campaign all use this router.
# The platform tries them in order until one succeeds.
#
# Groq:        https://console.groq.com/keys      (free tier, fastest)
# OpenRouter:  https://openrouter.ai/keys         (one key, many models)
# Gemini:      https://aistudio.google.com/apikey (Google's, free tier)
GROQ_API_KEY=REPLACE_ME_OR_LEAVE_BLANK
OPENROUTER_API_KEY=REPLACE_ME_OR_LEAVE_BLANK
GEMINI_API_KEY=REPLACE_ME_OR_LEAVE_BLANK

# ---- SMS (Twilio, optional) -------------------------------------------
# Used for SMS campaigns when push isn't available (very old phones, customers
# who refuse push). Without these, SMS sends are no-op'd silently.
# Sign up: https://www.twilio.com/console
TWILIO_ACCOUNT_SID=REPLACE_ME_OR_LEAVE_BLANK
TWILIO_AUTH_TOKEN=REPLACE_ME_OR_LEAVE_BLANK
TWILIO_FROM_NUMBER=+33000000000

# --- Social login (optional; a missing ID simply hides that button) ---
# Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Web client
GOOGLE_CLIENT_ID=
# Apple Developer → Identifiers → Services IDs (NOT the App ID), e.g. com.fidclic.web
APPLE_CLIENT_ID=
# Must match the Services ID "Return URLs" exactly
APPLE_REDIRECT_URI=https://app.fidclic.com/login
# Version string stamped on CGU/DPA acceptance; bump it when the legal texts change
TERMS_VERSION=2026-09

# --- Native wallet passes (optional; buttons appear on the card once set) ---
# Apple: Pass Type ID + its certificate (Certificates, Identifiers & Profiles)
#   openssl pkcs12 -in pass.p12 -clcerts -nokeys -out pass-cert.pem
#   openssl pkcs12 -in pass.p12 -nocerts -nodes -out pass-key.pem
#   openssl x509 -inform der -in AppleWWDRCAG4.cer -out wwdr.pem
#   values = base64 of each PEM file (base64 -i file)
APPLE_PASS_TYPE_ID=pass.com.fidclic.loyalty
APPLE_TEAM_ID=
APPLE_PASS_CERT_B64=
APPLE_PASS_KEY_B64=
APPLE_WWDR_B64=
# random string used to derive each pass's authenticationToken (openssl rand -hex 24)
PASS_AUTH_SECRET=
# Google Wallet: issuer id (pay.google.com/business/console) + service-account JSON key (base64)
GOOGLE_WALLET_ISSUER_ID=
GOOGLE_WALLET_SA_B64=

# ---- Stripe billing (required for paid plans) -------------------------
# This is the RESELLER's Stripe account — the businesses (your tenants) pay
# the reseller. The reseller pays you separately.
#
# Get keys: https://dashboard.stripe.com/apikeys
# Webhook signing secret: https://dashboard.stripe.com/webhooks → add
# endpoint pointing to https://YOUR_DOMAIN/api/billing/webhook,
# subscribe to events: checkout.session.completed, invoice.paid,
# invoice.payment_failed, customer.subscription.updated,
# customer.subscription.deleted.
STRIPE_SECRET_KEY=sk_live_REPLACE_ME
STRIPE_WEBHOOK_SECRET=whsec_REPLACE_ME

# Plan price IDs — create in Stripe Dashboard → Products. The platform
# expects three tiers; each tier has a price object you copy here.
STRIPE_PRICE_STARTER=price_REPLACE_ME
STRIPE_PRICE_GROWTH=price_REPLACE_ME
STRIPE_PRICE_PRO=price_REPLACE_ME


# ---- Public URL -------------------------------------------------------
# Where the platform lives. Used in password-reset + trial-reminder emails
# and Stripe return URLs.
PUBLIC_SITE_URL=https://app.fidclic.com

# ---- Optional: Sentry / error tracking --------------------------------
# SENTRY_DSN=REPLACE_ME
# VITE_SENTRY_DSN=REPLACE_ME
`;

const writeFlagIdx = process.argv.indexOf('--write');
if (writeFlagIdx !== -1) {
  const path = process.argv[writeFlagIdx + 1] || '.env';
  if (existsSync(path)) {
    console.error(`✗ ${path} already exists. Refusing to overwrite. Move it aside first.`);
    process.exit(1);
  }
  writeFileSync(path, envOutput, { mode: 0o600 });
  console.log(`✓ Wrote ${path} (mode 600). Add this file to .gitignore.`);
  console.log(`✓ VAPID public key (use this in the frontend):\n  ${vapid.publicKey}`);
} else {
  process.stdout.write(envOutput);
  console.error('\n--- end of env block ---');
  console.error('Tip: re-run with `--write .env` to save to disk instead of printing.');
}
