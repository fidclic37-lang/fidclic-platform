import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sparkles, Clock, Repeat, TrendingDown, Send, Users, ChevronDown } from 'lucide-react';
import { ownerAPI } from '../../lib/api';
import { eur } from '../../lib/money';
import RecoLastResult from '../RecoLastResult';

/* Tableau de bord › « FidClic IA a repéré » (user, 2026-10-25): the client
   brain's three lists — habitués en retard, pas revenus après la 1ère visite,
   viennent moins souvent — each with its count, « Pourquoi ? », its clients
   and the composer written for them. Nothing leaves without the owner. */

const ICON = { clock: Clock, repeat: Repeat, 'trending-down': TrendingDown };
const TONE = {
  orange: { bg: '#FFF3E8', fg: '#C2410C' },
  violet: { bg: '#F3EEFF', fg: '#6D28D9' },
  rose: { bg: '#FFF1F3', fg: '#E11D48' },
};

export default function IaSpotted() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    let alive = true;
    ownerAPI.brainDetectors()
      .then(({ data }) => { if (alive) setRows(data.detectors || []); })
      .catch(() => { if (alive) setRows([]); });
    return () => { alive = false; };
  }, []);

  if (!rows) return null;
  return (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]" data-testid="ia-spotted">
      <header className="mb-3 flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#F1EEFF] text-[#5B3FD6]"><Sparkles size={16} /></span>
        <div>
          <h2 className="text-[15px] font-bold text-[#0B1C3F]">FidClic IA a repéré</h2>
          <p className="text-[12px] text-[#64748B]">Calculé sur le rythme de chacun de vos clients, mis à jour à chaque passage.</p>
        </div>
      </header>
      <ul className="divide-y divide-[#F1F5FB]">
        {rows.map((r) => {
          const I = ICON[r.icon] || Users;
          const t = TONE[r.tone] || TONE.violet;
          return (
            <li key={r.key} className="py-3" data-testid={`ia-${r.key}`}>
              <div className="flex flex-wrap items-center gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: t.bg, color: t.fg }}><I size={17} /></span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13.5px] font-semibold text-[#0B1C3F]">
                    <span className="mr-1.5 text-[18px] font-extrabold tabular-nums" style={{ color: r.count ? t.fg : '#94A3B8' }}>{r.count}</span>
                    {r.label}
                  </p>
                  {r.count > 0 && (
                    <p translate="no" className="notranslate truncate text-[12px] text-[#64748B]">
                      {r.names.filter(Boolean).join(', ')}{r.count > r.names.length ? ` et ${r.count - r.names.length} autres` : ''}
                      {r.worth > 0 && <span> · panier habituel cumulé {eur(r.worth)}</span>}
                    </p>
                  )}
                </div>
                <button type="button" onClick={() => setOpen(open === r.key ? null : r.key)} aria-expanded={open === r.key}
                        className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-[#2F6BFF]">
                  Pourquoi ? <ChevronDown size={13} className={open === r.key ? 'rotate-180' : ''} />
                </button>
                {r.count > 0 && (
                  <>
                    <button type="button" onClick={() => navigate(r.clients)}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#E2E8F0] px-3 text-[12.5px] font-semibold text-[#334155] hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                      <Users size={13} /> Voir les clients
                    </button>
                    <button type="button" data-testid={`ia-${r.key}-cta`}
                            onClick={() => navigate(`/dashboard/campaigns?template=${encodeURIComponent(r.template)}&from=repere`)}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#5B3FD6] px-3 text-[12.5px] font-semibold text-white hover:bg-[#4C32C0]">
                      <Send size={13} /> Préparer le message
                    </button>
                  </>
                )}
              </div>
              <RecoLastResult r={r} className="mt-1.5" />
              {open === r.key && <p className="mt-2 rounded-lg bg-[#F8FAFF] px-3 py-2 text-[12.5px] leading-relaxed text-[#475569]">{r.why}
                {r.why_rank?.text && <span data-testid="reco-why" className="mt-1 block text-[#64748B]">En premier ? {r.why_rank.text}</span>}</p>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
