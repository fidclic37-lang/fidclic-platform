import React, { useEffect, useState } from 'react';
import { ImagePlus, X, UploadCloud, CheckCircle, AlertCircle, RefreshCw } from 'lucide-react';
import { ownerAPI } from '../lib/api';

// Google Wallet section of the Card Designer.
//
// The Card Designer above is the source of truth: logo, brand colour,
// business name, reward text and links are auto-mapped into the merchant's
// Google Wallet class by the backend. This block only adds the Wallet-specific
// extras (optional banner, programme name, points label), a Google-style
// preview, the publish status and the "Publier sur Google Wallet" action.
//
// The class is created ONLY when the owner clicks Publier — never
// automatically. Re-publishing updates the same class (Google pushes the
// new look to every saved pass).

// Same approach as the designer's own uploader: re-encode client-side so
// the stored data URL stays small. Google's hero is ~3:1 (1032×336).
function compressImage(file, maxDim = 1200, quality = 0.82) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement('canvas');
        canvas.width = w; canvas.height = h;
        canvas.getContext('2d').drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL('image/jpeg', quality));
      };
      img.onerror = reject;
      img.src = e.target.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// Google picks black or white text from the background — mirror that.
function textOn(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return '#FFFFFF';
  const n = parseInt(m[1], 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.6 ? '#1F1F1F' : '#FFFFFF';
}

function errMsg(e) {
  const d = e?.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object' && d.message) return d.message;
  return e?.message || 'Erreur inconnue';
}

export default function GoogleWalletSection({ brand, rules, tenant, saveDesign }) {
  const [status, setStatus] = useState(null);
  const [programmeName, setProgrammeName] = useState('');
  const [pointsLabel, setPointsLabel] = useState('');
  const [busy, setBusy] = useState('');        // '' | 'load' | 'settings' | 'hero' | 'publish'
  const [msg, setMsg] = useState(null);        // { kind: 'ok'|'err', text }

  const flash = (kind, text) => { setMsg({ kind, text }); setTimeout(() => setMsg(null), 6000); };

  const applyStatus = (data) => {
    setStatus(data);
    setProgrammeName(data?.programme_name || '');
    setPointsLabel(data?.points_label || '');
  };

  useEffect(() => {
    (async () => {
      setBusy('load');
      try { applyStatus((await ownerAPI.getGoogleWalletStatus()).data); }
      catch (_e) { /* section renders in its empty state */ }
      finally { setBusy(''); }
    })();
  }, []);

  const saveSettings = async () => {
    setBusy('settings');
    try {
      applyStatus((await ownerAPI.saveGoogleWalletSettings({ programme_name: programmeName, points_label: pointsLabel })).data);
      flash('ok', 'Réglages Google Wallet enregistrés.');
    } catch (e) { flash('err', errMsg(e)); }
    finally { setBusy(''); }
  };

  const uploadHero = async (file) => {
    setBusy('hero');
    try {
      const dataUrl = await compressImage(file, 1200, 0.85);
      applyStatus((await ownerAPI.uploadGoogleWalletHero(dataUrl)).data);
      flash('ok', 'Bannière Google Wallet enregistrée.');
    } catch (e) { flash('err', errMsg(e)); }
    finally { setBusy(''); }
  };

  const removeHero = async () => {
    setBusy('hero');
    try { applyStatus((await ownerAPI.deleteGoogleWalletHero()).data); }
    catch (e) { flash('err', errMsg(e)); }
    finally { setBusy(''); }
  };

  const publish = async () => {
    setBusy('publish');
    try {
      // The class is built from the SAVED design — persist the designer first
      // so the logo/colour the owner sees is what Google receives.
      if (typeof saveDesign === 'function') await saveDesign();
      const res = await ownerAPI.publishGoogleWallet();
      applyStatus(res.data);
      const action = res.data?.result?.action === 'created' ? 'publiée' : 'mise à jour';
      flash('ok', `Carte Google Wallet ${action}. Les nouveaux clients recevront votre design.`);
    } catch (e) { flash('err', errMsg(e)); }
    finally { setBusy(''); }
  };

  // ── Preview data: live designer values win over what the server last saw ──
  const preview = status?.preview || {};
  const bg = (brand?.layout_style === 'wallet' && brand?.brand_color) || brand?.primary_color || preview.background_color || '#B85C38';
  const fg = textOn(bg);
  const logo = brand?.logo_url || preview.logo_url || '';
  const hero = preview.hero_url || brand?.hero_image_url || '';
  const businessName = tenant?.name || tenant?.business_name || preview.business_name || 'Mon commerce';
  const programme = programmeName.trim() || preview.programme_name || businessName;
  const ptsLabel = pointsLabel.trim() || brand?.points_label || preview.points_label || 'Points';
  const reward = rules?.reward_description || preview.reward_text || '';
  const threshold = parseInt(rules?.reward_threshold_stamps, 10) || 10;

  const published = status?.class_status === 'active';
  const configured = status ? status.configured : true;

  return (
    <div className="rounded-xl border border-[#E9E5E0] bg-white p-5 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <UploadCloud size={20} className="text-[#B85C38]" />
          <h2 className="text-lg font-bold text-[#171412]">Google Wallet — votre carte sur Android</h2>
        </div>
        {published ? (
          <span className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full" style={{ background: '#E8F3EA', color: '#20714C' }}>
            <CheckCircle size={12} /> Publiée
            {status?.review_status && status.review_status !== 'APPROVED' ? ' · en attente Google' : ''}
          </span>
        ) : (
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-[#FAFAF8] border border-[#E9E5E0] text-[#57504A]">Non publiée</span>
        )}
      </div>
      <p className="text-xs text-[#57504A] -mt-2">
        Votre logo, votre couleur de marque, le nom de l'établissement, la récompense et vos liens
        sont repris automatiquement du design ci-dessus. Ajoutez seulement une bannière si vous le
        souhaitez, puis cliquez sur <b>Publier sur Google Wallet</b>. Tant que vous ne publiez pas,
        vos clients reçoivent la carte FIDCLIC générique.
      </p>

      {!configured && (
        <div className="text-xs rounded-lg px-3 py-2" style={{ background: '#FFF4E5', color: '#8A4B00' }}>
          Google Wallet n'est pas configuré sur ce serveur. Contactez le support Fidclic.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[1fr,300px] gap-6">
        {/* Editor column */}
        <div className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-[#57504A] mb-1">Nom du programme</label>
              <input
                type="text" maxLength={40} value={programmeName} placeholder={businessName}
                onChange={(e) => setProgrammeName(e.target.value)}
                className="w-full border border-[#E9E5E0] rounded-lg px-3 py-2 text-sm"
              />
              <p className="text-[11px] text-[#8D857D] mt-1">Affiché en haut de la carte. Par défaut : le nom de l'établissement.</p>
            </div>
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-[#57504A] mb-1">Libellé des points</label>
              <input
                type="text" maxLength={20} value={pointsLabel} placeholder={brand?.points_label || 'Points'}
                onChange={(e) => setPointsLabel(e.target.value)}
                className="w-full border border-[#E9E5E0] rounded-lg px-3 py-2 text-sm"
              />
              <p className="text-[11px] text-[#8D857D] mt-1">Ex. « Points », « Tampons », « Cafés ».</p>
            </div>
          </div>

          {/* Optional banner */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-[#57504A] mb-1">
              Bannière Google Wallet (optionnelle, format large ≈ 3:1)
            </label>
            <p className="text-[11px] text-[#8D857D] mb-2">
              Sans bannière, la photo de la carte ci-dessus est utilisée si elle existe.
            </p>
            <div className="flex items-center gap-3">
              {hero ? (
                <div className="relative">
                  <img src={hero} alt="" className="w-40 h-14 rounded-lg object-cover border border-[#E9E5E0]" />
                  {status?.has_wallet_hero && (
                    <button type="button" onClick={removeHero} disabled={busy === 'hero'}
                      className="absolute -top-2 -right-2 w-7 h-7 rounded-full bg-[#171412] text-white flex items-center justify-center shadow-md"
                      aria-label="Supprimer la bannière">
                      <X size={14} />
                    </button>
                  )}
                </div>
              ) : (
                <div className="w-40 h-14 rounded-lg bg-[#FAFAF8] border border-dashed border-[#D6D3D1] flex items-center justify-center text-[#8D857D]">
                  <ImagePlus size={22} />
                </div>
              )}
              <label className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm font-medium text-[#171412] cursor-pointer hover:bg-[#FAFAF8]">
                <ImagePlus size={14} />
                {busy === 'hero' ? 'Envoi…' : (status?.has_wallet_hero ? 'Changer la bannière' : 'Téléverser une bannière')}
                <input type="file" accept="image/*" className="hidden" disabled={busy === 'hero'}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadHero(f); e.target.value = ''; }} />
              </label>
            </div>
          </div>

          {msg && (
            <div className="flex items-start gap-2 text-sm rounded-lg px-3 py-2"
              style={msg.kind === 'ok' ? { background: '#E8F3EA', color: '#20714C' } : { background: '#FDECEC', color: '#A32D2D' }}>
              {msg.kind === 'ok' ? <CheckCircle size={16} className="mt-0.5 shrink-0" /> : <AlertCircle size={16} className="mt-0.5 shrink-0" />}
              <span>{msg.text}</span>
            </div>
          )}
          {!msg && status?.last_error && (
            <div className="flex items-start gap-2 text-sm rounded-lg px-3 py-2" style={{ background: '#FDECEC', color: '#A32D2D' }}>
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <span>Dernière publication refusée par Google : {status.last_error}</span>
            </div>
          )}

          <div className="flex flex-wrap gap-2 items-center">
            <button type="button" onClick={saveSettings} disabled={!!busy}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold border border-[#E9E5E0] text-[#171412] hover:bg-[#FAFAF8] disabled:opacity-50">
              {busy === 'settings' ? 'Enregistrement…' : 'Enregistrer les réglages'}
            </button>
            <button type="button" onClick={publish} disabled={!!busy || !configured}
              className="inline-flex items-center gap-2 px-5 py-2 rounded-full text-sm font-semibold text-white shadow-md hover:-translate-y-0.5 transition-all disabled:opacity-50"
              style={{ background: '#1F1F1F' }}>
              {busy === 'publish' ? <RefreshCw size={14} className="animate-spin" /> : <UploadCloud size={14} />}
              {busy === 'publish' ? 'Publication…' : (published ? 'Mettre à jour sur Google Wallet' : 'Publier sur Google Wallet')}
            </button>
          </div>
          <p className="text-[11px] text-[#8D857D]">
            Google affiche la mention « TEST ONLY » sur les cartes tant que la validation Google de
            l'émetteur Fidclic n'est pas terminée. Les clients qui avaient déjà ajouté la carte
            générique la conservent ; les nouveaux reçoivent votre design.
          </p>
        </div>

        {/* Google Wallet-style preview */}
        <div className="flex flex-col items-center">
          <div className="text-[10px] uppercase tracking-widest text-[#8D857D] mb-2">Aperçu Google Wallet</div>
          <div className="w-[280px] rounded-2xl overflow-hidden shadow-lg" style={{ background: bg, color: fg, fontFamily: 'Roboto, Inter, system-ui, sans-serif' }}>
            <div className="flex items-center gap-3 px-4 pt-4 pb-2">
              <div className="w-9 h-9 rounded-full overflow-hidden flex items-center justify-center shrink-0" style={{ background: 'rgba(255,255,255,0.9)' }}>
                {logo ? <img src={logo} alt="" className="w-full h-full object-cover" /> : <span className="text-[10px] text-[#8D857D]">logo</span>}
              </div>
              <div className="min-w-0">
                <div className="text-[11px] opacity-80 truncate">{businessName}</div>
                <div className="text-sm font-semibold truncate">{programme}</div>
              </div>
            </div>
            <div className="px-4 pb-3 grid grid-cols-2 gap-3">
              <div>
                <div className="text-[10px] uppercase opacity-70">Membre</div>
                <div className="text-sm font-medium">Marie Dupont</div>
              </div>
              <div>
                <div className="text-[10px] uppercase opacity-70 truncate">{ptsLabel}</div>
                <div className="text-sm font-medium">120</div>
              </div>
            </div>
            {hero ? (
              <img src={hero} alt="" className="w-full h-[90px] object-cover" />
            ) : null}
            <div className="px-4 py-3 space-y-2" style={{ background: 'rgba(255,255,255,0.96)', color: '#1F1F1F' }}>
              <div className="flex justify-center">
                <div className="w-24 h-24 rounded bg-[#1F1F1F]" style={{ backgroundImage: 'repeating-linear-gradient(90deg,#fff 0 3px,transparent 3px 6px), repeating-linear-gradient(0deg,#fff 0 3px,transparent 3px 6px)', opacity: 0.85 }} />
              </div>
              <div className="text-center text-[10px] tracking-widest text-[#57504A]">FT-A1B2C3D4</div>
              {reward && (
                <div className="text-[11px]">
                  <span className="uppercase text-[10px] text-[#8D857D]">Récompense</span>
                  <div>{reward} — après {threshold} passages</div>
                </div>
              )}
            </div>
          </div>
          <p className="text-[10px] text-[#8D857D] mt-2 text-center">Google impose la mise en page ; vous contrôlez logo, couleur, textes et bannière.</p>
        </div>
      </div>
    </div>
  );
}
