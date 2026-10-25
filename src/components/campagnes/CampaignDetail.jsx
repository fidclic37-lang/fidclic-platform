import React, { useEffect, useState } from 'react';
import {
  X, Loader2, Users, Mail, MousePointerClick, RotateCcw, Euro, CalendarDays, Link2, Pencil, Trash2, Ban, BarChart3, Info, UserRound,
} from 'lucide-react';
import TemoinResult from '../TemoinResult';
import { ownerAPI } from '../../lib/api';
import { eur } from '../../lib/money';
import { KIND_META } from './kinds';

/**
 * A campaign of « Vos campagnes récentes », opened by a click on its row
 * (user, 2026-10-10: a click always shows the campaign): what it said, to
 * whom, when, and once sent what it did. Editing, cancelling and deleting
 * stay one click away for the campaigns that allow it.
 */
const STATUS = {
  live: ['En cours', '#EAF1FF', '#1D4ED8'], ended: ['Terminée', '#E3F6EC', '#047857'],
  scheduled: ['Programmée', '#F1EAFF', '#6D28D9'], cancelled: ['Annulée', '#F1F5F9', '#64748B'],
  draft: ['Brouillon', '#F1F5F9', '#475569'], sending: ["En cours d'envoi", '#EAF1FF', '#1D4ED8'],
};
const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
const when = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()} à ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};
// {prénom} → a soft chip, so the message reads as the owner wrote it
const Message = ({ text }) => (
  <>{String(text || '').split(/(\{[a-zéèàù_]+\})/gi).map((p, i) => (/^\{.+\}$/.test(p)
    ? <span key={i} className="mx-0.5 rounded-md bg-[#E6EEFF] px-1.5 py-0.5 text-[13px] font-semibold text-[#1D4ED8]">{p}</span>
    : <React.Fragment key={i}>{p}</React.Fragment>))}</>
);

function Stat({ icon: I, tone, value, label, hint, wide }) {
  return (
    <div className={`rounded-xl border border-[#E6EEFB] p-3 ${wide ? 'col-span-2 sm:col-span-1' : ''}`}>
      <span className="mb-2 flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: tone[0], color: tone[1] }}><I size={16} /></span>
      <p className="text-[20px] font-extrabold leading-none tabular-nums text-[#0B1C3F]">{value}</p>
      <p className="mt-1 text-[12.5px] font-medium text-[#334155]">{label}</p>
      {hint && <p className="text-[11.5px] text-[#94A3B8]">{hint}</p>}
    </div>
  );
}

function Line({ icon: I, label, children }) {
  return (
    <div className="flex gap-3 border-t border-[#EEF2F7] py-3 first:border-t-0">
      <I size={17} className="mt-0.5 shrink-0 text-[#64748B]" />
      <div className="min-w-0 flex-1">
        <p className="text-[12.5px] font-semibold uppercase tracking-wide text-[#64748B]">{label}</p>
        <div className="mt-0.5 text-[14.5px] text-[#0B1C3F]">{children}</div>
      </div>
    </div>
  );
}

export default function CampaignDetail({ id, onClose, onEdit, onCancel, onDelete, onAnalysis }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    let alive = true;
    setD(null); setErr('');
    ownerAPI.campaignDetail(id).then(({ data }) => { if (alive) setD(data); })
      .catch((e) => { if (alive) setErr(e?.response?.data?.detail || "Cette campagne n'a pas pu être ouverte."); });
    return () => { alive = false; };
  }, [id]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const m = KIND_META[d?.kind] || KIND_META.message;
  const I = m.icon;
  const [sl, sbg, sfg] = STATUS[d?.status] || STATUS.draft;
  const st = d?.stats;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/45 sm:items-center sm:p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={d ? `Campagne ${d.name}` : 'Campagne'}
           className="flex max-h-[92vh] w-full max-w-3xl flex-col rounded-t-3xl bg-white shadow-[0_30px_70px_-30px_rgba(11,28,63,.6)] sm:rounded-3xl"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start gap-3 border-b border-[#EEF3FB] p-5">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: m.bg, color: m.fg }}><I size={24} /></span>
          <div className="min-w-0 flex-1">
            <h3 className="break-words text-[19px] font-extrabold leading-snug text-[#0B1C3F]">{d?.name || 'Campagne'}</h3>
            {d && (
              <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-[#475569]">
                <span className="rounded-lg px-2 py-0.5 text-[12.5px] font-semibold" style={{ background: sbg, color: sfg }}>{sl}</span>
                <span>{d.type_label}</span>
                {d.terms && <span className="text-[#64748B]">· {d.terms}</span>}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer" className="rounded-full p-2 text-[#0B1C3F] hover:bg-[#F1F5F9]"><X size={20} /></button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {err && <p role="alert" className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[14px] text-[#B91C1C]">{err}</p>}
          {!d && !err && <p className="flex items-center gap-2 py-8 text-[14px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</p>}
          {d && (
            <>
              {st && (
                <div className="mb-5">
                  <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-5">
                    <Stat icon={Users} tone={['#EAF1FF', '#2F6BFF']} value={nf(st.recipients)} label="Destinataires" />
                    <Stat icon={Mail} tone={['#FFECEC', '#EF4444']} value={`${st.open_rate} %`} label="Taux d'ouverture" hint={`${nf(st.opened)} ouverture${st.opened > 1 ? 's' : ''}`} />
                    <Stat icon={MousePointerClick} tone={['#F1EAFF', '#7C3AED']} value={nf(st.clicks)} label="Clics" />
                    <Stat icon={RotateCcw} tone={['#E3F6EC', '#059669']} value={nf(st.came_back)} label="Clients revenus" hint={`${st.came_back_rate} % en ${st.window_days} j`} />
                    <Stat icon={Euro} tone={['#FFF1DC', '#F59E0B']} value={eur(st.revenue)} label="CA généré" hint={`en ${st.window_days} jours`} wide />
                  </div>
                  {st.temoin && <div className="mt-3"><TemoinResult t={st.temoin} what="cette campagne" /></div>}
                </div>
              )}

              <div className="rounded-2xl border border-[#E6EEFB] px-4">
                <Line icon={Mail} label="Message">
                  <p className="whitespace-pre-wrap break-words leading-relaxed">{d.message ? <Message text={d.message} /> : '—'}</p>
                </Line>
                {d.details && <Line icon={Info} label="Description"><p className="whitespace-pre-wrap break-words">{d.details}</p></Line>}
                {d.image_url && <Line icon={Info} label="Photo"><img src={d.image_url} alt="" className="mt-1 max-h-40 rounded-xl border border-[#E6EEFB] object-cover" /></Line>}
                {d.link_url && (
                  <Line icon={Link2} label="Lien">
                    <a href={d.link_url} target="_blank" rel="noopener noreferrer" className="break-all font-medium text-[#1463FF] underline">{d.link_url}</a>
                  </Line>
                )}
                <Line icon={Users} label="Destinataires">
                  {d.audience_label}{/^\d/.test(d.audience_label || '') ? '' : ` · ${nf(d.recipients)} client${d.recipients > 1 ? 's' : ''}`}
                  {d.recipients_list?.length > 0 && (
                    <span className="mt-1.5 flex flex-wrap gap-1.5" data-testid="campaign-recipients">
                      {d.recipients_list.map((p) => (
                        <span key={p.id} translate="no" className="notranslate rounded-full bg-[#F1F5FD] px-2.5 py-1 text-[12.5px] font-medium text-[#0B1C3F]">
                          {p.name}{p.barcode_id ? <span className="ml-1 text-[#64748B]">{p.barcode_id}</span> : null}
                        </span>
                      ))}
                      {d.recipients_more > 0 && <span className="px-1 py-1 text-[12.5px] text-[#64748B]">et {nf(d.recipients_more)} autre{d.recipients_more > 1 ? 's' : ''}</span>}
                    </span>
                  )}
                </Line>
                {d.sent_by_label && (
                  <Line icon={UserRound} label="Envoyée par"><span translate="no" className="notranslate">{d.sent_by_label}</span></Line>
                )}
                <Line icon={CalendarDays} label="Envoi">
                  {d.sent_at ? <>Envoyée le {when(d.sent_at)}</>
                    : d.status === 'scheduled' ? <>Programmée pour le {when(d.scheduled_for)}</>
                      : d.status === 'cancelled' ? <>Annulée{d.cancelled_at ? ` le ${when(d.cancelled_at)}` : ''}{d.cancel_reason ? ` · ${d.cancel_reason}` : ''}</>
                        : <>Brouillon{d.created_at ? `, créé le ${when(d.created_at)}` : ''}</>}
                  {d.sent_at && d.live_until && (
                    <span className="block text-[13px] text-[#64748B]">
                      {d.status === 'live' ? 'Visible sur la carte de vos clients jusqu\'au ' : 'Visible sur la carte jusqu\'au '}{when(d.live_until)}
                    </span>
                  )}
                </Line>
              </div>
            </>
          )}
        </div>

        {d && (
          <div className="flex flex-wrap items-center gap-2 border-t border-[#EEF3FB] p-4">
            {d.can_delete && (
              <button type="button" onClick={() => onDelete(d)} className="inline-flex items-center gap-2 rounded-xl px-3 py-2.5 text-[14px] font-semibold text-[#DC2626] hover:bg-[#FEF2F2]">
                <Trash2 size={16} /> Supprimer
              </button>
            )}
            {d.can_cancel && (
              <button type="button" onClick={() => onCancel(d)} className="inline-flex items-center gap-2 rounded-xl px-3 py-2.5 text-[14px] font-semibold text-[#B45309] hover:bg-[#FFF7ED]">
                <Ban size={16} /> Annuler l'envoi
              </button>
            )}
            <span className="flex-1" />
            {d.sent_at && (
              <button type="button" onClick={() => onAnalysis(d.id)} className="inline-flex items-center gap-2 rounded-xl border border-[#BFD3FF] px-4 py-2.5 text-[14px] font-semibold text-[#1463FF] hover:bg-[#F1F6FF]">
                <BarChart3 size={16} /> Analyse détaillée
              </button>
            )}
            {d.can_edit && (
              <button type="button" onClick={() => onEdit(d)} className="inline-flex items-center gap-2 rounded-xl bg-[#1463FF] px-4 py-2.5 text-[14px] font-semibold text-white hover:bg-[#0F54E0]">
                <Pencil size={16} /> Modifier
              </button>
            )}
            {!d.can_edit && (
              <button type="button" onClick={onClose} className="rounded-xl bg-[#1463FF] px-5 py-2.5 text-[14px] font-semibold text-white hover:bg-[#0F54E0]">Fermer</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
