import React, { useEffect, useState } from 'react';
import api from '../lib/api';
import { Award, Save, RefreshCw, TrendingUp } from 'lucide-react';
import { C as C_PS } from './PageShell';

/**
 * Drop-in card for SettingsPage: lets the owner define their own tier
 * thresholds (silver/gold/vip min visits) and the big-spender rule.
 *
 * Talks to the additive backend module `features/tier_definitions.py`.
 * After saving, click "Recompute now" to apply the new thresholds across
 * the whole customer base. The live scan endpoint still uses the original
 * server-side thresholds — recompute brings everyone in line.
 */
const TierDefinitionCard = () => {
  const [defn, setDefn] = useState({
    silver_min_visits: 10,
    gold_min_visits: 20,
    vip_min_visits: 40,
    big_spender_min_amount: 500,
    big_spender_min_avg_ticket: 0,
  });
  const [saving, setSaving] = useState(false);
  const [recomputing, setRecomputing] = useState(false);
  const [savedAt, setSavedAt] = useState(null);
  const [recomputeResult, setRecomputeResult] = useState(null);

  const load = async () => {
    try {
      const res = await api.get('/owner/tier-definitions');
      if (res.data) setDefn({
        silver_min_visits: res.data.silver_min_visits ?? 10,
        gold_min_visits: res.data.gold_min_visits ?? 20,
        vip_min_visits: res.data.vip_min_visits ?? 40,
        big_spender_min_amount: res.data.big_spender_min_amount ?? 500,
        big_spender_min_avg_ticket: res.data.big_spender_min_avg_ticket ?? 0,
      });
    } catch (e) {
      console.error('tier-definitions load failed', e);
    }
  };
  useEffect(() => { load(); }, []);

  const valid =
    defn.silver_min_visits > 0 &&
    defn.silver_min_visits < defn.gold_min_visits &&
    defn.gold_min_visits < defn.vip_min_visits;

  const save = async () => {
    if (!valid) {
      alert('Thresholds must be silver < gold < vip.');
      return;
    }
    setSaving(true);
    try {
      await api.put('/owner/tier-definitions', defn);
      setSavedAt(new Date());
    } catch (e) {
      alert('Failed to save: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const recompute = async () => {
    if (!window.confirm('This will rewrite every customer\'s tier based on the saved thresholds. Continue?')) return;
    setRecomputing(true);
    try {
      const res = await api.post('/owner/tier-definitions/recompute');
      setRecomputeResult(res.data);
    } catch (e) {
      alert('Recompute failed: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setRecomputing(false);
    }
  };

  return (
    <div className="rounded-xl bg-white p-6 mt-6" style={{ border: `1px solid ${C_PS.hairline}` }}>
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: `${C_PS.ochre}1A`, color: C_PS.ochre }}>
          <Award size={18} />
        </div>
        <div>
          <h2 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond', color: C_PS.inkDeep }}>
            Tier thresholds & big-spender rule
          </h2>
          <p className="text-sm mt-1" style={{ color: C_PS.inkMute }}>
            Define when a customer reaches Silver, Gold, and VIP — based on visits.
            And set the spend threshold that flags a customer as a "big spender" for filtering.
          </p>
        </div>
      </div>

      <p className="text-[10px] uppercase font-bold tracking-widest mb-2" style={{ color: C_PS.inkMute }}>Tier ladder (visit count)</p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Threshold label="Silver from" suffix="visits" tone="silver"
          value={defn.silver_min_visits} onChange={(v) => setDefn({ ...defn, silver_min_visits: v })} />
        <Threshold label="Gold from" suffix="visits" tone="gold"
          value={defn.gold_min_visits} onChange={(v) => setDefn({ ...defn, gold_min_visits: v })} />
        <Threshold label="VIP from" suffix="visits" tone="vip"
          value={defn.vip_min_visits} onChange={(v) => setDefn({ ...defn, vip_min_visits: v })} />
      </div>
      {!valid && (
        <p className="text-xs mt-2 text-red-600">
          Thresholds must increase: silver &lt; gold &lt; vip.
        </p>
      )}

      <div className="mt-6 pt-5 border-t" style={{ borderColor: C_PS.hairline }}>
        <p className="text-[10px] uppercase font-bold tracking-widest mb-2" style={{ color: C_PS.inkMute }}>
          Big-spender rule
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Threshold label="Total spend ≥" suffix="€" tone="terracotta"
            value={defn.big_spender_min_amount} onChange={(v) => setDefn({ ...defn, big_spender_min_amount: v })} step="0.01" />
          <Threshold label="Avg ticket ≥ (optional)" suffix="€" tone="terracotta"
            value={defn.big_spender_min_avg_ticket} onChange={(v) => setDefn({ ...defn, big_spender_min_avg_ticket: v })} step="0.01"
            hint="0 = no constraint on avg ticket." />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 mt-6">
        <button type="button" onClick={save} disabled={saving || !valid}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-white font-semibold disabled:opacity-50"
          style={{ background: C_PS.terracotta }}>
          <Save size={14} /> {saving ? 'Saving…' : 'Save thresholds'}
        </button>
        <button type="button" onClick={recompute} disabled={recomputing}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold disabled:opacity-50"
          style={{ background: 'var(--flc-card, #FFFFFF)', color: C_PS.terracotta, border: `1px solid ${C_PS.terracotta}55` }}>
          <RefreshCw size={14} className={recomputing ? 'animate-spin' : ''} /> {recomputing ? 'Recomputing…' : 'Recompute now'}
        </button>
        {savedAt && <span className="text-xs" style={{ color: C_PS.inkMute }}>Saved {savedAt.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</span>}
      </div>

      {recomputeResult && (
        <div className="mt-5 pt-5 border-t" style={{ borderColor: C_PS.hairline }}>
          <p className="text-[10px] uppercase font-bold tracking-widest mb-2" style={{ color: C_PS.inkMute }}>
            Recompute result
          </p>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <ResultTile label="Bronze" value={recomputeResult.distribution?.bronze ?? 0} bg="#F3F4F6" fg="#374151" />
            <ResultTile label="Silver" value={recomputeResult.distribution?.silver ?? 0} bg="#E5E7EB" fg="#1F2937" />
            <ResultTile label="Gold" value={recomputeResult.distribution?.gold ?? 0} bg="#FEF3C7" fg="#92400E" />
            <ResultTile label="VIP" value={recomputeResult.distribution?.vip ?? 0} bg="#EDE9FE" fg="#5B21B6" />
            <ResultTile label="Big spenders" value={recomputeResult.big_spenders ?? 0} bg="#FEE2E2" fg="#991B1B" icon={TrendingUp} />
          </div>
          <p className="text-xs mt-2" style={{ color: C_PS.inkMute }}>
            {recomputeResult.customers_updated ?? 0} customer record{(recomputeResult.customers_updated ?? 0) === 1 ? '' : 's'} updated.
          </p>
        </div>
      )}
    </div>
  );
};

const Threshold = ({ label, suffix, value, onChange, step, hint, tone }) => {
  const accent = {
    silver: '#9CA3AF', gold: '#D97706', vip: '#7C3AED', terracotta: '#B85C38',
  }[tone] || '#B85C38';
  return (
    <div>
      <label className="text-xs font-bold uppercase tracking-widest mb-1 block" style={{ color: accent }}>{label}</label>
      <div className="flex items-center gap-2">
        <input type="number" min={0} step={step || 1} value={value}
          onChange={(e) => onChange(parseFloat(e.target.value || '0'))}
          className="w-full border rounded-lg px-3 py-2 text-sm"
          style={{ borderColor: C_PS.hairline }} />
        <span className="text-xs font-semibold shrink-0" style={{ color: C_PS.inkMute }}>{suffix}</span>
      </div>
      {hint && <p className="text-[11px] mt-1" style={{ color: C_PS.inkMute }}>{hint}</p>}
    </div>
  );
};

const ResultTile = ({ label, value, bg, fg, icon: Icon }) => (
  <div className="rounded-lg p-3" style={{ background: bg }}>
    <div className="flex items-center gap-1.5">
      {Icon && <Icon size={12} style={{ color: fg }} />}
      <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: fg }}>{label}</p>
    </div>
    <p className="text-2xl font-bold mt-1" style={{ color: fg }}>{value}</p>
  </div>
);

export default TierDefinitionCard;
