import React from 'react';
import { Plus, Trash2, Upload, X } from 'lucide-react';
import PosterCropper from '../PosterCropper';
import { FIELD_VARS } from './walletLook';

/**
 * The Google Wallet side of « Design de la carte » (user, 2026-10-08): what
 * Google lets a loyalty card change — one colour, a round or wide logo, the
 * hero banner, up to three rows of values, the barcode, the « Détails »
 * screen, and which events notify. Saved with the page (card settings
 * google_design + google_links); the server cleans it (clean_google_design).
 *
 * Props: tab, value (google_design), onChange(patch), links, onLinksChange,
 * rowFields ({key: label}), codes ({TYPE: label}), disabled.
 */
const inputCls = 'w-full rounded-lg border border-[#E1E8F5] bg-white px-3 py-2 text-[12.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
const Lbl = ({ children, hint }) => (
  <p className="mb-1 text-[12px] font-semibold text-[#334155]">{children}{hint && <span className="ml-1 font-normal text-[#94A3B8]">{hint}</span>}</p>
);
async function fitPng(file, mw, mh) {
  const src = await readFile(file);
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = src; });
  const k = Math.min(1, mw / img.width, mh / img.height);
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(img.width * k)); c.height = Math.max(1, Math.round(img.height * k));
  c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL('image/png');
}
const readFile = (f) => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });

export default function GoogleDesignEditor({ tab, value = {}, onChange, links = [], onLinksChange, rowFields = {}, codes = {}, disabled }) {
  const [crop, setCrop] = React.useState(null);
  const v = value || {};
  const rows = v.rows || [];
  const set = (patch) => onChange(patch);
  const pickImage = async (key, file, w, h) => {
    if (!file) return;
    // a logo keeps its transparency: fitted as a PNG, never cropped
    const url = key === 'wide_logo' ? await fitPng(file, w, h)
      : await new Promise((resolve) => setCrop({ file, w, h, resolve }));
    if (url) set({ [key]: url, ...(key === 'hero_image' ? { hero: 'photo' } : { logo: 'wide' }) });
  };

  return (
    <fieldset disabled={disabled} className="m-0 min-w-0 border-0 p-0">
      {tab === 'g_couleur' && (
        <div className="space-y-4">
          <div>
            <Lbl hint="Google choisit lui-même la couleur du texte">Couleur de la carte</Lbl>
            <div className="flex items-center gap-2">
              <input type="color" value={v.bg_color || '#1C1D22'} onChange={(e) => set({ bg_color: e.target.value })}
                     className="h-9 w-12 cursor-pointer rounded-md border border-[#E1E8F5] bg-white p-0.5" />
              <input className={`${inputCls} max-w-[140px]`} value={v.bg_color || ''} placeholder="#691B1B"
                     onChange={(e) => set({ bg_color: e.target.value })} />
              {v.bg_color && <button type="button" onClick={() => set({ bg_color: undefined })} className="text-[12px] font-semibold text-[#64748B]">Couleur de la carte Apple</button>}
            </div>
          </div>
          <div>
            <Lbl hint="sous le logo, en grand">Nom du programme</Lbl>
            <input className={inputCls} value={v.program_name || ''} placeholder="Le nom de la carte (Identité)"
                   onChange={(e) => set({ program_name: e.target.value })} />
          </div>
          <div>
            <Lbl>Logo</Lbl>
            <div className="grid grid-cols-2 gap-2">
              {[['round', 'Logo rond + nom', 'Votre logo (Identité), Google le met dans un cercle'],
                ['wide', 'Logo large', 'Une bannière de logo à la place du logo rond et du nom']].map(([k, l, h]) => (
                <button key={k} type="button" onClick={() => set({ logo: k })}
                        className={`rounded-lg border px-2.5 py-2 text-left text-[12px] font-semibold ${(v.logo || 'round') === k ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#E6EEFB] bg-white text-[#334155]'}`}>
                  {l}<span className="mt-0.5 block text-[10.5px] font-normal text-[#94A3B8]">{h}</span>
                </button>
              ))}
            </div>
            {(v.logo === 'wide' || v.wide_logo) && (
              <div className="mt-2 flex items-center gap-2">
                {v.wide_logo && <img src={v.wide_logo} alt="" className="h-9 max-w-[160px] rounded border border-[#E6EEFB] object-contain" />}
                <label className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-[#E1E8F5] px-2.5 py-1.5 text-[12px] font-semibold text-[#334155]">
                  <Upload size={12} /> {v.wide_logo ? 'Changer' : 'Ajouter le logo large'} (1280 × 400)
                  <input type="file" accept="image/*" className="hidden" onChange={(e) => { pickImage('wide_logo', e.target.files?.[0], 1280, 400); e.target.value = ''; }} />
                </label>
                {v.wide_logo && <button type="button" onClick={() => set({ wide_logo: undefined, logo: 'round' })} className="text-[12px] font-semibold text-[#E5484D]">Retirer</button>}
              </div>
            )}
            <p className="mt-1 text-[11.5px] text-[#94A3B8]">« Logo rond » et sa bordure (Identité) s’appliquent aussi ici.</p>
          </div>
        </div>
      )}

      {tab === 'g_banniere' && (
        <div className="space-y-2">
          <Lbl hint="en bas de la carte, 1032 × 336">Bannière</Lbl>
          {[['fidclic', 'Bannière FidClic', 'La photo de fond (Identité) avec la jauge de progression'],
            ['photo', 'Ma photo', 'Une image rien que pour Google'],
            ['none', 'Aucune', 'La carte s’arrête au code-barres']].map(([k, l, h]) => (
            <button key={k} type="button" onClick={() => (k === 'photo' && !v.hero_image ? null : set({ hero: k }))}
                    className={`block w-full rounded-lg border px-3 py-2 text-left text-[12px] font-semibold ${(v.hero || 'fidclic') === k ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#E6EEFB] bg-white text-[#334155]'}`}>
              {l}<span className="mt-0.5 block text-[10.5px] font-normal text-[#94A3B8]">{h}</span>
            </button>
          ))}
          <div className="flex items-center gap-2 pt-1">
            {v.hero_image && <img src={v.hero_image} alt="" className="h-12 w-36 rounded border border-[#E6EEFB] object-cover" />}
            <label className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-[#E1E8F5] px-2.5 py-1.5 text-[12px] font-semibold text-[#334155]">
              <Upload size={12} /> {v.hero_image ? 'Changer la photo' : 'Ajouter ma photo'}
              <input type="file" accept="image/*" className="hidden" onChange={(e) => { pickImage('hero_image', e.target.files?.[0], 1032, 336); e.target.value = ''; }} />
            </label>
            {v.hero_image && <button type="button" onClick={() => set({ hero_image: undefined, hero: 'fidclic' })} className="text-[12px] font-semibold text-[#E5484D]">Retirer</button>}
          </div>
        </div>
      )}

      {tab === 'g_lignes' && (
        <div className="space-y-3">
          <p className="text-[12px] text-[#64748B]">Jusqu’à trois lignes sous le nom du programme, une à trois valeurs chacune. Sans ligne, Google affiche les points, la progression et le nom.</p>
          {rows.map((row, i) => (
            <div key={i} className="rounded-xl border border-[#E6EEFB] bg-[#FAFCFF] p-2.5">
              <div className="mb-1.5 flex items-center justify-between">
                <p className="text-[12px] font-bold text-[#0B1C3F]">Ligne {i + 1}</p>
                <button type="button" onClick={() => set({ rows: rows.filter((_, j) => j !== i) })} aria-label="Supprimer la ligne"
                        className="rounded p-1 text-[#E5484D] hover:bg-[#FEF2F2]"><Trash2 size={13} /></button>
              </div>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-3">
                {[0, 1, 2].map((k) => (k <= row.length ? (
                  <select key={k} className={inputCls} value={row[k] || ''}
                          onChange={(e) => {
                            const next = [...row];
                            if (e.target.value) next[k] = e.target.value; else next.splice(k, 1);
                            set({ rows: rows.map((r, j) => (j === i ? next.filter(Boolean) : r)).filter((r) => r.length) });
                          }}>
                    <option value="">{k === 0 ? 'Choisir…' : '— aucune —'}</option>
                    {Object.entries(rowFields).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                  </select>
                ) : null))}
              </div>
            </div>
          ))}
          {rows.length < 3 && (
            <button type="button" onClick={() => set({ rows: [...rows, [Object.keys(rowFields)[0] || 'points']] })}
                    className="inline-flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF]"><Plus size={13} /> Ajouter une ligne</button>
          )}
        </div>
      )}

      {tab === 'g_code' && (
        <div className="space-y-4">
          <div>
            <Lbl>Format</Lbl>
            <select className={inputCls} value={v.barcode || 'QR_CODE'} onChange={(e) => set({ barcode: e.target.value })}>
              {Object.entries(codes).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <p className="mt-1 text-[11.5px] text-[#94A3B8]">Même contenu que sur Apple : le lien de la carte (QR, Aztec, PDF417), le numéro FT-… (Code 128 / 39) ou un code de chiffres (EAN-13, Codabar).</p>
          </div>
          <div>
            <Lbl>Texte sous le code</Lbl>
            <select className={inputCls} value={v.alt_text || 'card'} onChange={(e) => set({ alt_text: e.target.value })}>
              <option value="card">Le numéro de carte du client</option>
              <option value="none">Rien</option>
            </select>
          </div>
        </div>
      )}

      {tab === 'g_details' && (
        <div className="space-y-4">
          <div>
            <Lbl hint="en haut de l’écran Détails">Vos lignes</Lbl>
            <div className="space-y-1.5">
              {(v.details || []).map((r, i) => (
                <div key={i} className="flex gap-1.5">
                  <input className={`${inputCls} w-1/3`} value={r.label} placeholder="Horaires"
                         onChange={(e) => set({ details: v.details.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })} />
                  <input className={inputCls} value={r.value} placeholder="Mar–Sam 9h–19h"
                         onChange={(e) => set({ details: v.details.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)) })} />
                  <select value="" title="Insérer une donnée du client" className="w-10 shrink-0 rounded-lg border border-[#E1E8F5] bg-[#F7FAFF] text-center text-[12px] text-[#2F6BFF]"
                          onChange={(e) => e.target.value && set({ details: v.details.map((x, j) => (j === i ? { ...x, value: `${x.value || ''}${e.target.value}` } : x)) })}>
                    <option value="">＋</option>
                    {FIELD_VARS.filter(([k]) => ['{prenom}', '{nom}', '{carte}', '{points}', '{visites}', '{commerce}'].includes(k)).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                  <button type="button" onClick={() => set({ details: v.details.filter((_, j) => j !== i) })} aria-label="Supprimer"
                          className="shrink-0 rounded-lg px-1.5 text-[#E5484D] hover:bg-[#FEF2F2]"><X size={14} /></button>
                </div>
              ))}
            </div>
            {(v.details || []).length < 6 && (
              <button type="button" onClick={() => set({ details: [...(v.details || []), { label: '', value: '' }] })}
                      className="mt-1.5 inline-flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF]"><Plus size={13} /> Ajouter une ligne</button>
            )}
            <p className="mt-1 text-[11.5px] text-[#94A3B8]">FidClic ajoute ensuite l’offre du moment, la prochaine récompense, le programme, votre adresse, téléphone et site.</p>
          </div>
          <div>
            <Lbl hint="Google n’a pas de boutons : les liens les remplacent">Liens</Lbl>
            <div className="space-y-1.5">
              {(links || []).map((row, i) => (
                <div key={i} className="flex gap-1.5">
                  <input className={`${inputCls} w-1/3`} value={row.label} placeholder="Réserver une table"
                         onChange={(e) => onLinksChange(links.map((r, j) => (j === i ? { ...r, label: e.target.value } : r)))} />
                  <input className={inputCls} value={row.uri} placeholder="https://…"
                         onChange={(e) => onLinksChange(links.map((r, j) => (j === i ? { ...r, uri: e.target.value } : r)))} />
                  <button type="button" onClick={() => onLinksChange(links.filter((_, j) => j !== i))} aria-label="Supprimer le lien"
                          className="shrink-0 rounded-lg px-1.5 text-[#E5484D] hover:bg-[#FEF2F2]"><X size={14} /></button>
                </div>
              ))}
            </div>
            {(links || []).length < 3 && (
              <button type="button" onClick={() => onLinksChange([...(links || []), { label: '', uri: '' }])}
                      className="mt-1.5 inline-flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF]"><Plus size={13} /> Ajouter un lien</button>
            )}
            <p className="mt-1 text-[11.5px] text-[#94A3B8]">« Ma carte en ligne » et le lien d’une offre en cours sont ajoutés tout seuls.</p>
          </div>
        </div>
      )}

      {tab === 'g_notif' && (
        <div className="space-y-2">
          <p className="text-[12px] text-[#64748B]">Google autorise 3 notifications par carte et par jour. Une notification coupée arrive quand même dans la carte, sans sonner.</p>
          {[['campaign', 'Campagnes', 'L’offre envoyée depuis Campagnes'], ['reward', 'Récompense débloquée', 'Quand le client atteint sa récompense'],
            ['birthday', 'Anniversaire', 'Le message d’anniversaire']].map(([k, l, h]) => {
            const on = (v.notify || {})[k] !== false;
            return (
              <label key={k} className="flex cursor-pointer items-start justify-between gap-3 rounded-xl border border-[#E6EEFB] px-3 py-2">
                <span><span className="block text-[12.5px] font-semibold text-[#334155]">{l}</span><span className="block text-[11.5px] text-[#94A3B8]">{h}</span></span>
                <span onClick={(e) => { e.preventDefault(); set({ notify: { ...(v.notify || {}), [k]: !on } }); }}
                      className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition ${on ? 'bg-[#2F6BFF]' : 'bg-[#CBD5E1]'}`}>
                  <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition ${on ? 'left-[18px]' : 'left-0.5'}`} />
                </span>
              </label>
            );
          })}
        </div>
      )}

      {crop && (
        <PosterCropper file={crop.file} outW={crop.w} outH={crop.h} guides={false}
                       title={crop.w === 1032 ? 'Cadrer la bannière Google' : 'Cadrer le logo large'}
                       onDone={(url) => { crop.resolve(url); setCrop(null); }}
                       onCancel={() => { crop.resolve(null); setCrop(null); }} />
      )}
    </fieldset>
  );
}
