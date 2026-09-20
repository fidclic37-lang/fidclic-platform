import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Building2, Store, Coffee, Tag, Hash, MapPin, Phone, ArrowRight } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { onboardingAPI } from '../lib/api';
import { LEGAL_LINKS } from '../lib/legal';
import OnboardingShell from '../components/OnboardingShell';

/**
 * OnboardingCompanyPage — STEP 2 of 2: the COMPANY.
 *
 *   raison sociale · nom commercial (optionnel) · secteur · activité ·
 *   SIRET (optionnel) · adresse · code postal · ville
 *   → POST /api/onboarding/company → tenant onboarding_status="done",
 *     28-day trial starts → /modules.
 *
 * Reached right after /register (auto-login) or after a first Google /
 * Apple sign-in. The route guards in App.jsx send any business_owner with
 * onboarding_status="company" back here until it is completed, so a
 * half-registered account can never wander into the dashboard.
 *
 * Google / Apple users never saw the step-1 consent checkbox, so it is
 * shown here for them (the backend refuses to complete without it).
 */
const SECTOR_KEYS = [
  { value: 'cafe',       i18nKey: 'auth.sector_cafe' },
  { value: 'restaurant', i18nKey: 'auth.sector_restaurant' },
  { value: 'pizzeria',   i18nKey: 'auth.sector_pizzeria' },
  { value: 'bakery',     i18nKey: 'auth.sector_bakery' },
  { value: 'bar',        i18nKey: 'auth.sector_bar' },
  { value: 'spa',        i18nKey: 'auth.sector_spa' },
  { value: 'salon',      i18nKey: 'auth.sector_salon' },
  { value: 'gym',        i18nKey: 'auth.sector_gym' },
  { value: 'retail',     i18nKey: 'auth.sector_retail' },
  { value: 'other',      i18nKey: 'auth.sector_other' },
];

function IconField({ icon: Icon, children }) {
  return (
    <div className="flex items-stretch border border-[#E7E5E4] rounded-xl bg-white overflow-hidden focus-within:ring-2 focus-within:ring-[#2F6BFF]/10 focus-within:ring-4 focus-within:border-[#2F6BFF] transition">
      <div className="flex items-center justify-center px-3 text-[#2F6BFF] bg-white border-r border-[#EEF2F9] shrink-0"
           style={{ width: 44 }} aria-hidden="true">
        <Icon size={16} />
      </div>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}

const INNER_INPUT = 'w-full px-3 py-3 text-sm bg-transparent outline-none placeholder:text-[#A8A29E]';
const Label = ({ children, optional, t }) => (
  <label className="block text-xs font-semibold text-[#57534E] mb-1">
    {children}{optional && <span className="font-normal text-[#A8A29E]"> · {t('auth.optional')}</span>}
  </label>
);

const OnboardingCompanyPage = () => {
  const { t } = useTranslation();
  const { user, checkAuth } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({
    legal_name: '', name: '', sector: 'cafe', activity: '', siret: '',
    address: '', postal_code: '', city: '', phone: '', accepted_terms: false,
  });
  const [needsTerms, setNeedsTerms] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Prefill what step 1 / the OAuth provider already told us.
    onboardingAPI.status().then((r) => {
      const d = r.data || {};
      setNeedsTerms(!d.terms_accepted);
      setForm((f) => ({
        ...f,
        phone: d.prefill?.phone || f.phone,
        postal_code: d.prefill?.postal_code || f.postal_code,
        sector: d.prefill?.sector || f.sector,
      }));
    }).catch(() => {});
  }, []);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (form.legal_name.trim().length < 2) return setError(t('onboarding.legal_name_required'));
    if (!form.address.trim() || !form.city.trim()) return setError(t('onboarding.address_required'));
    if (!/^\d{5}$/.test(form.postal_code.trim())) return setError(t('onboarding.postal_code_invalid'));
    const siretDigits = form.siret.replace(/\D/g, '');
    if (siretDigits && siretDigits.length !== 14) return setError(t('onboarding.siret_invalid'));
    if (needsTerms && !form.accepted_terms) return setError(t('auth.terms_required'));

    setLoading(true);
    try {
      await onboardingAPI.company({ ...form, siret: siretDigits || null });
      await checkAuth();            // refreshes user.onboarding_status → guards let us through
      navigate('/onboarding/carte', { replace: true });
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || t('onboarding.failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <OnboardingShell step={2}>
      <div className="mt-7 text-center">
        <h1 className="text-[30px] font-extrabold tracking-[-0.02em] text-[#0B1C3F]">
          {t('onboarding.title', { name: user?.first_name || '' }).trim()}
        </h1>
        <p className="mt-2 text-[15px] text-[#4B5C7A]">{t('onboarding.subtitle')}</p>
      </div>

        {error && (
          <div className="bg-red-50 text-red-700 border border-red-200 p-3 rounded-xl text-sm mb-4">⚠ {error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest text-[#8B8680] mb-2">{t('onboarding.section_identity')}</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="md:col-span-2">
                <Label t={t}>{t('onboarding.legal_name')}</Label>
                <IconField icon={Building2}>
                  <input required type="text" autoComplete="organization" placeholder={t('onboarding.legal_name_placeholder')}
                         className={INNER_INPUT} value={form.legal_name} onChange={set('legal_name')} />
                </IconField>
              </div>
              <div className="md:col-span-2">
                <Label t={t} optional>{t('onboarding.trade_name')}</Label>
                <IconField icon={Store}>
                  <input type="text" placeholder={t('onboarding.trade_name_placeholder')}
                         className={INNER_INPUT} value={form.name} onChange={set('name')} />
                </IconField>
              </div>
              <div>
                <Label t={t}>{t('auth.sector')}</Label>
                <IconField icon={Coffee}>
                  <select className={INNER_INPUT + ' appearance-none cursor-pointer pr-10'} value={form.sector} onChange={set('sector')}>
                    {SECTOR_KEYS.map((s) => <option key={s.value} value={s.value}>{t(s.i18nKey)}</option>)}
                  </select>
                </IconField>
              </div>
              <div>
                <Label t={t}>{t('onboarding.activity')}</Label>
                <IconField icon={Tag}>
                  <input type="text" placeholder={t('onboarding.activity_placeholder')}
                         className={INNER_INPUT} value={form.activity} onChange={set('activity')} />
                </IconField>
              </div>
              <div className="md:col-span-2">
                <Label t={t} optional>{t('onboarding.siret')}</Label>
                <IconField icon={Hash}>
                  <input type="text" inputMode="numeric" placeholder="123 456 789 00012"
                         className={INNER_INPUT} value={form.siret} onChange={set('siret')} />
                </IconField>
              </div>
            </div>
          </div>

          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest text-[#8B8680] mb-2 mt-2">{t('onboarding.section_address')}</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="md:col-span-3">
                <Label t={t}>{t('onboarding.address')}</Label>
                <IconField icon={MapPin}>
                  <input required type="text" autoComplete="street-address" placeholder={t('onboarding.address_placeholder')}
                         className={INNER_INPUT} value={form.address} onChange={set('address')} />
                </IconField>
              </div>
              <div>
                <Label t={t}>{t('auth.postal_code')}</Label>
                <IconField icon={MapPin}>
                  <input required type="text" inputMode="numeric" maxLength="5" autoComplete="postal-code" placeholder="37000"
                         className={INNER_INPUT} value={form.postal_code} onChange={set('postal_code')} />
                </IconField>
              </div>
              <div>
                <Label t={t}>{t('onboarding.city')}</Label>
                <IconField icon={MapPin}>
                  <input required type="text" autoComplete="address-level2" placeholder="Tours"
                         className={INNER_INPUT} value={form.city} onChange={set('city')} />
                </IconField>
              </div>
              <div>
                <Label t={t} optional>{t('onboarding.business_phone')}</Label>
                <IconField icon={Phone}>
                  <input type="tel" autoComplete="tel" placeholder="02 47 00 00 00"
                         className={INNER_INPUT} value={form.phone} onChange={set('phone')} />
                </IconField>
              </div>
            </div>
          </div>

          {needsTerms && (
            <label className="flex items-start gap-2.5 text-xs text-[#57534E] leading-relaxed cursor-pointer pt-1">
              <input type="checkbox" checked={form.accepted_terms} onChange={set('accepted_terms')}
                     className="mt-0.5 h-4 w-4 shrink-0 rounded border-[#D6D3D1] accent-[#2F6BFF]" />
              <span>
                {t('auth.terms_prefix')}{' '}
                <a href={LEGAL_LINKS.cgu} target="_blank" rel="noreferrer" className="underline text-[#1C1917]">{t('auth.terms_cgu')}</a>,{' '}
                <a href={LEGAL_LINKS.privacy} target="_blank" rel="noreferrer" className="underline text-[#1C1917]">{t('auth.terms_privacy')}</a>{' '}
                {t('auth.terms_and')}{' '}
                <a href={LEGAL_LINKS.dpa} target="_blank" rel="noreferrer" className="underline text-[#1C1917]">{t('auth.terms_dpa')}</a>{' '}
                {t('auth.terms_suffix')}
              </span>
            </label>
          )}

          <button type="submit" disabled={loading}
                  className="w-full text-white py-4 rounded-2xl font-semibold text-[17px] mt-4 transition-all hover:-translate-y-0.5 disabled:opacity-60 disabled:cursor-not-allowed inline-flex items-center justify-center gap-2"
                  style={{ background: '#0A6CFF', boxShadow: '0 12px 28px -12px rgba(10,108,255,.6)' }}>
            {loading ? t('auth.creating') : <>{t('onboarding.submit')} <ArrowRight size={16} /></>}
          </button>
          <p className="text-center text-[11px] text-[#8B8680]">{t('onboarding.trial_note')}</p>
        </form>
    </OnboardingShell>
  );
};
export default OnboardingCompanyPage;
