import React, { useEffect, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Mail, MessageSquare, ShieldCheck, Loader2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { onboardingAPI } from '../lib/api';
import OnboardingShell from '../components/OnboardingShell';

/**
 * OnboardingVerifyPage — right after step 1 (user, 2026-10-05): the owner picks
 * e-mail or SMS, receives a 6-digit code, types it → step 2. Only the channels
 * the server can actually use are offered (Brevo for e-mail, Twilio for SMS).
 * Google / Apple sign-ups never land here (their e-mail is already verified).
 */
export default function OnboardingVerifyPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user, checkAuth } = useAuth();
  const [st, setSt] = useState(null);
  const [sent, setSent] = useState(null);        // {channel, to}
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [wait, setWait] = useState(0);

  useEffect(() => {
    onboardingAPI.verifyState().then((r) => setSt(r.data)).catch(async (e) => {
      if (e?.response?.status === 409) { await checkAuth(); navigate('/onboarding/entreprise', { replace: true }); }
      else setErr(t('verify.failed'));
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (wait <= 0) return undefined;
    const id = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(id);
  }, [wait]);

  if (user && user.onboarding_status && user.onboarding_status !== 'verify') return <Navigate to="/onboarding/entreprise" replace />;

  const send = async (channel) => {
    setErr(''); setBusy('send');
    try {
      const r = await onboardingAPI.verifySend(channel);
      setSent({ channel, to: r.data.to }); setCode(''); setWait(60);
    } catch (e) {
      setErr(e?.response?.data?.detail || t('verify.failed'));
    } finally { setBusy(''); }
  };

  const verify = async (e) => {
    e.preventDefault(); setErr(''); setBusy('check');
    try {
      await onboardingAPI.verifyCheck(code);
      await checkAuth();
      navigate('/onboarding/entreprise', { replace: true });
    } catch (e2) {
      setErr(e2?.response?.data?.detail || t('verify.failed'));
      setBusy('');
    }
  };

  const ch = st?.channels || {};
  const none = st && !ch.email && !ch.sms;
  const btn = 'flex w-full items-center gap-3 rounded-2xl border border-[#E1E8F5] px-5 py-4 text-left transition hover:border-[#2F6BFF] hover:bg-[#F6F9FF] disabled:opacity-60';

  return (
    <OnboardingShell step={1}>
      <div className="mt-8 text-center">
        <span className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-[#EEF4FF] text-[#2F6BFF]"><ShieldCheck size={24} /></span>
        <h1 className="text-[32px] font-extrabold tracking-[-0.02em] text-[#0B1C3F]">{t('verify.title')}</h1>
        <p className="mx-auto mt-2 max-w-[440px] text-[15.5px] text-[#4B5C7A]">{t('verify.subtitle')}</p>
      </div>
      {err && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">⚠ {err}</div>}
      {!st && !err && <div className="mt-8 flex justify-center"><Loader2 className="animate-spin text-[#94A3B8]" /></div>}
      {none && <div className="mt-6 rounded-xl bg-[#FFF7E6] px-4 py-3 text-[14px] text-[#92400E]">{t('verify.none')}</div>}

      {st && !sent && !none && (
        <div className="mt-8 space-y-3">
          {ch.email && (
            <button type="button" className={btn} disabled={!!busy} onClick={() => send('email')}>
              <Mail className="text-[#2F6BFF]" size={22} />
              <span className="flex-1"><b className="block text-[15px] text-[#0B1C3F]">{t('verify.by_email')}</b><span className="text-[13.5px] text-[#64748B]">{st.email}</span></span>
              {busy === 'send' && <Loader2 size={18} className="animate-spin text-[#94A3B8]" />}
            </button>
          )}
          {ch.sms && (
            <button type="button" className={btn} disabled={!!busy} onClick={() => send('sms')}>
              <MessageSquare className="text-[#2F6BFF]" size={22} />
              <span className="flex-1"><b className="block text-[15px] text-[#0B1C3F]">{t('verify.by_sms')}</b><span className="text-[13.5px] text-[#64748B]">{st.phone}</span></span>
            </button>
          )}
        </div>
      )}

      {sent && (
        <form onSubmit={verify} className="mt-8 space-y-4">
          <p className="text-center text-[14px] text-[#16803C]">{t('verify.sent_to', { to: sent.to })}</p>
          <label htmlFor="otp" className="block text-[15px] font-semibold text-[#0B1C3F]">{t('verify.code_label')}</label>
          <input id="otp" inputMode="numeric" autoComplete="one-time-code" maxLength={7} autoFocus
                 value={code} onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, ''))}
                 className="w-full rounded-xl border border-[#E1E8F5] px-4 py-3 text-center text-[26px] font-bold tracking-[0.5em] text-[#0B1C3F] outline-none focus:border-[#2F6BFF] focus:ring-4 focus:ring-[#2F6BFF]/10"
                 placeholder="••••••" />
          <button type="submit" disabled={code.replace(/\D/g, '').length !== 6 || busy === 'check'}
                  className="flex w-full items-center justify-center gap-2 rounded-2xl py-4 text-[17px] font-semibold text-white disabled:opacity-50" style={{ background: '#0A6CFF' }}>
            {busy === 'check' && <Loader2 size={18} className="animate-spin" />} {t('verify.check')}
          </button>
          <div className="flex items-center justify-between text-[13.5px]">
            <button type="button" disabled={wait > 0 || !!busy} onClick={() => send(sent.channel)} className="font-semibold text-[#2F6BFF] disabled:text-[#94A3B8]">
              {wait > 0 ? t('verify.resend_in', { s: wait }) : t('verify.resend')}
            </button>
            {ch.email && ch.sms && (
              <button type="button" onClick={() => { setSent(null); setErr(''); }} className="font-semibold text-[#2F6BFF]">{t('verify.change')}</button>
            )}
          </div>
          {sent.channel === 'email' && <p className="text-center text-[12.5px] text-[#64748B]">{t('verify.spam')}</p>}
        </form>
      )}
    </OnboardingShell>
  );
}
