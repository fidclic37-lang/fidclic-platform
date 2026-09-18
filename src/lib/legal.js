// Where the legal texts live. They are published on the marketing site
// (fidclic.com), not inside the app, so the app links out. Override the base
// with VITE_LEGAL_BASE_URL on a preview deployment if needed.
const BASE = (import.meta.env.VITE_LEGAL_BASE_URL || 'https://fidclic.com').replace(/\/$/, '');

export const LEGAL_LINKS = {
  cgu: `${BASE}/cgu`,
  privacy: `${BASE}/confidentialite`,
  dpa: `${BASE}/dpa`,
};
