/**
 * Where a customer came from — the frontend's copy of api/services/sources.py
 * (user, 2026-10-08: accuracy). Same keys, labels, words and aliases, so the
 * signup page, the owner's links, the Clients filter and Analyses agree.
 */
export const SOURCES = {
  qr_store: 'QR code en magasin',
  instagram: 'Instagram',
  facebook: 'Facebook',
  whatsapp: 'WhatsApp',
  tiktok: 'TikTok',
  google: 'Google',
  website: 'Site web',
  email: 'E-mail',
  sms: 'SMS',
  referral: 'Parrainage',
  import: 'Import de fichier',
  autre: 'Autre',
};
export const UNKNOWN = 'none';
export const UNKNOWN_LABEL = 'Non renseigné';

// what a customer can answer to « Comment nous avez-vous connu ? »
/* An employee's own link (Paramètres › Lien d'inscription › Liens par
   employé): /inscription/<compte>[/<établissement>]/e-marie. The word travels
   as it is — the server alone turns it into an employee, against this shop,
   so a word can never be read as someone else's (2026-10-16). */
export const AGENT_WORD = /^e-[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const isAgentWord = (raw) => AGENT_WORD.test(String(raw || '').trim().toLowerCase());

export const SIGNUP_SOURCES = ['qr_store', 'instagram', 'facebook', 'whatsapp', 'tiktok', 'google', 'website', 'email', 'sms', 'autre'];

// each channel's link: /inscription/<slug>/<word>
export const CHANNEL_WORDS = {
  qr_store: 'qr', instagram: 'insta', facebook: 'fb', whatsapp: 'wa', tiktok: 'tiktok',
  google: 'google', website: 'site', email: 'mail', sms: 'sms',
};

const ALIASES = {
  qr: 'qr_store', qrcode: 'qr_store', qr_code: 'qr_store', qr_store: 'qr_store', store: 'qr_store', magasin: 'qr_store',
  in_store: 'qr_store', instore: 'qr_store',
  insta: 'instagram', ig: 'instagram', instagram: 'instagram',
  fb: 'facebook', facebook: 'facebook', meta: 'facebook',
  wa: 'whatsapp', whatsapp: 'whatsapp', whats_app: 'whatsapp', wapp: 'whatsapp',
  tt: 'tiktok', tiktok: 'tiktok', tik_tok: 'tiktok',
  google: 'google', gmb: 'google', maps: 'google', google_maps: 'google',
  site: 'website', web: 'website', website: 'website', site_web: 'website',
  email: 'email', mail: 'email', e_mail: 'email', newsletter: 'email',
  sms: 'sms', texto: 'sms',
  autre: 'autre', other: 'autre',
};

export const normalizeSource = (raw) => {
  const k = String(raw || '').trim().toLowerCase().replace(/[\s-]/g, '_').replace(/[^a-z_]/g, '');
  return ALIASES[k] || null;
};

export const sourceLabel = (key) => SOURCES[key] || UNKNOWN_LABEL;
