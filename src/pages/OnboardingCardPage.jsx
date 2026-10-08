import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Upload, Pipette, Store, PenLine, X, ImagePlus, Trash2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { onboardingAPI } from '../lib/api';
import WalletPassLive from '../components/WalletPassLive';
import OnboardingShell, { Field, FieldLabel, INPUT, StepButtons } from '../components/OnboardingShell';
import { OWNER_HOME } from '../lib/modules';

/**
 * OnboardingCardPage — STEP 4 of 4, optional: "Configuration de votre carte" (approved mockup).
 *
 * The preview on the left IS the customer's card: it renders
 * <WalletPassLive> — the pass as the server builds it, the pkpass-faithful component MyWalletCardPage shows
 * once a customer joins (real Apple Wallet storeCard geometry), fed with the
 * same template fields this page saves. Nothing is mocked — what the merchant
 * sees here is what their customers get, on the web card and on the native
 * pass alike.
 *
 *   logo              → logo_url         (base64, downscaled client-side)
 *   couleur principale→ surface_color    (the card body)
 *   couleur secondaire→ brand_color      (accent: stamps, meter, tier ring)
 *   nom sur la carte  → card_name        (falls back to tenant.name)
 *   slogan            → tagline
 *
 * Saved through POST /api/owner/card-template with layout_style="wallet" so
 * the wallet-anatomy render is active from day one; every other knob
 * (hero photo, stamps, offer chip, labels…) stays editable in Card Designer.
 * The same fields are what an Apple / Google Wallet pass is built from
 * (logo, background colour, label colour, organisation name, barcode), so the
 * native passes will carry this exact design too.
 */
const DEFAULTS = { surface_color: '#000000', brand_color: '#D4AF37', card_name: '', tagline: '', logo_url: '', hero_image_url: '' };
const HEX = /^#[0-9a-f]{6}$/i;

// Preview customer — the numbers on the mockup card ("Points 150 · Gold").

/** Downscale the picked logo to ≤320px so the base64 stays far below the
 *  API's body limit (large PNG uploads used to 413). Returns a data URL. */
function readLogo(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const max = 320; const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL(file.type === 'image/png' || file.type === 'image/svg+xml' ? 'image/png' : 'image/jpeg', 0.9));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('bad image')); };
    img.src = url;
  });
}

/** Banner (Apple calls it the strip): fixed 375×144 pt, so any photo is
 *  centre-cropped to that ratio at 3× (1125×432) — the size Wallet asks for
 *  on the sharpest screens — and encoded as JPEG to keep the record small. */
function readBanner(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const W = 1125; const H = 432;
      const c = document.createElement('canvas');
      c.width = W; c.height = H;
      const ctx = c.getContext('2d');
      const scale = Math.max(W / img.width, H / img.height);
      const w = img.width * scale; const h = img.height * scale;
      ctx.drawImage(img, (W - w) / 2, (H - h) / 2, w, h);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL('image/jpeg', 0.85));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('bad image')); };
    img.src = url;
  });
}

const ColourField = ({ label, value, onChange }) => {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const commit = (v) => { setText(v); if (HEX.test(v)) onChange(v.toUpperCase()); };
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <div className="flex items-center rounded-xl border border-[#E1E8F5] bg-white px-3 transition focus-within:border-[#2F6BFF] focus-within:ring-4 focus-within:ring-[#2F6BFF]/10">
        <label className="relative h-9 w-9 shrink-0 cursor-pointer overflow-hidden rounded-full border border-[#E1E8F5]" style={{ background: value }} aria-label={label}>
          <input type="color" value={value} onChange={(e) => commit(e.target.value)} className="absolute inset-0 h-full w-full cursor-pointer opacity-0" />
        </label>
        <input type="text" value={text} onChange={(e) => commit(e.target.value)} maxLength={7} spellCheck={false}
               className="min-w-0 flex-1 bg-transparent px-3 py-3.5 text-[15px] uppercase tracking-wide text-[#0F172A] outline-none" />
        <label className="cursor-pointer text-[#2F6BFF]" aria-hidden="true">
          <Pipette size={18} />
          <input type="color" value={value} onChange={(e) => commit(e.target.value)} className="sr-only" />
        </label>
      </div>
    </div>
  );
};

const OnboardingCardPage = () => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const fileRef = useRef(null);
  const bannerRef = useRef(null);
  const [tpl, setTpl] = useState(null);
  const [brand, setBrand] = useState(DEFAULTS);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    onboardingAPI.cardTemplate().then((r) => {
      const d = r.data || {}; const bf = d.brand_fields || {};
      setTpl(d);
      setBrand({
        surface_color: d.surface_color || bf.surface_color || DEFAULTS.surface_color,
        brand_color: d.brand_color || bf.brand_color || DEFAULTS.brand_color,
        card_name: d.card_name || bf.card_name || user?.tenant_name || '',
        tagline: d.tagline || bf.tagline || '',
        logo_url: d.logo_url || bf.logo_url || '',
        hero_image_url: d.hero_image_url || bf.hero_image_url || '',
      });
    }).catch(() => setTpl({}));
  }, [user?.tenant_name]);

  const set = (k) => (v) => setBrand((b) => ({ ...b, [k]: v }));

  const pickLogo = async (e) => {
    const f = e.target.files?.[0]; e.target.value = '';
    if (!f) return;
    try { set('logo_url')(await readLogo(f)); setError(''); } catch { setError(t('card_step.logo_invalid')); }
  };

  const pickBanner = async (e) => {
    const f = e.target.files?.[0]; e.target.value = '';
    if (!f) return;
    try { set('hero_image_url')(await readBanner(f)); setError(''); } catch { setError(t('card_step.logo_invalid')); }
  };

  // The card the customer will see, built from exactly what is being saved.
  const card = useMemo(() => ({
    layout_style: 'wallet', hero_mode: brand.hero_image_url ? 'image' : 'none', code_type: 'qr',
    hero_image_url: brand.hero_image_url,
    surface: '', surface_color: brand.surface_color, brand_color: brand.brand_color,
    logo_url: brand.logo_url, card_name: brand.card_name.trim(), tagline: brand.tagline.trim(),
    reward_threshold_stamps: tpl?.reward_threshold_stamps || 10,
    points_per_visit: tpl?.points_per_visit || 10,
  }), [brand, tpl]);
  const tenant = { name: user?.tenant_name || '' };

  const save = async (e) => {
    e.preventDefault();
    setError('');
    if (!brand.logo_url) return setError(t('card_step.logo_required'));
    if (!brand.card_name.trim()) return setError(t('card_step.name_required'));
    setSaving(true);
    try {
      // Same shape CardDesignerPage writes: brand_fields carries every design
      // key; the ones the customer-card serializer reads at top level are
      // mirrored there too (top level wins on read).
      const fields = { ...card };
      await onboardingAPI.saveCardTemplate({
        ...(tpl || {}),
        brand_fields: { ...((tpl && tpl.brand_fields) || {}), ...fields },
        ...fields,
      });
      navigate('/onboarding/termine', { replace: true });
    } catch (err) {
      setSaving(false);
      setError(err?.response?.data?.detail || err?.message || t('onboarding.failed'));
    }
  };

  return (
    <OnboardingShell step={4} wide>
      <div className="mt-8 text-center">
        <h1 className="text-[36px] font-extrabold tracking-[-0.02em] text-[#0B1C3F]">{t('card_step.title')}</h1>
        <p className="mt-2 text-[16px] text-[#4B5C7A]">{t('card_step.subtitle')}</p>
      </div>
      {error && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">⚠ {error}</div>}

      <form onSubmit={save} className="mt-7 grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,.95fr)_minmax(0,1.05fr)]">
        {/* ── live preview: the real customer card ── */}
        <div>
          <p className="mb-2 text-[15px] font-semibold text-[#0B1C3F]">{t('card_step.preview')}</p>
          <div className="rounded-2xl border border-dashed border-[#C9D6F2] bg-[#F7FAFF] p-3">
            <div className="mx-auto w-fit"><WalletPassLive card={card} width={236} /></div>
            <button type="button" onClick={() => setFullscreen(true)} className="mt-3 block w-full text-center text-[13px] font-medium text-[#2F6BFF] underline underline-offset-2">
              {t('card_step.preview_full')}
            </button>
          </div>
        </div>

        {/* ── controls ── */}
        <div className="space-y-5">
          <div>
            <FieldLabel>{t('card_step.logo')}</FieldLabel>
            <div className="flex items-center gap-4 rounded-xl border border-[#E1E8F5] bg-white p-3">
              <div className="flex h-[76px] w-[110px] shrink-0 items-center justify-center overflow-hidden rounded-lg bg-[#F4F7FC]">
                {brand.logo_url
                  ? <img src={brand.logo_url} alt="" className="max-h-full max-w-full object-contain" />
                  : <Store size={28} className="text-[#94A3B8]" />}
              </div>
              <button type="button" onClick={() => fileRef.current?.click()}
                      className="ml-auto inline-flex items-center gap-2 rounded-xl bg-[#EEF4FF] px-4 py-2.5 text-[14px] font-semibold text-[#2F6BFF] hover:bg-[#E2ECFF]">
                <Upload size={16} /> {brand.logo_url ? t('card_step.logo_change') : t('card_step.logo_add')}
              </button>
              <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" className="hidden" onChange={pickLogo} />
            </div>
          </div>
          <div>
            <FieldLabel optional>{t('card_step.banner')}</FieldLabel>
            <div className="rounded-xl border border-[#E1E8F5] bg-white p-3">
              <div className="relative overflow-hidden rounded-lg bg-[#F4F7FC]" style={{ aspectRatio: '375 / 144' }}>
                {brand.hero_image_url ? (
                  <img src={brand.hero_image_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-[#94A3B8]">
                    <ImagePlus size={22} />
                    <span className="text-[12px]">{t('card_step.banner_hint')}</span>
                  </div>
                )}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <button type="button" onClick={() => bannerRef.current?.click()}
                        className="inline-flex items-center gap-2 rounded-xl bg-[#EEF4FF] px-4 py-2.5 text-[14px] font-semibold text-[#2F6BFF] hover:bg-[#E2ECFF]">
                  <Upload size={16} /> {brand.hero_image_url ? t('card_step.banner_change') : t('card_step.banner_add')}
                </button>
                {brand.hero_image_url && (
                  <button type="button" onClick={() => set('hero_image_url')('')}
                          className="inline-flex items-center gap-2 rounded-xl px-3 py-2.5 text-[14px] font-medium text-[#64748B] hover:text-[#E5484D]">
                    <Trash2 size={16} /> {t('card_step.banner_remove')}
                  </button>
                )}
              </div>
              <input ref={bannerRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={pickBanner} />
            </div>
          </div>
          <ColourField label={t('card_step.colour_primary')} value={brand.surface_color} onChange={set('surface_color')} />
          <ColourField label={t('card_step.colour_secondary')} value={brand.brand_color} onChange={set('brand_color')} />
          <div>
            <FieldLabel>{t('card_step.name')}</FieldLabel>
            <Field icon={Store}>
              <input required type="text" maxLength={40} placeholder={t('card_step.name_placeholder')} className={INPUT}
                     value={brand.card_name} onChange={(e) => set('card_name')(e.target.value)} />
            </Field>
          </div>
          <div>
            <FieldLabel optional>{t('card_step.slogan')}</FieldLabel>
            <Field icon={PenLine}>
              <input type="text" maxLength={60} placeholder={t('card_step.slogan_placeholder')} className={INPUT}
                     value={brand.tagline} onChange={(e) => set('tagline')(e.target.value)} />
            </Field>
          </div>
        </div>

        <div className="md:col-span-2">
          <StepButtons onBack={() => navigate('/onboarding/formule')} backLabel={t('onboarding.back')}
                       nextLabel={saving ? t('auth.creating') : t('card_step.finish')} loading={saving} />
          {/* Optional step (user, 2026-10-04): the card can be designed later
              from Carte de fidélité; the trial is already running. */}
          <button type="button" onClick={() => navigate(OWNER_HOME, { replace: true })}
                  className="mx-auto mt-4 block text-[14px] font-semibold text-[#2F6BFF] hover:underline">
            {t('card_step.skip')}
          </button>
        </div>
      </form>

      {fullscreen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/70 p-6" onClick={() => setFullscreen(false)}>
          <div className="w-full max-w-[400px]" onClick={(e) => e.stopPropagation()}>
            <button type="button" onClick={() => setFullscreen(false)} className="mb-3 ml-auto flex h-10 w-10 items-center justify-center rounded-full bg-white text-[#0B1C3F]" aria-label="close"><X size={20} /></button>
            <div className="mx-auto w-fit"><WalletPassLive card={card} width={375} /></div>
          </div>
        </div>
      )}
    </OnboardingShell>
  );
};
export default OnboardingCardPage;
