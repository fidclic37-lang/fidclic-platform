import React, { useEffect, useState } from 'react';
import { X, Loader2, Send, Users, MousePointerClick, ShoppingCart } from 'lucide-react';
import { ownerAPI } from '../../lib/api';
import { eur } from '../../lib/money';

/*
 * « Performance des campagnes », opened (user, 2026-10-23: a card opened the
 * Campagnes page instead of what it counts). One window, four tabs — the
 * campaigns of the period, the clients they reached, who clicked, the visits
 * credited — each with one line saying what is counted, so « 0 clic, 1 vente »
 * reads as what it is.
 */
const TABS = [
  { key: 'campaigns', label: 'Campagnes envoyées', icon: Send,
    note: 'Les campagnes parties sur la période. Ouvrez-en une pour son message, ses destinataires et son résultat.' },
  { key: 'touched', label: 'Clients touchés', icon: Users,
    note: 'Les clients qui ont reçu au moins une campagne de la période.' },
  { key: 'clicks', label: 'Clics', icon: MousePointerClick,
    note: "Un clic = le client a appuyé sur le lien ou sur « Voir l'offre » de la campagne. Ouvrir sa carte ou lire la notification n'est pas un clic."  },
  { key: 'sales', label: 'Ventes attribuées', icon: ShoppingCart,
    note: 'Une vente est attribuée quand un client passe en caisse dans les {d} jours après avoir reçu la campagne — même sans avoir cliqué. Chaque passage compte pour une seule campagne, la plus récente.' },
];

const nf = (n) => Number(n || 0).toLocaleString('fr-FR');
const day = (iso) => { try { return new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }); } catch { return ''; } };
const dayTime = (iso) => { try { return new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); } catch { return ''; } };

export default function CampaignLists({ days, start = 'campaigns', onClose, onOpenCampaign, onOpenClient }) {
  const [tab, setTab] = useState(start);
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    let alive = true;
    ownerAPI.homeCampaigns({ days })
      .then(({ data }) => { if (alive) setD(data); })
      .catch((e) => { if (alive) setErr(e?.response?.data?.detail || 'Impossible de charger le détail.'); });
    return () => { alive = false; };
  }, [days]);
  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [onClose]);

  const meta = TABS.find((t) => t.key === tab) || TABS[0];
  const Client = ({ p }) => (
    <button type="button" onClick={() => onOpenClient(p.customer_id)} translate="no"
            className="notranslate text-left font-semibold text-[#0B1C3F] hover:text-[#1463FF] hover:underline">
      {p.name}{p.barcode_id ? <span className="ml-1.5 text-[11.5px] font-normal text-[#94A3B8]">{p.barcode_id}</span> : null}
    </button>
  );
  const Camp = ({ id, name }) => (
    <button type="button" onClick={() => onOpenCampaign(id)} className="text-left text-[#1463FF] hover:underline">{name}</button>
  );
  const empty = (txt) => <p className="py-8 text-center text-[13px] text-[#94A3B8]">{txt}</p>;

  let body = null;
  if (d) {
    if (tab === 'campaigns') {
      body = d.campaigns.length ? (
        <ul className="divide-y divide-[#F1F5F9]">
          {d.campaigns.map((c) => (
            <li key={c.id}>
              <button type="button" onClick={() => onOpenCampaign(c.id)} className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 py-3 text-left hover:bg-[#F8FAFF]">
                <span className="min-w-0 flex-1 truncate text-[13.5px] font-semibold text-[#0B1C3F]">{c.name}</span>
                <span className="text-[12px] text-[#64748B]">{day(c.sent_at)}</span>
                <span className="text-[12px] text-[#475569]"><b>{nf(c.recipients)}</b> touchés · <b>{nf(c.clicks)}</b> clics · <b>{nf(c.sales)}</b> ventes · {eur(c.revenue)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : empty('Aucune campagne envoyée sur la période.');
    } else if (tab === 'touched') {
      body = d.touched.length ? (
        <ul className="divide-y divide-[#F1F5F9]">
          {d.touched.map((p) => (
            <li key={p.customer_id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-[13px]">
              <span className="min-w-0 flex-1"><Client p={p} /></span>
              <span className="text-[12px] text-[#64748B]">{p.campaigns.join(' · ')}</span>
            </li>
          ))}
        </ul>
      ) : empty("Aucun client n'a reçu de campagne sur la période.");
    } else if (tab === 'clicks') {
      body = (
        <>
          <p className="mb-2 text-[12.5px] text-[#475569]"><b>{nf(d.clicks.total)}</b> clic{d.clicks.total > 1 ? 's' : ''} au total — un client peut cliquer plusieurs fois.</p>
          {d.clicks.people.length ? (
            <ul className="divide-y divide-[#F1F5F9]">
              {d.clicks.people.map((p, i) => (
                <li key={`${p.customer_id}-${p.campaign_id}-${i}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-[13px]">
                  <span className="min-w-0 flex-1"><Client p={p} /></span>
                  <Camp id={p.campaign_id} name={p.campaign} />
                </li>
              ))}
            </ul>
          ) : empty(d.clicks.total ? 'Les clics ont été faits sans carte reconnue : le client ne peut pas être nommé.' : 'Aucun clic sur la période.')}
        </>
      );
    } else {
      body = d.sales.length ? (
        <ul className="divide-y divide-[#F1F5F9]">
          {d.sales.map((s, i) => (
            <li key={`${s.customer_id}-${s.visit_time}-${i}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-[13px]">
              <span className="min-w-0 flex-1"><Client p={s} /></span>
              <span className="text-[12px] text-[#64748B]">{dayTime(s.visit_time)}</span>
              <span className="w-20 text-right font-semibold tabular-nums text-[#0B1C3F]">{eur(s.amount)}</span>
              <Camp id={s.campaign_id} name={s.campaign} />
            </li>
          ))}
        </ul>
      ) : empty('Aucune vente attribuée sur la période.');
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Performance des campagnes" onClick={(e) => e.stopPropagation()}
           className="flex max-h-[88vh] w-[min(760px,100%)] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <header className="flex items-center gap-3 border-b border-[#EEF3FB] px-5 py-4">
          <p className="flex-1 text-[16px] font-bold text-[#0B1C3F]">Performance des campagnes</p>
          <button type="button" aria-label="Fermer" onClick={onClose} className="text-[#94A3B8] hover:text-[#0B1C3F]"><X size={20} /></button>
        </header>
        <div className="flex flex-wrap gap-1.5 border-b border-[#EEF3FB] px-5 py-3" role="tablist">
          {TABS.map((t) => {
            const I = t.icon;
            const n = !d ? null : t.key === 'campaigns' ? d.campaigns.length : t.key === 'touched' ? d.touched.length
              : t.key === 'clicks' ? d.clicks.total : d.sales.length;
            return (
              <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
                      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] font-semibold ${tab === t.key ? 'bg-[#1463FF] text-white' : 'bg-[#F1F5F9] text-[#475569]'}`}>
                <I size={14} /> {t.label}{n != null ? ` · ${nf(n)}` : ''}
              </button>
            );
          })}
        </div>
        <div className="overflow-y-auto px-5 py-3" data-testid={`campaign-lists-${tab}`}>
          <p className="mb-2 rounded-xl bg-[#F8FAFF] px-3 py-2 text-[12.5px] text-[#475569]">{meta.note.replace('{d}', d?.window_days || 15)}</p>
          {err && <p className="py-6 text-center text-[13px] text-[#B91C1C]">{err}</p>}
          {!d && !err && <p className="flex items-center justify-center gap-2 py-8 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</p>}
          {body}
        </div>
      </div>
    </div>
  );
}
