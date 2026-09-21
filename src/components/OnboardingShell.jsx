import React from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, ArrowRight, Check } from 'lucide-react';

/**
 * OnboardingShell — the frame around the signup steps, from the approved
 * mockups: marketing nav on top (links back to fidclic.com), the phone-in-hand
 * visual on the left (one image, identical on every step), and the white card
 * on the right with the 1-2-3 stepper above the step's content.
 *
 *   step 1  /register               → RegisterPage           (vos informations)
 *   step 2  /onboarding/entreprise  → OnboardingCompanyPage  (votre établissement)
 *   step 3  /onboarding/carte       → OnboardingCardPage     (configuration carte)
 *   done    /onboarding/termine     → OnboardingDonePage     (carte créée — QR à partager)
 */
const SITE = (import.meta.env.VITE_LEGAL_BASE_URL || 'https://www.fidclic.com').replace(/\/$/, '');
const LOGO = '/brand/fidclic-logo.png';
// The left panel of the mockup (phone, cards, feature chips, "100 % sécurisé"),
// used as-is so the page matches the approved visual pixel for pixel.
const HERO = '/brand/onboarding-hero.jpg';

const NAV = [
  { key: 'features', href: `${SITE}/fonctionnalites` },
  { key: 'sectors',  href: `${SITE}/cas-d-usage` },
  { key: 'pricing',  href: `${SITE}/tarifs` },
  { key: 'blog',     href: `${SITE}/ressources` },
  { key: 'faq',      href: `${SITE}/ressources#faq` },
];

// Shared field chrome (icon column + borderless input) — same pattern as
// RegisterPage so the three steps look like one form.
export const Field = ({ icon: Icon, children, trailing }) => (
  <div className="flex items-stretch rounded-xl border border-[#E1E8F5] bg-white transition focus-within:border-[#2F6BFF] focus-within:ring-4 focus-within:ring-[#2F6BFF]/10">
    <div className="flex w-12 shrink-0 items-center justify-center border-r border-[#EEF2F9] text-[#2F6BFF]" aria-hidden="true">
      <Icon size={18} strokeWidth={1.8} />
    </div>
    <div className="flex min-w-0 flex-1 items-stretch">{children}</div>
    {trailing}
  </div>
);
export const INPUT = 'w-full bg-transparent px-4 py-3 text-[15px] text-[#0F172A] outline-none placeholder:text-[#94A3B8]';
export const FieldLabel = ({ children, optional }) => (
  <label className="mb-2 block text-[15px] font-semibold text-[#0B1C3F]">
    {children}{optional ? '' : ' *'}
  </label>
);

/** "← Retour · Continuer →" row at the bottom of steps 2 and 3. */
export const StepButtons = ({ onBack, backLabel, nextLabel, loading, type = 'submit', onNext }) => (
  <div className="mt-8 grid grid-cols-[minmax(0,.8fr)_minmax(0,1fr)] gap-4">
    <button type="button" onClick={onBack}
            className="inline-flex items-center justify-center gap-3 rounded-2xl bg-[#EEF4FF] py-4 text-[17px] font-semibold text-[#0B1C3F] transition hover:bg-[#E2ECFF]">
      <ArrowLeft size={20} className="text-[#2F6BFF]" /> {backLabel}
    </button>
    <button type={type} onClick={onNext} disabled={loading}
            className="inline-flex items-center justify-center gap-3 rounded-2xl py-4 text-[17px] font-semibold text-white transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60"
            style={{ background: '#0A6CFF', boxShadow: '0 12px 28px -12px rgba(10,108,255,.6)' }}>
      {nextLabel} <ArrowRight size={20} />
    </button>
  </div>
);

export const Stepper = ({ step }) => {
  const { t } = useTranslation();
  const steps = [t('signup.step1'), t('signup.step2'), t('signup.step3')];
  return (
    <ol className="flex items-center justify-center gap-3 text-[13px]">
      {steps.map((label, i) => {
        const n = i + 1; const active = n === step; const done = n < step;
        return (
          <li key={label} className="flex items-center gap-3">
            <span className={`flex h-9 w-9 items-center justify-center rounded-full text-[14px] font-bold ${active || done ? 'bg-[#2F6BFF] text-white shadow-[0_6px_16px_-6px_rgba(47,107,255,.7)]' : 'bg-[#EEF2F9] text-[#64748B]'}`}>
              {done ? <Check size={18} strokeWidth={3} /> : n}
            </span>
            <span className={`whitespace-nowrap ${active ? 'font-semibold text-[#0B1C3F]' : 'text-[#64748B]'}`}>{label}</span>
            {n < 3 && <span className="hidden h-px w-8 bg-[#DCE3EF] sm:block" />}
          </li>
        );
      })}
    </ol>
  );
};

export default function OnboardingShell({ step, children, wide = false }) {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen bg-white">
      {/* ── marketing nav ── */}
      <header className="flex h-[76px] items-center justify-between px-6 lg:px-12">
        <a href={SITE} className="flex items-center"><img src={LOGO} alt="FidClic" className="h-11 w-auto" /></a>
        <nav className="hidden items-center gap-8 text-[15px] text-[#0B1C3F] lg:flex">
          {NAV.map((n) => <a key={n.key} href={n.href} className="hover:text-[#2F6BFF]">{t(`signup.nav_${n.key}`)}</a>)}
        </nav>
        <div className="text-[14px] text-[#4B5C7A]">
          <span className="hidden sm:inline">{t('auth.have_account')} </span>
          <Link to="/login" className="font-semibold text-[#2F6BFF] hover:underline">{t('auth.sign_in')}</Link>
        </div>
      </header>

      <div className="grid min-h-[calc(100vh-76px)] lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        {/* ── left: the mockup visual, identical on every step ── */}
        {/* Locked to the viewport height (sticky) so a tall form on the right
            never stretches this column — the visual is shown WHOLE, never
            cropped or zoomed; a blurred copy fills any leftover edge. */}
        <aside className="relative hidden self-start overflow-hidden lg:sticky lg:top-[76px] lg:flex lg:h-[calc(100vh-76px)] lg:items-center lg:justify-center">
          <img src={HERO} alt="" aria-hidden="true" className="absolute inset-0 h-full w-full object-cover" style={{ filter: 'blur(28px)', transform: 'scale(1.15)', opacity: .9 }} />
          <img src={HERO} alt="" className="relative h-full w-full object-contain object-center" />
        </aside>

        {/* ── right: step card ── */}
        <main className="flex items-start justify-center px-4 py-6 lg:px-8">
          <div className={`w-full ${wide ? 'max-w-[680px]' : 'max-w-[640px]'} rounded-[22px] border border-[#E6EEFB] bg-white px-6 py-8 shadow-[0_24px_60px_-30px_rgba(47,107,255,.25)] sm:px-9`}>
            <Stepper step={step} />
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
