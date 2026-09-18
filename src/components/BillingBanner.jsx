import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertCircle, Sparkles, Clock, Lock, X } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * BillingBanner — trial countdown + payment-state alert bar.
 *
 * Renders at the very top of every authenticated owner page. Three modes,
 * in order of urgency:
 *
 *  1. TRIAL — quiet pill showing "X days left in trial". Default state for
 *     every new business for the first ~18 days. Click → opens Settings →
 *     Billing where they can pick a plan early.
 *  2. REMINDER — when days_left <= reminder_days_before (default 3), the
 *     pill grows into an orange banner with "Choose a plan now" CTA.
 *  3. EXPIRED — once days_left <= 0, banner turns red and locks paid
 *     features. Owner can still access Settings → Billing to upgrade.
 *
 * Driven by GET /api/owner/trial-status which returns days_left,
 * reminder_window, is_expired, plan, plan_price, and the full plan
 * catalogue so we can render an inline picker without a second request.
 *
 * Falls back silently if the endpoint errors (legacy tenant, network
 * blip) — no banner is shown rather than blocking the dashboard.
 */
export default function BillingBanner() {
  const [trial, setTrial] = useState(null);
  const [dismissed, setDismissed] = useState(false);
  const [upgrading, setUpgrading] = useState(false);
  const [showPicker, setShowPicker] = useState(false);

  // Poll on mount + every 5 minutes so the countdown stays fresh even if
  // the tab is left open all day.
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      ownerAPI.getTrialStatus()
        .then((res) => { if (!cancelled) setTrial(res.data); })
        .catch(() => { /* silent — legacy tenant or backend hiccup */ });
    };
    load();
    const t = setInterval(load, 5 * 60_000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (!trial) return null;
  // Active paid subscription — nothing to show.
  if (trial.subscription_status === 'active') return null;
  if (!trial.is_in_trial && !trial.is_expired) return null;

  // The "quiet" pill (>3 days left) is dismissible per-session.
  const isReminder = !!trial.reminder_window;
  const isExpired = !!trial.is_expired;
  const isQuiet = trial.is_in_trial && !isReminder;
  if (isQuiet && dismissed) return null;

  const handleUpgrade = async (plan) => {
    setUpgrading(true);
    try {
      const res = await ownerAPI.upgradePlan(plan);
      setTrial(res.data);
      setShowPicker(false);
      // Visual confirmation — fall through to the re-render where the
      // banner disappears because subscription_status is now 'active'.
    } catch (e) {
      alert('Plan switch failed: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setUpgrading(false);
    }
  };

  // ── Styling per state ─────────────────────────────────────────────────
  const bgClass = isExpired
    ? 'bg-[#FBEAE7] border-[#E89A8A] text-[#7A2E20]'
    : isReminder
      ? 'bg-[#FFF1DC] border-[#E3A869] text-[#7A4A0A]'
      : 'bg-[#F0F6F4] border-[#9CC2B5] text-[#1F4D40]';

  const Icon = isExpired ? Lock : isReminder ? AlertCircle : Sparkles;

  // Pretty time-left string. Below 24h, fall back to hours for granularity.
  const daysLeft = trial.days_left ?? 0;
  const hoursLeft = trial.hours_left ?? 0;
  const timeLeftText = isExpired
    ? 'Free trial ended'
    : daysLeft >= 1
      ? `${daysLeft} day${daysLeft > 1 ? 's' : ''} left in your free trial`
      : hoursLeft > 0
        ? `${hoursLeft} hour${hoursLeft > 1 ? 's' : ''} left in your free trial`
        : 'Your free trial ends today';

  return (
    <div className={`border-b ${bgClass}`}>
      <div className="max-w-7xl mx-auto px-4 py-2 flex items-center gap-3 text-sm">
        <Icon size={16} className="flex-shrink-0" />

        <div className="flex-1 min-w-0">
          {isExpired ? (
            <span>
              <strong>{timeLeftText}.</strong> Paid features are locked — pick a plan to keep using FidClic.
            </span>
          ) : isReminder ? (
            <span>
              <strong>{timeLeftText}.</strong> Pick a plan now to avoid interruption.
              {trial.trial_ends_at && (
                <span className="ml-2 opacity-75">
                  (expires {new Date(trial.trial_ends_at).toLocaleDateString()})
                </span>
              )}
            </span>
          ) : (
            <span>
              <Clock size={12} className="inline-block -mt-0.5 mr-1" />
              {timeLeftText}.
              {' '}
              <button
                onClick={() => setShowPicker(true)}
                className="underline font-semibold"
                type="button"
              >
                See plans
              </button>
            </span>
          )}
        </div>

        {/* Primary CTA — same intent everywhere, label adapts to urgency. */}
        <button
          onClick={() => setShowPicker(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md bg-white text-[#171412] font-semibold text-xs hover:bg-[#FAFAF8] transition-colors border border-[#E9E5E0] shrink-0"
          type="button"
        >
          {isExpired ? 'Unlock now' : isReminder ? 'Choose a plan' : 'View plans'}
        </button>

        {/* Quiet mode is dismissible — reminder & expired are not. */}
        {isQuiet && (
          <button
            onClick={() => setDismissed(true)}
            aria-label="Dismiss"
            className="text-current opacity-60 hover:opacity-100 shrink-0"
            type="button"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Inline plan picker modal — no separate route, so it works even
          if Settings → Billing isn't yet built out for this tenant. */}
      {showPicker && (
        <PlanPicker
          trial={trial}
          upgrading={upgrading}
          onPick={handleUpgrade}
          onClose={() => setShowPicker(false)}
        />
      )}
    </div>
  );
}


// ───────────────────────────────────────────────────────────────────────────
// PlanPicker — modal dialog rendered over the page. Shows the 3 plans,
// their prices, what's included, and a "Pick this plan" button. Powered
// by trial.available_plans which the trial-status endpoint already
// ships — no extra request.
// ───────────────────────────────────────────────────────────────────────────
function PlanPicker({ trial, upgrading, onPick, onClose }) {
  const plans = trial.available_plans || [];
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(28,25,23,0.55)',
        zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 16, backdropFilter: 'blur(4px)',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--flc-card, #FFFFFF)', borderRadius: 18, padding: '28px 28px 22px',
          maxWidth: 760, width: '100%', boxShadow: '0 32px 80px rgba(0,0,0,0.25)',
          maxHeight: '90vh', overflowY: 'auto',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 18 }}>
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.14em', color: '#B85C38', margin: 0 }}>
              FidClic Plans
            </p>
            <h2 style={{ fontFamily: 'Cormorant Garamond, Georgia, serif', fontSize: 28, fontWeight: 700, margin: '6px 0 4px', color: '#171412' }}>
              {trial.is_expired ? 'Your trial has ended — pick a plan to continue' : 'Pick the plan that fits your business'}
            </h2>
            <p style={{ fontSize: 13.5, color: '#6B6359', margin: 0 }}>
              Switch any time. Limits and features change instantly when you upgrade — no migration.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" type="button"
                  style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: '#6B6359' }}>
            <X size={20} />
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14 }}>
          {plans.map((p) => {
            const isCurrent = p.plan === trial.plan;
            const accent = p.plan === 'silver' ? '#6FA89C' : p.plan === 'gold' ? '#D4A574' : '#B85C38';
            return (
              <div key={p.plan}
                style={{
                  border: `2px solid ${isCurrent ? accent : '#EFEDE9'}`,
                  borderRadius: 14, padding: '18px 16px',
                  background: isCurrent ? `${accent}10` : 'white',
                  position: 'relative',
                }}>
                {isCurrent && (
                  <span style={{
                    position: 'absolute', top: -10, left: 14,
                    background: accent, color: 'white',
                    fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em',
                    padding: '3px 8px', borderRadius: 99,
                  }}>Current</span>
                )}
                <p style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.12em', color: accent, margin: 0 }}>
                  {p.plan}
                </p>
                <p style={{ fontFamily: 'Cormorant Garamond, serif', fontSize: 32, fontWeight: 700, margin: '4px 0 2px', color: '#171412' }}>
                  €{p.price}<span style={{ fontSize: 14, fontWeight: 400, color: '#6B6359' }}>/mo</span>
                </p>
                <ul style={{ listStyle: 'none', padding: 0, margin: '12px 0', fontSize: 13, color: '#171412' }}>
                  <li style={{ padding: '4px 0' }}>✓ Up to {p.max_customers?.toLocaleString()} customers</li>
                  <li style={{ padding: '4px 0', color: p.ai_queries_per_day > 0 ? '#171412' : '#A8A29E' }}>
                    {p.ai_queries_per_day > 0 ? '✓' : '✗'} AI Assistant ({p.ai_queries_per_day || 0}/day)
                  </li>
                  <li style={{ padding: '4px 0', color: p.geo_proximity ? '#171412' : '#A8A29E' }}>
                    {p.geo_proximity ? '✓' : '✗'} Geolocation campaigns
                  </li>
                </ul>
                <button
                  type="button"
                  disabled={isCurrent || upgrading}
                  onClick={() => onPick(p.plan)}
                  style={{
                    width: '100%', padding: '10px 12px', borderRadius: 99,
                    background: isCurrent ? '#EFEDE9' : accent,
                    color: isCurrent ? '#6B6359' : 'white',
                    border: 'none', cursor: isCurrent ? 'default' : 'pointer',
                    fontSize: 13, fontWeight: 700,
                    opacity: upgrading ? 0.6 : 1,
                  }}>
                  {isCurrent ? 'Current plan' : upgrading ? 'Switching…' : `Pick ${p.plan}`}
                </button>
              </div>
            );
          })}
        </div>

        <p style={{ fontSize: 11, color: '#A8A29E', marginTop: 14, textAlign: 'center' }}>
          Test/staging environment switches plans instantly. Production routes through Stripe Checkout.
        </p>
      </div>
    </div>
  );
}
