import { vh } from '../lib/fit';
import React, { useEffect, useRef, useState } from 'react';
import { useParams, Link, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { readMine, addMine, forgetMine, keyOf } from '../lib/myCards';
import { Bell, RefreshCw, Trash2, CheckCircle2, XCircle, Clock, X, Download, ShieldCheck, Star, Settings, MapPin, Phone, Globe, Store, ChevronLeft, Flame, Gift } from 'lucide-react';
import api, { publicAPI } from '../lib/api';
import { ensureSubscribed, unsubscribe as unsubscribePush, isSupported as isPushSupported } from '../lib/webpush';
import { programmeOf, earningRule, balanceText } from '../lib/programme';
import { here as walletPlace } from '../lib/iosSafari';
import { waitForAppleAdd } from '../lib/walletOpen';
import { cycleVisits, rewardsPending } from '../lib/cardCycle';
import { protectNames } from '../lib/translator';
import { liveOffers } from '../lib/cardOffers';
import { themeFromCard, themeVars } from '../lib/cardTheme';
import { photoPalette } from '../lib/photoPalette';
import { activityTime, activityRow, pointsBox, tabFromSearch, searchForTab, followNetworks, ctaOf, appleAddHref, cardViewPath, navActive, reviewOpen } from '../lib/cardPage';
import CardOffersContent from '../components/CardOffersContent';
import CardShareContent from '../components/CardShareContent';
import './MyWalletCardPage.css';

// The public « Partagez la carte » page (round 4: unrouted, kept for a rollback)
// — only for a phone that cannot open this card (see CardOwnerGate).
const CardSharePage = React.lazy(() => import('./CardSharePage'));

/*
 * « Ma carte en ligne » — the customer's card page (/card/:barcodeId, the
 * Wallet pass's « Ma carte en ligne » link). Photo/tabs redesign 2026-11-25
 * (mockup « Carte en ligne claire »): the card's own photo, the points box in
 * the programme's words, three tiles, the last activities, « Suivez-nous »,
 * and the bottom bar (MyWalletCardPagePrev.jsx, unrouted, for a rollback):
 *
 *   Accueil      the mockup + the missed-offers banner + the automation message
 *   Historique   every activity, page by page (also « Voir tout »)
 *   Récompenses  « Vos offres » IN the page (round 4, user 2026-11-26: no page
 *                opens another page): défis, the reward and its meter, the live
 *                offers, an offer's sheet — components/CardOffersContent
 *   Mon compte   paramètres, avis, à propos, RGPD, delete the card
 *
 * Two views with no bottom item lit (the bar stays, a back arrow leads home):
 *   ?onglet=programme   « Le programme », the reward waiting, the défis (Wallet tile)
 *   ?onglet=parrainage  « Parrainer un proche » — components/CardShareContent
 * The old addresses /card/{bc}/offres and /card/{bc}/partager open this page on
 * those views (lib/cardPage cardViewPath); their pages stay unrouted (rollback).
 *
 * « Ma carte » is gone everywhere (user, 2026-11-25): no tab, no button in the
 * points box, no pass preview, no Wallet buttons, no share / home screen /
 * print row, no PWA prompt, no geolocation card on this page (they stay on
 * the signup's « Félicitations »). An old ?onglet=carte link opens Accueil;
 * a ?wallet=apple arrival (« Ajouter à Apple Wallet » tapped in another app,
 * opened in Safari) starts that add itself — see appleAddHref.
 *
 * Tabs live in the address bar (?onglet=historique|recompenses|compte|
 * programme|parrainage) so the back button walks them.
 * Colours come from the card itself, else from its photo (lib/cardTheme
 * themeFromCard + lib/photoPalette), words from lib/cardPage.
 * Hero: logo + shop name + tagline compact in the TOP-LEFT corner, right under
 * the status bar (round 4); « Bonjour, <prénom> ! » at the photo's BOTTOM, just
 * above the points box; the photo fills the hero (cover). The colours are the
 * Wallet card's own (card.pass_colors + the photo's bottom band, lib/cardTheme).
 * Home tiles: offers · parrainer · the store's button (card.cta, set by the
 * FidClic super admin per établissement — « Prendre rendez-vous » by default).
 * A network or a button with no link says « Lien pas encore ajouté ».
 */

const FONT_ID = 'wcp-font-jakarta';
const FONT_URL = 'https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap';

// ---------------------------------------------------------------- icons (mockup)
const Svg = ({ size = 21, children, fill = 'none', sw = 1.8, ...rest }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={fill === 'none' ? 'currentColor' : undefined}
       strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...rest}>{children}</svg>
);
const I = {
  chev: <Svg size={14} sw={2.4}><path d="m9 6 6 6-6 6" /></Svg>,
  bell: <Svg size={19}><path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8" /><path d="M10 20a2 2 0 0 0 4 0" /></Svg>,
  user: (s = 19) => <Svg size={s}><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></Svg>,
  coins: <Svg size={23}><ellipse cx="10" cy="6.5" rx="6" ry="2.5" /><path d="M4 6.5v4c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-4" /><path d="M8 15.3v2.2c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-4c0-1.2-2-2.2-4.6-2.4" /></Svg>,
  stamp: (s = 23) => <Svg size={s}><circle cx="12" cy="12" r="8.5" /><path d="m8.5 12.2 2.4 2.4 4.6-5" /></Svg>,
  ticket: <Svg><path d="M3 8a2 2 0 0 0 2-2h14a2 2 0 0 0 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 0-2 2H5a2 2 0 0 0-2-2v-2a2 2 0 0 0 0-4z" /><path d="m9.5 14.5 5-5" /><circle cx="9.7" cy="9.7" r=".7" fill="currentColor" /><circle cx="14.3" cy="14.3" r=".7" fill="currentColor" /></Svg>,
  people: <Svg><circle cx="9" cy="8" r="3.2" /><path d="M3 19c.8-3 3.2-5 6-5s5.2 2 6 5" /><circle cx="17" cy="9" r="2.4" /><path d="M16.5 14c2.3 0 4 1.6 4.5 4" /></Svg>,
  pulse: <Svg size={19} sw={2.2}><path d="M2 12h4l3-7 5 14 3-7h5" /></Svg>,
  db: <Svg size={19}><ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></Svg>,
  gift: (s) => <Svg size={s}><rect x="4" y="10" width="16" height="10" rx="1.5" /><rect x="3" y="7" width="18" height="4" rx="1.5" /><path d="M12 7v13M12 7c-1.5-3.5-6-4-5.5-1.3C6.8 7 12 7 12 7zM12 7c1.5-3.5 6-4 5.5-1.3C17.2 7 12 7 12 7z" /></Svg>,
  home: <Svg size={23} fill="currentColor"><path d="M4 10.5 12 4l8 6.5V20h-5.5v-5.5h-5V20H4z" /></Svg>,
  clock23: <Svg size={23}><circle cx="12" cy="13" r="8" /><path d="M12 9v4l2.5 2M9 2h6" /></Svg>,
  calendar: <Svg><rect x="3.5" y="5" width="17" height="15.5" rx="2.5" /><path d="M3.5 10h17M8 3v4M16 3v4" /><path d="m9.2 15 1.9 1.9 3.8-3.8" /></Svg>,
};
const NET = {
  instagram: <Svg size={18} sw={2}><rect x="4" y="4" width="16" height="16" rx="5" /><circle cx="12" cy="12" r="3.8" /><circle cx="17" cy="7" r="1" fill="currentColor" stroke="none" /></Svg>,
  tiktok: <Svg size={17} fill="currentColor"><path d="M14 2h3c.3 2.4 1.8 4 4 4.3v3.1c-1.5 0-2.9-.5-4-1.2V15a6.5 6.5 0 1 1-6.5-6.5c.3 0 .6 0 .9.1v3.2a3.4 3.4 0 1 0 2.6 3.2z" /></Svg>,
  snapchat: <svg width="19" height="19" viewBox="0 0 24 24" fill="#fff" stroke="#000" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true"><path d="M12 3c3.2 0 5.2 2.4 5.2 5.4v2.3l1.8-.5c.6 0 .8.7.3 1l-2 1c.6 1.8 2 3.2 3.7 3.7-.3.8-1.6 1-2.6 1.1-.2.6-.3 1.2-.6 1.3-.6.2-1.5-.2-2.5.1-1 .3-1.7 1.6-3.3 1.6s-2.3-1.3-3.3-1.6c-1-.3-1.9.1-2.5-.1-.3-.1-.4-.7-.6-1.3-1-.1-2.3-.3-2.6-1.1 1.7-.5 3.1-1.9 3.7-3.7l-2-1c-.5-.3-.3-1 .3-1l1.8.5V8.4C6.8 5.4 8.8 3 12 3z" /></svg>,
  facebook: <Svg size={18} fill="currentColor"><path d="M13.5 21v-7.5H16l.4-3h-2.9V8.6c0-.9.3-1.5 1.5-1.5h1.5V4.4A20 20 0 0 0 14.3 4C12 4 10.5 5.4 10.5 7.9v2.6H8v3h2.5V21z" /></Svg>,
  youtube: <Svg size={18} fill="currentColor"><path d="M21.6 7.2a2.5 2.5 0 0 0-1.8-1.8C18.2 5 12 5 12 5s-6.2 0-7.8.4A2.5 2.5 0 0 0 2.4 7.2 26 26 0 0 0 2 12a26 26 0 0 0 .4 4.8 2.5 2.5 0 0 0 1.8 1.8C5.8 19 12 19 12 19s6.2 0 7.8-.4a2.5 2.5 0 0 0 1.8-1.8A26 26 0 0 0 22 12a26 26 0 0 0-.4-4.8zM10 15V9l5.2 3z" /></Svg>,
  x: <Svg size={16} fill="currentColor"><path d="M17.5 3h3.1l-6.8 7.8L21.8 21h-6.3l-4.9-6.4L5 21H1.9l7.3-8.3L1.6 3h6.4l4.4 5.9zm-1.1 16.2h1.7L7.1 4.7H5.3z" /></Svg>,
  linkedin: <Svg size={17} fill="currentColor"><path d="M4.5 3.5a2 2 0 1 1 0 4 2 2 0 0 1 0-4zM3 9h3v12H3zm6 0h2.9v1.7h.1c.4-.8 1.4-1.9 3-1.9 3.2 0 3.8 2.1 3.8 4.8V21h-3v-6.5c0-1.6 0-3.5-2.1-3.5s-2.5 1.7-2.5 3.4V21H9z" /></Svg>,
  pinterest: <Svg size={18} fill="currentColor"><path d="M12 2a10 10 0 0 0-3.6 19.3c-.1-.8-.2-2 0-2.9l1.3-5.4s-.3-.7-.3-1.6c0-1.5.9-2.7 2-2.7.9 0 1.4.7 1.4 1.5 0 .9-.6 2.3-.9 3.6-.3 1.1.5 2 1.6 2 1.9 0 3.4-2 3.4-5 0-2.6-1.9-4.4-4.6-4.4-3.1 0-5 2.3-5 4.8 0 .9.4 1.9.8 2.5.1.1.1.2.1.3l-.3 1.2c0 .2-.2.3-.4.2-1.4-.7-2.3-2.7-2.3-4.4 0-3.6 2.6-6.9 7.5-6.9 3.9 0 7 2.8 7 6.6 0 3.9-2.5 7.1-5.9 7.1-1.2 0-2.3-.6-2.6-1.3l-.7 2.7c-.3 1-1 2.2-1.4 3A10 10 0 1 0 12 2z" /></Svg>,
  whatsapp: <Svg size={18} fill="currentColor"><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm5.3 14.1c-.2.6-1.3 1.2-1.8 1.3-.5 0-1 .2-3.3-.7-2.8-1.1-4.5-3.9-4.7-4.1-.1-.2-1.1-1.5-1.1-2.8s.7-2 1-2.3c.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.9 2.1c.1.2.1.4 0 .5l-.3.5-.4.4c-.1.1-.3.3-.1.6.2.3.8 1.3 1.7 2.1 1.2 1 2.1 1.4 2.4 1.5.3.1.5.1.7-.1l.9-1.1c.2-.3.4-.2.7-.1l2 1c.3.1.5.2.5.3.1.2.1.6-.1 1.2z" /></Svg>,
  site: <Svg size={18}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z" /></Svg>,
};
const NET_CLASS = { instagram: 'ig', tiktok: 'tt', snapchat: 'sc', facebook: 'fb', youtube: 'yt', x: 'x', linkedin: 'li', pinterest: 'pi', whatsapp: 'wa' };

// Only a real picture address reaches a CSS url(): http(s), same-site or data:image.
function cssUrl(u) {
  const s = String(u || '').trim();
  if (!/^(https?:\/\/|\/(?!\/)|data:image\/)/i.test(s)) return null;
  return `url("${s.replace(/["\\\n\r]/g, (c) => encodeURIComponent(c))}")`;
}

// The shop's logo, or its first letter when there is none (or it does not load).
function ShopLogo({ url, name, className }) {
  const [broken, setBroken] = useState(false);
  if (url && !broken) return <img src={url} alt="" className={className} onError={() => setBroken(true)} />;
  return <span className={`${className} letter`} aria-hidden="true">{(name || '?').trim().charAt(0).toUpperCase()}</span>;
}

const ROW_ICON = { coin: ['coin', I.db], stamp: ['coin', I.stamp(19)], gift: ['ok', I.gift(19)], people: ['', I.people] };
function ActivityRows({ items, card, testId }) {
  const rows = (items || []).map((it) => ({ it, r: activityRow(it, card) })).filter((x) => x.r);
  return (
    <ul className="rows" data-testid={testId}>
      {rows.map(({ it, r }, i) => {
        const [cls, icon] = ROW_ICON[r.icon] || ROW_ICON.coin;
        return (
          <li key={`${it.at || ''}-${i}`} className="row">
            <span className={`ico ${cls}`}>{icon}</span>
            <div style={{ minWidth: 0 }}>
              <b className="num">{r.title}</b>
              {r.sub && <span>{r.sub}</span>}
              {r.sub && r.plus && <span> · </span>}
              {r.plus && <span className="plus num">{r.plus}</span>}
            </div>
            <time className="num notranslate" translate="no" dateTime={typeof it.at === 'string' ? it.at : undefined}>{activityTime(it.at)}</time>
          </li>
        );
      })}
    </ul>
  );
}

const fmtDay = (s) => {
  const t = Date.parse(s || '');
  return Number.isFinite(t) ? new Date(t).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', timeZone: 'Europe/Paris' }) : '';
};

const TAB_DEFS = [
  { key: 'accueil', label: 'Accueil', icon: I.home },
  { key: 'historique', label: 'Historique', icon: I.clock23 },
  { key: 'recompenses', label: 'Récompenses', icon: I.gift(23) },   // « Vos offres », in the page (round 4)
  { key: 'compte', label: 'Mon compte', icon: I.user(23) },
];

const CardView = () => {
  const { barcodeId } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [deleted, setDeleted] = useState(false);
  // RGPD forget-me completed — distinct from `deleted` (card removed from
  // wallet, data kept) because here the DATA itself is gone.
  const [erased, setErased] = useState(false);
  const [toast, setToast] = useState(null);
  // The notification the customer just tapped in the News tab. When set,
  // the detail modal at the bottom of the page renders showing the full
  // campaign body, image, and (if present) a CTA link the customer can
  // tap. The open is tracked the moment they tap the card; the click is
  // tracked separately when they tap the CTA link.
  const [openedNotification, setOpenedNotification] = useState(null);
  // Rate-your-visit state
  const [reviewRating, setReviewRating] = useState(8);
  const [reviewText, setReviewText] = useState('');
  const [reviewSubmitting, setReviewSubmitting] = useState(false);

  // ─── Strategy 1 + 3 — Push-recovery state ────────────────────────────
  // We fetch /api/card/{bc}/notification-status on load. If the customer
  // has no active push subscription AND has missed ≥1 campaign in the
  // last 30 days, we show a prominent banner offering to enable. If
  // they arrive via the staff QR (?notify=1), we auto-trigger the prompt.
  const [notifStatus, setNotifStatus] = useState(null);
  // {subscribed: bool, missed_count: int, since_days: int}
  const [showMissedBanner, setShowMissedBanner] = useState(true);
  const [reviewThanks, setReviewThanks] = useState(false);
  // Set only when the server decides this customer should be invited to review
  // publicly — a satisfied rating, and a shop that switched it on.
  const [googleReviewUrl, setGoogleReviewUrl] = useState(null);
  const [reviewError, setReviewError] = useState(null);

  // Swap the page's <link rel="manifest"> to the per-card manifest
  // returned by /api/manifest/{barcodeId}. That manifest has
  // start_url=/card/{barcodeId} so when the customer taps "Add to Home
  // Screen" and later launches from the icon, the OS opens THIS card
  // directly — not the landing page (which is what happens with the
  // default site-wide manifest).
  //
  // An inline script in index.html does the SAME swap before React
  // boots, so iOS Safari (which reads the manifest at page load, not
  // at install time) sees the correct href even before this hook runs.
  // We re-apply it here for client-side route changes.
  //
  // We ALSO stash this card's barcode in localStorage so the launch
  // failsafe below can recover the customer's card if the PWA boots
  // at "/" anyway — which happens on some older iOS versions that
  // ignore the manifest start_url entirely and just open the site root.
  useEffect(() => {
    if (!barcodeId) return;
    const link = document.querySelector('link[rel="manifest"]');
    if (link) {
      const original = link.getAttribute('href');
      // With the owner key, the installed app opens on the owner's link (an
      // iPhone home-screen app has its own storage: lib/myCards). The card is
      // remembered for main.jsx's failsafe by lib/myCards, for this phone's
      // own cards only.
      const k = keyOf(barcodeId);
      link.setAttribute('href', `/api/manifest/${barcodeId}${k ? `?k=${encodeURIComponent(k)}` : ''}`);
      return () => {
        if (original) link.setAttribute('href', original);
      };
    }
  }, [barcodeId]);

  // Whose card this is on this phone is decided before this view renders:
  // see CardOwnerGate at the bottom (a friend's scanned QR never shows here).

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get(`/card/${barcodeId}`);
        setData(res.data);
      } catch (e) {
        // Surface the real reason — without this every failure became a
        // generic "Card not found" and the owner couldn't tell whether
        // it was a 404, 500, network error, or auth issue. Log to
        // console for DevTools-on-mobile workflows.
        const status = e?.response?.status;
        const detail = e?.response?.data?.detail;
        const msg = status === 410
          ? (detail || "Ce programme de fidélité n'est plus disponible.")
          : status === 404
          ? `Aucune carte trouvée pour ${barcodeId}. Vérifiez que la carte a bien été créée (côté commerçant : Dashboard → Customers).`
          : status === 500
            ? `Erreur serveur (${detail || 'sans détail'}). Le commerçant doit recharger le seed ou contacter le support.`
            : (detail || e.message || 'Carte indisponible.');
        // eslint-disable-next-line no-console
        console.error('[wallet card] load failed', { status, detail, e });
        setErr(msg);
      } finally {
        setLoading(false);
      }
    })();
  }, [barcodeId]);

  // Self-healing web-push subscription: if the customer has push_enabled=true
  // (set on a previous visit) but the browser has no live subscription right
  // now — e.g. they cleared site data, switched device, or the browser rotated
  // the endpoint — silently re-register. This runs only when permission is
  // already granted, so we never prompt the user unexpectedly.
  // The shop's name is a name, not words: « Royal Trim Liberté » must not read
  // « Royal Trim Freedom » in English. This page lives outside the dashboard
  // layout, which is the only place that registered names until now, so on the
  // customer's own card nothing protected it (user, 2026-10-13).
  useEffect(() => {
    protectNames([data?.tenant?.name, data?.customer?.name]);
  }, [data?.tenant?.name, data?.customer?.name]);

  useEffect(() => {
    if (!data?.prefs?.push_enabled) return;
    if (!isPushSupported()) return;
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    const tenantSlug = data?.tenant?.slug;
    if (!tenantSlug || !barcodeId) return;
    ensureSubscribed(tenantSlug, barcodeId).catch(() => { /* silent */ });
  }, [data?.prefs?.push_enabled, data?.tenant?.slug, barcodeId]);

  // ─── Strategy 1 — fetch notification status + missed-offer count ───
  // Runs whenever the wallet card loads. Tells us if the customer needs
  // a re-enable banner (subscribed=false AND missed_count>0).
  useEffect(() => {
    // once the card is here: asked before it too, the status went out twice
    // per page load (2026-11-21 — every request counts on a busy server)
    if (!barcodeId || !data?.customer?.id) return;
    let alive = true;
    fetch(`/api/card/${encodeURIComponent(barcodeId)}/notification-status`,
          { headers: keyOf(barcodeId) ? { 'X-Card-Key': keyOf(barcodeId) } : {} })
      .then((r) => r.ok ? r.json() : null)
      .then((s) => { if (alive && s) setNotifStatus(s); })
      .catch(() => { /* silent — banner just won't show */ });
    return () => { alive = false; };
  }, [barcodeId, data?.customer?.id]);

  // ─── Strategy 3 link target — auto-trigger notification prompt ─────
  // When customer arrives at this page via the staff QR (URL has ?notify=1),
  // we fire the browser permission prompt as soon as the page is ready.
  // The card MUST have rendered first (loading=false) for the user gesture
  // to be considered "in response to a tap" — otherwise iOS blocks it.
  useEffect(() => {
    if (loading || !data?.tenant?.slug || !barcodeId) return;
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('notify') !== '1') return;
    if (typeof Notification === 'undefined') return;
    if (Notification.permission === 'granted') {
      // Already enabled — just clean the URL and show a confirmation.
      window.history.replaceState({}, '', window.location.pathname);
      return;
    }
    if (Notification.permission === 'denied') {
      // Browser already blocked — can't re-prompt, must go through settings.
      showToast("Activez les notifications dans les paramètres de votre navigateur.");
      window.history.replaceState({}, '', window.location.pathname);
      return;
    }
    // Permission === 'default' — trigger the prompt now.
    const t = setTimeout(() => {
      ensureSubscribed(data.tenant.slug, barcodeId).then((r) => {
        if (r && r.ok) {
          showToast('Notifications activées — merci !');
          setNotifStatus({ subscribed: true, missed_count: 0 });
        }
        window.history.replaceState({}, '', window.location.pathname);
      }).catch(() => {
        window.history.replaceState({}, '', window.location.pathname);
      });
    }, 800);
    return () => clearTimeout(t);
  }, [loading, data?.tenant?.slug, barcodeId]);

  // iOS standalone-mode auto-prompt:
  //
  // On iOS Safari, web push is only allowed once the page has been added to
  // the home screen as a standalone PWA. As soon as the user opens the card
  // FROM the home screen, we auto-prompt for notification permission so they
  // don't have to dig into settings. Permission.request returns 'default' on
  // older iOS where it's still unsupported — we just silently no-op.
  useEffect(() => {
    if (!data?.tenant?.slug || !barcodeId) return;
    const isStandalone =
      window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true;
    if (!isStandalone) return;
    if (typeof Notification === 'undefined') return;
    if (Notification.permission !== 'default') return; // already decided
    const t = setTimeout(() => {
      // Tiny delay so the prompt doesn't compete with first paint.
      ensureSubscribed(data.tenant.slug, barcodeId).catch(() => { /* silent */ });
    }, 1500);
    return () => clearTimeout(t);
  }, [data?.tenant?.slug, barcodeId]);

  // Real-time proximity push: when the wallet card page opens AND the user has
  // already granted geolocation, ping the backend with the current GPS. If the
  // customer is within the tenant's configured radius, a proximity push is
  // logged and shown at the top of the card. Each Géolocalisation automation
  // keeps its own gap per client on the server (« une fois tous les X jours »).
  useEffect(() => {
    if (!data?.customer?.id || !navigator.geolocation) return;
    // Only ping once per card view, and stay silent if permissions are denied
    // (don't pop a prompt — we let the Join flow ask for geo explicitly).
    let ignored = false;
    navigator.permissions?.query({ name: 'geolocation' }).then((perm) => {
      if (perm.state !== 'granted') return;
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          if (ignored) return;
          try {
            const res = await publicAPI.proximityPing({
              customer_id: data.customer.id,
              latitude: pos.coords.latitude,
              longitude: pos.coords.longitude,
            });
            if (res?.data?.status === 'sent') {
              // the shop's « Géolocalisation » automation: its words and its button, at the top
              setGeoMsg({ log_id: `geo-${Date.now()}`, title: res.data.title, body: res.data.body,
                button_label: res.data.button_label, button_url: res.data.button_url });
            }
          } catch (_e) { /* best-effort; ignore */ }
        },
        () => { /* user-denied or timeout — silent */ },
        { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 }
      );
    }).catch(() => {});
    return () => { ignored = true; };
  }, [data?.customer?.id]);

  const [geoMsg, setGeoMsg] = useState(null);
  const [hiddenMsg, setHiddenMsg] = useState(() => {
    try { return localStorage.getItem('fidclic:auto_msg_hidden') || ''; } catch { return ''; }
  });
  const toastTimer = useRef(null);
  const showToast = (msg) => {
    setToast(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 2600);
  };
  useEffect(() => () => clearTimeout(toastTimer.current), []);
  // a network or the store's button with no link yet (user, 2026-11-25)
  const noLink = () => showToast('Lien pas encore ajouté');

  const togglePref = async (key) => {
    if (!data) return;
    setSavingPrefs(true);
    const newVal = !data.prefs[key];
    try {
      // Persist the preference flag first so the backend knows the user's intent
      const res = await api.put(`/card/${barcodeId}/prefs`, { [key]: newVal });
      setData({ ...data, prefs: res.data });

      // For the push toggle, also drive the actual browser subscription.
      // We do this AFTER the prefs save so the toggle visibly flips first.
      if (key === 'push_enabled') {
        const tenantSlug = data?.tenant?.slug;
        if (newVal) {
          if (!isPushSupported()) {
            // Special-case iOS Safari before iOS 16.4: push isn't supported
            // there at all, but adding the card to home screen UNLOCKS it.
            // Even on newer iOS, push only works in standalone mode, so the
            // friendly action is to walk the user through "Add to Home Screen".
            const ua = navigator.userAgent || '';
            const isIos = /iPhone|iPad|iPod/.test(ua);
            const isStandalone =
              window.matchMedia('(display-mode: standalone)').matches ||
              window.navigator.standalone === true;
            if (isIos && !isStandalone) {
              showToast("Ajoutez d'abord la carte à votre écran d'accueil pour activer les notifications.");
            } else {
              showToast("Ce navigateur ne supporte pas les notifications push.");
            }
          } else {
            const result = await ensureSubscribed(tenantSlug, barcodeId);
            if (result.ok) {
              showToast('Notifications activées');
            } else if (result.status === 'permission_denied') {
              showToast("Veuillez autoriser les notifications dans votre navigateur.");
            } else if (result.status === 'vapid_not_configured') {
              showToast("Notifications push non configurées (contactez le commerçant).");
            } else {
              showToast("Impossible d'activer les notifications.");
            }
          }
        } else {
          await unsubscribePush(tenantSlug, barcodeId).catch(() => {});
          showToast('Notifications désactivées');
        }
      } else {
        showToast(
          newVal ? 'Mise à jour automatique activée' : 'Mise à jour automatique désactivée'
        );
      }
    } catch (e) {
      showToast('Échec de la mise à jour');
    } finally {
      setSavingPrefs(false);
    }
  };

  const deleteCard = async () => {
    if (!window.confirm('Supprimer cette carte du wallet ? Vos visites restent enregistrées côté commerçant.')) return;
    try {
      await api.delete(`/card/${barcodeId}`);
      forgetMine([barcodeId]);             // no longer this phone's card (lib/myCards)
      setDeleted(true);
    } catch (e) {
      showToast('Impossible de supprimer la carte');
    }
  };

  // ─── RGPD self-service ────────────────────────────────────────────
  // Art. 15/20 — download everything we hold as a JSON file.
  const downloadMyData = async () => {
    try {
      const res = await api.get(`/card/${barcodeId}/my-data`);
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mes-donnees-${barcodeId}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast('Vos données ont été téléchargées.');
    } catch (e) {
      showToast('Impossible de télécharger vos données.');
    }
  };

  // Art. 17 — irreversible erasure. Double confirmation because there is
  // no undo: window.confirm + a typed keyword would be overkill on mobile,
  // two distinct confirms is the accepted pattern.
  const forgetMe = async () => {
    if (!window.confirm('Supprimer définitivement toutes vos données personnelles ? Cette action est IRRÉVERSIBLE — votre carte, vos points et votre historique seront perdus.')) return;
    if (!window.confirm('Dernière confirmation : vos données seront effacées et cette carte ne fonctionnera plus. Continuer ?')) return;
    try {
      await api.post(`/card/${barcodeId}/forget-me`, { confirm: true });
      setErased(true);
    } catch (e) {
      showToast('La suppression a échoué. Réessayez ou contactez le commerçant.');
    }
  };

  // ── Merged "Offres" feed — MUST stay above every early return ───────
  // React error #310 ("Rendered more hooks than during the previous
  // render") lived here: this useMemo sat BELOW the `if (loading)` /
  // `if (!data)` guards. First paint bailed out at `loading` and never
  // reached the hook; the next paint got past the guards and ran it, so
  // React saw the hook count grow between renders and tore the tree down.
  // Every freshly-joined customer hit it, because their first visit to
  // /card/:id is always loading-then-loaded.
  //
  // Hooks are positional: they must run in the same order on every
  // render. Anything conditional goes INSIDE the hook, never around it —
  // hence the `data?.` reads below instead of the destructured locals,
  // which do not exist yet at this point in the function.
  const mergedFeed = React.useMemo(() => {
    const seen = new Set();
    const out = [];
    // 1. Standing offer (kind:'primary') first, if present.
    for (const o of (data?.offers || [])) {
      if (o.kind === 'primary' && o.id && !seen.has(o.id)) {
        seen.add(o.id);
        out.push({ ...o, _ts: 9e15 /* always first */ });
      }
    }
    // 2. Campaign-kind items from offers (already has body/image/link).
    for (const o of (data?.offers || [])) {
      if (o.kind === 'campaign' && o.id && !seen.has(o.id)) {
        seen.add(o.id);
        out.push({ ...o, _ts: o.sent_at ? Date.parse(o.sent_at) : 0 });
      }
    }
    // 3. Anything in `notifications` that wasn't already in offers (fallback,
    // future-proofing if backend ever returns extra notifications).
    for (const n of (data?.notifications || [])) {
      if (n.id && !seen.has(n.id)) {
        seen.add(n.id);
        out.push({
          id: n.id,
          kind: 'campaign',
          title: n.title,
          description: n.body || '',
          body: n.body || '',
          image_url: n.image_url,
          link: n.link,
          sent_at: n.sent_at,
          _ts: n.sent_at ? Date.parse(n.sent_at) : 0,
        });
      }
    }
    out.sort((a, b) => (b._ts || 0) - (a._ts || 0));
    return out;
  }, [data?.offers, data?.notifications]);
  // « Mes offres · N en cours » counts what its page lists: the live offers only,
  // never the ended campaigns or défis `notifications` still carries (lib/cardOffers)
  const liveOfferCount = React.useMemo(() => liveOffers(data).length, [data?.offers]);

  // « Voir l'offre » on the back of the Wallet pass lands here with
  // ?offre=<campaign id>: open that campaign (photo + full text) right away,
  // since Wallet itself can show neither.
  const offerOpened = useRef(false);
  useEffect(() => {
    if (offerOpened.current || typeof window === 'undefined') return;
    const wanted = new URLSearchParams(window.location.search).get('offre');
    if (!wanted || !data?.customer?.id) return;
    const item = mergedFeed.find((o) => o.kind === 'campaign' && String(o.id) === wanted);
    if (!item) return;
    offerOpened.current = true;
    setOpenedNotification({
      id: item.id, title: item.title, body: item.body || item.description || '',
      image_url: item.image_url, link: item.link, sent_at: item.sent_at,
    });
    api.get(`/campaigns/${item.id}/pixel/${data.customer.id}.png`).catch(() => {});
  }, [mergedFeed, data?.customer?.id]);

  // ── Redesign 2026-11-25: tabs, activity, theme — above every early return ──
  // The tab is the address bar's (?onglet=…), so the back button walks tabs.
  const location = useLocation();
  const navigate = useNavigate();
  const tab = tabFromSearch(location.search);
  // `anchor`: an element of the new view to scroll to (« Mes offres exclusives » → the offers)
  const scrollToAnchor = (id) => {
    try { document.getElementById(id)?.scrollIntoView({ block: 'start' }); } catch (_e) { /* old browsers */ }
  };
  const goTab = (next, anchor) => {
    const search = searchForTab(window.location.search, next);
    if (search === window.location.search) {
      if (anchor) scrollToAnchor(anchor);
      return;
    }
    navigate({ pathname: window.location.pathname, search }, { state: { cardTab: true, anchor: anchor || null } });
    if (!anchor) { try { window.scrollTo({ top: 0 }); } catch (_e) { /* old browsers */ } }
  };
  // the new view is drawn: go to the part asked for (the tile « Mes offres exclusives » → the offers)
  const anchorWanted = location.state?.anchor;
  useEffect(() => {
    if (!anchorWanted) return undefined;
    const raf = requestAnimationFrame(() => scrollToAnchor(anchorWanted));
    return () => cancelAnimationFrame(raf);
  }, [location.key, anchorWanted]); // eslint-disable-line react-hooks/exhaustive-deps
  const backHome = () => (location.state?.cardTab ? navigate(-1) : goTab('accueil'));

  // « Ajouter à Apple Wallet » tapped in another app opened this card in Safari
  // with ?wallet=apple (components/WalletButtons). There is no « Ma carte »
  // button to point at any more (user, 2026-11-25): the page opens the same
  // pass link itself, once, then waits for the iPhone's word and opens Wallet
  // (lib/walletOpen) — as that button did. Anywhere but Safari on an iPhone,
  // only ?wallet= is forgotten.
  const [appleAdd, setAppleAdd] = useState(null);       // the pass link being opened
  const appleTried = useRef(false);
  useEffect(() => {
    if (appleTried.current || !barcodeId || !data?.customer?.id) return undefined;
    const search = window.location.search;
    if (new URLSearchParams(search).get('wallet') !== 'apple') return undefined;
    appleTried.current = true;
    try {
      const q = new URLSearchParams(search);
      q.delete('wallet');
      const rest = q.toString();
      window.history.replaceState(window.history.state, '', `${window.location.pathname}${rest ? `?${rest}` : ''}${window.location.hash}`);
    } catch (_e) { /* old browsers: the param stays, harmless */ }
    const place = walletPlace();
    if (place !== 'safari') return undefined;
    let gone = false;
    api.get('/wallet/config', { params: { barcode: barcodeId } }).then((r) => {
      const href = appleAddHref({ search, barcodeId, key: keyOf(barcodeId), place, appleOn: r?.data?.apple === true });
      if (!href || gone) return;
      setAppleAdd(href);
      try { window.location.href = href; } catch (_e) { /* « Réessayer » below */ }
      waitForAppleAdd({
        ask: () => api.get(`/card/${barcodeId}/apple-wallet/added`).then((x) => x.data?.added === true),
        hidden: () => document.hidden,
        cancelled: () => gone,
      }).then((added) => {
        // #521 dropped the jump to the Wallet app (lib/walletOpen): the card is in Wallet
        if (!added || gone) return;
        setAppleAdd(null);
      });
    }).catch(() => {});
    return () => { gone = true; };
  }, [barcodeId, data?.customer?.id]);

  // « Mes dernières activités »: the last three, asked once the card is here
  const [recent, setRecent] = useState(null);
  useEffect(() => {
    if (!barcodeId || !data?.customer?.id) return;
    let alive = true;
    api.get(`/card/${barcodeId}/activity`, { params: { limit: 3 } })
      .then((r) => { if (alive) setRecent(Array.isArray(r?.data?.items) ? r.data.items : []); })
      .catch(() => { if (alive) setRecent([]); });
    return () => { alive = false; };
  }, [barcodeId, data?.customer?.id]);

  // Historique: the whole list, page by page (`next` → `before`)
  const [history, setHistory] = useState({ items: [], next: null, loaded: false, busy: false });
  const loadHistory = (before) => {
    setHistory((h) => ({ ...h, busy: true }));
    api.get(`/card/${barcodeId}/activity`, { params: { limit: 20, ...(before ? { before } : {}) } })
      .then((r) => {
        const items = Array.isArray(r?.data?.items) ? r.data.items : [];
        setHistory((h) => ({ items: before ? [...h.items, ...items] : items, next: r?.data?.next || null, loaded: true, busy: false }));
      })
      .catch(() => setHistory((h) => ({ ...h, loaded: true, busy: false })));
  };
  useEffect(() => {
    if (tab !== 'historique' || !data?.customer?.id || history.loaded || history.busy) return;
    loadHistory(null);
  }, [tab, data?.customer?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // The shop's colours, calmed (lib/cardTheme), and the mockup's font. A card
  // with no colour of its own (black / white / grey) takes its photo's colours
  // (lib/photoPalette, user 2026-11-25): read from the picture the hero already
  // loads — no API request — and the page re-themes when they arrive.
  const heroSrc = data?.card?.hero_photo_url;
  const [photoPal, setPhotoPal] = useState(null);
  useEffect(() => {
    const src = String(heroSrc || '').trim();
    if (!/^(https?:\/\/|\/(?!\/)|data:image\/)/i.test(src)) { setPhotoPal(null); return undefined; }
    let alive = true;
    photoPalette(src).then((pal) => { if (alive) setPhotoPal(pal); });
    return () => { alive = false; };
  }, [heroSrc]);
  const theme = React.useMemo(() => themeFromCard(data?.card, photoPal), [data?.card, photoPal]);
  useEffect(() => {
    if (document.getElementById(FONT_ID)) return;
    const l = document.createElement('link');
    l.id = FONT_ID; l.rel = 'stylesheet'; l.href = FONT_URL;
    document.head.appendChild(l);
  }, []);
  // the page colour behind iOS's overscroll too
  useEffect(() => {
    if (!data?.card) return undefined;
    const before = document.body.style.backgroundColor;
    document.body.style.backgroundColor = theme.page;
    return () => { document.body.style.backgroundColor = before; };
  }, [theme.page, data?.card]);

  if (loading) {
    return <div key="loading" className="min-h-screen bg-[#FAFAF8] flex items-center justify-center text-[#57504A]">Chargement de votre carte…</div>;
  }
  if (err) {
    return (
      <div className="min-h-screen bg-[#FAFAF8] flex items-center justify-center">
        <div className="bg-white rounded-2xl p-8 border border-[#E9E5E0] max-w-md text-center">
          <XCircle className="mx-auto text-[#B85C38] mb-3" size={40} />
          <p className="text-[#171412] font-semibold mb-2">{/n'est plus disponible/.test(err) ? 'Programme terminé' : 'Carte introuvable'}</p>
          <p className="text-[#57504A] text-sm">{err}</p>
          <Link to="/" className="inline-block mt-5 text-[#B85C38] underline">Retour à l'accueil</Link>
        </div>
      </div>
    );
  }
  if (erased) {
    return (
      <div className="min-h-screen bg-[#FAFAF8] flex items-center justify-center">
        <div className="bg-white rounded-2xl p-8 border border-[#E9E5E0] max-w-md text-center">
          <ShieldCheck className="mx-auto text-[#4A5D23] mb-3" size={40} />
          <p className="text-[#171412] font-semibold mb-2">Données supprimées</p>
          <p className="text-[#57504A] text-sm">
            Vos données personnelles ont été effacées conformément au RGPD.
            Cette carte n'est plus utilisable. Vous pouvez vous réinscrire à
            tout moment auprès du commerçant.
          </p>
          <Link to="/" className="inline-block mt-5 text-[#B85C38] underline">Retour à l'accueil</Link>
        </div>
      </div>
    );
  }
  if (deleted) {
    return (
      <div className="min-h-screen bg-[#FAFAF8] flex items-center justify-center">
        <div className="bg-white rounded-2xl p-8 border border-[#E9E5E0] max-w-md text-center">
          <CheckCircle2 className="mx-auto text-[#4A5D23] mb-3" size={40} />
          <p className="text-[#171412] font-semibold mb-2">Carte supprimée</p>
          <p className="text-[#57504A] text-sm">Votre carte a bien été retirée de votre wallet.</p>
          <Link to="/" className="inline-block mt-5 text-[#B85C38] underline">Retour à l'accueil</Link>
        </div>
      </div>
    );
  }

  // Safety net: every observable path through useEffect either sets
  // data or sets err and flips loading=false. If we somehow reach
  // here with both null, render something explicit instead of falling
  // into a destructure-of-null crash that white-screens the page.
  if (!data) {
    return (
      <div className="min-h-screen bg-[#FAFAF8] flex items-center justify-center">
        <div className="bg-white rounded-2xl p-8 border border-[#E9E5E0] max-w-md text-center">
          <XCircle className="mx-auto text-[#B85C38] mb-3" size={40} />
          <p className="text-[#171412] font-semibold mb-2">Carte indisponible</p>
          <p className="text-[#57504A] text-sm">
            La carte n'a pas pu être chargée. Vérifiez votre connexion ou rechargez la page.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="inline-block mt-5 px-4 py-2 rounded-lg bg-[#B85C38] text-white text-sm font-medium"
          >
            Recharger
          </button>
        </div>
      </div>
    );
  }

  const { customer, tenant, card, offers, prefs, notifications } = data;
  // Same belt-and-braces guard for missing sub-objects — keeps the
  // page rendering even if the backend payload shape changes.
  if (!customer || !card) {
    return (
      <div className="min-h-screen bg-[#FAFAF8] flex items-center justify-center">
        <div className="bg-white rounded-2xl p-8 border border-[#E9E5E0] max-w-md text-center">
          <XCircle className="mx-auto text-[#B85C38] mb-3" size={40} />
          <p className="text-[#171412] font-semibold mb-2">Carte incomplète</p>
          <p className="text-[#57504A] text-sm">
            Les données reçues du serveur sont incomplètes. Veuillez contacter le commerçant.
          </p>
        </div>
      </div>
    );
  }
  const stampsTarget = card.reward_threshold || 10;



  // « Donner mon avis »: 14 days after the last visit — GET /card/{bc} sends it
  const recentVisit = reviewOpen(customer.last_visit_date);
  const pending = rewardsPending(customer);
  // the shop's view (?vue=commerce, from the dashboard) stays on through every
  // tab and view: searchForTab keeps it (QA F34, 2026-10-11)
  const shop = tenant?.name || '';
  const firstName = (customer.first_name || String(customer.name || '').trim().split(/\s+/)[0] || '').trim();
  const box = pointsBox(card, customer);
  const networks = followNetworks(card.socials);
  const joinUrl = networks.find((n) => n.url)?.url || null;
  const cta = ctaOf(card);
  const heroUrl = cssUrl(card.hero_photo_url);
  const missed = notifStatus && !notifStatus.subscribed && notifStatus.missed_count > 0;
  const autoMsg = (() => {
    const am = geoMsg || data?.auto_message;
    return am && am.title && hiddenMsg !== am.log_id ? am : null;
  })();
  const tier = ({ bronze: 'Bronze', silver: 'Argent', gold: 'Or', vip: 'VIP' })[String(customer.tier || 'bronze').toLowerCase()] || customer.tier;
  const enableFromBanner = async () => {
    const slug = data?.tenant?.slug;
    if (!slug || !barcodeId) return;
    try {
      const r = await ensureSubscribed(slug, barcodeId);
      if (r && r.ok) { showToast('Notifications activées — merci !'); setNotifStatus({ subscribed: true, missed_count: 0 }); }
      else if (r?.status === 'permission_denied') showToast('Activez les notifications dans les paramètres de votre navigateur.');
      else showToast("Impossible d'activer les notifications.");
    } catch { showToast("Impossible d'activer les notifications."); }
  };
  const hideAutoMsg = (am) => {
    setHiddenMsg(am.log_id); setGeoMsg(null);
    try { localStorage.setItem('fidclic:auto_msg_hidden', am.log_id); } catch { /* private mode */ }
  };
  const submitReview = async () => {
    try {
      setReviewSubmitting(true);
      setReviewError(null);
      const { data: sent } = await publicAPI.submitReview({
        customer_id: customer.id, barcode_id: customer.barcode_id, rating: reviewRating, text: reviewText,
        visit_id: customer.last_visit_id || undefined, branch_id: customer.branch_id || undefined,
      });
      setGoogleReviewUrl(sent?.google_review_url || null);
      setReviewThanks(true);
      setReviewText('');
    } catch (e) {
      setReviewError(e?.response?.data?.detail || 'Impossible d\'envoyer votre avis.');
    } finally {
      setReviewSubmitting(false);
    }
  };
  const testPush = async () => {
    try {
      const { data: d = {} } = await api.post(`/card/${customer.barcode_id}/test-push`);
      if (d.sent > 0) showToast(`Notification envoyée à ${d.sent} appareil${d.sent > 1 ? 's' : ''}.`);
      else if (d.error === 'no_subscription') showToast('Activez d’abord les notifications ci-dessus.');
      else if (d.error === 'vapid_not_configured') showToast('Notifications non configurées (contactez le commerçant).');
      else showToast(`Échec : ${d.error || 'inconnu'}`);
    } catch (e) { showToast('Erreur réseau lors du test.'); }
  };

  // Header of the tabs other than Accueil: the shop, then the tab's title
  const tabHead = (title, back) => (
    <header className="head">
      {back
        ? <button type="button" className="back" aria-label="Retour" onClick={back}><ChevronLeft size={22} aria-hidden="true" /></button>
        : <ShopLogo url={card.logo_url} name={shop} className="logo" />}
      <div style={{ minWidth: 0 }}>
        <p className="k notranslate" translate="no" style={{ margin: 0 }}>{shop}</p>
        <h1>{title}</h1>
      </div>
    </header>
  );

  // ─────────────────────────────────────────────────── Accueil
  const home = (
    <>
      <div className={`hero${heroUrl ? '' : ' nophoto'}`} data-testid="card-hero">
        {heroUrl && <div className="hero-img" data-testid="hero-photo" aria-hidden="true" style={{ backgroundImage: heroUrl }} />}
        {heroUrl && <div className="hero-shade" aria-hidden="true" />}
        {/* the shop, compact in the top-left corner under the status bar (round 4) */}
        <header className="top" data-testid="hero-brand">
          <div className="brand">
            <ShopLogo url={card.logo_url} name={shop} className="logo" />
            <div style={{ minWidth: 0 }}>
              <div className="wm notranslate" translate="no">{shop}</div>
              {String(card.tagline || '').trim() && <div className="tag" data-testid="hero-tagline">{String(card.tagline).trim()}</div>}
            </div>
          </div>
        </header>
        <div className="hero-space">
          {!heroUrl && <span data-testid="hero-logo"><ShopLogo url={card.logo_url} name={shop} className="biglogo" /></span>}
        </div>
        {/* at the photo's bottom, just above the points box (as in PR #519 — user, 2026-11-25) */}
        <div className="hello"><h1>{firstName ? <>Bonjour, <span className="notranslate" translate="no">{firstName}</span> !</> : 'Bonjour !'}</h1></div>
      </div>
      <div className="hero-tail" aria-hidden="true" />
      <div className="stack">
        <section className="sheet points" data-testid="points-box" aria-label={box.label}>
          <div className="ph">
            <span className="ico">{programmeOf(card) === 'stamps' ? I.stamp() : I.coins}</span>
            <div style={{ minWidth: 0 }}>
              <div className="label">{box.label}</div>
              <div className="big num">{box.big}{box.unit && <> <small>{box.unit}</small></>}</div>
            </div>
          </div>
          <div className="pb">
            <div>
              {box.message && (
                <p>{box.strong && box.message.includes(box.strong)
                  ? <>{box.message.split(box.strong)[0]}<strong className="num">{box.strong}</strong>{box.message.split(box.strong).slice(1).join(box.strong)}</>
                  : box.message}</p>
              )}
              {box.progress != null && (
                <div className="bar" role="progressbar" aria-label="Progression vers la récompense"
                     aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(box.progress * 100)}>
                  <i style={{ width: `${Math.max(box.progress > 0 ? 4 : 0, box.progress * 100)}%` }} />
                </div>
              )}
              {box.scale && <div className="scale num">{box.scale}</div>}
            </div>
            <svg viewBox="0 0 74 70" width="74" height="70" aria-hidden="true">
              <ellipse cx="37" cy="64" rx="26" ry="4" fill="var(--soft)" />
              <rect x="12" y="30" width="50" height="32" rx="5" fill="var(--soft)" stroke="var(--brand)" strokeWidth="1.6" />
              <rect x="8" y="21" width="58" height="12" rx="4" fill="var(--sheet)" stroke="var(--brand)" strokeWidth="1.6" />
              <rect x="33" y="21" width="8" height="41" fill="var(--ribbon,var(--brand))" />
              <path d="M37 21c-5-10-18-11-16-3 1 4 9 3 16 3zM37 21c5-10 18-11 16-3-1 4-9 3-16 3z" fill="var(--sheet)" stroke="var(--brand)" strokeWidth="1.6" strokeLinejoin="round" />
            </svg>
          </div>
        </section>

        {/* Missed offers — not subscribed and offers went out (push recovery, strategy 1) */}
        {missed && showMissedBanner && (
          <div role="alert" className="sheet note warn">
            <span aria-hidden="true" className="ico" style={{ width: 40, height: 40, background: 'var(--sheet)', color: 'var(--accent-ink)' }}>{I.bell}</span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <p className="t">{notifStatus.missed_count === 1 ? 'Vous avez raté 1 offre' : `Vous avez raté ${notifStatus.missed_count} offres`}</p>
              <p className="d">Activez les notifications pour ne plus rien manquer de <span className="notranslate" translate="no">{shop || 'cette boutique'}</span>.</p>
              <button type="button" className="solid" style={{ marginTop: 10 }} onClick={enableFromBanner}>Activer les notifications</button>
            </div>
            <button type="button" className="close" onClick={() => setShowMissedBanner(false)} aria-label="Fermer"><X size={16} aria-hidden="true" /></button>
          </div>
        )}

        {/* Automatisations: the latest message and its button (a Wallet notification cannot carry one) */}
        {autoMsg && (
          <div className="sheet">
            <div className="note">
              <div style={{ minWidth: 0, flex: 1 }}>
                <p className="t" style={{ fontSize: 15 }}>{autoMsg.title}</p>
                {autoMsg.body && <p className="d">{autoMsg.body}</p>}
              </div>
              {autoMsg.image_url && <img src={autoMsg.image_url} alt="" style={{ width: 64, height: 64, borderRadius: 14, objectFit: 'cover', flex: 'none' }} />}
              <button type="button" className="close" aria-label="Masquer ce message" onClick={() => hideAutoMsg(autoMsg)}><X size={16} aria-hidden="true" /></button>
            </div>
            {autoMsg.button_url && autoMsg.button_label && (
              <a href={autoMsg.button_url} rel="noopener" className="msg-cta">{autoMsg.button_label}</a>
            )}
          </div>
        )}

        <div className="tiles">
          {/* both stay in this page (round 4): the Récompenses tab at its offers, the Parrainage view */}
          <button type="button" className="sheet tile" data-testid="tile-offers" onClick={() => goTab('recompenses', 'wcp-offres')}>
            <span className="ico">{I.ticket}</span>Mes offres exclusives
            {liveOfferCount > 0 && <span className="badge num">{liveOfferCount} en cours</span>}
          </button>
          <button type="button" className="sheet tile" data-testid="tile-share" onClick={() => goTab('parrainage')}>
            <span className="ico">{I.people}</span>Parrainer un proche
          </button>
          {/* the store's button (FidClic super admin, per établissement) — a new tab, or « Lien pas encore ajouté » */}
          {cta.url ? (
            <a href={cta.url} target="_blank" rel="noopener noreferrer" className="sheet tile" data-testid="card-cta">
              <span className="ico">{I.calendar}</span>{cta.label}
            </a>
          ) : (
            <button type="button" className="sheet tile" data-testid="card-cta" onClick={noLink}>
              <span className="ico">{I.calendar}</span>{cta.label}
            </button>
          )}
        </div>

        <section className="sheet acts" aria-labelledby="wcp-acts">
          <div className="ah">
            <h2 id="wcp-acts">{I.pulse}Mes dernières activités</h2>
            <button type="button" className="link" onClick={() => goTab('historique')}>Voir tout {I.chev}</button>
          </div>
          <ActivityRows items={(recent || []).slice(0, 3)} card={card} testId="activity-list" />
          {recent && !recent.some((it) => activityRow(it, card)) && (
            <p className="calm" data-testid="activity-empty">Pas encore d’activité : elle apparaîtra après votre prochaine visite.</p>
          )}
        </section>

        {/* always, with the 4 networks (user, 2026-11-25): one not added says so */}
        <section className="follow" data-testid="follow-us" aria-labelledby="wcp-follow">
          <h2 id="wcp-follow">Suivez-nous</h2>
          <p>Restez informé de nos actualités, nouveautés et offres exclusives !</p>
          <div className="cta">
            {joinUrl
              ? <a href={joinUrl} target="_blank" rel="noopener noreferrer" className="btn">Nous rejoindre {I.chev}</a>
              : <button type="button" className="btn" onClick={noLink}>Nous rejoindre {I.chev}</button>}
            <div className="so">
              {networks.map((n) => (n.url ? (
                <a key={n.network} href={n.url} target="_blank" rel="noopener noreferrer" aria-label={n.label}>
                  <span className={NET_CLASS[n.network]}>{NET[n.network]}</span>
                </a>
              ) : (
                <button key={n.network} type="button" aria-label={n.label} onClick={noLink}>
                  <span className={NET_CLASS[n.network]}>{NET[n.network]}</span>
                </button>
              )))}
            </div>
          </div>
          <div className="hand" aria-hidden="true"><ShopLogo url={card.logo_url} name={shop} className="hl" /></div>
        </section>
      </div>
    </>
  );

  // ─────────────────────────────────────────────────── Récompenses
  const defis = data?.defis || {};
  const programmePanel = (
    <>
      {tabHead('Le programme', backHome)}
      <div className="stack">
        {/* A full card restarts on the next visit; its reward stays valid until handed over */}
        {pending > 0 && (
          <div className="good" data-testid="pending-reward">
            <Gift size={20} aria-hidden="true" style={{ flex: 'none', marginTop: 1 }} />
            <p><strong>{pending > 1 ? `${pending} récompenses à récupérer` : '1 récompense à récupérer'}</strong>
              {card.reward_description ? ` : ${card.reward_description}` : ''}. Présentez votre carte en caisse.</p>
          </div>
        )}
        <section className="sheet sec" aria-labelledby="wcp-prog">
          <h2 id="wcp-prog"><Gift size={18} aria-hidden="true" /> Le programme</h2>
          <div className="kv">
            <p className="k" style={{ margin: 0 }}>Récompense</p>
            <p className="v" style={{ marginBottom: 0 }}>🎁 {card.reward_description || 'Une récompense fidélité'}</p>
            {programmeOf(card) === 'stamps' ? (
              <p className="s" style={{ marginBottom: 0 }}>Débloquée après {stampsTarget} visites — {Math.min(cycleVisits(customer), stampsTarget)} / {stampsTarget} sur cette carte.</p>
            ) : parseInt(card.reward_points, 10) > 0 && (
              // a points card: its reward is reached in points, not in visits (QA R7 F28)
              <p className="s" style={{ marginBottom: 0 }} data-testid="programme-progress">
                Débloquée dès {card.reward_points} points — {Math.min(parseInt(customer.points, 10) || 0, parseInt(card.reward_points, 10))} / {card.reward_points} sur cette carte.
              </p>
            )}
          </div>
          {/* how the card earns, as the shop set it — none on a Tampons card (QA BUG-009 / R7 F28) */}
          {earningRule(card) && (
            <div className="kv" data-testid="programme-earning">
              <p className="k" style={{ margin: 0 }}>Comment gagner</p>
              <p className="v" style={{ marginBottom: 0 }}>{earningRule(card)}</p>
            </div>
          )}
          <div className="kv">
            <p className="k" style={{ margin: 0 }}>Votre statut</p>
            <p className="v" style={{ marginBottom: 0 }}>
              {tier}{' · '}{card.show_points !== false ? `${balanceText(card, customer.points)} · ` : ''}{customer.visits || 0} visite{(customer.visits || 0) > 1 ? 's' : ''}
            </p>
          </div>
        </section>
        {/* « Défi en cours » (Campagnes › Défi): the soonest end first, then what was won */}
        {(defis.running || []).map((x) => (
          <section key={x.id} className="defi" data-testid="defi-running">
            <p className="k" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}><Flame size={16} aria-hidden="true" /> Défi en cours</p>
            <p className="t">{x.title}</p>
            <p className="d">Faites {x.target} visite{x.target > 1 ? 's' : ''}{x.end_date ? ` avant le ${fmtDay(x.end_date)}` : ''}{x.count_mode === 'per_day' ? ' (une par jour)' : ''}{x.reward ? ` · 🎁 ${x.reward}` : ''}</p>
            <div className="bar" role="progressbar" aria-label="Progression du défi" aria-valuemin={0} aria-valuemax={x.target} aria-valuenow={Math.min(x.progress || 0, x.target)}>
              <i style={{ width: `${Math.min(100, ((x.progress || 0) / Math.max(1, x.target)) * 100)}%` }} />
            </div>
            <p className="d num">{Math.min(x.progress || 0, x.target)} / {x.target}{x.days_left != null ? ` · ${x.days_left <= 1 ? 'Dernier jour' : `encore ${x.days_left} jours`}` : ''}</p>
          </section>
        ))}
        {(defis.won || []).map((w) => (
          <section key={w.id} className="defi won" data-testid="defi-won">
            <p className="k" style={{ margin: 0 }}>{w.kind === 'parrainage' ? '🎁 Parrainage' : '🏆 Défi réussi'}</p>
            <p className="t">{w.reward}</p>
            <p className="d">{w.kind === 'parrainage' ? 'Votre récompense de parrainage' : `« ${w.title} »`} — présentez votre carte en caisse{w.expires_at ? `, avant le ${fmtDay(w.expires_at)}` : ''}.</p>
          </section>
        ))}
        <button type="button" className="ghostbtn" onClick={() => goTab('recompenses', 'wcp-offres')}>Voir mes offres {I.chev}</button>
      </div>
    </>
  );

  // ─────────────────────────────────────────────────── Récompenses (« Vos offres », in the page — round 4)
  const offersPanel = (
    <>
      {tabHead(`Vos offres${firstName ? `, ${firstName}` : ''}`)}
      <div className="stack" data-testid="offers-tab">
        <CardOffersContent data={data} barcodeId={barcodeId} onParrainage={() => goTab('parrainage')} />
      </div>
    </>
  );

  // ─────────────────────────────────────────────────── Parrainage (the home tile, the old /partager)
  const sharePanel = (
    <>
      {tabHead('Parrainage', backHome)}
      <div className="stack">
        <CardShareContent barcodeId={barcodeId} qrInk={theme.ink} />
      </div>
    </>
  );

  // ─────────────────────────────────────────────────── Mon compte
  const details = card.details || {};
  const has = (v) => v && String(v).trim().length > 0;
  const compteRows = [
    ['about', details.about], ['hours', details.hours], ['address', details.address || tenant.address],
    ['phone', details.phone || tenant.phone], ['website', details.website || tenant.website],
  ];
  const comptePanel = (
    <>
      {tabHead('Mon compte')}
      <div className="stack">
        <section className="sheet sec" aria-labelledby="wcp-settings">
          <h2 id="wcp-settings"><Settings size={18} aria-hidden="true" /> Paramètres</h2>
          <div className="list">
            <ToggleRow icon={<RefreshCw size={18} aria-hidden="true" />} label="Mise à jour automatique" hint="Met à jour votre carte sans action de votre part"
                       value={prefs.auto_update} onToggle={() => togglePref('auto_update')} disabled={savingPrefs} />
            <ToggleRow icon={<Bell size={18} aria-hidden="true" />} label="Autoriser les notifications" hint="Recevez les nouvelles offres et rappels"
                       value={prefs.push_enabled} onToggle={() => togglePref('push_enabled')} disabled={savingPrefs} />
          </div>
          <button type="button" onClick={testPush} className="ghostbtn" style={{ marginTop: 12 }}>
            <Bell size={15} aria-hidden="true" /> Envoyer une notification test
          </button>
        </section>

        {recentVisit && (
          <section className="sheet sec" aria-labelledby="wcp-review">
            <h2 id="wcp-review"><Star size={18} aria-hidden="true" /> Donner mon avis</h2>
            {reviewThanks ? (
              <div className="good" style={{ display: 'block', textAlign: 'center' }}>
                <p style={{ fontWeight: 700 }}>Merci pour votre avis ! 🙏</p>
                <p style={{ marginTop: 4, fontSize: 13 }}>Votre retour aide <span className="notranslate" translate="no">{shop}</span> à progresser.</p>
                {googleReviewUrl && (
                  <a href={googleReviewUrl} target="_blank" rel="noopener noreferrer" className="solid" style={{ marginTop: 12 }}
                     onClick={() => { publicAPI.googleReviewClick(customer.barcode_id).catch(() => {}); }}>
                    ⭐ Laissez-nous un avis sur Google
                  </a>
                )}
              </div>
            ) : (
              <div>
                <p style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Comment s’est passée votre visite ?</p>
                <p style={{ margin: '2px 0 0', fontSize: 12.5, color: 'var(--muted)' }}>Votre note reste anonyme.</p>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>1</span>
                  <input type="range" min="1" max="10" step="1" value={reviewRating} aria-label="Note sur 10"
                         onChange={(e) => setReviewRating(parseInt(e.target.value, 10))} />
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>10</span>
                </div>
                <p style={{ margin: 0, textAlign: 'center' }}><span className="num" style={{ fontSize: 30, fontWeight: 800, color: 'var(--brand-ink)' }}>{reviewRating}</span><span style={{ fontSize: 14, color: 'var(--muted)' }}>/10</span></p>
                <textarea value={reviewText} onChange={(e) => setReviewText(e.target.value.slice(0, 500))} rows={3} aria-label="Votre commentaire"
                          placeholder="Un mot pour l’équipe ? (optionnel — service, propreté, accueil…)" style={{ marginTop: 8 }} />
                {reviewError && <p style={{ margin: '8px 0 0', fontSize: 12.5, color: '#B42318' }}>{reviewError}</p>}
                <button type="button" disabled={reviewSubmitting} onClick={submitReview} className="solid wide" style={{ marginTop: 12, minHeight: 48 }}>
                  {reviewSubmitting ? 'Envoi…' : 'Envoyer mon avis'}
                </button>
              </div>
            )}
          </section>
        )}

        <section className="sheet sec" aria-labelledby="wcp-about">
          <h2 id="wcp-about"><Store size={18} aria-hidden="true" /> À propos de <span className="notranslate" translate="no">{shop || 'la boutique'}</span></h2>
          <div className="about">
            {has(details.about) && <div><p className="k">À propos</p><p className="v">{details.about}</p></div>}
            {has(details.hours) && <div><p className="k"><Clock size={12} aria-hidden="true" /> Horaires</p><p className="v notranslate" translate="no">{details.hours}</p></div>}
            {has(details.address || tenant.address) && <div><p className="k"><MapPin size={12} aria-hidden="true" /> Adresse</p><p className="v">{details.address || tenant.address}</p></div>}
            {has(details.phone || tenant.phone) && <div><p className="k"><Phone size={12} aria-hidden="true" /> Téléphone</p><a className="v" href={`tel:${details.phone || tenant.phone}`}>{details.phone || tenant.phone}</a></div>}
            {has(details.website || tenant.website) && <div><p className="k"><Globe size={12} aria-hidden="true" /> Site web</p><a className="v" href={details.website || tenant.website} target="_blank" rel="noopener noreferrer">{details.website || tenant.website}</a></div>}
            {(has(details.instagram) || has(details.facebook)) && (
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                {has(details.instagram) && <a className="v" href={details.instagram.startsWith('http') ? details.instagram : `https://instagram.com/${details.instagram.replace('@', '')}`} target="_blank" rel="noopener noreferrer">Instagram : {details.instagram}</a>}
                {has(details.facebook) && <a className="v" href={details.facebook.startsWith('http') ? details.facebook : `https://facebook.com/${details.facebook}`} target="_blank" rel="noopener noreferrer">Facebook : {details.facebook}</a>}
              </div>
            )}
            {(details.custom_sections || []).map((s, i) => (has(s.title) || has(s.body) ? (
              <div key={i}>{has(s.title) && <p className="k">{s.title}</p>}<p className="v">{s.body}</p></div>
            ) : null))}
            {!compteRows.some(([, v]) => has(v)) && (details.custom_sections || []).length === 0 && (
              <p className="calm" style={{ padding: 0 }}>Le commerçant n'a pas encore ajouté de détails.</p>
            )}
          </div>
        </section>

        <section className="sheet sec" aria-labelledby="wcp-rgpd">
          <h2 id="wcp-rgpd"><ShieldCheck size={18} aria-hidden="true" /> Mes données (RGPD)</h2>
          <div className="list">
            <button type="button" onClick={downloadMyData} className="li-row">
              <Download size={18} aria-hidden="true" />
              <span><span className="lt">Télécharger mes données</span><span className="ls">Profil, visites, notifications — fichier JSON</span></span>
            </button>
            <button type="button" onClick={deleteCard} className="li-row">
              <Trash2 size={18} aria-hidden="true" />
              <span><span className="lt">Supprimer la carte</span><span className="ls">Retire la carte ; vos visites restent chez le commerçant</span></span>
            </button>
            <button type="button" onClick={forgetMe} className="li-row danger">
              <XCircle size={18} aria-hidden="true" />
              <span><span className="lt">Supprimer mes données personnelles</span><span className="ls">Effacement définitif et irréversible (droit à l’oubli)</span></span>
            </button>
          </div>
        </section>
        <p className="small notranslate" translate="no">{customer.name}{customer.email ? ` · ${customer.email}` : ''}</p>
      </div>
    </>
  );

  // ─────────────────────────────────────────────────── Historique (the bottom tab, « Voir tout »)
  const historyPanel = (
    <>
      {tabHead('Historique')}
      <div className="stack">
        <section className="sheet acts" aria-label="Toutes mes activités">
          <ActivityRows items={history.items} card={card} testId="history-list" />
          {history.loaded && !history.items.some((it) => activityRow(it, card)) && (
            <p className="calm">Pas encore d’activité : elle apparaîtra après votre prochaine visite.</p>
          )}
          {!history.loaded && <p className="calm">Chargement…</p>}
        </section>
        {history.next && (
          <button type="button" className="ghostbtn" disabled={history.busy} onClick={() => loadHistory(history.next)}>
            {history.busy ? 'Chargement…' : 'Voir plus'}
          </button>
        )}
      </div>
    </>
  );

  const panels = { accueil: home, recompenses: offersPanel, programme: programmePanel, parrainage: sharePanel,
    compte: comptePanel, historique: historyPanel };
  const tabLabel = TAB_DEFS.find((t) => t.key === tab)?.label
    || ({ programme: 'Le programme', parrainage: 'Parrainage' })[tab] || 'Accueil';
  // the lit bottom item: none on the programme and parrainage views
  const lit = navActive(tab);
  const hidden = !lit;

  return (
    <div className="wcp" data-testid="card-page" style={themeVars(theme)}>
      <div className="wcp-col" role="tabpanel" id={`wcp-panel-${tab}`}
            aria-labelledby={hidden ? undefined : `wcp-tab-${tab}`} aria-label={hidden ? tabLabel : undefined}>
        {panels[tab] || home}
      </div>

      <nav className="wcp-nav" aria-label="Ma carte en ligne">
        <div role="tablist" aria-label="Rubriques de la carte">
          {TAB_DEFS.map((t) => (
            <button key={t.key} type="button" role="tab" id={`wcp-tab-${t.key}`}
                    aria-selected={lit === t.key} aria-controls={lit === t.key ? `wcp-panel-${t.key}` : undefined}
                    tabIndex={lit === t.key || (hidden && t.key === 'accueil') ? 0 : -1}
                    onClick={() => goTab(t.key)}
                    onKeyDown={(e) => {
                      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
                      const tabs = TAB_DEFS;
                      const i = tabs.findIndex((x) => x.key === t.key);
                      const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
                      goTab(next.key);
                      setTimeout(() => document.getElementById(`wcp-tab-${next.key}`)?.focus(), 0);
                    }}>
              {t.icon}{t.label}
            </button>
          ))}
        </div>
      </nav>

      {toast && <div role="status" aria-live="polite" className="wcp-toast">{toast}</div>}
      {/* ?wallet=apple from another app: the add is under way (no « Ma carte » tab to show it in) */}
      {appleAdd && (
        <div role="status" aria-live="polite" className="wcp-toast wcp-apple" data-testid="apple-wallet-opening">
          Ajout à Apple Wallet en cours… <a href={appleAdd} className="u">Réessayer</a>
        </div>
      )}

      {/* « Voir l'offre » on the back of the Wallet pass (?offre=) opens that campaign here */}
      {openedNotification && (
        <NotificationDetailModal notification={openedNotification} tenant={tenant} card={card}
                                 customerId={customer.id} onClose={() => setOpenedNotification(null)} />
      )}
    </div>
  );
};

const ToggleRow = ({ icon, label, hint, value, onToggle, disabled }) => (
  <div className="li-row">
    {icon}
    <span style={{ flex: 1, minWidth: 0 }}>
      <span className="lt">{label}</span>
      <span className="ls">{hint}</span>
    </span>
    <button type="button" role="switch" aria-checked={!!value} aria-label={label} onClick={onToggle} disabled={disabled} className="switch-hit">
      <span className="switch" aria-hidden="true" />
    </button>
  </div>
);

// ───────────────────────────────────────────────────────────────────────
// NotificationDetailModal — full-screen-ish modal for one notification.
//
// Why a modal rather than a route: the customer is on their wallet card
// (the most important page on the site for them) and we don't want to
// navigate them away. A modal keeps the card behind it and lets them
// close with a single tap to get back to scanning.
//
// Tracking:
//   • OPEN  → already recorded by the parent's onClick (pixel endpoint)
//   • CLICK → recorded here when the customer taps the CTA link. Uses
//             POST /api/campaigns/{id}/track-click which the existing
//             campaign analytics pipeline already aggregates.
// ───────────────────────────────────────────────────────────────────────
function NotificationDetailModal({ notification, tenant, card, customerId, onClose }) {
  // the card's own button colour (lib/cardTheme, the .wcp variables)
  const accent = 'var(--btn, #B85C38)';
  // Pluck the first URL from the body so we can offer a tappable CTA.
  // Merchants usually paste an offer URL into the message; this surfaces
  // it as a proper button instead of leaving the customer to find it.
  const urlMatch = (notification.body || '').match(/(https?:\/\/[^\s)]+)/);
  const ctaUrl = notification.link || (urlMatch ? urlMatch[0] : null);

  const handleCtaClick = (e) => {
    // Fire the click-tracking endpoint BEFORE navigation. We don't await
    // it — the customer shouldn't have to wait — but we let it fly off
    // so the campaign analytics get the increment.
    try {
      api.post(`/campaigns/${notification.id}/track-click`, null, {
        params: { customer_id: customerId },
      }).catch(() => {});
    } catch (_e) { /* tracking failure must not block the navigation */ }
    // Default <a> behaviour handles the navigation — we don't preventDefault.
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(28,25,23,0.55)',
        zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 16, backdropFilter: 'blur(4px)',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--flc-card, #FFFFFF)', borderRadius: 18, padding: '24px 22px 18px',
          maxWidth: 520, width: '100%', maxHeight: vh(85), overflowY: 'auto',
          boxShadow: '0 32px 80px rgba(0,0,0,0.25)',
        }}
      >
        {/* Header — business name + close button */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 16 }}>
          <div
            style={{
              width: 40, height: 40, borderRadius: 10, flexShrink: 0,
              background: accent, color: 'var(--btn-ink, #fff)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontWeight: 700, fontSize: 16,
            }}
          >
            {(tenant?.name || '?').charAt(0).toUpperCase()}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{ margin: 0, fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#8D857D' }}>
              {tenant?.name || 'Notification'}
            </p>
            <h3 style={{ margin: '4px 0 0', fontFamily: 'Cormorant Garamond, serif', fontSize: 22, fontWeight: 700, color: '#171412', lineHeight: 1.2 }}>
              {notification.title}
            </h3>
            {notification.sent_at && (
              <p style={{ margin: '4px 0 0', fontSize: 11, color: '#8D857D' }}>
                {new Date(notification.sent_at).toLocaleString('fr-FR', { dateStyle: 'long', timeStyle: 'short' })}
              </p>
            )}
          </div>
          <button onClick={onClose} aria-label="Fermer" type="button"
                  style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: '#6B6359', padding: 4 }}>
            <X size={20} />
          </button>
        </div>

        {/* Image — if the campaign attached a hero image */}
        {notification.image_url && (
          <img
            src={notification.image_url}
            alt=""
            style={{ width: '100%', borderRadius: 12, marginBottom: 14, display: 'block' }}
          />
        )}

        {/* Full body — preserves line breaks the merchant typed */}
        <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.55, color: '#171412', whiteSpace: 'pre-wrap' }}>
          {notification.body}
        </p>

        {/* CTA button — if there's a link, surface it prominently */}
        {ctaUrl && (
          <a
            href={ctaUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={handleCtaClick}
            style={{
              display: 'block', textAlign: 'center', marginTop: 18,
              padding: '12px 18px', borderRadius: 99,
              background: accent, color: 'var(--btn-ink, #fff)',
              fontWeight: 700, fontSize: 14, textDecoration: 'none',
            }}
          >
            Voir l'offre →
          </a>
        )}

        <p style={{ margin: '16px 0 0', fontSize: 10.5, color: '#A8A29E', textAlign: 'center' }}>
          ID campagne : {notification.id}
        </p>
      </div>
    </div>
  );
}

/**
 * Whose card is this, on this phone? (user, 2026-10-08: scanning a friend's
 * QR opened the friend's card — it must open mine, or the signup form when I
 * have no card at that shop, or no longer have it in Wallet.)
 *
 * The server decides (api/services/card_owner.py) from the owner key in the
 * link and the cards this phone holds (lib/myCards). Nothing of the card is
 * loaded before it answers « card ».
 */
// The « whose card » question gets this long; then the owner's link (or this
// phone's own key) opens the card without the answer.
const WHOSE_TIMEOUT = 10_000;

// index.html starts a watchdog on every /card/ page: if the app never gets
// this far, it reloads once, then shows a plain « Réessayer » screen.
function cardAlive() {
  try { window.__fcCardOk = true; } catch (_e) { /* */ }
  try { sessionStorage.removeItem('fidclic:card-watchdog'); } catch (_e) { /* private mode */ }
}

const CardOwnerGate = () => {
  const { barcodeId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [view, setView] = useState(null);       // null: asking · 'card' · 'retry'
  const [attempt, setAttempt] = useState(0);
  // /card/{bc}/offres and /card/{bc}/partager (old links): this page, on that view
  const canonical = cardViewPath(location.pathname, location.search);
  useEffect(() => {
    if (canonical) return undefined;
    let alive = true;
    const bc = String(barcodeId || '').toUpperCase();
    const params = new URLSearchParams(location.search);
    const k = params.get('k') || '';
    setView(null);
    // the app is up: index.html's watchdog stands down (2026-11-26 — one
    // iPhone's Chrome stopped before this question was ever asked)
    cardAlive();
    // ?vue=commerce: opened from the dashboard (« Voir sa carte »), the shop's
    // team sees the card; a camera scan never asks for that view.
    // Never waited on for ever: past WHOSE_TIMEOUT the owner's link opens the card.
    api.post(`/card/${bc}/whose`, { k: k || null, mine: readMine(), shop: params.get('vue') === 'commerce' },
      { timeout: WHOSE_TIMEOUT })
      .then(({ data }) => {
        if (!alive) return;
        forgetMine(data?.drop || []);
        if (data?.key) addMine(bc, data.key);
        if (k || params.has('_r')) {           // the key is kept on the phone, not in the address bar
          params.delete('k');
          params.delete('_r');                 // the watchdog's retry mark
          const q = params.toString();
          navigate({ pathname: location.pathname, search: q ? `?${q}` : '', hash: location.hash }, { replace: true });
        }
        const wanted = tabFromSearch(params.toString());
        if (data?.view === 'own' && data.barcode_id) {
          // this phone's own card — on the view the link asked for (offers, parrainage, programme)
          const keep = ['recompenses', 'parrainage', 'programme'].includes(wanted) ? `?onglet=${wanted}` : '';
          window.location.replace(`/card/${data.barcode_id}${keep}`);
        } else if (data?.view === 'join' && data.slug && wanted === 'parrainage') {
          // « 🎁 Partagez la carte » on the back of the Wallet card carries no owner
          // key (anyone may be sent that text): a phone that cannot open the card
          // still gets the public share page it always had — the card's public QR
          // and the apps, nothing of the card's data (wallet_passes.share_url)
          setView('share');
        } else if (data?.view === 'join' && data.slug) {
          // a friend's card: the signup form, filed as « Parrainage », never « QR en magasin »
          // …of the friend's establishment (an account with several: one card per store)
          window.location.replace(`/join/${data.slug}${data.store ? `/${encodeURIComponent(data.store)}` : ''}?p=${encodeURIComponent(data.parrain || bc)}`);
        } else {
          setView('card');
        }
      })
      .catch((e) => {
        if (!alive) return;
        // no answer (timeout, network): the link's own key goes with the card's
        // requests — the server still checks it on every one of them
        if (k && !e?.response) addMine(bc, k);
        // an unknown card: the view says « Carte introuvable »; otherwise only
        // this phone's own card opens without the server's answer
        setView(e?.response?.status === 404 || keyOf(bc) || k ? 'card' : 'retry');
      });
    return () => { alive = false; };
  }, [barcodeId, attempt, canonical]); // eslint-disable-line react-hooks/exhaustive-deps

  if (canonical) return <Navigate to={`${canonical}${location.hash || ''}`} replace />;
  if (view === 'card') return <CardView />;
  if (view === 'share') {
    return (
      <React.Suspense fallback={<div className="min-h-screen bg-[#FAFAF8]" />}>
        <CardSharePage />
      </React.Suspense>
    );
  }
  if (view === 'retry') {
    return (
      <div className="min-h-screen bg-[#FAFAF8] flex items-center justify-center px-4">
        <div className="bg-white rounded-2xl p-8 border border-[#E9E5E0] max-w-md text-center">
          <p className="text-[#171412] font-semibold mb-2">Connexion impossible</p>
          <p className="text-[#57504A] text-sm">Vérifiez votre connexion internet, puis réessayez.</p>
          <button type="button" onClick={() => setAttempt((n) => n + 1)}
                  className="mt-5 rounded-xl bg-[#171412] px-5 py-2.5 text-sm font-semibold text-white">Réessayer</button>
        </div>
      </div>
    );
  }
  return <div className="min-h-screen bg-[#FAFAF8] flex items-center justify-center text-[#57504A]">Chargement de votre carte…</div>;
};

export default CardOwnerGate;
