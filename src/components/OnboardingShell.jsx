import React from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  CreditCard, Users, Bell, BarChart3, MapPin, Store, Gift, Share2, Settings2,
} from 'lucide-react';

/**
 * OnboardingShell — the frame around the 3 signup steps, from the approved
 * mockup: marketing nav on top (links back to fidclic.com), a photo panel on
 * the left with the feature chips and the "100 % sécurisé" badge, and the
 * white card on the right with the 1-2-3 stepper above the step's content.
 *
 *   step 1  /register               → RegisterPage           (vos informations)
 *   step 2  /onboarding/entreprise  → OnboardingCompanyPage  (votre établissement)
 *   step 3  /onboarding/carte       → OnboardingCardPage     (configuration carte)
 */
const SITE = (import.meta.env.VITE_LEGAL_BASE_URL || 'https://www.fidclic.com').replace(/\/$/, '');
const LOGO = '/brand/fidclic-logo.png';
const HERO = '/brand/register-hero.jpg';

const NAV = [
  { key: 'features', href: `${SITE}/fonctionnalites` },
  { key: 'sectors',  href: `${SITE}/cas-d-usage` },
  { key: 'pricing',  href: `${SITE}/tarifs` },
  { key: 'blog',     href: `${SITE}/ressources` },
  { key: 'faq',      href: `${SITE}/ressources#faq` },
];

// One chip per feature; the icon square colour is part of the mockup.
const CHIPS = [
  { key: 'wallet',    icon: CreditCard, bg: '#EAF0FF', fg: '#2F6BFF' },
  { key: 'crm',       icon: Users,      bg: '#FFF4D6', fg: '#F5A623' },
  { key: 'push',      icon: Bell,       bg: '#E8F8EE', fg: '#22A559' },
  { key: 'analytics', icon: BarChart3,  bg: '#F0E9FF', fg: '#7C3AED' },
  { key: 'geo',       icon: MapPin,     bg: '#FFE9E9', fg: '#E5484D' },
  { key: 'multi',     icon: Store,      bg: '#EAF0FF', fg: '#2F6BFF' },
  { key: 'loyalty',   icon: Gift,       bg: '#FFE6F0', fg: '#E93D82' },
  { key: 'referral',  icon: Share2,     bg: '#EAF0FF', fg: '#2F6BFF' },
  { key: 'marketing', icon: Settings2,  bg: '#E8F8EE', fg: '#22A559' },
];

// Apple Wallet / Google Wallet marks, drawn inline (no external assets).
const WalletGlyph = ({ kind }) => kind === 'apple' ? (
  <svg width="24" height="20" viewBox="0 0 24 20" aria-hidden="true">
    <rect x="1" y="1" width="22" height="18" rx="3" fill="#1F2937" />
    <rect x="1" y="4" width="22" height="4" fill="#F59E0B" /><rect x="1" y="8" width="22" height="4" fill="#22C55E" />
    <rect x="1" y="12" width="22" height="7" rx="2" fill="#3B82F6" />
  </svg>
) : (
  <svg width="24" height="20" viewBox="0 0 24 20" aria-hidden="true">
    <rect x="1" y="1" width="22" height="18" rx="4" fill="#F1F5F9" />
    <path d="M3 8c0-2 1.5-3.5 3.5-3.5H21v4H3z" fill="#EA4335" /><path d="M3 8h18v4H3z" fill="#FBBC05" />
    <path d="M3 12h18v2.5c0 2-1.5 3.5-3.5 3.5H3z" fill="#34A853" /><path d="M3 8v10h6V8z" fill="#4285F4" />
  </svg>
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
            <span className={`flex h-9 w-9 items-center justify-center rounded-full text-[14px] font-bold ${active ? 'bg-[#2F6BFF] text-white shadow-[0_6px_16px_-6px_rgba(47,107,255,.7)]' : done ? 'bg-[#2F6BFF]/15 text-[#2F6BFF]' : 'bg-[#EEF2F9] text-[#64748B]'}`}>
              {n}
            </span>
            <span className={`whitespace-nowrap ${active ? 'font-semibold text-[#0B1C3F]' : 'text-[#64748B]'}`}>{label}</span>
            {n < 3 && <span className="hidden h-px w-8 bg-[#DCE3EF] sm:block" />}
          </li>
        );
      })}
    </ol>
  );
};

export default function OnboardingShell({ step, children }) {
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
        {/* ── left: photo + chips ── */}
        <aside className="relative hidden overflow-hidden lg:block">
          <img src={HERO} alt="" className="absolute inset-0 h-full w-full object-cover object-[15%_center]" />
          <div aria-hidden="true" className="absolute inset-0" style={{ background: 'linear-gradient(90deg, rgba(255,255,255,0) 45%, rgba(244,248,254,.55) 100%)' }} />
          {/* chips column, along a soft arc on the right side of the panel */}
          <ul className="absolute right-5 top-16 flex w-[250px] flex-col gap-3">
            {CHIPS.map((c, i) => {
              const Icon = c.icon;
              const offset = [52, 30, 14, 4, 0, 4, 14, 30, 52][i]; // arc
              return (
                <li key={c.key} style={{ marginRight: offset }}
                    className="flex items-center gap-3 rounded-2xl bg-white/95 px-3.5 py-2.5 text-[14px] font-semibold text-[#0B1C3F] shadow-[0_8px_24px_-12px_rgba(11,28,63,.35)] backdrop-blur">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: c.bg, color: c.fg }}>
                    <Icon size={18} strokeWidth={2} />
                  </span>
                  {t(`signup.chip_${c.key}`)}
                </li>
              );
            })}
          </ul>
          <div className="absolute bottom-8 left-8 flex gap-3">
            {[['apple', t('signup.wallet_apple')], ['google', t('signup.wallet_google')]].map(([k, label]) => (
              <div key={k} className="flex items-center gap-3 rounded-2xl bg-white/95 px-4 py-3 shadow-[0_8px_24px_-12px_rgba(11,28,63,.35)] backdrop-blur">
                <span className="flex h-11 w-11 items-center justify-center rounded-xl" style={{ background: k === 'apple' ? '#111827' : '#FFFFFF', border: k === 'google' ? '1px solid #E6EAF2' : 'none' }}>
                  <WalletGlyph kind={k} />
                </span>
                <span>
                  <span className="block text-[12px] text-[#4B5C7A]">{t('signup.compatible')}</span>
                  <span className="block text-[15px] font-bold text-[#0B1C3F]">{label}</span>
                </span>
              </div>
            ))}
          </div>
        </aside>

        {/* ── right: step card ── */}
        <main className="flex items-start justify-center px-4 py-6 lg:px-8">
          <div className="w-full max-w-[640px] rounded-[22px] border border-[#E6EEFB] bg-white px-6 py-8 shadow-[0_24px_60px_-30px_rgba(47,107,255,.25)] sm:px-9">
            <Stepper step={step} />
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
