import React, { useState, useEffect } from 'react';
import { PieChart, Pie, Cell, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Legend } from 'recharts';
import { chartAnimation } from '../lib/chartAnimation';
import { AlertCircle, TrendingUp, TrendingDown, Users, DollarSign, Eye, Activity, ChevronRight, X, CheckCircle2 } from 'lucide-react';
import api, { adminAPI } from '../lib/api';
import { PageHeader, StatCard, Section, C } from '../components/PageShell';

export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [enhancedAnalytics, setEnhancedAnalytics] = useState(null);
  const [planDistribution, setPlanDistribution] = useState([]);
  const [tenantGrowth, setTenantGrowth] = useState([]);
  const [topPerformers, setTopPerformers] = useState([]);
  const [businessHealth, setBusinessHealth] = useState({
    regular: { count: 0, list: [] },
    growing: { count: 0, list: [] },
    declining: { count: 0, list: [] },
  });
  const [recentActivity, setRecentActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [systemStatus, setSystemStatus] = useState('operational');
  const [selectedModal, setSelectedModal] = useState(null);
  const [modalData, setModalData] = useState([]);

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    try {
      setLoading(true);

      // allSettled so one slow/failing endpoint doesn't zero out the whole page
      const [statsRes, detailedRes, enhancedRes] = await Promise.allSettled([
        adminAPI.getAnalytics(),
        adminAPI.getDetailedAnalytics(),
        adminAPI.getEnhancedAnalytics(),
      ]);

      let anyFailed = false;

      if (statsRes.status === 'fulfilled') {
        const d = statsRes.value.data;
        setStats({
          totalBusinesses: d.total_tenants || 0,
          totalCustomers: d.total_customers || 0,
          monthlyRevenue: d.monthly_revenue || 0,
          activeBusinesses30Days: d.active_tenants_30d || 0,
          avgCustomersPerBusiness: d.total_tenants > 0
            ? Math.round(d.total_customers / d.total_tenants)
            : 0,
          platformVisitCount: d.total_visits || 0,
        });
      } else {
        anyFailed = true;
        console.error('getAnalytics failed:', statsRes.reason);
      }

      if (detailedRes.status === 'fulfilled') {
        setPlanDistribution(detailedRes.value.data.plans_distribution || []);
        setTenantGrowth((detailedRes.value.data.growth || []).map(g => ({ date: g.month, count: g.tenants })));
      } else {
        anyFailed = true;
        console.error('getDetailedAnalytics failed:', detailedRes.reason);
      }

      if (enhancedRes.status === 'fulfilled') {
        const d = enhancedRes.value.data;
        setEnhancedAnalytics(d);
        setTopPerformers(d.top_performers || []);
        setBusinessHealth({
          regular: {
            count: d.business_health?.regular || 0,
            list: d.business_health?.regular_list || [],
          },
          growing: {
            count: d.business_health?.growing || 0,
            list: d.business_health?.growing_list || [],
          },
          declining: {
            count: d.business_health?.declining || 0,
            list: d.business_health?.declining_list || [],
          },
        });
      } else {
        anyFailed = true;
        console.error('getEnhancedAnalytics failed:', enhancedRes.reason);
      }

      // Mock recent activity (in production, this would come from a real endpoint)
      setRecentActivity([
        { id: 1, action: 'New business registered', detail: 'Café Milano', timestamp: '2 hours ago' },
        { id: 2, action: 'Customer tier upgraded', detail: '5 customers upgraded to Gold', timestamp: '4 hours ago' },
        { id: 3, action: 'Campaign sent', detail: 'Loyalty boost campaign', timestamp: '6 hours ago' },
        { id: 4, action: 'Plan upgraded', detail: 'Basic → Gold', timestamp: '1 day ago' },
        { id: 5, action: 'Customer joined', detail: '12 new customers across platform', timestamp: '1 day ago' },
      ]);

      setSystemStatus(anyFailed ? 'degraded' : 'operational');
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error);
      setSystemStatus('degraded');
    } finally {
      setLoading(false);
    }
  };

  const PLAN_COLORS = {
    'Basic': '#4A5D23',
    'Gold': '#E3A869',
    'VIP': '#B85C38',
  };

  const BUSINESS_HEALTH_COLORS = {
    regular: '#2D7D9A',
    growing: '#4A5D23',
    declining: '#B85C38',
  };

  const handleKPIClick = (type) => {
    setSelectedModal(type);
    switch (type) {
      case 'businesses':
        setModalData(enhancedAnalytics?.top_performers?.map(p => ({ name: p.name, value: 1 })) || []);
        break;
      case 'customers':
        setModalData([{ name: 'Total Customers', value: stats?.totalCustomers || 0 }]);
        break;
      case 'visits':
        setModalData([{ name: 'Total Platform Visits', value: stats?.platformVisitCount || 0 }]);
        break;
      case 'regular':
        setModalData(businessHealth.regular.list);
        break;
      case 'growing':
        setModalData(businessHealth.growing.list);
        break;
      case 'declining':
        setModalData(businessHealth.declining.list);
        break;
      default:
        break;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="flex items-center gap-3" style={{ color: C.inkMute }}>
          <div className="w-2 h-2 rounded-full animate-pulse" style={{ background: C.terracotta }} />
          <span className="text-sm font-medium">Loading dashboard…</span>
        </div>
      </div>
    );
  }

  const operational = systemStatus === 'operational';

  return (
    <>
      <PageHeader
        eyebrow="Platform Overview"
        title="Admin Dashboard"
        description="Cross-tenant performance, growth, and business health at a glance."
        role="super_admin"
        actions={
          <div
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-full text-xs font-semibold"
            style={{
              background: operational ? `${C.sage}1A` : `${C.terracotta}1A`,
              color: operational ? C.sage : C.terracotta,
              border: `1px solid ${operational ? C.sage : C.terracotta}33`,
            }}
          >
            {operational ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
            <span>System {operational ? 'Operational' : 'Degraded'}</span>
          </div>
        }
      />

      {/* Top KPI row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        <StatCard
          label="Total Businesses"
          value={stats?.totalBusinesses || 0}
          sublabel="All active & inactive registrations"
          icon={Users}
          color={C.terracotta}
          onClick={() => handleKPIClick('businesses')}
        />
        <StatCard
          label="Total Customers"
          value={(stats?.totalCustomers || 0).toLocaleString()}
          sublabel="Unique end-users across all tenants"
          icon={Users}
          color={C.ochre}
          onClick={() => handleKPIClick('customers')}
        />
        <StatCard
          label="Monthly Revenue"
          value={`€${(stats?.monthlyRevenue || 0).toLocaleString()}`}
          sublabel="Subscription revenue this month"
          icon={DollarSign}
          color={C.sage}
          variant="dark"
        />
        <StatCard
          label="Active (30d)"
          value={stats?.activeBusinesses30Days || 0}
          sublabel="Tenants with activity in the last 30 days"
          icon={TrendingUp}
          color={C.teal}
        />
        <StatCard
          label="Avg Customers / Business"
          value={stats?.avgCustomersPerBusiness || 0}
          sublabel="Average customer base per tenant"
          icon={Activity}
          color={C.lavender}
        />
        <StatCard
          label="Platform Visits"
          value={(stats?.platformVisitCount || 0).toLocaleString()}
          sublabel="Total visits across all tenants"
          icon={Eye}
          color={C.amber}
          onClick={() => handleKPIClick('visits')}
        />
      </div>

      {/* Business Health row — three-state breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        {[
          { key: 'regular',  title: 'Regular',  count: businessHealth.regular.count,  hint: 'Active in last 14 days', color: C.teal,       icon: Activity },
          { key: 'growing',  title: 'Growing',  count: businessHealth.growing.count,  hint: 'New customers increasing', color: C.sage,    icon: TrendingUp },
          { key: 'declining',title: 'Declining',count: businessHealth.declining.count,hint: 'Fewer visits this period', color: C.terracotta, icon: TrendingDown },
        ].map((row) => (
          <button
            key={row.key}
            onClick={() => handleKPIClick(row.key)}
            className="relative w-full text-left p-6 rounded-2xl overflow-hidden transition-all bg-white hover:-translate-y-0.5 hover:shadow-lg"
            style={{ border: `1px solid ${C.hairline}`, boxShadow: '0 1px 2px rgba(28,25,23,0.04)' }}
          >
            <div
              aria-hidden="true"
              className="absolute -top-12 -right-12 w-40 h-40 rounded-full blur-3xl opacity-25"
              style={{ background: row.color }}
            />
            <div className="relative flex items-start justify-between mb-4">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-[0.14em]" style={{ color: C.inkMute }}>
                  Health
                </p>
                <h3
                  className="font-['Cormorant_Garamond'] text-2xl font-bold mt-1"
                  style={{ color: C.inkDeep }}
                >
                  {row.title}
                </h3>
              </div>
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center"
                style={{ background: `${row.color}1A`, color: row.color, border: `1px solid ${row.color}33` }}
              >
                <row.icon size={20} />
              </div>
            </div>
            <p
              className="font-['Cormorant_Garamond'] text-5xl font-bold leading-none mb-2"
              style={{ color: row.color }}
            >
              {row.count}
            </p>
            <p className="text-sm" style={{ color: C.inkMute }}>{row.hint}</p>
            <div className="mt-4 pt-4 flex items-center justify-between" style={{ borderTop: `1px solid ${C.hairline}` }}>
              <span className="text-xs font-medium" style={{ color: C.inkMute }}>
                See all {row.count} businesses
              </span>
              <ChevronRight size={14} style={{ color: row.color }} />
            </div>
          </button>
        ))}
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <Section title="Subscription Plans" hint="Distribution of tenants across plan tiers.">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie isAnimationActive={chartAnimation()}
                  data={planDistribution}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value }) => `${name}: ${value}`}
                  outerRadius={95}
                  innerRadius={55}
                  paddingAngle={3}
                  dataKey="value"
                >
                  {planDistribution.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={PLAN_COLORS[entry.name] || C.terracotta} stroke="white" strokeWidth={3} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </Section>

        <Section title="Business Growth" hint="New tenants joining the platform over time.">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={tenantGrowth}>
                <defs>
                  <linearGradient id="adminGrowth" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%"  stopColor={C.terracotta} stopOpacity={1} />
                    <stop offset="100%" stopColor={C.rose} stopOpacity={0.7} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={C.hairline} />
                <XAxis dataKey="date" stroke={C.inkMute} />
                <YAxis stroke={C.inkMute} />
                <Tooltip contentStyle={{ backgroundColor: C.cream, border: `1px solid ${C.hairline}`, borderRadius: 12 }} />
                <Line isAnimationActive={chartAnimation()}
                  type="monotone"
                  dataKey="count"
                  stroke="url(#adminGrowth)"
                  dot={{ fill: C.terracotta, r: 4 }}
                  activeDot={{ r: 6 }}
                  strokeWidth={3}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Section>
      </div>

      {/* Top performers */}
      <Section title="Top 5 Performing Businesses" hint="Highest engagement by total customer visits." className="mb-6">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={topPerformers.slice(0, 5)}>
              <defs>
                <linearGradient id="adminBar" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%"  stopColor={C.terracotta} />
                  <stop offset="100%" stopColor={C.rose} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={C.hairline} />
              <XAxis dataKey="name" stroke={C.inkMute} angle={-30} textAnchor="end" height={80} />
              <YAxis stroke={C.inkMute} />
              <Tooltip contentStyle={{ backgroundColor: C.cream, border: `1px solid ${C.hairline}`, borderRadius: 12 }} />
              <Bar isAnimationActive={chartAnimation()} dataKey="total_visits" fill="url(#adminBar)" radius={[10, 10, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Section>

      {/* Recent activity */}
      <Section title="Recent Activity" hint="Latest events across all tenants.">
        <div className="space-y-3">
          {recentActivity.length === 0 && (
            <p className="text-sm py-4 text-center" style={{ color: C.inkMute }}>
              No recent activity to show.
            </p>
          )}
          {recentActivity.map((activity, idx) => (
            <div
              key={activity.id || idx}
              className="flex items-start gap-3 p-3 rounded-xl transition-colors"
              style={{ background: idx % 2 === 0 ? C.bone : 'white' }}
            >
              <div
                className="w-2 h-2 rounded-full mt-2 shrink-0"
                style={{ background: `linear-gradient(135deg, ${C.terracotta}, ${C.rose})` }}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold" style={{ color: C.inkDeep }}>{activity.action}</p>
                <p className="text-xs" style={{ color: C.inkMute }}>{activity.detail}</p>
              </div>
              <p className="text-[11px] font-medium whitespace-nowrap" style={{ color: C.inkMute }}>
                {activity.timestamp}
              </p>
            </div>
          ))}
        </div>
      </Section>

      {/* Modal for KPI Details */}
      {selectedModal && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-2xl w-full max-h-[80vh] overflow-auto">
            <div className="sticky top-0 bg-white border-b border-[#E7E5E4] p-6 flex justify-between items-center">
              <h2 className="text-2xl font-bold text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond' }}>
                {selectedModal === 'businesses' && 'All Businesses'}
                {selectedModal === 'customers' && 'Total Customers'}
                {selectedModal === 'visits' && 'Platform Visits'}
                {selectedModal === 'regular' && 'Regular Businesses'}
                {selectedModal === 'growing' && 'Growing Businesses'}
                {selectedModal === 'declining' && 'Declining Businesses'}
              </h2>
              <button
                onClick={() => setSelectedModal(null)}
                className="text-[#A8A29E] hover:text-[#1C1917]"
              >
                <X size={24} />
              </button>
            </div>
            <div className="p-6">
              {selectedModal === 'customers' || selectedModal === 'visits' ? (
                <div className="text-center py-8">
                  <p className="text-3xl font-bold text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond' }}>
                    {modalData[0]?.value || 0}
                  </p>
                  <p className="text-[#57534E] mt-2">{modalData[0]?.name}</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-[#E7E5E4]">
                        <th className="py-3 px-4 font-semibold text-[#57534E]">Business Name</th>
                        <th className="py-3 px-4 font-semibold text-[#57534E]">Customers</th>
                        <th className="py-3 px-4 font-semibold text-[#57534E]">Visits</th>
                        <th className="py-3 px-4 font-semibold text-[#57534E]">Plan</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(selectedModal === 'businesses' ? enhancedAnalytics?.top_performers || [] : modalData).map((item, idx) => (
                        <tr key={idx} className="border-b border-[#E7E5E4] hover:bg-[#F3EFE7]">
                          <td className="py-3 px-4 text-[#1C1917]">{item.name}</td>
                          <td className="py-3 px-4 text-[#57534E]">{item.customer_count || 0}</td>
                          <td className="py-3 px-4 text-[#57534E]">{item.total_visits || 0}</td>
                          <td className="py-3 px-4">
                            <span className={`px-3 py-1 rounded-full text-xs font-bold uppercase
                              ${item.plan === 'vip' ? 'bg-[#B85C38] text-white' :
                                item.plan === 'gold' ? 'bg-[#E3A869] text-[#1C1917]' :
                                'bg-[#4A5D23] text-white'}`}>
                              {item.plan}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
