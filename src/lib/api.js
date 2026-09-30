import axios from 'axios';

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

api.interceptors.request.use((config) => {
  try {
    const t = localStorage.getItem(TOKEN_KEY);
    if (t) {
      config.headers = config.headers || {};
      config.headers.Authorization = `Bearer ${t}`;
    }
    // The establishment chosen under the logo (BranchContext). The server
    // decides what the caller may actually see — see features/store_scope.py.
    config.headers = config.headers || {};
    config.headers['X-FidClic-Store'] = localStorage.getItem('ft_selected_branch_v1') || 'all';
  } catch (_e) { /* ignore */ }
  return config;
});

export const authAPI = {
  login: (data) => api.post('/auth/login', data),
  login2fa: (challenge, code) => api.post('/auth/login/2fa', { challenge, code }),
  register: (data) => api.post('/auth/register', data),
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

export const adminAPI = {
  // Facturation — the issuer of FidClic's invoices, and every invoice issued.
  franchise: () => api.get('/admin/franchise'),
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
  scan: (data) => api.post('/owner/scan', data),
  register: (data) => api.post('/owner/register', data),
  getCardTemplate: () => api.get('/owner/card-template'),
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
  saveReferralConfig: (config) => api.put('/owner/referrals/config', config),
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
  getHomeGoal: () => api.get('/owner/home/goal'),
  setHomeGoal: (body) => api.put('/owner/home/goal', body),
  // Clients — the page's four figures, its segments and its paginated table.
  clientsOverview: () => api.get('/owner/clients/overview'),
  clientsList: (params) => api.get('/owner/clients/list', { params }),
  clientsExport: (params) => api.get('/owner/clients/export', { params, responseType: 'blob' }),
  // Every client the current filter matches — ids only, so a message goes to
  // the whole filter rather than to the page that happens to be on screen.
  clientIds: (params) => api.get('/owner/clients/ids', { params }),
  sendCampaignToGroup: (body) => api.post('/owner/campaigns/send-to-group', body),
  // Campagnes — the page in one call, the composer in one call.
  campaignsPage: () => api.get('/owner/campaigns/page'),
  composeCampaign: (body) => api.post('/owner/campaigns/compose', body),
  campaignAiDraft: (body) => api.post('/owner/campaigns/ai-draft', body),
  googleWalletStatus: () => api.get('/owner/wallet/google-status'),

  // Segmentation — the page in one call, the builder counted live.
  segmentationPage: () => api.get('/owner/segmentation/page'),
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
  teamAccess: () => api.get('/owner/team-access'),
  teamCreate: (body) => api.post('/owner/team-access/users', body),
  teamUpdate: (id, body) => api.put(`/owner/team-access/users/${encodeURIComponent(id)}`, body),
  teamStatus: (id, active) => api.post(`/owner/team-access/users/${encodeURIComponent(id)}/status`, { active }),
  teamPassword: (id) => api.post(`/owner/team-access/users/${encodeURIComponent(id)}/password`),
  teamDelete: (id) => api.delete(`/owner/team-access/users/${encodeURIComponent(id)}`),
  teamStoreAccess: (storeId, id, enabled) => api.put(`/owner/team-access/stores/${encodeURIComponent(storeId)}/users/${encodeURIComponent(id)}`, { enabled }),
  joinLink: () => api.get('/owner/join-link'),
  joinSlugCheck: (slug) => api.get('/owner/join-link/slug-check', { params: { slug } }),
  saveJoinSlug: (slug) => api.put('/owner/join-link/slug', { slug }),
  saveJoinPage: (body) => api.put('/owner/join-link/page', body),
  segmentPreview: (body) => api.post('/owner/segmentation/preview', body),
  createSegment: (body) => api.post('/owner/segmentation/segments', body),
  updateSegment: (id, body) => api.put(`/owner/segmentation/segments/${id}`, body),
  deleteSegment: (id) => api.delete(`/owner/segmentation/segments/${id}`),
  segmentClients: (id) => api.get(`/owner/segmentation/segments/${id}/clients`),

  // Insights — « Faites grandir votre commerce ».
  insightsPage: () => api.get('/owner/insights/page'),
  insightTemplate: (key, day) => api.get(`/owner/insights/templates/${encodeURIComponent(key)}`, { params: day != null && day !== '' ? { day } : {} }),
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
  getJoinInfo: (slug) => api.get('/join/' + slug),
  joinProgram: (slug, data) => api.post('/join/' + slug, data),
  // -- Real-time proximity push (wallet card calls this with device GPS) --
  proximityPing: (data) => api.post('/public/proximity-ping', data),
  // -- Customer review submission (wallet card → rate-your-visit panel) --
  submitReview: (data) => api.post('/public/reviews', data),
  googleReviewClick: (barcode) => api.post(`/card/${barcode}/google-review-click`),
  // -- Signup page: its words (Paramètres › Lien d'inscription) and one visit --
  joinPage: (slug) => api.get(`/join/${slug}/page`),
  joinView: (slug, body) => api.post(`/join/${slug}/view`, body),
};

export default api;
