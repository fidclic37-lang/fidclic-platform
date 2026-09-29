import React, { useEffect, useState } from 'react';
import api from '../lib/api';
import { TrendingUp, Users } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { chartAnimation } from '../lib/chartAnimation';
import { C as C_PS } from './PageShell';
import { useBranch } from '../contexts/BranchContext';

/**
 * Customer-acquisition-history chart.
 *
 * Per the v2 spec:
 *   - Range presets ONLY (no free-form number input)
 *   - days  → max 30
 *   - weeks → max 52
 *   - months → max 24
 *   - years → max 5
 *   - "Buckets shown" KPI is replaced with a more useful average
 *
 * Backend pre-seeds empty buckets, so '12 weeks' renders exactly 12 bars
 * (was 11 before — the bug you flagged).
 */
const PRESETS = [
  { unit: 'days',   count: 7,  label: '7 derniers jours' },
  { unit: 'days',   count: 14, label: '14 derniers jours' },
  { unit: 'days',   count: 30, label: '30 derniers jours' },
  { unit: 'weeks',  count: 12, label: '12 dernières semaines' },
  { unit: 'weeks',  count: 26, label: '26 dernières semaines' },
  { unit: 'weeks',  count: 52, label: '52 dernières semaines' },
  { unit: 'months', count: 6,  label: '6 derniers mois' },
  { unit: 'months', count: 12, label: '12 derniers mois' },
  { unit: 'months', count: 24, label: '24 derniers mois' },
  { unit: 'years',  count: 3,  label: '3 dernières années' },
  { unit: 'years',  count: 5,  label: '5 dernières années' },
  { unit: 'all',    count: null, label: 'Depuis le début' },
];

const HistoricalAcquisitionChart = () => {
  const [presetIdx, setPresetIdx] = useState(4); // default: 12 dernières semaines
  const [data, setData] = useState([]);
  const [bucketUnit, setBucketUnit] = useState('weeks');
  const [total, setTotal] = useState(0);
  const [avgPerBucket, setAvgPerBucket] = useState(0);
  const [loading, setLoading] = useState(true);
  // App-wide branch filter — picking a branch on the layout bar refilters this chart too.
  const { branchId } = useBranch();

  const preset = PRESETS[presetIdx];

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const params = preset.unit === 'all'
          ? { unit: 'all' }
          : { unit: preset.unit, count: preset.count };
        if (branchId) params.branch_id = branchId;
        const res = await api.get('/owner/analytics/history/new-customers', { params });
        setData(res.data?.series || []);
        setBucketUnit(res.data?.bucket_unit || preset.unit);
        setTotal(res.data?.total_new_customers || 0);
        setAvgPerBucket(res.data?.average_per_bucket || 0);
      } catch (e) {
        console.error('Historical acquisition load failed', e);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [presetIdx, branchId]);

  // Friendly label for the "average" KPI based on bucket unit
  const avgLabel = (() => {
    if (bucketUnit === 'days')   return 'Moyenne par jour';
    if (bucketUnit === 'weeks')  return 'Moyenne par semaine';
    if (bucketUnit === 'months') return 'Moyenne par mois';
    if (bucketUnit === 'years')  return 'Moyenne par année';
    return 'Moyenne par période';
  })();

  // Convert an ISO week label like "2026-W18" → the Monday-of-that-week JS Date.
  // Owner-friendly labels like "5 Mai" instead of cryptic "W18" / "W46".
  const isoWeekToMonday = (s) => {
    const m = String(s).match(/^(\d{4})-W(\d+)$/);
    if (!m) return null;
    const year = parseInt(m[1], 10);
    const week = parseInt(m[2], 10);
    // Per ISO 8601, week 1 is the week containing January 4.
    const jan4 = new Date(Date.UTC(year, 0, 4));
    const jan4Dow = jan4.getUTCDay() || 7; // Sun(0) → 7
    const week1Mon = new Date(jan4);
    week1Mon.setUTCDate(jan4.getUTCDate() - jan4Dow + 1);
    const target = new Date(week1Mon);
    target.setUTCDate(week1Mon.getUTCDate() + (week - 1) * 7);
    return target;
  };

  const FR_MONTHS_SHORT = ['Jan','Fév','Mar','Avr','Mai','Jui','Jul','Aoû','Sep','Oct','Nov','Déc'];

  // Human-readable X-axis labels.
  // Weeks now show the week's Monday (e.g. "5 Mai") — way clearer for non-tech
  // owners and the labels naturally sort even across year boundaries.
  const formatTick = (raw) => {
    if (!raw) return '';
    const s = String(raw);
    if (bucketUnit === 'weeks') {
      const d = isoWeekToMonday(s);
      if (d) return `${d.getUTCDate()} ${FR_MONTHS_SHORT[d.getUTCMonth()]}`;
      return s;
    }
    if (bucketUnit === 'months') {
      const [, mm] = s.split('-');
      const idx = parseInt(mm, 10) - 1;
      return FR_MONTHS_SHORT[idx] || s;
    }
    if (bucketUnit === 'days') {
      const [, mm, dd] = s.split('-');
      return mm && dd ? `${dd}/${mm}` : s;
    }
    return s;
  };

  // Tooltip label — when hovering a week bar, show the full Monday→Sunday range
  // so the owner immediately sees which days the bar covers.
  const formatTooltipLabel = (raw) => {
    if (bucketUnit !== 'weeks') return formatTick(raw);
    const d = isoWeekToMonday(raw);
    if (!d) return raw;
    const end = new Date(d);
    end.setUTCDate(d.getUTCDate() + 6);
    return `Semaine du ${d.getUTCDate()} ${FR_MONTHS_SHORT[d.getUTCMonth()]} au ${end.getUTCDate()} ${FR_MONTHS_SHORT[end.getUTCMonth()]}`;
  };
  const tickInterval = data.length <= 12 ? 0 : Math.ceil(data.length / 12) - 1;

  return (
    <div className="rounded-xl bg-white p-6 mt-6" style={{ border: `1px solid ${C_PS.hairline}` }}>
      <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: `${C_PS.sage}1A`, color: C_PS.sage }}>
            <TrendingUp size={18} />
          </div>
          <div>
            <h2 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond', color: C_PS.inkDeep }}>
              Acquisition de clients dans le temps
            </h2>
            <p className="text-sm mt-1" style={{ color: C_PS.inkMute }}>
              Visualisez vos nouveaux clients par jour, semaine, mois ou année. Choisissez la période ci-contre.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            className="border rounded-lg px-3 py-2 text-sm font-medium"
            style={{ borderColor: C_PS.hairline, background: 'white', minWidth: 220 }}
            value={presetIdx}
            onChange={(e) => setPresetIdx(parseInt(e.target.value, 10))}
          >
            {PRESETS.map((p, i) => (
              <option key={i} value={i}>{p.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-4">
        <KPI
          label="Nouveaux clients sur la période"
          value={total}
          accent={C_PS.sage}
          icon={Users}
        />
        <KPI
          label={avgLabel}
          value={avgPerBucket}
          accent={C_PS.terracotta}
          icon={TrendingUp}
        />
        <KPI
          label="Granularité"
          value={
            ({ days: 'jours', weeks: 'semaines', months: 'mois', years: 'années' })[bucketUnit] || bucketUnit
          }
          accent={C_PS.lavender}
        />
      </div>

      <div className="h-72">
        {loading ? (
          <div className="h-full flex items-center justify-center text-sm" style={{ color: C_PS.inkMute }}>
            Chargement…
          </div>
        ) : data.length === 0 ? (
          <div className="h-full flex items-center justify-center text-sm" style={{ color: C_PS.inkMute }}>
            Aucune inscription sur cette période.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 10, right: 12, bottom: 24, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--flc-line, #E9E5E0)" />
              <XAxis
                dataKey="label"
                stroke="var(--flc-ink3, #57504A)"
                fontSize={10}
                interval={tickInterval}
                tickFormatter={formatTick}
                angle={-35}
                textAnchor="end"
                height={50}
                tick={{ dy: 4 }}
              />
              <YAxis stroke="var(--flc-ink3, #57504A)" fontSize={11} allowDecimals={false} width={36} />
              <Tooltip labelFormatter={formatTooltipLabel} />
              <Bar isAnimationActive={chartAnimation()} dataKey="count" fill={C_PS.sage} radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
};

const KPI = ({ label, value, accent, icon: Icon }) => (
  <div
    className="rounded-xl p-3 flex items-center gap-3"
    style={{
      background: `linear-gradient(135deg, white 0%, ${accent ? accent + '12' : '#F5F4F1'} 100%)`,
      border: `1px solid ${accent ? accent + '33' : C_PS.hairline}`,
    }}
  >
    {Icon && (
      <div
        className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
        style={{ background: 'white', boxShadow: `0 4px 10px ${accent || C_PS.terracotta}33` }}
      >
        <Icon size={16} style={{ color: accent || C_PS.terracotta }} />
      </div>
    )}
    <div className="min-w-0">
      <p className="text-[10px] font-bold uppercase tracking-widest truncate" style={{ color: C_PS.inkMute }}>{label}</p>
      <p className="text-lg font-bold leading-tight" style={{ color: C_PS.inkDeep }}>{value}</p>
    </div>
  </div>
);

export default HistoricalAcquisitionChart;
