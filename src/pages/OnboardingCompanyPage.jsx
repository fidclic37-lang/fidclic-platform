import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Building2, Store, MapPin, Mail, Globe, ChevronDown } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { onboardingAPI } from '../lib/api';
import { LEGAL_LINKS } from '../lib/legal';
import OnboardingShell, { Field, FieldLabel, INPUT, StepButtons } from '../components/OnboardingShell';

/**
 * OnboardingCompanyPage — STEP 2 of 4: "Votre établissement" (approved mockup).
 *
 *   nom de l'établissement · secteur · adresse · code postal · ville · pays
 *   → POST /api/onboarding/company → tenant onboarding_status="plan" (still a
 *     hidden draft) → step 3 (/onboarding/formule), where the trial starts.
 *
 * The backend still stores legal_name (Kbis name) — at signup it is the shop
 * name; SIRET / raison sociale / activité can be completed later in Settings.
 *
 * Reached right after /register (auto-login) or after a first Google /
 * Apple sign-in. The route guards in App.jsx send any business_owner with
 * onboarding_status="company" back here until it is completed. Google /
 * Apple users never saw the step-1 consent checkbox, so it is shown here
 * for them (the backend refuses to complete without it).
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
const COUNTRIES = [
  { code: 'FR', flag: '🇫🇷', label: 'France' },
  { code: 'BE', flag: '🇧🇪', label: 'Belgique' },
  { code: 'CH', flag: '🇨🇭', label: 'Suisse' },
  { code: 'LU', flag: '🇱🇺', label: 'Luxembourg' },
  { code: 'MC', flag: '🇲🇨', label: 'Monaco' },
];
const SELECT = INPUT + ' cursor-pointer appearance-none pr-10';
const Caret = () => <ChevronDown size={18} className="pointer-events-none mr-4 self-center text-[#2F6BFF]" />;

const OnboardingCompanyPage = () => {
  const { t } = useTranslation();
  const { checkAuth } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: '', sector: '', address: '', postal_code: '', city: '', country: 'FR', accepted_terms: false });
  const [needsTerms, setNeedsTerms] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    onboardingAPI.status().then((r) => {
      const d = r.data || {};
      setNeedsTerms(!d.terms_accepted);
      setForm((f) => ({ ...f, postal_code: d.prefill?.postal_code || f.postal_code, sector: d.prefill?.sector || f.sector }));
    }).catch(() => {});
  }, []);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (form.name.trim().length < 2) return setError(t('onboarding.name_required'));
    if (!form.sector) return setError(t('onboarding.sector_required'));
    if (!form.address.trim() || !form.city.trim()) return setError(t('onboarding.address_required'));
    if (!/^\d{5}$/.test(form.postal_code.trim())) return setError(t('onboarding.postal_code_invalid'));
    if (needsTerms && !form.accepted_terms) return setError(t('auth.terms_required'));
    setLoading(true);
    try {
      await onboardingAPI.company({
        legal_name: form.name.trim(), name: form.name.trim(), sector: form.sector,
        address: form.address.trim(), postal_code: form.postal_code.trim(), city: form.city.trim(),
        country: form.country, accepted_terms: needsTerms ? form.accepted_terms : undefined,
      });
      await checkAuth();            // refreshes user.onboarding_status → guards let us through
      navigate('/onboarding/formule', { replace: true });
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || t('onboarding.failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <OnboardingShell step={2}>
      <div className="mt-8 text-center">
        <h1 className="text-[36px] font-extrabold tracking-[-0.02em] text-[#0B1C3F]">{t('onboarding.title')}</h1>
        <p className="mt-2 text-[16px] text-[#4B5C7A]">{t('onboarding.subtitle')}</p>
      </div>
      {error && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">⚠ {error}</div>}

      <form onSubmit={handleSubmit} className="mt-8 space-y-6">
        <div>
          <FieldLabel>{t('onboarding.name')}</FieldLabel>
          <Field icon={Building2}>
            <input required type="text" autoComplete="organization" placeholder={t('onboarding.name_placeholder')}
                   className={INPUT} value={form.name} onChange={set('name')} />
          </Field>
        </div>
        <div>
          <FieldLabel>{t('auth.sector')}</FieldLabel>
          <Field icon={Store} trailing={<Caret />}>
            <select required className={SELECT + (form.sector ? '' : ' text-[#94A3B8]')} value={form.sector} onChange={set('sector')}>
              <option value="" disabled>{t('onboarding.sector_placeholder')}</option>
              {SECTOR_KEYS.map((s) => <option key={s.value} value={s.value}>{t(s.i18nKey)}</option>)}
            </select>
          </Field>
        </div>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-[1.15fr_1fr]">
          <div>
            <FieldLabel>{t('onboarding.address')}</FieldLabel>
            <Field icon={MapPin}>
              <input required type="text" autoComplete="street-address" placeholder={t('onboarding.address_placeholder')}
                     className={INPUT} value={form.address} onChange={set('address')} />
            </Field>
          </div>
          <div>
            <FieldLabel>{t('auth.postal_code')}</FieldLabel>
            <Field icon={Mail}>
              <input required type="text" inputMode="numeric" maxLength="5" autoComplete="postal-code" placeholder="75000"
                     className={INPUT} value={form.postal_code} onChange={set('postal_code')} />
            </Field>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-[1fr_1.15fr]">
          <div>
            <FieldLabel>{t('onboarding.city')}</FieldLabel>
            <Field icon={Building2}>
              <input required type="text" autoComplete="address-level2" placeholder={t('onboarding.city_placeholder')}
                     className={INPUT} value={form.city} onChange={set('city')} />
            </Field>
          </div>
          <div>
            <FieldLabel>{t('onboarding.country')}</FieldLabel>
            <Field icon={Globe} trailing={<Caret />}>
              <select className={SELECT} value={form.country} onChange={set('country')}>
                {COUNTRIES.map((c) => <option key={c.code} value={c.code}>{c.flag} {c.label}</option>)}
              </select>
            </Field>
          </div>
        </div>

        {needsTerms && (
          <label className="flex cursor-pointer items-start gap-2.5 text-[13px] leading-relaxed text-[#4B5C7A]">
            <input type="checkbox" checked={form.accepted_terms} onChange={set('accepted_terms')}
                   className="mt-0.5 h-4 w-4 shrink-0 rounded border-[#D6D3D1] accent-[#2F6BFF]" />
            <span>
              {t('auth.terms_prefix')}{' '}
              <a href={LEGAL_LINKS.cgu} target="_blank" rel="noreferrer" className="underline text-[#0B1C3F]">{t('auth.terms_cgu')}</a>,{' '}
              <a href={LEGAL_LINKS.privacy} target="_blank" rel="noreferrer" className="underline text-[#0B1C3F]">{t('auth.terms_privacy')}</a>{' '}
              {t('auth.terms_and')}{' '}
              <a href={LEGAL_LINKS.dpa} target="_blank" rel="noreferrer" className="underline text-[#0B1C3F]">{t('auth.terms_dpa')}</a>{' '}
              {t('auth.terms_suffix')}
            </span>
          </label>
        )}

        <StepButtons onBack={() => navigate(-1)} backLabel={t('onboarding.back')} nextLabel={t('onboarding.continue')} loading={loading} />
        <p className="text-center text-[12px] text-[#8B95A8]">{t('onboarding.trial_note')}</p>
      </form>
    </OnboardingShell>
  );
};
export default OnboardingCompanyPage;
