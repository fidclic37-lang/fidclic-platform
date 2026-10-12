import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, Link, useSearchParams, useNavigate, useLocation } from 'react-router-dom';
import { User, Mail, Phone, CalendarDays, ArrowRight, Check, Share2, Smartphone, Printer, Store } from 'lucide-react';
import api, { publicAPI } from '../lib/api';
import { SIGNUP_SOURCES, normalizeSource } from '../lib/sources';
import { addMine, ownerLink } from '../lib/myCards';
import PhoneField, { phoneValueError } from '../components/PhoneField';
import WalletButtons from '../components/WalletButtons';
import WalletPassPreview from '../components/WalletPassPreview';
import PremiumLoyaltyCard from '../components/PremiumLoyaltyCard';
import Fireworks from '../components/Fireworks';

/* /join/:slug — the customer's signup (redesigned 2026-10-09 to the user's
   mockup; the previous page is JoinPageLegacy.jsx, unrouted).
     • the shop's logo and words, « by FidClic »;
     • name, e-mail (optional), phone (a country, then digits), postal code,
       the full date of birth (the age shows in Clients);
     • no « how did you hear of us »: the link says it (lib/sources); no
       « étudiant » (decided with the user);
     • the position, asked when the form is sent — optional, the consent says so;
     • consent naming the shop and FidClic (decided with the user).
   Then « Félicitations ! » with the shop's own card, the Wallet buttons,
   share / home screen / print. */

const postalDigits = (raw) => {
  const s = String(raw ?? '');
  const five = s.match(/(?:^|\D)(\d{5})(?:\D|$)/);
  return five ? five[1] : s.replace(/\D/g, '').slice(0, 5);
};

// « 25121990 » → « 25/12/1990 » as it is typed: the « / » appears as soon
// as the day (and then the month) is complete; erasing never puts it back.
export const maskDate = (raw, prev = '') => {
  const d = String(raw ?? '').replace(/\D/g, '').slice(0, 8);
  const out = [d.slice(0, 2), d.slice(2, 4), d.slice(4, 8)].filter(Boolean).join('/');
  const erasing = String(raw ?? '').length < String(prev ?? '').length;
  return !erasing && (d.length === 2 || d.length === 4) ? `${out}/` : out;
};

export function birthError(value) {
  const m = String(value || '').match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!m) return 'Date de naissance : JJ/MM/AAAA, par exemple 25/12/1990.';
  const [d, mo, y] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const dt = new Date(Date.UTC(y, mo - 1, d));
  if (mo < 1 || mo > 12 || dt.getUTCDate() !== d || dt.getUTCMonth() !== mo - 1) return 'Date de naissance invalide : ce jour n’existe pas.';
  const now = new Date();
  if (y < 1900 || dt > now) return 'Date de naissance invalide : vérifiez l’année.';
  return null;
}

function resolveSourceFromUrl(searchParams, channel) {
  const raw = channel || searchParams.get('src') || searchParams.get('source') || searchParams.get('utm_source') || '';
  const key = normalizeSource(raw);
  return key && SIGNUP_SOURCES.includes(key) ? key : null;
}

// Multi-touch attribution: every ?src= this browser landed with, sent with the form.
const TOUCHPOINTS_KEY = (slug) => `ft_touchpoints_${slug}`;
const loadTouchpoints = (slug) => {
  try { const a = JSON.parse(localStorage.getItem(TOUCHPOINTS_KEY(slug)) || '[]'); return Array.isArray(a) ? a : []; } catch (_e) { return []; }
};
const recordTouchpoint = (slug, source) => {
  if (!source) return;
  try {
    const list = loadTouchpoints(slug);
    if (list[list.length - 1]?.source === source) return;
    list.push({ source, ts: new Date().toISOString() });
    while (list.length > 10) list.shift();
    localStorage.setItem(TOUCHPOINTS_KEY(slug), JSON.stringify(list));
  } catch (_e) { /* private mode */ }
};
const clearTouchpoints = (slug) => { try { localStorage.removeItem(TOUCHPOINTS_KEY(slug)); } catch (_e) { /* ignore */ } };

// The position, asked once the form is sent (user, 2026-10-09: « position lo,
// it is important for géolocalisation »). Never blocks the signup: no answer
// within a few seconds, or a refusal, and the card is made without it.
const askPosition = () => new Promise((resolve) => {
  if (!('geolocation' in navigator)) { resolve(null); return; }
  let done = false;
  const finish = (v) => { if (!done) { done = true; resolve(v); } };
  setTimeout(() => finish(null), 8000);
  try {
    navigator.geolocation.getCurrentPosition(
      (p) => finish({ latitude: p.coords.latitude, longitude: p.coords.longitude }),
      () => finish(null),
      { enableHighAccuracy: false, timeout: 7000, maximumAge: 60000 },
    );
  } catch (_e) { finish(null); }
});

const box = (err) => `flex min-h-[60px] min-w-0 items-center gap-3 overflow-hidden rounded-2xl border bg-white px-4 transition focus-within:border-[#2F6BFF] focus-within:ring-4 focus-within:ring-[#2F6BFF]/10 ${err ? 'border-[#DC2626]' : 'border-[#E2E8F0]'}`;
// the box draws the border: the app's global input styling is switched off inside it
// 16px: iPhone Safari zooms the whole page into any smaller field
const inputCls = 'min-w-0 flex-1 !border-0 !rounded-none bg-transparent !px-0 py-4 !text-[16px] text-[#0B1C3F] !shadow-none !outline-none !ring-0 placeholder:text-[#64748B]';
const Star = () => <span className="text-[#DC2626]" aria-hidden="true">*</span>;
const FieldError = ({ id, children }) => (children ? <p id={id} role="alert" className="mt-1.5 px-1 text-[12px] text-[#B91C1C]">{children}</p> : null);

function Brand() {
  return (
    <p className="mt-3 text-[15px] text-[#64748B]">
      by <span className="font-bold"><span className="text-[#2F6BFF]">Fid</span><span className="text-[#F59E0B]">Clic</span></span>
    </p>
  );
}

function Success({ result, tenant }) {
  const bc = result.barcode_id;
  const [data, setData] = useState(null);
  const [toast, setToast] = useState('');
  useEffect(() => {
    api.get(`/card/${bc}`).then(({ data: d }) => setData(d)).catch(() => setData(null));
  }, [bc]);
  const say = (m) => { setToast(m); setTimeout(() => setToast(''), 3500); };
  // the card's public address — what the card's QR holds: a friend who opens
  // it gets the signup, with parrainage; the owner key never travels
  const shareUrl = `${window.location.origin}/card/${bc}`;
  const share = async () => {
    try {
      if (navigator.share) await navigator.share({ title: `${tenant.name} — ma carte de fidélité`, url: shareUrl });
      else { await navigator.clipboard.writeText(shareUrl); say('Lien copié.'); }
    } catch (_e) { /* cancelled */ }
  };
  const home = () => say(/iPad|iPhone|iPod/.test(navigator.userAgent)
    ? 'Dans Safari, touchez Partager puis « Sur l’écran d’accueil ».'
    : 'Dans le menu du navigateur, choisissez « Ajouter à l’écran d’accueil ».');

  return (
    <div className="text-center">
      <Fireworks />
      <div className="relative mx-auto mb-4 h-16 w-16">
        {['-left-10 top-1 rotate-[35deg] bg-[#C2410C]', '-left-14 top-8 rotate-[60deg] bg-[#F59E0B]',
          '-right-10 top-1 -rotate-[35deg] bg-[#F59E0B]', '-right-14 top-8 -rotate-[60deg] bg-[#C2410C]'].map((c) => (
            <span key={c} aria-hidden="true" className={`absolute h-1.5 w-5 rounded-full ${c}`} />
        ))}
        <span className="flex h-16 w-16 items-center justify-center rounded-full bg-[#E7F6EC] text-[#15803D]"><Check size={30} strokeWidth={3} /></span>
      </div>
      <h2 className="text-[28px] font-extrabold text-[#0B1C3F]">Félicitations !</h2>
      {tenant?.name && <p className="mt-1 text-[18px] font-semibold text-[#0B1C3F]">Bienvenue chez {tenant.name} !</p>}
      <p className="mt-1 text-[16px] text-[#64748B]">Votre carte de fidélité est prête.</p>

      <div className="mt-6 flex justify-center">
        {data?.card ? (
          data.card.layout_style === 'wallet' ? (
            <div style={{ maxWidth: 360, width: '100%' }}>
              <WalletPassPreview customer={data.customer} tenant={data.tenant} card={data.card} width={360} />
            </div>
          ) : (
            <div className="w-full max-w-[360px]"><PremiumLoyaltyCard customer={data.customer} tenant={data.tenant} card={data.card} /></div>
          )
        ) : (
          <div className="h-56 w-full max-w-[360px] animate-pulse rounded-2xl bg-[#E2E8F0]" />
        )}
      </div>

      <div className="mx-auto mt-5 max-w-[360px] space-y-3 text-left">
        <WalletButtons barcodeId={bc} onError={say} />
        <div className="grid grid-cols-3 gap-2">
          {[[Share2, 'Partager / copier', share], [Smartphone, 'Sur l’écran d’accueil', home], [Printer, 'Imprimer', () => window.print()]].map(([Icon, label, fn]) => (
            <button key={label} type="button" onClick={fn}
                    className="flex flex-col items-center gap-1.5 rounded-2xl bg-[#F1F5F9] px-2 py-3 text-[12.5px] font-medium text-[#0B1C3F] hover:bg-[#E2E8F0]">
              <Icon size={18} aria-hidden="true" /> {label}
            </button>
          ))}
        </div>
        <Link to={ownerLink(bc, result.card_key)}
              className="flex h-14 items-center justify-center gap-2 rounded-2xl bg-[#1463FF] text-[17px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)] hover:bg-[#0F54E0]">
          Voir ma carte <ArrowRight size={18} />
        </Link>
      </div>
      {toast && <p role="status" className="mx-auto mt-4 max-w-[360px] rounded-xl bg-[#0B1C3F] px-4 py-2.5 text-[13px] text-white">{toast}</p>}
    </div>
  );
}

const JoinPage = () => {
  // /join/<compte>/<établissement>[/<canal>] or /join/<compte>/<canal> (multi-store, 2026-10-12)
  const { slug, channel: seg, channel2 } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [page, setPage] = useState(null);
  const stores = page?.stores || [];                    // only when the account has several
  const urlStore = stores.find((x) => x.slug === String(seg || '').toLowerCase()) || null;
  const channel = urlStore ? channel2 : seg;
  const [chosenStore, setChosenStore] = useState('');
  const askStore = stores.length > 1 && !urlStore && !searchParams.get('p');
  const lockedSource = useMemo(() => resolveSourceFromUrl(searchParams, channel), [searchParams, channel]);
  // ?p=FT-… — a friend's card brought them: parrainage
  const parrainBarcode = (searchParams.get('p') || '').trim().toUpperCase();
  const [inviter, setInviter] = useState(null);
  const [tenant, setTenant] = useState(null);
  const [closed, setClosed] = useState(null);
  const [logoBroken, setLogoBroken] = useState(false);
  const [form, setForm] = useState({ name: '', email: '', phone: '', postal_code: '', birth: '' });
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState({});
  const [joinError, setJoinError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(null);
  const postalRef = useRef(null);
  const set = (k, v) => { setForm((f) => ({ ...f, [k]: v })); setErrors((e) => ({ ...e, [k]: undefined })); };

  useEffect(() => {
    if (!parrainBarcode) return undefined;
    let alive = true;
    api.get(`/card/${parrainBarcode}/inviter`).then(({ data }) => { if (alive && data?.enabled) setInviter(data); }).catch(() => {});
    return () => { alive = false; };
  }, [parrainBarcode]);

  useEffect(() => {
    publicAPI.getJoinInfo(slug).then((res) => {
      const live = res.data?.slug;                 // a name from before a rename
      if (live && live !== slug) {
        const base = location.pathname.startsWith('/inscription/') ? '/inscription/' : '/join/';
        const rest = location.pathname.split('/').slice(3).filter(Boolean).join('/');   // the store / channel stay
        navigate(`${base}${live}${rest ? `/${rest}` : ''}${location.search}`, { replace: true });
        return;
      }
      setTenant(res.data);
    }).catch((e) => {
      if (e?.response?.status === 410) setClosed(e.response.data?.detail || "Ce programme de fidélité n'est plus disponible.");
    });
    publicAPI.joinPage(slug).then(({ data }) => setPage(data)).catch(() => {});
  }, [slug]); // eslint-disable-line react-hooks/exhaustive-deps

  // one visit per browser per day for Paramètres › Lien d'inscription (not the owner's preview)
  useEffect(() => {
    if (searchParams.get('preview')) return;
    let visitor = '';
    try {
      visitor = localStorage.getItem('fidclic:visitor') || '';
      if (!visitor) {
        visitor = Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, '0')).join('');
        localStorage.setItem('fidclic:visitor', visitor);
      }
    } catch (_e) { /* private mode */ }
    // the 2nd part of the address may be the establishment (the server checks it)
    if (visitor) publicAPI.joinView(slug, { visitor, src: lockedSource || resolveSourceFromUrl(searchParams, channel2), store: seg || undefined }).catch(() => {});
  }, [slug]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (lockedSource) recordTouchpoint(slug, lockedSource); }, [slug, lockedSource]);

  const submit = async (e) => {
    e.preventDefault();
    const postal = postalDigits(postalRef.current?.value ?? form.postal_code);
    const errs = {};
    if (!form.name.trim()) errs.name = 'Indiquez votre nom.';
    const pe = phoneValueError(form.phone);
    if (pe) errs.phone = pe;
    if (!/^\d{5}$/.test(postal)) errs.postal_code = 'Code postal : 5 chiffres, par exemple 37000.';
    const be = birthError(form.birth);
    if (be) errs.birth = be;
    if (!consent) errs.consent = 'Cochez la case pour créer votre carte.';
    if (askStore && !chosenStore) errs.store = 'Choisissez votre établissement.';
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true); setJoinError(null);
    const position = await askPosition();          // asked now, never required
    try {
      const chain = loadTouchpoints(slug);
      if (lockedSource && chain[chain.length - 1]?.source !== lockedSource) chain.push({ source: lockedSource, ts: new Date().toISOString() });
      const payload = {
        name: form.name.trim(), email: form.email.trim(), phone: form.phone, postal_code: postal,
        birthday: form.birth,                        // JJ/MM/AAAA — the server keeps the day and the age
        acquisition_source: lockedSource || '', touchpoints_history: chain,
        consent: true, consent_policy_version: '2026-10-09',
        ...(position || {}),
        ...(parrainBarcode ? { parrain_barcode: parrainBarcode } : {}),
        ...(urlStore ? { store: urlStore.slug } : chosenStore ? { store: chosenStore } : {}),
      };
      const res = await publicAPI.joinProgram(slug, payload);
      clearTouchpoints(slug);
      addMine(res.data?.barcode_id, res.data?.card_key);   // this phone now holds the card
      setSuccess(res.data);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      const detail = err?.response?.data?.detail_raw ?? err?.response?.data?.detail;
      if (detail && typeof detail === 'object' && detail.code === 'store_required') {
        setErrors((x) => ({ ...x, store: detail.message }));
        setJoinError(null);
      } else if (err?.response?.status === 409 && detail && typeof detail === 'object') {
        setJoinError({ tone: 'amber', title: detail.code === 'email_taken' ? 'E-mail déjà utilisé' : 'Vous avez déjà une carte', message: detail.message });
      } else if (err?.response?.status === 403 && detail && typeof detail === 'object' && detail.code === 'plan_limit_reached') {
        setJoinError({ tone: 'amber', title: 'Programme complet', message: detail.message || 'Ce programme de fidélité est complet pour le moment.' });
      } else {
        setJoinError({ tone: 'red', title: 'Inscription impossible',
          message: (typeof detail === 'string' && detail) || detail?.message || 'Une erreur est survenue, veuillez réessayer.' });
      }
    } finally { setBusy(false); }
  };

  if (closed) return <div className="flex min-h-screen items-center justify-center p-8 text-center"><div className="max-w-md rounded-2xl border border-[#E2E8F0] bg-white p-8"><p className="mb-2 font-semibold text-[#0B1C3F]">Programme terminé</p><p className="text-sm text-[#64748B]">{closed}</p></div></div>;
  if (!tenant) return <div className="p-8 text-center text-[#64748B]">Chargement…</div>;

  const logo = page?.logo_url;
  const title = page?.page?.title || 'Rejoignez notre programme de fidélité !';
  const subtitle = page?.page?.subtitle || 'Cumulez des points et profitez d’offres exclusives toute l’année.';

  return (
    <div className="min-h-screen bg-[#F8FAFC] px-4 py-10 font-['Inter']">
      <div className="mx-auto w-full max-w-md">
        {success ? <Success result={success} tenant={tenant} /> : (
          <>
            <header className="text-center">
              {logo && !logoBroken ? (
                <img src={logo} alt={tenant.name} onError={() => setLogoBroken(true)}
                     className="mx-auto h-28 w-28 rounded-full object-cover shadow-[0_12px_30px_-12px_rgba(11,28,63,.45)]" />
              ) : (
                <span translate="no" className="notranslate mx-auto flex h-28 w-28 items-center justify-center rounded-full bg-[#0B1C3F] text-[40px] font-bold text-white">
                  {(tenant.name || '?').slice(0, 1).toUpperCase()}
                </span>
              )}
              <h1 className="mt-6 text-[30px] font-extrabold leading-[1.12] text-[#0B1C3F]">{title}</h1>
              <p className="mt-3 text-[16px] leading-snug text-[#64748B]">{subtitle}</p>
              <Brand />
            </header>

            {inviter && (
              <div className="mt-6 flex items-start gap-3 rounded-2xl border border-[#DCE7FF] bg-[#F3F7FF] p-3.5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#2F6BFF] text-[13px] font-bold text-white">
                  {(inviter.first_name || '?').slice(0, 1).toUpperCase()}
                </span>
                <p className="text-[13px] leading-snug text-[#0B1C3F]">
                  Vous êtes invité par <strong translate="no" className="notranslate">{inviter.first_name || 'un client'}</strong>.
                  {inviter.referee_points > 0 && (
                    <> Créez votre carte et vous recevrez <strong>{inviter.referee_points} points</strong> à votre
                      {Number(inviter.minimum_visits || 1) <= 1 ? ' première' : ` ${inviter.minimum_visits}e`} visite
                      {inviter.reward_mode === 'every' ? ', puis à chaque visite' : ''}.</>
                  )}
                </p>
              </div>
            )}

            <form id="join-form" onSubmit={submit} noValidate className="mt-7 space-y-3.5">
              {urlStore && (
                <p className="flex items-center justify-center gap-2 rounded-2xl bg-[#F3F7FF] px-4 py-2.5 text-[13.5px] text-[#0B1C3F]">
                  <Store size={17} className="text-[#2F6BFF]" aria-hidden="true" />
                  Établissement : <strong translate="no" className="notranslate">{urlStore.name}</strong>
                </p>
              )}
              {askStore && (
                <div>
                  <label className={box(errors.store)}>
                    <Store size={22} className="shrink-0 text-[#64748B]" aria-hidden="true" />
                    <select aria-label="Votre établissement" required className={`${inputCls} bg-transparent`} value={chosenStore}
                            onChange={(e) => { setChosenStore(e.target.value); setErrors((x) => ({ ...x, store: undefined })); }}>
                      <option value="">Votre établissement</option>
                      {stores.map((x) => <option key={x.id} value={x.slug}>{x.name}{x.city ? ` — ${x.city}` : ''}</option>)}
                    </select>
                    <Star />
                  </label>
                  <FieldError id="join-store-error">{errors.store}</FieldError>
                </div>
              )}
              <div>
                <label className={box(errors.name)}>
                  <User size={22} className="shrink-0 text-[#64748B]" aria-hidden="true" />
                  <input type="text" autoComplete="name" placeholder="Nom complet" aria-label="Nom complet" required
                         aria-invalid={errors.name ? 'true' : undefined} className={inputCls}
                         value={form.name} onChange={(e) => set('name', e.target.value)} />
                  <Star />
                </label>
                <FieldError id="join-name-error">{errors.name}</FieldError>
              </div>
              <label className={box(false)}>
                <Mail size={22} className="shrink-0 text-[#64748B]" aria-hidden="true" />
                <input type="email" autoComplete="email" placeholder="Email (optionnel)" aria-label="Email (optionnel)"
                       className={inputCls} value={form.email} onChange={(e) => set('email', e.target.value)} />
              </label>
              <div>
                <div className={box(errors.phone)}>
                  <Phone size={22} className="shrink-0 text-[#64748B]" aria-hidden="true" />
                  <PhoneField id="join-phone" required value={form.phone} onChange={(v) => set('phone', v)}
                              placeholder="Téléphone" aria-label="Téléphone"
                              aria-invalid={errors.phone ? 'true' : undefined}
                              selectClassName="shrink-0 cursor-pointer pr-2 text-[13px] text-[#334155]"
                              inputClassName={inputCls} />
                  <Star />
                </div>
                <FieldError id="join-phone-error">{errors.phone}</FieldError>
              </div>
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] gap-3">
                <div className="min-w-0">
                  <label className={box(errors.postal_code)}>
                    <input ref={postalRef} type="text" inputMode="numeric" autoComplete="postal-code" name="postal-code"
                           maxLength={5} placeholder="Code postal" aria-label="Code postal"
                           aria-invalid={errors.postal_code ? 'true' : undefined} className={inputCls}
                           value={form.postal_code}
                           onInput={(e) => { const d = postalDigits(e.currentTarget.value); if (e.currentTarget.value !== d) e.currentTarget.value = d; }}
                           onChange={(e) => set('postal_code', postalDigits(e.target.value))} />
                  </label>
                  <FieldError id="join-postal-error">{errors.postal_code}</FieldError>
                </div>
                <div className="min-w-0">
                  <label className={`${box(errors.birth)} gap-2.5 px-3`}>
                    <CalendarDays size={20} className="shrink-0 text-[#64748B]" aria-hidden="true" />
                    <span className="flex min-w-0 flex-1 flex-col py-2">
                      <span className="truncate text-[12.5px] leading-tight text-[#64748B]">Date de naissance</span>
                      <input type="text" inputMode="numeric" autoComplete="bday" name="bday" maxLength={10}
                             placeholder="JJ/MM/AAAA" aria-label="Date de naissance (JJ/MM/AAAA)" data-keep-zeros=""
                             aria-invalid={errors.birth ? 'true' : undefined}
                             className="w-full min-w-0 !border-0 !rounded-none bg-transparent !p-0 !text-[16px] text-[#0B1C3F] !shadow-none !outline-none !ring-0 placeholder:text-[#94A3B8]"
                             value={form.birth} onChange={(e) => set('birth', maskDate(e.target.value, form.birth))} />
                    </span>
                  </label>
                  <FieldError id="join-birth-error">{errors.birth}</FieldError>
                </div>
              </div>

              <label className="flex cursor-pointer items-start gap-3 pt-3">
                <input type="checkbox" required checked={consent}
                       onChange={(e) => { setConsent(e.target.checked); setErrors((x) => ({ ...x, consent: undefined })); }}
                       className="mt-0.5 h-6 w-6 shrink-0 cursor-pointer rounded-md accent-[#2F6BFF]" />
                <span className="text-[14px] leading-relaxed text-[#1E293B]">
                  {tenant.privacy_public?.consent_text || (
                    <>J’accepte que <strong translate="no" className="notranslate">{tenant.name}</strong> et FidClic utilisent mes
                      données personnelles pour gérer ma carte de fidélité, mon compte et m’envoyer des offres personnalisées,
                      y compris des offres pertinentes à proximité si j’autorise ma position.</>
                  )}
                  <span className="mt-1 block text-[12.5px] text-[#64748B]">
                    Je peux retirer mon consentement à tout moment.
                    {tenant.privacy_public?.policy_url && (
                      <> <a href={tenant.privacy_public.policy_url} target="_blank" rel="noopener noreferrer"
                            className="underline" onClick={(e) => e.stopPropagation()}>Politique de confidentialité</a></>
                    )} <Star />
                  </span>
                </span>
              </label>
              <FieldError id="join-consent-error">{errors.consent}</FieldError>

              {joinError && (
                <div role="alert" className={`rounded-2xl border p-3.5 text-[13.5px] ${joinError.tone === 'amber'
                  ? 'border-[#FCD9B6] bg-[#FFF7ED] text-[#92400E]' : 'border-[#FCA5A5] bg-[#FEF2F2] text-[#7F1D1D]'}`}>
                  <p className="font-semibold">{joinError.title}</p>
                  <p className="mt-0.5 leading-relaxed">{joinError.message}</p>
                </div>
              )}

              <button type="submit" disabled={busy}
                      className="mt-3 flex h-14 w-full items-center justify-center gap-3 rounded-2xl bg-[#1463FF] text-[17px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)] transition hover:bg-[#0F54E0] disabled:opacity-70">
                {busy ? 'Création de votre carte…' : <>Rejoindre le programme <ArrowRight size={20} /></>}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
};

export default JoinPage;
