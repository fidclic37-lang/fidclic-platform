import { vh } from '../lib/fit';
import React, { useEffect, useRef, useState } from 'react';
import { useParams, Link, useNavigate, useLocation } from 'react-router-dom';
import { readMine, addMine, forgetMine, keyOf } from '../lib/myCards';
import { QRCodeSVG } from 'qrcode.react';
import { cardUrl } from '../components/PremiumLoyaltyCard';
import Code128Barcode from '../components/Code128Barcode';
import { Bell, RefreshCw, Trash2, Gift, Sparkles, ChevronRight, Store, MapPin, Phone, Globe, CheckCircle2, XCircle, Clock, ChevronDown, X, Download, ShieldCheck, Star, Settings, Share2, Smartphone, Printer } from 'lucide-react';
import api, { publicAPI } from '../lib/api';
import { ensureSubscribed, unsubscribe as unsubscribePush, isSupported as isPushSupported } from '../lib/webpush';
import InstallPwaPrompt from '../components/InstallPwaPrompt';
import GeoConsentCard from '../components/GeoConsentCard';
import PremiumLoyaltyCard from '../components/PremiumLoyaltyCard';
import WalletPassPreview from '../components/WalletPassPreview';
import WalletButtons from '../components/WalletButtons';
import TierBadge from '../components/TierBadge';
import { cycleVisits, rewardsPending } from '../lib/cardCycle';

// ---------------------------------------------------------------------------
// Element / stamp rendering — mirrors the owner-side designer
// ---------------------------------------------------------------------------
const ELEMENT_FALLBACK_TEXT = {
  business_name: '{business_name}',
  customer_name: '{name}',
  tier: 'Statut : {tier}',
  points: '{points} pts',
  birthday: '🎂 {birthday}',
  offer_banner: '{offer_title}',
  reward_hint: 'Encore {points_remaining} points pour une récompense',
  logo: '',
};

const substitute = (text, ctx) => {
  if (!text) return '';
  return String(text)
    .replace(/\{name\}/g, ctx.name || '')
    .replace(/\{first_name\}/g, (ctx.name || '').split(' ')[0] || '')
    .replace(/\{tier\}/g, (ctx.tier || '').charAt(0).toUpperCase() + (ctx.tier || '').slice(1))
    .replace(/\{points\}/g, ctx.points ?? 0)
    .replace(/\{points_remaining\}/g, ctx.points_remaining ?? '')
    .replace(/\{birthday\}/g, ctx.birthday || '')
    .replace(/\{business_name\}/g, ctx.business_name || '')
    .replace(/\{offer_title\}/g, ctx.offer_title || '');
};

const RenderElement = ({ id, cfg, ctx, tpl }) => {
  if (!cfg || cfg.visible === false) return null;
  const text = substitute(cfg.text ?? ELEMENT_FALLBACK_TEXT[id] ?? '', ctx);
  if (id === 'logo' && tpl.logo_url) {
    return (
      <img
        src={tpl.logo_url}
        alt=""
        className="absolute rounded-lg object-cover border-2 border-white/20 pointer-events-none"
        style={{
          left: `${cfg.x_pct}%`, top: `${cfg.y_pct}%`,
          transform: 'translate(-50%, -50%)',
          width: `${Math.max(cfg.font_size * 3, 44)}px`,
          height: `${Math.max(cfg.font_size * 3, 44)}px`,
        }}
      />
    );
  }
  if (!text) return null;
  return (
    <div
      className="absolute pointer-events-none"
      style={{
        left: `${cfg.x_pct}%`, top: `${cfg.y_pct}%`,
        transform: 'translate(-50%, -50%)',
        fontFamily: cfg.font_family || 'Inter',
        fontSize: `${cfg.font_size || 14}px`,
        fontWeight: cfg.font_weight || 'normal',
        fontStyle: cfg.font_style || 'normal',
        textDecoration: cfg.text_decoration || 'none',
        color: cfg.color || '#FFFFFF',
        textAlign: cfg.align || 'left',
        whiteSpace: 'nowrap', maxWidth: '92%',
      }}
    >{text}</div>
  );
};

const StampVisual = ({ style, filled, total, accent }) => {
  if (style === 'none') return null;
  if (style === 'bar') {
    return (
      <div>
        <div className="text-[10px] uppercase tracking-widest opacity-70 mb-1">Carte de fidélité</div>
        <div className="h-3 bg-white/20 rounded-full overflow-hidden">
          <div className="h-full rounded-full" style={{ width: `${(filled / total) * 100}%`, background: accent }} />
        </div>
        <div className="text-xs opacity-80 mt-1">{filled} / {total} visites</div>
      </div>
    );
  }
  const items = [...Array(total)];
  const cols = Math.min(total, 10);
  const renderOne = (i) => {
    const on = i < filled;
    if (style === 'hexagon') return (
      <svg key={i} viewBox="0 0 100 100" className="w-8 h-8 drop-shadow-sm" style={{ fill: on ? accent : 'transparent', stroke: accent, strokeWidth: 4 }}>
        <polygon points="50,5 95,25 95,75 50,95 5,75 5,25" />
      </svg>
    );
    if (style === 'circles') return <div key={i} className="w-7 h-7 rounded-full border-2" style={{ background: on ? accent : 'transparent', borderColor: accent }} />;
    if (style === 'classic_dots') return <div key={i} className="w-4 h-4 rounded-full" style={{ background: on ? accent : 'rgba(255,255,255,0.2)' }} />;
    if (style === 'squares') return <div key={i} className="w-7 h-7 rounded border-2" style={{ background: on ? accent : 'transparent', borderColor: accent }} />;
    if (style === 'stars') return (
      <svg key={i} viewBox="0 0 24 24" className="w-7 h-7" style={{ fill: on ? accent : 'transparent', stroke: accent, strokeWidth: 1.5 }}>
        <polygon points="12,2 15,9 22,9 17,14 19,22 12,18 5,22 7,14 2,9 9,9" />
      </svg>
    );
    return null;
  };
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="text-[10px] uppercase tracking-widest opacity-70">Carte de fidélité</div>
      <div className="grid gap-2 justify-items-center" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, auto))` }}>
        {items.map((_, i) => renderOne(i))}
      </div>
    </div>
  );
};

// Tiny error boundary scoped to the wallet card render. Without this,
// any thrown error inside <PremiumLoyaltyCard /> bubbles up and Vercel's
// runtime turns it into a blank page — terrible debugging UX for the
// owner who tries the URL on a phone.
class WalletCardErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('[wallet card] render crash:', error, info?.componentStack);
  }
  render() {
    if (this.state.error) {
      return (
        <div className="bg-white rounded-2xl p-6 border border-[#E9E5E0] max-w-md mx-auto text-center my-10">
          <XCircle className="mx-auto text-[#B85C38] mb-3" size={32} />
          <p className="text-[#171412] font-semibold mb-1">La carte n'a pas pu s'afficher</p>
          <p className="text-[#57504A] text-sm">
            Erreur de rendu :{' '}
            <code style={{ fontSize: 11 }}>{String(this.state.error?.message || this.state.error)}</code>
          </p>
          <p className="text-[#8D857D] text-xs mt-2">
            Ouvrez la console du navigateur pour la trace complète.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

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
  // Two tabs only now (offers + program). The old "news" tab was a
  // duplicate of offers — same backend campaigns shown under a different
  // name. Merged into a single "Offres & messages" feed on the offers
  // tab so customers (and merchants) don't see the same items twice.
  // ?onglet=offres|programme — where the iOS 27 tiles under the Wallet pass land.
  // The menu's open sheet: program | review | about | settings (2026-10-10
  // redesign). The Wallet « Programme » tile (?onglet=programme) opens « Le
  // programme » right away.
  const [sheet, setSheet] = useState(() => {
    try { return new URLSearchParams(window.location.search).get('onglet') === 'programme' ? 'program' : null; }
    catch (_e) { return null; }
  });
  // the pass at the phone's width (WalletPassPreview draws at a fixed px width)
  const [passW, setPassW] = useState(() => Math.min(420, Math.max(280, (typeof window !== 'undefined' ? window.innerWidth : 390) - 32)));
  useEffect(() => {
    const fit = () => setPassW(Math.min(420, Math.max(280, window.innerWidth - 32)));
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, []);
  const [toast, setToast] = useState(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  // Forces the InstallPwaPrompt to ignore the "dismissed recently" memory.
  // We flip this on when the user tries to enable push on iOS without having
  // installed the PWA first — the install flow is the actual fix.
  const [showInstallHelp, setShowInstallHelp] = useState(false);
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
    if (!barcodeId) return;
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
  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2600);
  };

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
              setShowInstallHelp(true);
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
  const activeOffer = card.active_offer || {};
  const stampsTarget = card.reward_threshold || 10;



  const recentVisit = (() => {
    const last = customer.last_visit_date ? new Date(customer.last_visit_date) : null;
    return !!last && (Date.now() - last.getTime()) / 86400000 <= 14;
  })();
  const pending = rewardsPending(customer);
  const shareCard = async () => {
    // the card's public link (no owner key): a friend who opens it gets the signup
    const url = `${window.location.origin}/card/${barcodeId}`;
    try {
      if (navigator.share) {
        await navigator.share({ title: `${tenant?.name || 'FidClic'} — ma carte de fidélité`, url });
      } else {
        await navigator.clipboard.writeText(url);
        showToast('Lien copié — collez-le où vous voulez');
      }
    } catch (_e) { /* cancelled */ }
  };
  const homeHelp = () => {
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
    showToast(isIOS
      ? 'Dans Safari : bouton Partager, puis « Sur l’écran d’accueil ».'
      : 'Dans le menu du navigateur : « Ajouter à l’écran d’accueil ».');
  };
  // the shop's view (?vue=commerce, from the dashboard) stays on through « Mes
  // offres » and back — without it the page took the browser's own card for
  // the shop and opened that one instead (QA F34, 2026-10-11)
  const shopView = new URLSearchParams(window.location.search).get('vue') === 'commerce';
  const menu = [
    { key: 'offers', icon: Sparkles, label: 'Mes offres', hint: mergedFeed.length ? `${mergedFeed.length} en cours` : 'Les offres de la boutique', to: `/card/${barcodeId}/offres${shopView ? '?vue=commerce' : ''}` },
    { key: 'program', icon: Gift, label: 'Le programme', hint: card.reward_description ? `${card.reward_description} après ${stampsTarget} visites` : 'Récompenses et points' },
    recentVisit && { key: 'review', icon: Star, label: 'Donner mon avis', hint: 'Sur votre dernière visite — anonyme' },
    { key: 'about', icon: Store, label: `À propos de ${tenant.name || 'la boutique'}`, hint: 'Adresse, horaires, contact' },
    { key: 'settings', icon: Settings, label: 'Paramètres', hint: 'Notifications, mes données, supprimer ma carte' },
  ].filter(Boolean);

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#F4F7FC] to-[#EEF3FB] font-['Inter',system-ui,sans-serif]">
      <div className="mx-auto max-w-[460px] px-4 pb-12 pt-6">
        {/* Missed offers — the customer is not subscribed and offers went out (push recovery, strategy 1) */}
        {notifStatus && !notifStatus.subscribed && notifStatus.missed_count > 0 && showMissedBanner && (
          <div role="alert" className="mb-4 flex items-start gap-3 rounded-2xl border border-[#F5D58A] bg-[#FFF8E6] p-3.5">
            <span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#FDEBB8] text-[18px]">🔔</span>
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-bold text-[#0B1C3F]">
                {notifStatus.missed_count === 1 ? 'Vous avez raté 1 offre' : `Vous avez raté ${notifStatus.missed_count} offres`}
              </p>
              <p className="mt-0.5 text-[12.5px] leading-snug text-[#475569]">Activez les notifications pour ne plus rien manquer de {tenant?.name || 'cette boutique'}.</p>
              <button type="button"
                      onClick={async () => {
                        const slug = data?.tenant?.slug;
                        if (!slug || !barcodeId) return;
                        try {
                          const r = await ensureSubscribed(slug, barcodeId);
                          if (r && r.ok) { showToast('Notifications activées — merci !'); setNotifStatus({ subscribed: true, missed_count: 0 }); }
                          else if (r?.status === 'permission_denied') showToast('Activez les notifications dans les paramètres de votre navigateur.');
                          else showToast("Impossible d'activer les notifications.");
                        } catch { showToast("Impossible d'activer les notifications."); }
                      }}
                      className="mt-2 rounded-lg bg-[#F59E0B] px-3 py-1.5 text-[12.5px] font-semibold text-white">
                Activer les notifications
              </button>
            </div>
            <button type="button" onClick={() => setShowMissedBanner(false)} aria-label="Fermer" className="p-1 text-[#94A3B8]"><X size={16} /></button>
          </div>
        )}

        {/* Automatisations: the latest message and its action button (a Wallet
            notification cannot carry a button — tapping it opens this card) */}
        {(() => {
          const am = geoMsg || data?.auto_message;
          if (!am || !am.title || hiddenMsg === am.log_id) return null;
          return (
            <div className="mb-4 overflow-hidden rounded-2xl border border-[#D6E4FF] bg-white shadow-[0_18px_40px_-30px_rgba(20,99,255,.6)]">
              <div className="flex items-start gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <p className="text-[15px] font-bold leading-snug text-[#0B1C3F]">{am.title}</p>
                  {am.body && <p className="mt-0.5 text-[13.5px] leading-snug text-[#334155]">{am.body}</p>}
                </div>
                {am.image_url && <img src={am.image_url} alt="" className="h-16 w-16 shrink-0 rounded-xl object-cover" />}
                <button type="button" aria-label="Masquer ce message" className="-mr-1 -mt-1 p-1 text-[#94A3B8]"
                        onClick={() => { setHiddenMsg(am.log_id); setGeoMsg(null); try { localStorage.setItem('fidclic:auto_msg_hidden', am.log_id); } catch { /* private mode */ } }}>
                  <X size={16} /></button>
              </div>
              {am.button_url && am.button_label && (
                <a href={am.button_url} rel="noopener"
                   className="block border-t border-[#E6EEFB] bg-[#F1F5FF] py-3 text-center text-[14.5px] font-semibold text-[#1463FF]">{am.button_label}</a>
              )}
            </div>
          );
        })()}

        {/* The card itself — the pass as it sits in Apple / Google Wallet, in the shop's colours */}
        <WalletCardErrorBoundary>
          <div className="flex justify-center">
            <div className="overflow-hidden rounded-[18px] shadow-[0_24px_50px_-28px_rgba(15,23,42,.6)]" style={{ width: passW }}>
              <WalletPassPreview customer={customer} tenant={tenant} card={card} width={passW} />
            </div>
          </div>
        </WalletCardErrorBoundary>

        {/* A full card restarts on the next visit; its reward stays valid until handed over */}
        {pending > 0 && (
          <div className="mt-4 flex items-start gap-3 rounded-2xl border border-[#BFE6D3] bg-[#EAF7F0] p-4">
            <Gift className="mt-0.5 h-5 w-5 shrink-0 text-[#0F8B58]" aria-hidden="true" />
            <p className="text-[14px] leading-snug text-[#0B3D27]">
              <strong>{pending > 1 ? `${pending} récompenses à récupérer` : '1 récompense à récupérer'}</strong>
              {card.reward_description ? ` : ${card.reward_description}` : ''}. Présentez votre carte en caisse.
            </p>
          </div>
        )}

        <div className="mt-5 space-y-3">
          {/* Native wallets — shown once the certificates are configured */}
          <WalletButtons barcodeId={barcodeId} onError={showToast} />
          <div className="grid grid-cols-3 gap-2">
            {[[Share2, 'Partager / copier', shareCard], [Smartphone, 'Sur l’écran d’accueil', homeHelp], [Printer, 'Imprimer', () => window.print()]].map(([Icon, label, fn]) => (
              <button key={label} type="button" onClick={fn}
                      className="flex flex-col items-center gap-1.5 rounded-2xl bg-white px-2 py-3 text-[12.5px] font-medium text-[#0B1C3F] shadow-[0_6px_18px_-14px_rgba(15,23,42,.35)] hover:bg-[#F8FAFC]">
                <Icon size={18} aria-hidden="true" /> {label}
              </button>
            ))}
          </div>
        </div>

        {/* The rest, one tap away */}
        <nav aria-label="Ma carte" className="mt-5 overflow-hidden rounded-3xl bg-white shadow-[0_10px_30px_-22px_rgba(15,23,42,.35)]">
          {menu.map(({ key, icon: Icon, label, hint, to }, i) => {
            const inner = (
              <>
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Icon size={18} /></span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px] font-semibold text-[#0B1C3F]">{label}</span>
                  <span className="block truncate text-[12.5px] text-[#64748B]">{hint}</span>
                </span>
                <ChevronRight size={18} className="shrink-0 text-[#94A3B8]" />
              </>
            );
            const cls = `flex w-full items-center gap-3 px-4 py-3.5 text-left hover:bg-[#F8FAFC] ${i ? 'border-t border-[#EEF2F7]' : ''}`;
            return to
              ? <Link key={key} to={to} className={cls}>{inner}</Link>
              : <button key={key} type="button" onClick={() => setSheet(key)} className={cls}>{inner}</button>;
          })}
        </nav>

        <p className="mt-3 text-center text-[11.5px] text-[#94A3B8]">La carte se met à jour après chaque visite, dans n’importe quel navigateur.</p>

        {/* iOS needs the card on the home screen before it can receive notifications */}
        <InstallPwaPrompt
          context="card"
          force={showInstallHelp}
          onInstalled={() => {
            if (data?.tenant?.slug && barcodeId) ensureSubscribed(data.tenant.slug, barcodeId).catch(() => {});
            setShowInstallHelp(false);
          }}
        />
        <GeoConsentCard customerId={customer.id} tenantSlug={tenant.slug} barcodeId={barcodeId} />
      </div>

      {sheet === 'program' && (
        <Sheet title="Le programme" onClose={() => setSheet(null)}>
          <div className="space-y-3 text-[14px]">
            <div className="rounded-2xl bg-[#F8FAFC] p-4">
              <p className="text-[11.5px] font-semibold uppercase tracking-wide text-[#64748B]">Récompense</p>
              <p className="mt-1 font-semibold text-[#0B1C3F]">🎁 {card.reward_description || 'Une récompense fidélité'}</p>
              <p className="mt-1 text-[13px] text-[#475569]">Débloquée après {stampsTarget} visites — {Math.min(cycleVisits(customer), stampsTarget)} / {stampsTarget} sur cette carte.</p>
            </div>
            {/* a Tampons card earns no points (QA BUG-009): no « points par visite » */}
            {!!card.points_per_visit && card.show_points !== false && (
              <div className="rounded-2xl bg-[#F8FAFC] p-4">
                <p className="text-[11.5px] font-semibold uppercase tracking-wide text-[#64748B]">Points par visite</p>
                <p className="mt-1 font-semibold text-[#0B1C3F]">+{card.points_per_visit} pts à chaque passage</p>
              </div>
            )}
            <div className="rounded-2xl bg-[#F8FAFC] p-4">
              <p className="text-[11.5px] font-semibold uppercase tracking-wide text-[#64748B]">Votre statut</p>
              <p className="mt-1 font-semibold text-[#0B1C3F]">
                {({ bronze: 'Bronze', silver: 'Argent', gold: 'Or', vip: 'VIP' })[String(customer.tier || 'bronze').toLowerCase()] || customer.tier}
                {' · '}{card.show_points !== false ? `${customer.points || 0} pts · ` : ''}{customer.visits || 0} visite{(customer.visits || 0) > 1 ? 's' : ''}
              </p>
            </div>
          </div>
        </Sheet>
      )}

      {sheet === 'review' && (
        <Sheet title="Donner mon avis" onClose={() => setSheet(null)}>
          {reviewThanks ? (
            <div className="rounded-2xl bg-[#EAF7F0] p-4 text-center">
              <p className="text-[15px] font-semibold text-[#0B3D27]">Merci pour votre avis ! 🙏</p>
              <p className="mt-1 text-[13px] text-[#0B3D27]/80">Votre retour aide {tenant.name} à progresser.</p>
              {googleReviewUrl && (
                <a href={googleReviewUrl} target="_blank" rel="noopener noreferrer"
                   onClick={() => { publicAPI.googleReviewClick(customer.barcode_id).catch(() => {}); }}
                   className="mt-3 inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2 text-[14px] font-semibold text-[#0B1C3F] shadow-sm ring-1 ring-black/5">
                  ⭐ Laissez-nous un avis sur Google
                </a>
              )}
            </div>
          ) : (
            <div>
              <p className="text-[14px] font-semibold text-[#0B1C3F]">Comment s’est passée votre visite ?</p>
              <p className="text-[12.5px] text-[#64748B]">Votre note reste anonyme.</p>
              <div className="mt-3 flex items-center gap-2">
                <span className="w-4 text-[12px] text-[#64748B]">1</span>
                <input type="range" min="1" max="10" step="1" value={reviewRating}
                       onChange={(e) => setReviewRating(parseInt(e.target.value, 10))} className="flex-1 accent-[#2F6BFF]" aria-label="Note sur 10" />
                <span className="w-6 text-[12px] text-[#64748B]">10</span>
              </div>
              <p className="mt-1 text-center"><span className="text-[30px] font-bold text-[#2F6BFF]">{reviewRating}</span><span className="text-[14px] text-[#64748B]">/10</span></p>
              <textarea value={reviewText} onChange={(e) => setReviewText(e.target.value.slice(0, 500))} rows={3}
                        placeholder="Un mot pour l’équipe ? (optionnel — service, propreté, accueil…)"
                        className="mt-2 w-full resize-none rounded-xl border border-[#E2E8F0] bg-white p-3 text-[16px]" />
              {reviewError && <p className="mt-2 text-[12.5px] text-[#B91C1C]">{reviewError}</p>}
              <button type="button" disabled={reviewSubmitting}
                      onClick={async () => {
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
                      }}
                      className="mt-3 h-12 w-full rounded-2xl bg-[#1463FF] text-[15px] font-semibold text-white disabled:opacity-60">
                {reviewSubmitting ? 'Envoi…' : 'Envoyer mon avis'}
              </button>
            </div>
          )}
        </Sheet>
      )}

      {sheet === 'about' && <DetailsDrawer tenant={tenant} card={card} onClose={() => setSheet(null)} />}

      {sheet === 'settings' && (
        <Sheet title="Paramètres" onClose={() => setSheet(null)}>
          <div className="divide-y divide-[#EEF2F7] rounded-2xl bg-[#F8FAFC]">
            <ToggleRow icon={<RefreshCw size={18} />} label="Mise à jour automatique" hint="Met à jour votre carte sans action de votre part"
                       value={prefs.auto_update} onToggle={() => togglePref('auto_update')} disabled={savingPrefs} />
            <ToggleRow icon={<Bell size={18} />} label="Autoriser les notifications" hint="Recevez les nouvelles offres et rappels"
                       value={prefs.push_enabled} onToggle={() => togglePref('push_enabled')} disabled={savingPrefs} />
          </div>
          <button type="button"
                  onClick={async () => {
                    try {
                      const { data: d = {} } = await api.post(`/card/${customer.barcode_id}/test-push`);
                      if (d.sent > 0) showToast(`Notification envoyée à ${d.sent} appareil${d.sent > 1 ? 's' : ''}.`);
                      else if (d.error === 'no_subscription') showToast('Activez d’abord les notifications ci-dessus.');
                      else if (d.error === 'vapid_not_configured') showToast('Notifications non configurées (contactez le commerçant).');
                      else showToast(`Échec : ${d.error || 'inconnu'}`);
                    } catch (e) { showToast('Erreur réseau lors du test.'); }
                  }}
                  className="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl border border-[#2F6BFF] py-3 text-[14px] font-semibold text-[#2F6BFF]">
            <Bell size={15} /> Envoyer une notification test
          </button>
          <p className="mb-2 mt-6 flex items-center gap-1.5 text-[11.5px] font-semibold uppercase tracking-wide text-[#64748B]"><ShieldCheck size={13} /> Mes données (RGPD)</p>
          <div className="divide-y divide-[#EEF2F7] rounded-2xl bg-[#F8FAFC]">
            <button type="button" onClick={downloadMyData} className="flex w-full items-center gap-3 p-4 text-left">
              <Download size={18} className="shrink-0 text-[#2F6BFF]" />
              <span><span className="block text-[14px] font-medium text-[#0B1C3F]">Télécharger mes données</span><span className="block text-[12px] text-[#64748B]">Profil, visites, notifications — fichier JSON</span></span>
            </button>
            <button type="button" onClick={deleteCard} className="flex w-full items-center gap-3 p-4 text-left">
              <Trash2 size={18} className="shrink-0 text-[#B45309]" />
              <span><span className="block text-[14px] font-medium text-[#0B1C3F]">Supprimer la carte</span><span className="block text-[12px] text-[#64748B]">Retire la carte ; vos visites restent chez le commerçant</span></span>
            </button>
            <button type="button" onClick={forgetMe} className="flex w-full items-center gap-3 p-4 text-left">
              <XCircle size={18} className="shrink-0 text-[#B91C1C]" />
              <span><span className="block text-[14px] font-medium text-[#B91C1C]">Supprimer mes données personnelles</span><span className="block text-[12px] text-[#64748B]">Effacement définitif et irréversible (droit à l’oubli)</span></span>
            </button>
          </div>
          <p className="mt-4 text-center text-[12px] text-[#94A3B8]">{customer.name}{customer.email ? ` · ${customer.email}` : ''}</p>
        </Sheet>
      )}

      {toast && (
        <div role="status" className="fixed bottom-6 left-1/2 z-[60] max-w-[90vw] -translate-x-1/2 rounded-2xl bg-[#0B1C3F] px-5 py-2.5 text-center text-[13.5px] text-white shadow-lg">
          {toast}
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

// A bottom sheet for the menu's rows (Le programme, Avis, Paramètres).
function Sheet({ title, onClose, children }) {
  return (
    <div role="dialog" aria-modal="true" aria-label={title} onClick={onClose}
         className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/50 sm:items-center sm:p-4">
      <div onClick={(e) => e.stopPropagation()}
           className="max-h-[88vh] w-full max-w-[520px] overflow-y-auto rounded-t-3xl bg-white p-5 shadow-2xl sm:rounded-3xl">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-[19px] font-bold text-[#0B1C3F]">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Fermer" className="rounded-full p-1.5 text-[#64748B] hover:bg-[#F1F5F9]"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

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
  const accent = card?.primary_color || '#B85C38';
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
              background: accent, color: 'white',
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
              background: accent, color: 'white',
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

// ---------------------------------------------------------------------------
// Wallet pass — applies the modern card-template schema
// ---------------------------------------------------------------------------
const WalletPass = ({ customer, tenant, card, activeOffer, onOpenDetails }) => {
  const design = card.design || {};
  const primary = card.primary_color || design.primary_color || '#171412';
  const secondary = card.secondary_color || design.secondary_color || '#B85C38';
  const accent = card.accent_color || design.accent_color || '#D4A574';
  const textColor = design.text_color || '#FFFFFF';

  const elements = card.elements || {};
  const stampStyle = card.stamp_style || 'hexagon';
  const showMeter = card.show_meter !== false;
  const promotion = card.promotion || { enabled: false };
  const stampsTarget = card.reward_threshold || 10;
  const stampsEarned = Math.min(cycleVisits(customer), stampsTarget);   // THIS card (lib/cardCycle)
  const pointsRemaining = Math.max(0, stampsTarget - stampsEarned);

  const ctx = {
    name: customer.name, tier: customer.tier,
    points: customer.points, points_remaining: pointsRemaining,
    birthday: customer.birthday, business_name: tenant.name,
    offer_title: activeOffer?.active ? activeOffer.title : '',
  };

  const hasElements = elements && Object.keys(elements).some(k => elements[k]?.visible !== false);

  return (
    <>
      <div className="rounded-2xl shadow-xl overflow-hidden relative" style={{ background: `linear-gradient(${design.gradient_direction || '135deg'}, ${primary} 0%, ${secondary} 100%)`, color: textColor }}>
        {/* Promotion mode — replaces the header region */}
        {promotion.enabled ? (
          <div className="p-6">
            <div className="rounded-xl px-5 py-6 text-center relative overflow-hidden" style={{ background: promotion.background_color || accent, color: promotion.text_color || '#FFFFFF', backgroundImage: promotion.image_url ? `url(${promotion.image_url})` : undefined, backgroundSize: 'cover', backgroundPosition: 'center' }}>
              {promotion.image_url && <div className="absolute inset-0 bg-black/40" />}
              <div className="relative">
                <p className="text-xs uppercase tracking-widest opacity-80 mb-1">Avantage exclusif fidélité</p>
                <p className="text-3xl font-black leading-tight" style={{ fontFamily: 'Cormorant Garamond' }}>{promotion.title || 'Promotion'}</p>
                {promotion.subtitle && <p className="text-sm opacity-90 mt-1 font-semibold">{promotion.subtitle}</p>}
                {promotion.body && <p className="text-xs opacity-80 mt-3 leading-snug whitespace-pre-wrap">{promotion.body}</p>}
                {promotion.link && (
                  <a href={promotion.link} target="_blank" rel="noreferrer" className="mt-4 inline-block bg-white/20 backdrop-blur text-sm font-bold px-5 py-2 rounded-full hover:bg-white/30 transition-colors">
                    {promotion.link_label || 'En savoir plus'}
                  </a>
                )}
                {promotion.expires_at && (
                  <p className="text-[10px] opacity-70 mt-3 flex items-center justify-center gap-1">
                    <Clock size={10} /> expire le {new Date(promotion.expires_at).toLocaleDateString('fr-FR')}
                  </p>
                )}
              </div>
            </div>
          </div>
        ) : hasElements ? (
          // Free-form element layout
          <div className="relative h-[160px] border-b border-white/10">
            {Object.keys(elements).filter(id => ['logo', 'business_name', 'customer_name'].includes(id)).map(id => (
              <RenderElement key={id} id={id} cfg={elements[id]} ctx={ctx} tpl={card} />
            ))}
          </div>
        ) : (
          // Legacy fallback header
          <div className="px-6 pt-6 flex items-center justify-between">
            <div className="flex items-center gap-3">
              {card.logo_url ? (
                <img src={card.logo_url} alt={tenant.name} className="w-11 h-11 rounded-lg object-cover border border-white/30" />
              ) : (
                <div className="w-11 h-11 rounded-lg flex items-center justify-center font-bold text-lg" style={{ background: accent, color: secondary }}>
                  {tenant.name?.charAt(0) || '?'}
                </div>
              )}
              <div>
                <p className="font-bold text-lg leading-none">{tenant.name}</p>
                <p className="text-xs opacity-80 mt-0.5">Programme de Fidélité</p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wider opacity-70">Membre depuis</p>
              <p className="text-xs font-semibold">
                {customer.member_since ? new Date(customer.member_since).toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' }) : '—'}
              </p>
            </div>
          </div>
        )}

        {/* Active offer banner — only when not already in promotion mode */}
        {!promotion.enabled && activeOffer?.active && activeOffer?.title && (
          <div className="mx-6 mt-5 rounded-xl p-4 text-center" style={{ background: accent, color: secondary }}>
            <p className="text-2xl font-black tracking-tight uppercase leading-tight" style={{ fontFamily: 'Cormorant Garamond' }}>{activeOffer.title}</p>
            {activeOffer.description && <p className="text-xs mt-1 opacity-90">{activeOffer.description}</p>}
          </div>
        )}

        {/* Stamps */}
        <div className="px-6 py-5">
          <StampVisual style={stampStyle} filled={stampsEarned} total={stampsTarget} accent={accent} />
          {showMeter && stampStyle !== 'none' && (
            <div className="mt-3">
              <div className="flex justify-between text-[11px] opacity-80 mb-1">
                <span>Progression récompense</span><span>{stampsEarned}/{stampsTarget}</span>
              </div>
              <div className="h-1.5 rounded-full overflow-hidden bg-white/20">
                <div className="h-full rounded-full" style={{ width: `${(stampsEarned / stampsTarget) * 100}%`, background: accent }} />
              </div>
              <p className="text-[11px] opacity-80 mt-2">🎁 {card.reward_description}</p>
            </div>
          )}
        </div>

        {/* Element bottom strip: points / tier / birthday / reward_hint */}
        {hasElements && (
          <div className="relative h-[110px] border-t border-white/10">
            {Object.keys(elements).filter(id => ['points', 'tier', 'birthday', 'reward_hint'].includes(id)).map(id => (
              <RenderElement key={id} id={id} cfg={elements[id]} ctx={ctx} tpl={card} />
            ))}
          </div>
        )}

        {/* QR ONLY. The 1D Code 128 barcode that used to stack below
            this block was removed per owner spec — modern POS scanners
            read QR fine, and one code looks much cleaner. To bring back
            the 1D fallback (for old laser scanners), restore
            <Code128Barcode value={customer.barcode_id} ... /> here. */}
        <div className="px-6 pb-5 pt-2">
          {/* On the card's own colour, with its ink — no white plate. The
              quiet zone the plate used to give the code is now marginSize. */}
          <div className="mx-auto inline-block">
            <QRCodeSVG value={cardUrl(customer.barcode_id)} size={200} level="M"
                       marginSize={4} bgColor={primary} fgColor={textColor} />
          </div>
          <p className="mt-2 font-mono text-xs opacity-90 text-center">{customer.barcode_id}</p>
        </div>

        {/* Counter row — always shown as quick glance info */}
        {!hasElements && (
          <div className="px-6 pb-4 grid grid-cols-3 gap-3 text-center">
            <div className="bg-white/10 rounded-lg py-2">
              <p className="text-xs opacity-80">Visites</p>
              <p className="font-bold text-lg">{customer.visits}</p>
            </div>
            <div className="bg-white/10 rounded-lg py-2">
              <p className="text-xs opacity-80">Points</p>
              <p className="font-bold text-lg">{customer.points}</p>
            </div>
            <div className="bg-white/10 rounded-lg py-2">
              <p className="text-xs opacity-80">Statut</p>
              <p className="font-bold text-sm uppercase">{customer.tier}</p>
            </div>
          </div>
        )}

        {/* Tap-to-expand call-to-action */}
        <button
          onClick={onOpenDetails}
          className="w-full flex items-center justify-center gap-1.5 py-2.5 text-[11px] uppercase tracking-widest border-t border-white/10 hover:bg-white/5 transition-colors"
          style={{ color: textColor }}
        >
          Touchez pour plus de détails <ChevronDown size={12} />
        </button>
      </div>

      {/* Save / share actions — see MyWalletCardPage for rationale. */}
      <div className="grid grid-cols-3 gap-2 mt-5">
        <button
          onClick={async (e) => {
            e.stopPropagation();
            try {
              if (navigator.share) {
                await navigator.share({ title: 'Ma carte de fidélité', url: window.location.href });
              } else {
                await navigator.clipboard.writeText(window.location.href);
                alert('Lien copié.');
              }
            } catch (_e) { /* user cancelled */ }
          }}
          className="bg-[#171412] text-white py-3 rounded-xl font-medium text-sm"
        >
          📤 Partager
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
            alert(isIOS
              ? "Touchez le bouton Partager dans Safari, puis 'Sur l'écran d'accueil'."
              : "Menu Chrome → 'Ajouter à l'écran d'accueil'.");
          }}
          className="bg-[#B85C38] text-white py-3 rounded-xl font-medium text-sm"
        >
          📱 Accueil
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); window.print(); }}
          className="bg-white border border-[#E9E5E0] py-3 rounded-xl font-medium text-sm"
          style={{ color: '#171412' }}
        >
          🖨️ Imprimer
        </button>
      </div>

      {/* Push notification preview */}
      <div className="mt-6 bg-white/70 backdrop-blur rounded-xl p-4 border border-[#E9E5E0]">
        <div className="flex items-center gap-2 mb-2">
          <Sparkles size={16} className="text-[#B85C38]" />
          <h3 className="text-sm font-semibold text-[#171412]">Aperçu de la notification push</h3>
        </div>
        <div className="bg-[#171412]/5 rounded-lg p-3 flex gap-3">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm" style={{ background: primary, color: textColor }}>
            {tenant.name?.charAt(0)}
          </div>
          <div className="flex-1">
            <p className="text-[11px] font-semibold text-[#171412]">{tenant.name}</p>
            <p className="text-xs text-[#57504A] leading-snug">
              {promotion.enabled
                ? `${promotion.title} — ${promotion.subtitle || 'Nouvelle offre disponible'}`
                : activeOffer?.active
                ? `${activeOffer.title} — ${activeOffer.description}`
                : 'Nouvelle offre disponible dans votre carte de fidélité'}
            </p>
            <p className="text-[10px] text-[#8D857D] mt-0.5">maintenant</p>
          </div>
        </div>
      </div>
    </>
  );
};

// ---------------------------------------------------------------------------
// Details drawer — opened when customer taps "pour plus de détails"
// ---------------------------------------------------------------------------
const DetailsDrawer = ({ tenant, card, onClose }) => {
  const details = card.details || {};
  const has = (v) => v && String(v).trim().length > 0;
  return (
    <div className="fixed inset-0 bg-black/50 flex items-end sm:items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white w-full sm:max-w-lg rounded-t-3xl sm:rounded-3xl max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="sticky top-0 bg-white border-b border-[#E9E5E0] flex items-center justify-between px-5 py-3">
          <h2 className="font-['Playfair_Display'] text-xl font-bold text-[#171412]">À propos de {tenant.name}</h2>
          <button onClick={onClose} className="p-2 hover:bg-[#F5F5F4] rounded-lg"><X size={18} /></button>
        </div>
        <div className="p-5 space-y-4 text-sm">
          {has(details.about) && (
            <div>
              <p className="text-xs font-bold text-[#8D857D] uppercase tracking-wider mb-1">À propos</p>
              <p className="text-[#171412] whitespace-pre-wrap leading-relaxed">{details.about}</p>
            </div>
          )}
          {has(details.hours) && (
            <div>
              <p className="text-xs font-bold text-[#8D857D] uppercase tracking-wider mb-1 flex items-center gap-1"><Clock size={12} /> Horaires</p>
              <p className="text-[#171412] whitespace-pre-wrap">{details.hours}</p>
            </div>
          )}
          {has(details.address || tenant.address) && (
            <div>
              <p className="text-xs font-bold text-[#8D857D] uppercase tracking-wider mb-1 flex items-center gap-1"><MapPin size={12} /> Adresse</p>
              <p className="text-[#171412]">{details.address || tenant.address}</p>
            </div>
          )}
          {has(details.phone || tenant.phone) && (
            <div>
              <p className="text-xs font-bold text-[#8D857D] uppercase tracking-wider mb-1 flex items-center gap-1"><Phone size={12} /> Téléphone</p>
              <a href={`tel:${details.phone || tenant.phone}`} className="text-[#B85C38] underline">{details.phone || tenant.phone}</a>
            </div>
          )}
          {has(details.website || tenant.website) && (
            <div>
              <p className="text-xs font-bold text-[#8D857D] uppercase tracking-wider mb-1 flex items-center gap-1"><Globe size={12} /> Site web</p>
              <a href={details.website || tenant.website} target="_blank" rel="noreferrer" className="text-[#B85C38] underline break-all">{details.website || tenant.website}</a>
            </div>
          )}
          {(has(details.instagram) || has(details.facebook)) && (
            <div className="flex gap-3">
              {has(details.instagram) && <a href={details.instagram.startsWith('http') ? details.instagram : `https://instagram.com/${details.instagram.replace('@','')}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-[#B85C38] text-sm">Instagram: {details.instagram}</a>}
              {has(details.facebook) && <a href={details.facebook.startsWith('http') ? details.facebook : `https://facebook.com/${details.facebook}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-[#B85C38] text-sm">Facebook: {details.facebook}</a>}
            </div>
          )}
          {(details.custom_sections || []).map((s, i) => has(s.title) || has(s.body) ? (
            <div key={i}>
              {has(s.title) && <p className="text-xs font-bold text-[#8D857D] uppercase tracking-wider mb-1">{s.title}</p>}
              <p className="text-[#171412] whitespace-pre-wrap leading-relaxed">{s.body}</p>
            </div>
          ) : null)}
          {!has(details.about) && !has(details.hours) && !has(details.address) && !has(details.phone) && !has(details.website) && (details.custom_sections || []).length === 0 && (
            <p className="text-sm text-[#8D857D] italic text-center py-6">Le commerçant n'a pas encore ajouté de détails.</p>
          )}
        </div>
      </div>
    </div>
  );
};

const ToggleRow = ({ icon, label, hint, value, onToggle, disabled }) => (
  <div className="flex items-center gap-3 p-4">
    <div className="text-[#2F6BFF]">{icon}</div>
    <div className="flex-1">
      <p className="font-medium text-sm text-[#171412]">{label}</p>
      <p className="text-xs text-[#57504A]">{hint}</p>
    </div>
    <button
      onClick={onToggle}
      disabled={disabled}
      className={`relative w-11 h-6 shrink-0 rounded-full transition-colors ${value ? 'bg-[#2F6BFF]' : 'bg-[#CBD5E1]'} ${disabled ? 'opacity-60' : ''}`}
      aria-pressed={value}
    >
      <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${value ? 'translate-x-5' : 'translate-x-0.5'}`} />
    </button>
  </div>
);

const TabBtn = ({ active, onClick, label, count }) => (
  <button
    onClick={onClick}
    className={`flex-1 py-3 text-xs font-semibold uppercase tracking-wider transition-colors ${active ? 'bg-white text-[#B85C38] border-b-2 border-[#B85C38]' : 'text-[#8D857D] hover:text-[#171412]'}`}
  >
    {label}{count !== undefined ? ` (${count})` : ''}
  </button>
);


/**
 * Whose card is this, on this phone? (user, 2026-10-08: scanning a friend's
 * QR opened the friend's card — it must open mine, or the signup form when I
 * have no card at that shop, or no longer have it in Wallet.)
 *
 * The server decides (api/services/card_owner.py) from the owner key in the
 * link and the cards this phone holds (lib/myCards). Nothing of the card is
 * loaded before it answers « card ».
 */
const CardOwnerGate = () => {
  const { barcodeId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [view, setView] = useState(null);       // null: asking · 'card' · 'retry'
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    const bc = String(barcodeId || '').toUpperCase();
    const params = new URLSearchParams(location.search);
    const k = params.get('k') || '';
    setView(null);
    // ?vue=commerce: opened from the dashboard (« Voir sa carte »), the shop's
    // team sees the card; a camera scan never asks for that view
    api.post(`/card/${bc}/whose`, { k: k || null, mine: readMine(), shop: params.get('vue') === 'commerce' })
      .then(({ data }) => {
        if (!alive) return;
        forgetMine(data?.drop || []);
        if (data?.key) addMine(bc, data.key);
        if (k) {                               // the key is kept on the phone, not in the address bar
          params.delete('k');
          const q = params.toString();
          navigate({ pathname: location.pathname, search: q ? `?${q}` : '', hash: location.hash }, { replace: true });
        }
        if (data?.view === 'own' && data.barcode_id) {
          window.location.replace(`/card/${data.barcode_id}`);
        } else if (data?.view === 'join' && data.slug) {
          // a friend's card: the signup form, filed as « Parrainage », never « QR en magasin »
          window.location.replace(`/join/${data.slug}?p=${encodeURIComponent(data.parrain || bc)}`);
        } else {
          setView('card');
        }
      })
      .catch((e) => {
        if (!alive) return;
        // an unknown card: the view says « Carte introuvable »; otherwise only
        // this phone's own card opens without the server's answer
        setView(e?.response?.status === 404 || keyOf(bc) || k ? 'card' : 'retry');
      });
    return () => { alive = false; };
  }, [barcodeId, attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  if (view === 'card') return <CardView />;
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
