/**
 * AdminPlansPage — DB-backed editor for per-plan limits.
 *
 * What's editable per plan (basic / gold / vip / chain):
 *   • max_customers          — hard cap enforced at /api/join
 *   • campaigns_per_month    — informational today; will gate campaign creation later
 *   • ai_queries_per_day     — enforced on every AI assistant call
 *   • csv_export             — feature flag, gates the Export CSV button on Customers
 *   • geo_proximity          — feature flag, gates geo-radius push campaigns
 *   • multi_branch           — feature flag, gates the branch picker / add-branch
 *
 * Read model:
 *   • baseline   — hardcoded defaults in api/models.py (PLAN_FEATURES)
 *   • overrides  — admin-edited values stored in db.plan_settings
 *   • effective  — baseline merged with overrides (what every business sees)
 *
 * Saving "" or clearing an override sends `null` to the API → that field
 * falls back to the baseline. So an admin who raises basic from 500 → 750
 * can later type 0 or clear the field to revert to 500.
 *
 * NB: per-tenant plan switching lives on the existing Tenants page
 * (Tenants → ⋯ menu → "Change plan"). This page is platform-wide.
 */
import React, { useEffect, useState } from 'react';
import { adminAPI } from '../lib/api';
import { Crown, Users, Mail, Brain, Download, MapPin, GitBranch, RotateCcw, Save, AlertCircle, CheckCircle2, Loader2, Clock, Bell, Euro, Send, UserCog, Store } from 'lucide-react';
import { PageHeader, C as C_PS } from '../components/PageShell';
import FranchisePanel from '../components/admin/FranchisePanel';

// Visual label, helper text, and icon for each editable field — colocated
// so we can render the rows uniformly without sprinkling copy through JSX.
const FIELDS = [
  { key: 'price',                       label: 'Monthly price (€)',         type: 'number',  icon: Euro,     hint: 'What the business sees in the plan picker. Changes take effect on the next page load.' },
  { key: 'max_customers',               label: 'Max customers',             type: 'number',  icon: Users,    hint: 'Hard cap enforced when a customer tries to join. Soft-deleted customers do not count.' },
  { key: 'push_per_month',              label: 'Push / month',              type: 'number',  icon: Send,     hint: 'Marketing pushes delivered per calendar month (0 = unlimited). Counted from delivery_log and enforced on campaign sends; reward/transactional messages are never blocked. This is the figure sold on fidclic.com/tarifs.' },
  { key: 'campaigns_per_month',         label: 'Campaigns / month',         type: 'number',  icon: Mail,     hint: 'How many campaigns this plan can send each calendar month (0 = unlimited).' },
  { key: 'staff_accounts',              label: 'Staff accounts',            type: 'number',  icon: UserCog,  hint: 'How many people (owner + collaborators) can log in for this tenant.' },
  { key: 'establishments',              label: 'Establishments',            type: 'number',  icon: Store,    hint: 'Points of sale included. Networks and franchises are quoted separately.' },
  { key: 'ai_queries_per_day',          label: 'AI queries / day',          type: 'number',  icon: Brain,    hint: '0 disables the AI Assistant entirely for this plan. Resets at midnight UTC.' },
  { key: 'csv_export',                  label: 'CSV export',                type: 'boolean', icon: Download, hint: 'Whether owners on this plan can export their customer list.' },
  { key: 'geo_proximity',               label: 'Geo-proximity',             type: 'boolean', icon: MapPin,   hint: 'Enables radius-targeted push campaigns based on customer location.' },
  { key: 'multi_branch',                label: 'Multi-branch',              type: 'boolean', icon: GitBranch,hint: 'Lets the tenant define multiple branches and tag visits per branch.' },
  { key: 'trial_duration_days',         label: 'Free trial (days)',         type: 'number',  icon: Clock,    hint: 'How long every new tenant on this plan gets before they must subscribe. 21 = 3 weeks.' },
  { key: 'trial_reminder_days_before',  label: 'Trial reminder lead time',  type: 'number',  icon: Bell,     hint: 'How many days BEFORE trial-end the warning banner escalates from quiet to urgent.' },
];

// Canonical 3-tier system. Order = the order they render in.
const PLAN_META = {
  // Commercial names (what the website and the merchant see). The internal
  // keys stay silver/gold/vip — every tenant row references them.
  silver: { label: 'Starter', tone: '#6FA89C', gradient: 'linear-gradient(135deg, #6FA89C 0%, #98C9BB 100%)' },
  gold:   { label: 'Pro',     tone: '#D4A574', gradient: 'linear-gradient(135deg, #D4A574 0%, #E8C49A 100%)' },
  vip:    { label: 'Pro AI',  tone: '#B85C38', gradient: 'linear-gradient(135deg, #B85C38 0%, #E8917C 100%)' },
  // Sold on quote: its « price » is set per franchise, below the plans.
  franchise: { label: 'Franchise', tone: '#2F6BFF', gradient: 'linear-gradient(135deg, #2F6BFF 0%, #7AA2FF 100%)' },
};

export default function AdminPlansPage() {
  const [rows, setRows] = useState([]);   // server-truth rows from /api/admin/plans
  const [drafts, setDrafts] = useState({});// { [plan]: { [field]: editedValue } }
  const [loading, setLoading] = useState(true);
  const [savingPlan, setSavingPlan] = useState(null);
  const [savedAt, setSavedAt] = useState({}); // { [plan]: Date } — used to flash ✓
  const [error, setError] = useState(null);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const { data } = await adminAPI.listPlans();
      setRows(data.plans || []);
      // Seed drafts from effective values so the inputs render with the
      // actual current limit (after any admin overrides have been applied).
      const seed = {};
      for (const r of data.plans || []) {
        seed[r.plan] = { ...r.effective };
      }
      setDrafts(seed);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Failed to load plans.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // Update a single field in the draft for a plan. Numeric fields are
  // coerced on save (kept as string in state so the input handles empty).
  const setDraftField = (plan, key, value) => {
    setDrafts((prev) => ({
      ...prev,
      [plan]: { ...(prev[plan] || {}), [key]: value },
    }));
  };

  const hasChanges = (plan) => {
    const row = rows.find((r) => r.plan === plan);
    if (!row) return false;
    const draft = drafts[plan] || {};
    return FIELDS.some((f) => {
      const a = draft[f.key];
      const b = row.effective[f.key];
      // Compare loosely: '500' === 500, true === true, '' empties out
      if (f.type === 'number') {
        const av = a === '' || a === null || a === undefined ? null : Number(a);
        const bv = b === null || b === undefined ? null : Number(b);
        return av !== bv;
      }
      return Boolean(a) !== Boolean(b);
    });
  };

  // Save sends only the fields that differ. Empty/null values clear that
  // field's override (back to baseline). The server returns the freshly
  // computed row so we replace it in place — no need to refetch the list.
  const save = async (plan) => {
    try {
      setSavingPlan(plan);
      const row = rows.find((r) => r.plan === plan);
      const draft = drafts[plan] || {};
      const body = {};
      for (const f of FIELDS) {
        const a = draft[f.key];
        const b = row.effective[f.key];
        if (f.type === 'number') {
          const av = a === '' || a === null || a === undefined ? null : Number(a);
          if (Number.isNaN(av)) continue; // skip invalid input
          if (av !== (b === null || b === undefined ? null : Number(b))) {
            body[f.key] = av;
          }
        } else {
          if (Boolean(a) !== Boolean(b)) body[f.key] = Boolean(a);
        }
      }
      if (Object.keys(body).length === 0) return; // nothing to do

      const { data } = await adminAPI.updatePlan(plan, body);
      setRows((prev) => prev.map((r) => (r.plan === plan ? data : r)));
      setDrafts((prev) => ({ ...prev, [plan]: { ...data.effective } }));
      setSavedAt((prev) => ({ ...prev, [plan]: new Date() }));
      // Auto-clear the ✓ after 2s so the button can flash again on next save.
      setTimeout(() => setSavedAt((p) => {
        const next = { ...p };
        delete next[plan];
        return next;
      }), 2000);
    } catch (e) {
      setError(`Failed to save ${plan} plan: ` + (e?.response?.data?.detail || e.message));
    } finally {
      setSavingPlan(null);
    }
  };

  // Reset a single field to baseline (clears its override on the server).
  const resetField = async (plan, key) => {
    try {
      setSavingPlan(plan);
      const { data } = await adminAPI.updatePlan(plan, { [key]: null });
      setRows((prev) => prev.map((r) => (r.plan === plan ? data : r)));
      setDrafts((prev) => ({ ...prev, [plan]: { ...data.effective } }));
    } catch (e) {
      setError(`Failed to reset ${key}: ` + (e?.response?.data?.detail || e.message));
    } finally {
      setSavingPlan(null);
    }
  };

  if (loading) {
    return (
      <div className="py-12 px-4 text-center" style={{ color: C_PS.inkMute }}>
        <Loader2 className="inline-block w-6 h-6 animate-spin mb-2" />
        <p className="text-sm">Loading plans…</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Platform"
        title="Plans &amp; limits"
        description="Starter / Pro / Pro AI, and Franchise (on quote). Edit the price, quota caps, feature flags and free-trial length per plan. Changes apply instantly to every tenant on that plan — no redeploy needed. To switch a single business's plan, use the Tenants page."
        role="super_admin"
      />

      {error && (
        <div className="rounded-xl border-2 border-red-200 bg-red-50 p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold text-red-900">{error}</p>
            <button onClick={() => { setError(null); load(); }} className="text-xs underline text-red-700 mt-1">Retry</button>
          </div>
        </div>
      )}

      <div className="grid gap-6">
        {rows.map((row) => {
          const meta = PLAN_META[row.plan] || PLAN_META.basic;
          const draft = drafts[row.plan] || {};
          const overridden = row.overrides || {};
          const dirty = hasChanges(row.plan);
          const justSaved = !!savedAt[row.plan];
          return (
            <section
              key={row.plan}
              className="bg-white rounded-2xl border overflow-hidden"
              style={{ borderColor: C_PS.hairline, boxShadow: '0 1px 2px rgba(28,25,23,0.04)' }}
            >
              {/* Plan header — gradient strip + name + price + tenant count */}
              <header className="flex items-center justify-between gap-3 p-5"
                      style={{ background: meta.gradient, color: 'white' }}>
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-white/20 flex items-center justify-center">
                    <Crown size={18} />
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.18em] font-bold opacity-80">Plan</p>
                    <h2 className="font-['Cormorant_Garamond'] text-2xl font-bold leading-tight">
                      {meta.label}
                      {row.plan === 'franchise' ? <span className="ml-2 text-sm font-normal opacity-90">sur devis — défauts ci-dessous</span>
                        : row.price != null && <span className="ml-2 text-sm font-normal opacity-90">€{row.price}/mo</span>}
                    </h2>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-[10px] uppercase tracking-[0.18em] font-bold opacity-80">Tenants</p>
                  <p className="text-2xl font-bold tabular-nums">{row.tenant_count}</p>
                </div>
              </header>

              {/* Editable rows */}
              <div className="divide-y" style={{ borderColor: C_PS.hairline }}>
                {FIELDS.filter((f) => !(row.plan === 'franchise' && f.key === 'price')).map((f) => {
                  const Icon = f.icon;
                  const isOverridden = Object.prototype.hasOwnProperty.call(overridden, f.key);
                  const baselineVal = row.baseline?.[f.key];
                  const draftVal = draft[f.key];
                  return (
                    <div key={f.key} className="grid grid-cols-12 gap-4 p-4 items-start" style={{ borderColor: C_PS.hairline }}>
                      {/* Label + hint */}
                      <div className="col-span-12 md:col-span-5 flex items-start gap-3">
                        <div className="w-9 h-9 rounded-lg shrink-0 flex items-center justify-center"
                             style={{ background: `${meta.tone}1A`, color: meta.tone, border: `1px solid ${meta.tone}33` }}>
                          <Icon size={16} />
                        </div>
                        <div>
                          <p className="text-sm font-bold" style={{ color: C_PS.inkDeep }}>{f.label}</p>
                          <p className="text-xs mt-0.5" style={{ color: C_PS.inkMute }}>{f.hint}</p>
                          <p className="text-[10px] mt-1" style={{ color: C_PS.inkMute }}>
                            Default: {f.type === 'boolean'
                              ? (baselineVal ? 'enabled' : 'disabled')
                              : (baselineVal ?? '—')}
                            {isOverridden && (
                              <span
                                className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider"
                                style={{ background: `${meta.tone}22`, color: meta.tone }}
                              >
                                override
                              </span>
                            )}
                          </p>
                        </div>
                      </div>

                      {/* Input */}
                      <div className="col-span-8 md:col-span-5">
                        {f.type === 'number' ? (
                          <input
                            type="number"
                            min="0"
                            value={draftVal ?? ''}
                            onChange={(e) => setDraftField(row.plan, f.key, e.target.value)}
                            className="w-full px-3 py-2 rounded-lg border-2 outline-none text-sm font-mono tabular-nums focus:border-[#B85C38]"
                            style={{ borderColor: C_PS.hairline, background: 'white' }}
                          />
                        ) : (
                          <label className="inline-flex items-center gap-2 cursor-pointer select-none">
                            <input
                              type="checkbox"
                              checked={!!draftVal}
                              onChange={(e) => setDraftField(row.plan, f.key, e.target.checked)}
                              className="w-4 h-4 accent-[#B85C38]"
                            />
                            <span className="text-sm" style={{ color: C_PS.inkSoft }}>
                              {draftVal ? 'Enabled for this plan' : 'Disabled for this plan'}
                            </span>
                          </label>
                        )}
                      </div>

                      {/* Per-field reset (only when an override is in effect) */}
                      <div className="col-span-4 md:col-span-2 flex justify-end">
                        {isOverridden && (
                          <button
                            type="button"
                            onClick={() => resetField(row.plan, f.key)}
                            disabled={savingPlan === row.plan}
                            title={`Revert to baseline (${baselineVal})`}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium hover:bg-[#FAF8F4] disabled:opacity-50"
                            style={{ color: C_PS.inkMute, border: `1px solid ${C_PS.hairline}` }}
                          >
                            <RotateCcw size={12} /> Reset
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Footer — save button */}
              <footer className="flex items-center justify-between p-4 bg-[#FAF8F4] border-t" style={{ borderColor: C_PS.hairline }}>
                <p className="text-xs" style={{ color: C_PS.inkMute }}>
                  Changes apply immediately to every tenant on this plan.
                </p>
                <button
                  type="button"
                  onClick={() => save(row.plan)}
                  disabled={!dirty || savingPlan === row.plan}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-bold text-white transition disabled:opacity-50"
                  style={{ background: meta.tone }}
                >
                  {savingPlan === row.plan ? (
                    <><Loader2 size={14} className="animate-spin" /> Saving…</>
                  ) : justSaved ? (
                    <><CheckCircle2 size={14} /> Saved</>
                  ) : (
                    <><Save size={14} /> Save changes</>
                  )}
                </button>
              </footer>
            </section>
          );
        })}
      </div>

      <FranchisePanel />

      {/* Cross-link to per-tenant plan editing */}
      <div className="rounded-xl border-2 border-dashed p-4 text-sm flex items-start gap-3"
           style={{ borderColor: C_PS.hairline, background: 'white', color: C_PS.inkSoft }}>
        <Crown size={16} style={{ color: C_PS.inkMute, marginTop: 2 }} />
        <div>
          <p className="font-semibold" style={{ color: C_PS.inkDeep }}>Need to change one business's plan?</p>
          <p className="text-xs mt-1">
            Open <a href="/admin/tenants" className="underline" style={{ color: '#B85C38' }}>Manage Businesses</a>,
            click the ⋯ menu on the tenant row, and pick a new plan.
            That changes the cap that business sees, without affecting every other tenant on the same plan.
          </p>
        </div>
      </div>
    </div>
  );
}
