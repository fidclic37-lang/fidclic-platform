import React, { useEffect, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Check, Minus, Sparkles } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { onboardingAPI } from '../lib/api';
import OnboardingShell, { StepButtons } from '../components/OnboardingShell';

/**
 * OnboardingPlanPage — STEP 3 of 4: "Votre formule" (user, 2026-10-04).
 *
 * The three plans side by side, each with its real monthly price (HT) struck
 * through, « 0 € » in its place and the trial length. The page only SHOWS the
 * plans: every trial runs on Pro AI (TRIAL_PLAN) and the owner picks what
 * they pay for when the trial ends (Paramètres › Abonnement).
 *
 * « Commencer mon essai gratuit » → POST /api/onboarding/start-trial: the
 * business leaves draft (it appears in the super admin from now on), the
 * 30-day trial starts → step 4 (/onboarding/carte, optional).
 *
 * Prices, limits and features come from /api/public/plans — the same source as
 * the pricing page on fidclic.com and Super admin › Plan Limits.
 */
const fmt = (n) => Number(n || 0).toLocaleString('fr-FR');

function featureRows(p, t) {
  const L = p.limits || {}; const F = p.features || {};
  const rows = [];
  rows.push({ on: true, text: L.max_customers ? t('plan_step.f_customers', { n: fmt(L.max_customers) }) : t('plan_step.f_customers_unl') });
  if (L.new_cards_per_month) rows.push({ on: true, text: t('plan_step.f_cards', { n: fmt(L.new_cards_per_month) }) });
  if (L.push_per_month) rows.push({ on: true, text: t('plan_step.f_push', { n: fmt(L.push_per_month) }) });
  if (L.establishments) rows.push({ on: true, text: t('plan_step.f_establishments', { count: L.establishments }) });
  rows.push({ on: F.campaigns, text: t('plan_step.f_campaigns') });
  rows.push({ on: F.automation, text: t('plan_step.f_automation') });
  rows.push({ on: F.segments || F.crm, text: t('plan_step.f_segments') });
  rows.push({ on: F.referral, text: t('plan_step.f_referral') });
  rows.push({ on: F.geo, text: t('plan_step.f_geo') });
  rows.push({ on: F.analytics, text: t('plan_step.f_analytics') });
  const ai = F.ai_level || 'none';
  rows.push({ on: ai !== 'none', text: t(ai === 'advanced' ? 'plan_step.f_ai_advanced' : ai === 'basic' ? 'plan_step.f_ai_basic' : 'plan_step.f_ai_none') });
  rows.push({ on: F.api, text: t('plan_step.f_api') });
  return rows;
}

const OnboardingPlanPage = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user, checkAuth } = useAuth();
  const [cat, setCat] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    onboardingAPI.plans().then((r) => setCat(r.data)).catch(() => setError(t('plan_step.load_failed')));
  }, [t]);

  const days = cat?.trial_days || 30;
  const trialPlan = cat?.trial_plan || 'vip';

  const start = async () => {
    setError('');
    setLoading(true);
    try {
      await onboardingAPI.startTrial();
      await checkAuth();            // onboarding_status → "done": the guards let the owner through
      navigate('/onboarding/carte', { replace: true });
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || t('onboarding.failed'));
      setLoading(false);
    }
  };

  // The company step comes first (the route skips the generic gate so an owner
  // at "plan" can reach this page).
  if (user?.onboarding_status === 'verify') return <Navigate to="/onboarding/verification" replace />;
  if (user?.onboarding_status === 'company') return <Navigate to="/onboarding/entreprise" replace />;

  return (
    <OnboardingShell step={3} full>
      <div className="mt-8 text-center">
        <h1 className="text-[36px] font-extrabold tracking-[-0.02em] text-[#0B1C3F]">{t('plan_step.title')}</h1>
        <p className="mx-auto mt-2 max-w-[520px] text-[16px] text-[#4B5C7A]">{t('plan_step.subtitle')}</p>
        <span className="mt-4 inline-flex items-center gap-2 rounded-full bg-[#E9F8EF] px-4 py-1.5 text-[14px] font-semibold text-[#137A3E]">
          <Sparkles size={16} /> {t('plan_step.trial_badge', { days })}
        </span>
      </div>

      {error && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">⚠ {error}</div>}

      <div className="mt-7 grid gap-4 sm:grid-cols-3">
        {(cat?.plans || []).map((p) => {
          const featured = p.key === trialPlan;
          return (
            <div key={p.key}
                 className={`relative flex flex-col rounded-2xl border bg-white p-5 ${featured ? 'border-[#2F6BFF] shadow-[0_18px_40px_-24px_rgba(47,107,255,.55)]' : 'border-[#E1E8F5]'}`}>
              {featured && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-[#2F6BFF] px-3 py-1 text-[11.5px] font-bold uppercase tracking-[.06em] text-white">
                  {t('plan_step.in_trial')}
                </span>
              )}
              <p className="text-[17px] font-bold text-[#0B1C3F]">{p.label}</p>
              <p className="mt-3 text-[15px] font-semibold text-[#334155]">
                <s className="decoration-[#DC2626] decoration-2">{fmt(p.price_monthly)} {t('plan_step.per_month')}</s>
              </p>
              <p className="mt-0.5 flex items-baseline gap-1.5">
                <span className="text-[34px] font-extrabold leading-none tracking-[-0.02em] text-[#0B1C3F]">0 €</span>
                <span className="text-[13px] text-[#4B5C7A]">{t('plan_step.today')}</span>
              </p>
              <p className="mt-2 text-[12.5px] font-semibold text-[#137A3E]">{t('plan_step.trial_badge', { days })}</p>
              <p className="text-[12px] text-[#64748B]">{t('plan_step.then', { price: fmt(p.price_monthly) })}</p>
              <ul className="mt-4 space-y-2 border-t border-[#EEF2F9] pt-4 text-[13px]">
                {featureRows(p, t).map((r) => (
                  <li key={r.text} className={`flex items-start gap-2 ${r.on ? 'text-[#0B1C3F]' : 'text-[#A0AABB]'}`}>
                    {r.on
                      ? <Check size={15} strokeWidth={2.6} className="mt-0.5 shrink-0 text-[#2F6BFF]" />
                      : <Minus size={15} className="mt-0.5 shrink-0" />}
                    <span>{r.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {!cat && !error && [0, 1, 2].map((i) => <div key={i} className="h-[420px] animate-pulse rounded-2xl bg-[#F3F6FB]" />)}
      </div>

      <div className="mx-auto max-w-[640px]">
      <StepButtons type="button" onBack={() => navigate('/onboarding/entreprise')} backLabel={t('onboarding.back')}
                   onNext={start} loading={loading || !cat}
                   nextLabel={loading ? t('plan_step.starting') : t('plan_step.cta', { days })} />
      <p className="mt-4 text-center text-[12.5px] leading-relaxed text-[#64748B]">{t('plan_step.note')}</p>
      </div>
    </OnboardingShell>
  );
};

export default OnboardingPlanPage;
