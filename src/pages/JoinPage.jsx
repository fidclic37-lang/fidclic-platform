import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, Link, useSearchParams, useNavigate, useLocation } from 'react-router-dom';
import api, { publicAPI } from '../lib/api';
import { QRCodeSVG } from 'qrcode.react';
import Code128Barcode from '../components/Code128Barcode';
import { SIGNUP_SOURCES, normalizeSource, sourceLabel } from '../lib/sources';
import { addMine, ownerLink } from '../lib/myCards';
import PhoneField, { phoneValueError } from '../components/PhoneField';

// « 37000 Tours », « 12 rue … 37000 » (autofill) → « 37000 »: the 5-digit group
// when there is one, otherwise the digits typed so far.
const postalDigits = (raw) => {
  const s = String(raw ?? '');
  const five = s.match(/(?:^|\D)(\d{5})(?:\D|$)/);
  return five ? five[1] : s.replace(/\D/g, '').slice(0, 5);
};

// Where they came from (lib/sources, user 2026-10-08): the channel of the link —
// /inscription/<slug>/insta, /wa, /qr… or the older ?src=ig / ?utm_source=fb.
// An unknown word is no source at all, never a guess.
function resolveSourceFromUrl(searchParams, channel) {
  const raw = channel || searchParams.get('src') || searchParams.get('source') || searchParams.get('utm_source') || '';
  const key = normalizeSource(raw);
  return key && SIGNUP_SOURCES.includes(key) ? key : null;
}

// Multi-touch attribution. Every time the visitor lands on /join/<slug>
// with a ?src=... param, append it to a per-tenant list in localStorage.
// On submit, the full chain travels with the form so the owner can see
// "joined via QR, but originally found us on Instagram a week earlier."
const TOUCHPOINTS_KEY = (slug) => `ft_touchpoints_${slug}`;

const loadTouchpoints = (slug) => {
  try {
    const raw = localStorage.getItem(TOUCHPOINTS_KEY(slug));
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch (_e) { return []; }
};

const recordTouchpoint = (slug, source) => {
  if (!source) return;
  try {
    const list = loadTouchpoints(slug);
    // Don't double-record the same source twice in a row (refresh, etc.).
    const last = list[list.length - 1];
    if (last && last.source === source) return;
    list.push({ source, ts: new Date().toISOString() });
    // Cap at 10 entries — anything older is statistical noise.
    while (list.length > 10) list.shift();
    localStorage.setItem(TOUCHPOINTS_KEY(slug), JSON.stringify(list));
  } catch (_e) { /* private mode etc — silent */ }
};

const clearTouchpoints = (slug) => {
  try { localStorage.removeItem(TOUCHPOINTS_KEY(slug)); } catch (_e) { /* ignore */ }
};

const JoinPage = () => {
  const { t } = useTranslation();
  const { slug, channel } = useParams();
  const [searchParams] = useSearchParams();
  const lockedSource = useMemo(() => resolveSourceFromUrl(searchParams, channel), [searchParams, channel]);
  // ?p=FT-XXXX — the card whose QR brought this visitor here. There is no
  // referral link and no second QR: an existing customer's own card is the
  // invitation, so the form says who invited them and the signup records it.
  const parrainBarcode = (searchParams.get('p') || '').trim().toUpperCase();
  const [inviter, setInviter] = useState(null);
  useEffect(() => {
    if (!parrainBarcode) return;
    let alive = true;
    api.get(`/card/${parrainBarcode}/inviter`)
      .then(({ data }) => { if (alive && data?.enabled) setInviter(data); })
      .catch(() => {});      // an unknown card just means no banner
    return () => { alive = false; };
  }, [parrainBarcode]);
  const [tenant, setTenant] = useState(null);
  const [closed, setClosed] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    phone: '',
    postal_code: '',
    birthday: '',
    // no channel in the link → the customer answers, or it stays « Non renseigné »
    acquisition_source: lockedSource || '',
  });
  const [geoStatus, setGeoStatus] = useState('idle'); // idle | requesting | granted | denied | unsupported
  const [geoCoords, setGeoCoords] = useState(null);
  // RGPD: explicit, unticked-by-default consent checkbox (Art. 7 — consent
  // must be a positive action, pre-ticked boxes are illegal per CJUE Planet49).
  const [consentChecked, setConsentChecked] = useState(false);
  // Student status — French merchants run student offers all year, so it is
  // asked once at signup rather than guessed later. Optional, never required.
  const [isStudent, setIsStudent] = useState(false);
  // The town is not asked for any more: the postal code already says it, and
  // more precisely than a free-text answer would (37100 is Tours Nord, not just
  // Tours). services/communes.py resolves it server-side.
  const [success, setSuccess] = useState(null);
  // Structured error from the join endpoint. Today the meaningful case
  // is the 403 "plan_limit_reached" — the loyalty programme has hit its
  // customer cap and we surface a friendly message instead of a generic
  // alert. All other failures fall back to a single-line error message.
  const [joinError, setJoinError] = useState(null);
  // phone and postal code are checked here, said under their field, and again
  // by the server (user, 2026-10-09)
  const [fieldErrors, setFieldErrors] = useState({});
  const postalRef = React.useRef(null);

  const navigate = useNavigate();
  const location = useLocation();
  const [page, setPage] = useState(null);
  const [logoBroken, setLogoBroken] = useState(false);
  useEffect(() => {
    publicAPI.getJoinInfo(slug).then(res => {
      // Opened through a name the shop had before a rename (a QR code printed
      // earlier): move to the live name so every later call uses it.
      const live = res.data?.slug;
      if (live && live !== slug) {
        const base = location.pathname.startsWith('/inscription/') ? '/inscription/' : '/join/';
        navigate(`${base}${live}${location.search}`, { replace: true });
        return;
      }
      setTenant(res.data);
    }).catch((e) => {
      // Résilié (2026-10-01): the business left FidClic — say so instead of loading forever.
      if (e?.response?.status === 410) setClosed(e.response.data?.detail || "Ce programme de fidélité n'est plus disponible.");
      else console.error(e);
    });
    publicAPI.joinPage(slug).then(({ data }) => setPage(data)).catch(() => {});
  }, [slug]); // eslint-disable-line react-hooks/exhaustive-deps

  // One visit per browser per day, for the figures on Paramètres › Lien
  // d'inscription. The id is random and stays in this browser — no personal
  // data. The owner's own "Aperçu" (?preview=1) is not counted.
  useEffect(() => {
    if (searchParams.get('preview')) return;
    let visitor = '';
    try {
      visitor = localStorage.getItem('fidclic:visitor') || '';
      if (!visitor) {
        visitor = Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, '0')).join('');
        localStorage.setItem('fidclic:visitor', visitor);
      }
    } catch (_e) { /* private mode: the visit simply is not counted */ }
    if (visitor) publicAPI.joinView(slug, { visitor, src: lockedSource }).catch(() => {});
  }, [slug]); // eslint-disable-line react-hooks/exhaustive-deps

  // Multi-touch attribution: record this URL's source the moment the page loads,
  // even if the visitor never submits. So when they finally fill the form a week
  // later (with maybe a different ?src=...), we still have the original touch.
  useEffect(() => {
    if (lockedSource) recordTouchpoint(slug, lockedSource);
  }, [slug, lockedSource]);

  // Why this is heavier than a one-liner getCurrentPosition: on desktop
  // browsers (Chrome/Firefox/Edge on a laptop without GPS) the call often
  // fails with error code 2 (POSITION_UNAVAILABLE) or 3 (TIMEOUT) after
  // a few seconds. The previous implementation silently reset the UI to
  // 'idle' on those errors, which made the button look broken — the user
  // tapped it and nothing visibly changed.
  //
  // Now we:
  //   1. Use the Permissions API (where available) to detect a prior
  //      "denied" state BEFORE calling getCurrentPosition, so the user
  //      sees an immediate explanation instead of waiting 10s for the
  //      silent timeout.
  //   2. Differentiate all 3 GeolocationPositionError codes so every
  //      failure path shows a visible message.
  //   3. Bump the timeout to 15s — desktops without GPS sometimes take
  //      that long to resolve via Wi-Fi triangulation.
  //   4. Disable enableHighAccuracy → desktop GPS-less browsers are much
  //      more reliable with the lower-precision Wi-Fi/IP lookup.
  const requestGeolocation = async () => {
    // FIRST THING: flip the UI to "requesting". Two reasons:
    //   1. Even on a slow desktop browser where the Permissions API or
    //      getCurrentPosition takes hundreds of ms, the user sees an
    //      immediate visual change — the button vanishes, "Demande de
    //      position en cours…" appears. Without this, the button looked
    //      broken on PC ("I clicked but nothing happened").
    //   2. Some PC browsers (especially Chrome on Windows behind corporate
    //      proxies) silently swallow getCurrentPosition with neither
    //      callback ever firing. The watchdog below catches that case.
    setGeoStatus('requesting');
    console.debug('[geo] requestGeolocation() invoked');

    if (!('geolocation' in navigator)) {
      console.warn('[geo] navigator.geolocation missing');
      setGeoStatus('unsupported');
      return;
    }

    // Pre-check via Permissions API — fast path for "already denied"
    // (avoids the 15s timeout) AND lets us surface a "blocked" message
    // distinct from the user actively tapping "Block" on the prompt.
    // Safari < 16 doesn't expose navigator.permissions for geolocation,
    // so we wrap in try/catch and fall through to getCurrentPosition.
    try {
      if (navigator.permissions && navigator.permissions.query) {
        const status = await navigator.permissions.query({ name: 'geolocation' });
        console.debug('[geo] Permissions API state =', status.state);
        if (status.state === 'denied') {
          // Browser remembers a previous deny — the prompt won't appear
          // again until the user manually re-enables it in site settings.
          setGeoStatus('denied');
          return;
        }
      }
    } catch (e) {
      console.debug('[geo] Permissions API unavailable:', e?.message || e);
    }

    // Watchdog: some Chrome/Edge/Firefox installs silently drop the
    // getCurrentPosition call (corporate firewalls, privacy extensions,
    // certain VPNs) without firing either callback. After 20s with no
    // response, mark the request as errored so the user isn't stuck on
    // "requesting…" forever. Cleared as soon as either callback fires.
    let settled = false;
    const watchdog = setTimeout(() => {
      if (settled) return;
      console.warn('[geo] watchdog fired — neither callback responded in 20s');
      settled = true;
      setGeoStatus('timeout');
    }, 20000);

    try {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          if (settled) return;
          settled = true;
          clearTimeout(watchdog);
          console.debug('[geo] got position', pos.coords);
          setGeoCoords({ latitude: pos.coords.latitude, longitude: pos.coords.longitude });
          setGeoStatus('granted');
        },
        (err) => {
          if (settled) return;
          settled = true;
          clearTimeout(watchdog);
          console.warn('[geo] error callback', err);
          // Map every error code to a visible state so the user always
          // gets feedback. Code 1 = user denied, 2 = position unavailable
          // (no GPS, Wi-Fi triangulation failed), 3 = timeout.
          if (!err) { setGeoStatus('error'); return; }
          switch (err.code) {
            case 1: setGeoStatus('denied'); break;
            case 2: setGeoStatus('unavailable'); break;
            case 3: setGeoStatus('timeout'); break;
            default: setGeoStatus('error');
          }
        },
        { enableHighAccuracy: false, timeout: 15000, maximumAge: 60000 }
      );
    } catch (e) {
      // Some browsers throw synchronously if the call is blocked entirely
      // by a Permissions-Policy header. Surface that instead of leaving
      // the UI stuck on "requesting".
      clearTimeout(watchdog);
      settled = true;
      console.error('[geo] getCurrentPosition threw synchronously:', e);
      setGeoStatus('error');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    // What the browser put in the field counts, not only what React saw: a
    // saved address picked from autofill could leave text there.
    const postal = String(postalRef.current?.value ?? formData.postal_code ?? '').trim();
    const errs = {};
    const phoneErr = phoneValueError(formData.phone);
    if (phoneErr) errs.phone = phoneErr;
    if (!/^\d{5}$/.test(postal)) errs.postal_code = 'Code postal : 5 chiffres, par exemple 37000.';
    setFieldErrors(errs);
    if (Object.keys(errs).length) return;
    try {
      const payload = { ...formData, postal_code: postal };
      if (geoCoords) {
        payload.latitude = geoCoords.latitude;
        payload.longitude = geoCoords.longitude;
      }
      // Attach the full touchpoint history. The first item is FIRST-touch
      // (e.g. Instagram) — preserved even when the customer signs up later
      // from a different source (e.g. in-store QR). The last item is
      // LAST-touch (the URL they actually submitted from).
      const chain = loadTouchpoints(slug);
      // Belt-and-braces: if the visitor's CURRENT URL has a ?src= we haven't
      // recorded yet (e.g. they never refreshed), inject it.
      if (lockedSource && (!chain.length || chain[chain.length - 1].source !== lockedSource)) {
        chain.push({ source: lockedSource, ts: new Date().toISOString() });
      }
      // And if they manually picked a source from the dropdown that disagrees
      // with what we tracked, record it too — multi-touch with both signals.
      if (formData.acquisition_source && (!chain.length || chain[chain.length - 1].source !== formData.acquisition_source)) {
        chain.push({ source: formData.acquisition_source, ts: new Date().toISOString() });
      }
      payload.touchpoints_history = chain;
      // RGPD consent proof — backend refuses new signups without it.
      payload.consent = consentChecked;
      payload.consent_policy_version = '2026-07-21';
      payload.is_student = isStudent;
      if (parrainBarcode) payload.parrain_barcode = parrainBarcode;
      setJoinError(null);
      const res = await publicAPI.joinProgram(slug, payload);
      clearTouchpoints(slug);  // chain has been persisted server-side, no need to keep it here
      // this phone now holds the card: a friend's QR scanned later opens it (lib/myCards)
      addMine(res.data?.barcode_id, res.data?.card_key);
      setSuccess(res.data);
    } catch (err) {
      // Plan-cap hit: the backend returns 403 with a structured detail.
      // Surface its `message` field directly so the visitor sees the
      // friendly French explanation instead of a raw "Error" alert.
      // lib/api turns an object detail into its sentence and keeps the object
      // as detail_raw — the code (already_member, plan_limit_reached…) is there
      const detail = err?.response?.data?.detail_raw ?? err?.response?.data?.detail;
      if (err?.response?.status === 409 && detail && typeof detail === 'object') {
        // Already a customer here, or an e-mail already used: said plainly —
        // the card itself is never handed over to whoever typed the number.
        setJoinError({ kind: detail.code || 'already_member', message: detail.message });
      } else if (err?.response?.status === 403 && detail && typeof detail === 'object' && detail.code === 'plan_limit_reached') {
        setJoinError({
          kind: 'plan_limit_reached',
          message: detail.message || 'Ce programme de fidélité est complet pour le moment.',
        });
      } else {
        const msg = (typeof detail === 'string' && detail)
          || (typeof detail === 'object' && detail?.message)
          || err?.message
          || "Une erreur est survenue, veuillez réessayer.";
        setJoinError({ kind: 'other', message: msg });
      }
    }
  };

  if (closed) return <div className="flex min-h-screen items-center justify-center p-8 text-center"><div className="max-w-md rounded-2xl border border-[#E9E5E0] bg-white p-8"><p className="mb-2 font-semibold text-[#171412]">Programme terminé</p><p className="text-sm text-[#57504A]">{closed}</p></div></div>;
  if (!tenant) return <div className="p-8 text-center">{t('common.loading')}</div>;

  return (
    <div className="min-h-screen bg-[#FDFBF7] font-['Inter'] flex flex-col items-center py-20 px-4">
      <div className="bg-white p-8 rounded-2xl shadow-sm w-full max-w-md border border-[#E7E5E4]">
        {page ? (
          // The shop's own words (Paramètres › Lien d'inscription › Personnaliser la page).
          <div className="mb-8 text-center">
            {page.logo_url && !logoBroken ? (
              <img src={page.logo_url} alt="" onError={() => setLogoBroken(true)}
                   className="mx-auto mb-3 h-16 w-16 rounded-full border border-[#E6EEFB] object-cover" />
            ) : (
              <span className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-full bg-[#0B1C3F] text-[22px] font-bold text-white">
                {(tenant.name || '?').slice(0, 1).toUpperCase()}
              </span>
            )}
            <p className="text-[14px] font-semibold text-[#0B1C3F]">{tenant.name}</p>
            <h1 className="mt-3 text-[24px] font-bold leading-tight text-[#0B1C3F]">{page.page.title}</h1>
            {page.page.subtitle && <p className="mt-2 text-[14px] leading-snug text-[#64748B]">{page.page.subtitle}</p>}
            {page.page.benefits?.length > 0 && (
              <ul className="mx-auto mt-4 inline-flex flex-col gap-1.5 text-left text-[13.5px] text-[#334155]">
                {page.page.benefits.map((b) => (
                  <li key={b} className="flex items-center gap-2">
                    <span className="flex h-4 w-4 items-center justify-center rounded-full bg-[#2F6BFF] text-[10px] text-white">✓</span>{b}
                  </li>
                ))}
              </ul>
            )}
            {!success && (
              <button type="button"
                onClick={() => document.getElementById('join-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                className="mt-5 w-full rounded-xl bg-[#2F6BFF] py-3 text-[15px] font-semibold text-white hover:bg-[#2559DB]">
                {page.page.button}
              </button>
            )}
          </div>
        ) : (
          <>
            <h1 className="font-['Cormorant_Garamond'] text-3xl font-bold text-center mb-2 ft-gradient-text-slow">{tenant.name}</h1>
            <p className="text-center text-[#57534E] mb-8">{t('join.title')}</p>
          </>
        )}

        {success ? (
          <div className="text-center space-y-6">
            <h2 className="text-2xl font-bold text-[#4A5D23]">{t('join.welcome')}</h2>
            <p className="text-[#57534E]">{t('join.card_ready')}</p>
            {/* QR only — the Code 128 1D barcode below was removed per
                owner spec. Modern POS phones/tablets scan QR reliably. */}
            <div className="p-4 bg-white rounded-xl border border-[#E7E5E4] flex justify-center">
              <QRCodeSVG value={`${window.location.origin}${ownerLink(success.barcode_id, success.card_key)}`} size={200} level="M" />
            </div>
            <p className="font-mono bg-gray-100 p-2 rounded">{success.barcode_id}</p>
            <div className="space-y-3">
              <Link
                to={ownerLink(success.barcode_id, success.card_key)}
                className="block text-center w-full bg-[#B85C38] text-white py-3 rounded-xl font-medium hover:bg-[#9C4E2F] transition-colors"
              >
                {t('join.open_card')} →
              </Link>
              <p className="text-xs text-center text-[#8B8680] pt-2">
                {t('join.open_card_hint')}
              </p>
            </div>
          </div>
        ) : (
          <form id="join-form" onSubmit={handleSubmit} className="space-y-4 scroll-mt-6">
            {inviter && (
              <div className="flex items-start gap-3 rounded-xl border border-[#E6EEFB] bg-[#F6F9FF] p-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#2F6BFF] text-[13px] font-bold text-white">
                  {(inviter.first_name || '?').slice(0, 1).toUpperCase()}
                </span>
                <p className="text-[13px] leading-snug text-[#0B1C3F]">
                  Vous êtes invité par <strong>{inviter.first_name || 'un client'}</strong>.
                  {inviter.referee_points > 0 && (
                    <> Créez votre carte et vous recevrez <strong>{inviter.referee_points} points</strong> à
                    votre {Number(inviter.minimum_visits || 1) <= 1 ? 'première' : `${inviter.minimum_visits}e`} visite
                    {inviter.reward_mode === 'every' ? ', puis à chaque visite' : ''} — {inviter.first_name || 'votre parrain'} aussi.</>
                  )}
                </p>
              </div>
            )}
            <div>
              <label className="block text-sm font-medium mb-1 text-[#57534E]">{t('join.full_name')}</label>
              <input required type="text" className="w-full border border-[#E7E5E4] rounded-lg p-3 focus:ring-[#B85C38]/20 focus:border-[#B85C38]" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1 text-[#57534E]">{t('join.email_optional')}</label>
              {/* Email is OPTIONAL. We keep type="email" so the browser
                  validates the format IF the customer fills it, but no
                  `required` so they can submit without one. Backend
                  dedup falls back to phone-only when email is blank. */}
              <input type="email" className="w-full border border-[#E7E5E4] rounded-lg p-3 focus:ring-[#B85C38]/20 focus:border-[#B85C38]" value={formData.email} onChange={e => setFormData({...formData, email: e.target.value})} />
            </div>
            <div>
              <label htmlFor="join-phone" className="block text-sm font-medium mb-1 text-[#57534E]">{t('auth.phone')}</label>
              {/* a country from the list, then digits only (user, 2026-10-09) */}
              <div className={`flex items-stretch rounded-lg border bg-white focus-within:border-[#B85C38] ${fieldErrors.phone ? 'border-[#DC2626]' : 'border-[#E7E5E4]'}`}>
                <PhoneField
                  id="join-phone"
                  required
                  value={formData.phone}
                  onChange={(v) => { setFormData((f) => ({ ...f, phone: v })); setFieldErrors((x) => ({ ...x, phone: undefined })); }}
                  aria-invalid={fieldErrors.phone ? 'true' : undefined}
                  aria-describedby={fieldErrors.phone ? 'join-phone-error' : undefined}
                  selectClassName="shrink-0 cursor-pointer rounded-l-lg border-r border-[#E7E5E4] bg-transparent pl-2 pr-1 text-sm text-[#1C1917] outline-none"
                  inputClassName="min-w-0 flex-1 rounded-r-lg bg-transparent p-3 outline-none"
                />
              </div>
              {fieldErrors.phone && <p id="join-phone-error" role="alert" className="mt-1 text-xs text-[#B91C1C]">{fieldErrors.phone}</p>}
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-[1fr_1.4fr]">
              <div>
                <label className="block text-sm font-medium mb-1 text-[#57534E]">{t('join.postal_code')}</label>
                {/* digits only — even when a saved address is picked from the
                    browser's autofill (user, 2026-10-09: text got in) */}
                <input ref={postalRef} required type="text" inputMode="numeric" autoComplete="postal-code" name="postal-code"
                       maxLength={5} pattern="[0-9]{5}" title="5 chiffres, par exemple 37000"
                       aria-invalid={fieldErrors.postal_code ? 'true' : undefined}
                       aria-describedby={fieldErrors.postal_code ? 'join-postal-error' : undefined}
                       className={`w-full border rounded-lg p-3 focus:ring-[#B85C38]/20 focus:border-[#B85C38] ${fieldErrors.postal_code ? 'border-[#DC2626]' : 'border-[#E7E5E4]'}`}
                       value={formData.postal_code}
                       onInput={e => { const d = postalDigits(e.currentTarget.value); if (e.currentTarget.value !== d) e.currentTarget.value = d; }}
                       onBlur={e => { const d = postalDigits(e.currentTarget.value); setFormData(f => ({ ...f, postal_code: d })); }}
                       onChange={e => { setFormData({...formData, postal_code: postalDigits(e.target.value)}); setFieldErrors(x => ({ ...x, postal_code: undefined })); }} />
                {fieldErrors.postal_code && <p id="join-postal-error" role="alert" className="mt-1 text-xs text-[#B91C1C]">{fieldErrors.postal_code}</p>}
              </div>
              <div>
                <label className="block text-sm font-medium mb-1 text-[#57534E]">{t('join.birthday')}</label>
                {/* day, then month — the French way, and never an impossible date (QA UX10) */}
                <div className="flex gap-2">
                  <select required aria-label="Jour de naissance" className="w-1/2 border border-[#E7E5E4] rounded-lg p-3 bg-white focus:ring-[#B85C38]/20 focus:border-[#B85C38]"
                          value={(formData.birthday.split('-')[1]) || ''}
                          onChange={e => { const m = formData.birthday.split('-')[0] || ''; setFormData({...formData, birthday: `${m}-${e.target.value}`}); }}>
                    <option value="">Jour</option>
                    {Array.from({ length: [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][(Number(formData.birthday.split('-')[0]) || 1) - 1] }, (_, i) => String(i + 1).padStart(2, '0'))
                      .map((d) => <option key={d} value={d}>{Number(d)}</option>)}
                  </select>
                  <select required aria-label="Mois de naissance" className="w-1/2 border border-[#E7E5E4] rounded-lg p-3 bg-white focus:ring-[#B85C38]/20 focus:border-[#B85C38]"
                          value={formData.birthday.split('-')[0] || ''}
                          onChange={e => { const dd = formData.birthday.split('-')[1] || ''; const max = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][Number(e.target.value) - 1] || 31; setFormData({...formData, birthday: `${e.target.value}-${dd && Number(dd) > max ? String(max).padStart(2, '0') : dd}`}); }}>
                    <option value="">Mois</option>
                    {['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
                      .map((m, i) => <option key={m} value={String(i + 1).padStart(2, '0')}>{m}</option>)}
                  </select>
                </div>
              </div>
            </div>
            {lockedSource || parrainBarcode ? (
              // The link says where they came from (or a friend's card: the
              // server files it as « Parrainage »): nothing to ask, nothing to
              // change — the attribution stays exact.
              <input type="hidden" value={formData.acquisition_source} readOnly />
            ) : (
              <div>
                <label className="block text-sm font-medium mb-1 text-[#57534E]">Comment nous avez-vous connu ? <span className="font-normal text-[#A8A29E]">(facultatif)</span></label>
                <select className="w-full border border-[#E7E5E4] rounded-lg p-3 focus:ring-[#B85C38]/20 focus:border-[#B85C38]" value={formData.acquisition_source} onChange={e => setFormData({...formData, acquisition_source: e.target.value})}>
                  <option value="">Choisir…</option>
                  {SIGNUP_SOURCES.map((k) => <option key={k} value={k}>{sourceLabel(k)}</option>)}
                </select>
              </div>
            )}
            <div className="p-3 rounded-lg border border-[#E7E5E4] bg-[#F3EFE7]">
              <p className="text-sm font-medium text-[#1C1917] mb-2">{t('join.geo_title')}</p>
              <p className="text-xs text-[#57534E] mb-3">
                {t('join.geo_subtitle')}
              </p>
              {geoStatus === 'idle' && (
                <button
                  type="button"
                  onClick={requestGeolocation}
                  className="text-sm px-3 py-1.5 bg-white border border-[#B85C38] text-[#B85C38] rounded-lg font-medium hover:bg-[#B85C38] hover:text-white transition-colors"
                >
                  {t('join.geo_share')}
                </button>
              )}
              {geoStatus === 'requesting' && <p className="text-xs text-[#57534E]">{t('join.geo_requesting')}</p>}
              {geoStatus === 'granted' && (
                <p className="text-xs text-[#065F46] font-medium">
                  {t('join.geo_granted')} ({geoCoords.latitude.toFixed(3)}°, {geoCoords.longitude.toFixed(3)}°)
                </p>
              )}
              {/* All three failure paths share the same "show a message +
                  let them try again" pattern. Distinct copy per code so
                  the user knows whether to re-enable in settings (denied)
                  or retry the request (unavailable / timeout). */}
              {/* "denied" is the one state where retrying is pointless: the
                  browser has remembered the refusal and will not prompt again
                  until the user resets the site permission themselves. Offering
                  "Réessayer" there just fails instantly and makes the product
                  look broken — so that state gets the instruction instead of
                  the button. The transient states keep the retry, because for
                  them a second attempt genuinely can succeed. */}
              {geoStatus === 'denied' && (
                <div className="text-xs text-[#92400E]">
                  <p>{t('join.geo_denied')}</p>
                  <p className="mt-1 text-[#78716C]">{t('join.geo_denied_howto')}</p>
                </div>
              )}
              {(geoStatus === 'unavailable' || geoStatus === 'timeout' || geoStatus === 'error') && (
                <div className="flex items-center gap-2 text-xs text-[#92400E]">
                  <span>
                    {geoStatus === 'unavailable' && t('join.geo_unavailable')}
                    {geoStatus === 'timeout'     && t('join.geo_timeout')}
                    {geoStatus === 'error'       && t('join.geo_error')}
                  </span>
                  <button
                    type="button"
                    onClick={requestGeolocation}
                    className="text-[#B85C38] underline"
                  >
                    {t('join.geo_retry')}
                  </button>
                </div>
              )}
              {geoStatus === 'unsupported' && <p className="text-xs text-[#92400E]">{t('join.geo_unsupported')}</p>}
            </div>

            {/* RGPD consent — required, unticked by default. The <label>
                wraps the checkbox so the whole text row is tappable (44px+
                hit area on mobile). `required` gives free browser-level
                blocking with a native message if left unticked. */}
            {/* Student status — asked plainly, ticked by the customer, never
                required. It drives the merchant's student offers and the
                parrainage breakdown. */}
            <label className="flex items-start gap-3 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isStudent}
                onChange={(e) => setIsStudent(e.target.checked)}
                className="mt-0.5 w-5 h-5 shrink-0 accent-[#B85C38] cursor-pointer"
              />
              <span className="text-xs text-[#57534E] leading-relaxed">
                Je suis <strong>étudiant·e</strong> — pour recevoir les offres
                réservées aux étudiants.
              </span>
            </label>

            <label className="flex items-start gap-3 p-3 rounded-lg border border-[#E7E5E4] bg-white cursor-pointer select-none">
              <input
                type="checkbox"
                required
                checked={consentChecked}
                onChange={(e) => setConsentChecked(e.target.checked)}
                className="mt-0.5 w-5 h-5 shrink-0 accent-[#B85C38] cursor-pointer"
              />
              <span className="text-xs text-[#57534E] leading-relaxed">
                {/* The shop's own sentence (Paramètres › Données &
                    confidentialité), or the standard one. */}
                {tenant.privacy_public?.consent_text || (
                  <>J'accepte que <strong>{tenant.name}</strong> utilise mes données
                  (nom, contact, visites) pour gérer ma carte de fidélité et
                  m'envoyer des offres. Je peux à tout moment télécharger ou
                  supprimer mes données depuis ma carte, conformément au RGPD.</>
                )}
                {tenant.privacy_public?.policy_url && (
                  <> <a href={tenant.privacy_public.policy_url} target="_blank" rel="noopener noreferrer"
                        className="underline text-[#B85C38]" onClick={(e) => e.stopPropagation()}>Politique de confidentialité</a></>
                )}
                <span className="text-[#B85C38]"> *</span>
              </span>
            </label>

            {tenant.privacy_public?.cookie_notice && (
              <p className="text-[11px] leading-snug text-[#78716C]">
                Cette page n'utilise que le stockage nécessaire à votre carte (aucun cookie publicitaire ni de mesure d'audience).
              </p>
            )}

            {joinError && (
              <div
                role="alert"
                className={`p-3 rounded-lg border text-sm ${
                  ['plan_limit_reached', 'already_member', 'email_taken'].includes(joinError.kind)
                    ? 'bg-[#FFF7ED] border-[#FCD9B6] text-[#92400E]'
                    : 'bg-[#FEE2E2] border-[#FCA5A5] text-[#7A2E20]'
                }`}
              >
                <p className="font-medium mb-0.5">
                  {joinError.kind === 'plan_limit_reached'
                    ? t('join.plan_full_title')
                    : joinError.kind === 'already_member'
                      ? 'Vous avez déjà une carte'
                      : joinError.kind === 'email_taken'
                        ? 'E-mail déjà utilisé'
                        : t('join.join_error_title')}
                </p>
                <p className="text-xs leading-relaxed">{joinError.message}</p>
              </div>
            )}

            <button type="submit" className="w-full bg-[#B85C38] text-white py-3 rounded-full font-medium hover:bg-[#9C4E2F] transition-colors mt-6">
              {t('join.join_button')}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};

export default JoinPage;
