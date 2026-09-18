import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { QRCodeSVG } from 'qrcode.react';
import Code128Barcode from '../components/Code128Barcode';
import { Bell, RefreshCw, Trash2, Gift, Sparkles, ChevronRight, Store, MapPin, Phone, Globe, CheckCircle2, XCircle, Clock, ChevronDown, X, Download, ShieldCheck } from 'lucide-react';
import api, { publicAPI } from '../lib/api';
import { ensureSubscribed, unsubscribe as unsubscribePush, isSupported as isPushSupported } from '../lib/webpush';
import InstallPwaPrompt from '../components/InstallPwaPrompt';
import GeoConsentCard from '../components/GeoConsentCard';
import PremiumLoyaltyCard from '../components/PremiumLoyaltyCard';
import WalletPassPreview from '../components/WalletPassPreview';
import TierBadge from '../components/TierBadge';

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

const MyWalletCardPage = () => {
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
  const [tab, setTab] = useState('offers'); // offers | program
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
      link.setAttribute('href', `/api/manifest/${barcodeId}`);
      // Remember which card the customer is using on this device.
      // App boot (main.jsx) reads this key to deep-link standalone PWA
      // launches that landed on "/" back to /card/<barcodeId>.
      try { localStorage.setItem('fidelitour:last_card', barcodeId); } catch (_e) {}
      return () => {
        if (original) link.setAttribute('href', original);
      };
    }
  }, [barcodeId]);

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
        const msg = status === 404
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
    fetch(`/api/card/${encodeURIComponent(barcodeId)}/notification-status`)
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
  // logged and shown as a toast. Rate-limited on the server side by the
  // tenant's geo_cooldown_days.
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
              showToast(`📍 ${res.data.title || 'Vous êtes juste à côté !'}`);
            }
          } catch (_e) { /* best-effort; ignore */ }
        },
        () => { /* user-denied or timeout — silent */ },
        { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 }
      );
    }).catch(() => {});
    return () => { ignored = true; };
  }, [data?.customer?.id]);

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

  if (loading) {
    return <div className="min-h-screen bg-[#FAFAF8] flex items-center justify-center text-[#57504A]">Chargement de votre carte…</div>;
  }
  if (err) {
    return (
      <div className="min-h-screen bg-[#FAFAF8] flex items-center justify-center">
        <div className="bg-white rounded-2xl p-8 border border-[#E9E5E0] max-w-md text-center">
          <XCircle className="mx-auto text-[#B85C38] mb-3" size={40} />
          <p className="text-[#171412] font-semibold mb-2">Carte introuvable</p>
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



  return (
    <div className="min-h-screen bg-[#FAFAF8] font-['Manrope'] py-10 px-4">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <Link to="/" className="text-[#B85C38] text-sm">← Retour</Link>
          <TierBadge tier={customer.tier} size="sm" />
        </div>

        {/* ─── Strategy 1 — Missed-offers banner ────────────────────────
            Shows when customer is NOT subscribed to push AND has missed
            ≥1 campaign in the last 30 days. Tap → triggers browser
            permission prompt. Dismissable for this session. */}
        {notifStatus && !notifStatus.subscribed && notifStatus.missed_count > 0 && showMissedBanner && (
          <div
            style={{
              marginBottom: 18,
              padding: '14px 16px',
              borderRadius: 12,
              background: 'linear-gradient(135deg, hsl(42 78% 52% / .12), rgb(184 92 56 / .08))',
              border: '1px solid hsl(42 78% 52% / .35)',
              display: 'flex',
              alignItems: 'flex-start',
              gap: 12,
            }}
            role="alert"
          >
            <div style={{
              flexShrink: 0, width: 40, height: 40, borderRadius: 10,
              background: 'hsl(42 78% 52% / .20)', color: 'hsl(32 80% 35%)',
              display: 'grid', placeItems: 'center', fontSize: 20,
            }}>
              🔔
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ margin: 0, fontSize: 14, fontWeight: 700, color: '#171412' }}>
                {notifStatus.missed_count === 1
                  ? "Vous avez raté 1 offre exclusive"
                  : `Vous avez raté ${notifStatus.missed_count} offres exclusives`}
              </p>
              <p style={{ margin: '2px 0 10px', fontSize: 12.5, color: '#57504A', lineHeight: 1.45 }}>
                Activez les notifications pour ne plus rien manquer de {tenant?.name || 'cette boutique'}.
              </p>
              <button
                type="button"
                onClick={async () => {
                  const slug = data?.tenant?.slug;
                  if (!slug || !barcodeId) return;
                  try {
                    const r = await ensureSubscribed(slug, barcodeId);
                    if (r && r.ok) {
                      showToast('Notifications activées — merci !');
                      setNotifStatus({ subscribed: true, missed_count: 0 });
                    } else if (r?.status === 'permission_denied') {
                      showToast('Activez les notifications dans les paramètres de votre navigateur.');
                    } else {
                      showToast("Impossible d'activer les notifications.");
                    }
                  } catch {
                    showToast("Impossible d'activer les notifications.");
                  }
                }}
                style={{
                  background: 'linear-gradient(135deg, hsl(32 80% 48%), hsl(38 80% 42%))',
                  color: '#FFFFFF', border: 'none', borderRadius: 8,
                  padding: '8px 14px', fontSize: 12.5, fontWeight: 600,
                  cursor: 'pointer', fontFamily: 'inherit',
                  boxShadow: '0 6px 14px -6px hsl(32 80% 48% / .55)',
                }}
              >
                Activer les notifications
              </button>
            </div>
            <button
              type="button"
              onClick={() => setShowMissedBanner(false)}
              aria-label="Fermer"
              style={{
                flexShrink: 0, background: 'transparent', border: 'none',
                color: '#8D857D', cursor: 'pointer', padding: 4,
                fontSize: 16,
              }}
            >
              ×
            </button>
          </div>
        )}

        <div className="grid lg:grid-cols-[1fr,360px] gap-8">
          {/* LEFT: Wallet card.
              Single source of truth — PremiumLoyaltyCard renders here AND in
              Card Designer's preview. What the patron sees while designing is
              literally the same component the customer sees on their phone. */}
          <section>
            <WalletCardErrorBoundary>
              {/* Wallet templates render the pkpass-FAITHFUL card — the same
                  component the designer previews, real Apple Wallet geometry.
                  The interim PWA-styled render (WalletCard) is gone at the
                  owner's request: the merchant launches with real passes, and
                  this page must show exactly that. Legacy templates keep the
                  old render until they opt in. */}
              {card?.layout_style === 'wallet' ? (
                <div style={{ maxWidth: 375, width: '100%' }}>
                  <WalletPassPreview customer={customer} tenant={tenant} card={card} width={375} />
                </div>
              ) : (
                <PremiumLoyaltyCard customer={customer} tenant={tenant} card={card} />
              )}
            </WalletCardErrorBoundary>

            {/* Save / share actions — the previous "Add to Apple/Google Wallet"
                buttons were fake because real .pkpass generation needs a paid
                Apple Developer cert. Until that's set up, give the customer
                three actions that actually work today. */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-5">
              <button
                onClick={async () => {
                  try {
                    if (navigator.share) {
                      await navigator.share({
                        title: `${tenant?.name || 'FidéliTour'} — ma carte de fidélité`,
                        text: `Ma carte de fidélité ${tenant?.name || 'FidéliTour'}`,
                        url: window.location.href,
                      });
                    } else {
                      await navigator.clipboard.writeText(window.location.href);
                      showToast('Lien copié — collez-le où vous voulez');
                    }
                  } catch (_e) { /* user cancelled, ignore */ }
                }}
                className="bg-[#171412] text-white py-3 rounded-xl font-medium text-sm hover:opacity-90 transition"
              >
                📤 Partager / copier
              </button>
              <button
                onClick={() => {
                  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
                  showToast(isIOS
                    ? "Touchez le bouton Partager dans Safari, puis 'Sur l'écran d'accueil'."
                    : "Menu Chrome → 'Ajouter à l'écran d'accueil'.");
                }}
                className="bg-[#B85C38] text-white py-3 rounded-xl font-medium text-sm hover:opacity-90 transition"
              >
                📱 Sur l'écran d'accueil
              </button>
              <button
                onClick={() => window.print()}
                className="bg-white text-[#171412] py-3 rounded-xl font-medium text-sm border border-[#E9E5E0] hover:bg-[#FAFAF8] transition"
              >
                🖨️ Imprimer
              </button>
            </div>
            <p className="text-[10px] text-[#8D857D] text-center mt-2">
              💡 La carte fonctionne dans n'importe quel navigateur. Apple Wallet / Google Wallet natifs nécessitent un compte développeur payant — disponibles sur demande.
            </p>

            {/* PWA install prompt — quietly invites the customer to install
                this card to their home screen. On iOS this is the only way to
                receive push notifications, so the prompt becomes a hard
                prerequisite for the Bell toggle below. */}
            <InstallPwaPrompt
              context="card"
              force={showInstallHelp}
              onInstalled={() => {
                // After install, retry push subscription so iOS picks it up
                // immediately on next launch.
                if (data?.tenant?.slug && barcodeId) {
                  ensureSubscribed(data.tenant.slug, barcodeId).catch(() => {});
                }
                setShowInstallHelp(false);
              }}
            />

            {/* Geolocation consent — explicit pre-prompt with a clear "why".
                Renders only if the customer hasn't already granted location.
                After grant, we silently update prefs.geo_enabled = true so the
                proximity-push backend can address them. */}
            <GeoConsentCard
              customerId={customer.id}
              tenantSlug={tenant.slug}
              barcodeId={barcodeId}
            />

            {/* Push notification preview */}
            <div className="mt-6 bg-white/70 backdrop-blur rounded-xl p-4 border border-[#E9E5E0]">
              <div className="flex items-center gap-2 mb-2">
                <Sparkles size={16} className="text-[#B85C38]" />
                <h3 className="text-sm font-semibold text-[#171412]">Aperçu de la notification push</h3>
              </div>
              <div className="bg-[#171412]/5 rounded-lg p-3 flex gap-3">
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm"
                  style={{
                    background: card?.primary_color || '#B85C38',
                    color: '#FFFFFF',
                  }}
                >
                  {tenant.name?.charAt(0)}
                </div>
                <div className="flex-1">
                  <p className="text-[11px] font-semibold text-[#171412]">{tenant.name}</p>
                  <p className="text-xs text-[#57504A] leading-snug">
                    {activeOffer?.active
                      ? `${activeOffer.title} — ${activeOffer.description}`
                      : 'Nouvelle offre disponible dans votre carte de fidélité'}
                  </p>
                  <p className="text-[10px] text-[#8D857D] mt-0.5">maintenant</p>
                </div>
              </div>
            </div>
          </section>

          {/* RIGHT: Settings + offers panel */}
          <aside className="bg-white rounded-2xl border border-[#E9E5E0] shadow-sm overflow-hidden">
            <div className="p-5 border-b border-[#E9E5E0]">
              <h2 className="font-['Cormorant_Garamond'] text-2xl font-bold ft-gradient-text-slow">Mon Programme de Fidélité</h2>
              <p className="text-xs text-[#57504A] mt-1">{customer.name} · {customer.email}</p>
            </div>

            {/* Toggle list */}
            <div className="divide-y divide-[#E9E5E0]">
              <ToggleRow
                icon={<RefreshCw size={18} />}
                label="Mise à jour automatique"
                hint="Met à jour votre carte sans action de votre part"
                value={prefs.auto_update}
                onToggle={() => togglePref('auto_update')}
                disabled={savingPrefs}
              />
              <ToggleRow
                icon={<Bell size={18} />}
                label="Autoriser les notifications"
                hint="Recevez les nouvelles offres et rappels"
                value={prefs.push_enabled}
                onToggle={() => togglePref('push_enabled')}
                disabled={savingPrefs}
              />
              {/* Self-service push test. Hitting POST /api/card/<bc>/test-push
                  fires a "FidéliTour — test push ✓" notification to all of
                  this customer's subscribed devices. Surfaces the actual
                  failure reason in a toast (no_subscription, vapid_not_configured,
                  endpoint expired, etc) so the customer can debug without
                  needing the owner to send a campaign. */}
              <div className="p-4 bg-[#F5F4F1] border-t border-[#E9E5E0]">
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      const res = await api.post(`/card/${customer.barcode_id}/test-push`);
                      const d = res.data || {};
                      if (d.sent > 0) {
                        showToast(`Push envoyé à ${d.sent} appareil${d.sent > 1 ? 's' : ''}. Regardez votre écran de verrouillage.`);
                      } else if (d.error === 'no_subscription') {
                        showToast("Notifications pas encore activées — basculez le bouton ci-dessus puis réessayez.");
                      } else if (d.error === 'vapid_not_configured') {
                        showToast("Serveur non configuré pour les notifications (VAPID).");
                      } else {
                        showToast(`Échec: ${d.error || 'inconnu'} (${d.subs_total || 0} abonnement${(d.subs_total || 0) > 1 ? 's' : ''})`);
                      }
                    } catch (e) {
                      showToast('Erreur réseau lors du test push.');
                    }
                  }}
                  className="w-full inline-flex items-center justify-center gap-2 py-2.5 rounded-lg bg-white border border-[#B85C38] text-[#B85C38] font-semibold text-sm hover:bg-[#B85C38] hover:text-white transition-colors"
                >
                  <Bell size={14} />
                  Envoyer une notification test
                </button>
                <p className="text-[10px] text-[#8D857D] mt-1.5 text-center">
                  Vérifie que les notifications atteignent bien votre téléphone.
                </p>
              </div>
              <button
                onClick={deleteCard}
                className="w-full text-left p-4 flex items-center gap-3 hover:bg-[#FFF4F1] transition-colors text-[#B85C38]"
              >
                <Trash2 size={18} />
                <div>
                  <p className="font-medium text-sm">Supprimer la carte</p>
                  <p className="text-xs opacity-80">Retire la carte de votre wallet</p>
                </div>
              </button>

              {/* ─── RGPD — Confidentialité ─────────────────────────────
                  Self-service data rights: export (Art. 15/20) and full
                  erasure (Art. 17). Both barcode-keyed, no login needed —
                  same auth model as the rest of the card page. */}
              <div className="p-4 bg-[#F8F6F1]">
                <p className="text-[10px] font-bold uppercase tracking-widest text-[#8D857D] mb-3 flex items-center gap-1.5">
                  <ShieldCheck size={12} /> Confidentialité (RGPD)
                </p>
                <button
                  onClick={downloadMyData}
                  className="w-full text-left py-2.5 flex items-center gap-3 text-[#171412] hover:text-[#B85C38] transition-colors"
                >
                  <Download size={16} className="shrink-0" />
                  <div>
                    <p className="font-medium text-sm">Télécharger mes données</p>
                    <p className="text-xs text-[#8D857D]">Profil, visites, notifications — fichier JSON</p>
                  </div>
                </button>
                <button
                  onClick={forgetMe}
                  className="w-full text-left py-2.5 flex items-center gap-3 text-[#9B2C2C] hover:opacity-80 transition-opacity"
                >
                  <XCircle size={16} className="shrink-0" />
                  <div>
                    <p className="font-medium text-sm">Supprimer mes données personnelles</p>
                    <p className="text-xs opacity-70">Effacement définitif et irréversible (droit à l'oubli)</p>
                  </div>
                </button>
              </div>
            </div>

            {/* Rate your visit — only shown right after a visit (<= 14 days). */}
            {(() => {
              const lastVisit = customer.last_visit_date ? new Date(customer.last_visit_date) : null;
              const recentVisit = lastVisit && (Date.now() - lastVisit.getTime()) / 86400000 <= 14;
              if (!recentVisit) return null;
              if (reviewThanks) {
                return (
                  <div className="m-3 rounded-xl border border-[#4A5D23]/40 bg-[#e8f3e5] p-4 text-center">
                    <p className="text-sm font-semibold text-[#2d5016]">Merci pour votre avis ! 🙏</p>
                    <p className="text-xs text-[#2d5016]/80 mt-1">Votre retour aide {tenant.name} à progresser.</p>
                  </div>
                );
              }
              return (
                <div className="m-3 rounded-xl border border-[#E3A869]/40 bg-[#F6E9E2] p-4">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-sm font-bold text-[#171412]">Comment s'est passée votre visite ?</p>
                    <span className="text-xs text-[#96431F]">Votre note reste anonyme</span>
                  </div>
                  <div className="mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-[#57504A] w-4">1</span>
                      <input
                        type="range"
                        min="1"
                        max="10"
                        step="1"
                        value={reviewRating}
                        onChange={(e) => setReviewRating(parseInt(e.target.value, 10))}
                        className="flex-1 accent-[#B85C38]"
                      />
                      <span className="text-xs text-[#57504A] w-6">10</span>
                    </div>
                    <p className="text-center mt-1">
                      <span className="text-3xl font-bold text-[#B85C38]">{reviewRating}</span>
                      <span className="text-sm text-[#57504A]">/10</span>
                    </p>
                  </div>
                  <textarea
                    value={reviewText}
                    onChange={(e) => setReviewText(e.target.value.slice(0, 500))}
                    placeholder="Un mot pour l'équipe ? (optionnel — service, propreté, accueil…)"
                    rows={2}
                    className="w-full text-sm border border-[#E9E5E0] rounded p-2 bg-white resize-none"
                  />
                  {reviewError && (
                    <p className="text-xs text-red-600 mt-2">{reviewError}</p>
                  )}
                  <button
                    type="button"
                    disabled={reviewSubmitting}
                    onClick={async () => {
                      try {
                        setReviewSubmitting(true);
                        setReviewError(null);
                        await publicAPI.submitReview({
                          customer_id: customer.id,
                          barcode_id: customer.barcode_id,
                          rating: reviewRating,
                          text: reviewText,
                          visit_id: customer.last_visit_id || undefined,
                          branch_id: customer.branch_id || undefined,
                        });
                        setReviewThanks(true);
                        setReviewText('');
                      } catch (e) {
                        setReviewError(e?.response?.data?.detail || 'Impossible d\'envoyer votre avis.');
                      } finally {
                        setReviewSubmitting(false);
                      }
                    }}
                    className="mt-3 w-full bg-[#B85C38] text-white py-2 rounded-lg font-semibold text-sm disabled:opacity-50"
                  >
                    {reviewSubmitting ? 'Envoi…' : 'Envoyer mon avis'}
                  </button>
                </div>
              );
            })()}

            {/* Tabs — Offres now combines the old offers + news lists into
                one chronological feed. The old "News" tab was a duplicate
                of the same campaigns shown under offers, which confused
                both customers and merchants. */}
            <div className="flex border-t border-[#E9E5E0] bg-[#FAFAF8]">
              <TabBtn active={tab === 'offers'}  onClick={() => setTab('offers')} label="Offres" count={mergedFeed.length} />
              <TabBtn active={tab === 'program'} onClick={() => setTab('program')} label="Programme" />
            </div>

            <div className="p-4 max-h-[420px] overflow-y-auto space-y-3">
              {/* Single unified feed — standing offers + recent campaigns
                  in chronological order, deduplicated. Every campaign-kind
                  item is tappable and opens the detail modal (firing the
                  pixel open-tracking endpoint). The standing card-template
                  offer is rendered non-clickable because it has no
                  campaign id to attach analytics to. */}
              {tab === 'offers' && (mergedFeed.length === 0 ? (
                <p className="text-sm text-[#8D857D] text-center py-8">Aucune offre ni message pour le moment.</p>
              ) : mergedFeed.map(item => {
                const isClickable = item.kind === 'campaign' && item.id;
                const Wrapper = isClickable ? 'button' : 'div';
                return (
                  <Wrapper
                    key={item.id}
                    {...(isClickable ? {
                      type: 'button',
                      onClick: () => {
                        setOpenedNotification({
                          id: item.id,
                          title: item.title,
                          body: item.body || item.description || '',
                          image_url: item.image_url,
                          link: item.link,
                          sent_at: item.sent_at,
                        });
                        try {
                          api.get(`/campaigns/${item.id}/pixel/${customer.id}.png`).catch(() => {});
                        } catch (_e) { /* tracking failure must not block the open */ }
                      },
                    } : {})}
                    className={`w-full text-left rounded-lg border border-[#E9E5E0] p-3 bg-white ${isClickable ? 'hover:bg-[#FFF4F1] transition-colors cursor-pointer' : ''}`}
                  >
                    <div className="flex items-start gap-3">
                      <Gift size={18} className="text-[#B85C38] mt-0.5 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold text-[#171412] text-sm">{item.title}</p>
                        <p className="text-xs text-[#57504A] mt-0.5 line-clamp-2">{item.description || item.body}</p>
                        {item.sent_at && item.kind === 'campaign' && (
                          <p className="text-[10px] text-[#8D857D] mt-1">
                            {new Date(item.sent_at).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })}
                          </p>
                        )}
                        {item.valid_until && item.kind === 'primary' && (
                          <p className="text-[10px] text-[#8D857D] mt-1">
                            Valable jusqu'au {new Date(item.valid_until).toLocaleDateString('fr-FR')}
                          </p>
                        )}
                      </div>
                      {isClickable && <ChevronRight size={16} className="text-[#8D857D] shrink-0 mt-1" />}
                    </div>
                  </Wrapper>
                );
              }))}

              {tab === 'program' && (
                <div className="space-y-3 text-sm">
                  <div className="rounded-lg border border-[#E9E5E0] p-3 bg-white">
                    <p className="text-xs text-[#8D857D] uppercase tracking-wider font-semibold mb-1">Récompense</p>
                    <p className="text-[#171412] font-medium">🎁 {card.reward_description}</p>
                    <p className="text-xs text-[#57504A] mt-1">Débloquée après {stampsTarget} visites.</p>
                  </div>
                  <div className="rounded-lg border border-[#E9E5E0] p-3 bg-white">
                    <p className="text-xs text-[#8D857D] uppercase tracking-wider font-semibold mb-1">Points par visite</p>
                    <p className="text-[#171412] font-medium">+{card.points_per_visit} pts à chaque passage</p>
                  </div>
                  <div className="rounded-lg border border-[#E9E5E0] p-3 bg-white">
                    <p className="text-xs text-[#8D857D] uppercase tracking-wider font-semibold mb-2">Commerçant</p>
                    <p className="flex items-center gap-2 text-[#171412]"><Store size={14} /> {tenant.name}</p>
                    {tenant.address && <p className="flex items-center gap-2 text-[#57504A] text-xs mt-1"><MapPin size={12} /> {tenant.address}</p>}
                    {tenant.phone && <p className="flex items-center gap-2 text-[#57504A] text-xs mt-1"><Phone size={12} /> {tenant.phone}</p>}
                    {tenant.website && <p className="flex items-center gap-2 text-[#57504A] text-xs mt-1"><Globe size={12} /> {tenant.website}</p>}
                  </div>
                </div>
              )}
            </div>
          </aside>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-[#171412] text-white text-sm py-2.5 px-5 rounded-full shadow-lg">
          {toast}
        </div>
      )}

      {/* Tap-to-expand details drawer */}
      {detailsOpen && (
        <DetailsDrawer tenant={tenant} card={card} onClose={() => setDetailsOpen(false)} />
      )}

      {/* Notification detail modal — opens when the customer taps any
          notification in the News tab. Shows the full campaign body and,
          if present, a CTA link that fires the track-click endpoint
          before navigating away (so the merchant's analytics show real
          click-through numbers, not just opens). */}
      {openedNotification && (
        <NotificationDetailModal
          notification={openedNotification}
          tenant={tenant}
          card={card}
          customerId={customer.id}
          onClose={() => setOpenedNotification(null)}
        />
      )}
    </div>
  );
};

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
          maxWidth: 520, width: '100%', maxHeight: '85vh', overflowY: 'auto',
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
  const stampsEarned = Math.min(customer.visits || 0, stampsTarget);
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
          <div className="bg-white rounded-xl p-4 mx-auto inline-block">
            <QRCodeSVG value={customer.barcode_id} size={200} level="M" />
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
    <div className="text-[#B85C38]">{icon}</div>
    <div className="flex-1">
      <p className="font-medium text-sm text-[#171412]">{label}</p>
      <p className="text-xs text-[#57504A]">{hint}</p>
    </div>
    <button
      onClick={onToggle}
      disabled={disabled}
      className={`relative w-11 h-6 rounded-full transition-colors ${value ? 'bg-[#4A5D23]' : 'bg-[#D6D3D1]'} ${disabled ? 'opacity-60' : ''}`}
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

export default MyWalletCardPage;
