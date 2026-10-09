import React, { useEffect, useRef, useState } from 'react';
import {
  Lightbulb, TrendingUp, TrendingDown, Info, Loader2, X, Clock, Check, AlertTriangle, Sparkles,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import InfoTip from './InfoTip';
import { eur } from '../lib/money';

/**
 * « Ce qui marche chez vous » — what FidClic learnt from the campaigns this
 * shop sent (features/campaign_learning.py). Nothing here sends anything: it
 * reads past sends and advises the next one (user, 2026-10-02).
 *
 *   ResultChip     a send's effect in the Campagnes table
 *   ResultModal    one send, measured and taken apart
 *   ComposerTips   advice on the message being written
 *   LearningPanel  the learnings, in plain French
 */
// 93,10 € — cents keep two digits (lib/money)
const money = eur;

export function ResultChip({ result, windowDays = 15 }) {
  if (!result) return <span className="text-[11.5px] text-[#94A3B8]">—</span>;
  if (!result.mature) {
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-[#EEF2F8] px-2 py-0.5 text-[11px] font-semibold text-[#64748B]"
            title={`Le résultat se lit ${windowDays} jours après l'envoi.`}>
        <Clock size={11} /> En cours · J+{result.day}/{windowDays}
      </span>
    );
  }
  // The clients a send brought on top of those who were coming anyway — a
  // count, not a rate: on a send to ten clients « −85 / 100 » reads like a
  // disaster when it is one client either way.
  const extra = Math.round(result.came - result.expected);
  const good = extra >= 1;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-semibold tabular-nums"
          title={`${result.came} clients revenus, ${(Math.round(result.expected * 10) / 10).toLocaleString('fr-FR')} attendus de toute façon.`}
          style={good ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#EEF2F8', color: '#64748B' }}>
      {good ? <TrendingUp size={11} /> : extra <= -1 ? <TrendingDown size={11} /> : null}
      {extra === 0 ? '≈ 0 client' : `${extra > 0 ? '+' : '−'}${Math.abs(extra)} client${Math.abs(extra) > 1 ? 's' : ''}`}
    </span>
  );
}

export function ResultModal({ id, onClose }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    ownerAPI.campaignResult(id).then(({ data }) => setD(data))
      .catch((e) => setErr(e?.response?.data?.detail || 'Résultat indisponible.'));
  }, [id]);
  const r = d?.result;
  const extra = r ? Math.round(r.came - r.expected) : 0;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/40 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" className="flex max-h-[90vh] w-full max-w-xl flex-col rounded-2xl bg-white shadow-[0_30px_70px_-30px_rgba(11,28,63,.6)]"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-[#EEF3FB] p-5">
          <div className="min-w-0">
            <h3 className="truncate text-[16px] font-bold text-[#0B1C3F]">{d?.name || 'Résultat de la campagne'}</h3>
            {d?.content && <p className="mt-0.5 text-[12.5px] text-[#64748B]">{d.content}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#334155]"><X size={18} /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {err && <p className="rounded-xl bg-[#FEECEC] px-3 py-2 text-[12.5px] text-[#C0392B]">{err}</p>}
          {!d && !err && <p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={14} className="animate-spin" /> Calcul…</p>}
          {d && !r && <p className="text-[13px] text-[#64748B]">Cette campagne n'a pas encore été envoyée.</p>}
          {r && (
            <>
              {!r.mature && (
                <p className="mb-3 flex items-start gap-2 rounded-xl bg-[#EEF2F8] px-3 py-2 text-[12px] text-[#475569]">
                  <Clock size={13} className="mt-px shrink-0" /> En cours : jour {r.day} sur {d.window_days}. Les chiffres bougeront jusqu'au bout.
                </p>
              )}
              <div className="mb-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                {[['Clients touchés', r.n.toLocaleString('fr-FR'), '#0B1C3F'],
                  ['Clients revenus', r.came.toLocaleString('fr-FR'), '#0B1C3F'],
                  ['Attendus sans message', (Math.round(r.expected * 10) / 10).toLocaleString('fr-FR'), '#64748B'],
                  ['En plus grâce au message', `${extra >= 0 ? '+' : ''}${extra}`, extra > 0 ? '#0F8B58' : '#64748B']].map(([label, v, color]) => (
                  <div key={label} className="rounded-xl border border-[#E6EEFB] p-3 text-center">
                    <p className="text-[19px] font-extrabold leading-none tabular-nums" style={{ color }}>{v}</p>
                    <p className="mt-1 text-[11px] leading-tight text-[#64748B]">{label}</p>
                  </div>
                ))}
              </div>
              <p className="mb-4 text-[12.5px] text-[#475569]">
                CA des clients revenus : <b className="text-[#0B1C3F]">{money(r.revenue)}</b>
              </p>
              <p className="mb-2 text-[12.5px] font-bold text-[#0B1C3F]">Ce qui a joué</p>
              <ul className="space-y-1.5">
                {d.traits.map((t) => (
                  <li key={t.dimension} className="flex items-center justify-between gap-3 text-[12.5px]">
                    <span className="text-[#64748B]">{t.dimension_label}</span>
                    <span className="flex items-center gap-2 text-right">
                      <span className="font-medium text-[#0B1C3F]">{t.label}</span>
                      {t.verdict === 'plus' && <span className="rounded-md bg-[#E7F7EE] px-1.5 py-0.5 text-[10.5px] font-bold text-[#0F8B58]">ça marche</span>}
                      {t.verdict === 'moins' && <span className="rounded-md bg-[#FFF7E6] px-1.5 py-0.5 text-[10.5px] font-bold text-[#B45309]">ça freine</span>}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-4 flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]">
                <Info size={12} className="mt-px shrink-0" />
                « Attendus » : les clients qui seraient venus de toute façon dans les {d.window_days} jours, d'après leurs
                habitudes des 6 derniers mois. « ça marche / ça freine » n'apparaît que quand vos campagnes l'ont montré.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function ComposerTips({ title, message, segment, image, link, scheduleAt }) {
  const [d, setD] = useState(null);
  const seq = useRef(0);
  useEffect(() => {
    if (!title.trim() && !message.trim()) { setD(null); return undefined; }
    const n = ++seq.current;
    const id = setTimeout(() => {
      ownerAPI.campaignTips({ title, message, segment, image: !!image, link: !!link, schedule_at: scheduleAt || null })
        .then(({ data }) => { if (n === seq.current) setD(data); }).catch(() => {});
    }, 600);
    return () => clearTimeout(id);
  }, [title, message, segment, image, link, scheduleAt]);
  if (!d) return null;
  if (!d.tips.length) {
    return d.has_learnings ? null : (
      <p className="mb-3 flex items-start gap-1.5 rounded-xl bg-[#F5F8FE] px-3 py-2 text-[11.5px] leading-snug text-[#64748B]">
        <Lightbulb size={13} className="mt-px shrink-0 text-[#94A3B8]" />
        Les conseils arrivent avec vos résultats : FidClic apprend de chaque campagne envoyée
        ({d.campaigns_measured} mesurée{d.campaigns_measured > 1 ? 's' : ''} pour l'instant).
      </p>
    );
  }
  const ICON = { good: [Check, '#0F8B58', '#E7F7EE'], try: [Lightbulb, '#1D4ED8', '#EFF5FF'],
    warn: [AlertTriangle, '#B45309', '#FFF7E6'], time: [Clock, '#6D28D9', '#F3EEFF'] };
  return (
    <div className="mb-3 space-y-1.5" aria-live="polite">
      <p className="flex items-center gap-1.5 text-[11.5px] font-bold text-[#0B1C3F]"><Sparkles size={13} className="text-[#8B5CF6]" /> Conseils FidClic</p>
      {d.tips.map((t, i) => {
        const [Icon, fg, bg] = ICON[t.kind] || ICON.try;
        return (
          <p key={i} className="flex items-start gap-1.5 rounded-xl px-3 py-2 text-[11.5px] leading-snug" style={{ background: bg, color: fg }}>
            <Icon size={13} className="mt-px shrink-0" /> <span>{t.text}</span>
          </p>
        );
      })}
    </div>
  );
}

export function LearningPanel() {
  const [d, setD] = useState(null);
  useEffect(() => { ownerAPI.campaignLearning().then(({ data }) => setD(data)).catch(() => {}); }, []);
  if (!d) return null;
  const rows = d.learnings || [];
  return (
    <section className="mb-4 rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-[15px] font-bold text-[#0B1C3F]">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#F3EEFF] text-[#6D28D9]"><Lightbulb size={16} /></span>
          Ce qui marche chez vous <InfoTip k="learning" />
        </h2>
        <span className="text-[11.5px] text-[#64748B]">
          {d.campaigns_measured} campagne{d.campaigns_measured > 1 ? 's' : ''} mesurée{d.campaigns_measured > 1 ? 's' : ''}
        </span>
      </div>
      {rows.length ? (
        <ul className="space-y-2">
          {rows.slice(0, 8).map((f) => (
            <li key={`${f.dimension}-${f.value}`} className="flex items-start gap-2.5 rounded-xl border border-[#EEF3FB] px-3 py-2.5">
              <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg ${f.better ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FFF7E6] text-[#B45309]'}`}>
                {f.better ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
              </span>
              <span className="min-w-0 flex-1 text-[12.5px] leading-snug text-[#334155]">{f.sentence}</span>
              <span className="flex shrink-0 flex-col items-end gap-1">
                <span className={`rounded-md px-1.5 py-0.5 text-[10.5px] font-bold ${f.confidence === 'solide' ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#EFF5FF] text-[#1D4ED8]'}`}>
                  {f.confidence === 'solide' ? 'Solide' : 'Probable'}
                </span>
                {f.source === 'secteur' && <span className="text-[10px] text-[#94A3B8]">commerces similaires</span>}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-xl bg-[#F5F8FE] px-3 py-3 text-[12.5px] leading-snug text-[#475569]">
          Pas encore assez de données. FidClic compare vos campagnes entre elles : il en faut au moins {d.needs} de
          chaque sorte (par exemple 3 avec un cadeau et 3 avec une remise), mesurées sur {d.window_days} jours,
          avant de vous dire ce qui marche — pour ne jamais vous conseiller sur un coup de chance.
        </p>
      )}
      <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]">
        <Info size={12} className="mt-px shrink-0" /> {d.method}
      </p>
    </section>
  );
}
