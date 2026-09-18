import React, { useEffect, useMemo, useState } from 'react';
import api from '../lib/api';
import { Megaphone, Send, Eye, MousePointerClick, Users, X, CalendarDays, ExternalLink } from 'lucide-react';
import {
  ComposedChart, Bar, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts';
import { C as C_PS } from './PageShell';
import TimeRangeSelector from './TimeRangeSelector';
import { useBranch } from '../contexts/BranchContext';

/**
 * Visits-by-day chart with campaign send markers overlaid.
 *
 * - Bars = daily visit counts (last N days, default 30)
 * - Scatter dots in a contrasting purple = days a campaign was sent
 * - Click a dot to see that campaign's details + performance below
 *
 * Data comes from the additive backend endpoint
 *   GET /api/owner/analytics/history/visits-with-campaigns?days=N
 *
 * Existing visits/analytics endpoints are NOT touched.
 */
const CAMPAIGN_COLOR = 'var(--flc-info, #2F6BFF)'; // distinct info-blue marker — purple retired with the dual theme

const VisitsWithCampaignsChart = () => {
  const [range, setRange] = useState({ unit: 'days', count: 30 });
  const [data, setData] = useState({ visit_series: [], campaign_markers: [], totals: {} });
  const [loading, setLoading] = useState(true);
  const [selectedCampaignId, setSelectedCampaignId] = useState(null);

  // Click-a-bar drill-down: customers who visited on a specific day
  const [selectedDate, setSelectedDate] = useState(null);
  const [dayDetail, setDayDetail] = useState(null);          // { rows, visits_count, unique_customers, total_revenue }
  const [dayLoading, setDayLoading] = useState(false);
  const [dayError, setDayError] = useState(null);

  // Click-a-campaign drill-down: recipient list + who actually visited after
  const [campaignTracking, setCampaignTracking] = useState(null);
  const [campaignTrackingLoading, setCampaignTrackingLoading] = useState(false);

  const days = TimeRangeSelector.toDays(range) ?? 30;
  const { branchId } = useBranch();

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const params = { days };
        if (branchId) params.branch_id = branchId;
        const res = await api.get('/owner/analytics/history/visits-with-campaigns', { params });
        setData(res.data || { visit_series: [], campaign_markers: [] });
      } catch (e) {
        console.error('visits-with-campaigns load failed', e);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [days, branchId]);

  // Merge visits + campaign markers into a single dataset Recharts can render.
  // Each row has both a `visits` bar value and (if a campaign was sent that day)
  // a `campaign_y` scatter value pinned to a constant — visible above all bars.
  const chartData = useMemo(() => {
    const sentSet = new Set((data.campaign_markers || []).map((c) => c.sent_date));
    const maxVisit = Math.max(1, ...(data.visit_series || []).map((d) => d.visits || 0));
    const markerY = Math.ceil(maxVisit * 1.15) + 1;
    return (data.visit_series || []).map((d) => ({
      date: d.date,
      visits: d.visits,
      campaign_y: sentSet.has(d.date) ? markerY : null,
    }));
  }, [data]);

  const fmtTickDate = (s) => {
    if (!s) return '';
    const [, m, day] = s.split('-');
    return `${day}/${m}`;
  };
  const fmtFullDate = (d) => {
    if (!d) return '—';
    const dt = typeof d === 'string' ? new Date(d) : d;
    return dt.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  };

  // Find which campaign was sent on a given day (for click + tooltip)
  const campaignsOnDate = (date) =>
    (data.campaign_markers || []).filter((c) => c.sent_date === date);

  const selectedCampaign = (data.campaign_markers || []).find((c) => c.id === selectedCampaignId);

  // Custom tooltip — when hovering on a day with campaigns, show their names too
  const TooltipContent = ({ active, payload, label }) => {
    if (!active || !payload || !payload.length) return null;
    const visits = payload.find((p) => p.dataKey === 'visits')?.value ?? 0;
    const camps = campaignsOnDate(label);
    return (
      <div className="rounded-lg p-3 shadow-md text-xs"
        style={{ background: 'var(--flc-card, #FFFFFF)', border: `1px solid ${C_PS.hairline}` }}>
        <p className="font-bold mb-1" style={{ color: C_PS.inkDeep }}>{fmtFullDate(label)}</p>
        <p style={{ color: C_PS.inkMute }}>Visits: <span className="font-bold" style={{ color: C_PS.terracotta }}>{visits}</span></p>
        {camps.length > 0 && (
          <div className="mt-2 pt-2 border-t" style={{ borderColor: C_PS.hairline }}>
            <p className="text-[10px] uppercase font-bold tracking-widest mb-1" style={{ color: CAMPAIGN_COLOR }}>
              Campaign{camps.length > 1 ? 's' : ''} sent
            </p>
            {camps.map((c) => (
              <p key={c.id} className="font-semibold" style={{ color: CAMPAIGN_COLOR }}>• {c.name}</p>
            ))}
            <p className="text-[10px] mt-1" style={{ color: C_PS.inkMute }}>Click the marker to inspect.</p>
          </div>
        )}
      </div>
    );
  };

  const onScatterClick = (point) => {
    if (!point || !point.date) return;
    const camps = campaignsOnDate(point.date);
    if (camps.length === 0) return;
    setSelectedCampaignId(camps[0].id);
  };

  // Click-a-bar handler: fetch the customers who visited that day
  const onBarClick = (point) => {
    const date = point?.activeLabel || point?.date || point?.payload?.date;
    if (!date) return;
    if (selectedDate === date) {
      // Toggle off if user clicks the same bar again
      setSelectedDate(null);
      setDayDetail(null);
      return;
    }
    setSelectedDate(date);
  };

  // Fetch the day-detail (customers who visited) when selectedDate changes
  useEffect(() => {
    if (!selectedDate) return;
    let cancelled = false;
    setDayLoading(true);
    setDayError(null);
    setDayDetail(null);
    api.get('/owner/analytics/history/visits-on-day', { params: { date: selectedDate } })
      .then((res) => { if (!cancelled) setDayDetail(res.data); })
      .catch((e) => {
        if (!cancelled) setDayError(e?.response?.data?.detail || 'Failed to load customers for this day.');
      })
      .finally(() => { if (!cancelled) setDayLoading(false); });
    return () => { cancelled = true; };
  }, [selectedDate]);

  // Fetch full campaign tracking (recipients with name/email/opened/visited)
  // when a campaign is selected. Falls back gracefully if the endpoint errors.
  useEffect(() => {
    if (!selectedCampaignId) {
      setCampaignTracking(null);
      return;
    }
    let cancelled = false;
    setCampaignTrackingLoading(true);
    setCampaignTracking(null);
    api.get(`/owner/campaigns/${selectedCampaignId}/tracking`)
      .then((res) => { if (!cancelled) setCampaignTracking(res.data); })
      .catch(() => { /* silent — falls back to summary metrics only */ })
      .finally(() => { if (!cancelled) setCampaignTrackingLoading(false); });
    return () => { cancelled = true; };
  }, [selectedCampaignId]);

  return (
    // `vwcc` (Visits With Campaigns Chart) is a styling hook. The component
    // ships light-theme colours inline, so when it renders inside the dark
    // Analytics V2 skin, the dark theme overrides in index.css use this
    // class to swap surface + text colours to remain readable on a navy
    // background. The class is a no-op outside .av2-light-skin.
    <div className="rounded-xl bg-white p-6 mt-6 vwcc" style={{ border: `1px solid ${C_PS.hairline}` }}>
      <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: `${CAMPAIGN_COLOR}1A`, color: CAMPAIGN_COLOR }}>
            <Megaphone size={18} />
          </div>
          <div>
            <h2 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond', color: C_PS.inkDeep }}>
              Visits with campaign markers
            </h2>
            <p className="text-sm mt-1" style={{ color: C_PS.inkMute }}>
              Daily visits, with a purple marker on every day a campaign was sent.
              Click a marker to inspect that campaign's performance.
            </p>
          </div>
        </div>
        <TimeRangeSelector value={range} onChange={setRange} allowAllTime={false} />
      </div>

      <div className="grid grid-cols-3 gap-2 mb-4">
        <KPI label="Visits in range" value={data.totals?.visits ?? 0} />
        <KPI label="Campaigns sent" value={data.totals?.campaigns_sent ?? 0} accent={CAMPAIGN_COLOR} />
        <KPI label="Range" value={`${days} days`} />
      </div>

      <div className="h-80">
        {loading ? (
          <div className="h-full flex items-center justify-center text-sm" style={{ color: C_PS.inkMute }}>Loading…</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={chartData}
              margin={{ top: 16, right: 16, bottom: 8, left: 0 }}
              onClick={onBarClick}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--flc-line, #DCE3EF)" />
              <XAxis dataKey="date" tickFormatter={fmtTickDate} stroke="var(--flc-ink3, #334155)" fontSize={11}
                interval={Math.max(0, Math.floor(chartData.length / 12))} />
              <YAxis stroke="var(--flc-ink3, #334155)" fontSize={11} allowDecimals={false} />
              <Tooltip content={<TooltipContent />} />
              <Legend
                payload={[
                  { value: 'Visits (click a bar to see customers)', type: 'square', color: C_PS.terracotta },
                  { value: 'Campaign sent (click for recipients)', type: 'circle', color: CAMPAIGN_COLOR },
                ]}
              />
              <Bar
                dataKey="visits"
                fill={C_PS.terracotta}
                radius={[4, 4, 0, 0]}
                cursor="pointer"
                onClick={onBarClick}
              />
              <Scatter
                name="Campaign sent"
                dataKey="campaign_y"
                fill={CAMPAIGN_COLOR}
                shape="circle"
                onClick={onScatterClick}
                cursor="pointer"
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Day-detail panel — appears when a bar is clicked */}
      {selectedDate && (
        <div className="mt-4 rounded-xl p-4 relative"
          style={{ background: `${C_PS.terracotta}0D`, border: `1px solid ${C_PS.terracotta}33` }}>
          <button
            type="button"
            aria-label="Close day details"
            onClick={() => { setSelectedDate(null); setDayDetail(null); }}
            className="absolute top-3 right-3 w-7 h-7 rounded-full flex items-center justify-center hover:bg-white/40"
            style={{ color: C_PS.terracotta }}
          >
            <X size={14} />
          </button>
          <div className="flex items-center gap-2 mb-2">
            <CalendarDays size={14} style={{ color: C_PS.terracotta }} />
            <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: C_PS.terracotta }}>
              Customers on {fmtFullDate(selectedDate)}
            </p>
          </div>

          {dayLoading && (
            <p className="text-sm" style={{ color: C_PS.inkMute }}>Loading customers…</p>
          )}
          {dayError && (
            <p className="text-sm text-red-600">{dayError}</p>
          )}

          {dayDetail && !dayLoading && (
            <>
              <div className="grid grid-cols-3 gap-2 mb-3">
                <Metric label="Visits" value={dayDetail.visits_count} icon={Megaphone} />
                <Metric label="Unique customers" value={dayDetail.unique_customers} icon={Users} />
                <Metric label="Revenue" value={`€${(dayDetail.total_revenue ?? 0).toFixed(2)}`} icon={Send} />
              </div>

              {dayDetail.rows.length === 0 ? (
                <p className="text-sm italic" style={{ color: C_PS.inkMute }}>
                  No visits recorded on this day.
                </p>
              ) : (
                <CustomerList rows={dayDetail.rows} mode="day" />
              )}
            </>
          )}
        </div>
      )}

      {/* Campaign chips (click to inspect) */}
      {(data.campaign_markers || []).length > 0 && (
        <div className="mt-4 pt-4 border-t" style={{ borderColor: C_PS.hairline }}>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: C_PS.inkMute }}>
            Campaigns in this range — click to inspect
          </p>
          <div className="flex flex-wrap gap-2">
            {data.campaign_markers.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setSelectedCampaignId(c.id)}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold transition"
                style={{
                  background: selectedCampaignId === c.id ? CAMPAIGN_COLOR : `${CAMPAIGN_COLOR}1A`,
                  color: selectedCampaignId === c.id ? 'white' : CAMPAIGN_COLOR,
                  border: `1px solid ${CAMPAIGN_COLOR}55`,
                }}
              >
                <Send size={11} /> {c.name} · {fmtFullDate(c.sent_at)}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Selected campaign details */}
      {selectedCampaign && (
        <div className="mt-4 rounded-xl p-4 relative"
          style={{ background: `${CAMPAIGN_COLOR}0D`, border: `1px solid ${CAMPAIGN_COLOR}33` }}>
          <button
            type="button"
            aria-label="Close campaign details"
            onClick={() => setSelectedCampaignId(null)}
            className="absolute top-3 right-3 w-7 h-7 rounded-full flex items-center justify-center hover:bg-white/40"
            style={{ color: CAMPAIGN_COLOR }}
          >
            <X size={14} />
          </button>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-1" style={{ color: CAMPAIGN_COLOR }}>
            Campaign details
          </p>
          <h3 className="text-lg font-bold mb-1" style={{ color: C_PS.inkDeep }}>{selectedCampaign.name}</h3>
          <p className="text-xs mb-3" style={{ color: C_PS.inkMute }}>
            Sent {fmtFullDate(selectedCampaign.sent_at)} · status {selectedCampaign.status}
          </p>
          {selectedCampaign.content_preview && (
            <p className="text-sm mb-3 italic" style={{ color: C_PS.inkSoft }}>
              "{selectedCampaign.content_preview}"
            </p>
          )}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <Metric label="Targeted" value={selectedCampaign.targeted_count} icon={Users} />
            <Metric label="Delivered" value={selectedCampaign.delivered_count} icon={Send} />
            <Metric label="Opens" value={selectedCampaign.opens} icon={Eye} />
            <Metric label="Clicks" value={selectedCampaign.clicks} icon={MousePointerClick} />
            <Metric
              label="Visits attributed"
              value={selectedCampaign.visits_from_campaign}
              icon={Megaphone}
              hint="Visits within 15 days of send"
            />
          </div>

          {/* Recipient drill-down */}
          <div className="mt-4 pt-4 border-t" style={{ borderColor: `${CAMPAIGN_COLOR}33` }}>
            <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: CAMPAIGN_COLOR }}>
              Recipients & responses
            </p>
            {campaignTrackingLoading && (
              <p className="text-sm" style={{ color: C_PS.inkMute }}>Loading recipients…</p>
            )}
            {!campaignTrackingLoading && campaignTracking && Array.isArray(campaignTracking.recipients) && (
              campaignTracking.recipients.length === 0 ? (
                <p className="text-sm italic" style={{ color: C_PS.inkMute }}>
                  No recipients recorded for this campaign.
                </p>
              ) : (
                <CustomerList rows={campaignTracking.recipients} mode="campaign" />
              )
            )}
            {!campaignTrackingLoading && !campaignTracking && (
              <p className="text-sm italic" style={{ color: C_PS.inkMute }}>
                Recipient details unavailable.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

const KPI = ({ label, value, accent }) => (
  <div className="rounded-lg p-3" style={{ background: 'var(--flc-paper2, #F5F7FB)' }}>
    <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: C_PS.inkMute }}>{label}</p>
    <p className="text-lg font-bold" style={{ color: accent || C_PS.inkDeep }}>{value}</p>
  </div>
);

const Metric = ({ label, value, icon: Icon, hint }) => (
  <div className="rounded-lg p-2.5 bg-white" style={{ border: `1px solid ${C_PS.hairline}` }}>
    <div className="flex items-center gap-1.5 mb-0.5" style={{ color: CAMPAIGN_COLOR }}>
      <Icon size={12} />
      <span className="text-[10px] font-bold uppercase tracking-widest">{label}</span>
    </div>
    <p className="text-base font-bold" style={{ color: C_PS.inkDeep }}>{value ?? 0}</p>
    {hint && <p className="text-[10px] mt-0.5" style={{ color: C_PS.inkMute }}>{hint}</p>}
  </div>
);

/**
 * Generic table of customers used by both the day-detail and the campaign-detail panels.
 *
 *   mode="day"      — shows visit_time, amount_paid, points_awarded
 *   mode="campaign" — shows opened / visited badges
 */
const CustomerList = ({ rows, mode }) => {
  const tierStyle = (tier) => {
    const t = (tier || 'bronze').toLowerCase();
    if (t === 'vip')    return { bg: 'var(--flc-ink, #0F172A)', color: 'var(--flc-paper, #FFFFFF)' };
    if (t === 'gold')   return { bg: '#93B4FF', color: '#0F172A' };
    if (t === 'silver') return { bg: '#CBD5E1', color: '#0F172A' };
    return { bg: '#C7D7FF', color: '#1D4ED8' };
  };

  const fmtTime = (iso) => {
    if (!iso) return '—';
    const dt = new Date(iso);
    return dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="rounded-lg overflow-hidden bg-white" style={{ border: `1px solid ${C_PS.hairline}` }}>
      <div
        className="grid gap-2 px-3 py-2 text-[10px] font-bold uppercase tracking-widest"
        style={{
          color: C_PS.inkMute,
          background: '#F5F7FB',
          borderBottom: `1px solid ${C_PS.hairline}`,
          gridTemplateColumns: mode === 'day'
            ? '1.5fr 1.4fr 70px 70px 80px 70px'
            : '1.5fr 1.6fr 70px 90px 90px',
        }}
      >
        <span>Customer</span>
        <span>Email</span>
        <span>Tier</span>
        {mode === 'day' && <><span>Time</span><span>Amount</span><span>Points</span></>}
        {mode === 'campaign' && <><span>Opened</span><span>Visited</span></>}
      </div>
      <div className="max-h-72 overflow-y-auto divide-y" style={{ borderColor: C_PS.hairline }}>
        {rows.map((r, i) => {
          const ts = tierStyle(r.tier);
          return (
            <div
              key={(r.customer_id || r.visit_id || i) + '_' + i}
              className="grid gap-2 px-3 py-2 text-sm items-center"
              style={{
                gridTemplateColumns: mode === 'day'
                  ? '1.5fr 1.4fr 70px 70px 80px 70px'
                  : '1.5fr 1.6fr 70px 90px 90px',
              }}
            >
              <span className="font-semibold truncate" style={{ color: C_PS.inkDeep }}>
                {r.name || r.customer_name || '—'}
              </span>
              <span className="truncate text-xs" style={{ color: C_PS.inkMute }}>
                {r.email || '—'}
              </span>
              <span
                className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full text-center"
                style={{ background: ts.bg, color: ts.color }}
              >
                {(r.tier || 'bronze')}
              </span>

              {mode === 'day' && (
                <>
                  <span className="text-xs" style={{ color: C_PS.inkSoft }}>{fmtTime(r.visit_time)}</span>
                  <span className="text-xs font-semibold" style={{ color: C_PS.inkDeep }}>
                    €{(r.amount_paid ?? 0).toFixed(2)}
                  </span>
                  <span className="text-xs" style={{ color: C_PS.inkSoft }}>
                    +{r.points_awarded ?? 0}
                  </span>
                </>
              )}

              {mode === 'campaign' && (
                <>
                  <Pill on={r.opened} labelOn="Yes" labelOff="No" colorOn="#5B8DEF" />
                  <Pill on={r.visited || r.visited_after} labelOn="Yes" labelOff="No" colorOn="#2F6BFF" />
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Pill = ({ on, labelOn, labelOff, colorOn }) => (
  <span
    className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full text-center"
    style={{
      background: on ? `${colorOn}1A` : '#EEF2F9',
      color: on ? colorOn : '#94A3B8',
      border: `1px solid ${on ? colorOn + '44' : '#DCE3EF'}`,
    }}
  >
    {on ? labelOn : labelOff}
  </span>
);

export default VisitsWithCampaignsChart;
