import React, { useMemo, useState } from 'react';
import { Type, Sparkles, RotateCcw } from 'lucide-react';

/**
 * « Nom stylé » (user, 2026-10-13: « MUSEUM mein M bada »): the name beside the
 * logo, letter by letter — each its size, colour and font, symbols too. The
 * server draws it into the logo image (wallet_passes.name_logo), so Apple
 * (iOS 27 and 26) and Google show exactly what is set here.
 *
 *   value = { letters: [{ c, s, color, font }] } | null
 */
const MAX = 40;
const SYMBOLS = ['★', '✦', '✧', '♛', '♚', '✂', '❤', '♥', '✿', '❀', '•', '◆', '☕', '✈', '☀', '♪', '&', '·', '—', '|'];
const API = '/api';

const blank = (c) => ({ c, s: 100, color: null, font: null });

// keep each letter's style when the text changes: same start, same end
function retext(letters, text) {
  const chars = Array.from(text).slice(0, MAX);
  let a = 0;
  while (a < chars.length && a < letters.length && letters[a].c === chars[a]) a += 1;
  let b = 0;
  while (b < chars.length - a && b < letters.length - a
         && letters[letters.length - 1 - b].c === chars[chars.length - 1 - b]) b += 1;
  const mid = chars.slice(a, chars.length - b).map(blank);
  return [...letters.slice(0, a), ...mid, ...letters.slice(letters.length - b)];
}

export default function NameStyleEditor({ value, fallbackText, fonts = [], defaultColor = '#FFFFFF', onChange, ColorField }) {
  const letters = useMemo(() => (value && Array.isArray(value.letters) ? value.letters : []), [value]);
  const on = letters.length > 0;
  const [sel, setSel] = useState([]);
  const text = letters.map((l) => l.c).join('');

  const set = (next) => onChange(next.length ? { letters: next } : {});
  const start = () => { const t = (fallbackText || '').trim() || 'Mon commerce'; set(Array.from(t).slice(0, MAX).map(blank)); setSel([0]); };
  const patch = (p) => set(letters.map((l, i) => (sel.includes(i) ? { ...l, ...p } : l)));
  const toggle = (i) => setSel((s) => (s.includes(i) ? s.filter((x) => x !== i) : [...s, i].sort((x, y) => x - y)));
  const insert = (ch) => {
    if (letters.length >= MAX) return;
    const at = sel.length ? sel[sel.length - 1] + 1 : letters.length;
    const next = [...letters.slice(0, at), blank(ch), ...letters.slice(at)];
    set(next); setSel([at]);
  };
  const first = sel.length ? letters[sel[0]] : null;
  const same = (k) => (sel.length && sel.every((i) => (letters[i] || {})[k] === first?.[k]) ? first?.[k] : undefined);

  return (
    <div className="rounded-xl border border-[#E6EEFB] bg-[#FAFCFF] p-3" data-testid="name-style">
      <style>{fonts.map((f) => `@font-face{font-family:'fc-${f.key}';src:url('${API}/wallet/name-fonts/${f.key}.ttf') format('truetype');font-display:swap;}`).join('')}</style>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[13px] font-semibold text-[#0B1C3F]"><Type size={15} className="text-[#2F6BFF]" /> Nom stylé, lettre par lettre</p>
        {on ? (
          <button type="button" onClick={() => { onChange({}); setSel([]); }}
                  className="inline-flex items-center gap-1 text-[12px] font-semibold text-[#64748B] hover:text-[#B91C1C]">
            <RotateCcw size={13} /> Revenir au nom simple
          </button>
        ) : (
          <button type="button" onClick={start}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[#2F6BFF] px-3 py-1.5 text-[12.5px] font-semibold text-white hover:bg-[#2559DB]">
            <Sparkles size={14} /> Styliser le nom
          </button>
        )}
      </div>
      {!on && <p className="mt-1.5 text-[11.5px] text-[#64748B]">Taille, couleur et police de chaque lettre (comme le grand « M » de MUSEUM), et des symboles ★ ♛ ✂… Visible sur iOS 27, iOS 26 et Google Wallet.</p>}
      {on && (
        <div className="mt-3 space-y-3">
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-[#475569]">Texte ({text.length}/{MAX})</span>
            <input value={text} maxLength={MAX} aria-label="Texte du nom stylé"
                   onChange={(e) => { const next = retext(letters, e.target.value); set(next); setSel((s) => s.filter((i) => i < next.length)); }}
                   className="h-10 w-full rounded-lg border border-[#E2E8F0] bg-white px-3 text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
          </label>
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[12px] font-medium text-[#475569]">Cliquez sur une ou plusieurs lettres</span>
              <span className="flex gap-2 text-[12px] font-semibold text-[#2F6BFF]">
                <button type="button" onClick={() => setSel(letters.map((_, i) => i))}>Tout</button>
                <button type="button" onClick={() => setSel([])}>Aucune</button>
              </span>
            </div>
            <div role="group" aria-label="Lettres du nom" className="flex min-h-[64px] flex-wrap items-end gap-x-0 gap-y-1 rounded-lg bg-[#0B1C3F] px-2 py-2">
              {letters.map((l, i) => (
                <button key={i} type="button" aria-pressed={sel.includes(i)} aria-label={`Lettre ${i + 1} : ${l.c === ' ' ? 'espace' : l.c}`}
                        onClick={() => toggle(i)}
                        className={`flex min-w-[8px] items-end justify-center rounded px-[1px] leading-none ${sel.includes(i) ? 'bg-[#2F6BFF]/35 ring-2 ring-[#60A5FA]' : 'hover:bg-white/10'}`}
                        style={{ fontSize: `${Math.round(20 * (l.s || 100) / 100)}px`, color: l.color || defaultColor,
                                 fontFamily: l.font ? `'fc-${l.font}', sans-serif` : "'fc-dejavu', sans-serif", height: 48 }}>
                  {l.c === ' ' ? ' ' : l.c}
                </button>
              ))}
            </div>
          </div>
          <div>
            <span className="mb-1 block text-[12px] font-medium text-[#475569]">Ajouter un symbole {sel.length ? 'après la sélection' : 'à la fin'}</span>
            <div className="flex flex-wrap gap-1">
              {SYMBOLS.map((c) => (
                <button key={c} type="button" onClick={() => insert(c)} aria-label={`Ajouter ${c}`}
                        className="h-8 w-8 rounded-md border border-[#E2E8F0] bg-white text-[15px] text-[#0B1C3F] hover:border-[#2F6BFF]"
                        style={{ fontFamily: "'fc-dejavu', sans-serif" }}>{c}</button>
              ))}
            </div>
          </div>
          {sel.length > 0 ? (
            <div className="grid gap-3 rounded-lg border border-[#DCE6FA] bg-white p-3 sm:grid-cols-3">
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-[#475569]">Taille : {same('s') ?? '—'} %</span>
                <input type="range" min={50} max={200} step={5} value={same('s') ?? 100} aria-label="Taille des lettres choisies"
                       onChange={(e) => patch({ s: Number(e.target.value) })} className="w-full accent-[#2F6BFF]" />
              </label>
              <div>
                <span className="mb-1 flex items-center justify-between text-[12px] font-medium text-[#475569]">
                  Couleur
                  {same('color') !== null && <button type="button" className="text-[11.5px] font-semibold text-[#2F6BFF]" onClick={() => patch({ color: null })}>Automatique</button>}
                </span>
                {ColorField ? <ColorField value={same('color') || defaultColor} onChange={(v) => patch({ color: v })} />
                  : <input type="color" value={same('color') || defaultColor} onChange={(e) => patch({ color: e.target.value.toUpperCase() })} aria-label="Couleur des lettres choisies" />}
              </div>
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-[#475569]">Police</span>
                <select value={same('font') ?? ''} aria-label="Police des lettres choisies"
                        onChange={(e) => patch({ font: e.target.value || null })}
                        className="h-10 w-full rounded-lg border border-[#E2E8F0] bg-white px-2 text-[13.5px] text-[#0B1C3F]">
                  <option value="">Par défaut (Sans gras)</option>
                  {fonts.filter((f) => f.key !== 'dejavu').map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                </select>
              </label>
              {sel.length > 0 && (
                <button type="button" onClick={() => { set(letters.filter((_, i) => !sel.includes(i))); setSel([]); }}
                        className="text-left text-[12px] font-semibold text-[#B91C1C] sm:col-span-3">Supprimer {sel.length > 1 ? `ces ${sel.length} caractères` : 'ce caractère'}</button>
              )}
            </div>
          ) : (
            <p className="text-[11.5px] text-[#64748B]">Choisissez des lettres pour changer leur taille, leur couleur ou leur police. L'aperçu à droite montre la carte telle que vos clients la verront.</p>
          )}
        </div>
      )}
    </div>
  );
}
