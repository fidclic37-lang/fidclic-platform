import React, { useEffect, useState } from 'react';
import api from '../lib/api';
import { UserCheck, UserX, UserMinus, UserPlus, Settings2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { C as C_PS } from './PageShell';

/**
 * Customer Status KPIs — uses the LIVE configurable definition set in
 * Settings (Active / Inactive / Dormant / New thresholds), so when the
 * owner changes the definition, this immediately reflects it.
 *
 * Drop-in for AnalyticsPage. Reads the additive backend module
 *   GET /api/owner/customer-status/summary
 * which honours `customer_status_config`. The legacy 30-day-based KPIs
 * elsewhere on the page remain useful for quick comparison and aren't
 * touched.
 */
const CustomerStatusKPI = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await api.get('/owner/customer-status/summary');
        if (!cancelled) setData(res.data);
      } catch (e) {
        console.error('customer-status summary failed', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const cfg = data?.config;
  const counts = data?.counts || { active: 0, inactive: 0, dormant: 0, new: 0 };
  const total = data?.total ?? Object.values(counts).reduce((s, n) => s + (n || 0), 0);

  return (
    <div className="rounded-xl bg-white p-5" style={{ border: `1px solid ${C_PS.hairline}` }}>
      <div className="flex items-start justify-between gap-3 mb-4 flex-wrap">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.18em]" style={{ color: C_PS.terracotta }}>
            Live · uses your saved definition
          </p>
          <h2 className="text-xl font-bold mt-0.5" style={{ fontFamily: 'Cormorant Garamond', color: C_PS.inkDeep }}>
            Customer status — by your definition
          </h2>
          {cfg && (
            <p className="text-xs mt-1" style={{ color: C_PS.inkMute }}>
              Active = visited within <b>{cfg.active_within_days} days</b> ·
              Dormant = silent for <b>{cfg.dormant_after_days}+ days</b> ·
              Min visits to be active: <b>{cfg.minimum_visits_for_active}</b>
            </p>
          )}
        </div>
        <Link
          to="/dashboard/settings"
          className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full transition"
          style={{ background: `${C_PS.terracotta}1A`, color: C_PS.terracotta, border: `1px solid ${C_PS.terracotta}33` }}
        >
          <Settings2 size={12} /> Edit definition
        </Link>
      </div>

      {loading ? (
        <div className="py-8 text-center text-sm" style={{ color: C_PS.inkMute }}>Loading…</div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Tile label="Active" value={counts.active} pct={pct(counts.active, total)} icon={UserCheck} tone="success" />
          <Tile label="Inactive" value={counts.inactive} pct={pct(counts.inactive, total)} icon={UserMinus} tone="default" />
          <Tile label="Dormant" value={counts.dormant} pct={pct(counts.dormant, total)} icon={UserX} tone="danger" />
          <Tile label="New (no visits)" value={counts.new} pct={pct(counts.new, total)} icon={UserPlus} tone="info" />
        </div>
      )}
    </div>
  );
};

const pct = (n, total) => (total > 0 ? Math.round((n / total) * 100) : 0);

const Tile = ({ label, value, pct, icon: Icon, tone }) => {
  const palette = {
    // White tile + hairline for every status; only the NUMBER carries meaning
    // (blue = healthy, grey = dormant, red = at risk) — mockup style, no tints.
    success: { bg: 'var(--flc-card, #FFFFFF)', fg: 'var(--flc-ok, #16A34A)',           accent: 'var(--flc-ok, #16A34A)' },
    danger:  { bg: 'var(--flc-card, #FFFFFF)', fg: 'var(--flc-risk, #E11D48)',        accent: 'var(--flc-risk, #E11D48)' },
    info:    { bg: 'var(--flc-card, #FFFFFF)', fg: 'var(--flc-accent-deep, #1D4ED8)', accent: 'var(--flc-accent, #2F6BFF)' },
    default: { bg: 'var(--flc-card, #FFFFFF)', fg: 'var(--flc-ink2, #334155)',        accent: 'var(--flc-ink3, #64748B)' },
  }[tone] || { bg: 'var(--flc-paper2, #F3F4F6)', fg: 'var(--flc-ink2, #374151)', accent: 'var(--flc-ink3, #6B7280)' };

  return (
    <div className="rounded-lg p-4 relative overflow-hidden" style={{ background: palette.bg }}>
      <div
        className="absolute top-3 right-3 w-9 h-9 rounded-lg flex items-center justify-center"
        style={{ background: 'var(--flc-card, #FFFFFF)', color: palette.accent }}
      >
        <Icon size={18} />
      </div>
      <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: palette.fg }}>{label}</p>
      <p className="text-3xl font-bold mt-1" style={{ color: palette.fg }}>{value ?? 0}</p>
      <p className="text-xs mt-1" style={{ color: palette.fg, opacity: 0.7 }}>{pct}% of customer base</p>
    </div>
  );
};

export default CustomerStatusKPI;
