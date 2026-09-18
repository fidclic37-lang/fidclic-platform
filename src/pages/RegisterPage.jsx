import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { User, Mail, Lock, Phone, ArrowRight, Eye, EyeOff } from 'lucide-react';
import {
  passwordRules, passwordValid, passwordStrength,
  STRENGTH_LABELS, STRENGTH_COLORS,
} from '../lib/passwordPolicy';
import SocialAuthButtons from '../components/SocialAuthButtons';
import { LEGAL_LINKS } from '../lib/legal';

/**
 * RegisterPage — STEP 1 of 2 of the self-serve onboarding: the PERSON.
 *
 *   prénom · nom · email · téléphone · mot de passe · consent (CGU +
 *   Politique de confidentialité + DPA)  →  POST /api/auth/register
 *   → auto-login → /onboarding/entreprise (step 2: the COMPANY —
 *   raison sociale, secteur, activité, adresse; that is where the 28-day
 *   trial starts).
 *
 * Google / Apple sit under an "ou" divider: they skip this form entirely
 * and land on step 2, where the consent checkbox is collected instead.
 *
 * Layout uses the IconField flex pattern (44px icon column + divider +
 * borderless inner input) — do NOT go back to padding-left hacks, the icon
 * bled into the placeholder every single time.
 */
function IconField({ icon: Icon, children, trailing }) {
  return (
    <div className="flex items-stretch border border-[#E7E5E4] rounded-xl bg-white overflow-hidden focus-within:ring-2 focus-within:ring-[#B85C38]/20 focus-within:border-[#B85C38] transition">
      <div className="flex items-center justify-center px-3 text-[#B85C38] bg-[#FAF5F2] border-r border-[#E7E5E4] shrink-0"
           style={{ width: 44 }} aria-hidden="true">
        <Icon size={16} />
      </div>
      <div className="flex-1 min-w-0">{children}</div>
      {trailing}
    </div>
  );
}

const INNER_INPUT = 'w-full px-3 py-3 text-sm bg-transparent outline-none placeholder:text-[#A8A29E]';

const RegisterPage = () => {
  const { t } = useTranslation();
  const { register } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({
    first_name: '', last_name: '', email: '', phone: '', password: '', accepted_terms: false,
  });
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const pwRules = passwordRules(form.password);
  const pwStrength = passwordStrength(form.password);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!form.first_name.trim()) return setError(t('auth.first_name_required'));
    if (!form.last_name.trim())  return setError(t('auth.last_name_required'));
    if (!form.email.trim())      return setError(t('auth.email_required'));
    if (!passwordValid(form.password)) {
      const missing = pwRules.filter((r) => !r.ok).map((r) => r.label);
      return setError(`${t('auth.password_weak')} ${missing.join(', ')}.`);
    }
    if (!form.accepted_terms) return setError(t('auth.terms_required'));

    setLoading(true);
    try {
      const session = await register({ ...form, role: 'business_owner' });
      navigate(session?.onboarding_status === 'company' ? '/onboarding/entreprise' : '/modules');
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || t('auth.register_failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4"
         style={{ background: 'radial-gradient(circle at 30% 0%, #FCE3DC 0%, transparent 50%), radial-gradient(circle at 100% 100%, #FDE7C7 0%, transparent 60%), #FDFBF7' }}>
      <div className="bg-white p-8 rounded-3xl shadow-xl border border-[#E7E5E4] w-full max-w-md">
        <div className="text-center mb-6">
          <Link to="/" className="font-['Cormorant_Garamond'] text-3xl font-bold ft-gradient-text">FidéliTour</Link>
          <h2 className="text-2xl font-bold text-[#1C1917] mt-4" style={{ fontFamily: 'Cormorant Garamond' }}>
            {t('auth.register_title')}
          </h2>
          <p className="text-[#57534E] mt-1 text-sm">{t('auth.register_subtitle')}</p>
          <p className="text-[10px] font-bold uppercase tracking-widest text-[#8B8680] mt-3">
            {t('auth.step_of', { n: 1, total: 2 })} · {t('auth.step1_label')}
          </p>
        </div>

        {error && (
          <div className="bg-red-50 text-red-700 border border-red-200 p-3 rounded-xl text-sm mb-4">⚠ {error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-[#57534E] mb-1">{t('auth.first_name')}</label>
              <IconField icon={User}>
                <input required type="text" autoComplete="given-name" placeholder={t('auth.first_name_placeholder')}
                       className={INNER_INPUT} value={form.first_name} onChange={set('first_name')} />
              </IconField>
            </div>
            <div>
              <label className="block text-xs font-semibold text-[#57534E] mb-1">{t('auth.last_name')}</label>
              <IconField icon={User}>
                <input required type="text" autoComplete="family-name" placeholder={t('auth.last_name_placeholder')}
                       className={INNER_INPUT} value={form.last_name} onChange={set('last_name')} />
              </IconField>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-[#57534E] mb-1">{t('auth.email')}</label>
            <IconField icon={Mail}>
              <input required type="email" autoComplete="email" placeholder={t('auth.email_placeholder')}
                     className={INNER_INPUT} value={form.email} onChange={set('email')} />
            </IconField>
          </div>

          <div>
            <label className="block text-xs font-semibold text-[#57534E] mb-1">{t('auth.phone')}</label>
            <IconField icon={Phone}>
              <input type="tel" autoComplete="tel" placeholder={t('auth.phone_placeholder')}
                     className={INNER_INPUT} value={form.phone} onChange={set('phone')} />
            </IconField>
          </div>

          <div>
            <label className="block text-xs font-semibold text-[#57534E] mb-1">{t('auth.password')}</label>
            <IconField icon={Lock} trailing={
              <button type="button" onClick={() => setShowPw((v) => !v)}
                      aria-label={showPw ? t('auth.hide_password') : t('auth.show_password')}
                      className="px-3 text-[#8B8680] hover:text-[#1C1917] transition">
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            }>
              <input required type={showPw ? 'text' : 'password'} autoComplete="new-password"
                     placeholder={t('auth.password_placeholder')}
                     className={INNER_INPUT} value={form.password} onChange={set('password')} />
            </IconField>

            {/* Rules are visible BEFORE typing — a user should know what is
                expected upfront; they turn green as the password grows. */}
            <div className="mt-2 px-1">
              {form.password.length > 0 && (
                <>
                  <div className="flex gap-1 mb-1.5">
                    {[0, 1, 2, 3].map((i) => (
                      <div key={i} className="h-1.5 flex-1 rounded-full transition-colors"
                           style={{ background: i < pwStrength ? STRENGTH_COLORS[pwStrength] : '#EFE9E0' }} />
                    ))}
                  </div>
                  <div className="text-[11px] font-semibold mb-1.5" style={{ color: STRENGTH_COLORS[pwStrength] }}>
                    {STRENGTH_LABELS[pwStrength]}
                  </div>
                </>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-0.5">
                {pwRules.map((r) => {
                  const started = form.password.length > 0;
                  return (
                    <div key={r.id} className="flex items-center gap-1.5 text-[11px] transition-colors"
                         style={{ color: started && r.ok ? '#2F7A52' : '#8B8680' }}>
                      <span className="w-3.5 text-center">{started && r.ok ? '✓' : '○'}</span>{r.label}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Consent — required by the backend too (400 without it). */}
          <label className="flex items-start gap-2.5 text-xs text-[#57534E] leading-relaxed cursor-pointer pt-1">
            <input type="checkbox" checked={form.accepted_terms} onChange={set('accepted_terms')}
                   className="mt-0.5 h-4 w-4 shrink-0 rounded border-[#D6D3D1] accent-[#B85C38]" />
            <span>
              {t('auth.terms_prefix')}{' '}
              <a href={LEGAL_LINKS.cgu} target="_blank" rel="noreferrer" className="underline text-[#1C1917]">{t('auth.terms_cgu')}</a>,{' '}
              <a href={LEGAL_LINKS.privacy} target="_blank" rel="noreferrer" className="underline text-[#1C1917]">{t('auth.terms_privacy')}</a>{' '}
              {t('auth.terms_and')}{' '}
              <a href={LEGAL_LINKS.dpa} target="_blank" rel="noreferrer" className="underline text-[#1C1917]">{t('auth.terms_dpa')}</a>{' '}
              {t('auth.terms_suffix')}
            </span>
          </label>

          <button type="submit" disabled={loading}
                  className="w-full text-white py-3.5 rounded-full font-semibold text-sm mt-2 transition-all hover:-translate-y-0.5 disabled:opacity-60 disabled:cursor-not-allowed inline-flex items-center justify-center gap-2"
                  style={{ background: 'linear-gradient(135deg, #B85C38 0%, #E8917C 100%)', boxShadow: '0 8px 22px -8px rgba(184,92,56,0.55)' }}>
            {loading ? t('auth.creating') : <>{t('auth.create_account')} <ArrowRight size={16} /></>}
          </button>
        </form>

        <div className="mt-5">
          <SocialAuthButtons onError={setError} />
        </div>

        <p className="text-center mt-6 text-[#57534E] text-sm">
          {t('auth.have_account')}{' '}
          <Link to="/login" className="text-[#B85C38] font-semibold hover:underline">{t('auth.sign_in')}</Link>
        </p>
      </div>
    </div>
  );
};
export default RegisterPage;
