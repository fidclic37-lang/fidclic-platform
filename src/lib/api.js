import axios from 'axios';
import { keyOf } from './myCards';

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
});

// Belt-and-braces auth: even though the backend sets an httpOnly cookie on
// login, some browsers / extensions / cross-tab edge cases drop the cookie on
// POST requests. We ALSO stash the JWT in localStorage and attach it as a
// Bearer header on every request. The backend now accepts either path.
const TOKEN_KEY = 'fidelitour_access_token';

export const setAuthToken = (token) => {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (_e) { /* private mode etc — silent */ }
};

// « Accéder au compte »: the super admin's read-only view of a business lives
// in its own tab, with its own token kept in sessionStorage (per tab) so the
// super admin's session in the other tabs is left untouched.
export const VIEW_KEY = 'fidclic_view_token';
export const viewToken = () => { try { return sessionStorage.getItem(VIEW_KEY); } catch (_e) { return null; } };

api.interceptors.request.use((config) => {
  try {
    const t = viewToken() || localStorage.getItem(TOKEN_KEY);
    if (t) {
      config.headers = config.headers || {};
      config.headers.Authorization = `Bearer ${t}`;
    }
    // The establishment chosen under the logo (BranchContext). The server
    // decides what the caller may actually see — see features/store_scope.py.
    config.headers = config.headers || {};
    config.headers['X-FidClic-Store'] = localStorage.getItem('ft_selected_branch_v1') || 'all';
    // A card's own phone proves it with the card's owner key (lib/myCards):
    // the server answers card data, prefs, delete, RGPD and Wallet passes
    // only to that phone or to the shop (2026-10-09 — the card number alone
    // is printed in every QR).
    const m = String(config.url || '').match(/\/card\/(FT-[A-Z0-9]+)/i);
    const bc = m ? m[1] : (config.data && typeof config.data === 'object' ? config.data.barcode_id : null);
    const k = bc ? keyOf(bc) : null;
    if (k) config.headers['X-Card-Key'] = k;
  } catch (_e) { /* ignore */ }
  return config;
});

// Super admin › Plan Limits: a call the business's plan does not include
// (403 PLAN_FEATURE_DISABLED) or a quota reached (429 PLAN_QUOTA_REACHED)
// opens the upgrade prompt (components/PlanAccess.jsx). The caller still gets
// the error, so its own « chargement impossible » stays quiet or short.
// A settings tab saved: Paramètres' « Réinitialiser » refreshes what it can undo.
const SETTINGS_SAVE = /^\/?(owner\/(etablissement|settings\/hours|customer-rules|join-link\/(slug|page)|team-access\/(users|stores|roles)|privacy|notifications\/rules|integrations\/webhooks)|me\/preferences)/;
const settingsSaved = (r) => {
  try {
    const m = String(r?.config?.method || '').toLowerCase();
    if (m && m !== 'get' && SETTINGS_SAVE.test(r?.config?.url || '')) window.dispatchEvent(new Event('fidclic:settings-saved'));
    // any owner change may have queued Wallet cards: the layout sends them
    // (lib/walletRefresh) — never the follow-up call itself
    const u = String(r?.config?.url || '');
    if (m && m !== 'get' && /^\/?owner\//.test(u) && !/wallet\/refresh/.test(u)) window.dispatchEvent(new Event('fidclic:wallet-kick'));
  } catch (_e) { /* never in the way of a response */ }
  return r;
};

// « Accéder au compte » keeps its full access while the tab is open (user,
// 2026-10-09: past its 30 minutes every page said « Not enough permissions »
// under a banner still reading « accès complet »). The tab asks for a fresh
// one with the super admin's own session — before it runs out, when the tab
// comes back, and once more if a call finds it expired.
const viewClaims = () => {
  const t = viewToken();
  if (!t) return null;
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); } catch (_e) { return null; }
};
let renewing = null;
export const renewView = () => {
  const c = viewClaims();
  if (!c?.tenant_id) return Promise.resolve(false);
  if (!renewing) {
    let own = null;
    try { own = localStorage.getItem(TOKEN_KEY); } catch (_e) { own = null; }
    renewing = fetch(`/api/admin/commerces/${encodeURIComponent(c.tenant_id)}/view-as`, {
      method: 'POST', credentials: 'include', headers: own ? { Authorization: `Bearer ${own}` } : {},
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d?.token) return false;
        try { sessionStorage.setItem(VIEW_KEY, d.token); } catch (_e) { return false; }
        return true;
      })
      .catch(() => false)
      .finally(() => { setTimeout(() => { renewing = null; }, 0); });
  }
  return renewing;
};
const renewIfDue = () => {
  const c = viewClaims();
  if (c?.exp && c.exp * 1000 - Date.now() < 12 * 60 * 1000) renewView();
};
if (typeof window !== 'undefined' && viewToken()) {
  setInterval(renewIfDue, 60 * 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) renewIfDue(); });
}

api.interceptors.response.use(settingsSaved, async (error) => {
  // the account's access ran out: renew it once and replay the call
  try {
    const res = error?.response;
    const det = res?.data?.detail;
    if (res?.status === 401 && det && typeof det === 'object' && det.code === 'VIEW_EXPIRED'
        && error.config && !error.config._viewRenewed) {
      if (await renewView()) {
        error.config._viewRenewed = true;
        return api(error.config);
      }
    }
  } catch (_e) { /* fall through to the usual message */ }
  try {
    const res = error?.response;
    if (res && (res.status === 403 || res.status === 429)) {
      let detail = res.data?.detail;
      if (res.data instanceof Blob) {
        try { detail = JSON.parse(await res.data.text())?.detail; } catch (_e) { detail = null; }
      }
      if (detail && typeof detail === 'object' && ['PLAN_FEATURE_DISABLED', 'PLAN_QUOTA_REACHED'].includes(detail.code)) {
        window.dispatchEvent(new CustomEvent('fidclic:plan-locked', { detail }));
        // Pages show `detail` as text: hand them the sentence, keep the rest aside.
        error.response.data = { detail: detail.message || 'Fonctionnalité non incluse dans votre offre.', plan: detail };
      }
    }
    // Every page shows `detail` as text. A validation error (422) is a list of
    // objects, and any other object would crash the page that renders it
    // (React #31 — QA F01: « Enregistrer ce filtre » replaced the whole Clients
    // page with the error screen; ~140 places render `detail` this way). One
    // sentence, here, for all of them.
    const d = error?.response?.data;
    if (d && typeof d === 'object' && !(d instanceof Blob) && d.detail && typeof d.detail !== 'string') {
      const det = d.detail;
      let text;
      if (Array.isArray(det)) {
        const fields = [...new Set(det.map((x) => (x?.loc || []).filter((k) => k !== 'body' && typeof k === 'string').join(' › ')).filter(Boolean))];
        text = fields.length ? `Données invalides : ${fields.join(', ')}.` : 'Données invalides.';
      } else {
        text = det.message || det.msg || 'La demande a été refusée.';
      }
      error.response.data = { ...d, detail: text, detail_raw: det };
    }
  } catch (_e) { /* never break the caller */ }
  return Promise.reject(error);
});

export const authAPI = {
  login: (data) => api.post('/auth/login', data),
  login2fa: (challenge, code) => api.post('/auth/login/2fa', { challenge, code }),
  register: (data) => api.post('/auth/register', data),
  // Live sign-up check: format, typo, throwaway, domain (services/email_check.py).
  checkEmail: (email) => api.get('/auth/check-email', { params: { email } }),
  logout: () => api.post('/auth/logout'),
  me: () => api.get('/auth/me'),
  // Social login — the browser gets a signed ID token from Google / Apple
  // and posts it here; the backend verifies it and issues the same session.
  oauthConfig: () => api.get('/auth/oauth/config'),
  oauthGoogle: (payload) => api.post('/auth/oauth/google', payload),   // { access_token } or { credential }
  oauthApple: (payload) => api.post('/auth/oauth/apple', payload),
};

// Self-serve onboarding step 2 (company details). See features/onboarding.py.
export const onboardingAPI = {
  cardTemplate: () => api.get('/owner/card-template'),
  saveCardTemplate: (data) => api.post('/owner/card-template', data),
  status: () => api.get('/onboarding/status'),
  company: (data) => api.post('/onboarding/company', data),
  // Step 3: the plans shown side by side, then « Commencer l'essai ».
  plans: () => api.get('/public/plans'),
  startTrial: () => api.post('/onboarding/start-trial'),
  // Step 1 bis: a code by e-mail or SMS (features/signup_verify.py).
  verifyState: () => api.get('/onboarding/verify'),
  verifySend: (channel) => api.post('/onboarding/verify/send', { channel }),
  verifyCheck: (code) => api.post('/onboarding/verify/check', { code }),
  // « Modifier l'adresse e-mail » while the code is awaited (QA BUG-001)
  verifyEmail: (email) => api.post('/onboarding/verify/email', { email }),
  // Step 2: suggestions inside the selected country (services/addresses.py).
  addressSearch: (params) => api.get('/onboarding/address-search', { params }),
};

// CRM de prospection — FidClic's own sales (super admin + commercials).
export const crmAPI = {
  meta: () => api.get('/crm/meta'),
  overview: (params) => api.get('/crm/overview', { params }),
  prospects: (params) => api.get('/crm/prospects', { params }),
  prospect: (id) => api.get(`/crm/prospects/${id}`),
  addProspect: (body) => api.post('/crm/prospects', body),
  editProspect: (id, body) => api.put(`/crm/prospects/${id}`, body),
  setStage: (id, stage, lost_reason) => api.post(`/crm/prospects/${id}/stage`, { stage, lost_reason }),
  addNote: (id, text) => api.post(`/crm/prospects/${id}/notes`, { text }),
  deleteProspect: (id) => api.delete(`/crm/prospects/${id}`),
  tasks: (params) => api.get('/crm/tasks', { params }),
  addTask: (body) => api.post('/crm/tasks', body),
  editTask: (id, body) => api.put(`/crm/tasks/${id}`, body),
  deleteTask: (id) => api.delete(`/crm/tasks/${id}`),
  importPreview: (file) => { const f = new FormData(); f.append('file', file); return api.post('/crm/import/preview', f, { headers: { 'Content-Type': 'multipart/form-data' } }); },
  importCommit: (body) => api.post('/crm/import/commit', body),
  exportCsv: (params) => api.get('/crm/export', { params, responseType: 'blob' }),
  pilotage: (params) => api.get('/crm/pilotage', { params }),
  pilotageList: (key) => api.get(`/crm/pilotage/attention/${key}`),
  setGoal: (target) => api.put('/crm/goal', { target }),
  team: () => api.get('/crm/team'),
  addMember: (body) => api.post('/crm/team', body),
  memberStatus: (email, active) => api.post(`/crm/team/${encodeURIComponent(email)}/status`, { active }),
  pipeline: (params) => api.get('/crm/pipeline', { params }),
  tasksSummary: () => api.get('/crm/tasks/summary'),
  addTaskTemplate: (body) => api.post('/crm/tasks/templates', body),
  deleteTaskTemplate: (id) => api.delete(`/crm/tasks/templates/${id}`),
  calendar: (params) => api.get('/crm/calendar', { params }),
  calls: (params) => api.get('/crm/calls', { params }),
  callsSummary: () => api.get('/crm/calls/summary'),
  call: (id) => api.get(`/crm/calls/${id}`),
  addCall: (body) => api.post('/crm/calls', body),
  editCall: (id, body) => api.put(`/crm/calls/${id}`, body),
  deleteCall: (id) => api.delete(`/crm/calls/${id}`),
  uploadRecording: (id, file) => { const f = new FormData(); f.append('file', file); return api.post(`/crm/calls/${id}/recording`, f, { headers: { 'Content-Type': 'multipart/form-data' } }); },
  recording: (id) => api.get(`/crm/calls/${id}/recording`, { responseType: 'blob' }),
  deleteRecording: (id) => api.delete(`/crm/calls/${id}/recording`),
  callsImportPreview: (file) => { const f = new FormData(); f.append('file', file); return api.post('/crm/calls/import/preview', f, { headers: { 'Content-Type': 'multipart/form-data' } }); },
  callsImportCommit: (rows) => api.post('/crm/calls/import/commit', { rows }),
  exportCalls: (params) => api.get('/crm/calls/export/csv', { params, responseType: 'blob' }),
  emailStatus: () => api.get('/crm/email/status'),
  emailTest: (to) => api.post('/crm/email/test', { to }),
  emailPreview: (body) => api.post('/crm/email/preview', body),
  emailSend: (body) => api.post('/crm/email/send', body),
  emailTemplates: (params) => api.get('/crm/email/templates', { params }),
  addEmailTemplate: (body) => api.post('/crm/email/templates', body),
  editEmailTemplate: (id, body) => api.put(`/crm/email/templates/${id}`, body),
  deleteEmailTemplate: (id) => api.delete(`/crm/email/templates/${id}`),
  sequences: (params) => api.get('/crm/sequences', { params }),
  sequencesSummary: () => api.get('/crm/sequences/summary'),
  sequence: (id) => api.get(`/crm/sequences/${id}`),
  addSequence: (body) => api.post('/crm/sequences', body),
  editSequence: (id, body) => api.put(`/crm/sequences/${id}`, body),
  sequenceStatus: (id, status) => api.post(`/crm/sequences/${id}/status`, { status }),
  duplicateSequence: (id) => api.post(`/crm/sequences/${id}/duplicate`),
  deleteSequence: (id) => api.delete(`/crm/sequences/${id}`),
  enroll: (id, body) => api.post(`/crm/sequences/${id}/enroll`, body),
  stopEnrollment: (id, eid) => api.post(`/crm/sequences/${id}/enrollments/${eid}/stop`),
  runSequences: () => api.post('/crm/sequences/run'),
};

// Super admin › Sécurité — FidClic's own team, roles, logins, journal.
const resetQs = (include_crm, keep) => {
  const q = new URLSearchParams({ include_crm: String(include_crm) });
  keep.forEach((e) => q.append('keep', e));
  return q.toString();
};

export const securityAPI = {
  // Remise à zéro (features/platform_reset.py) — super admin only, three gates.
  // keep=a&keep=b (FastAPI's list form, not axios' keep[]=)
  resetPreview: (include_crm, keep = []) => api.get(`/admin/reset/preview?${resetQs(include_crm, keep)}`),
  resetBackup: (include_crm, keep = []) => api.get(`/admin/reset/backup?${resetQs(include_crm, keep)}`, { responseType: 'blob' }),
  reset: (body) => api.post('/admin/reset', body),
  overview: (params) => api.get('/admin/security/overview', { params }),
  users: (params) => api.get('/admin/security/users', { params }),
  addUser: (body) => api.post('/admin/security/users', body),
  editUser: (email, body) => api.put(`/admin/security/users/${encodeURIComponent(email)}`, body),
  resetPassword: (email) => api.post(`/admin/security/users/${encodeURIComponent(email)}/reset-password`),
  unlock: (email) => api.post(`/admin/security/users/${encodeURIComponent(email)}/unlock`),
  roles: () => api.get('/admin/security/roles'),
  addRole: (body) => api.post('/admin/security/roles', body),
  editRole: (id, body) => api.put(`/admin/security/roles/${id}`, body),
  deleteRole: (id) => api.delete(`/admin/security/roles/${id}`),
  assignRole: (id, emails) => api.post(`/admin/security/roles/${id}/assign`, { emails }),
  logins: (params) => api.get('/admin/security/logins', { params }),
  journal: (params) => api.get('/admin/security/journal', { params }),
  journalExport: (params) => api.get('/admin/security/journal/export', { params, responseType: 'blob' }),
  settings: () => api.get('/admin/security/settings'),
  saveSettings: (body) => api.put('/admin/security/settings', body),
  alerts: () => api.get('/admin/security/alerts'),
};

// Super admin › Suivi d'équipe — FidClic's team tasks (features/team_tasks.py).
export const teamAPI = {
  board: (week) => api.get('/admin/equipe/board', { params: week ? { week } : {} }),
  create: (body) => api.post('/admin/equipe/tasks', body),
  task: (id) => api.get(`/admin/equipe/tasks/${id}`),
  edit: (id, body) => api.put(`/admin/equipe/tasks/${id}`, body),
  complete: (id, done) => api.post(`/admin/equipe/tasks/${id}/complete`, { done }),
  remove: (id, scope = 'this') => api.delete(`/admin/equipe/tasks/${id}`, { params: { scope } }),
  stopSeries: (id) => api.post(`/admin/equipe/tasks/${id}/stop-series`),
  comment: (id, text) => api.post(`/admin/equipe/tasks/${id}/comments`, { text }),
  deleteComment: (cid) => api.delete(`/admin/equipe/comments/${cid}`),
  history: (params) => api.get('/admin/equipe/history', { params }),
  historyExport: (params) => api.get('/admin/equipe/history/export', { params, responseType: 'blob' }),
  candidates: () => api.get('/admin/equipe/members/candidates'),
  addMember: (body) => api.post('/admin/equipe/members', body),
  editMember: (email, body) => api.put(`/admin/equipe/members/${encodeURIComponent(email)}`, body),
  memberUsage: (email) => api.get(`/admin/equipe/members/${encodeURIComponent(email)}/usage`),
  // « Retirer de l'équipe »: their open tasks handed over (to, moves)
  removeMember: (email, body) => api.post(`/admin/equipe/members/${encodeURIComponent(email)}/remove`, body),
  orderMembers: (ids) => api.put('/admin/equipe/members/order', { ids }),
  breakdown: (email, params) => api.get(`/admin/equipe/members/${encodeURIComponent(email)}/breakdown`, { params }),
  // the team's own lists — kind: 'types' | 'priorities' | 'fonctions'
  listAdd: (kind, body) => api.post(`/admin/equipe/lists/${kind}`, body),
  listEdit: (kind, id, body) => api.put(`/admin/equipe/lists/${kind}/${id}`, body),
  listOrder: (kind, ids) => api.put(`/admin/equipe/lists/${kind}/order`, { ids }),
  listUsage: (kind, id) => api.get(`/admin/equipe/lists/${kind}/${id}/usage`),
  listDelete: (kind, id, body) => api.post(`/admin/equipe/lists/${kind}/${id}/delete`, body),
  alerts: () => api.get('/admin/equipe/alerts'),
};

// Super admin › Centre de support, and the merchant's « Mes demandes »
// (features/support_center.py).
const upload = (url, file, onProgress) => { const f = new FormData(); f.append('file', file); return api.post(url, f, { headers: { 'Content-Type': 'multipart/form-data' }, onUploadProgress: onProgress }); };
export const supportAPI = {
  overview: () => api.get('/admin/support/overview'),
  badge: () => api.get('/admin/support/badge'),
  tickets: (params) => api.get('/admin/support/tickets', { params }),
  ticket: (id) => api.get(`/admin/support/tickets/${id}`),
  create: (body) => api.post('/admin/support/tickets', body),
  send: (id, body) => api.post(`/admin/support/tickets/${id}/messages`, body),
  patch: (id, body) => api.patch(`/admin/support/tickets/${id}`, body),
  bulk: (body) => api.post('/admin/support/tickets/bulk', body),
  unread: (id) => api.post(`/admin/support/tickets/${id}/unread`),
  exportTickets: (params) => api.get('/admin/support/export', { params, responseType: 'blob' }),
  exportThread: (id) => api.get(`/admin/support/tickets/${id}/export`, { responseType: 'blob' }),
  replies: () => api.get('/admin/support/replies'),
  addReply: (body) => api.post('/admin/support/replies', body),
  editReply: (id, body) => api.put(`/admin/support/replies/${id}`, body),
  deleteReply: (id) => api.delete(`/admin/support/replies/${id}`),
  tags: () => api.get('/admin/support/tags'),
  saveTags: (body) => api.put('/admin/support/tags', body),
  commerces: (q) => api.get('/admin/support/commerces', { params: { q } }),
  alerts: () => api.get('/admin/support/alerts'),
  upload: (file, onProgress) => upload('/admin/support/files', file, onProgress),
  file: (id, inline) => api.get(`/support/files/${id}`, { params: inline ? { inline: 1 } : {}, responseType: 'blob' }),
};
export const mySupportAPI = {
  tickets: () => api.get('/owner/support/tickets'),
  ticket: (id) => api.get(`/owner/support/tickets/${id}`),
  create: (body) => api.post('/owner/support/tickets', body),
  send: (id, body) => api.post(`/owner/support/tickets/${id}/messages`, body),
  rate: (id, body) => api.post(`/owner/support/tickets/${id}/rating`, body),
  alerts: () => api.get('/owner/support/alerts'),
  unread: () => api.get('/owner/support/unread'),
  upload: (file, onProgress) => upload('/owner/support/files', file, onProgress),
  file: (id, inline) => api.get(`/support/files/${id}`, { params: inline ? { inline: 1 } : {}, responseType: 'blob' }),
};

export const adminAPI = {
  // Facturation — the issuer of FidClic's invoices, and every invoice issued.
  franchise: () => api.get('/admin/franchise'),
  dashboard: (params) => api.get('/admin/dashboard', { params }),
  commerces: (params) => api.get('/admin/commerces', { params }),
  commercesExport: (params) => api.get('/admin/commerces/export', { params, responseType: 'blob' }),
  commercesRules: (body) => api.put('/admin/commerces/rules', body),
  addCommerce: (body) => api.post('/admin/commerces', body),
  commerce: (id) => api.get(`/admin/commerces/${id}`),
  editCommerce: (id, body) => api.put(`/admin/commerces/${id}`, body),
  commerceClients: (id, params) => api.get(`/admin/commerces/${id}/clients`, { params }),
  commerceDetails: (id) => api.get(`/admin/commerces/${id}/details`),
  commerceZone: (id) => api.get(`/admin/commerces/${id}/zone`),
  commercePlan: (id, plan) => api.post(`/admin/commerces/${id}/plan`, { plan }),
  suspendCommerce: (id, reason) => api.post(`/admin/commerces/${id}/suspend`, { reason }),
  reactivateCommerce: (id) => api.post(`/admin/commerces/${id}/reactivate`),
  resilierCommerce: (id, body) => api.post(`/admin/commerces/${id}/resilier`, body),
  annulerResiliation: (id) => api.post(`/admin/commerces/${id}/annuler-resiliation`),
  dashboardList: (key, params) => api.get(`/admin/dashboard/list/${key}`, { params }),
  dashboardToday: () => api.get('/admin/dashboard/today'),
  deepCohorts: (params) => api.get('/admin/analytics/deep/cohorts', { params }),
  deepBenchmarks: () => api.get('/admin/analytics/deep/benchmarks'),
  deepAdoption: () => api.get('/admin/analytics/deep/adoption'),
  deepPlanMoves: (params) => api.get('/admin/analytics/deep/plan-moves', { params }),
  deepGrowth: (params) => api.get('/admin/analytics/deep/growth', { params }),
  deepMap: () => api.get('/admin/analytics/deep/map'),
  viewAs: (id) => api.post(`/admin/commerces/${id}/view-as`),
  setFranchise: (id, body) => api.put(`/admin/tenants/${id}/franchise`, body),
  invoicingIssuer: () => api.get('/admin/invoicing/issuer'),
  saveInvoicingIssuer: (body) => api.put('/admin/invoicing/issuer', body),
  invoices: () => api.get('/admin/invoicing/invoices'),
  invoicePdf: (id) => api.get(`/admin/invoicing/invoices/${id}/pdf`, { responseType: 'blob' }),
  getTenants: () => api.get('/admin/tenants'),
  createTenant: (data) => api.post('/admin/tenants', data),
  updateTenant: (id, data) => api.put('/admin/tenants/' + id, data),
  deleteTenant: (id) => api.delete('/admin/tenants/' + id),
  getTenantDetails: (id) => api.get('/admin/tenants/' + id + '/details'),
  updateTenantGeo: (id, data) => api.put('/admin/tenants/' + id + '/geo', data),
  getAnalytics: () => api.get('/admin/analytics'),
  getDetailedAnalytics: () => api.get('/admin/detailed-analytics'),
  getEnhancedAnalytics: () => api.get('/admin/enhanced-analytics'),
  getTenantsByPlan: (plan) => api.get('/admin/tenants-by-plan/' + plan),
  getCardTemplate: (tenantId) => api.get('/admin/card-template/' + tenantId),
  saveCardTemplate: (tenantId, data) => api.post('/admin/card-template/' + tenantId, data),
  aiQuery: (data) => api.post('/admin/ai-query', data),
  sendBusinessCampaign: (data) => api.post('/admin/send-business-campaign', data),
  getTenantCustomers: (tenantId) => api.get('/admin/tenants/' + tenantId + '/customers'),
  getTenantAnalytics: (tenantId, params) => api.get('/admin/tenants/' + tenantId + '/analytics', { params }),
  getTenantsByTier: (tier) => api.get('/admin/tenants-by-tier/' + tier),
  getTenantsByAcquisition: (source) => api.get('/admin/tenants-by-acquisition/' + source),
  getTenantsByGeo: (enabled) => api.get('/admin/tenants-by-geo/' + (enabled ? 'enabled' : 'disabled')),
  getTenantsByMonth: (iso) => api.get('/admin/tenants-by-month/' + iso),
  getInsights: () => api.get('/admin/insights'),
  insightsBoard: (params) => api.get('/admin/insights/board', { params }),
  analyticsGlobal: (params) => api.get('/admin/analytics/global', { params }),
  aiPage: () => api.get('/admin/ai/page'),
  aiAsk: (question, params) => api.post('/admin/ai/ask', { question }, { params }),
  aiAnalysis: (key, params) => api.get(`/admin/ai/analysis/${key}`, { params }),
  aiExport: (key, params) => api.get(`/admin/ai/export/${key}`, { params, responseType: 'blob' }),
  aiSaved: () => api.get('/admin/ai/saved'),
  aiSave: (body) => api.post('/admin/ai/saved', body),
  aiRunSaved: (id) => api.post(`/admin/ai/saved/${id}/run`),
  aiDeleteSaved: (id) => api.delete(`/admin/ai/saved/${id}`),
  aiReports: () => api.get('/admin/ai/reports'),
  aiCreateReport: (body) => api.post('/admin/ai/reports', body),
  aiEditReport: (id, body) => api.put(`/admin/ai/reports/${id}`, body),
  aiDeleteReport: (id) => api.delete(`/admin/ai/reports/${id}`),
  aiSendReport: (id) => api.post(`/admin/ai/reports/${id}/send`),
  analyticsActivity: (params) => api.get('/admin/analytics/activity', { params }),
  usageFigures: (params) => api.get('/admin/analytics/usage', { params }),
  usageCommerces: (params) => api.get('/admin/analytics/usage/commerces', { params }),
  usagePlans: () => api.get('/admin/analytics/usage/plans'),
  usageRenewals: (params) => api.get('/admin/analytics/usage/renewals', { params }),
  usageExport: (params) => api.get('/admin/analytics/usage/export', { params, responseType: 'blob' }),
  insightsExport: (params) => api.get('/admin/insights/export', { params, responseType: 'blob' }),
  insightRules: () => api.get('/admin/insights/rules'),
  saveInsightRules: (body) => api.put('/admin/insights/rules', body),
  // -- Broadcast (admin → end-customers) --
  broadcast: (data) => api.post('/admin/broadcast', data),
  broadcastPreview: (filters) => api.post('/admin/broadcast/preview', { filters }),
  listBroadcasts: () => api.get('/admin/broadcasts'),
  // -- Upgrade-plan requests inbox --
  listUpgradeRequests: () => api.get('/admin/upgrade-requests'),
  resolveUpgradeRequest: (id, status) => api.put('/admin/upgrade-requests/' + id, { status }),
  // -- Cron trigger (dev/manual) --
  triggerDailyTasks: (secret) =>
    api.post('/cron/daily-triggers' + (secret ? '?secret=' + encodeURIComponent(secret) : '')),
  // -- Reviews (super admin: global or per-tenant) --
  getReviewAnalytics: (params) => api.get('/admin/analytics/reviews', { params }),
  // -- Plan limit overrides (admin can raise/lower max_customers per plan,
  //    plus a handful of other limit fields, without redeploying) --
  listPlans: () => api.get('/admin/plans'),
  updatePlan: (plan, data) => api.put('/admin/plans/' + plan, data),
  planLimits: () => api.get('/admin/plan-limits'),
  planLimitsHistory: (limit = 50) => api.get('/admin/plan-limits/history', { params: { limit } }),
  savePlanLimits: (plan, features) => api.put(`/admin/plan-limits/${plan}`, { features }),
  savePlanMeta: (plan, body) => api.put(`/admin/plan-limits/${plan}/meta`, body),
  createPlan: (body) => api.post('/admin/plan-limits', body),
  deletePlan: (plan) => api.delete(`/admin/plan-limits/${plan}`),
  resetPlanLimits: () => api.post('/admin/plan-limits/reset'),
  savePlanLimitSettings: (body) => api.put('/admin/plan-limits/settings', body),
};

export const ownerAPI = {
  getTenant: () => api.get('/owner/tenant'),
  updateTenant: (data) => api.put('/owner/tenant', data),
  // Trial countdown + plan catalogue. BillingBanner polls this on every
  // dashboard load to render the countdown / reminder / expired states.
  getTrialStatus: () => api.get('/owner/trial-status'),
  // Self-serve plan switcher (no-Stripe fallback path). Pass plan='silver'|'gold'|'vip'.
  upgradePlan: (plan) => api.post('/owner/upgrade-plan', { plan }),
  getCustomers: (params) => api.get('/owner/customers', { params }),
  getAnalytics: (params) => api.get('/owner/analytics', { params }),
  scanVisit: (data) => api.post('/owner/scan', data),
  // whose card, its stamps, and the paper-card stamps it can still take (2026-10-10)
  scanPreview: (barcode) => api.get('/owner/scan/preview', { params: { barcode } }),
  // « Enregistrer une visite » V2 — the whole card in one answer
  // (features/scan_page): balance, palier, offers and rewards, paper card.
  scanCard: (barcode) => api.get('/owner/scan/card', { params: { barcode } }),
  scan: (data) => api.post('/owner/scan', data),
  register: (data) => api.post('/owner/register', data),
  getCardTemplate: () => api.get('/owner/card-template'),
  // The Apple Wallet pass as the server builds it, for a sample customer (features/wallet_passes.py).
  walletPreview: (body) => api.post('/owner/wallet/preview', body),
  googlePreview: (body) => api.post('/owner/wallet/google-preview', body),
  saveCardTemplate: (data) => api.post('/owner/card-template', data),
  getCampaigns: () => api.get('/owner/campaigns'),
  createCampaign: (data) => api.post('/owner/campaigns', data),
  updateCampaign: (id, data) => api.put('/owner/campaigns/' + id, data),
  sendCampaign: (id) => api.post('/owner/campaigns/' + id + '/send'),
  previewSegment: (data) => api.post('/owner/campaigns/preview-segment', data),
  // Per-customer card overrides — push a middle-band overlay to a filtered segment.
  pushCardOverride: (data) => api.post('/owner/card-overrides/push', data),
  // Apple Wallet — adoption stats + a manual "refresh everyone's pass".
  walletStats: () => api.get('/owner/wallet/stats'),
  // Carte de fidélité page — design + programme + tiers + real figures.
  cardSettings: () => api.get('/owner/card/settings'),
  saveCardSettings: (data) => api.put('/owner/card/settings', data),
  // Apple Pass Designer template as the card's design (features/pass_designer.py)
  passDesigner: () => api.get('/owner/card/pass-designer'),
  passDesignerFull: () => api.get('/owner/card/pass-designer', { params: { full: 1 } }),
  passDesignerStarter: () => api.get('/owner/card/pass-designer/starter'),
  importPassDesigner: (body) => api.put('/owner/card/pass-designer', body),
  removePassDesigner: () => api.delete('/owner/card/pass-designer'),
  cardStats: (days) => api.get('/owner/card/stats', { params: { days } }),
  saveCardRewards: (tiers) => api.put('/owner/card/rewards', tiers),
  // Bonus de bienvenue — lives on the card page (features/welcome_bonus.py).
  earnRules: () => api.get('/owner/earn-rules'),
  saveEarnRules: (rules) => api.put('/owner/earn-rules', rules),
  // Besoin d'aide ? — the FAQ knowledge base is public; the assistant and the
  // conversation history are per-merchant.
  supportKb: () => api.get('/support/kb'),
  supportAsk: (message) => api.post('/owner/support/chat', { message }),
  supportHistory: (limit = 12) => api.get('/owner/support/chat', { params: { limit } }),
  // Historique — the merged activity feed, its four figures, its filter
  // vocabulary and the CSV of exactly what is on screen.
  historyFilters: () => api.get('/owner/history/filters'),
  historyActivity: (params) => api.get('/owner/history/activity', { params }),
  historyStats: (params) => api.get('/owner/history/stats', { params }),
  historyExport: (params) => api.get('/owner/history/export', { params, responseType: 'blob' }),
  // Géolocalisation — catchment rings, travel-time bands and the communes
  // behind them, plus the same breakdown as CSV.
  geoCatchment: (params) => api.get('/owner/geo/catchment', { params }),
  geoExport: (params) => api.get('/owner/geo/export', { params, responseType: 'blob' }),
  // Parrainage — the programme's dashboard, its settings and its share links.
  referralOverview: (params) => api.get('/owner/referrals/overview', { params }),
  referralExport: (params) => api.get('/owner/referrals/export', { params, responseType: 'blob' }),
  // every parrainage of the period, 20 per page, searchable (QA R5 F25)
  referralList: (params) => api.get('/owner/referrals/list', { params }),
  saveReferralConfig: (config) => api.put('/owner/referrals/config', config),
  referralConfig: () => api.get('/owner/referrals/config'),
  // Automatisations · Push Wallet — the scenarios, their figures, and firing
  // one by hand.
  pushWalletScenarios: () => api.get('/owner/push-wallet/scenarios'),
  pushWalletStats: (params) => api.get('/owner/push-wallet/stats', { params }),
  createPushWalletScenario: (body) => api.post('/owner/push-wallet/scenarios', body),
  updatePushWalletScenario: (id, patch) => api.put(`/owner/push-wallet/scenarios/${id}`, patch),
  deletePushWalletScenario: (id) => api.delete(`/owner/push-wallet/scenarios/${id}`),
  runPushWalletScenario: (id) => api.post(`/owner/push-wallet/scenarios/${id}/run`),
  pushWalletPreview: (id) => api.get(`/owner/push-wallet/scenarios/${id}/preview`),
  // À valider — the scenarios' daily batches, waiting for an OK.
  pushWalletPending: () => api.get('/owner/push-wallet/pending'),
  approvePushWalletLot: (id) => api.post(`/owner/push-wallet/pending/${id}/approve`),
  skipPushWalletLot: (id) => api.post(`/owner/push-wallet/pending/${id}/skip`),
  // Messages automatiques — Google review after a scan, "récompense proche".
  // Automatisations — redesign 2026-10-11 (features/automations.py)
  automations: () => api.get('/owner/automations'),
  createAutomation: (body) => api.post('/owner/automations', body),
  updateAutomation: (id, body) => api.put(`/owner/automations/${encodeURIComponent(id)}`, body),
  automationStatus: (id, status) => api.post(`/owner/automations/${encodeURIComponent(id)}/status`, { status }),
  duplicateAutomation: (id) => api.post(`/owner/automations/${encodeURIComponent(id)}/duplicate`),
  deleteAutomation: (id) => api.delete(`/owner/automations/${encodeURIComponent(id)}`),
  automationPreview: (body) => api.post('/owner/automations/preview', body),
  automationAiDraft: (objective) => api.post('/owner/automations/ai-draft', { objective }),
  automationGeoZone: () => api.get('/owner/automations/geo/zone'),
  // Nouvelle automatisation (2026-10-11): « Adresse ou établissement », the till's « Offre utilisée »
  automationAddress: (q) => api.get('/owner/automations/address-search', { params: { q } }),
  useOffer: (campaignId, body) => api.post(`/owner/offers/${encodeURIComponent(campaignId)}/use`, body),
  autoMessages: () => api.get('/owner/auto-messages'),
  saveAutoMessages: (body) => api.put('/owner/auto-messages', body),
  // Paramètres › Établissement
  etablissement: () => api.get('/owner/etablissement'),
  saveEtablissement: (body) => api.put('/owner/etablissement', body),
  geocodeEtablissement: (body) => api.post('/owner/etablissement/geocode', body),
  addStore: (body) => api.post('/owner/etablissement/stores', body),
  editStore: (id, body) => api.put(`/owner/etablissement/stores/${id}`, body),
  businessHours: () => api.get('/owner/settings/hours'),
  saveWeeklyHours: (weekly) => api.put('/owner/settings/hours/weekly', { weekly_schedule: weekly }),
  saveHolidayClosures: (closures) => api.put('/owner/settings/hours/holidays', { holiday_closures: closures }),
  saveAnnualClosures: (annual) => api.put('/owner/settings/hours/annual', { annual_closures: annual }),
  // Paramètres › Notifications — usage, plan limits, the business's sending rules.
  notificationsOverview: (period) => api.get('/owner/notifications/overview', { params: { period } }),
  saveSendRules: (rules) => api.put('/owner/notifications/rules', rules),
  // Paramètres › Abonnement & facturation
  billingOverview: () => api.get('/owner/billing/overview'),
  invoices: () => api.get('/owner/invoices'),
  invoicePdf: (id) => api.get(`/owner/invoices/${id}/pdf`, { responseType: 'blob' }),
  billingCheckout: (plan) => api.post('/billing/checkout', { plan, success_path: '/dashboard/parametres/abonnement?billing=success', cancel_path: '/dashboard/parametres/abonnement?billing=cancelled' }),
  billingPortal: () => api.post('/billing/portal', { return_path: '/dashboard/parametres/abonnement' }),
  cancelSubscription: (reason) => api.post('/owner/billing/cancel', { reason }),
  resumeSubscription: () => api.post('/owner/billing/resume'),
  // Paramètres › Données & confidentialité
  privacy: () => api.get('/owner/privacy'),
  savePrivacy: (body) => api.put('/owner/privacy', body),
  exportPrivacy: (body) => api.post('/owner/privacy/export', body, { responseType: 'blob' }),
  searchPrivacy: (q) => api.get('/owner/privacy/search', { params: { q } }),
  eraseCustomer: (id) => api.delete(`/owner/privacy/customers/${id}`, { params: { confirm: true } }),
  // Paramètres › Sécurité
  security: () => api.get('/security/overview'),
  securityActivity: () => api.get('/security/activity'),
  changePassword: (current, next) => api.post('/security/password', { current, new: next }),
  totpSetup: () => api.post('/security/2fa/setup'),
  totpEnable: (code) => api.post('/security/2fa/enable', { code }),
  totpDisable: (password, code) => api.post('/security/2fa/disable', { password, code }),
  endSession: (sid) => api.delete(`/security/sessions/${sid}`),
  endOtherSessions: () => api.post('/security/sessions/revoke-others'),
  // « Cet appareil est la caisse » — marks THIS session, nothing else
  markCaisse: (store_id) => api.post('/security/caisse', { store_id }),
  unmarkCaisse: () => api.delete('/security/caisse'),
  // « Code de la caisse » — off by default; a lock on the counter, not a login
  setCaisseCode: (body) => api.put('/security/caisse/code', body),
  unlockCaisse: (code) => api.post('/security/caisse/unlock', { code }),
  // Sécurité › changer l'adresse e-mail du compte (features/account_email)
  emailState: () => api.get('/security/email'),
  emailStart: (new_email, password, method) => api.post('/security/email/start', { new_email, password, method }),
  emailConfirm: (proof) => api.post('/security/email/confirm', proof),
  emailCancel: () => api.post('/security/email/cancel'),
  deleteAccount: (password, confirm) => api.post('/security/account/delete', { password, confirm }),
  restoreAccount: () => api.post('/security/account/restore'),
  resetTeamPassword: (uid) => api.post(`/owner/team-access/users/${uid}/password`),
  // Paramètres › Préférences
  preferences: () => api.get('/me/preferences'),
  savePreferences: (body) => api.put('/me/preferences', body),
  resetPreferences: () => api.post('/me/preferences/reset'),
  // Analyses — one tab per request, and the overview as a CSV.
  analyses: (params) => api.get('/owner/analyses', { params }),
  analysesExport: (params) => api.get('/owner/analyses/export', { params, responseType: 'blob' }),
  // Tableau de bord — the home page's eleven panels, and the monthly goal.
  homeOverview: (params) => api.get('/owner/home/overview', { params }),
  planAccess: () => api.get('/owner/plan-access'),
  integrations: () => api.get('/owner/integrations'),
  createApiKey: (body) => api.post('/owner/integrations/keys', body),
  revokeApiKey: (id) => api.delete(`/owner/integrations/keys/${id}`),
  createWebhook: (body) => api.post('/owner/integrations/webhooks', body),
  editWebhook: (id, body) => api.put(`/owner/integrations/webhooks/${id}`, body),
  deleteWebhook: (id) => api.delete(`/owner/integrations/webhooks/${id}`),
  testWebhook: (id) => api.post(`/owner/integrations/webhooks/${id}/test`),
  resendDelivery: (id) => api.post(`/owner/integrations/deliveries/${id}/resend`),
  limitAlerts: () => api.get('/owner/limit-alerts'),
  getHomeGoal: () => api.get('/owner/home/goal'),
  setHomeGoal: (body) => api.put('/owner/home/goal', body),
  // Clients — the page's four figures, its segments and its paginated table.
  clientsOverview: () => api.get('/owner/clients/overview'),
  clientsList: (params) => api.get('/owner/clients/list', { params }),
  clientsExport: (params) => api.get('/owner/clients/export', { params, responseType: 'blob' }),
  // Every client the current filter matches — ids only, so a message goes to
  // the whole filter rather than to the page that happens to be on screen.
  clientIds: (params) => api.get('/owner/clients/ids', { params }),
  // Clients › Importer + invitation emails (features/client_import.py).
  clientsImportPreview: (file) => {
    const fd = new FormData();
    fd.append('file', file);
    return api.post('/owner/clients/import/preview', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  clientsImportCommit: (body) => api.post('/owner/clients/import/commit', body),
  clientInvitations: () => api.get('/owner/clients/invitations'),
  clientRelanceList: () => api.get('/owner/clients/invitations/relance'),
  clientRelanceSend: (customer_ids) => api.post('/owner/clients/invitations/relance', { customer_ids }),
  // « Déjà contactés » before a campaign (features/resend_guard.py).
  campaignRecentCheck: (body) => api.post('/owner/campaigns/recent-check', body),
  sendCampaignToGroup: (body) => api.post('/owner/campaigns/send-to-group', body),
  // Campagnes — the page in one call, the composer in one call.
  campaignsPage: () => api.get('/owner/campaigns/page'),
  // Campagnes redesign (2026-10-10): the list's tabs and the wizard's live audience
  campaignDetail: (id) => api.get(`/owner/campaigns/${encodeURIComponent(id)}/detail`),
  campaignsList: (params) => api.get('/owner/campaigns/list', { params }),
  campaignAudiencePreview: (body) => api.post('/owner/campaigns/audience-preview', body),
  redeemDefiReward: (id) => api.post(`/owner/defis/rewards/${id}/redeem`),
  // « Ce qui marche chez vous » (features/campaign_learning.py).
  campaignLearning: () => api.get('/owner/campaigns/learning'),
  campaignResult: (id) => api.get(`/owner/campaigns/${id}/result`),
  campaignTips: (body) => api.post('/owner/campaigns/learning/tips', body),
  // Autopilot — daily + weekly campaigns for the owner's OK (features/autopilot.py).
  autopilot: () => api.get('/owner/autopilot'),
  saveAutopilot: (body) => api.put('/owner/autopilot', body),
  autopilotPrepare: () => api.post('/owner/autopilot/prepare'),
  autopilotApprove: (id, body) => api.post(`/owner/autopilot/${id}/approve`, body || {}),
  autopilotSkip: (id) => api.post(`/owner/autopilot/${id}/skip`),
  copilotPreparePlan: () => api.post('/owner/copilot/plan/prepare'),
  // Rapport mensuel des campagnes (features/campaign_report.py).
  campaignReports: () => api.get('/owner/campaign-reports'),
  campaignReport: (month) => api.get(`/owner/campaign-reports/${month}`),
  saveCampaignReportSettings: (body) => api.put('/owner/campaign-reports/settings', body),
  generateCampaignReport: (body) => api.post('/owner/campaign-reports/generate', body || {}),
  composeCampaign: (body) => api.post('/owner/campaigns/compose', body),
  // Clients › « Modifier la fiche » / « Ajuster points / tampons » (features/customer_edit.py)
  clientFiche: (id) => api.get(`/owner/clients/${id}/fiche`),
  saveClientFiche: (id, body) => api.put(`/owner/clients/${id}/fiche`, body),
  // multi-store (2026-10-12): the client's home store, a store's link
  setHomeStore: (id, branchId) => api.put(`/owner/customers/${encodeURIComponent(id)}/home-store`, { branch_id: branchId }),
  setStoreSlug: (branchId, slug) => api.put(`/owner/stores/${encodeURIComponent(branchId)}/slug`, { slug }),
  adjustClient: (id, body) => api.post(`/owner/clients/${id}/ajustement`, body),
  // « Reprendre » / « Supprimer » a draft (QA F02)
  campaignDraft: (id) => api.get(`/owner/campaigns/drafts/${id}`),
  deleteCampaignDraft: (id) => api.delete(`/owner/campaigns/drafts/${id}`),
  // « Annuler l'envoi » of a planned campaign: back to the drafts
  cancelCampaignSchedule: (id) => api.post(`/owner/campaigns/drafts/${id}/cancel-schedule`),
  campaignAiDraft: (body) => api.post('/owner/campaigns/ai-draft', body),
  googleWalletStatus: () => api.get('/owner/wallet/google-status'),

  // Segmentation — the page in one call, the builder counted live.
  segmentationPage: () => api.get('/owner/segmentation/page'),
  // « Objectifs et récompenses » — les paliers que le commerce se fixe
  // lui-même (features/milestones).
  milestones: () => api.get('/owner/milestones'),
  saveMilestones: (items) => api.put('/owner/milestones', { items }),
  cataloguePage: (days) => api.get('/owner/catalogue/page', { params: { days } }),
  createProduct: (body) => api.post('/owner/catalogue/products', body),
  updateProduct: (id, body) => api.put(`/owner/catalogue/products/${id}`, body),
  deleteProduct: (id) => api.delete(`/owner/catalogue/products/${id}`),
  duplicateProduct: (id) => api.post(`/owner/catalogue/products/${id}/duplicate`),
  bulkProducts: (body) => api.post('/owner/catalogue/products/bulk', body),
  importProducts: (items) => api.post('/owner/catalogue/products/import', { items }),
  setProductImage: (id, dataUrl) => api.put(`/owner/catalogue/products/${id}/image`, { data_url: dataUrl }),
  deleteProductImage: (id) => api.delete(`/owner/catalogue/products/${id}/image`),
  createCategory: (body) => api.post('/owner/catalogue/categories', body),
  updateCategory: (body) => api.put('/owner/catalogue/categories', body),
  deleteCategory: (name, moveTo) => api.delete(`/owner/catalogue/categories/${encodeURIComponent(name)}`, { params: { move_to: moveTo || '' } }),
  customerRules: () => api.get('/owner/customer-rules'),
  saveCustomerRules: (body) => api.put('/owner/customer-rules', body),
  restoreCustomerRules: () => api.post('/owner/customer-rules/restore'),
  settingsVersion: (section) => api.get(`/owner/settings-versions/${section}`),
  revertSettings: (section) => api.post(`/owner/settings-versions/${section}/revert`),
  teamAccess: () => api.get('/owner/team-access'),
  teamCreate: (body) => api.post('/owner/team-access/users', body),
  teamUpdate: (id, body) => api.put(`/owner/team-access/users/${encodeURIComponent(id)}`, body),
  teamStatus: (id, active) => api.post(`/owner/team-access/users/${encodeURIComponent(id)}/status`, { active }),
  teamPassword: (id) => api.post(`/owner/team-access/users/${encodeURIComponent(id)}/password`),
  teamDelete: (id) => api.delete(`/owner/team-access/users/${encodeURIComponent(id)}`),
  teamRoleCreate: (body) => api.post('/owner/team-access/roles', body),
  teamRoleUpdate: (key, body) => api.put(`/owner/team-access/roles/${encodeURIComponent(key)}`, body),
  teamRoleDelete: (key) => api.delete(`/owner/team-access/roles/${encodeURIComponent(key)}`),
  teamStoreAccess: (storeId, id, enabled) => api.put(`/owner/team-access/stores/${encodeURIComponent(storeId)}/users/${encodeURIComponent(id)}`, { enabled }),
  joinLink: () => api.get('/owner/join-link'),
  joinSlugCheck: (slug) => api.get('/owner/join-link/slug-check', { params: { slug } }),
  saveJoinSlug: (slug) => api.put('/owner/join-link/slug', { slug }),
  saveJoinPage: (body) => api.put('/owner/join-link/page', body),
  saveSignupImage: (image) => api.put('/owner/join-link/image', { image }),
  segmentPreview: (body) => api.post('/owner/segmentation/preview', body),
  createSegment: (body) => api.post('/owner/segmentation/segments', body),
  updateSegment: (id, body) => api.put(`/owner/segmentation/segments/${id}`, body),
  deleteSegment: (id) => api.delete(`/owner/segmentation/segments/${id}`),
  segmentClients: (id) => api.get(`/owner/segmentation/segments/${id}/clients`),

  // Insights — « Faites grandir votre commerce ».
  insightsPage: () => api.get('/owner/insights/page'),
  insightTemplate: (key, day, store) => api.get(`/owner/insights/templates/${encodeURIComponent(key)}`, {
    params: { ...(day != null && day !== '' ? { day } : {}), ...(store ? { store } : {}) },
  }),
  activateInsight: (action) => api.post(`/owner/insights/actions/${action}/activate`),
  setGoogleReview: (body) => api.put('/owner/insights/google-review', body),
  insightsExport: () => api.get('/owner/insights/export.pdf', { responseType: 'blob' }),

  // FidClic IA Copilote.
  copilotPage: (params) => api.get('/owner/copilot/page', { params }),
  copilotFeedback: (key, kind) => api.post(`/owner/copilot/recommendations/${encodeURIComponent(key)}/feedback`, { kind }),
  copilotAutopilot: (enabled) => api.put('/owner/copilot/autopilot', { enabled }),
  copilotEditPlan: (steps) => api.put('/owner/copilot/plan', { steps }),
  copilotRebuildPlan: () => api.post('/owner/copilot/plan/rebuild'),
  copilotApprove: (stepId) => api.post(`/owner/copilot/plan/steps/${stepId}/approve`),
  copilotChat: (message) => api.post('/owner/copilot/chat', { message }),
  copilotChatHistory: () => api.get('/owner/copilot/chat'),

  walletNotify: () => api.post('/owner/wallet/notify'),
  walletRefresh: () => api.post('/owner/wallet/refresh'),
  clearCardOverrideForCustomer: (customerId) => api.delete('/owner/card-overrides/customer/' + customerId),
  clearAllCardOverrides: () => api.delete('/owner/card-overrides/all'),
  getActiveCardOverrideCount: () => api.get('/owner/card-overrides/active-count'),
  aiQuery: (data) => api.post('/owner/ai-query', data),
  // New methods for dashboard
  getBranches: () => api.get('/owner/branches'),
  createBranch: (data) => api.post('/owner/branches', data),
  deleteBranch: (id) => api.delete('/owner/branches/' + id),
  getBranchPerformance: (params) => api.get('/owner/branches/performance', { params }),
  getLtvBreakdown: (params) => api.get('/owner/analytics/ltv-breakdown', { params }),
  getProactiveAlerts: (params) => api.get('/owner/insights/alerts', { params }),
  getAiSuggestions: (params) => api.get('/owner/ai/suggestions', { params }),
  getCardsFilled: (params) => api.get('/owner/analytics/cards-filled', { params }),
  getRecovered: (params) => api.get('/owner/analytics/recovered', { params }),
  getHighestPaying: (params) => api.get('/owner/analytics/highest-paying', { params }),
  getAcquisitionSources: (params) => api.get('/owner/analytics/acquisition-sources', { params }),
  getAnalyticsSummary: (params) => api.get('/owner/analytics/summary', { params }),
  // Product / service catalog. Owner edits in Settings → Catalogue.
  // Staff (and managers/owners) fetch it on the scan page to render
  // an item picker. The server is the source of truth for prices, so
  // saving a visit with `items` makes the backend recompute amount_paid
  // from the catalog — clients cannot inflate revenue by editing prices.
  getCatalog: () => api.get('/owner/catalog'),
  putCatalog: (items) => api.put('/owner/catalog', { items }),
  // Vision-LLM OCR of a menu photo. The image is sent base64-encoded
  // (with the data: prefix); server strips the prefix, calls a vision
  // model (Groq Llama-3.2-vision free → OpenRouter fallback), parses
  // the JSON the model returns and gives us [{name, price, category}].
  // The owner reviews/edits the result before saving via putCatalog.
  parseMenuFromPhoto: (imageBase64, mime, language = 'fr') =>
    api.post('/owner/catalog/parse-menu', { image_base64: imageBase64, mime, language }),
  // Single-metric endpoint — drives per-tile period pickers on dashboard/analytics.
  // params: { metric, days, branch_id? }
  getAnalyticsMetric: (params) => api.get('/owner/analytics/metric', { params }),
  // Customer cleanup (item 31) — soft-delete + restore + trash view
  purgeInactiveCustomers: (data) => api.post('/owner/customers/purge-inactive', data),
  restoreCustomer: (customerId) => api.post(`/owner/customers/${customerId}/restore`),
  getCustomerTrash: () => api.get('/owner/customers/trash'),
  // AI campaign analyzer (item 23) — returns 3 plain-English bullets
  aiAnalyzeCampaign: (campaignId) => api.post(`/owner/campaigns/${campaignId}/ai-analyze`),
  // Tenant identity — works for owner, manager, staff. Used by the sidebar
  // tenant badge so the user always knows which account they're in.
  getTenant: () => api.get('/owner/tenant'),
  // Team password reset — returns the new plaintext password ONCE so the owner can share it.
  resetTeamPassword: (email, newPassword) =>
    api.post(`/owner/team/${encodeURIComponent(email)}/reset-password`, {
      new_password: newPassword || null,
    }),
  getCustomerMap: (params) => api.post('/owner/customers/map', null, { params }),
  sendCampaignToGroup: (data) => api.post('/owner/campaigns/send-to-group', data),
  getCampaignTracking: (id) => api.get('/owner/campaigns/' + id + '/tracking'),
  // --- 12 new insight endpoints (now accept params, used to forward branch_id) ---
  getChurn: (params) => api.get('/owner/analytics/churn', { params }),
  getLTV: (params) => api.get('/owner/analytics/ltv', { params }),
  getAlerts: (params) => api.get('/owner/analytics/alerts', { params }),
  getTimeSegmentation: (params) => api.get('/owner/analytics/time-segmentation', { params }),
  getCityBreakdown: (params) => api.get('/owner/analytics/city-breakdown', { params }),
  getReactivationTemplates: (params) => api.get('/owner/campaigns/reactivation-templates', { params }),
  updateSenderName: (name) => api.put('/owner/settings/sender-name', { sender_name: name }),
  listTeam: () => api.get('/owner/team'),
  addTeamMember: (data) => api.post('/owner/team', data),
  removeTeamMember: (email) => api.delete('/owner/team/' + encodeURIComponent(email)),
  getMonthlyReport: (month) => api.get('/owner/monthly-report' + (month ? '?month=' + month : '')),
  getActiveCards: (params) => api.get('/owner/analytics/active-cards', { params }),
  trackOfferClick: (campaignId, customerId) =>
    api.post('/campaigns/' + campaignId + '/track-click' + (customerId ? '?customer_id=' + customerId : '')),
  trackPushDismiss: (campaignId) => api.post('/campaigns/' + campaignId + '/track-dismiss'),
  // -- Scheduled / triggered campaigns --
  scheduleCampaign: (data) => api.post('/owner/campaigns/schedule', data),
  listScheduled: () => api.get('/owner/campaigns/scheduled'),
  deleteScheduled: (id) => api.delete('/owner/campaigns/scheduled/' + id),
  // -- Upgrade plan request (owner side) --
  requestUpgrade: (data) => api.post('/owner/request-upgrade', data),
  // -- Modern card designer --
  savePromotion: (data, notify = false) =>
    api.post('/owner/card-template/promotion' + (notify ? '?notify=true' : ''), data),
  saveCardDetails: (data) => api.post('/owner/card-template/details', data),
  sendCardNotification: (data) => api.post('/owner/card-notifications', data),
  // -- Reward redemption (this batch) --
  redeemReward: (data) => api.post('/owner/rewards/redeem', data),
  listRedeemedRewards: (params) => api.get('/owner/rewards/redeemed', { params }),
  // -- Per-customer visit history --
  customerVisitHistory: (customerId, params) =>
    api.get('/owner/customers/' + customerId + '/visits', { params }),
  // -- Birthdays this month --
  birthdaysThisMonth: (params) =>
    api.get('/owner/analytics/birthdays-this-month', { params }),
  // -- Saved segments --
  listSavedSegments: () => api.get('/owner/segments'),
  createSavedSegment: (data) => api.post('/owner/segments', data),
  deleteSavedSegment: (id) => api.delete('/owner/segments/' + id),
  // -- Reviews & ratings --
  getReviewAnalytics: (params) => api.get('/owner/analytics/reviews', { params }),
  listReviews: (params) => api.get('/owner/reviews', { params }),
};

// Facturation électronique (French e-invoicing) — second product module.
// Backed by services.pdp_connector (Mock by default; B2Brouter via env).
export const facturationAPI = {
  // availability is ungated (returns {enabled:false} for loyalty-only tenants)
  availability: () => api.get('/owner/facturation/availability'),
  enable: (data) => api.post('/owner/facturation/enable', data || {}),
  status: () => api.get('/owner/facturation/status'),
  activate: (data) => api.post('/owner/facturation/activate', data || {}),
  listInvoices: () => api.get('/owner/facturation/invoices'),
  createInvoice: (data) => api.post('/owner/facturation/invoices', data),
  sendInvoice: (id) => api.post('/owner/facturation/invoices/' + id + '/send'),
  getInvoice: (id) => api.get('/owner/facturation/invoices/' + id),
  // S1 — the four status families move independently of each other.
  setReview: (id, data) => api.post('/owner/facturation/invoices/' + id + '/review', data),
  setPayment: (id, data) => api.post('/owner/facturation/invoices/' + id + '/payment', data),
  audit: () => api.get('/owner/facturation/audit'),
  creditNote: (id, data) => api.post('/owner/facturation/invoices/' + id + '/credit-note', data),
  listCreditNotes: () => api.get('/owner/facturation/credit-notes'),
  listReceived: () => api.get('/owner/facturation/received'),
  markReceived: (id, data) => api.post('/owner/facturation/received/' + id + '/mark', data),
  seedReceived: (data) => api.post('/owner/facturation/received/seed-test', data || {}),
  sendEreporting: (data) => api.post('/owner/facturation/ereporting', data),
  coherence: () => api.get('/owner/facturation/coherence'),
  fecUrl: (from, to) => '/api/owner/facturation/fec' + ((from||to) ? ('?from=' + (from||'') + '&to=' + (to||'')) : ''),
  // Cabinet (owner side): link/unlink my accountant.
  inviteAccountant: (email) => api.post('/owner/facturation/cabinet/invite', { email }),
  listAccountants: () => api.get('/owner/facturation/cabinet/links'),
  revokeAccountant: (email) => api.delete('/owner/facturation/cabinet/links', { data: { email } }),
};

// Cabinet multi-dossier — accountant (role "comptable") control tower.
/** S5/S7 — the cabinet as an organisation: people, roles, assignment. */
export const cabinetOsAPI = {
  signup: (data) => api.post('/cabinet/signup', data),
  me: () => api.get('/cabinet/me'),
  team: () => api.get('/cabinet/team'),
  createMember: (data) => api.post('/cabinet/team', data),
  updateMember: (id, data) => api.patch('/cabinet/team/' + id, data),
  changePassword: (data) => api.post('/cabinet/change-password', data),
  resetMemberPassword: (id) => api.post('/cabinet/team/' + id + '/reset-password'),
  assign: (tenantId, membershipId) =>
    api.post('/cabinet/dossiers/' + tenantId + '/assign', { membership_id: membershipId }),
  unassigned: () => api.get('/cabinet/dossiers/unassigned'),
  updateSettings: (data) => api.patch('/cabinet/settings', data),
  sirenLookup: (siren) => api.get('/cabinet/siren-lookup?siren=' + siren),
  createClient: (data) => api.post('/cabinet/clients', data),
  agentDraftInvoice: (tenantId, body = {}) =>
    api.post('/cabinet/dossiers/' + tenantId + '/agent/draft-invoice', body),
  docRequests: (tenantId) => api.get('/cabinet/dossiers/' + tenantId + '/doc-requests'),
  createDocRequest: (tenantId, body) =>
    api.post('/cabinet/dossiers/' + tenantId + '/doc-requests', body),
  markDocReceived: (id) => api.post('/cabinet/doc-requests/' + id + '/received'),
  runCollection: () => api.post('/cabinet/agent/collect/run'),
  subscriptions: (tenantId) => api.get('/cabinet/dossiers/' + tenantId + '/subscriptions'),
  createSubscription: (tenantId, body) =>
    api.post('/cabinet/dossiers/' + tenantId + '/subscriptions', body),
  toggleSubscription: (id, active) =>
    api.patch('/cabinet/subscriptions/' + id, { active }),
  runBilling: () => api.post('/cabinet/agent/billing/run'),
  // Chapter 4 — OCR reads a supplier invoice photo; Saisie proposes the entry.
  ocrIngest: (tenantId, body) =>
    api.post('/cabinet/dossiers/' + tenantId + '/ocr', body),
  saisieEntries: (tenantId) => api.get('/cabinet/dossiers/' + tenantId + '/saisie'),
  runSaisie: (tenantId) => api.post('/cabinet/dossiers/' + tenantId + '/saisie/run'),
  validateSaisie: (entryId) => api.post('/cabinet/saisie/' + entryId + '/validate'),
  // Chapter 8 — La Mémoire (dossier notes) + Le Conseiller (advisory opportunities).
  memoire: (tenantId) => api.get('/cabinet/dossiers/' + tenantId + '/memoire'),
  addMemoire: (tenantId, body) =>
    api.post('/cabinet/dossiers/' + tenantId + '/memoire', body),
  runConseiller: (tenantId) =>
    api.post('/cabinet/dossiers/' + tenantId + '/conseiller/run'),
  conseils: (tenantId) => api.get('/cabinet/dossiers/' + tenantId + '/conseils'),
  dismissConseil: (id) => api.post('/cabinet/conseils/' + id + '/dismiss'),
  // TVA/CA3 — draft VAT declaration from validated sales + accepted purchases.
  runTva: (tenantId, body) =>
    api.post('/cabinet/dossiers/' + tenantId + '/tva/run', body || {}),
  tvaDeclarations: (tenantId) => api.get('/cabinet/dossiers/' + tenantId + '/tva'),
  // Le Lettrage — bank reconciliation (agent proposes, human validates).
  seedBankTx: (tenantId, body) =>
    api.post('/cabinet/dossiers/' + tenantId + '/bank-transactions/seed-test', body),
  runLettrage: (tenantId) => api.post('/cabinet/dossiers/' + tenantId + '/lettrage/run'),
  lettrageMatches: (tenantId) => api.get('/cabinet/dossiers/' + tenantId + '/lettrage'),
  validateLettrage: (id) => api.post('/cabinet/lettrage/' + id + '/validate'),
  // Le Gardien — anomaly findings.
  runGardien: (tenantId) => api.post('/cabinet/dossiers/' + tenantId + '/gardien/run'),
  gardienFindings: (tenantId) => api.get('/cabinet/dossiers/' + tenantId + '/gardien'),
  resolveGardien: (id) => api.post('/cabinet/gardien/' + id + '/resolve'),
  // Le Réviseur — pre-validation review report.
  runRevision: (tenantId) => api.post('/cabinet/dossiers/' + tenantId + '/revision/run'),
  revisionReports: (tenantId) => api.get('/cabinet/dossiers/' + tenantId + '/revision'),
  // Multi-PA (Model B) — each client can be on its own Plateforme Agréée.
  paProviders: () => api.get('/facturation/pa-providers'),
  setDossierPa: (tenantId, provider) =>
    api.post('/owner/facturation/set-pa', { tenant_id: tenantId, pdp_provider: provider }),
  // Imports — clients (CSV), invoices (CSV/FEC), bank (CSV/OFX) + reception pull.
  importClients: (content) => api.post('/cabinet/import/clients', { content }),
  importInvoices: (tenantId, content, format) =>
    api.post('/cabinet/dossiers/' + tenantId + '/import/invoices', { content, format }),
  importBank: (tenantId, content, format) =>
    api.post('/cabinet/dossiers/' + tenantId + '/import/bank', { content, format }),
  syncReceived: (tenantId) =>
    api.post('/owner/facturation/received/sync', { tenant_id: tenantId }),
  importInvoicesXlsx: (tenantId, contentB64) =>
    api.post('/cabinet/dossiers/' + tenantId + '/import/invoices',
             { content_b64: contentB64, format: 'xlsx' }),
  importEinvoiceXml: (tenantId, content) =>
    api.post('/cabinet/dossiers/' + tenantId + '/import/einvoice', { content }),
  // Coefficients sectoriels — la reconstitution simulée.
  learnCoefficients: () => api.post('/cabinet/coefficients/learn'),
  coefficients: () => api.get('/cabinet/coefficients'),
  // OCR d'une facture de VENTE (papier émise par le client) → fact_invoices.
  ocrVente: (tenantId, imageDataUrl) =>
    api.post('/cabinet/dossiers/' + tenantId + '/ocr-vente', { image: imageDataUrl }),
};

/** S9 — grille de répartition: who does what on each dossier. */
export const grilleAPI = {
  get: (tenantId) => api.get('/cabinet/dossiers/' + tenantId + '/grille'),
  set: (tenantId, body) => api.post('/cabinet/dossiers/' + tenantId + '/grille', body),
};

/** S4 — Exception Centre: failures as owned, dated work items. */
export const casesAPI = {
  list: (params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
    ).toString();
    return api.get('/cabinet/cases' + (q ? '?' + q : ''));
  },
  assign: (id, membershipId) =>
    api.post('/cabinet/cases/' + id + '/assign', { membership_id: membershipId }),
  setStatus: (id, status, note) =>
    api.post('/cabinet/cases/' + id + '/status', { status, note }),
};

export const cabinetExtraAPI = {
  // S2 — "kaun kya kar raha hai" (self-updating: working IS reporting)
  audit: (tenantId) => api.get('/comptable/audit' + (tenantId ? '?tenant_id=' + tenantId : '')),
  activity: (days = 7) => api.get('/comptable/activity-summary?days=' + days),

  // Acting FOR a client: the same facturation endpoints, with tenant_id naming
  // the dossier. The server verifies the mandate and records "on behalf of".
  createInvoiceFor: (tenantId, data) =>
    api.post('/owner/facturation/invoices', { ...data, tenant_id: tenantId }),
  ereportingFor: (tenantId, data) =>
    api.post('/owner/facturation/ereporting', { ...data, tenant_id: tenantId }),
  activateFor: (tenantId, data) =>
    api.post('/owner/facturation/activate', { ...(data || {}), tenant_id: tenantId }),
  seedReceivedFor: (tenantId, data) =>
    api.post('/owner/facturation/received/seed-test', { ...(data || {}), tenant_id: tenantId }),
};

export const comptableAPI = {
  clients: () => api.get('/comptable/clients'),
  client: (tenantId) => api.get('/comptable/clients/' + tenantId),
  alerts: () => api.get('/comptable/alerts'),
  reviewQueue: () => api.get('/comptable/review-queue'),
  fec: (tenantId, from, to) => api.get('/cabinet/dossiers/' + tenantId + '/fec' + ((from||to) ? ('?from=' + (from||'') + '&to=' + (to||'')) : ''), { responseType: 'text' }),
  exportUrl: '/api/comptable/export',
};

export const publicAPI = {
  getJoinInfo: (slug, store) => api.get('/join/' + slug, { params: store ? { store } : {} }),
  joinProgram: (slug, data) => api.post('/join/' + slug, data),
  // -- Real-time proximity push (wallet card calls this with device GPS) --
  proximityPing: (data) => api.post('/public/proximity-ping', data),
  // -- Customer review submission (wallet card → rate-your-visit panel) --
  submitReview: (data) => api.post('/public/reviews', data),
  googleReviewClick: (barcode) => api.post(`/card/${barcode}/google-review-click`),
  // -- Signup page: its words (Paramètres › Lien d'inscription) and one visit --
  joinPage: (slug, store) => api.get(`/join/${slug}/page`, { params: store ? { store } : {} }),
  joinView: (slug, body) => api.post(`/join/${slug}/view`, body),
};

export default api;
