import React, { useEffect, useState } from 'react';
import api from '../lib/api';
import { UserCheck, Save } from 'lucide-react';
import { C as C_PS } from './PageShell';

/**
 * Drop-in card for SettingsPage: lets the owner define how the platform
 * classifies "active" / "inactive" / "dormant" / "new" customers.
 *
 * Talks to the additive backend module `features/customer_status.py`.
 * Existing customer-status logic in server.py is unaffected — this is a
 * parallel definition the owner can opt into via the new
 *   /api/owner/customer-status/list
 * endpoint and via the filter on CustomersPage.
 */
const CustomerStatusConfigCard = () => {
  const [cfg, setCfg] = useState({
    active_within_days: 30,
    dormant_after_days: 90,
    minimum_visits_for_active: 1,
    about_to_lose_days: 21,
    loyal_visits_per_month: 4,
    regular_visits_per_month: 2,
  });
  const [counts, setCounts] = useState(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(null);

  const load = async () => {
    try {
      const res = await api.get('/owner/customer-status/summary');
      if (res.data?.config) {
        setCfg({
          active_within_days: res.data.config.active_within_days ?? 30,
          dormant_after_days: res.data.config.dormant_after_days ?? 90,
          minimum_visits_for_active: res.data.config.minimum_visits_for_active ?? 1,
          about_to_lose_days: res.data.config.about_to_lose_days ?? 21,
          loyal_visits_per_month: res.data.config.loyal_visits_per_month ?? 4,
          regular_visits_per_month: res.data.config.regular_visits_per_month ?? 2,
        });
      }
      if (res.data?.counts) setCounts(res.data.counts);
    } catch (e) {
      console.error('Failed to load customer-status config', e);
    }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.put('/owner/customer-status/config', cfg);
      setSavedAt(new Date());
      await load();
    } catch (e) {
      alert('Failed to save: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-xl bg-white p-6 mt-6" style={{ border: `1px solid ${C_PS.hairline}` }}>
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: `${C_PS.terracotta}1A`, color: C_PS.terracotta }}>
          <UserCheck size={18} />
        </div>
        <div>
          <h2 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond', color: C_PS.inkDeep }}>
            Active / Inactive customer definition
          </h2>
          <p className="text-sm mt-1" style={{ color: C_PS.inkMute }}>
            Set the rules that classify your customers. These thresholds power the
            History page filters and the new "by status" search on the Customers page.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Field
          label="Active if visited within"
          suffix="days"
          value={cfg.active_within_days}
          onChange={(v) => setCfg({ ...cfg, active_within_days: v })}
          help="A customer who's visited at least this recently is considered Active."
        />
        <Field
          label="About to lose if silent for"
          suffix="days"
          value={cfg.about_to_lose_days}
          onChange={(v) => setCfg({ ...cfg, about_to_lose_days: v })}
          help="Active but drifting — flagged for re-engagement before they go fully inactive."
        />
        <Field
          label="Dormant if no visit for"
          suffix="days"
          value={cfg.dormant_after_days}
          onChange={(v) => setCfg({ ...cfg, dormant_after_days: v })}
          help="Once silence exceeds this, the customer becomes Dormant (deeper churn risk)."
        />
        <Field
          label="Minimum visits to be Active"
          suffix="visits"
          value={cfg.minimum_visits_for_active}
          onChange={(v) => setCfg({ ...cfg, minimum_visits_for_active: v })}
          help="A customer with fewer total visits than this never reaches Active."
        />
        <Field
          label="Loyal — visits/month ≥"
          suffix="visits/mo"
          value={cfg.loyal_visits_per_month}
          onChange={(v) => setCfg({ ...cfg, loyal_visits_per_month: v })}
          help="Customers visiting at least this often are flagged as Loyal."
        />
        <Field
          label="Regular — visits/month ≥"
          suffix="visits/mo"
          value={cfg.regular_visits_per_month}
          onChange={(v) => setCfg({ ...cfg, regular_visits_per_month: v })}
          help="Below Loyal but above this — flagged as Regular."
        />
      </div>

      {counts && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-5 pt-5 border-t" style={{ borderColor: C_PS.hairline }}>
          <Tile label="Active" value={counts.active ?? 0} tone="success" />
          <Tile label="Inactive" value={counts.inactive ?? 0} tone="default" />
          <Tile label="Dormant" value={counts.dormant ?? 0} tone="danger" />
          <Tile label="New (no visits yet)" value={counts.new ?? 0} tone="info" />
        </div>
      )}

      <div className="flex items-center gap-3 mt-5">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-white font-semibold disabled:opacity-50"
          style={{ background: C_PS.terracotta }}
        >
          <Save size={14} />
          {saving ? 'Saving…' : 'Save status definition'}
        </button>
        {savedAt && <span className="text-xs" style={{ color: C_PS.inkMute }}>Saved {savedAt.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</span>}
      </div>
    </div>
  );
};

const Field = ({ label, suffix, value, onChange, help }) => (
  <div>
    <label className="text-xs font-bold uppercase tracking-widest mb-1 block" style={{ color: C_PS.inkMute }}>{label}</label>
    <div className="flex items-center gap-2">
      <input
        type="number"
        min={0}
        value={value}
        onChange={(e) => onChange(Math.max(0, parseInt(e.target.value || '0', 10)))}
        className="w-full border rounded-lg px-3 py-2 text-sm"
        style={{ borderColor: C_PS.hairline }}
      />
      <span className="text-xs font-semibold" style={{ color: C_PS.inkMute }}>{suffix}</span>
    </div>
    {help && <p className="text-[11px] mt-1" style={{ color: C_PS.inkMute }}>{help}</p>}
  </div>
);

const Tile = ({ label, value, tone }) => {
  const palette = {
    success: { bg: '#ECFDF5', fg: '#065F46' },
    danger:  { bg: '#FEF2F2', fg: '#991B1B' },
    info:    { bg: '#EFF6FF', fg: '#1E40AF' },
    default: { bg: '#F3F4F6', fg: '#374151' },
  }[tone] || { bg: '#F3F4F6', fg: '#374151' };
  return (
    <div className="rounded-lg p-3" style={{ background: palette.bg }}>
      <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: palette.fg }}>{label}</p>
      <p className="text-2xl font-bold" style={{ color: palette.fg }}>{value}</p>
    </div>
  );
};

export default CustomerStatusConfigCard;
