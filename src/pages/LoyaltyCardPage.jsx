import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CreditCard, Eye, Plus, Image as ImageIcon, Trash2, Save, Settings2, Gift, Star,
  QrCode, Users, TrendingUp, TrendingDown, Lightbulb, Loader2, Check, X, Sliders,
  MapPin, Share2, CalendarClock, Type, ChevronDown,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import WalletCard from '../components/WalletCard';
import InfoTip from '../components/InfoTip';
import PosterCropper from '../components/PosterCropper';
import CardDesigner from '../components/wallet/CardDesigner';
import FeaturedActionsEditor from '../components/wallet/FeaturedActionsEditor';

/**
 * Carte de fidélité — the one page where a merchant designs their card, sets
 * the programme rules, reads how the card is performing and edits the reward
 * ladder. Built to the approved mockup (blue/white), and wired end to end:
 *
 *   • design + rules save to card_templates through /api/owner/card/settings,
 *     which also pushes every customer's Wallet pass so their card follows.
 *   • the four figures come from /api/owner/card/stats — real counts of
 *     customers, visits and redemptions, each against the previous window.
 *     An empty shop reads 0; there is no demo data on this page.
 *   • "Vue client" renders the card exactly as the customer's page does;
 *     "Vue wallet" renders the pkpass-faithful preview, so what is designed
 *     here is what lands in Apple Wallet.
 *
 * The programme type is a rule, not a label: "Points" makes points accrue per
 * euro and reads the ladder in points, "Tampons" keeps one stamp per visit and
 * reads it in visits.
 */
const BLUE = '#2F6BFF';
const INK = '#0B1C3F';

/* ── small building blocks, all in the mockup's idiom ─────────────────── */
// `locked`: shown, not editable — the card is the owner's to change.
const Card = ({ icon: Icon, title, subtitle, action, children, className = '', locked = false, id, help }) => (
  <section id={id} className={`rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] ${className}`}>
    <header className="mb-4 flex items-start gap-3">
      {Icon && (
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]">
          <Icon size={19} />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <h2 className="flex items-center gap-1.5 text-[15px] font-bold leading-tight text-[#0B1C3F]">{title} {help && <InfoTip k={help} />}</h2>
        {subtitle && <p className="mt-0.5 text-[12.5px] leading-snug text-[#64748B]">{subtitle}</p>}
      </div>
      {action}
    </header>
    {locked ? <fieldset disabled className="m-0 min-w-0 border-0 p-0">{children}</fieldset> : children}
  </section>
);

const Label = ({ children, hint }) => (
  <label className="mb-1.5 block text-[12.5px] font-semibold text-[#334155]">
    {children}{hint && <span className="ml-1 font-normal text-[#94A3B8]">{hint}</span>}
  </label>
);

const Input = (props) => (
  <input
    {...props}
    className={`w-full rounded-xl border border-[#E1E8F5] bg-white px-3.5 py-2.5 text-[13.5px] text-[#0F172A] outline-none transition placeholder:text-[#94A3B8] focus:border-[#2F6BFF] focus:ring-4 focus:ring-[#2F6BFF]/10 ${props.className || ''}`}
  />
);

const Select = ({ children, ...props }) => (
  <div className="relative">
    <select
      {...props}
      className="w-full appearance-none rounded-xl border border-[#E1E8F5] bg-white px-3.5 py-2.5 pr-9 text-[13.5px] text-[#0F172A] outline-none transition focus:border-[#2F6BFF] focus:ring-4 focus:ring-[#2F6BFF]/10"
    >
      {children}
    </select>
    <svg className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#64748B]" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="m6 9 6 6 6-6" />
    </svg>
  </div>
);

const ColorField = ({ value, onChange }) => (
  <div className="flex items-center gap-2 rounded-xl border border-[#E1E8F5] bg-white px-2.5 py-2">
    <label className="relative h-7 w-7 shrink-0 cursor-pointer overflow-hidden rounded-md border border-[#E1E8F5]" style={{ background: value }}>
      <input type="color" value={value} onChange={(e) => onChange(e.target.value.toUpperCase())}
             className="absolute inset-0 h-full w-full cursor-pointer opacity-0" />
    </label>
    <input value={value} onChange={(e) => onChange(e.target.value.toUpperCase())} maxLength={7} spellCheck={false}
           className="min-w-0 flex-1 bg-transparent text-[13px] uppercase tracking-wide text-[#0F172A] outline-none" />
  </div>
);

/** Image slot: preview + upload + delete, like the mockup's two thumbnails. */
const ImageField = ({ value, onChange, label, aspect = '16 / 10', accept = 'image/png,image/jpeg,image/webp', downscale }) => {
  const ref = useRef(null);
  const pick = async (e) => {
    const file = e.target.files?.[0]; e.target.value = '';
    if (!file) return;
    onChange(await downscale(file));
  };
  return (
    <div>
      <Label>{label}</Label>
      <div className="flex items-stretch gap-2 rounded-xl border border-[#E1E8F5] bg-white p-2">
        <button type="button" onClick={() => ref.current?.click()}
                className="relative flex-1 overflow-hidden rounded-lg bg-[#F4F7FC]" style={{ aspectRatio: aspect }}>
          {value ? (
            <img src={value} alt="" className="h-full w-full object-cover" />
          ) : (
            <span className="flex h-full w-full flex-col items-center justify-center gap-1 text-[#94A3B8]">
              <ImageIcon size={16} /><span className="text-[11px]">Ajouter</span>
            </span>
          )}
        </button>
        {value && (
          <button type="button" onClick={() => onChange('')} aria-label={`Retirer ${label}`}
                  className="flex w-9 shrink-0 items-center justify-center rounded-lg text-[#E5484D] hover:bg-[#FEF2F2]">
            <Trash2 size={16} />
          </button>
        )}
      </div>
      <input ref={ref} type="file" accept={accept} className="hidden" onChange={pick} />
    </div>
  );
};

const Toggle = ({ icon: Icon, label, checked, onChange }) => (
  <button type="button" onClick={() => onChange(!checked)}
          className="flex w-full items-center gap-2.5 rounded-xl px-2 py-2 text-left transition hover:bg-[#F7FAFF]">
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#EAF1FF] text-[#2F6BFF]"><Icon size={14} /></span>
    <span className="flex-1 text-[13px] text-[#334155]">{label}</span>
    <span className={`relative h-[22px] w-[42px] shrink-0 rounded-full transition ${checked ? 'bg-[#2F6BFF]' : 'bg-[#CBD5E1]'}`}>
      <span className={`absolute top-[3px] h-4 w-4 rounded-full bg-white shadow transition-all ${checked ? 'left-[23px]' : 'left-[3px]'}`} />
    </span>
  </button>
);

/** One statistic: figure, label, and the change against the previous window. */
const Stat = ({ icon: Icon, tone, value, label, delta, hint, help }) => {
  const up = typeof delta === 'number' && delta >= 0;
  return (
    <div className="rounded-xl border border-[#E6EEFB] bg-white p-3.5">
      <span className="mb-2 flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: tone.bg, color: tone.fg }}>
        <Icon size={15} />
      </span>
      <div className="text-[22px] font-extrabold leading-none tracking-[-0.02em] text-[#0B1C3F]">{value}</div>
      <div className="mt-1 flex items-center gap-1 text-[12px] text-[#64748B]">{label} {help && <InfoTip k={help} size={12} />}</div>
      {typeof delta === 'number' ? (
        <div className={`mt-2 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-bold ${up ? 'bg-[#E8F8EE] text-[#15803D]' : 'bg-[#FEECEC] text-[#B91C1C]'}`}>
          {up ? <TrendingUp size={11} /> : <TrendingDown size={11} />}{up ? '+' : ''}{delta}%
        </div>
      ) : (
        <div className="mt-2 inline-flex rounded-md bg-[#F1F5F9] px-1.5 py-0.5 text-[11px] font-semibold text-[#64748B]">
          période précédente vide
        </div>
      )}
    </div>
  );
};

/* ── image helpers ────────────────────────────────────────────────────── */
// `jpeg` with cover=false: the WHOLE photo, only made smaller — never cropped
// (user, 2026-10-06: « puri photo dikhe, kati hui nhi »).
const downscaleTo = (maxW, maxH, cover, jpeg = false) => (file) => new Promise((resolve, reject) => {
  const img = new Image();
  const url = URL.createObjectURL(file);
  img.onload = () => {
    const c = document.createElement('canvas');
    const ctx = c.getContext('2d');
    if (cover) {
      c.width = maxW; c.height = maxH;
      const k = Math.max(maxW / img.width, maxH / img.height);
      const w = img.width * k; const h = img.height * k;
      ctx.drawImage(img, (maxW - w) / 2, (maxH - h) / 2, w, h);
    } else {
      const k = Math.min(1, maxW / img.width, maxH / img.height);
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      ctx.drawImage(img, 0, 0, c.width, c.height);
    }
    URL.revokeObjectURL(url);
    resolve(c.toDataURL(cover || jpeg ? 'image/jpeg' : 'image/png', 0.85));
  };
  img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('bad image')); };
  img.src = url;
});
const readLogo = downscaleTo(320, 320, false);
// Whole photos, never cropped at upload: the classic strip and the iOS 27
// poster each frame it themselves, server side.
const readBanner = downscaleTo(1600, 1600, false, true);
// (the « Image poster » goes through PosterCropper instead: framed, full card)

const PROGRAMME_HINT = {
  points_euro: 'Le client cumule des points proportionnels au montant dépensé.',
  points_visit: 'Chaque passage en caisse crédite le même nombre de points.',
  stamps: 'Un tampon par visite ; la récompense tombe au bout de N tampons.',
  cashback: 'Un pourcentage du ticket est rendu au client sous forme de cagnotte.',
};

/* « Bonus de bienvenue » moved to the Automatisations page (user, 2026-10-02):
   it is the message a new client gets, and it lives with the other automatic
   messages (components/AutoMessagesPanel). */

const TIER_TONE = ['#B08968', '#94A3B8', '#E0A128', '#7C3AED'];
const WINDOWS = [{ d: 7, label: '7 derniers jours' }, { d: 30, label: '30 derniers jours' }, { d: 90, label: '90 derniers jours' }];

export default function LoyaltyCardPage() {
  // One card for every establishment: the owner changes it, everyone else
  // sees it as it is — with the figures of their own establishments.
  const { user } = useAuth();
  const edit = user?.role === 'business_owner';
  const [data, setData] = useState(null);          // server truth
  const [design, setDesign] = useState(null);
  const [programme, setProgramme] = useState(null);
  const [toggles, setToggles] = useState(null);
  const [tiers, setTiers] = useState([]);
  const [advanced, setAdvanced] = useState(null);
  // « Image poster »: the photo is framed by the owner, then fills the card
  const [cropReq, setCropReq] = useState(null);
  const readPoster = (file) => new Promise((resolve) => setCropReq({ file, resolve }));
  // bumped when the card editor saves: the « Vue wallet » preview refetches
  const [pdVersion, setPdVersion] = useState(0);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [customerPreview, setCustomerPreview] = useState(false);
  const [stats, setStats] = useState(null);
  const [days, setDays] = useState(30);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(null);
  // The save bar shows only when there is something to save — and for a few
  // seconds after a save, to say it went through (user, 2026-10-03: « Toutes
  // les modifications sont enregistrées » sat there all the time).
  const [justSaved, setJustSaved] = useState(false);
  useEffect(() => {
    if (!savedAt) return undefined;
    setJustSaved(true);
    const t = window.setTimeout(() => setJustSaved(false), 4000);
    return () => window.clearTimeout(t);
  }, [savedAt]);
  const [error, setError] = useState('');
  const [editTiers, setEditTiers] = useState(false);
  const [tierError, setTierError] = useState('');
  const [snapshot, setSnapshot] = useState('');   // what the server holds, to know what is unsaved
  const advancedRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const r = await ownerAPI.cardSettings();
      setData(r.data);
      setDesign(r.data.design);
      setProgramme(r.data.programme);
      setToggles(r.data.toggles);
      setTiers(r.data.tiers);
      // A photo on file with the banner style still reading "brand" can only be
      // a card saved before the upload started setting the style — the owner
      // added a banner and never saw it. Show the photo.
      const adv = r.data.advanced?.hero_mode === 'brand' && r.data.design?.hero_image_url
        ? { ...r.data.advanced, hero_mode: 'image' }
        : r.data.advanced;
      setAdvanced(adv);
      setSnapshot(JSON.stringify([r.data.design, r.data.programme, r.data.toggles, adv]));
    } catch (e) {
      setError(e?.response?.data?.detail || "Impossible de charger la carte.");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Unsaved changes: the save bar says so, and leaving the page asks first.
  const settingsDirty = Boolean(snapshot) && JSON.stringify([design, programme, toggles, advanced]) !== snapshot;
  // the card editor's own design (pass.json template) has its own save
  const designerRef = useRef(null);
  const [designerDirty, setDesignerDirty] = useState(false);
  const dirty = settingsDirty || designerDirty;
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (e) => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const discard = () => {
    if (settingsDirty) {
      const [d, p, t, a] = JSON.parse(snapshot);
      setDesign(d); setProgramme(p); setToggles(t); setAdvanced(a);
    }
    if (designerDirty) designerRef.current?.reset();
  };

  // « Options avancées » opens the panel and brings it on screen — it sat
  // below the fold, so a click seemed to do nothing (user, 2026-10-02).
  const openAdvanced = () => {
    setShowAdvanced(true);
    requestAnimationFrame(() => requestAnimationFrame(() => advancedRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })));
  };
  useEffect(() => {
    if (advanced && window.location.hash === '#options-avancees') openAdvanced();
  }, [Boolean(advanced)]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    let alive = true;
    ownerAPI.cardStats(days).then((r) => { if (alive) setStats(r.data); }).catch(() => {});
    return () => { alive = false; };
  }, [days]);

  const isPoints = programme?.type !== 'stamps';

  /* The preview is fed the same fields the customer's card reads, so what is
     on screen here is what the customer gets — no mock. */
  const cardForPreview = useMemo(() => ({
    layout_style: 'wallet',
    card_name: design?.card_name,
    surface_color: design?.surface_color,
    brand_color: design?.brand_color,
    logo_url: design?.logo_url,
    hero_image_url: design?.hero_image_url,
    // Same fallback the server uses, so the preview and the saved card agree.
    hero_mode: advanced?.hero_mode || (design?.hero_image_url ? 'image' : 'brand'),
    tagline: design?.welcome_text,
    offer_box_text: toggles?.show_message ? design?.card_message : '',
    show_offer_box: Boolean(toggles?.show_message && design?.card_message),
    show_points: toggles?.show_points !== false,
    show_tier: advanced?.show_tier !== false,
    show_tier_badge: advanced?.show_tier !== false,
    show_visits: advanced?.show_visits !== false,
    // Derived from the single choice, so the preview shows exactly one.
    show_stamps: (advanced?.progress_style || 'meter') === 'stamps',
    show_meter: (advanced?.progress_style || 'meter') === 'meter',
    // Every card shows its code; its kind is the « Type de code » option.
    show_qr: true,
    code_type: advanced?.code_type || 'qr',
    show_card_number: advanced?.show_card_number !== false,
    use_full_name: Boolean(advanced?.use_full_name),
    greeting_label: advanced?.greeting_label,
    points_label: advanced?.points_label,
    visits_label: advanced?.visits_label,
    stamps_label: advanced?.stamps_label,
    reward_threshold_stamps: programme?.reward_threshold_stamps,
    reward_description: programme?.reward_description,
    points_per_visit: programme?.points_per_visit,
    // iOS 27: the poster and its tiles, previewed as they are chosen
    poster_style: advanced ? advanced.poster_style !== false : undefined,
    poster_image_url: advanced?.poster_image_url,
    pd_version: pdVersion,                      // refetch the preview after an import
    featured_actions: advanced?.featured_actions,
    // « Logo rond » and the Google Wallet design, previewed as they are chosen
    logo_round: Boolean(advanced?.logo_round),
    logo_ring: Boolean(advanced?.logo_ring),
    logo_ring_color: advanced?.logo_ring_color || undefined,
    google_design: advanced?.google_design,
    google_links: advanced?.google_links,
  }), [design, programme, toggles, advanced, pdVersion]);

  const previewCustomer = useMemo(() => ({
    name: 'Marie Love', first_name: 'Marie', tier: 'silver',
    points: isPoints ? 1200 : (programme?.points_per_visit || 10) * 7,
    visits: 7, barcode_id: 'FIDCLIC-0000-0000',
    reward_threshold: programme?.reward_threshold_stamps || 10,
  }), [isPoints, programme]);

  // The card's identity — the old « Personnalisation de la carte » card — now
  // the editor's first tab.
  const identityPanel = design && (
    <fieldset disabled={!edit} className="m-0 min-w-0 border-0 p-0">
      <div className="space-y-3.5">
        <div>
          <Label>Nom de la carte</Label>
          <Input value={design.card_name} maxLength={40}
                 onChange={(e) => setDesign({ ...design, card_name: e.target.value })} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Couleur principale</Label>
            <ColorField value={design.surface_color} onChange={(v) => setDesign({ ...design, surface_color: v })} />
          </div>
          <div>
            <Label>Couleur secondaire</Label>
            <ColorField value={design.brand_color} onChange={(v) => setDesign({ ...design, brand_color: v })} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <ImageField label="Logo de l'établissement" value={design.logo_url} aspect="16 / 10" downscale={readLogo}
                      onChange={(v) => setDesign({ ...design, logo_url: v })} />
          {/* Uploading a banner IS the choice to use it. Without this the
              advanced "Style de bannière" select — which reads "brand" for
              any shop that never had a photo — silently outranked the image
              the owner had just added, on the preview and on the real card
              alike. Removing the photo hands the banner back to the brand
              colour. */}
          <ImageField label="Image de fond (optionnelle)" value={design.hero_image_url} aspect="16 / 10" downscale={readBanner}
                      onChange={(v) => {
                        setDesign({ ...design, hero_image_url: v });
                        setAdvanced((a) => ({ ...a, hero_mode: v ? 'image' : (a?.hero_mode === 'none' ? 'none' : 'brand') }));
                      }} />
        </div>
        {/* « Logo rond » (user, 2026-10-08): cut to a disc on Apple and Google
            alike, with an optional ring — the preview shows it at once */}
        {advanced && (
          <div className="-mx-2 space-y-0.5 rounded-xl border border-[#E6EEFB] py-1">
            <Toggle icon={ImageIcon} label="Logo rond" checked={Boolean(advanced.logo_round)}
                    onChange={(v) => setAdvanced({ ...advanced, logo_round: v })} />
            {advanced.logo_round && (
              <Toggle icon={ImageIcon} label="Bordure autour du logo" checked={Boolean(advanced.logo_ring)}
                      onChange={(v) => setAdvanced({ ...advanced, logo_ring: v })} />
            )}
            {advanced.logo_round && advanced.logo_ring && (
              <div className="flex items-center justify-between gap-3 px-2 py-1.5">
                <span className="text-[13px] text-[#334155]">Couleur de la bordure</span>
                <div className="w-40">
                  <ColorField value={advanced.logo_ring_color || design.brand_color || '#D4AF37'}
                              onChange={(v) => setAdvanced({ ...advanced, logo_ring_color: v })} />
                </div>
              </div>
            )}
          </div>
        )}
        <div>
          <Label>Texte d'accueil sur la carte</Label>
          <textarea rows={3} maxLength={100} value={design.welcome_text}
                    onChange={(e) => setDesign({ ...design, welcome_text: e.target.value })}
                    className="w-full resize-none rounded-xl border border-[#E1E8F5] bg-white px-3.5 py-2.5 text-[13.5px] text-[#0F172A] outline-none focus:border-[#2F6BFF] focus:ring-4 focus:ring-[#2F6BFF]/10" />
          <div className="mt-1 text-right text-[11px] text-[#94A3B8]">{(design.welcome_text || '').length}/100</div>
        </div>
      </div>
    </fieldset>
  );

  // One save for the page and the card editor's design.
  const save = async () => {
    setSaving(true); setError('');
    try {
      let wallet = 0;
      if (settingsDirty) {
      const r = await ownerAPI.saveCardSettings({
        ...design,
        programme: programme.type,
        points_per_euro: Number(programme.points_per_euro),
        cashback_rate: Number(programme.cashback_rate),
        points_per_visit: Number(programme.points_per_visit),
        reward_threshold_stamps: Number(programme.reward_threshold_stamps),
        reward_points: Number(programme.reward_points),
        reward_description: programme.reward_description,
        ...toggles,
        show_qr: true, wallet_enabled: true,
        ...(advanced || {}),
      });
      wallet = r.data?.wallet_passes_updated || 0;
      }
      if (designerDirty) await designerRef.current?.save();
      setSavedAt({ at: Date.now(), wallet });
      load();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Enregistrement impossible.');
    } finally {
      setSaving(false);
    }
  };

  const saveTiers = async () => {
    setSaving(true); setError(''); setTierError('');
    try {
      const r = await ownerAPI.saveCardRewards(tiers.map((t) => ({ key: t.key, min: Number(t.min), reward: t.reward })));
      setTiers(r.data.tiers);
      setEditTiers(false);
    } catch (e) {
      // Said beside the rungs, where the owner is looking.
      setTierError(e?.response?.data?.detail || 'Paliers invalides.');
    } finally {
      setSaving(false);
    }
  };

  if (!design) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-[#64748B]">
        {error ? <span className="text-[#B91C1C]">⚠ {error}</span> : <Loader2 className="animate-spin" />}
      </div>
    );
  }

  const unit = isPoints ? 'points' : 'visites';

  return (
    <div className="lc lc-wrap space-y-4 pb-28">
      {/* ── page header ── */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#2F6BFF] text-[15px] font-bold text-white">4</span>
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-[#EAF1FF] px-2 py-0.5 text-[11px] font-bold text-[#2F6BFF]">4 / 10</span>
              <h1 className="text-[22px] font-extrabold tracking-[-0.02em] text-[#0B1C3F]">Carte de fidélité</h1>
            </div>
            <nav className="mt-1 text-[11.5px] text-[#94A3B8]">
              <span>Clients</span> <span className="px-1">›</span> <span className="text-[#64748B]">Carte de fidélité</span>
            </nav>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setCustomerPreview(true)}
                  className="inline-flex items-center gap-2 rounded-xl border border-[#E1E8F5] bg-white px-3.5 py-2.5 text-[13px] font-semibold text-[#334155] hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
            <Eye size={15} /> Aperçu client
          </button>
          <button type="button" onClick={openAdvanced}
                  className="inline-flex items-center gap-2 rounded-xl px-3.5 py-2.5 text-[13px] font-semibold text-white"
                  style={{ background: BLUE, boxShadow: '0 10px 22px -12px rgba(47,107,255,.8)' }}>
            <Sliders size={15} /> Options avancées
            <ChevronDown size={14} />
          </button>
        </div>
      </div>

      {/* ── info banner ── */}
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-[#DCE8FF] bg-[#F2F7FF] p-4">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#2F6BFF] text-white"><CreditCard size={18} /></span>
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-bold text-[#0B1C3F]">Créez, personnalisez et gérez votre carte de fidélité digitale.</p>
        </div>
        <button type="button" onClick={() => document.getElementById('design-wallet')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                className="inline-flex items-center gap-2 rounded-xl border border-[#E1E8F5] bg-white px-3.5 py-2 text-[12.5px] font-semibold text-[#334155] hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
          <Eye size={14} /> Voir un exemple
        </button>
      </div>

      {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-[13px] text-red-700">⚠ {error}</div>}
      {!edit && (
        <div className="flex items-start gap-2.5 rounded-xl border border-[#E6EEFB] bg-white px-4 py-3 text-[12.5px] text-[#475569]">
          <Eye size={15} className="mt-0.5 shrink-0 text-[#2F6BFF]" />
          La carte est la même dans tous les établissements : seul le propriétaire peut la modifier.
          Les statistiques ci-dessous sont celles de vos établissements.
        </div>
      )}

      {/* ── the card, in one place (user, 2026-10-07): the old « Personnalisation de la
          carte » fields are the editor's « Identité » tab, and its preview shows
          iOS 27, iOS 26 and the customer's web card together ── */}
      <Card id="design-wallet" icon={Sliders} title="Design de la carte"
            subtitle="Identité, style, images, code-barres, boutons et champs — l’aperçu iOS 27, iOS 26 et web suit chaque modification.">
        {advanced ? (
          <CardDesigner ref={designerRef} edit={edit} types={advanced.featured_types || []} formats={advanced.barcode_formats || []}
                        actions={advanced.featured_actions || []}
                        onActionsChange={(rows) => setAdvanced((a) => ({ ...a, featured_actions: rows }))}
                        identityPanel={identityPanel} previewCard={cardForPreview}
                        clientPreview={<WalletCard customer={previewCustomer} tenant={{ name: data?.tenant?.name }} card={cardForPreview} compact />}
                        externalDirty={settingsDirty} onSaveAll={save} onDirtyChange={setDesignerDirty}
                        googleDesign={advanced.google_design || {}}
                        onGoogleChange={(patch) => setAdvanced((a) => ({ ...a, google_design: { ...(a.google_design || {}), ...patch } }))}
                        googleLinks={advanced.google_links || []}
                        onGoogleLinksChange={(rows) => setAdvanced((a) => ({ ...a, google_links: rows }))}
                        onSaved={() => { setPdVersion((v) => v + 1); load(); }} />
        ) : (
          <div className="flex items-center gap-2 py-6 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Chargement…</div>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4">
        {/* 3. programme */}
        <Card icon={Settings2} title="Paramètres de la carte" subtitle="Configurez le fonctionnement de votre programme." locked={!edit}>
          {/* full width now: two columns on a wide screen */}
          <div className="grid grid-cols-1 items-start gap-x-8 gap-y-3.5 lg:grid-cols-2">
            <div>
              <Label>Type de programme</Label>
              <Select value={programme.type} onChange={(e) => setProgramme({ ...programme, type: e.target.value })}>
                <option value="points_euro">Points par euro dépensé</option>
                <option value="points_visit">Points par visite</option>
                <option value="stamps">Tampons (1 par visite)</option>
                <option value="cashback">Cagnotte (% du ticket)</option>
              </Select>
              <p className="mt-1 text-[11.5px] text-[#94A3B8]">{PROGRAMME_HINT[programme.type]}</p>
            </div>
            {programme.type === 'cashback' && (
              <div>
                <Label hint="part du ticket rendue au client">Taux de cagnotte</Label>
                <Select value={String(programme.cashback_rate)}
                        onChange={(e) => setProgramme({ ...programme, cashback_rate: Number(e.target.value) })}>
                  {[1, 2, 3, 5, 8, 10].map((n) => <option key={n} value={n}>{n} % du montant</option>)}
                </Select>
                <p className="mt-1 text-[11.5px] text-[#94A3B8]">
                  Un ticket de 20 € crédite {(20 * (programme.cashback_rate || 5) / 100).toFixed(2).replace('.', ',')} € au client.
                </p>
              </div>
            )}
            {programme.type === 'points_visit' && (
              <div>
                <Label>Points par visite</Label>
                <Input type="number" min="1" value={programme.points_per_visit}
                       onChange={(e) => setProgramme({ ...programme, points_per_visit: e.target.value })} />
              </div>
            )}
            {isPoints ? (
              <>
                {programme.type === 'points_euro' && (
                <div>
                  <Label>Valeur d'un point</Label>
                  <Select value={String(programme.points_per_euro)}
                          onChange={(e) => setProgramme({ ...programme, points_per_euro: Number(e.target.value) })}>
                    {[1, 2, 5, 10, 20].map((n) => <option key={n} value={n}>1 € = {n} point{n > 1 ? 's' : ''}</option>)}
                  </Select>
                </div>
                )}
                <div>
                  <Label>Récompense par défaut</Label>
                  <div className="flex gap-2">
                    <Input type="number" min="1" value={programme.reward_points} className="w-24"
                           onChange={(e) => setProgramme({ ...programme, reward_points: e.target.value })} />
                    <Input value={programme.reward_description} placeholder="1 boisson offerte"
                           onChange={(e) => setProgramme({ ...programme, reward_description: e.target.value })} />
                  </div>
                  <p className="mt-1 text-[11.5px] text-[#94A3B8]">{programme.reward_points} points = {programme.reward_description || '—'}</p>
                </div>
              </>
            ) : (
              <>
                <div>
                  <Label>Tampons pour une récompense</Label>
                  <Input type="number" min="1" max="50" value={programme.reward_threshold_stamps}
                         onChange={(e) => setProgramme({ ...programme, reward_threshold_stamps: e.target.value })} />
                </div>
                <div>
                  <Label>Récompense par défaut</Label>
                  <Input value={programme.reward_description} placeholder="Un café offert"
                         onChange={(e) => setProgramme({ ...programme, reward_description: e.target.value })} />
                  <p className="mt-1 text-[11.5px] text-[#94A3B8]">{programme.reward_threshold_stamps} tampons = {programme.reward_description || '—'}</p>
                </div>
              </>
            )}
            <div>
              <Label>Message sur la carte</Label>
              <Input value={design.card_message} maxLength={120}
                     onChange={(e) => setDesign({ ...design, card_message: e.target.value })} />
            </div>
            <div className="-mx-2 space-y-0.5 pt-1">
              <Toggle icon={Star} label="Afficher le solde de points" checked={toggles.show_points}
                      onChange={(v) => setToggles({ ...toggles, show_points: v })} />
              <Toggle icon={CreditCard} label="Afficher le message sur la carte" checked={toggles.show_message}
                      onChange={(v) => setToggles({ ...toggles, show_message: v })} />
              <Toggle icon={Users} label="Notification anniversaire" checked={toggles.birthday_notification}
                      onChange={(v) => setToggles({ ...toggles, birthday_notification: v })} />
            </div>
          </div>
        </Card>
      </div>

      {/* ── options avancées — the knobs Apple and Google really expose ── */}
      {showAdvanced && advanced && (
        <div ref={advancedRef} id="options-avancees" className="scroll-mt-24">
        <Card icon={Sliders} title="Options avancées" locked={!edit}
              action={(
                <button type="button" onClick={() => setShowAdvanced(false)}
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[#E1E8F5] bg-white px-3 py-2 text-[12.5px] font-semibold text-[#334155] hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                  <X size={14} /> Masquer
                </button>
              )}
              subtitle="Réglages pris en charge par Apple Wallet et Google Wallet. Tout le reste (police, mise en page, animations) est imposé par Apple.">
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
            {/* code + identity */}
            <div className="space-y-3.5">
              <div>
                <Label hint="certaines caisses ne lisent que les codes-barres">Type de code</Label>
                <Select value={advanced.code_type} onChange={(e) => setAdvanced({ ...advanced, code_type: e.target.value })}>
                  <option value="qr">QR code</option>
                  <option value="barcode">Code-barres (Code 128)</option>
                  <option value="pdf417">PDF417</option>
                  <option value="aztec">Aztec</option>
                  {(advanced.barcode_formats || []).filter((f) => f.ios27_only).map((f) => (
                    <option key={f.format} value={f.format}>{f.label} — iOS 27</option>
                  ))}
                </Select>
              </div>
              <div>
                <Label hint="ce que lisent les iPhone sans iOS 27">Code de secours</Label>
                <Select value={advanced.code_fallback || ''} onChange={(e) => setAdvanced({ ...advanced, code_fallback: e.target.value })}>
                  <option value="">Automatique (QR code si besoin)</option>
                  {(advanced.barcode_formats || []).filter((f) => !f.ios27_only).map((f) => (
                    <option key={f.format} value={f.format}>{f.label}</option>
                  ))}
                </Select>
              </div>
              <div className="-mx-2">
                <Toggle icon={QrCode} label="Afficher le numéro sous le code" checked={advanced.show_card_number}
                        onChange={(v) => setAdvanced({ ...advanced, show_card_number: v })} />
                <Toggle icon={Users} label="Afficher le nom complet du client" checked={advanced.use_full_name}
                        onChange={(v) => setAdvanced({ ...advanced, use_full_name: v })} />
                {/* These two are rendered by Apple itself — they change the pass
                    on the phone, never this preview. Saying so beats letting the
                    merchant hunt for a change that cannot appear here. */}
                <Toggle icon={Share2} label="Autoriser le partage de la carte" checked={advanced.allow_sharing}
                        onChange={(v) => setAdvanced({ ...advanced, allow_sharing: v })} />
                <Toggle icon={Star} label="Reflet Apple sur la bannière" checked={advanced.strip_shine}
                        onChange={(v) => setAdvanced({ ...advanced, strip_shine: v })} />
                <p className="px-2 pt-1 text-[11.5px] leading-snug text-[#94A3B8]">
                  Ces deux réglages sont appliqués par Apple sur le téléphone : ils ne changent pas l'aperçu ci-dessus.
                </p>
              </div>
            </div>

            {/* labels */}
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-[12.5px] font-semibold text-[#334155]">
                <Type size={14} className="text-[#2F6BFF]" /> Libellés affichés sur la carte
              </div>
              {[['greeting_label', 'Membre'], ['points_label', 'Points'], ['visits_label', 'Visites'], ['stamps_label', 'Tampons']].map(([k, ph]) => (
                <Input key={k} value={advanced[k] || ''} placeholder={ph}
                       onChange={(e) => setAdvanced({ ...advanced, [k]: e.target.value })} />
              ))}
              <p className="text-[11.5px] text-[#94A3B8]">Ex. « Tampons » → « Cafés », « Points » → « Étoiles ».</p>
            </div>

            {/* lifecycle + proximity */}
            <div className="space-y-3.5">
              <div>
                <Label hint="carte saisonnière — laissez vide pour une carte permanente">Date d'expiration</Label>
                <Input type="date" value={(advanced.pass_expiration_date || '').slice(0, 10)}
                       onChange={(e) => setAdvanced({ ...advanced, pass_expiration_date: e.target.value ? `${e.target.value}T23:59:00Z` : '' })} />
              </div>
              <div className="-mx-2">
                <Toggle icon={MapPin} label="Rappel quand le client passe devant" checked={advanced.location_reminder}
                        onChange={(v) => setAdvanced({ ...advanced, location_reminder: v })} />
              </div>
              {!advanced.has_coordinates && (
                <p className="rounded-lg bg-[#FFFBEB] px-3 py-2 text-[11.5px] text-[#92400E]">
                  Renseignez l'adresse de l'établissement dans Paramètres pour activer le rappel de proximité.
                </p>
              )}
              <div>
                <Label hint="visibles au dos de la carte">Informations complémentaires</Label>
                <div className="space-y-2">
                  {(advanced.back_fields || []).map((row, i) => (
                    <div key={i} className="flex gap-2">
                      <Input value={row.label} placeholder="Horaires" className="w-1/3"
                             onChange={(e) => setAdvanced({ ...advanced, back_fields: advanced.back_fields.map((r, j) => (j === i ? { ...r, label: e.target.value } : r)) })} />
                      <Input value={row.value} placeholder="Lun-Sam 8h-19h"
                             onChange={(e) => setAdvanced({ ...advanced, back_fields: advanced.back_fields.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)) })} />
                      <button type="button" aria-label="Supprimer la ligne"
                              onClick={() => setAdvanced({ ...advanced, back_fields: advanced.back_fields.filter((_, j) => j !== i) })}
                              className="shrink-0 rounded-lg px-2 text-[#E5484D] hover:bg-[#FEF2F2]"><Trash2 size={15} /></button>
                    </div>
                  ))}
                  {(advanced.back_fields || []).length < 8 && (
                    <button type="button"
                            onClick={() => setAdvanced({ ...advanced, back_fields: [...(advanced.back_fields || []), { label: '', value: '' }] })}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-[#CBD5E1] px-3 py-1.5 text-[12.5px] font-semibold text-[#64748B] hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                      <Plus size={13} /> Ajouter une ligne
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
          {/* second row — what the card shows, and how it behaves */}
          <div className="mt-5 grid grid-cols-1 gap-5 border-t border-[#EEF2F9] pt-5 lg:grid-cols-3">
            <div className="space-y-3.5">
              <div>
                <Label hint="seul champ visible quand la carte est empilée">Champ en haut à droite</Label>
                <Select value={advanced.header_field} onChange={(e) => setAdvanced({ ...advanced, header_field: e.target.value })}>
                  <option value="auto">Automatique</option>
                  <option value="points">Solde de points</option>
                  <option value="tier">Statut (palier)</option>
                  <option value="visits">Nombre de visites</option>
                  <option value="none">Aucun</option>
                </Select>
              </div>
              <div>
                <Label hint={design.hero_image_url ? 'retirez la photo pour revenir aux couleurs' : undefined}>
                  Style de bannière
                </Label>
                {/* With a photo on file the gradient is not an option here —
                    it is what you get by removing the photo. Offering both
                    made it possible to save a state where the uploaded banner
                    was never shown. */}
                <Select value={advanced.hero_mode} onChange={(e) => setAdvanced({ ...advanced, hero_mode: e.target.value })}>
                  {design.hero_image_url
                    ? <option value="image">Photo de l'établissement</option>
                    : <option value="brand">Dégradé aux couleurs de la marque</option>}
                  <option value="none">Aucune bannière</option>
                </Select>
              </div>
              <div>
                <Label hint="ce que lit la caisse">Contenu du code</Label>
                <Select value={advanced.code_content} onChange={(e) => setAdvanced({ ...advanced, code_content: e.target.value })}>
                  <option value="number">Numéro de carte</option>
                  <option value="url">Lien vers la carte du client</option>
                </Select>
              </div>
            </div>

            <div className="-mx-2">
              <p className="px-2 pb-1 text-[12.5px] font-semibold text-[#334155]">Éléments affichés sur la carte</p>
              <Toggle icon={Star} label="Statut (Bronze, Argent, Or, VIP)" checked={advanced.show_tier}
                      onChange={(v) => setAdvanced({ ...advanced, show_tier: v })} />
              <Toggle icon={Users} label="Nombre de visites" checked={advanced.show_visits}
                      onChange={(v) => setAdvanced({ ...advanced, show_visits: v })} />
              {/* One control, not two. The stamps row and the progress bar show
                  the same fact, and offering both let a card carry it twice. */}
              <div className="col-span-full">
                <Label hint="une seule jauge sur la carte">Indicateur de progression</Label>
                <Select
                  value={advanced.progress_style || 'meter'}
                  onChange={(e) => {
                    const style = e.target.value;
                    setAdvanced({ ...advanced, progress_style: style,
                                  show_stamps: style === 'stamps', show_meter: style === 'meter' });
                  }}
                >
                  <option value="meter">Jauge de progression sur la bannière</option>
                  <option value="stamps">Tampons (une pastille par passage)</option>
                  <option value="none">Aucun indicateur</option>
                </Select>
              </div>
            </div>

            <div className="space-y-3.5">
              <div>
                <Label hint="affiché sur l'écran verrouillé">Message de mise à jour — points</Label>
                <Input value={advanced.points_change_message} placeholder="Vous avez maintenant %@ points"
                       onChange={(e) => setAdvanced({ ...advanced, points_change_message: e.target.value })} />
              </div>
              <div>
                <Label>Message de mise à jour — tampons</Label>
                <Input value={advanced.stamps_change_message} placeholder="Tampons : %@"
                       onChange={(e) => setAdvanced({ ...advanced, stamps_change_message: e.target.value })} />
                <p className="mt-1 text-[11.5px] text-[#94A3B8]">%@ est remplacé par la nouvelle valeur.</p>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>Rayon du rappel</Label>
                  {/* One radius for the shop: the web card and the Wallet pass
                      both use Paramètres › Établissement's. */}
                  <a href="/dashboard/parametres/etablissement"
                     className="flex h-[42px] items-center rounded-xl border border-[#E1E8F5] bg-[#F8FAFF] px-3 text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">
                    Réglé dans Établissement →
                  </a>
                </div>
                <div>
                  <Label>Texte du rappel</Label>
                  <Input value={advanced.location_text} placeholder="Un café vous attend !"
                         onChange={(e) => setAdvanced({ ...advanced, location_text: e.target.value })} />
                </div>
              </div>
            </div>
          </div>

          {/* iOS 27 (WWDC26): the poster style and the two tiles under the pass */}
          <div className="mt-5 border-t border-[#EEF2F9] pt-5">
            <p className="mb-2 text-[12.5px] font-semibold text-[#334155]">
              Nouvelle carte Apple Wallet <span className="font-normal text-[#94A3B8]">— iPhone avec iOS 27 ; les iPhone plus anciens gardent la carte actuelle</span>
            </p>
            <Toggle icon={ImageIcon} label="Style « poster » : votre photo en plein écran" checked={advanced.poster_style !== false}
                    onChange={(v) => setAdvanced({ ...advanced, poster_style: v })} />
            {advanced.poster_style !== false && (
              <div className="mt-2 max-w-[220px]">
                <ImageField label="Image poster (recommandée)" value={advanced.poster_image_url} aspect="345 / 505"
                            downscale={readPoster}
                            onChange={(v) => setAdvanced({ ...advanced, poster_image_url: v })} />
                <p className="mt-1 text-[11px] text-[#94A3B8]">Vous cadrez la photo : elle couvre toute la carte, comme sur Apple Wallet. Sans elle, l'image de fond est affichée entière sur un fond flouté.</p>
              </div>
            )}
            <p className="mt-3 text-[12px] text-[#64748B]">
              Pour tout régler comme dans Pass Designer (style, champs, couleurs, code-barres, import d’un modèle) :{' '}
              <a href="#design-wallet" className="font-semibold text-[#2F6BFF]">Design de la carte</a>, plus haut.
            </p>

            <p className="mb-2 mt-4 text-[12.5px] font-semibold text-[#334155]">
              Boutons sous la carte <span className="font-normal text-[#94A3B8]">— 2 au maximum, Apple choisit l'icône</span>
            </p>
            <FeaturedActionsEditor types={advanced.featured_types || []} value={advanced.featured_actions || []}
                                   onChange={(rows) => setAdvanced({ ...advanced, featured_actions: rows })} />
          </div>

          {/* third row — Google Wallet only */}
          <div className="mt-5 border-t border-[#EEF2F9] pt-5">
            <p className="mb-2 text-[12.5px] font-semibold text-[#334155]">
              Liens sur la carte <span className="font-normal text-[#94A3B8]">— Google Wallet uniquement (sur Apple, utilisez les boutons ci-dessus)</span>
            </p>
            <div className="space-y-2">
              {(advanced.google_links || []).map((row, i) => (
                <div key={i} className="flex gap-2">
                  <Input value={row.label} placeholder="Réserver une table" className="w-1/3"
                         onChange={(e) => setAdvanced({ ...advanced, google_links: advanced.google_links.map((r, j) => (j === i ? { ...r, label: e.target.value } : r)) })} />
                  <Input value={row.uri} placeholder="https://…"
                         onChange={(e) => setAdvanced({ ...advanced, google_links: advanced.google_links.map((r, j) => (j === i ? { ...r, uri: e.target.value } : r)) })} />
                  <button type="button" aria-label="Supprimer le lien"
                          onClick={() => setAdvanced({ ...advanced, google_links: advanced.google_links.filter((_, j) => j !== i) })}
                          className="shrink-0 rounded-lg px-2 text-[#E5484D] hover:bg-[#FEF2F2]"><Trash2 size={15} /></button>
                </div>
              ))}
              {(advanced.google_links || []).length < 3 && (
                <button type="button"
                        onClick={() => setAdvanced({ ...advanced, google_links: [...(advanced.google_links || []), { label: '', uri: '' }] })}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-[#CBD5E1] px-3 py-1.5 text-[12.5px] font-semibold text-[#64748B] hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                  <Plus size={13} /> Ajouter un lien
                </button>
              )}
            </div>
          </div>

          {edit && <div className="mt-4 flex items-center gap-3 border-t border-[#EEF2F9] pt-4">
            <button type="button" onClick={save} disabled={saving}
                    className="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-60"
                    style={{ background: BLUE }}>
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} Enregistrer les options
            </button>
            <p className="text-[11.5px] text-[#94A3B8]">
              <CalendarClock size={12} className="mr-1 inline" />
              Les cartes déjà dans Wallet sont mises à jour automatiquement.
            </p>
          </div>}
        </Card>
        </div>
      )}

      {/* ── statistics + rewards ── */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_1.15fr]">
        <Card
          icon={CreditCard}
          title="Statistiques de la carte"
          subtitle="Suivez les performances de votre programme."
          action={(
            <div className="w-[160px]">
              <Select value={String(days)} onChange={(e) => setDays(Number(e.target.value))}>
                {WINDOWS.map((w) => <option key={w.d} value={w.d}>{w.label}</option>)}
              </Select>
            </div>
          )}
        >
          {stats ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat icon={CreditCard} tone={{ bg: '#E8F8EE', fg: '#15803D' }} value={stats.cards_active.value}
                    label="Cartes actives" delta={stats.cards_active.delta} hint={stats.cards_active.hint} help="cards_active" />
              <Stat icon={QrCode} tone={{ bg: '#EAF1FF', fg: '#2F6BFF' }} value={stats.qr_scans.value}
                    label="Scans QR code" delta={stats.qr_scans.delta} hint={stats.qr_scans.hint} help="qr_scans" />
              <Stat icon={Gift} tone={{ bg: '#FFF4D6', fg: '#B45309' }} value={stats.rewards_used.value}
                    label="Récompenses utilisées" delta={stats.rewards_used.delta} hint={stats.rewards_used.hint} help="rewards_used" />
              <Stat icon={Users} tone={{ bg: '#F0E9FF', fg: '#7C3AED' }} value={stats.loyal_customers.value}
                    label="Clients fidèles" delta={stats.loyal_customers.delta} hint={stats.loyal_customers.hint} help="loyal" />
            </div>
          ) : (
            <div className="flex h-[132px] items-center justify-center text-[#94A3B8]"><Loader2 className="animate-spin" size={18} /></div>
          )}
        </Card>

        <Card
          icon={Gift}
          title="Récompenses et paliers"
          help="tiers"
          subtitle="Configurez les récompenses et visualisez les paliers de fidélité."
          action={edit && (
            <button type="button" onClick={() => (editTiers ? saveTiers() : setEditTiers(true))} disabled={saving}
                    className="inline-flex items-center gap-2 rounded-xl border border-[#E1E8F5] bg-white px-3 py-2 text-[12.5px] font-semibold text-[#334155] hover:border-[#2F6BFF] hover:text-[#2F6BFF] disabled:opacity-60">
              {editTiers ? <><Check size={14} /> Enregistrer</> : <><Settings2 size={14} /> Gérer les récompenses</>}
            </button>
          )}
        >
          {/* Each rung shows its upper number — « 200 points », not « 0 · 200 » —
              and the last one « 600+ points » (user, 2026-10-02). Editing works
              on the same numbers: a rung's ceiling is the next rung's floor. */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {tiers.map((t, i) => (
              <div key={t.key} className="text-center">
                <span className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full" style={{ background: `${TIER_TONE[i]}1F`, color: TIER_TONE[i] }}>
                  <Star size={17} fill="currentColor" />
                </span>
                {editTiers ? (
                  <div className="space-y-1.5">
                    {i < tiers.length - 1 ? (
                      <Input type="number" min="1" value={tiers[i + 1].min} className="py-1.5 text-center text-[12px]"
                             aria-label={`Plafond du palier ${t.label}`}
                             onChange={(e) => setTiers(tiers.map((x, j) => (j === i + 1 ? { ...x, min: e.target.value } : x)))} />
                    ) : (
                      <div className="rounded-xl border border-dashed border-[#E1E8F5] py-1.5 text-[12px] font-semibold text-[#64748B]">
                        {tiers[i].min}+ {unit}
                      </div>
                    )}
                    <Input value={t.reward} className="py-1.5 text-center text-[12px]" placeholder="Récompense"
                           onChange={(e) => setTiers(tiers.map((x, j) => (j === i ? { ...x, reward: e.target.value } : x)))} />
                  </div>
                ) : (
                  <>
                    <div className="text-[12px] font-semibold text-[#0B1C3F]">
                      {i < tiers.length - 1 ? `${tiers[i + 1].min} ${unit}` : `${t.min}+ ${unit}`}
                    </div>
                    <div className="mt-1 text-[12px] text-[#64748B]">{t.reward || '—'}</div>
                    <div className="mt-0.5 text-[11px] font-semibold" style={{ color: TIER_TONE[i] }}>{t.label}</div>
                  </>
                )}
              </div>
            ))}
          </div>
          {tierError && <p className="mt-3 rounded-xl bg-[#FEECEC] px-3 py-2 text-center text-[12px] text-[#C0392B]">{tierError}</p>}
          {editTiers && (
            <p className="mt-3 text-center text-[11.5px] text-[#94A3B8]">
              Le nombre de {unit} jusqu'où va chaque palier, croissant. Le dernier commence là où s'arrête le précédent.
              <button type="button" onClick={() => { setEditTiers(false); setTierError(''); load(); }} className="ml-2 inline-flex items-center gap-1 text-[#64748B] underline">
                <X size={11} /> annuler
              </button>
            </p>
          )}
          <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] p-3">
            <Lightbulb size={16} className="mt-0.5 shrink-0 text-[#B45309]" />
            <div>
              <p className="text-[12.5px] font-bold text-[#92400E]">Astuce</p>
              <p className="text-[12px] text-[#92400E]/90">Proposez des récompenses attractives pour encourager vos clients à revenir plus souvent !</p>
            </div>
          </div>
        </Card>
      </div>


      {/* ── the save bar — always on screen, so « Enregistrer » never has to be
          hunted for at the bottom of a column (Safari hid it, user 2026-10-02). ── */}
      {/* Fixed, not sticky: the layout's scroll container would hold a sticky
          bar at the foot of the page, out of sight. */}
      {edit && (dirty || saving || justSaved) && (
        <div className="fixed right-4 z-40 max-w-[calc(100vw-32px)] sm:right-6" style={{ bottom: 'calc(16px + env(safe-area-inset-bottom))' }}>
          <div className={`flex flex-wrap items-center justify-between gap-3 rounded-2xl border bg-white px-4 py-3 shadow-[0_18px_44px_-16px_rgba(11,28,63,.5)] ${
            dirty ? 'border-[#BFD3FF]' : 'border-[#E6EEFB]'}`}>
            <p className="flex items-center gap-2 text-[13px] font-semibold">
              {dirty ? (
                <><span className="h-2.5 w-2.5 rounded-full bg-[#F59E0B]" /><span className="text-[#0B1C3F]">Modifications non enregistrées</span></>
              ) : (
                <><Check size={15} className="text-[#15803D]" /><span className="text-[#15803D]">
                  {saving ? 'Enregistrement…' : `Modifications enregistrées${savedAt?.wallet > 0 ? ` · ${savedAt.wallet} carte${savedAt.wallet > 1 ? 's' : ''} Wallet mise${savedAt.wallet > 1 ? 's' : ''} à jour` : ''}`}
                </span></>
              )}
            </p>
            <div className="flex items-center gap-2">
              {dirty && (
                <button type="button" onClick={discard} disabled={saving}
                        className="rounded-xl border border-[#E1E8F5] bg-white px-3.5 py-2.5 text-[13px] font-semibold text-[#334155] hover:border-[#2F6BFF] disabled:opacity-60">
                  Annuler
                </button>
              )}
              <button type="button" onClick={save} disabled={!dirty || saving}
                      className="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50"
                      style={{ background: BLUE, boxShadow: dirty ? '0 10px 22px -12px rgba(47,107,255,.8)' : 'none' }}>
                {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} Enregistrer les modifications
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Aperçu client — the card exactly as the customer opens it ── */}
      {customerPreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/60 p-6" onClick={() => setCustomerPreview(false)}>
          <div className="w-full max-w-[420px] rounded-2xl bg-white p-5" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <p className="text-[14px] font-bold text-[#0B1C3F]">Aperçu client</p>
                <p className="text-[12px] text-[#64748B]">Ce que voit votre client en ouvrant sa carte.</p>
              </div>
              <button type="button" onClick={() => setCustomerPreview(false)} aria-label="Fermer"
                      className="flex h-9 w-9 items-center justify-center rounded-full text-[#64748B] hover:bg-[#F1F5F9]"><X size={18} /></button>
            </div>
            <div className="rounded-2xl bg-[#F4F7FC] p-4">
              <WalletCard customer={previewCustomer} tenant={{ name: data?.tenant?.name }} card={cardForPreview} />
            </div>
            {data?.tenant?.slug && (
              <a href={`/join/${data.tenant.slug}`} target="_blank" rel="noreferrer"
                 className="mt-3 block text-center text-[12.5px] font-semibold text-[#2F6BFF] underline underline-offset-2">
                Ouvrir le formulaire d'inscription client
              </a>
            )}
          </div>
        </div>
      )}
      {cropReq && (
        <PosterCropper file={cropReq.file}
                       onDone={(d) => { cropReq.resolve(d); setCropReq(null); }}
                       onCancel={() => { cropReq.resolve(advanced?.poster_image_url || ''); setCropReq(null); }} />
      )}
    </div>
  );
}
