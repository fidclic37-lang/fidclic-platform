import React, { useEffect, useState } from 'react';
import { adminAPI } from '../lib/api';
import {
  PieChart, Pie, Cell,
  LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, AreaChart, Area, Legend,
} from 'recharts';
import { chartAnimation } from '../lib/chartAnimation';
import { X, TrendingDown, Users, Euro, Store, MapPin, Award, Megaphone, Star, MessageSquare, ThumbsUp, ThumbsDown, TrendingUp, Activity } from 'lucide-react';
import { PageHeader, C as C_PS } from '../components/PageShell';

const PLAN_COLORS = { basic: '#4A5D23', gold: '#E3A869', vip: '#B85C38', chain: '#7B3F00' };
const TIER_COLORS = { Bronze: '#8B6914', Silver: '#C0C0C0', Gold: '#E3A869' };
const ACQ_COLORS = ['#B85C38', '#E3A869', '#4A5D23', '#7B3F00', '#5B8DEF', '#AA6EBE', '#8B6914'];
const GPS_COLORS = { 'GPS Enabled': '#4A5D23', 'GPS Disabled': '#A8A29E' };

const StatCard = ({ icon: Icon, label, value, sublabel, accent = '#B85C38' }) => (
  <div className="bg-white p-5 rounded-xl border border-[#E7E5E4] flex items-center gap-4">
    <div className="w-12 h-12 rounded-full flex items-center justify-center text-white" style={{ background: accent }}>
      <Icon size={22} />
    </div>
    <div>
      <p className="text-xs text-[#57534E] uppercase tracking-wide font-semibold">{label}</p>
      <p className="text-2xl font-bold text-[#1C1917] leading-tight">{value}</p>
      {sublabel && <p className="text-xs text-[#8B8680] mt-0.5">{sublabel}</p>}
    </div>
  </div>
);

const AdminAnalyticsPage = () => {
  const [data, setData] = useState(null);
  const [reviewData, setReviewData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [drill, setDrill] = useState(null); // { title, rows, columns }
  const [drillLoading, setDrillLoading] = useState(false);

  const loadAnalytics = async () => {
    try {
      setLoading(true);
      setLoadError(null);
      const [res, rv] = await Promise.allSettled([
        adminAPI.getDetailedAnalytics(),
        adminAPI.getReviewAnalytics(),
      ]);
      if (res.status === 'fulfilled') setData(res.value.data);
      if (rv.status === 'fulfilled') setReviewData(rv.value.data);
      if (res.status === 'rejected') throw res.reason;
    } catch (e) {
      console.error('Failed to fetch admin analytics', e);
      setLoadError(
        e?.response?.status
          ? `Error ${e.response.status}: ${e.response.data?.detail || e.message}`
          : e?.message || 'Network error'
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAnalytics();
  }, []);

  const openDrill = async (title, fetcher, columns) => {
    setDrill({ title, rows: [], columns, loading: true });
    setDrillLoading(true);
    try {
      const res = await fetcher();
      const rows = Array.isArray(res.data) ? res.data : [];
      setDrill({ title, rows, columns });
    } catch (e) {
      console.error('Drill failed', e);
      setDrill({ title, rows: [], columns, error: 'Failed to load' });
    } finally {
      setDrillLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="flex items-center gap-3 text-sm font-medium" style={{ color: C_PS.inkMute }}>
          <div className="w-2 h-2 rounded-full animate-pulse" style={{ background: C_PS.terracotta }} />
          Loading analytics…
        </div>
      </div>
    );
  }

  if (loadError || !data) {
    return (
      <div className="max-w-xl mx-auto mt-12 rounded-2xl p-8 text-center"
           style={{ background: 'white', border: `1px solid ${C_PS.hairline}`, boxShadow: '0 1px 2px rgba(28,25,23,0.04)' }}>
        <h2 className="text-2xl font-bold mb-2" style={{ color: C_PS.terracotta, fontFamily: 'Cormorant Garamond' }}>
          Analytics failed to load
        </h2>
        <p className="text-sm mb-5" style={{ color: C_PS.inkMute }}>
          {loadError || 'The server did not return data. It may still be warming up.'}
        </p>
        <button
          onClick={loadAnalytics}
          className="px-5 py-2.5 rounded-full text-sm font-semibold text-white shadow-md hover:-translate-y-0.5 transition-all"
          style={{ background: `linear-gradient(135deg, ${C_PS.terracotta}, ${C_PS.rose})` }}
        >
          Retry
        </button>
      </div>
    );
  }

  const totals = data.totals || {};
  const plans = data.plans_distribution || [];
  const tiers = data.tier_distribution || [];
  const acquisitions = data.acquisition_sources || [];
  const gps = data.gps_breakdown || [];
  const growth = data.growth || [];
  const performance = data.tenant_performance || [];

  // Customer growth series (derive cumulative from monthly growth, using totals as end-point)
  const growthLine = growth.map((g, i) => ({
    date: g.month,
    iso: g.iso,
    count: g.tenants,
  }));

  // Revenue per plan
  const revenueByPlan = plans.map(p => {
    const price = ({ basic: 29, gold: 79, vip: 199, chain: 349 })[p.name.toLowerCase()] || 0;
    return { name: p.name, revenue: p.value * price, count: p.value };
  });

  // Businesses at risk: bottom-5 by visits
  const atRisk = [...performance].sort((a, b) => a.visits - b.visits).slice(0, 5);

  // Tenant column sets
  const COLS_SUMMARY = [
    { key: 'name', label: 'Business' },
    { key: 'plan', label: 'Plan', render: (v) => <span className="uppercase text-xs font-bold">{v}</span> },
    { key: 'customer_count', label: 'Customers' },
    { key: 'total_visits', label: 'Visits' },
  ];
  const COLS_TIER = [
    { key: 'name', label: 'Business' },
    { key: 'plan', label: 'Plan' },
    { key: 'tier_customer_count', label: 'Customers in tier' },
    { key: 'total_customers', label: 'Total customers' },
  ];
  const COLS_ACQ = [
    { key: 'name', label: 'Business' },
    { key: 'plan', label: 'Plan' },
    { key: 'acquisition_count', label: 'Via this source' },
    { key: 'total_customers', label: 'Total customers' },
  ];
  const COLS_GEO = [
    { key: 'name', label: 'Business' },
    { key: 'plan', label: 'Plan' },
    { key: 'customer_count', label: 'Customers' },
    { key: 'total_visits', label: 'Visits' },
    { key: 'geo_radius_meters', label: 'GPS radius (m)', render: (v) => v ?? '—' },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Platform Analytics"
        title="Global Analytics"
        description="Platform-wide insights across every business. Click any chart or metric to drill in."
        role="super_admin"
      />

      {/* Topline KPIs */}
      <section className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard icon={Store}  label="Businesses" value={totals.tenants ?? 0} accent="#B85C38" />
        <StatCard icon={Users}  label="Customers" value={(totals.customers ?? 0).toLocaleString()} accent="#4A5D23" />
        <StatCard icon={Award}  label="Visits" value={(totals.visits ?? 0).toLocaleString()} accent="#E3A869" />
        <StatCard icon={Euro}   label="Subscription MRR" value={`€${(totals.subscription_revenue_month ?? 0).toLocaleString()}`} sublabel="Recurring monthly" accent="#7B3F00" />
        <StatCard icon={Euro}   label="Customer GMV" value={`€${(totals.customer_spend_all_time ?? 0).toLocaleString()}`} sublabel="Lifetime tenant revenue" accent="#5B8DEF" />
      </section>

      {/* Row 1 — growth + plans */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Business Growth Over Time" hint="Click any dot to see the businesses created that month">
          <ResponsiveContainer width="100%" height={300}>
            <LineChart
              data={growthLine}
              onClick={(e) => {
                const p = e?.activePayload?.[0]?.payload;
                if (p?.iso) {
                  openDrill(
                    `Businesses created · ${p.date}`,
                    () => adminAPI.getTenantsByMonth(p.iso),
                    COLS_SUMMARY,
                  );
                }
              }}
              style={{ cursor: 'pointer' }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#E7E5E4" />
              <XAxis dataKey="date" stroke="#57534E" />
              <YAxis stroke="#57534E" />
              <Tooltip contentStyle={{ backgroundColor: '#F3EFE7', border: '1px solid #E7E5E4' }} />
              <Line isAnimationActive={chartAnimation()}
                type="monotone" dataKey="count" stroke="#B85C38" strokeWidth={2}
                dot={{ fill: '#B85C38', r: 5, style: { cursor: 'pointer' } }}
                activeDot={{
                  r: 8,
                  style: { cursor: 'pointer' },
                  onClick: (_, payload) => {
                    const p = payload?.payload;
                    if (p?.iso) {
                      openDrill(
                        `Businesses created · ${p.date}`,
                        () => adminAPI.getTenantsByMonth(p.iso),
                        COLS_SUMMARY,
                      );
                    }
                  },
                }}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Businesses by Subscription Plan" hint="Click a slice to list businesses on that plan">
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie isAnimationActive={chartAnimation()}
                data={plans} cx="50%" cy="50%" outerRadius={110}
                dataKey="value" labelLine={false}
                label={({ name, value }) => `${name}: ${value}`}
                onClick={(entry) => openDrill(
                  `${entry.name} plan businesses`,
                  () => adminAPI.getTenantsByPlan(entry.name.toLowerCase()),
                  COLS_SUMMARY,
                )}
                style={{ cursor: 'pointer' }}
              >
                {plans.map((e, i) => (
                  <Cell key={i} fill={PLAN_COLORS[e.name.toLowerCase()] || '#B85C38'} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>
      </section>

      {/* Row 2 — tier + acquisition */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Customer Tier Distribution" hint="Click a tier to rank businesses by customers in that tier">
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie isAnimationActive={chartAnimation()}
                data={tiers} cx="50%" cy="50%" outerRadius={110}
                dataKey="value" labelLine={false}
                label={({ name, value }) => `${name}: ${value}`}
                onClick={(entry) => openDrill(
                  `${entry.name} customers — ranked by business`,
                  () => adminAPI.getTenantsByTier(entry.name.toLowerCase()),
                  COLS_TIER,
                )}
                style={{ cursor: 'pointer' }}
              >
                {tiers.map((e, i) => (
                  <Cell key={i} fill={TIER_COLORS[e.name] || '#B85C38'} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Customer Acquisition Sources" hint="Click a bar to see which businesses acquired via that channel">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={acquisitions} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#E7E5E4" />
              <XAxis type="number" stroke="#57534E" />
              <YAxis type="category" dataKey="name" stroke="#57534E" width={110} />
              <Tooltip contentStyle={{ backgroundColor: '#F3EFE7', border: '1px solid #E7E5E4' }} />
              <Bar isAnimationActive={chartAnimation()}
                dataKey="value"
                radius={[0, 8, 8, 0]}
                cursor="pointer"
                onClick={(entry) => openDrill(
                  `Acquisition · ${entry.name}`,
                  () => adminAPI.getTenantsByAcquisition(entry.raw),
                  COLS_ACQ,
                )}
              >
                {acquisitions.map((e, i) => (
                  <Cell key={i} fill={ACQ_COLORS[i % ACQ_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </section>

      {/* Row 3 — revenue + GPS */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Subscription Revenue by Plan (Monthly)" hint="Click a bar to list businesses on that plan">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={revenueByPlan}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E7E5E4" />
              <XAxis dataKey="name" stroke="#57534E" />
              <YAxis stroke="#57534E" />
              <Tooltip contentStyle={{ backgroundColor: '#F3EFE7', border: '1px solid #E7E5E4' }} formatter={(v) => `€${v.toLocaleString()}`} />
              <Bar isAnimationActive={chartAnimation()}
                dataKey="revenue"
                radius={[8, 8, 0, 0]}
                cursor="pointer"
                onClick={(entry) => openDrill(
                  `${entry.name} plan · €${entry.revenue.toLocaleString()}/mo`,
                  () => adminAPI.getTenantsByPlan(entry.name.toLowerCase()),
                  COLS_SUMMARY,
                )}
              >
                {revenueByPlan.map((e, i) => (
                  <Cell key={i} fill={PLAN_COLORS[e.name.toLowerCase()] || '#B85C38'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Geolocation Feature Adoption" hint="Click to see which businesses use GPS proximity">
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie isAnimationActive={chartAnimation()}
                data={gps} cx="50%" cy="50%" outerRadius={110}
                dataKey="value" labelLine={false}
                label={({ name, value }) => `${name}: ${value}`}
                onClick={(entry) => openDrill(
                  entry.name,
                  () => adminAPI.getTenantsByGeo(entry.name === 'GPS Enabled'),
                  COLS_GEO,
                )}
                style={{ cursor: 'pointer' }}
              >
                {gps.map((e, i) => (
                  <Cell key={i} fill={GPS_COLORS[e.name] || '#B85C38'} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>
      </section>

      {/* Performance leaderboard */}
      <section className="bg-white p-6 rounded-xl border border-[#E7E5E4]">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond' }}>
            Business Performance Leaderboard
          </h2>
          <p className="text-xs text-[#8B8680]">Click a row to see the business's customers</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-sm">
            <thead>
              <tr className="border-b border-[#E7E5E4] text-[#57534E]">
                <th className="py-2 px-3">#</th>
                <th className="py-2 px-3">Business</th>
                <th className="py-2 px-3">Plan</th>
                <th className="py-2 px-3">Customers</th>
                <th className="py-2 px-3">Visits</th>
                <th className="py-2 px-3">Revenue</th>
                <th className="py-2 px-3">Avg pts</th>
                <th className="py-2 px-3">GPS</th>
              </tr>
            </thead>
            <tbody>
              {performance.map((t, i) => (
                <tr
                  key={t.id}
                  className="border-b border-[#E7E5E4] hover:bg-[#F3EFE7] transition-colors cursor-pointer"
                  onClick={() => openDrill(
                    `${t.name} · customers`,
                    () => adminAPI.getTenantCustomers(t.id),
                    [
                      { key: 'name', label: 'Customer' },
                      { key: 'email', label: 'Email' },
                      { key: 'tier', label: 'Tier' },
                      { key: 'visits', label: 'Visits' },
                      { key: 'total_amount_paid', label: 'Spent', render: (v) => `€${(v || 0).toFixed(2)}` },
                    ],
                  )}
                >
                  <td className="py-2 px-3 text-[#8B8680]">{i + 1}</td>
                  <td className="py-2 px-3 font-medium text-[#1C1917]">{t.name}</td>
                  <td className="py-2 px-3 uppercase text-xs font-bold">{t.plan}</td>
                  <td className="py-2 px-3">{t.customers}</td>
                  <td className="py-2 px-3">{t.visits}</td>
                  <td className="py-2 px-3">€{(t.revenue || 0).toLocaleString()}</td>
                  <td className="py-2 px-3">{t.avg_points}</td>
                  <td className="py-2 px-3">{t.geo_enabled ? <MapPin size={14} className="text-[#4A5D23]" /> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Customer reviews — global view + per-tenant leaderboard */}
      {reviewData && (
        <section className="bg-white p-6 rounded-xl border border-[#E7E5E4] space-y-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <h2 className="text-xl font-semibold text-[#1C1917] flex items-center gap-2" style={{ fontFamily: 'Cormorant Garamond' }}>
                <Star size={20} className="text-[#E3A869]" /> Customer reviews (all tenants)
              </h2>
              <p className="text-xs text-[#8B8680] mt-1 max-w-3xl">
                Every customer review across every business. Ratings are /10. Sentiment and topics
                are computed from the text at submission time — these numbers update live as new
                reviews come in.
              </p>
            </div>
            <span className="text-xs text-[#57534E] flex items-center gap-1">
              <MessageSquare size={14} /> {reviewData.total_reviews} total review{reviewData.total_reviews === 1 ? '' : 's'}
            </span>
          </div>

          {reviewData.total_reviews === 0 ? (
            <p className="text-sm text-[#8B8680] italic">No reviews in the system yet.</p>
          ) : (
            <>
              {/* 4 headline KPIs */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                <StatCard
                  icon={Star}
                  label="Average rating"
                  value={reviewData.average_rating != null ? `${reviewData.average_rating}/10` : '—'}
                  sublabel="Mean across every rating submitted"
                  accent="#E3A869"
                />
                <StatCard
                  icon={ThumbsDown}
                  label="Negative review rate"
                  value={`${reviewData.negative_review_rate_pct}%`}
                  sublabel="% at 1–4/10 · leading indicator of churn"
                  accent="#B85C38"
                />
                <StatCard
                  icon={ThumbsUp}
                  label="Sentiment score"
                  value={`${reviewData.sentiment_score > 0 ? '+' : ''}${reviewData.sentiment_score}`}
                  sublabel="Positive % − Negative % (range -100 .. +100)"
                  accent="#4A5D23"
                />
                <StatCard
                  icon={TrendingUp}
                  label="Review velocity"
                  value={`${reviewData.review_velocity.last_30d}`}
                  sublabel={`last 30d vs ${reviewData.review_velocity.prev_30d} prev · ${reviewData.review_velocity.delta_pct >= 0 ? '+' : ''}${reviewData.review_velocity.delta_pct}%`}
                  accent="#7B3F00"
                />
              </div>

              {/* Distribution + topic breakdown */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="border border-[#E7E5E4] rounded-lg p-4">
                  <p className="text-sm font-bold text-[#1C1917] mb-1 flex items-center gap-2">
                    <Star size={14} /> Rating distribution
                  </p>
                  <p className="text-xs text-[#8B8680] mb-3">
                    Count of reviews at each score across all businesses.
                  </p>
                  <div className="space-y-1">
                    {(() => {
                      const dist = reviewData.rating_distribution || {};
                      const max = Math.max(1, ...Object.values(dist).map(v => +v || 0));
                      return [10, 9, 8, 7, 6, 5, 4, 3, 2, 1].map((n) => {
                        const v = dist[String(n)] || 0;
                        const pct = Math.round((v / max) * 100);
                        const color = n >= 8 ? '#4A5D23' : n >= 5 ? '#E3A869' : '#B85C38';
                        return (
                          <div key={n} className="flex items-center gap-2 text-xs">
                            <span className="w-6 text-right font-semibold text-[#1C1917]">{n}</span>
                            <div className="flex-1 bg-[#F3EFE7] rounded h-4 overflow-hidden">
                              <div className="h-full rounded" style={{ width: `${pct}%`, backgroundColor: color }} />
                            </div>
                            <span className="w-10 text-right text-[#57534E]">{v}</span>
                          </div>
                        );
                      });
                    })()}
                  </div>
                </div>
                <div className="border border-[#E7E5E4] rounded-lg p-4">
                  <p className="text-sm font-bold text-[#1C1917] mb-1 flex items-center gap-2">
                    <Activity size={14} /> Topic breakdown (global)
                  </p>
                  <p className="text-xs text-[#8B8680] mb-3">
                    Themes customers mention most often across every business.
                  </p>
                  {(reviewData.topic_breakdown || []).length === 0 ? (
                    <p className="text-xs text-[#8B8680] italic">No text mentions to cluster yet.</p>
                  ) : (
                    <div className="space-y-2">
                      {reviewData.topic_breakdown.map((t) => {
                        const label = {
                          speed: '⚡ Service speed',
                          cleanliness: '🧼 Cleanliness',
                          staff: '🤝 Staff friendliness',
                          price: '💶 Price / value',
                          wait_time: '⏱ Wait time',
                        }[t.topic] || t.topic;
                        const avgColor = t.avg_rating >= 8 ? '#4A5D23' : t.avg_rating >= 6 ? '#E3A869' : '#B85C38';
                        return (
                          <div key={t.topic} className="p-2 rounded bg-[#FDFBF7] border border-[#E7E5E4]">
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-semibold text-[#1C1917]">{label}</span>
                              <span style={{ color: avgColor }} className="font-bold">
                                {t.avg_rating}/10 · {t.count} mentions
                              </span>
                            </div>
                            <p className="text-[10px] text-[#8B8680] mt-1">
                              {t.positive_pct}% positive · {t.negative_pct}% negative · {t.mention_pct}% of reviews
                            </p>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>

              {/* Per-tenant leaderboard */}
              {(reviewData.leaderboard || []).length > 0 && (
                <div className="border border-[#E7E5E4] rounded-lg p-4">
                  <p className="text-sm font-bold text-[#1C1917] mb-3 flex items-center gap-2">
                    <Store size={14} /> Business rating leaderboard
                    <span className="text-xs text-[#8B8680] font-normal">(min. 3 reviews)</span>
                  </p>
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead className="bg-[#FDFBF7] text-[#57534E]">
                        <tr>
                          <th className="text-left px-3 py-2 font-semibold">Business</th>
                          <th className="text-right px-3 py-2 font-semibold">Avg rating</th>
                          <th className="text-right px-3 py-2 font-semibold">Reviews</th>
                          <th className="text-right px-3 py-2 font-semibold">Neg rate</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#E7E5E4]">
                        {reviewData.leaderboard.map((l) => {
                          const avgColor = l.average_rating >= 8 ? '#4A5D23' : l.average_rating >= 6 ? '#E3A869' : '#B85C38';
                          return (
                            <tr key={l.tenant_id}>
                              <td className="px-3 py-2 text-[#1C1917]">{l.tenant_name}</td>
                              <td className="px-3 py-2 text-right font-bold" style={{ color: avgColor }}>
                                {l.average_rating}/10
                              </td>
                              <td className="px-3 py-2 text-right text-[#57534E]">{l.review_count}</td>
                              <td className="px-3 py-2 text-right text-[#B85C38]">{l.negative_rate_pct}%</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {/* At risk */}
      <section className="bg-white p-6 rounded-xl border border-[#E7E5E4]">
        <div className="flex items-center gap-2 mb-4">
          <TrendingDown size={20} className="text-[#B85C38]" />
          <h2 className="text-xl font-semibold text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond' }}>
            Businesses at Risk
          </h2>
        </div>
        <p className="text-sm text-[#57534E] mb-4">Click a row for the customer list — a quick way to target a recovery campaign.</p>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-sm">
            <thead>
              <tr className="border-b border-[#E7E5E4] text-[#57534E]">
                <th className="py-2 px-3">Business</th>
                <th className="py-2 px-3">Plan</th>
                <th className="py-2 px-3">Visits</th>
                <th className="py-2 px-3">Customers</th>
                <th className="py-2 px-3">Revenue</th>
              </tr>
            </thead>
            <tbody>
              {atRisk.map((t) => (
                <tr
                  key={t.id}
                  className="border-b border-[#E7E5E4] hover:bg-[#F3EFE7] transition-colors cursor-pointer"
                  onClick={() => openDrill(
                    `${t.name} · customers`,
                    () => adminAPI.getTenantCustomers(t.id),
                    [
                      { key: 'name', label: 'Customer' },
                      { key: 'email', label: 'Email' },
                      { key: 'tier', label: 'Tier' },
                      { key: 'visits', label: 'Visits' },
                      { key: 'last_visit_date', label: 'Last visit', render: (v) => v ? new Date(v).toLocaleDateString() : '—' },
                    ],
                  )}
                >
                  <td className="py-2 px-3 font-medium text-[#1C1917]">{t.name}</td>
                  <td className="py-2 px-3 uppercase text-xs font-bold">{t.plan}</td>
                  <td className="py-2 px-3">{t.visits}</td>
                  <td className="py-2 px-3">{t.customers}</td>
                  <td className="py-2 px-3">€{(t.revenue || 0).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Drill-down modal */}
      {drill && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setDrill(null)}>
          <div className="bg-white rounded-xl max-w-5xl w-full max-h-[85vh] overflow-auto p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-2xl font-bold text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond' }}>
                {drill.title}
              </h3>
              <button onClick={() => setDrill(null)} className="text-[#A8A29E] hover:text-[#1C1917]"><X size={22} /></button>
            </div>
            {drillLoading ? (
              <p className="text-[#57534E] py-8 text-center">Loading…</p>
            ) : drill.rows.length === 0 ? (
              <p className="text-[#57534E] py-8 text-center">No matching records.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-[#E7E5E4] text-[#57534E]">
                      {drill.columns.map((c) => <th key={c.key} className="py-2 px-3">{c.label}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {drill.rows.map((r, i) => (
                      <tr key={i} className="border-b border-[#E7E5E4]">
                        {drill.columns.map((c) => (
                          <td key={c.key} className="py-2 px-3 text-[#1C1917]">
                            {c.render ? c.render(r[c.key]) : (r[c.key] ?? '—')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

const ChartCard = ({ title, hint, children }) => (
  <div className="bg-white p-6 rounded-xl border border-[#E7E5E4]">
    <h2 className="text-xl font-semibold text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond' }}>{title}</h2>
    {hint && <p className="text-xs text-[#8B8680] mt-1 mb-3">{hint}</p>}
    {children}
  </div>
);

export default AdminAnalyticsPage;
