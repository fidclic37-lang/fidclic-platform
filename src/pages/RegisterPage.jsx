import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { User, Mail, Lock, Phone, ArrowRight, Eye, EyeOff, ShieldCheck } from 'lucide-react';
import { passwordRules, passwordValid } from '../lib/passwordPolicy';
import OnboardingShell from '../components/OnboardingShell';
import SocialAuthButtons from '../components/SocialAuthButtons';
import { LEGAL_LINKS } from '../lib/legal';
import { onboardingPath } from '../lib/onboarding';

/**
 * RegisterPage — step 1 of 3 ("Vos informations"), from the approved mockup:
 * nom + prénom side by side, téléphone with the +33 prefix, email, mot de
 * passe with an eye toggle, the CGU + confidentialité checkbox (the backend
 * refuses the account without it), "Continuer →". Creates the user + tenant
 * stub, auto-logs-in, then goes to step 2 (/onboarding/entreprise).
 */
const Field = ({ icon: Icon, children, trailing }) => (
  <div className="flex items-stretch rounded-xl border border-[#E1E8F5] bg-white transition focus-within:border-[#2F6BFF] focus-within:ring-4 focus-within:ring-[#2F6BFF]/10">
    <div className="flex w-12 shrink-0 items-center justify-center border-r border-[#EEF2F9] text-[#2F6BFF]" aria-hidden="true">
      <Icon size={18} strokeWidth={1.8} />
    </div>
    <div className="flex min-w-0 flex-1 items-stretch">{children}</div>
    {trailing}
  </div>
);
const INPUT = 'w-full bg-transparent px-4 py-3 text-[15px] text-[#0F172A] outline-none placeholder:text-[#94A3B8]';
const Label = ({ children }) => <label className="mb-1.5 block text-[14px] font-semibold text-[#0B1C3F]">{children} *</label>;
const PREFIXES = [['+33', '🇫🇷'], ['+32', '🇧🇪'], ['+41', '🇨🇭'], ['+352', '🇱🇺'], ['+1', '🇨🇦']];

const RegisterPage = () => {
  const { t } = useTranslation();
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ last_name: '', first_name: '', prefix: '+33', phone: '', email: '', password: '', accepted_terms: false });
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const handleSubmit = async (e) => {
    e.preventDefault(); setError('');
    if (!form.last_name.trim())  return setError(t('auth.last_name_required'));
    if (!form.first_name.trim()) return setError(t('auth.first_name_required'));
    if (!form.phone.trim())      return setError(t('signup.phone_required'));
    if (!form.email.trim())      return setError(t('auth.email_required'));
    if (!passwordValid(form.password)) {
      const missing = passwordRules(form.password).filter((r) => !r.ok).map((r) => r.label);
      return setError(`${t('auth.password_weak')} ${missing.join(', ')}.`);
    }
    if (!form.accepted_terms) return setError(t('auth.terms_required'));
    setLoading(true);
    try {
      const { prefix, phone, ...rest } = form;
      const session = await register({ ...rest, phone: `${prefix} ${phone.trim()}`, role: 'business_owner' });
      navigate(onboardingPath({ role: 'business_owner', ...session }) || '/modules');
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || t('auth.register_failed'));
    } finally { setLoading(false); }
  };

  return (
    <OnboardingShell step={1}>
      <div className="mt-7 text-center">
        <h1 className="text-[34px] font-extrabold tracking-[-0.02em] text-[#0B1C3F]">{t('signup.title')}</h1>
        <p className="mt-2 text-[16px] text-[#4B5C7A]">{t('signup.subtitle')}</p>
      </div>
      {error && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">⚠ {error}</div>}

      <form onSubmit={handleSubmit} className="mt-7 space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div><Label>{t('auth.last_name')}</Label>
            <Field icon={User}><input required type="text" autoComplete="family-name" placeholder={t('signup.last_name_placeholder')} className={INPUT} value={form.last_name} onChange={set('last_name')} /></Field></div>
          <div><Label>{t('auth.first_name')}</Label>
            <Field icon={User}><input required type="text" autoComplete="given-name" placeholder={t('signup.first_name_placeholder')} className={INPUT} value={form.first_name} onChange={set('first_name')} /></Field></div>
        </div>
        <div><Label>{t('auth.phone')}</Label>
          <Field icon={Phone}>
            <select value={form.prefix} onChange={set('prefix')} aria-label="Indicatif"
                    className="shrink-0 cursor-pointer border-r border-[#EEF2F9] bg-transparent px-3 text-[14px] font-semibold text-[#0B1C3F] outline-none">
              {PREFIXES.map(([p, f]) => <option key={p} value={p}>{f} {p}</option>)}
            </select>
            <input required type="tel" autoComplete="tel-national" placeholder={t('signup.phone_placeholder')} className={INPUT} value={form.phone} onChange={set('phone')} />
          </Field></div>
        <div><Label>{t('auth.email')}</Label>
          <Field icon={Mail}><input required type="email" autoComplete="email" placeholder="votre@email.com" className={INPUT} value={form.email} onChange={set('email')} /></Field></div>
        <div><Label>{t('auth.password')}</Label>
          <Field icon={Lock} trailing={
            <button type="button" onClick={() => setShowPw((v) => !v)} aria-label={showPw ? t('auth.hide_password') : t('auth.show_password')} className="px-4 text-[#2F6BFF] hover:text-[#1D4ED8]">
              {showPw ? <EyeOff size={20} /> : <Eye size={20} />}
            </button>}>
            <input required type={showPw ? 'text' : 'password'} autoComplete="new-password" placeholder={t('signup.password_placeholder')} className={INPUT} value={form.password} onChange={set('password')} />
          </Field>
          <p className="mt-1.5 text-[12px] text-[#94A3B8]">{t('signup.password_hint')}</p>
        </div>

        <div className="pt-1"><SocialAuthButtons onError={setError} layout="row" /></div>

        <label className="flex cursor-pointer items-start gap-3 pt-1 text-[14px] leading-relaxed text-[#4B5C7A]">
          <input type="checkbox" checked={form.accepted_terms} onChange={set('accepted_terms')} className="mt-1 h-[18px] w-[18px] shrink-0 rounded border-[#CBD5E1] accent-[#2F6BFF]" />
          <span>
            {t('auth.terms_prefix')} <a href={LEGAL_LINKS.cgu} target="_blank" rel="noreferrer" className="font-medium text-[#2F6BFF] underline">{t('signup.terms_cgu')}</a>{' '}
            {t('auth.terms_and')} <a href={LEGAL_LINKS.privacy} target="_blank" rel="noreferrer" className="font-medium text-[#2F6BFF] underline">{t('signup.terms_privacy')}</a> {t('auth.terms_suffix')}
          </span>
        </label>

        <button type="submit" disabled={loading}
                className="mt-1 inline-flex w-full items-center justify-center gap-3 rounded-2xl py-4 text-[17px] font-semibold text-white transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60"
                style={{ background: '#0A6CFF', boxShadow: '0 12px 28px -12px rgba(10,108,255,.6)' }}>
          {loading ? t('auth.creating') : <>{t('signup.continue')} <ArrowRight size={20} /></>}
        </button>
        <p className="flex items-center justify-center gap-2 pt-1 text-[14px] text-[#4B5C7A]">
          <ShieldCheck size={16} className="text-[#0B1C3F]" /> {t('login.secure_note')}
        </p>
      </form>
    </OnboardingShell>
  );
};
export default RegisterPage;
