import React, { useState } from 'react';
import {
  BookOpen, KeyRound, Gauge, AlertTriangle, Users, Receipt, Undo2, Gift, ShieldCheck, Repeat, Webhook,
  Store, Monitor, ShoppingCart, Zap, Lock, History, Copy, Check, LogIn, Terminal,
} from 'lucide-react';

/* Public developer documentation of the FidClic merchant API
   (https://app.fidclic.com/developers, no login). The contract lives in
   features/merchant_api.py — keep this page in step with it. */

const BASE = 'https://app.fidclic.com/api/v1';
const API_VERSION = '2026-11-09';
const KEY = 'fc_live_VOTRE_CLE';

const SECTIONS = [
  { id: 'demarrer', label: 'Démarrer', icon: BookOpen },
  { id: 'authentification', label: 'Authentification', icon: KeyRound },
  { id: 'limites', label: 'Limites et offres', icon: Gauge },
  { id: 'erreurs', label: 'Erreurs', icon: AlertTriangle },
  { id: 'commerce', label: 'Votre commerce', icon: Store },
  { id: 'clients', label: 'Clients', icon: Users },
  { id: 'passages', label: 'Passages', icon: Receipt },
  { id: 'annulation', label: 'Annuler un passage', icon: Undo2 },
  { id: 'recompenses', label: 'Récompenses', icon: Gift },
  { id: 'verification', label: 'Vérification SMS', icon: ShieldCheck },
  { id: 'idempotence', label: 'Idempotence', icon: Repeat },
  { id: 'webhooks', label: 'Webhooks', icon: Webhook },
  { id: 'guide-caisse', label: 'Guide : caisse', icon: Receipt },
  { id: 'guide-borne', label: 'Guide : borne de commande', icon: Monitor },
  { id: 'guide-ecommerce', label: 'Guide : site e-commerce', icon: ShoppingCart },
  { id: 'guide-zapier', label: 'Guide : Zapier, Make, n8n', icon: Zap },
  { id: 'securite', label: 'Sécurité', icon: Lock },
  { id: 'changelog', label: 'Changelog', icon: History },
];

/* ───────────── building blocks ───────────── */

function CodeBlock({ code, label = 'Exemple' }) {
  const [ok, setOk] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setOk(true);
      setTimeout(() => setOk(false), 1500);
    } catch { /* no clipboard */ }
  };
  return (
    <div className="my-3 min-w-0 max-w-full overflow-hidden rounded-xl bg-[#0B1C3F]" translate="no">
      <div className="flex items-center justify-between gap-2 border-b border-white/10 px-3 py-1.5">
        <span className="truncate text-[11px] font-semibold uppercase tracking-wide text-[#94A3B8]">{label}</span>
        <button
          type="button"
          onClick={copy}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[11.5px] font-medium text-[#CBD5E1] hover:bg-white/10"
        >
          {ok ? <Check size={13} /> : <Copy size={13} />} {ok ? 'Copié' : 'Copier'}
        </button>
      </div>
      <pre className="overflow-x-auto px-4 py-3 text-[12px] leading-relaxed text-[#E2E8F0]"><code>{code}</code></pre>
    </div>
  );
}

const C = ({ children }) => (
  <code translate="no" className="break-words rounded bg-[#F1F5FB] px-1 py-px text-[12.5px] text-[#0B1C3F]">{children}</code>
);

function Section({ id, title, icon: Icon, children }) {
  return (
    <section id={id} className="scroll-mt-20 rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)] sm:p-6">
      <h2 className="mb-3 flex items-center gap-2 text-[18px] font-bold text-[#0B1C3F]">
        {Icon && <Icon size={18} className="shrink-0 text-[#2F6BFF]" />} {title}
      </h2>
      <div className="space-y-2 text-[13.5px] leading-relaxed text-[#475569]">{children}</div>
    </section>
  );
}

const H3 = ({ children }) => <h3 className="pt-3 text-[14.5px] font-bold text-[#0B1C3F]">{children}</h3>;

function Endpoint({ method, path }) {
  const color = method === 'GET' ? 'bg-[#E7F7EE] text-[#0F8B58]'
    : method === 'DELETE' ? 'bg-[#FDECEC] text-[#C2410C]'
      : 'bg-[#EAF1FF] text-[#2F6BFF]';
  return (
    <div className="mt-4 flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-[#EDF1F7] bg-[#F8FAFD] px-3 py-2" translate="no">
      <span className={`rounded-md px-2 py-0.5 text-[11.5px] font-bold ${color}`}>{method}</span>
      <code className="min-w-0 break-all text-[13px] font-semibold text-[#0B1C3F]">{path}</code>
    </div>
  );
}

function Fields({ rows }) {
  return (
    <dl className="divide-y divide-[#F1F5F9] rounded-lg border border-[#EDF1F7]">
      {rows.map(([name, text]) => (
        <div key={name} className="grid gap-0.5 px-3 py-2 sm:grid-cols-[180px_minmax(0,1fr)] sm:gap-3">
          <dt className="min-w-0 break-words"><C>{name}</C></dt>
          <dd className="min-w-0 text-[13px] text-[#475569]">{text}</dd>
        </div>
      ))}
    </dl>
  );
}

const Steps = ({ items }) => (
  <ol className="list-decimal space-y-1.5 pl-5">
    {items.map((t, i) => <li key={i}>{t}</li>)}
  </ol>
);

const Bullets = ({ items }) => (
  <ul className="list-disc space-y-1.5 pl-5">
    {items.map((t, i) => <li key={i}>{t}</li>)}
  </ul>
);

const Note = ({ children }) => (
  <p className="rounded-lg border border-[#DCE7FF] bg-[#F3F7FF] px-3 py-2 text-[13px] text-[#1E3A8A]">{children}</p>
);

/* ───────────── code samples ───────────── */

const CURL_ME = `curl ${BASE}/me \\
  -H "Authorization: Bearer ${KEY}"`;

const CURL_ME_XKEY = `curl ${BASE}/me \\
  -H "X-API-Key: ${KEY}"`;

const ERROR_JSON = `{
  "detail": {
    "code": "customer_not_found",
    "message": "Client introuvable."
  }
}`;

const CURL_CUSTOMERS = `curl "${BASE}/customers?search=martin&per_page=50&page=1" \\
  -H "Authorization: Bearer ${KEY}"`;

const LIST_JSON = `{
  "data": [ { "id": "…", "card_number": "FT-4F8K2Q", "name": "Camille Martin", "…": "…" } ],
  "page": 1,
  "per_page": 50,
  "total": 132,
  "has_more": true
}`;

const CURL_CUSTOMER = `# par numéro de carte
curl ${BASE}/customers/FT-4F8K2Q \\
  -H "Authorization: Bearer ${KEY}"

# par téléphone (06 12 34 56 78, +33 6…, 0033… : tous acceptés)
curl ${BASE}/customers/0612345678 \\
  -H "Authorization: Bearer ${KEY}"

# par e-mail (encodé dans l'URL)
curl ${BASE}/customers/camille.martin%40exemple.fr \\
  -H "Authorization: Bearer ${KEY}"`;

const CUSTOMER_JSON = `{
  "id": "…",
  "card_number": "FT-4F8K2Q",
  "card_url": "https://app.fidclic.com/…",
  "name": "Camille Martin",
  "first_name": "Camille",
  "email": "camille.martin@exemple.fr",
  "phone": "+33612345678",
  "postal_code": "37000",
  "birthday": "04-17",
  "tier": "silver",
  "points": 120,
  "visits": 14,
  "stamps": 4,
  "reward_threshold": 10,
  "reward_unlocked": false,
  "rewards_pending": 0,
  "reward_available": false,
  "total_spent": 218.4,
  "created_at": "2026-06-02T09:12:00Z",
  "last_visit_at": "2026-11-08T17:40:00Z"
}`;

const CURL_CREATE = `curl -X POST ${BASE}/customers \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "Camille Martin",
    "phone": "06 12 34 56 78",
    "email": "camille.martin@exemple.fr",
    "postal_code": "37000",
    "consent": true
  }'`;

const CURL_VISIT = `curl -X POST ${BASE}/visits \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "customer": "FT-4F8K2Q",
    "amount": 12.50,
    "external_id": "T-4521"
  }'`;

const VISIT_JSON = `{
  "visit": {
    "id": "…",
    "customer_id": "…",
    "amount": 12.5,
    "points": 12,
    "items": [],
    "branch_id": null,
    "external_id": "T-4521",
    "source": "api",
    "at": "2026-11-09T10:15:00Z"
  },
  "customer": { "card_number": "FT-4F8K2Q", "stamps": 5, "reward_available": false, "…": "…" },
  "tier_upgraded": false,
  "reward_unlocked": false,
  "duplicate": false
}`;

const CURL_VISITS = `curl "${BASE}/visits?customer=FT-4F8K2Q&since=2026-11-01T00:00:00Z&page=1&per_page=100" \\
  -H "Authorization: Bearer ${KEY}"`;

const CURL_CANCEL = `curl -X POST ${BASE}/visits/T-4521/cancel \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{ "reason": "Remboursement", "external_id": "AVOIR-4521" }'`;

const CANCEL_JSON = `{
  "cancelled": true,
  "duplicate": false,
  "visit": { "id": "…", "external_id": "T-4521", "…": "…" },
  "customer": { "card_number": "FT-4F8K2Q", "…": "…" },
  "reversed": {
    "visits": 1,
    "points": 12,
    "amount": 12.5,
    "stamps": 1,
    "rewards_cancelled": 0
  },
  "not_reversed": []
}`;

const CURL_HOLD = `curl -X POST ${BASE}/rewards/hold \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{ "customer": "FT-4F8K2Q", "ttl_seconds": 300 }'

# Réponse 201
# { "hold_id": "hold_…", "expires_at": "2026-11-09T10:20:00Z", "customer": { … } }`;

const CURL_RELEASE = `curl -X DELETE ${BASE}/rewards/hold/hold_XXXX \\
  -H "Authorization: Bearer ${KEY}"

# Réponse : { "released": true }`;

const CURL_REDEEM = `curl -X POST ${BASE}/rewards/redeem \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "customer": "FT-4F8K2Q",
    "reward_name": "Café offert",
    "external_id": "T-4522-recompense"
  }'

# Réponse : { "customer": { … }, "redeemed": true, "duplicate": false }`;

const CURL_VERIFY = `curl -X POST ${BASE}/customers/FT-4F8K2Q/verification \\
  -H "Authorization: Bearer ${KEY}"

# Réponse
# {
#   "sent": true,
#   "channel": "sms",
#   "to": "+33 6 •• •• •• 78",
#   "verification_id": "…",
#   "expires_at": "2026-11-09T10:25:00Z"
# }`;

const CURL_CHECK = `curl -X POST ${BASE}/customers/FT-4F8K2Q/verification/check \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{ "code": "482913" }'

# Réponse
# { "verified": true, "verification_token": "vt_…", "expires_at": "2026-11-09T10:30:00Z" }`;

const WEBHOOK_EVENT = `{
  "id": "evt_…",
  "type": "visit.created",
  "api_version": "${API_VERSION}",
  "created_at": "2026-11-09T10:15:00Z",
  "data": { "…": "…" }
}`;

const WEBHOOK_HEADERS = `Content-Type: application/json
X-FidClic-Event: visit.created
X-FidClic-Delivery: evt_…
X-FidClic-Api-Version: ${API_VERSION}
X-FidClic-Signature: t=1762683300,v1=5f2b…c9a1`;

const VERIFY_NODE = `const crypto = require('crypto');
const express = require('express');
const app = express();

// Le secret de signature est affiché dans l'onglet Webhooks.
const SECRET = process.env.FIDCLIC_WEBHOOK_SECRET;

function signatureValide(corpsBrut, entete) {
  const parts = Object.fromEntries((entete || '').split(',').map((p) => p.split('=')));
  const t = Number(parts.t);
  // Refuse les envois trop anciens (rejeu) : plus de 5 minutes d'écart.
  if (!t || Math.abs(Date.now() / 1000 - t) > 300) return false;
  const attendu = crypto.createHmac('sha256', SECRET)
    .update(\`\${t}.\`)
    .update(corpsBrut)
    .digest('hex');
  const a = Buffer.from(attendu, 'hex');
  const b = Buffer.from(parts.v1 || '', 'hex');
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// express.raw : on a besoin du corps EXACT, avant tout JSON.parse.
app.post('/webhooks/fidclic', express.raw({ type: 'application/json' }), (req, res) => {
  if (!signatureValide(req.body, req.get('X-FidClic-Signature'))) return res.status(401).end();
  const evt = JSON.parse(req.body.toString('utf8'));
  // Dédoublonnez sur X-FidClic-Delivery (= evt.id) : un envoi peut arriver deux fois.
  res.status(200).end(); // répondez vite, traitez ensuite
});`;

const VERIFY_PYTHON = `import hashlib
import hmac
import os
import time

SECRET = os.environ["FIDCLIC_WEBHOOK_SECRET"]


def signature_valide(corps_brut: bytes, entete: str) -> bool:
    try:
        parts = dict(p.split("=", 1) for p in entete.split(","))
        t = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(time.time() - t) > 300:  # rejeu
        return False
    attendu = hmac.new(SECRET.encode(), f"{t}.".encode() + corps_brut, hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendu, parts.get("v1", ""))


# Flask :
# @app.post("/webhooks/fidclic")
# def fidclic():
#     if not signature_valide(request.get_data(), request.headers.get("X-FidClic-Signature", "")):
#         abort(401)
#     evt = request.get_json()
#     return "", 200`;

const VERIFY_PHP = `<?php
$secret = getenv('FIDCLIC_WEBHOOK_SECRET');
$corps  = file_get_contents('php://input');           // corps brut
$entete = $_SERVER['HTTP_X_FIDCLIC_SIGNATURE'] ?? '';

$parts = [];
foreach (explode(',', $entete) as $p) {
    [$k, $v] = array_pad(explode('=', $p, 2), 2, '');
    $parts[$k] = $v;
}
$t = (int)($parts['t'] ?? 0);
if ($t === 0 || abs(time() - $t) > 300) { http_response_code(401); exit; } // rejeu

$attendu = hash_hmac('sha256', $t . '.' . $corps, $secret);
if (!hash_equals($attendu, $parts['v1'] ?? '')) { http_response_code(401); exit; }

$evt = json_decode($corps, true);
// Dédoublonnez sur $_SERVER['HTTP_X_FIDCLIC_DELIVERY'].
http_response_code(200);`;

const GUIDE_POS = `# 1. Ticket encaissé avec une carte FidClic scannée
curl -X POST ${BASE}/visits \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{ "customer": "FT-4F8K2Q", "amount": 23.80, "external_id": "T-4521" }'

# 2. Le ticket est remboursé
curl -X POST ${BASE}/visits/T-4521/cancel \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{ "reason": "Remboursement" }'

# 3. reward_available = true → le client utilise sa récompense
curl -X POST ${BASE}/rewards/redeem \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{ "customer": "FT-4F8K2Q", "external_id": "T-4522-recompense" }'`;

const GUIDE_KIOSK = `# 1. QR scanné sur la borne
curl ${BASE}/customers/FT-4F8K2Q -H "Authorization: Bearer ${KEY}"

# 2. reward_available = true → réserver la récompense pendant le paiement
curl -X POST ${BASE}/rewards/hold \\
  -H "Authorization: Bearer ${KEY}" -H "Content-Type: application/json" \\
  -d '{ "customer": "FT-4F8K2Q", "ttl_seconds": 300 }'

# 3. Paiement accepté → utiliser la récompense, puis enregistrer le passage
curl -X POST ${BASE}/rewards/redeem \\
  -H "Authorization: Bearer ${KEY}" -H "Content-Type: application/json" \\
  -d '{ "customer": "FT-4F8K2Q", "hold_id": "hold_XXXX", "external_id": "CMD-1042-recompense" }'

curl -X POST ${BASE}/visits \\
  -H "Authorization: Bearer ${KEY}" -H "Content-Type: application/json" \\
  -d '{ "customer": "FT-4F8K2Q", "amount": 14.90, "external_id": "CMD-1042" }'

# Commande abandonnée → libérer la récompense
curl -X DELETE ${BASE}/rewards/hold/hold_XXXX -H "Authorization: Bearer ${KEY}"`;

const GUIDE_SHOP = `# Côté SERVEUR uniquement (jamais dans le navigateur)

# 1. Le client saisit son téléphone
curl ${BASE}/customers/0612345678 -H "Authorization: Bearer ${KEY}"

# 2. Paiement CONFIRMÉ → enregistrer l'achat
curl -X POST ${BASE}/visits \\
  -H "Authorization: Bearer ${KEY}" -H "Content-Type: application/json" \\
  -d '{ "customer": "0612345678", "amount": 39.00, "external_id": "WEB-20931" }'

# 3. Utiliser une récompense en ligne (clé « Site en ligne »)
curl -X POST ${BASE}/customers/0612345678/verification -H "Authorization: Bearer ${KEY}"

curl -X POST ${BASE}/customers/0612345678/verification/check \\
  -H "Authorization: Bearer ${KEY}" -H "Content-Type: application/json" \\
  -d '{ "code": "482913" }'

curl -X POST ${BASE}/rewards/redeem \\
  -H "Authorization: Bearer ${KEY}" -H "Content-Type: application/json" \\
  -d '{ "customer": "0612345678", "verification_token": "vt_XXXX", "external_id": "WEB-20931-recompense" }'`;

const GUIDE_ZAPIER = `# Étape « Requête HTTP » (Zapier Webhooks, Make HTTP, n8n HTTP Request)
# Méthode : POST
# URL     : ${BASE}/customers
# En-têtes: Authorization: Bearer ${KEY}
#           Content-Type: application/json
# Corps   :
{
  "name": "{{nom}}",
  "phone": "{{telephone}}",
  "email": "{{email}}",
  "consent": true
}

# Équivalent curl
curl -X POST ${BASE}/customers \\
  -H "Authorization: Bearer ${KEY}" -H "Content-Type: application/json" \\
  -d '{ "name": "Camille Martin", "phone": "0612345678", "consent": true }'`;

/* ───────────── page ───────────── */

const ERRORS = [
  ['400', 'consent_required', 'Création de client sans consent: true.'],
  ['400', 'wrong_code', 'Code SMS faux (attempts_left = essais restants).'],
  ['401', 'missing_api_key', 'Aucune clé dans l\'en-tête Authorization (ou X-API-Key).'],
  ['401', 'invalid_api_key', 'Clé inconnue ou révoquée.'],
  ['403', 'PLAN_FEATURE_DISABLED', "L'API n'est pas incluse dans l'offre du commerce."],
  ['403', 'read_only_key', 'Écriture avec une clé « Lecture ».'],
  ['403', 'business_suspended', 'Le commerce est suspendu.'],
  ['403', 'verification_required', 'Clé « Site en ligne » : récompense sans verification_token valide.'],
  ['404', 'customer_not_found', 'Client inconnu ou supprimé.'],
  ['404', 'visit_not_found', 'Passage introuvable.'],
  ['404', 'hold_not_found', 'Réservation introuvable.'],
  ['409', 'ambiguous_customer', 'Plusieurs clients sur ce téléphone ou cet e-mail : utilisez le numéro de carte.'],
  ['409', 'no_reward', 'Aucune récompense disponible.'],
  ['409', 'reward_next_visit', 'Récompense gagnée à ce passage : utilisable à partir du suivant.'],
  ['409', 'reward_held', 'Récompense réservée par une autre borne ou caisse.'],
  ['409', 'visit_too_old', 'Passage de plus de 90 jours : non annulable.'],
  ['409', 'visit_not_cancellable', 'Passage qui a transféré une carte papier.'],
  ['409', 'no_phone', 'Le client n’a pas de téléphone.'],
  ['409', 'request_in_progress', 'Même external_id encore en cours : réessayez dans quelques secondes.'],
  ['422', 'idempotency_conflict', 'Même external_id avec un corps différent.'],
  ['422', 'finite_number', 'Un nombre infini ou NaN dans le corps JSON (1e309, NaN, Infinity) : refusé avant tout traitement.'],
  ['429', 'rate_limited', 'Plus de 120 requêtes par minute avec cette clé.'],
  ['429', 'too_many_holds', 'Plus de 3 réservations non utilisées pour ce client dans l\'heure.'],
  ['429', 'too_many_codes', 'Trop de codes SMS (3 par heure et par client, 200 par jour et par commerce).'],
  ['429', 'too_many_attempts', '5 codes faux : demandez un nouveau code.'],
  ['502', 'sms_failed', "L'envoi du SMS a échoué."],
  ['503', 'sms_unavailable', 'Envoi de SMS indisponible pour le moment.'],
];

function Toc({ onPick }) {
  return (
    <nav aria-label="Sommaire">
      <ul className="space-y-0.5">
        {SECTIONS.map(({ id, label, icon: Icon }) => (
          <li key={id}>
            <a
              href={`#${id}`}
              onClick={onPick}
              className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-[#475569] hover:bg-[#EAF1FF] hover:text-[#2F6BFF]"
            >
              <Icon size={14} className="shrink-0" /> {label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export default function DevelopersPage() {
  return (
    <div data-testid="dev-docs" lang="fr" className="min-h-screen overflow-x-hidden bg-[#F6F8FC] text-[#0B1C3F]">
      {/* top bar */}
      <header className="sticky top-0 z-30 border-b border-[#EDF1F7] bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4">
          <a href="#demarrer" className="flex min-w-0 items-center gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#2F6BFF] text-white"><Terminal size={16} /></span>
            <span className="truncate text-[15px] font-bold text-[#0B1C3F]">FidClic Developers</span>
          </a>
          <a
            href="/login"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[#2F6BFF] px-3 py-1.5 text-[13px] font-semibold text-white hover:bg-[#2559D9]"
          >
            <LogIn size={14} /> Se connecter
          </a>
        </div>
      </header>

      <div className="mx-auto flex max-w-6xl gap-8 px-4 py-6">
        {/* desktop table of contents */}
        <aside className="hidden w-60 shrink-0 lg:block">
          <div className="sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto rounded-2xl border border-[#EDF1F7] bg-white p-3">
            <p className="mb-2 px-2.5 text-[11px] font-semibold uppercase tracking-wide text-[#94A3B8]">Sommaire</p>
            <Toc />
          </div>
        </aside>

        <main className="min-w-0 flex-1 space-y-5">
          {/* mobile table of contents */}
          <details className="rounded-2xl border border-[#EDF1F7] bg-white p-3 lg:hidden">
            <summary className="cursor-pointer text-[13.5px] font-semibold text-[#0B1C3F]">Sommaire</summary>
            <div className="mt-2"><Toc /></div>
          </details>

          {/* hero */}
          <div className="rounded-2xl bg-[#0B1C3F] p-5 text-white sm:p-7">
            <p className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-[#93B4FF]">API marchand · version {API_VERSION}</p>
            <h1 className="text-[24px] font-bold leading-tight sm:text-[28px]">Connectez votre caisse, votre borne ou votre site à FidClic</h1>
            <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-[#CBD5E1]">
              Enregistrez les passages, retrouvez vos clients, faites utiliser les récompenses et recevez les événements en temps réel.
              Une API REST en JSON, les mêmes règles qu'au comptoir.
            </p>
          </div>

          <Section id="demarrer" title="Démarrer" icon={BookOpen}>
            <p>Toutes les adresses commencent par :</p>
            <CodeBlock label="URL de base" code={BASE} />
            <Steps items={[
              <>Le gérant du commerce crée une clé dans <strong>Paramètres › API & Intégrations</strong>.</>,
              <>Copiez-la tout de suite : elle n'est affichée qu'une fois.</>,
              <>Faites votre premier appel :</>,
            ]}
            />
            <CodeBlock label="curl" code={CURL_ME} />
            <p>Les réponses sont en JSON, les dates en ISO 8601.</p>
          </Section>

          <Section id="authentification" title="Authentification" icon={KeyRound}>
            <p>Chaque appel porte la clé dans l'en-tête <C>Authorization: Bearer fc_live_…</C>, ou dans <C>X-API-Key</C> :</p>
            <CodeBlock label="curl" code={CURL_ME_XKEY} />
            <H3>Types de clés</H3>
            <Fields rows={[
              ['Lecture', 'Lire le commerce, les clients et les passages. Les écritures répondent 403.'],
              ['Lecture + écriture', 'Créer des clients, enregistrer et annuler des passages, réserver et utiliser des récompenses.'],
              ['Option « Site en ligne »', <>Pour une clé utilisée par un site web : utiliser une récompense exige un jeton de vérification SMS (<a className="text-[#2F6BFF] underline" href="#verification">voir Vérification SMS</a>).</>],
            ]}
            />
          </Section>

          <Section id="limites" title="Limites et offres" icon={Gauge}>
            <Bullets items={[
              <><strong>120 requêtes par minute</strong> et par clé. Au-delà : <C>429 rate_limited</C>, réessayez un peu plus tard.</>,
              <>L'API est incluse dans les offres dont l'option <strong>« API & Intégrations »</strong> est activée. Sinon : <C>403 PLAN_FEATURE_DISABLED</C>.</>,
              <>Pagination : <C>per_page</C> vaut 100 au plus.</>,
            ]}
            />
          </Section>

          <Section id="erreurs" title="Erreurs" icon={AlertTriangle}>
            <p>Une erreur renvoie un code HTTP et un corps JSON avec un <C>code</C> stable (à tester dans votre code) et un <C>message</C> lisible :</p>
            <CodeBlock label="JSON" code={ERROR_JSON} />
            <div className="overflow-x-auto rounded-lg border border-[#EDF1F7]">
              <table className="w-full min-w-[520px] text-left text-[12.5px]">
                <thead className="bg-[#F8FAFD] text-[#64748B]">
                  <tr><th className="px-3 py-2 font-semibold">HTTP</th><th className="px-3 py-2 font-semibold">code</th><th className="px-3 py-2 font-semibold">Signification</th></tr>
                </thead>
                <tbody className="divide-y divide-[#F1F5F9]">
                  {ERRORS.map(([http, code, text]) => (
                    <tr key={`${http}-${code}-${text}`}>
                      <td className="px-3 py-1.5 font-semibold text-[#0B1C3F]" translate="no">{http}</td>
                      <td className="px-3 py-1.5" translate="no"><code className="text-[#0B1C3F]">{code}</code></td>
                      <td className="px-3 py-1.5 text-[#475569]">{text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section id="commerce" title="Votre commerce" icon={Store}>
            <Endpoint method="GET" path="/me" />
            <p>Le commerce lié à la clé, son offre, les règles de la carte et la clé elle-même.</p>
            <Fields rows={[
              ['business', <>id, name, slug, city, sector, <C>branches</C> : liste des établissements <C>{'{id, name}'}</C>.</>],
              ['plan', "L'offre du commerce."],
              ['card', <><C>reward_threshold</C> (passages pour la récompense), <C>reward</C>, <C>points_mode</C>.</>],
              ['key', <><C>name</C> et <C>scopes</C> de la clé utilisée.</>],
            ]}
            />
          </Section>

          <Section id="clients" title="Clients" icon={Users}>
            <Endpoint method="GET" path="/customers?search=&updated_since=&page=&per_page=" />
            <Fields rows={[
              ['search', 'Texte à chercher.'],
              ['updated_since', 'Date ISO : seulement les clients modifiés depuis.'],
              ['page, per_page', '100 par page au plus.'],
            ]}
            />
            <CodeBlock label="curl" code={CURL_CUSTOMERS} />
            <CodeBlock label="Réponse" code={LIST_JSON} />

            <Endpoint method="GET" path="/customers/{ref}" />
            <p>La référence <C>ref</C> d'un client peut être :</p>
            <Bullets items={[
              "l'identifiant FidClic du client ;",
              <>le numéro de carte <C>FT-XXXX</C> (ou l'URL de la carte) ;</>,
              <>le téléphone, dans n'importe quel format (<C>06 12 34 56 78</C>, <C>+33 6…</C>, <C>0033…</C>) : les 9 derniers chiffres sont comparés ;</>,
              "l'e-mail, exact, sans tenir compte des majuscules.",
            ]}
            />
            <p>Encodez la référence dans l'URL (par ex. <C>encodeURIComponent</C>). Cette même référence est acceptée partout où un champ <C>customer</C> est demandé.</p>
            <Note>Deux clients sur le même téléphone ou le même e-mail → <C>409 ambiguous_customer</C> : utilisez le numéro de carte. Client inconnu ou supprimé → <C>404 customer_not_found</C>.</Note>
            <CodeBlock label="curl" code={CURL_CUSTOMER} />

            <H3>L'objet client</H3>
            <CodeBlock label="JSON" code={CUSTOMER_JSON} />
            <Fields rows={[
              ['id', 'Identifiant FidClic.'],
              ['card_number, card_url', 'Numéro et lien de la carte du client.'],
              ['name, first_name', 'Nom complet et prénom.'],
              ['email, phone, postal_code', 'Coordonnées.'],
              ['birthday', 'Anniversaire (MM-JJ).'],
              ['tier', 'Palier du client.'],
              ['points, visits, stamps', 'Points, nombre de passages, tampons du cycle en cours.'],
              ['reward_threshold', 'Tampons nécessaires pour la récompense.'],
              ['reward_unlocked', 'La carte est complète.'],
              ['rewards_pending', 'Récompenses gagnées pas encore utilisées.'],
              ['reward_available', <>Une récompense est utilisable <strong>maintenant</strong>. Vrai seulement à partir du passage qui suit celui qui l'a gagnée.</>],
              ['total_spent', 'Total dépensé.'],
              ['created_at, last_visit_at', 'Inscription et dernier passage.'],
            ]}
            />

            <Endpoint method="POST" path="/customers" />
            <Fields rows={[
              ['name', 'Obligatoire.'],
              ['phone', 'Obligatoire.'],
              ['email, postal_code, birthday', 'Facultatifs.'],
              ['consent', <>Obligatoire, <C>true</C> : le client accepte le programme. Sinon <C>400 consent_required</C>.</>],
              ['source', "Facultatif : canal d'inscription."],
            ]}
            />
            <p>Réponse <C>201</C> : le client et <C>created: true</C>. Si le téléphone ou l'e-mail existe déjà, la carte existante est renvoyée avec <C>created: false</C> (pas de doublon).</p>
            <CodeBlock label="curl" code={CURL_CREATE} />
          </Section>

          <Section id="passages" title="Passages" icon={Receipt}>
            <Endpoint method="POST" path="/visits" />
            <p>Enregistre un passage / achat. <strong>Mêmes règles qu'un scan au comptoir</strong> : tampons, points, palier, récompense.</p>
            <Fields rows={[
              ['customer', 'Obligatoire. Référence du client (id, FT-…, téléphone, e-mail).'],
              ['amount', 'Montant du ticket, de 0 à 100000.'],
              ['items', <>Facultatif : <C>[{'{ "item_id": "…", "qty": 2 }'}]</C>. Les prix du catalogue remplacent <C>amount</C>.</>],
              ['branch_id', <>Obligatoire quand le commerce a plusieurs établissements (liste dans <C>GET /me</C>).</>],
              ['external_id', <>Numéro de ticket ou de commande, 120 caractères au plus. <a className="text-[#2F6BFF] underline" href="#idempotence">Voir Idempotence</a>.</>],
            ]}
            />
            <CodeBlock label="curl" code={CURL_VISIT} />
            <p>Réponse <C>201</C> :</p>
            <CodeBlock label="Réponse" code={VISIT_JSON} />
            <p><C>tier_upgraded</C> : le client change de palier. <C>reward_unlocked</C> : ce passage complète la carte (la récompense sera utilisable au passage suivant). <C>duplicate</C> : ce ticket avait déjà été reçu.</p>

            <Endpoint method="GET" path="/visits?customer=&since=&page=&per_page=" />
            <p>Les passages, filtrés par client et par date, page par page.</p>
            <CodeBlock label="curl" code={CURL_VISITS} />
          </Section>

          <Section id="annulation" title="Annuler un passage (remboursement)" icon={Undo2}>
            <Endpoint method="POST" path="/visits/{ref}/cancel" />
            <p><C>ref</C> = l'id du passage, ou l'<C>external_id</C> avec lequel il a été créé. Corps facultatif : <C>reason</C>, <C>external_id</C>.</p>
            <p>Le passage sort des chiffres et FidClic reprend ce qu'il avait donné :</p>
            <Bullets items={[
              'le passage et ses tampons ;',
              'ses points (jamais en dessous de 0) ;',
              'le montant dépensé ;',
              "la récompense qu'il avait débloquée, si elle n'a pas encore été utilisée.",
            ]}
            />
            <CodeBlock label="curl" code={CURL_CANCEL} />
            <CodeBlock label="Réponse" code={CANCEL_JSON} />
            <Fields rows={[
              ['reversed', 'Ce qui a été repris : visits, points, amount, stamps, rewards_cancelled.'],
              ['not_reversed', <>Ce qui n'a pas pu l'être : <C>points_already_spent</C> (points déjà dépensés), <C>reward_already_used</C> (récompense déjà utilisée).</>],
              ['duplicate', <>Un deuxième appel répond <C>200</C> avec <C>duplicate: true</C>, sans rien reprendre deux fois.</>],
            ]}
            />
            <Bullets items={[
              <><C>404 visit_not_found</C> · <C>409 visit_too_old</C> (plus de 90 jours) · <C>409 visit_not_cancellable</C> (passage qui a transféré une carte papier).</>,
              <><strong>Remboursement partiel</strong> : annulez le passage, puis envoyez un nouveau passage avec le montant gardé (et un nouvel <C>external_id</C>).</>,
              'Les messages déjà envoyés, les récompenses de défis et de parrainage déjà données ne sont pas reprises.',
            ]}
            />
          </Section>

          <Section id="recompenses" title="Récompenses" icon={Gift}>
            <p>Une récompense gagnée est utilisable <strong>à partir du passage suivant</strong> (<C>reward_available</C> sur l'objet client).</p>

            <H3>Réserver pendant le paiement (borne)</H3>
            <Endpoint method="POST" path="/rewards/hold" />
            <Fields rows={[
              ['customer', 'Obligatoire. Référence du client.'],
              ['ttl_seconds', 'Durée de la réservation, de 30 à 900 secondes (300 par défaut).'],
            ]}
            />
            <p>Réponse <C>201</C> : <C>hold_id</C> (<C>hold_…</C>), <C>expires_at</C>, <C>customer</C>. Pendant la réservation, la caisse et les autres clés reçoivent <C>409 reward_held</C>. Rien à réserver : <C>409 no_reward</C> ou <C>409 reward_next_visit</C>. Au plus 3 réservations par client et par heure qui ne finissent pas en récompense utilisée : au-delà, <C>429 too_many_holds</C> (la récompense reste disponible à la caisse).</p>
            <CodeBlock label="curl" code={CURL_HOLD} />
            <Endpoint method="DELETE" path="/rewards/hold/{hold_id}" />
            <p>Libère la réservation : <C>{'{ "released": true | false }'}</C>. Réservation inconnue : <C>404 hold_not_found</C>.</p>
            <CodeBlock label="curl" code={CURL_RELEASE} />
            <Note>Une réservation expirée ne bloque plus personne. La réservation verrouille un écran ; la récompense elle-même ne peut de toute façon être utilisée qu'une seule fois.</Note>

            <H3>Utiliser la récompense</H3>
            <Endpoint method="POST" path="/rewards/redeem" />
            <Fields rows={[
              ['customer', 'Obligatoire. Référence du client.'],
              ['reward_name', 'Facultatif : nom de la récompense donnée.'],
              ['external_id', 'Recommandé : numéro du ticket ou de la commande.'],
              ['hold_id', 'La réservation faite par la borne, le cas échéant.'],
              ['verification_token', 'Obligatoire avec une clé « Site en ligne » (jeton vt_… de la vérification SMS).'],
            ]}
            />
            <p>Réponse : <C>{'{ customer, redeemed: true, duplicate }'}</C>. Erreurs : <C>409 no_reward</C>, <C>409 reward_next_visit</C>, <C>409 reward_held</C>, <C>403 verification_required</C>.</p>
            <CodeBlock label="curl" code={CURL_REDEEM} />
          </Section>

          <Section id="verification" title="Vérification SMS (achats en ligne)" icon={ShieldCheck}>
            <p>Avec une clé « Site en ligne », le client prouve que la carte est la sienne avec un code reçu par SMS sur <strong>son propre téléphone</strong>.</p>
            <Endpoint method="POST" path="/customers/{ref}/verification" />
            <p>Envoie un code à 6 chiffres, valable 10 minutes. Réponse : <C>sent</C>, <C>channel: "sms"</C>, <C>to</C> (numéro masqué), <C>verification_id</C>, <C>expires_at</C>.</p>
            <Bullets items={[
              <>3 codes par heure et par client, 200 par jour et par commerce → <C>429 too_many_codes</C>.</>,
              <><C>409 no_phone</C> : le client n'a pas de téléphone · <C>503 sms_unavailable</C> · <C>502 sms_failed</C>.</>,
            ]}
            />
            <CodeBlock label="curl" code={CURL_VERIFY} />
            <Endpoint method="POST" path="/customers/{ref}/verification/check" />
            <p>Corps : <C>{'{ "code": "482913" }'}</C>. Réponse : <C>verified: true</C>, <C>verification_token</C> (<C>vt_…</C>), <C>expires_at</C>. Le jeton est valable 15 minutes, une seule fois, et uniquement pour ce client.</p>
            <Bullets items={[
              <><C>400 wrong_code</C> avec <C>attempts_left</C> (essais restants).</>,
              <><C>429 too_many_attempts</C> après 5 codes faux.</>,
            ]}
            />
            <CodeBlock label="curl" code={CURL_CHECK} />
          </Section>

          <Section id="idempotence" title="Idempotence" icon={Repeat}>
            <p>Envoyez un <C>external_id</C> sur <C>POST /visits</C>, <C>POST /rewards/redeem</C> et <C>POST /visits/{'{ref}'}/cancel</C>. Un même ticket envoyé deux fois n'est compté qu'une fois.</p>
            <Fields rows={[
              ['Même id, même corps', <>La même réponse, avec <C>duplicate: true</C>. Gardé 30 jours, par commerce.</>],
              ['Même id, autre corps', <><C>422 idempotency_conflict</C>.</>],
              ['Même id encore en cours', <><C>409 request_in_progress</C> : réessayez dans quelques secondes. Un appel bloqué depuis 60 secondes est repris.</>],
              ['Appel en échec', "L'id est libéré : vous pouvez le renvoyer."],
            ]}
            />
            <Note>Recommandé : <C>external_id</C> = le numéro du ticket ou de la commande. En cas d'erreur réseau, renvoyez le même appel avec le même id.</Note>
          </Section>

          <Section id="webhooks" title="Webhooks" icon={Webhook}>
            <p>Ajoutez l'adresse de votre serveur dans <strong>Paramètres › API & Intégrations › Webhooks</strong> et choisissez les événements :</p>
            <Fields rows={[
              ['customer.created', 'Une nouvelle carte est créée.'],
              ['visit.created', 'Un passage est enregistré.'],
              ['visit.cancelled', 'Un passage est annulé.'],
              ['reward.unlocked', 'Un client débloque une récompense.'],
              ['reward.redeemed', 'Un client utilise une récompense.'],
            ]}
            />
            <H3>Format</H3>
            <p>Chaque événement est un <C>POST</C> JSON :</p>
            <CodeBlock label="Corps" code={WEBHOOK_EVENT} />
            <CodeBlock label="En-têtes" code={WEBHOOK_HEADERS} />
            <Bullets items={[
              <><C>X-FidClic-Delivery</C> = l'id de l'événement. Un envoi peut arriver deux fois : <strong>dédoublonnez sur cet id</strong>.</>,
              <><C>X-FidClic-Signature</C> : <C>{'t=<unix>,v1=<hex>'}</C>, où <C>v1</C> = HMAC-SHA256(secret, <C>{'"<t>.<corps brut>"'}</C>).</>,
              <>Vérifiez la signature sur le corps <strong>brut</strong>, et refusez un <C>t</C> à plus de 300 secondes de l'heure actuelle (rejeu).</>,
            ]}
            />
            <H3>Vérifier la signature</H3>
            <CodeBlock label="Node.js" code={VERIFY_NODE} />
            <CodeBlock label="Python" code={VERIFY_PYTHON} />
            <CodeBlock label="PHP" code={VERIFY_PHP} />
            <H3>Règles d'envoi</H3>
            <Bullets items={[
              'Adresse en https uniquement, et publique : les adresses internes sont refusées, y compris après résolution DNS.',
              'Les redirections ne sont pas suivies.',
              'Les envois partent en arrière-plan : la caisse n\'attend jamais votre serveur.',
              'Répondez 2xx en moins de 3 secondes (traitez le reste ensuite).',
              "En cas d'échec : nouvel essai toutes les 15 minutes, puis chaque jour ; 3 essais au total sur 3 jours.",
              "Un envoi peut être renvoyé à la main depuis l'onglet Webhooks.",
            ]}
            />
          </Section>

          <Section id="guide-caisse" title="Guide : caisse (POS)" icon={Receipt}>
            <Steps items={[
              <>À chaque ticket encaissé avec un QR FidClic scanné : <C>POST /visits</C> avec <C>external_id</C> = le numéro du ticket.</>,
              <>Affichez à l'écran <C>reward_available</C> de la réponse (champ <C>customer</C>).</>,
              <>Le client utilise sa récompense : <C>POST /rewards/redeem</C>.</>,
              <>Ticket remboursé : <C>POST /visits/{'{numéro du ticket}'}/cancel</C>.</>,
            ]}
            />
            <CodeBlock label="curl" code={GUIDE_POS} />
          </Section>

          <Section id="guide-borne" title="Guide : borne de commande" icon={Monitor}>
            <Steps items={[
              <>Le client scanne son QR : <C>GET /customers/{'{ref}'}</C>.</>,
              <>Si <C>reward_available</C> : <C>POST /rewards/hold</C> pour la réserver.</>,
              'Appliquez la remise dans le panier.',
              <>Après le paiement : <C>POST /rewards/redeem</C> avec le <C>hold_id</C>, puis <C>POST /visits</C>.</>,
              <>Commande annulée : <C>DELETE /rewards/hold/{'{hold_id}'}</C>.</>,
            ]}
            />
            <CodeBlock label="curl" code={GUIDE_KIOSK} />
          </Section>

          <Section id="guide-ecommerce" title="Guide : site e-commerce / click & collect" icon={ShoppingCart}>
            <Note>Ne mettez jamais la clé dans le code du navigateur : tous les appels partent de votre serveur.</Note>
            <Steps items={[
              <>Le client saisit son téléphone : <C>GET /customers/{'{téléphone}'}</C>.</>,
              <>Après le paiement <strong>confirmé</strong> (jamais avant) : <C>POST /visits</C> avec <C>external_id</C> = le numéro de commande.</>,
              <>Pour utiliser une récompense en ligne (clé « Site en ligne ») : <C>POST /customers/{'{ref}'}/verification</C> → le client saisit le code reçu par SMS → <C>POST …/verification/check</C> → <C>POST /rewards/redeem</C> avec le <C>verification_token</C>.</>,
            ]}
            />
            <CodeBlock label="curl" code={GUIDE_SHOP} />
          </Section>

          <Section id="guide-zapier" title="Guide : Zapier, Make, n8n" icon={Zap}>
            <Steps items={[
              'Pour être prévenu : créez un déclencheur « Webhook » dans votre outil, collez son adresse dans l’onglet Webhooks et choisissez les événements.',
              'Pour agir dans FidClic (créer un client, ajouter un passage) : ajoutez une étape « Requête HTTP » avec votre clé dans l’en-tête Authorization.',
            ]}
            />
            <CodeBlock label="Requête HTTP" code={GUIDE_ZAPIER} />
          </Section>

          <Section id="securite" title="Sécurité" icon={Lock}>
            <Bullets items={[
              'Gardez la clé côté serveur uniquement : jamais dans une page web, une application mobile ou un dépôt de code.',
              'Une clé par outil (caisse, borne, site, Zapier) : vous pouvez en couper une sans arrêter les autres.',
              'Au moindre doute, révoquez la clé dans Paramètres › API & Intégrations et créez-en une nouvelle.',
              'Une clé « Lecture » quand l’outil n’a besoin que de lire.',
              'Vérifiez toujours la signature des webhooks.',
            ]}
            />
          </Section>

          <Section id="changelog" title="Changelog" icon={History}>
            <div className="rounded-lg border border-[#EDF1F7] p-3">
              <p className="mb-1 text-[13px] font-bold text-[#0B1C3F]" translate="no">{API_VERSION}</p>
              <p className="text-[13px]">
                Recherche par e-mail, <C>409 ambiguous_customer</C>, annulation de passage, réservation de récompense, vérification SMS,
                idempotence renforcée, <C>visit.cancelled</C>, webhooks en arrière-plan et protégés, recherche par téléphone indexée,
                <C>429 too_many_holds</C>, <C>422 finite_number</C>.
              </p>
            </div>
            <p className="text-[12.5px] text-[#64748B]">La version de l'API est envoyée dans l'en-tête <C>X-FidClic-Api-Version</C> des webhooks et dans le champ <C>api_version</C> des événements.</p>
          </Section>

          <footer className="pb-8 pt-2 text-center text-[12px] text-[#94A3B8]">FidClic · API marchand {API_VERSION}</footer>
        </main>
      </div>
    </div>
  );
}
