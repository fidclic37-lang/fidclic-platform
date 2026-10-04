import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MapPin, Building2, Mail, CheckCircle2, Loader2 } from 'lucide-react';
import { onboardingAPI } from '../lib/api';
import { Field, FieldLabel, INPUT } from './OnboardingShell';

/**
 * AddressPicker — step 2's address, always from the address service, inside
 * the selected country (api/services/addresses.py).
 *
 *   address mode  type → suggestions → pick one: street, postal code and city
 *                 are filled and locked.
 *   city mode     « Je ne trouve pas mon adresse » → pick the CITY from the
 *                 list, type the street (and the postal code when the city's
 *                 record has none).
 *
 * The parent gets onChange(value): null until something is picked, then
 * { address_token, kind, address, postal_code, needs_postcode }. The server
 * re-checks everything from the signed token, so this is the only way an
 * address gets in.
 */
function useSuggestions(country, kind, query) {
  const [state, setState] = useState({ results: [], loading: false, error: '' });
  const seq = useRef(0);
  useEffect(() => {
    const q = query.trim();
    if (q.length < (kind === 'city' ? 2 : 3)) { setState({ results: [], loading: false, error: '' }); return undefined; }
    const my = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: '' }));
    const timer = setTimeout(() => {
      onboardingAPI.addressSearch({ q, country, kind })
        .then((r) => { if (my === seq.current) setState({ results: r.data?.results || [], loading: false, error: '' }); })
        .catch((e) => { if (my === seq.current) setState({ results: [], loading: false, error: e?.response?.data?.detail || 'error' }); });
    }, 280);
    return () => clearTimeout(timer);
  }, [country, kind, query]);
  return state;
}

function SearchBox({ icon, kind, country, placeholder, onPick, autoFocus }) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const { results, loading, error } = useSuggestions(country, kind, query);
  const pick = (r) => { setOpen(false); setQuery(''); onPick(r); };
  const onKey = (e) => {
    if (!open || !results.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(results[active]); }
    else if (e.key === 'Escape') setOpen(false);
  };
  const showList = open && query.trim().length >= (kind === 'city' ? 2 : 3);
  return (
    <div className="relative">
      <Field icon={icon} trailing={loading ? <Loader2 size={18} className="mr-4 self-center animate-spin text-[#94A3B8]" /> : null}>
        <input type="text" autoComplete="off" autoFocus={autoFocus} placeholder={placeholder} className={INPUT}
               role="combobox" aria-expanded={showList} aria-autocomplete="list"
               value={query} onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0); }}
               onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)} onKeyDown={onKey} />
      </Field>
      {showList && (
        <ul role="listbox" className="absolute left-0 right-0 z-20 mt-1.5 max-h-72 overflow-auto rounded-xl border border-[#E1E8F5] bg-white py-1 shadow-[0_18px_40px_-20px_rgba(15,23,42,.35)]">
          {error && <li className="px-4 py-3 text-[13.5px] text-red-700">{error === 'error' ? t('onboarding.address_unavailable') : error}</li>}
          {!error && !loading && !results.length && <li className="px-4 py-3 text-[13.5px] text-[#64748B]">{t('onboarding.address_no_results')}</li>}
          {results.map((r, i) => (
            <li key={r.token} role="option" aria-selected={i === active}
                onMouseDown={(e) => { e.preventDefault(); pick(r); }} onMouseEnter={() => setActive(i)}
                className={`flex cursor-pointer items-start gap-2.5 px-4 py-2.5 text-[14px] ${i === active ? 'bg-[#EEF4FF]' : ''}`}>
              <MapPin size={16} className="mt-0.5 shrink-0 text-[#2F6BFF]" />
              <span className="text-[#0B1C3F]">{r.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Picked({ label, onChange }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-3 rounded-xl border border-[#BFE3CC] bg-[#F1FAF4] px-4 py-3">
      <CheckCircle2 size={18} className="shrink-0 text-[#16803C]" />
      <span className="min-w-0 flex-1 text-[15px] text-[#0B1C3F]">{label}</span>
      <button type="button" onClick={onChange} className="shrink-0 text-[13.5px] font-semibold text-[#2F6BFF] hover:underline">
        {t('onboarding.address_change')}
      </button>
    </div>
  );
}

export default function AddressPicker({ country, onChange }) {
  const { t } = useTranslation();
  const [mode, setMode] = useState('address');
  const [item, setItem] = useState(null);
  const [street, setStreet] = useState('');
  const [postal, setPostal] = useState('');

  // Another country: whatever was picked belongs to the old one.
  useEffect(() => { setItem(null); setStreet(''); setPostal(''); }, [country]);

  useEffect(() => {
    if (!item) { onChange(null); return; }
    onChange({
      address_token: item.token, kind: item.kind,
      address: item.kind === 'city' ? street : '',
      postal_code: item.postcode || postal,
      needs_postcode: !item.postcode,
    });
  }, [item, street, postal]); // eslint-disable-line react-hooks/exhaustive-deps

  const switchMode = (m) => { setMode(m); setItem(null); setStreet(''); setPostal(''); };

  if (mode === 'address') {
    return (
      <div>
        <FieldLabel>{t('onboarding.address')}</FieldLabel>
        {item ? <Picked label={item.label} onChange={() => setItem(null)} />
              : <SearchBox key={country} icon={MapPin} kind="address" country={country}
                           placeholder={t('onboarding.address_search_placeholder')} onPick={setItem} />}
        <p className="mt-2 text-[12.5px] text-[#64748B]">
          {t('onboarding.address_hint')}{' '}
          <button type="button" onClick={() => switchMode('city')} className="font-semibold text-[#2F6BFF] hover:underline">
            {t('onboarding.address_not_found_link')}
          </button>
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-5">
      <div>
        <FieldLabel>{t('onboarding.city')}</FieldLabel>
        {item ? <Picked label={item.label} onChange={() => setItem(null)} />
              : <SearchBox key={country} icon={Building2} kind="city" country={country} autoFocus
                           placeholder={t('onboarding.city_search_placeholder')} onPick={setItem} />}
      </div>
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-[1.4fr_1fr]">
        <div className={item && !item.postcode ? '' : 'sm:col-span-2'}>
          <FieldLabel>{t('onboarding.street')}</FieldLabel>
          <Field icon={MapPin}>
            <input type="text" autoComplete="address-line1" placeholder={t('onboarding.street_placeholder')}
                   className={INPUT} value={street} onChange={(e) => setStreet(e.target.value)} />
          </Field>
        </div>
        {item && !item.postcode && (
          <div>
            <FieldLabel>{t('auth.postal_code')}</FieldLabel>
            <Field icon={Mail}>
              <input type="text" autoComplete="postal-code" className={INPUT} value={postal}
                     onChange={(e) => setPostal(e.target.value)} />
            </Field>
          </div>
        )}
      </div>
      <button type="button" onClick={() => switchMode('address')} className="text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">
        {t('onboarding.address_back_link')}
      </button>
    </div>
  );
}
