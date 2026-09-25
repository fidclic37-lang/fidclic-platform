import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import { publicAPI } from '../lib/api';
import { QRCodeSVG } from 'qrcode.react';
import Code128Barcode from '../components/Code128Barcode';

const ALLOWED_SOURCES = ['qr_store', 'instagram', 'facebook', 'tiktok'];

// Accept common synonyms so a marketer can write `?src=ig` or `?utm_source=fb` etc.
const SOURCE_ALIASES = {
  qr: 'qr_store', qr_store: 'qr_store', store: 'qr_store', instore: 'qr_store', in_store: 'qr_store',
  ig: 'instagram', insta: 'instagram', instagram: 'instagram',
  fb: 'facebook', facebook: 'facebook', meta: 'facebook',
  tt: 'tiktok', tik: 'tiktok', tiktok: 'tiktok',
};

function resolveSourceFromUrl(searchParams) {
  // Accept ?src=, ?source=, ?utm_source= — first one wins
  const raw = (
    searchParams.get('src') ||
    searchParams.get('source') ||
    searchParams.get('utm_source') ||
    ''
  ).trim().toLowerCase().replace(/[^a-z_]/g, '');
  if (!raw) return null;
  const resolved = SOURCE_ALIASES[raw] || raw;
  return ALLOWED_SOURCES.includes(resolved) ? resolved : null;
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
  const { slug } = useParams();
  const [searchParams] = useSearchParams();
  const lockedSource = useMemo(() => resolveSourceFromUrl(searchParams), [searchParams]);
  const [tenant, setTenant] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    phone: '',
    postal_code: '',
    birthday: '',
    acquisition_source: lockedSource || 'qr_store',
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

  useEffect(() => {
    publicAPI.getJoinInfo(slug).then(res => setTenant(res.data)).catch(console.error);
  }, [slug]);

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
    try {
      const payload = { ...formData };
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
      setJoinError(null);
      const res = await publicAPI.joinProgram(slug, payload);
      clearTouchpoints(slug);  // chain has been persisted server-side, no need to keep it here
      setSuccess(res.data);
    } catch (err) {
      // Plan-cap hit: the backend returns 403 with a structured detail.
      // Surface its `message` field directly so the visitor sees the
      // friendly French explanation instead of a raw "Error" alert.
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 403 && detail && typeof detail === 'object' && detail.code === 'plan_limit_reached') {
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

  if (!tenant) return <div className="p-8 text-center">{t('common.loading')}</div>;

  return (
    <div className="min-h-screen bg-[#FDFBF7] font-['Manrope'] flex flex-col items-center py-20 px-4">
      <div className="bg-white p-8 rounded-2xl shadow-sm w-full max-w-md border border-[#E7E5E4]">
        <h1 className="font-['Cormorant_Garamond'] text-3xl font-bold text-center mb-2 ft-gradient-text-slow">{tenant.name}</h1>
        <p className="text-center text-[#57534E] mb-8">{t('join.title')}</p>

        {success ? (
          <div className="text-center space-y-6">
            <h2 className="text-2xl font-bold text-[#4A5D23]">{t('join.welcome')}</h2>
            <p className="text-[#57534E]">{t('join.card_ready')}</p>
            {/* QR only — the Code 128 1D barcode below was removed per
                owner spec. Modern POS phones/tablets scan QR reliably. */}
            <div className="p-4 bg-white rounded-xl border border-[#E7E5E4] flex justify-center">
              <QRCodeSVG value={success.barcode_id} size={200} level="M" />
            </div>
            <p className="font-mono bg-gray-100 p-2 rounded">{success.barcode_id}</p>
            <div className="space-y-3">
              <Link
                to={`/card/${success.barcode_id}`}
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
          <form onSubmit={handleSubmit} className="space-y-4">
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
              <label className="block text-sm font-medium mb-1 text-[#57534E]">{t('auth.phone')}</label>
              <input required type="tel" className="w-full border border-[#E7E5E4] rounded-lg p-3 focus:ring-[#B85C38]/20 focus:border-[#B85C38]" value={formData.phone} onChange={e => setFormData({...formData, phone: e.target.value})} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-1 text-[#57534E]">{t('join.postal_code')}</label>
                <input required type="text" inputMode="numeric" maxLength={5} className="w-full border border-[#E7E5E4] rounded-lg p-3 focus:ring-[#B85C38]/20 focus:border-[#B85C38]" value={formData.postal_code} onChange={e => setFormData({...formData, postal_code: e.target.value})} />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1 text-[#57534E]">{t('join.birthday')}</label>
                <input required type="text" placeholder="MM-DD" className="w-full border border-[#E7E5E4] rounded-lg p-3 focus:ring-[#B85C38]/20 focus:border-[#B85C38]" value={formData.birthday} onChange={e => setFormData({...formData, birthday: e.target.value})} />
              </div>
            </div>
            {lockedSource ? (
              // Source was deterministically tagged by the landing URL
              // (e.g. /join/<slug>?src=instagram). We hide the picker
              // entirely so it can't be changed — attribution stays clean.
              <input type="hidden" value={formData.acquisition_source} readOnly />
            ) : (
              <div>
                <label className="block text-sm font-medium mb-1 text-[#57534E]">{t('join.how_heard')}</label>
                <select className="w-full border border-[#E7E5E4] rounded-lg p-3 focus:ring-[#B85C38]/20 focus:border-[#B85C38]" value={formData.acquisition_source} onChange={e => setFormData({...formData, acquisition_source: e.target.value})}>
                  <option value="qr_store">📱 QR code in the store</option>
                  <option value="instagram">📸 Instagram</option>
                  <option value="facebook">👥 Facebook</option>
                  <option value="tiktok">🎵 TikTok</option>
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
                J'accepte que <strong>{tenant.name}</strong> utilise mes données
                (nom, contact, visites) pour gérer ma carte de fidélité et
                m'envoyer des offres. Je peux à tout moment télécharger ou
                supprimer mes données depuis ma carte, conformément au RGPD.
                <span className="text-[#B85C38]"> *</span>
              </span>
            </label>

            {joinError && (
              <div
                role="alert"
                className={`p-3 rounded-lg border text-sm ${
                  joinError.kind === 'plan_limit_reached'
                    ? 'bg-[#FFF7ED] border-[#FCD9B6] text-[#92400E]'
                    : 'bg-[#FEE2E2] border-[#FCA5A5] text-[#7A2E20]'
                }`}
              >
                <p className="font-medium mb-0.5">
                  {joinError.kind === 'plan_limit_reached'
                    ? t('join.plan_full_title')
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
