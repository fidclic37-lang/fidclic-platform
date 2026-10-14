import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Target, Plus, Trash2, Loader2, Check, ArrowRight, Repeat } from 'lucide-react';
import { ownerAPI } from '../../lib/api';

/**
 * « Objectifs et récompenses » — the milestones the shop sets for itself.
 *
 * Not the same thing as « Récompenses et paliers » on the loyalty card: that
 * one is the client's LEVEL (Bronze → VIP), one ordered ladder read by the
 * segments and the VIP rule. An objectif is « at 10 visits, a coffee » — as
 * many as the owner wants, each counted on whatever suits it, which is why
 * they cannot be rungs of the same ladder.
 */
const BLUE = '#1463FF';
const blank = () => ({ id: null, label: '', unit: 'visits', threshold: '', repeat: false, valid_days: 60, active: true });

export default function ObjectifsPage() {
  const [items, setItems] = useState(null);
  const [units, setUnits] = useState([]);
  const [max, setMax] = useState(30);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState('');

  const load = useCallback(() => {
    ownerAPI.milestones()
      .then(({ data }) => { setItems(data.items || []); setUnits(data.units || []); setMax(data.max || 30); })
      .catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger les objectifs.'));
  }, []);
  useEffect(() => { load(); }, [load]);

  const patch = (i, next) => setItems((rows) => rows.map((r, j) => (j === i ? { ...r, ...next } : r)));
  const suffix = (u) => (units.find((x) => x.key === u) || {}).suffix || '';

  const save = () => {
    setBusy(true); setErr('');
    const clean = items
      .filter((r) => (r.label || '').trim() && String(r.threshold).trim())
      .map((r) => ({ ...r, threshold: Number(r.threshold) }));
    ownerAPI.saveMilestones(clean)
      .then(({ data }) => { setItems(data.items || []); setToast('Objectifs enregistrés.'); setTimeout(() => setToast(''), 3000); })
      .catch((e) => setErr(e?.response?.data?.detail || "L'enregistrement n'a pas abouti."))
      .finally(() => setBusy(false));
  };

  if (!items) {
    return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p>
      : <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-20 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>;
  }

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
        <h2 className="flex items-center gap-2 text-[15px] font-bold text-[#0B1C3F]"><Target size={17} className="text-[#2F6BFF]" /> Objectifs et récompenses</h2>
        <p className="mt-1 text-[13px] text-[#64748B]">
          À tant de visites, de points ou d'euros dépensés : telle récompense. Dès qu'un client y arrive,
          la récompense l'attend en caisse — l'équipe la remet au scan suivant.
        </p>
        <p className="mt-2 text-[12.5px] text-[#64748B]">
          À ne pas confondre avec les <Link to="/dashboard/card" className="font-semibold text-[#2F6BFF] hover:underline">paliers Bronze → VIP</Link>,
          qui sont le <em>niveau</em> du client. Ici, ce sont vos propres objectifs, autant que vous voulez.
        </p>
      </div>

      {items.length === 0 && (
        <div className="rounded-2xl border border-dashed border-[#CBD5E1] bg-white px-6 py-12 text-center">
          <p className="text-[14px] font-semibold text-[#0B1C3F]">Aucun objectif pour le moment</p>
          <p className="mt-1 text-[13px] text-[#64748B]">Par exemple : « 10 visites → un café offert ».</p>
        </div>
      )}

      {items.map((r, i) => (
        <div key={r.id || `new-${i}`} className="rounded-2xl border border-[#E6EEFB] bg-white p-4">
          <div className="grid gap-3 md:grid-cols-[1fr_auto_auto_auto]">
            <label className="block text-[12.5px] font-medium text-[#334155]">Récompense
              <input value={r.label} maxLength={80} placeholder="Un café offert"
                     onChange={(e) => patch(i, { label: e.target.value })}
                     className="mt-1 w-full rounded-xl border border-[#E2E8F0] px-3 py-2.5 text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
            </label>
            <label className="block text-[12.5px] font-medium text-[#334155]">À partir de
              <span className="mt-1 flex items-stretch overflow-hidden rounded-xl border border-[#E2E8F0]">
                <input value={r.threshold} inputMode="decimal" placeholder="10"
                       onChange={(e) => patch(i, { threshold: e.target.value.replace(/[^\d.]/g, '') })}
                       className="w-24 px-3 py-2.5 text-[14px] text-[#0B1C3F] outline-none" />
                <span className="flex items-center border-l border-[#E2E8F0] px-2 text-[12.5px] text-[#64748B]">{suffix(r.unit)}</span>
              </span>
            </label>
            <label className="block text-[12.5px] font-medium text-[#334155]">Compté en
              <select value={r.unit} onChange={(e) => patch(i, { unit: e.target.value })}
                      className="mt-1 w-full rounded-xl border border-[#E2E8F0] px-3 py-2.5 text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]">
                {units.map((u) => <option key={u.key} value={u.key}>{u.label}</option>)}
              </select>
            </label>
            <label className="block text-[12.5px] font-medium text-[#334155]">Valable
              <span className="mt-1 flex items-stretch overflow-hidden rounded-xl border border-[#E2E8F0]">
                <input value={r.valid_days} inputMode="numeric"
                       onChange={(e) => patch(i, { valid_days: e.target.value.replace(/\D/g, '') })}
                       className="w-16 px-3 py-2.5 text-[14px] text-[#0B1C3F] outline-none" />
                <span className="flex items-center border-l border-[#E2E8F0] px-2 text-[12.5px] text-[#64748B]">jours</span>
              </span>
            </label>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-4">
            <label className="inline-flex cursor-pointer items-center gap-2 text-[13px] text-[#334155]">
              <input type="checkbox" checked={!!r.repeat} onChange={(e) => patch(i, { repeat: e.target.checked })}
                     className="h-4 w-4 accent-[#2F6BFF]" />
              <Repeat size={14} className="text-[#64748B]" />
              {r.repeat
                ? `À chaque fois — tous les ${r.threshold || 'N'} ${suffix(r.unit)}`
                : 'Une seule fois par client'}
            </label>
            <label className="inline-flex cursor-pointer items-center gap-2 text-[13px] text-[#334155]">
              <input type="checkbox" checked={r.active !== false} onChange={(e) => patch(i, { active: e.target.checked })}
                     className="h-4 w-4 accent-[#2F6BFF]" />
              Actif
            </label>
            <button type="button" onClick={() => setItems((rows) => rows.filter((_, j) => j !== i))}
                    className="ml-auto inline-flex items-center gap-1.5 text-[13px] font-medium text-[#B91C1C]">
              <Trash2 size={14} /> Supprimer
            </button>
          </div>
        </div>
      ))}

      {err && <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p>}

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={items.length >= max}
                onClick={() => setItems((rows) => [...rows, blank()])}
                className="inline-flex items-center gap-2 rounded-xl border border-[#2F6BFF] px-4 py-2.5 text-[13.5px] font-medium text-[#2F6BFF] disabled:opacity-50">
          <Plus size={15} /> Ajouter un objectif
        </button>
        <button type="button" disabled={busy} onClick={save}
                className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-[14px] font-medium text-white disabled:opacity-50"
                style={{ background: BLUE }}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Enregistrer
        </button>
        {items.length >= max && <span className="text-[12.5px] text-[#64748B]">{max} objectifs au maximum.</span>}
        <Link to="/dashboard/scan" className="ml-auto inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#2F6BFF] hover:underline">
          Voir la caisse <ArrowRight size={14} />
        </Link>
      </div>

      <div aria-live="polite" className="pointer-events-none fixed bottom-5 left-1/2 z-40 -translate-x-1/2 transition-opacity" style={{ opacity: toast ? 1 : 0 }}>
        <span className="inline-flex items-center gap-2 rounded-full bg-[#0B1C3F] px-4 py-2 text-[13px] font-medium text-white shadow-lg"><Check size={14} /> {toast}</span>
      </div>
    </div>
  );
}
