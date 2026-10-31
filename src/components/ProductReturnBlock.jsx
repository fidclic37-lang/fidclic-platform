import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Magnet, Circle, TrendingDown, Loader2, Lock, RefreshCcw, Pencil, Link2 } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { eur } from '../lib/money';
import { openUpgrade } from './PlanAccess';

/**
 * « Produits qui font revenir » — Analyses › Produits, at the top of the tab
 * (user, 2026-10-31: three columns by verdict). The page reads what the
 * engine stored each week (api/features/product_return.py); it never
 * computes. Pro: the verdicts; Pro AI: each card's « X sur 10 reviennent »,
 * its range, days to come back, CA 90 jours and Fiabilité, and the combos.
 */
const COLS = [
  { key: 'aimant', label: 'Aimant', icon: Magnet, tone: '#0F8B58', bg: '#ECFDF3', sub: 'Après ce produit, les clients reviennent plus.' },
  { key: 'neutre', label: 'Neutre', icon: Circle, tone: '#64748B', bg: '#F4F7FC', sub: 'Ni plus ni moins que les autres.' },
  { key: 'one_shot', label: 'One-shot', icon: TrendingDown, tone: '#B45309', bg: '#FFF7ED', sub: 'Après ce produit, les clients reviennent moins.' },
];
const VIEWS = [['first', '1ère visite'], ['all', 'Toutes les visites']];
const POLL_MS = 5000;
const POLL_MAX = 36;                          // 3 minutes, then « revenez plus tard » (a failing job is not asked again every 5 s)

function Card({ p, full }) {
  return (
    <li data-testid="pr-card" className="rounded-xl border border-[#EEF3FB] bg-white p-3">
      <p className="text-[13px] font-semibold leading-snug text-[#0B1C3F]">{p.name}</p>
      {p.together && (
        <p className="mt-0.5 inline-flex items-center gap-1 text-[11px] text-[#64748B]"><Link2 size={11} /> Toujours achetés ensemble</p>
      )}
      {full && p.back != null ? (
        <div className="mt-1.5 space-y-0.5 text-[12px] text-[#475569]">
          <p><strong className="text-[#0B1C3F]">{p.back} sur 10 reviennent</strong>
            {p.back_low != null && <span className="text-[#94A3B8]"> (entre {p.back_low} et {p.back_high})</span>}</p>
          {p.days_back != null && <p>Ils reviennent en {p.days_back} jours (médiane)</p>}
          {p.ca90 != null && <p>{eur(p.ca90)} sur 90 jours par client</p>}
          {p.fiabilite && <p className="text-[11px] text-[#94A3B8]">Fiabilité {p.fiabilite}</p>}
        </div>
      ) : (
        <p className="mt-1 text-[11.5px] text-[#94A3B8]">{p.clients} clients</p>
      )}
    </li>
  );
}

export default function ProductReturnBlock() {
  const [view, setView] = useState('first');
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [edit, setEdit] = useState(null);       // the window being edited (days, '' = the shop's rhythm)
  const [busy, setBusy] = useState(false);
  const [store, setStore] = useState(0);          // an account that sees several establishments: one at a time
  const [late, setLate] = useState(false);
  const timer = useRef(null);
  const polls = useRef(0);

  const load = useCallback((v) => {
    clearTimeout(timer.current);
    ownerAPI.produitsRetour(v)
      .then(({ data }) => {
        setD(data); setErr('');
        if (data.status === 'pending' || data.refreshing) {
          polls.current += 1;
          if (polls.current <= POLL_MAX) timer.current = setTimeout(() => load(v), POLL_MS);
          else setLate(true);
        } else {
          polls.current = 0;
          setLate(false);
        }
      })
      .catch((e) => {
        const det = e?.response?.data?.detail;
        if (det && det.code === 'PLAN_FEATURE_DISABLED') setD({ status: 'locked', detail: det });
        else setErr(typeof det === 'string' ? det : "Cette analyse n'a pas pu être chargée.");
      });
  }, []);
  useEffect(() => { load(view); return () => clearTimeout(timer.current); }, [view, load]);

  const saveWindow = async () => {
    setBusy(true);
    try {
      await ownerAPI.setProduitsWindow(edit === '' ? null : Number(edit));
      setEdit(null);
      setD((x) => ({ ...(x || {}), refreshing: true }));
      timer.current = setTimeout(() => load(view), POLL_MS);
    } catch (e) {
      setErr(e?.response?.data?.detail || "La fenêtre n'a pas pu être changée.");
    } finally { setBusy(false); }
  };

  const shell = (children) => (
    <section data-testid="product-return" className="mb-4 rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <header className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className="text-[15px] font-bold text-[#0B1C3F]">Produits qui font revenir</h2>
        <div className="ml-auto inline-flex rounded-lg border border-[#E6EEFB] p-0.5" role="group" aria-label="Quelles visites">
          {VIEWS.map(([k, label]) => (
            <button key={k} type="button" aria-pressed={view === k} onClick={() => setView(k)}
                    className={`rounded-md px-2.5 py-1 text-[12px] font-semibold ${view === k ? 'bg-[#2F6BFF] text-white' : 'text-[#475569] hover:bg-[#F4F7FC]'}`}>
              {label}
            </button>
          ))}
        </div>
      </header>
      {children}
    </section>
  );

  if (err) return shell(<p className="text-[12.5px] text-[#DC2626]">{err}</p>);
  if (!d) return shell(<p className="flex items-center gap-2 text-[12.5px] text-[#64748B]"><Loader2 size={14} className="animate-spin" /> Chargement…</p>);
  if (d.status === 'locked') {
    return shell(
      <button type="button" onClick={() => openUpgrade(d.detail)}
              className="inline-flex items-center gap-2 rounded-xl border border-dashed border-[#D9E4F7] px-4 py-3 text-[12.5px] text-[#475569]">
        <Lock size={14} /> {d.detail?.message || "Cette analyse n'est pas incluse dans votre offre."}
      </button>,
    );
  }
  if (d.status === 'pending') {
    return shell(
      late ? (
        <p data-testid="pr-late" className="text-[12.5px] text-[#64748B]">
          La première analyse de vos produits prend plus de temps que prévu. Revenez dans quelques heures : elle se fera en arrière-plan.
        </p>
      ) : (
        <p className="flex items-center gap-2 text-[12.5px] text-[#64748B]">
          <Loader2 size={14} className="animate-spin" /> FidClic IA analyse vos produits : la première fois prend quelques minutes.
        </p>
      ),
    );
  }

  const src = (d.stores && d.stores.length > 1) ? (d.stores[store] || d.stores[0]) : d;
  const v = (src.views || {})[d.view] || (src.views || {})[view] || { products: [] };
  const products = v.products || [];
  const full = d.level === 'full';
  const by = (k) => products.filter((p) => p.bucket === k);
  const few = by('insufficient');
  const everywhere = by('everywhere');
  const combos = full ? (v.combos || []) : [];

  return shell(
    <>
      {d.stores && d.stores.length > 1 && (
        <div className="mb-2 flex flex-wrap gap-1.5" role="group" aria-label="Établissement">
          {d.stores.map((x, i) => (
            <button key={x.store} type="button" aria-pressed={store === i} onClick={() => setStore(i)}
                    className={`rounded-full px-2.5 py-1 text-[11.5px] font-semibold ${store === i ? 'bg-[#0B1C3F] text-white' : 'bg-[#F4F7FC] text-[#475569]'}`}>
              {x.name}
            </button>
          ))}
        </div>
      )}
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-[#64748B]">
        {edit === null ? (
          <span>
            Fenêtre : {d.window_days} jours ({d.window_source === 'personnalise' ? 'choisie par vous' : 'le rythme de votre commerce'})
            {/* « Modifier » on Analyses only (the server refuses the others too) */}
            {d.can_edit && (
              <>{' '}<button type="button" onClick={() => setEdit(d.window_source === 'personnalise' ? String(d.window_days) : '')}
                             aria-label="Modifier la fenêtre" className="inline-flex items-center gap-1 font-semibold text-[#2F6BFF] hover:underline">
                <Pencil size={11} /> Modifier
              </button></>
            )}
          </span>
        ) : (
          <span className="inline-flex items-center gap-2">
            <label className="inline-flex items-center gap-1.5">Jours
              <input type="number" min={7} max={180} value={edit} placeholder={String(d.window_days)} aria-label="Jours"
                     onChange={(e) => setEdit(e.target.value)}
                     className="w-20 rounded-md border border-[#DCE3EE] px-2 py-1 text-[12px] outline-none focus:border-[#2F6BFF]" />
            </label>
            <button type="button" disabled={busy} onClick={saveWindow}
                    className="inline-flex items-center gap-1 rounded-md bg-[#2F6BFF] px-2.5 py-1 text-[12px] font-semibold text-white disabled:opacity-50">
              <RefreshCcw size={12} /> Recalculer
            </button>
            <button type="button" onClick={() => setEdit('')} className="text-[12px] font-medium text-[#475569] hover:underline">Rythme du commerce</button>
            <button type="button" onClick={() => setEdit(null)} className="text-[12px] text-[#94A3B8] hover:underline">Annuler</button>
          </span>
        )}
        <span>Produits renseignés : {src.coverage?.pct ?? 0} %</span>
        {d.refreshing && <span className="inline-flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Mise à jour…</span>}
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {COLS.map((c) => {
          const Icon = c.icon;
          const list = by(c.key);
          return (
            <div key={c.key} data-testid={`pr-col-${c.key}`} className="rounded-2xl p-3" style={{ background: c.bg }}>
              <p className="flex items-center gap-1.5 text-[13px] font-bold" style={{ color: c.tone }}>
                <Icon size={15} /> {c.label} ({list.length})
              </p>
              <p className="mb-2 text-[11px] text-[#64748B]">{c.sub}</p>
              {list.length ? <ul className="space-y-2">{list.map((p) => <Card key={p.name} p={p} full={full} />)}</ul>
                : <p className="text-[11.5px] text-[#94A3B8]">Aucun produit pour l'instant.</p>}
            </div>
          );
        })}
      </div>

      <div className="mt-3 space-y-1 text-[12px] text-[#475569]">
        {everywhere.length > 0 && <p>Dans presque tous les paniers : {everywhere.map((p) => p.name).join(', ')}</p>}
        {few.length > 0 && (
          <p>Pas assez de données : {few.map((p) => `${p.name} (${p.clients}/${p.needed || d.min_buyers || 30})`).join(', ')}</p>
        )}
        {combos.filter((c) => c.effect === 'plus').length > 0 && (
          <p>Ensemble, ils font revenir plus : {combos.filter((c) => c.effect === 'plus').map((c) => `${c.a} + ${c.b}`).join(', ')}</p>
        )}
        {combos.filter((c) => c.effect === 'moins').length > 0 && (
          <p>Ensemble, ils font revenir moins : {combos.filter((c) => c.effect === 'moins').map((c) => `${c.a} + ${c.b}`).join(', ')}</p>
        )}
        {!full && (
          <button type="button" onClick={() => openUpgrade({ feature: 'ai', label: 'Produits qui font revenir', message: "Le détail de chaque produit (sur 10 clients, combien reviennent, en combien de jours, ce qu'ils dépensent) est inclus dans l'offre Pro AI.", upgrade: { label: 'Pro AI' } })}
                  className="inline-flex items-center gap-1 font-semibold text-[#2F6BFF] hover:underline">
            <Lock size={12} /> Le détail de chaque produit avec Pro AI
          </button>
        )}
      </div>
    </>,
  );
}
