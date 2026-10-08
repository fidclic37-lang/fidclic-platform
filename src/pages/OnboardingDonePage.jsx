import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { QRCodeCanvas, QRCodeSVG } from 'qrcode.react';
import { Download, Printer, Link2, Share2, CheckCircle2, ArrowRight, Eye, X } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { onboardingAPI } from '../lib/api';
import WalletPassLive from '../components/WalletPassLive';
import OnboardingShell from '../components/OnboardingShell';
import { OWNER_HOME } from '../lib/modules';

/**
 * OnboardingDonePage — after step 4: "Votre carte est créée !" (approved mockup).
 *
 * Shows the saved card (the real <WalletPassLive> — the pass as the server builds it, read back from the template
 * just written) next to the tenant's join QR code — the one customers scan
 * to get their card (/join/<slug>). Download / print / copy / share all act
 * on that same link. "Accéder à mon espace établissement" → the dashboard.
 */

const SUPPORT = [
  { key: 'print', icon: Printer },
  { key: 'link',  icon: Link2 },
  { key: 'social', icon: Share2 },
];

const OnboardingDonePage = () => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const qrRef = useRef(null);
  const [card, setCard] = useState(null);
  const [slug, setSlug] = useState(user?.tenant_slug || '');
  const [toast, setToast] = useState('');
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    onboardingAPI.cardTemplate().then((r) => {
      const d = r.data || {};
      // Same merge the customer-card serializer does: brand_fields fills the gaps.
      setCard({ ...(d.brand_fields || {}), ...Object.fromEntries(Object.entries(d).filter(([, v]) => v !== null && v !== '')) });
    }).catch(() => setCard({}));
    if (!slug) onboardingAPI.status().then((r) => setSlug(r.data?.slug || '')).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const joinUrl = useMemo(() => `${window.location.origin}/join/${slug || ''}`, [slug]);
  // printed in the shop: its signups count as « QR code en magasin » (lib/sources)
  const qrUrl = `${joinUrl}/qr`;
  const shopName = card?.card_name || user?.tenant_name || '';
  const tenant = { name: user?.tenant_name || '' };
  const fileStem = (shopName || 'fidclic').replace(/[^\w-]+/g, '-');

  const flash = (msg) => { setToast(msg); setTimeout(() => setToast(''), 2200); };

  const downloadQr = () => {
    const canvas = qrRef.current?.querySelector('canvas');
    if (!canvas) return;
    const a = document.createElement('a');
    a.href = canvas.toDataURL('image/png'); a.download = `qr-${fileStem}.png`; a.click();
  };
  const copyLink = async () => {
    try { await navigator.clipboard.writeText(joinUrl); flash(t('done.copied')); } catch { flash(joinUrl); }
  };
  const share = async () => {
    if (navigator.share) {
      try { await navigator.share({ title: shopName, text: t('done.share_text', { name: shopName }), url: joinUrl }); return; } catch { /* cancelled */ }
    }
    copyLink();
  };
  const actions = { print: () => window.print(), link: copyLink, social: share };

  return (
    <OnboardingShell step={5} wide>
      <div className="mt-8 flex items-center justify-center gap-4">
        <span className="text-[44px] leading-none" aria-hidden="true">🎉</span>
        <h1 className="text-[32px] font-extrabold tracking-[-0.02em] text-[#0B1C3F]">{t('done.title', { name: shopName.toUpperCase() })}</h1>
      </div>
      <p className="mx-auto mt-2 max-w-[480px] text-center text-[16px] text-[#4B5C7A]">{t('done.subtitle')}</p>

      <div className="mt-7 grid grid-cols-1 gap-5 md:grid-cols-[minmax(0,.85fr)_minmax(0,1.15fr)]">
        <div>
          <div className="rounded-2xl border border-[#E6EEFB] bg-white p-3">
            {card ? <div className="mx-auto w-fit"><WalletPassLive card={card} width={220} /></div> : <div className="h-[300px] animate-pulse rounded-xl bg-[#F4F7FC]" />}
          </div>
          <button type="button" onClick={() => setFullscreen(true)} className="mt-2 inline-flex items-center gap-1.5 text-[13px] font-medium text-[#2F6BFF] underline underline-offset-2">
            <Eye size={15} /> {t('done.preview_full')}
          </button>
        </div>

        <div className="rounded-2xl bg-[#F3F7FF] p-5">
          <h2 className="text-[17px] font-bold text-[#0B1C3F]">{t('done.qr_title')}</h2>
          <p className="mt-1 text-[13px] leading-snug text-[#4B5C7A]">{t('done.qr_help')}</p>
          <div className="mt-4 flex items-center gap-4">
            <div ref={qrRef} className="flex-1 rounded-xl bg-white p-4 shadow-[0_8px_24px_-16px_rgba(11,28,63,.35)]">
              <div className="mx-auto w-fit"><QRCodeCanvas value={qrUrl} size={132} level="M" includeMargin={false} /></div>
            </div>
            <button type="button" onClick={downloadQr} aria-label={t('done.download')}
                    className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-white text-[#2F6BFF] shadow-[0_8px_24px_-16px_rgba(11,28,63,.35)] hover:bg-[#EEF4FF]">
              <Download size={22} />
            </button>
          </div>
          <button type="button" onClick={downloadQr}
                  className="mt-4 inline-flex w-full items-center justify-center gap-3 rounded-xl py-3.5 text-[16px] font-semibold text-white"
                  style={{ background: '#0A6CFF', boxShadow: '0 12px 28px -12px rgba(10,108,255,.6)' }}>
            <Download size={18} /> {t('done.download')}
          </button>
        </div>
      </div>

      <p className="mt-6 text-[15px] font-semibold text-[#0B1C3F]">{t('done.other_title')}</p>
      <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {SUPPORT.map(({ key, icon: Icon }) => (
          <button key={key} type="button" onClick={actions[key]}
                  className="inline-flex items-center justify-center gap-2.5 rounded-xl border border-[#E1E8F5] bg-white px-3 py-3.5 text-[14px] font-medium text-[#0B1C3F] hover:border-[#2F6BFF] hover:bg-[#F7FAFF]">
            <Icon size={18} className="text-[#2F6BFF]" /> {t(`done.support_${key}`)}
          </button>
        ))}
      </div>

      <div className="mt-6 flex items-start gap-3 rounded-2xl border border-[#BFE8D2] bg-[#EAF8F0] p-4">
        <CheckCircle2 size={26} className="shrink-0 text-[#1F9D5B]" />
        <div>
          <p className="text-[16px] font-bold text-[#0F5132]">{t('done.active_title')}</p>
          <p className="text-[13px] text-[#2F6B4F]">{t('done.active_sub')}</p>
        </div>
      </div>

      <button type="button" onClick={() => navigate(OWNER_HOME, { replace: true })}
              className="mt-5 inline-flex w-full items-center justify-center gap-3 rounded-2xl py-4 text-[17px] font-semibold text-white transition hover:-translate-y-0.5"
              style={{ background: '#0A6CFF', boxShadow: '0 12px 28px -12px rgba(10,108,255,.6)' }}>
        {t('done.go_dashboard')} <ArrowRight size={20} />
      </button>

      {toast && <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full bg-[#0B1C3F] px-5 py-2.5 text-[14px] text-white shadow-lg">{toast}</div>}

      {fullscreen && card && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/70 p-6" onClick={() => setFullscreen(false)}>
          <div className="w-full max-w-[400px]" onClick={(e) => e.stopPropagation()}>
            <button type="button" onClick={() => setFullscreen(false)} className="mb-3 ml-auto flex h-10 w-10 items-center justify-center rounded-full bg-white text-[#0B1C3F]" aria-label="close"><X size={20} /></button>
            <div className="mx-auto w-fit"><WalletPassLive card={card} width={375} /></div>
          </div>
        </div>
      )}

      {/* Printable A4 poster — only visible when printing ("Imprimer une affiche"). */}
      <div className="fidclic-poster" aria-hidden="true">
        <style>{`
          .fidclic-poster{display:none}
          @media print{
            body *{visibility:hidden}
            .fidclic-poster,.fidclic-poster *{visibility:visible}
            .fidclic-poster{display:flex!important;position:fixed;inset:0;z-index:9999;flex-direction:column;align-items:center;justify-content:center;gap:18px;background:#fff;color:#0B1C3F;font-family:-apple-system,Segoe UI,Roboto,sans-serif;text-align:center;padding:40px}
          }`}</style>
        {card?.logo_url ? <img src={card.logo_url} alt="" style={{ maxHeight: 140, maxWidth: 260, objectFit: 'contain' }} /> : null}
        <div style={{ fontSize: 40, fontWeight: 800 }}>{shopName}</div>
        <div style={{ fontSize: 22 }}>{t('done.poster_line')}</div>
        <QRCodeSVG value={qrUrl} size={320} level="M" />
        <div style={{ fontSize: 16, color: '#4B5C7A' }}>{joinUrl}</div>
        <div style={{ fontSize: 14, color: '#94A3B8' }}>FidClic — {t('done.poster_wallets')}</div>
      </div>
    </OnboardingShell>
  );
};
export default OnboardingDonePage;
