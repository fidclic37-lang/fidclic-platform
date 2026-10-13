import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Building2, Store, Globe, ChevronDown, Check } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { onboardingAPI } from '../lib/api';
import { LEGAL_LINKS } from '../lib/legal';
import OnboardingShell, { Field, FieldLabel, INPUT, StepButtons } from '../components/OnboardingShell';
import AddressPicker from '../components/AddressPicker';
import { countryOptions } from '../lib/countries';

/**
 * OnboardingCompanyPage — STEP 2 of 4: "Votre établissement" (approved mockup).
 *
 *   nom de l'établissement · secteur · pays · adresse (AddressPicker: picked
 *   from the address service, inside the chosen country — never free text)
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
const SELECT = INPUT + ' cursor-pointer appearance-none pr-10';
const Caret = () => <ChevronDown size={18} className="pointer-events-none mr-4 self-center text-[#2F6BFF]" />;

/* The sector, in FidClic's own list (QA BUG-002): the phone's native picker
   opened black and oversized in dark mode, unlike the rest of the page.
   A button and a listbox — click, ↑ ↓, Entrée, Échap, a tap outside closes. */
function SectorPicker({ value, onChange, options, placeholder, label }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);
  const chosen = options.find((o) => o.value === value);
  const pick = (v) => { onChange(v); setOpen(false); };
  const show = () => { setActive(Math.max(0, options.findIndex((o) => o.value === value))); setOpen(true); };
  const onKey = (e) => {
    if (e.key === 'Escape') { setOpen(false); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) { show(); return; }
      setActive((i) => (i + (e.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (open && active >= 0) pick(options[active].value); else show();
    }
  };
  return (
    <div className="relative" ref={box}>
      <Field icon={Store} trailing={<Caret />}>
        <button type="button" aria-haspopup="listbox" aria-expanded={open} aria-label={label}
                onClick={() => (open ? setOpen(false) : show())} onKeyDown={onKey}
                className={`${INPUT} text-left ${chosen ? '' : 'text-[#94A3B8]'}`}>
          {chosen ? chosen.label : placeholder}
        </button>
      </Field>
      {open && (
        <ul role="listbox" aria-label={label}
            className="absolute left-0 right-0 top-full z-30 mt-1.5 max-h-72 overflow-y-auto rounded-xl border border-[#E1E8F5] bg-white py-1 shadow-[0_18px_40px_-20px_rgba(11,28,63,.35)]">
          {options.map((o, i) => (
            <li key={o.value} role="option" aria-selected={o.value === value}
                onMouseDown={(e) => { e.preventDefault(); pick(o.value); }} onMouseEnter={() => setActive(i)}
                className={`flex cursor-pointer items-center justify-between gap-3 px-4 py-2.5 text-[14.5px] ${
                  i === active ? 'bg-[#F4F7FF]' : ''} ${o.value === value ? 'font-semibold text-[#2F6BFF]' : 'text-[#0F172A]'}`}>
              {o.label}{o.value === value && <Check size={16} aria-hidden="true" />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const OnboardingCompanyPage = () => {
  const { t, i18n } = useTranslation();
  const { user, checkAuth } = useAuth();
  const countries = useMemo(() => countryOptions(i18n.language || 'fr'), [i18n.language]);
  const [place, setPlace] = useState(null);
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: '', sector: '', country: 'FR', accepted_terms: false });
  const [needsTerms, setNeedsTerms] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    onboardingAPI.status().then((r) => {
      const d = r.data || {};
      setNeedsTerms(!d.terms_accepted);
      setForm((f) => ({ ...f, sector: d.prefill?.sector || f.sector }));
    }).catch(() => {});
  }, []);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (form.name.trim().length < 2) return setError(t('onboarding.name_required'));
    if (!form.sector) return setError(t('onboarding.sector_required'));
    if (!place) return setError(t('onboarding.address_pick'));
    if (place.kind === 'city' && place.address.trim().length < 3) return setError(t('onboarding.street_required'));
    if (place.needs_postcode && !place.postal_code.trim()) return setError(t('onboarding.postal_code_invalid'));
    if (needsTerms && !form.accepted_terms) return setError(t('auth.terms_required'));
    setLoading(true);
    try {
      await onboardingAPI.company({
        legal_name: form.name.trim(), name: form.name.trim(), sector: form.sector,
        country: form.country, address_token: place.address_token,
        address: place.address.trim(), postal_code: (place.postal_code || '').trim(),
        accepted_terms: needsTerms ? form.accepted_terms : undefined,
      });
      await checkAuth();            // refreshes user.onboarding_status → guards let us through
      navigate('/onboarding/formule', { replace: true });
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || t('onboarding.failed'));
    } finally {
      setLoading(false);
    }
  };

  // The e-mail/SMS code comes first (the route skips the generic gate).
  if (user?.onboarding_status === 'verify') return <Navigate to="/onboarding/verification" replace />;

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
          <SectorPicker value={form.sector} label={t('auth.sector')} placeholder={t('onboarding.sector_placeholder')}
                        onChange={(v) => setForm((f) => ({ ...f, sector: v }))}
                        options={SECTOR_KEYS.map((s) => ({ value: s.value, label: t(s.i18nKey) }))} />
        </div>
        <div>
          <FieldLabel>{t('onboarding.country')}</FieldLabel>
          <Field icon={Globe} trailing={<Caret />}>
            <select className={SELECT} value={form.country} onChange={set('country')} autoComplete="country">
              {countries.map((c) => <option key={c.code} value={c.code}>{c.flag} {c.label}</option>)}
            </select>
          </Field>
        </div>
        <AddressPicker country={form.country} onChange={setPlace} />

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
