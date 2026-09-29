import React, { useEffect, useState } from 'react';
import { ownerAPI } from '../lib/api';
import {
  AlertTriangle, TrendingDown, Euro, Users, Clock, MapPin, Calendar,
  Send, UserPlus, Trash2, CreditCard, Zap, RefreshCw, ChevronRight, X,
  Sparkles, Wand2,
} from 'lucide-react';
import { PageHeader, C as C_PS } from '../components/PageShell';
import LoadingDistraction from '../components/LoadingDistraction';
import { useBranch } from '../contexts/BranchContext';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, PieChart, Pie, Cell, Legend,
} from 'recharts';
import { chartAnimation } from '../lib/chartAnimation';

// Small reusable card shell
const Card = ({ children, className = '' }) => (
  <div className={`bg-white border border-[#E9E5E0] rounded-xl p-5 ${className}`}>{children}</div>
);

const SectionHead = ({ icon: Icon, title, subtitle }) => (
  <div className="flex items-start gap-3 mb-4">
    <div className="w-10 h-10 rounded-lg bg-[#B85C38]/10 flex items-center justify-center shrink-0">
      <Icon className="w-5 h-5 text-[#B85C38]" />
    </div>
    <div>
      <h2 className="text-lg font-bold text-[#171412]" style={{ fontFamily: 'Cormorant Garamond' }}>{title}</h2>
      {subtitle && <p className="text-xs text-[#57504A]">{subtitle}</p>}
    </div>
  </div>
);

const StatPill = ({ label, value, hint, tone = 'default' }) => {
  const toneMap = {
    default: 'bg-[#F5F4F1] text-[#171412]',
    danger:  'bg-red-50 text-[#991B1B]',
    warning: 'bg-amber-50 text-[#92400E]',
    success: 'bg-emerald-50 text-[#065F46]',
  };
  return (
    <div className={`rounded-lg px-3 py-2 ${toneMap[tone]}`}>
      <p className="text-xs uppercase tracking-wide font-semibold opacity-75">{label}</p>
      <p className="text-xl font-bold leading-tight">{value}</p>
      {hint && <p className="text-[10px] opacity-70 mt-0.5">{hint}</p>}
    </div>
  );
};

export default function InsightsPage() {
  const { branchId } = useBranch();
  const [alerts, setAlerts] = useState([]);
  const [churn, setChurn] = useState(null);
  const [ltv, setLtv] = useState(null);
  const [timeSeg, setTimeSeg] = useState(null);
  const [city, setCity] = useState(null);
  const [activeCards, setActiveCards] = useState(null);
  const [monthly, setMonthly] = useState(null);
  const [reactivation, setReactivation] = useState(null);
  const [team, setTeam] = useState([]);
  const [senderName, setSenderName] = useState('');
  const [senderNameSaving, setSenderNameSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [addTeamForm, setAddTeamForm] = useState({ email: '', password: '', role: 'staff' });
  // Proactive alerts feed + AI suggestions cards + LTV cohort breakdown.
  const [proactiveAlerts, setProactiveAlerts] = useState(null);
  const [aiSuggestions, setAiSuggestions] = useState([]);
  const [ltvBreakdown, setLtvBreakdown] = useState(null);
  // Open the campaign composer at /dashboard/campaigns with a pre-filled draft.
  const useSuggestion = (s) => {
    if (!s?.draft) return;
    try {
      sessionStorage.setItem('campaignHandoff', JSON.stringify({
        suggested_name: s.draft.name,
        suggested_body: s.draft.body,
        suggested_source: s.draft.source || 'push',
        filter: s.filter || {},
      }));
    } catch (_e) { /* sessionStorage unavailable, fall through */ }
    window.location.href = '/dashboard/campaigns';
  };

  // AI suggestions panel state
  const [aiQuestion, setAiQuestion] = useState('');
  const [aiAnswer, setAiAnswer] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(null);
  const AI_PRESET_QUESTIONS = [
    "What are the 3 most urgent things I should do this week?",
    "Which customer segments should I reactivate first — and with what offer?",
    "My best-paying customers: what do they have in common?",
    "Why is my churn rate where it is, and how do I lower it?",
    "Which day/time should I send my next campaign for maximum opens?",
    "Write me a re-engagement message for customers who haven't visited in 30 days.",
  ];

  const askAI = async (question) => {
    const q = (question ?? aiQuestion).trim();
    if (!q) return;
    setAiLoading(true);
    setAiError(null);
    setAiAnswer('');
    try {
      const res = await ownerAPI.aiQuery({ message: q });
      // The backend returns the answer in `reply`. Also fall back to legacy
      // field names so the UI still works if the response shape changes later.
      const answer =
        res?.data?.reply ||
        res?.data?.response ||
        res?.data?.answer ||
        res?.data?.message ||
        '';
      if (!answer) {
        setAiError('The AI returned an empty answer — try rephrasing your question.');
      } else {
        setAiAnswer(answer);
      }
    } catch (e) {
      // Surface the backend's own detail (e.g. "Daily AI query limit reached").
      const msg = e?.response?.data?.detail || e?.message || 'AI request failed';
      setAiError(msg);
    } finally {
      setAiLoading(false);
    }
  };

  const loadAll = async () => {
    setLoading(true);
    // Branch-aware params — picking a branch on the global selector refilters
    // every insight panel that supports branch filtering.
    const bp = branchId ? { branch_id: branchId } : undefined;
    const results = await Promise.allSettled([
      ownerAPI.getAlerts(bp),
      ownerAPI.getChurn(bp),
      ownerAPI.getLTV(bp),
      ownerAPI.getTimeSegmentation(bp),
      ownerAPI.getCityBreakdown(bp),
      ownerAPI.getActiveCards(bp),
      ownerAPI.getMonthlyReport(),
      ownerAPI.getReactivationTemplates(bp),
      ownerAPI.listTeam(),
      ownerAPI.getTenant(),
      // New proactive panels
      ownerAPI.getProactiveAlerts(bp),
      ownerAPI.getAiSuggestions(bp),
      ownerAPI.getLtvBreakdown(bp),
    ]);
    const [a, ch, l, t, c, ac, mr, rt, tm, tenant, pa, ai, lb] = results;
    if (a.status === 'fulfilled') setAlerts(a.value.data.alerts || []);
    if (ch.status === 'fulfilled') setChurn(ch.value.data);
    if (l.status === 'fulfilled') setLtv(l.value.data);
    if (t.status === 'fulfilled') setTimeSeg(t.value.data);
    if (c.status === 'fulfilled') setCity(c.value.data);
    if (ac.status === 'fulfilled') setActiveCards(ac.value.data);
    if (mr.status === 'fulfilled') setMonthly(mr.value.data);
    if (rt.status === 'fulfilled') setReactivation(rt.value.data);
    if (tm.status === 'fulfilled') setTeam(tm.value.data.members || []);
    if (tenant.status === 'fulfilled') {
      setSenderName(tenant.value.data?.campaign_sender_name || tenant.value.data?.name || '');
    }
    if (pa.status === 'fulfilled') setProactiveAlerts(pa.value.data);
    if (ai.status === 'fulfilled') setAiSuggestions(ai.value.data?.suggestions || []);
    if (lb.status === 'fulfilled') setLtvBreakdown(lb.value.data);
    setLoading(false);
  };

  // Re-fetch when the user picks a different branch on the global selector.
  useEffect(() => { loadAll(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [branchId]);

  const saveSenderName = async () => {
    setSenderNameSaving(true);
    try {
      await ownerAPI.updateSenderName(senderName);
      alert('Sender name saved.');
    } catch (e) {
      alert('Failed to save sender name: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setSenderNameSaving(false);
    }
  };

  const addTeamMember = async (e) => {
    e.preventDefault();
    try {
      await ownerAPI.addTeamMember(addTeamForm);
      setAddTeamForm({ email: '', password: '', role: 'staff' });
      const tm = await ownerAPI.listTeam();
      setTeam(tm.data.members || []);
    } catch (e) {
      alert('Failed: ' + (e?.response?.data?.detail || e.message));
    }
  };

  const removeTeamMember = async (email) => {
    if (!confirm(`Remove ${email}?`)) return;
    try {
      await ownerAPI.removeTeamMember(email);
      setTeam((prev) => prev.filter((m) => m.email !== email));
    } catch (e) {
      alert('Failed: ' + (e?.response?.data?.detail || e.message));
    }
  };

  if (loading) {
    return (
      <div className="py-12 px-4">
        <LoadingDistraction title="Chargement des insights" message="On compile vos alertes et recommandations…" />
      </div>
    );
  }

  const alertToneBg = {
    danger: 'bg-red-50 border-red-200',
    warning: 'bg-amber-50 border-amber-200',
    success: 'bg-emerald-50 border-emerald-200',
    info: 'bg-sky-50 border-sky-200',
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="AI-Powered"
        title="Insights"
        description="Everything the platform has learned about your customers — patterns, predictions, and growth opportunities."
        role="business_owner"
        actions={
          <button
            onClick={loadAll}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold transition-all hover:-translate-y-0.5"
            style={{ background: 'var(--flc-card, #FFFFFF)', border: `1px solid ${C_PS.hairline}`, color: C_PS.inkSoft }}
          >
            <RefreshCw size={14} /> Refresh
          </button>
        }
      />

      {/* ─────────── Smart Alerts feed ─────────── */}
      {proactiveAlerts && Array.isArray(proactiveAlerts.alerts) && proactiveAlerts.alerts.length > 0 && (
        <div
          className="rounded-2xl p-6 relative overflow-hidden"
          style={{ background: 'var(--flc-card, #FFFFFF)', border: `1px solid ${C_PS.hairline}`, boxShadow: '0 1px 2px rgba(28,25,23,0.04)' }}
        >
          <div aria-hidden="true" className="absolute -top-20 -right-20 w-72 h-72 rounded-full blur-3xl opacity-15 pointer-events-none"
               style={{ background: C_PS.terracotta }} />
          <header className="relative flex items-end justify-between gap-4 mb-5">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.18em]" style={{ color: C_PS.terracotta }}>
                Auto-Detected · Today
              </p>
              <h2 className="font-['Cormorant_Garamond'] text-3xl font-bold mt-1" style={{ color: C_PS.inkDeep }}>
                Smart Alerts
              </h2>
              <p className="text-sm mt-1" style={{ color: C_PS.inkMute }}>
                Patterns the platform spotted in your data this week, ranked by urgency.
              </p>
            </div>
            <div className="flex gap-1.5">
              {Object.entries(proactiveAlerts.counts_by_severity || {}).filter(([, n]) => n > 0).map(([sev, n]) => {
                const palette = {
                  critical: { bg: '#FEE2E2', fg: '#991B1B' },
                  warning:  { bg: '#FEF3C7', fg: '#92400E' },
                  win:      { bg: `${C_PS.sage}1A`, fg: C_PS.sage },
                  info:     { bg: `${C_PS.sky}1A`, fg: C_PS.sky },
                }[sev] || { bg: C_PS.bone, fg: C_PS.inkMute };
                return (
                  <span key={sev} className="text-[10px] font-bold uppercase tracking-widest px-2.5 py-1 rounded-full"
                        style={{ background: palette.bg, color: palette.fg }}>
                    {n} {sev}
                  </span>
                );
              })}
            </div>
          </header>

          <div className="relative grid grid-cols-1 md:grid-cols-2 gap-3">
            {proactiveAlerts.alerts.map((a) => {
              const sevPalette = {
                critical: { accent: '#DC2626', bg: '#FEF2F2', icon: AlertTriangle, label: 'Critical' },
                warning:  { accent: '#D97706', bg: '#FFFBEB', icon: AlertTriangle, label: 'Warning' },
                win:      { accent: C_PS.sage, bg: `${C_PS.sage}0D`, icon: Sparkles,  label: 'Win'    },
                info:     { accent: C_PS.sky,  bg: `${C_PS.sky}0D`,  icon: Calendar,  label: 'Info'   },
              }[a.severity] || { accent: C_PS.inkMute, bg: 'white', icon: AlertTriangle, label: 'Note' };
              const Icon = sevPalette.icon;
              return (
                <div
                  key={a.id}
                  className="relative p-4 rounded-xl flex gap-3"
                  style={{ background: sevPalette.bg, border: `1px solid ${sevPalette.accent}33` }}
                >
                  <div
                    className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                    style={{ background: `${sevPalette.accent}1A`, color: sevPalette.accent, border: `1px solid ${sevPalette.accent}33` }}
                  >
                    <Icon size={16} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: sevPalette.accent }}>
                        {sevPalette.label}
                      </p>
                      {a.metric && (
                        <span className="text-xs font-bold" style={{ color: sevPalette.accent }}>{a.metric}</span>
                      )}
                    </div>
                    <p className="text-sm font-semibold leading-tight" style={{ color: C_PS.inkDeep }}>{a.title}</p>
                    <p className="text-xs leading-relaxed mt-1" style={{ color: C_PS.inkMute }}>{a.body}</p>
                    {a.action && (
                      <a
                        href={a.action}
                        className="inline-flex items-center gap-1 mt-2 text-xs font-semibold hover:underline"
                        style={{ color: sevPalette.accent }}
                      >
                        Take action <ChevronRight size={12} />
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ─────────── AI Suggestions ─────────── */}
      {aiSuggestions.length > 0 && (
        <div
          className="rounded-2xl p-6 relative overflow-hidden"
          style={{ background: 'var(--flc-card, #FFFFFF)', border: `1px solid ${C_PS.hairline}`, boxShadow: '0 1px 2px rgba(28,25,23,0.04)' }}
        >
          <div aria-hidden="true" className="absolute -top-20 -right-20 w-72 h-72 rounded-full blur-3xl opacity-15 pointer-events-none"
               style={{ background: C_PS.lavender }} />
          <header className="relative flex items-end justify-between gap-4 mb-5">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.18em]" style={{ color: C_PS.lavender }}>
                AI · What to do today
              </p>
              <h2 className="font-['Cormorant_Garamond'] text-3xl font-bold mt-1" style={{ color: C_PS.inkDeep }}>
                Recommended Actions
              </h2>
              <p className="text-sm mt-1" style={{ color: C_PS.inkMute }}>
                Pre-built campaign drafts targeting the segments that need attention right now.
              </p>
            </div>
          </header>

          <div className="relative grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {aiSuggestions.map((s) => (
              <div
                key={s.id}
                className="relative p-5 rounded-2xl flex flex-col"
                style={{
                  background: `linear-gradient(155deg, ${C_PS.bone} 0%, white 60%)`,
                  border: `1px solid ${C_PS.hairline}`,
                }}
              >
                <div className="text-3xl mb-2">{s.icon || '✨'}</div>
                <h3 className="font-['Cormorant_Garamond'] text-xl font-bold leading-tight mb-1" style={{ color: C_PS.inkDeep }}>
                  {s.title}
                </h3>
                <p className="text-xs leading-relaxed" style={{ color: C_PS.inkMute }}>
                  {s.why}
                </p>
                <div className="mt-3 mb-4 inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest self-start px-2 py-1 rounded-full"
                     style={{ background: `${C_PS.lavender}1A`, color: C_PS.lavender, border: `1px solid ${C_PS.lavender}33` }}>
                  <Users size={10} /> {s.audience_count} customers
                </div>
                <button
                  onClick={() => useSuggestion(s)}
                  className="mt-auto inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-full text-xs font-semibold text-white transition-all shadow-md hover:-translate-y-0.5"
                  style={{ background: `linear-gradient(135deg, ${C_PS.lavender}, ${C_PS.terracotta})` }}
                >
                  <Send size={12} /> Open in composer
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ─────────── LTV Breakdown ─────────── */}
      {ltvBreakdown && ltvBreakdown.network && (ltvBreakdown.network.customers || 0) > 0 && (
        <div
          className="rounded-2xl p-6 relative overflow-hidden"
          style={{ background: 'var(--flc-card, #FFFFFF)', border: `1px solid ${C_PS.hairline}`, boxShadow: '0 1px 2px rgba(28,25,23,0.04)' }}
        >
          <div aria-hidden="true" className="absolute -top-20 -right-20 w-72 h-72 rounded-full blur-3xl opacity-15 pointer-events-none"
               style={{ background: C_PS.sage }} />
          <header className="relative flex items-end justify-between gap-4 mb-5">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.18em]" style={{ color: C_PS.sage }}>
                Lifetime Value
              </p>
              <h2 className="font-['Cormorant_Garamond'] text-3xl font-bold mt-1" style={{ color: C_PS.inkDeep }}>
                LTV Breakdown
              </h2>
              <p className="text-sm mt-1" style={{ color: C_PS.inkMute }}>
                What each customer is worth, by tier and acquisition cohort.
              </p>
            </div>
          </header>

          <div className="relative grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            <div className="p-3 rounded-xl" style={{ background: C_PS.bone, border: `1px solid ${C_PS.hairline}` }}>
              <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: C_PS.inkMute }}>Avg LTV</p>
              <p className="font-['Cormorant_Garamond'] text-2xl font-bold mt-1" style={{ color: C_PS.inkDeep }}>
                €{ltvBreakdown.network.avg_ltv}
              </p>
              <p className="text-[10px] mt-1" style={{ color: C_PS.inkMute }}>Across {ltvBreakdown.network.customers} customers</p>
            </div>
            <div className="p-3 rounded-xl" style={{ background: C_PS.bone, border: `1px solid ${C_PS.hairline}` }}>
              <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: C_PS.inkMute }}>Median LTV</p>
              <p className="font-['Cormorant_Garamond'] text-2xl font-bold mt-1" style={{ color: C_PS.inkDeep }}>
                €{ltvBreakdown.network.median_ltv}
              </p>
              <p className="text-[10px] mt-1" style={{ color: C_PS.inkMute }}>50% spend more, 50% less</p>
            </div>
            <div className="p-3 rounded-xl" style={{ background: `${C_PS.sage}1A`, border: `1px solid ${C_PS.sage}33` }}>
              <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: C_PS.sage }}>12-mo Predicted</p>
              <p className="font-['Cormorant_Garamond'] text-2xl font-bold mt-1" style={{ color: C_PS.inkDeep }}>
                €{ltvBreakdown.network.predicted_12mo}
              </p>
              <p className="text-[10px] mt-1" style={{ color: C_PS.inkMute }}>
                Forward-looking · {ltvBreakdown.network.repeat_rate_pct}% repeat
              </p>
            </div>
            <div className="p-3 rounded-xl" style={{ background: `${C_PS.terracotta}1A`, border: `1px solid ${C_PS.terracotta}33` }}>
              <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: C_PS.terracotta }}>Top 10% concentration</p>
              <p className="font-['Cormorant_Garamond'] text-2xl font-bold mt-1" style={{ color: C_PS.inkDeep }}>
                {ltvBreakdown.top_decile_share_pct}%
              </p>
              <p className="text-[10px] mt-1" style={{ color: C_PS.inkMute }}>of revenue from top 10% spenders</p>
            </div>
          </div>

          {ltvBreakdown.by_tier && ltvBreakdown.by_tier.length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: C_PS.inkMute }}>
                Average LTV by tier
              </p>
              <div className="space-y-2">
                {ltvBreakdown.by_tier.map((row) => {
                  const tierColors = {
                    vip:    C_PS.terracotta,
                    gold:   C_PS.ochre,
                    silver: C_PS.lavender,
                    bronze: C_PS.sage,
                  };
                  const accent = tierColors[row.tier] || C_PS.inkMute;
                  const widthPct = ltvBreakdown.by_tier[0]?.avg_ltv
                    ? (row.avg_ltv / ltvBreakdown.by_tier[0].avg_ltv) * 100
                    : 0;
                  return (
                    <div key={row.tier}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="font-semibold capitalize" style={{ color: accent }}>
                          {row.tier} · {row.customers} customers · {row.avg_visits} avg visits
                        </span>
                        <span className="font-bold" style={{ color: C_PS.inkDeep }}>
                          €{row.avg_ltv} avg
                          <span className="text-[10px] ml-2" style={{ color: C_PS.inkMute }}>
                            ({row.share_pct}% of revenue)
                          </span>
                        </span>
                      </div>
                      <div className="h-2 rounded-full overflow-hidden" style={{ background: `${accent}1A` }}>
                        <div className="h-full rounded-full transition-all" style={{ width: `${widthPct}%`, background: `linear-gradient(90deg, ${accent}, ${accent}AA)` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* AI Suggestions Panel */}
      <Card className="bg-gradient-to-br from-white to-[#FAFAF8]">
        <SectionHead
          icon={Sparkles}
          title="Ask the AI — your business advisor"
          subtitle="Powered by your own customer data. Ask anything about growth, retention, campaigns, or customers, and get a personalised recommendation."
        />
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {AI_PRESET_QUESTIONS.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => { setAiQuestion(q); askAI(q); }}
                disabled={aiLoading}
                className="text-xs px-3 py-1.5 rounded-full border border-[#E9E5E0] bg-white hover:bg-[#B85C38] hover:text-white hover:border-[#B85C38] transition disabled:opacity-60"
                title="Ask this question"
              >
                {q}
              </button>
            ))}
          </div>

          <div className="flex flex-col md:flex-row gap-2">
            <input
              type="text"
              value={aiQuestion}
              onChange={(e) => setAiQuestion(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !aiLoading) askAI(); }}
              placeholder="e.g. How do I win back gold-tier customers who went quiet last month?"
              className="flex-1 px-4 py-2 border border-[#E9E5E0] rounded-lg text-sm"
              disabled={aiLoading}
            />
            <button
              type="button"
              onClick={() => askAI()}
              disabled={aiLoading || !aiQuestion.trim()}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[#B85C38] text-white text-sm font-semibold hover:bg-[#9C4E2F] disabled:opacity-60"
            >
              <Wand2 size={14} />
              {aiLoading ? 'Thinking…' : 'Get a recommendation'}
            </button>
          </div>

          {aiError && (
            <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-800">
              {aiError}
            </div>
          )}

          {aiAnswer && (
            <div className="p-4 rounded-lg bg-[#F5F4F1] border border-[#E9E5E0]">
              <div className="flex items-start gap-2 mb-2">
                <Sparkles size={16} className="text-[#B85C38] shrink-0 mt-0.5" />
                <p className="text-xs font-semibold text-[#B85C38] uppercase tracking-wider">AI recommendation</p>
              </div>
              <div className="text-sm text-[#171412] whitespace-pre-wrap leading-relaxed">{aiAnswer}</div>
              <div className="mt-3 pt-3 border-t border-[#E9E5E0] text-[11px] text-[#8D857D]">
                Tip: every insight below (churn, LTV, alerts, city breakdown…) can also be fed back into this box. Copy a number, paste it here, and ask "what does this mean for me?"
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Feature 3: Smart Alerts */}
      <Card>
        <SectionHead icon={AlertTriangle} title="Alertes intelligentes" subtitle="Ce qui mérite votre attention maintenant" />
        {alerts.length === 0 ? (
          <p className="text-sm text-[#57504A]">Aucune alerte — votre activité est stable.</p>
        ) : (
          <div className="space-y-3">
            {alerts.map((a, i) => (
              <div key={i} className={`flex items-start gap-3 p-3 rounded-lg border ${alertToneBg[a.level] || 'bg-[#F5F4F1] border-[#E9E5E0]'}`}>
                <div className="text-2xl">{a.icon}</div>
                <div className="flex-1">
                  <p className="font-semibold text-[#171412]">{a.title}</p>
                  <p className="text-sm text-[#57504A]">{a.detail}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Feature 1 + 7: Churn */}
      {churn && (
        <Card>
          <SectionHead icon={TrendingDown} title="Churn & rétention" subtitle="Combien de clients vous perdez, et quand." />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatPill label="Clients total" value={churn.total_customers} />
            <StatPill
              label="1 visite seulement"
              value={`${churn.one_visit_only_pct}%`}
              hint={`${churn.one_visit_only} clients`}
              tone={churn.one_visit_only_pct >= 25 ? 'warning' : 'default'}
            />
            <StatPill
              label="Inactifs 30j"
              value={`${churn.inactive_30d_pct}%`}
              hint={`${churn.inactive_30d} clients`}
              tone={churn.inactive_30d_pct >= 30 ? 'warning' : 'default'}
            />
            <StatPill
              label="Churned 90j"
              value={`${churn.churned_90d_pct}%`}
              hint={`${churn.churned_90d} clients`}
              tone={churn.churned_90d_pct >= 30 ? 'danger' : 'default'}
            />
          </div>
          <p className="text-xs text-[#57504A] mt-4 border-t border-[#E9E5E0] pt-3">
            "1 visite seulement" = clients venus une seule fois qui ne sont pas revenus. "Inactifs 30j" = n'ont pas visité depuis 30 jours.
          </p>
        </Card>
      )}

      {/* Feature 2: LTV */}
      {ltv && (
        <Card>
          <SectionHead icon={Euro} title="Lifetime Value (LTV)" subtitle="Combien un client rapporte en moyenne." />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
            <StatPill label="LTV moyenne" value={`${ltv.average_ltv}€`} />
            <StatPill label="LTV médiane" value={`${ltv.median_ltv}€`} />
            <StatPill label="Top 10% LTV" value={`${ltv.top_10_pct_ltv}€`} tone="success" />
          </div>
          {ltv.by_tier?.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#E9E5E0]">
                    <th className="text-left py-2 px-2 text-[#57504A] font-semibold">Tier</th>
                    <th className="text-right py-2 px-2 text-[#57504A] font-semibold">Clients</th>
                    <th className="text-right py-2 px-2 text-[#57504A] font-semibold">LTV moyenne</th>
                    <th className="text-right py-2 px-2 text-[#57504A] font-semibold">Revenu total</th>
                  </tr>
                </thead>
                <tbody>
                  {ltv.by_tier.map((row) => (
                    <tr key={row.tier} className="border-b border-[#F5F4F1]">
                      <td className="py-2 px-2 capitalize font-medium">{row.tier}</td>
                      <td className="py-2 px-2 text-right">{row.count}</td>
                      <td className="py-2 px-2 text-right">{row.average_ltv}€</td>
                      <td className="py-2 px-2 text-right">{row.total_revenue}€</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* Feature 12: Active cards + upgrade prompt */}
      {activeCards && (
        <Card>
          <SectionHead icon={CreditCard} title="Cartes de fidélité actives" subtitle="Utilisation de votre plan" />
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <div className="flex justify-between text-sm mb-1">
                <span className="font-semibold">{activeCards.active_cards} / {activeCards.plan_cap}</span>
                <span className="text-[#57504A]">{activeCards.usage_pct}% utilisé</span>
              </div>
              <div className="h-3 bg-[#F5F4F1] rounded-full overflow-hidden">
                <div
                  className={`h-full ${activeCards.near_limit ? 'bg-[#B85C38]' : 'bg-[#4A5D23]'}`}
                  style={{ width: `${Math.min(activeCards.usage_pct, 100)}%` }}
                />
              </div>
              <p className="text-xs text-[#57504A] mt-2">Plan actuel : <span className="uppercase font-semibold">{activeCards.plan}</span></p>
            </div>
          </div>
          {activeCards.suggest_upgrade && (
            <div className="mt-4 p-3 bg-[#B85C38]/10 border border-[#B85C38]/30 rounded-lg flex flex-wrap items-center gap-3 justify-between">
              <p className="font-semibold text-[#B85C38]">
                ⚡ Vous approchez de votre limite. Passez à <span className="uppercase">{activeCards.next_plan}</span> pour {activeCards.next_plan_cap?.toLocaleString()} cartes max ({activeCards.next_plan_price}€/mois).
              </p>
              <button
                onClick={async () => {
                  const msg = window.prompt('Un petit mot pour l\'équipe ? (optionnel)', '');
                  try {
                    await ownerAPI.requestUpgrade({
                      requested_plan: activeCards.next_plan,
                      message: msg || '',
                    });
                    alert('Votre demande de montée de plan a été envoyée à l\'équipe FidClic. On revient vers vous très vite.');
                  } catch (e) {
                    alert('Erreur: ' + (e?.response?.data?.detail || e?.message));
                  }
                }}
                className="px-4 py-2 bg-[#B85C38] text-white rounded-lg text-sm font-medium hover:bg-[#9C4E2F]"
              >
                Demander la montée de plan
              </button>
            </div>
          )}
        </Card>
      )}

      {/* Feature 4: Time segmentation */}
      {timeSeg && (
        <Card>
          <SectionHead icon={Clock} title="Segmentation horaire" subtitle="Clients du midi vs soir vs week-end" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <p className="text-xs uppercase font-semibold text-[#57504A] mb-2">Par moment</p>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={timeSeg.daypart_breakdown}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#E9E5E0" />
                    <XAxis dataKey="name" stroke="#57504A" fontSize={11} />
                    <YAxis stroke="#57504A" fontSize={11} />
                    <Tooltip />
                    <Bar isAnimationActive={chartAnimation()} dataKey="visits" fill="#B85C38" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div>
              <p className="text-xs uppercase font-semibold text-[#57504A] mb-2">Par jour de semaine</p>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={timeSeg.weekday_breakdown}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#E9E5E0" />
                    <XAxis dataKey="day" stroke="#57504A" fontSize={11} />
                    <YAxis stroke="#57504A" fontSize={11} />
                    <Tooltip />
                    <Bar isAnimationActive={chartAnimation()} dataKey="visits" fill="#4A5D23" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <StatPill label="Visites weekend" value={timeSeg.weekend_visits} tone="success" />
            <StatPill label="Visites semaine" value={timeSeg.weekday_visits} />
          </div>
        </Card>
      )}

      {/* Feature 5: City breakdown */}
      {city && (
        <Card>
          <SectionHead icon={MapPin} title="Base de données par ville" subtitle={`${city.unique_postal_codes} codes postaux uniques`} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <p className="text-xs uppercase font-semibold text-[#57504A] mb-2">Top départements</p>
              <div className="space-y-1 max-h-64 overflow-y-auto">
                {city.by_departement.slice(0, 10).map((d) => (
                  <div key={d.code} className="flex justify-between px-3 py-2 rounded bg-[#F5F4F1]">
                    <span><span className="font-mono text-xs text-[#B85C38]">{d.code}</span> {d.name}</span>
                    <span className="font-semibold">{d.customer_count}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="text-xs uppercase font-semibold text-[#57504A] mb-2">Top codes postaux</p>
              <div className="space-y-1 max-h-64 overflow-y-auto">
                {city.by_postal_code.slice(0, 10).map((p) => (
                  <div key={p.postal_code} className="flex justify-between px-3 py-2 rounded bg-[#F5F4F1]">
                    <span className="font-mono">{p.postal_code}</span>
                    <span className="font-semibold">{p.customer_count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Feature 10: Monthly report */}
      {monthly && (
        <Card>
          <SectionHead icon={Calendar} title={`Compte-rendu — ${monthly.month_label}`} subtitle="Récap automatique du mois dernier" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <StatPill
              label="Visites"
              value={monthly.totals.visits}
              hint={monthly.totals.visits_delta_pct != null ? `${monthly.totals.visits_delta_pct > 0 ? '+' : ''}${monthly.totals.visits_delta_pct}% vs mois dernier` : '—'}
              tone={monthly.totals.visits_delta_pct > 0 ? 'success' : monthly.totals.visits_delta_pct < 0 ? 'danger' : 'default'}
            />
            <StatPill
              label="Nouveaux clients"
              value={monthly.totals.new_customers}
              hint={monthly.totals.new_customers_delta_pct != null ? `${monthly.totals.new_customers_delta_pct > 0 ? '+' : ''}${monthly.totals.new_customers_delta_pct}%` : '—'}
            />
            <StatPill label="Revenu" value={`${monthly.totals.revenue}€`} />
            <StatPill label="Panier moyen" value={`${monthly.totals.avg_basket}€`} />
          </div>
          {monthly.campaigns.length > 0 && (
            <div>
              <p className="text-xs uppercase font-semibold text-[#57504A] mb-2">Campagnes du mois</p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#E9E5E0]">
                      <th className="text-left py-1 px-2">Nom</th>
                      <th className="text-right py-1 px-2">Ciblés</th>
                      <th className="text-right py-1 px-2">Livrés</th>
                      <th className="text-right py-1 px-2">Ouvertures</th>
                      <th className="text-right py-1 px-2">Clics</th>
                      <th className="text-right py-1 px-2">Visites</th>
                    </tr>
                  </thead>
                  <tbody>
                    {monthly.campaigns.map((c, i) => (
                      <tr key={i} className="border-b border-[#F5F4F1]">
                        <td className="py-1 px-2">{c.name}</td>
                        <td className="py-1 px-2 text-right">{c.targeted}</td>
                        <td className="py-1 px-2 text-right">{c.delivered}</td>
                        <td className="py-1 px-2 text-right">{c.opens}</td>
                        <td className="py-1 px-2 text-right">{c.clicks}</td>
                        <td className="py-1 px-2 text-right">{c.visits_from}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Feature 6: Reactivation template */}
      {reactivation && (
        <Card>
          <SectionHead icon={Send} title="Relance clients inactifs" subtitle={`Template adapté à votre secteur : ${reactivation.sector}`} />
          <div className="p-4 bg-[#F5F4F1] rounded-lg border border-[#E9E5E0]">
            <p className="font-semibold text-[#B85C38] mb-1">{reactivation.template.title}</p>
            <p className="text-sm text-[#171412]">{reactivation.template.content}</p>
          </div>
          <p className="text-xs text-[#57504A] mt-3">
            Utilisez ce template dans la page Campaigns pour cibler les clients inactifs de plus de 30 jours.
          </p>
        </Card>
      )}

      {/* Feature 8: Sender name */}
      <Card>
        <SectionHead icon={Zap} title="Nom d'expéditeur des notifications" subtitle="Le nom qui apparaît dans les push et emails" />
        <div className="flex gap-2">
          <input
            type="text"
            value={senderName}
            onChange={(e) => setSenderName(e.target.value)}
            placeholder="Ex: Café Lumière"
            className="flex-1 border border-[#E9E5E0] rounded-lg px-3 py-2 focus:ring-[#B85C38]/20 focus:border-[#B85C38]"
          />
          <button
            onClick={saveSenderName}
            disabled={senderNameSaving}
            className="px-4 py-2 bg-[#B85C38] text-white rounded-lg font-medium hover:bg-[#9C4E2F] disabled:opacity-50"
          >
            {senderNameSaving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </Card>

      {/* Feature 9: Team (manager/staff roles) */}
      <Card>
        <SectionHead icon={Users} title="Équipe" subtitle="Manager = stats uniquement · Staff = scan uniquement" />
        <form onSubmit={addTeamMember} className="flex flex-wrap gap-2 mb-4">
          <input
            type="email"
            required
            placeholder="email@example.com"
            value={addTeamForm.email}
            onChange={(e) => setAddTeamForm({ ...addTeamForm, email: e.target.value })}
            className="flex-1 min-w-[180px] border border-[#E9E5E0] rounded-lg px-3 py-2"
          />
          <input
            type="password"
            required
            placeholder="Mot de passe"
            value={addTeamForm.password}
            onChange={(e) => setAddTeamForm({ ...addTeamForm, password: e.target.value })}
            className="w-40 border border-[#E9E5E0] rounded-lg px-3 py-2"
          />
          <select
            value={addTeamForm.role}
            onChange={(e) => setAddTeamForm({ ...addTeamForm, role: e.target.value })}
            className="border border-[#E9E5E0] rounded-lg px-3 py-2"
          >
            <option value="staff">Staff</option>
            <option value="manager">Manager</option>
          </select>
          <button className="px-4 py-2 bg-[#B85C38] text-white rounded-lg font-medium hover:bg-[#9C4E2F] flex items-center gap-2">
            <UserPlus size={16} /> Ajouter
          </button>
        </form>
        {team.length === 0 ? (
          <p className="text-sm text-[#57504A]">Aucun membre d'équipe pour le moment.</p>
        ) : (
          <div className="space-y-1">
            {team.map((m) => (
              <div key={m.email} className="flex items-center justify-between px-3 py-2 bg-[#F5F4F1] rounded">
                <span className="text-sm">{m.email}</span>
                <div className="flex items-center gap-3">
                  <span className="text-xs uppercase font-bold px-2 py-0.5 rounded bg-[#B85C38] text-white">{m.role}</span>
                  <button onClick={() => removeTeamMember(m.email)} className="text-red-600 hover:text-red-800">
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
