import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Mail, Lock, Eye, EyeOff, ArrowRight, ShieldCheck } from 'lucide-react';
import SocialAuthButtons, { routeAfterAuth } from '../components/SocialAuthButtons';
import api from '../lib/api';

/**
 * LoginPage — the approved mockup: a soft-blue welcome panel on the left,
 * the sign-in card on the right, "Créer un compte" top-right.
 *
 * Everything on it works: email + password → /api/auth/login; "Mot de passe
 * oublié ?" → /api/auth/forgot-password (magic link by email, neutral
 * response so accounts can't be enumerated); Google / Apple → the OAuth
 * flows in SocialAuthButtons (live as soon as GOOGLE_CLIENT_ID /
 * APPLE_CLIENT_ID are set in Vercel; disabled-with-tooltip until then).
 */
const LOGO = '/brand/fidclic-logo.png';
const ICON = '/brand/fidclic-icon.png';
const HERO = '/brand/login-hero.jpg';

const Field = ({ icon: Icon, children, trailing }) => (
  <div className="flex items-stretch rounded-xl border border-[#E1E8F5] bg-white transition focus-within:border-[#2F6BFF] focus-within:ring-4 focus-within:ring-[#2F6BFF]/10">
    <div className="flex w-12 shrink-0 items-center justify-center border-r border-[#EEF2F9] text-[#2F6BFF]" aria-hidden="true">
      <Icon size={18} strokeWidth={1.8} />
    </div>
    <div className="min-w-0 flex-1">{children}</div>
    {trailing}
  </div>
);
const INPUT = 'w-full bg-transparent px-4 py-3.5 text-[15px] text-[#0F172A] outline-none placeholder:text-[#94A3B8]';

const LoginPage = () => {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: '', password: '' });
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  // forgot-password: 'idle' → 'open' → 'sent'
  const [forgot, setForgot] = useState('idle');
  const [resetEmail, setResetEmail] = useState('');
  const variant = 3; // approved design: photo panel + full logo on the card

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await login(form);
      routeAfterAuth(navigate, res);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(detail && detail !== 'Incorrect credentials' ? detail : t('auth.invalid_credentials'));
    } finally {
      setLoading(false);
    }
  };

  const sendReset = async () => {
    const email = (resetEmail || form.email).trim();
    if (!email.includes('@')) return setError(t('auth.email_required'));
    try { await api.post('/auth/forgot-password', { email }); } catch (_e) { /* neutral by design */ }
    setForgot('sent');
  };

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-2" style={{ background: '#F4F8FE' }}>
      {/* ───────── Left: welcome panel ───────── */}
      {variant === 3 ? (
        /* The approved mockup's left panel (photo, logo, "Bienvenue chez
           FIDCLIC", benefits) is used as one image so it matches exactly. */
        <aside className="relative hidden overflow-hidden lg:block">
          <img src={HERO} alt="Bienvenue chez FidClic — la fidélité en un clic" className="absolute inset-0 h-full w-full object-cover object-center" />
        </aside>
      ) : (
      <aside className="relative hidden overflow-hidden lg:flex lg:flex-col lg:justify-between px-14 py-14"
             style={{ background: 'linear-gradient(160deg, #F1F7FF 0%, #E6F0FF 100%)' }}>
        <div aria-hidden="true" className="pointer-events-none absolute -right-32 -top-24 h-[520px] w-[520px] rounded-full"
             style={{ background: 'radial-gradient(closest-side, #DCE9FF 0%, rgba(220,233,255,0) 72%)' }} />
        <div aria-hidden="true" className="pointer-events-none absolute -bottom-40 -left-24 h-[560px] w-[620px] rounded-[45%]"
             style={{ background: 'radial-gradient(closest-side, #D3E3FF 0%, rgba(211,227,255,0) 70%)' }} />
        <div className="relative">
          <img src={LOGO} alt="FidClic — La fidélité en un clic" className="h-[64px] w-auto" />
          <h1 className="mt-16 text-[56px] font-extrabold leading-[1.02] tracking-[-0.02em] text-[#0B1C3F]">
            {t('login.welcome_line1')}<br />
            <span className="text-[#2F6BFF]">FIDCLIC</span> <span aria-hidden="true">👋</span>
          </h1>
          <p className="mt-6 max-w-md text-[19px] leading-relaxed text-[#4B5C7A]">{t('login.welcome_sub')}</p>
        </div>
        <div className="relative">
          <div className="mb-5 h-[3px] w-9 rounded-full bg-[#2F6BFF]" />
          <p className="max-w-xs text-[19px] leading-snug text-[#3B4A66]" style={{ fontFamily: "'Caveat', 'Segoe Script', cursive" }}>
            {t('login.quote')}
          </p>
        </div>
      </aside>
      )}

      {/* ───────── Right: sign-in card ───────── */}
      <main className="relative flex min-h-screen flex-col items-center justify-center px-5 py-10 lg:px-12">
        <div className="absolute right-6 top-6 text-[14px] text-[#4B5C7A] lg:right-12 lg:top-10">
          {t('auth.no_account')}{' '}
          <Link to="/register" className="font-semibold text-[#2F6BFF] hover:underline">{t('login.create_account')}</Link>
        </div>

        <div className="w-full max-w-[640px] rounded-[22px] border border-[#E6EEFB] bg-white px-7 py-10 shadow-[0_24px_60px_-30px_rgba(47,107,255,.25)] sm:px-11">
          <div className="text-center">
            {variant === 1
              ? <img src={ICON} alt="FidClic" className="mx-auto h-[40px] w-[40px] rounded-lg" />
              : <img src={LOGO} alt="FidClic" className="mx-auto h-[52px] w-auto" />}
            <h2 className="mt-5 text-[40px] font-extrabold tracking-[-0.025em] text-[#0B1C3F]">{t('login.title')}</h2>
            <p className="mt-2 text-[16px] text-[#4B5C7A]">{t('login.subtitle')}</p>
          </div>

          {error && (
            <div className="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">⚠ {error}</div>
          )}

          <form onSubmit={handleSubmit} className="mt-8 space-y-5">
            <div>
              <label className="mb-2 block text-[15px] font-semibold text-[#0B1C3F]">{t('auth.email')} *</label>
              <Field icon={Mail}>
                <input required type="email" autoComplete="email" placeholder="votre@email.com"
                       className={INPUT} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </Field>
            </div>

            <div>
              <label className="mb-2 block text-[15px] font-semibold text-[#0B1C3F]">{t('auth.password')} *</label>
              <Field icon={Lock} trailing={
                <button type="button" onClick={() => setShowPw((v) => !v)}
                        aria-label={showPw ? t('auth.hide_password') : t('auth.show_password')}
                        className="px-4 text-[#2F6BFF] hover:text-[#1D4ED8]">
                  {showPw ? <EyeOff size={20} /> : <Eye size={20} />}
                </button>
              }>
                <input required type={showPw ? 'text' : 'password'} autoComplete="current-password"
                       placeholder={t('login.password_placeholder')}
                       className={INPUT} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              </Field>
              <div className="mt-2 text-right">
                <button type="button" onClick={() => { setForgot(forgot === 'idle' ? 'open' : 'idle'); setError(''); }}
                        className="text-[14px] font-semibold text-[#2F6BFF] hover:underline">
                  {t('auth.forgot_password')}
                </button>
              </div>
              {forgot !== 'idle' && (
                <div className="mt-3 rounded-xl border border-[#E1E8F5] bg-[#F8FAFF] p-4 text-[13px] text-[#4B5C7A]">
                  {forgot === 'sent' ? (
                    <p className="font-semibold text-[#15803D]">✓ {t('login.reset_sent')}</p>
                  ) : (
                    <>
                      <p>{t('login.reset_help')}</p>
                      <div className="mt-2 flex gap-2">
                        <input type="email" value={resetEmail || form.email} onChange={(e) => setResetEmail(e.target.value)}
                               placeholder="votre@email.com"
                               className="flex-1 rounded-lg border border-[#E1E8F5] bg-white px-3 py-2 text-[13px] outline-none focus:border-[#2F6BFF]" />
                        <button type="button" onClick={sendReset}
                                className="rounded-lg bg-[#2F6BFF] px-4 py-2 text-[13px] font-semibold text-white hover:bg-[#1D4ED8]">
                          {t('login.reset_send')}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>

            <button type="submit" disabled={loading}
                    className="mt-2 inline-flex w-full items-center justify-center gap-3 rounded-2xl py-4 text-[17px] font-semibold text-white transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60"
                    style={{ background: '#0A6CFF', boxShadow: '0 12px 28px -12px rgba(10,108,255,.6)' }}>
              {loading ? t('login.loading') : <>{t('auth.login_button')} <ArrowRight size={20} /></>}
            </button>
          </form>

          <div className="my-7 flex items-center gap-4 text-[14px] text-[#6B7A99]">
            <div className="h-px flex-1 bg-[#E6EEFB]" /><span>{t('login.or_continue')}</span><div className="h-px flex-1 bg-[#E6EEFB]" />
          </div>

          <SocialAuthButtons onError={setError} layout="row" />

          <p className="mt-9 flex items-center justify-center gap-2 text-[14px] text-[#4B5C7A]">
            <ShieldCheck size={16} className="text-[#2F6BFF]" /> {t('login.secure_note')}
          </p>
        </div>
      </main>
    </div>
  );
};
export default LoginPage;
