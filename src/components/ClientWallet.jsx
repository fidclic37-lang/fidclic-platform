import React, { useEffect, useState } from 'react';
import { Loader2, Smartphone, Bell, History } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* « Carte Wallet » of one client (user, 2026-10-30, ROYAL TRIM LIBÉRTÉ:
   « 80 % des clients doivent rafraîchir leur carte »). Where the card is,
   each iPhone that holds it, the last pushes — Apple's answer, whether the
   iPhone asked and downloaded — and every registration event with its
   reason. Read only. */

const TZ = 'Europe/Paris';
const when = (iso) => (iso ? new Date(iso).toLocaleString('fr-FR', {
  timeZone: TZ, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : '—');

const TONE = {
  registered: { bg: '#E7F7EE', fg: '#0F7A45' },
  on_phone_unregistered: { bg: '#FEECEC', fg: '#B42318' },
  downloaded_not_registered: { bg: '#FFF4DB', fg: '#92400E' },
  removed: { bg: '#F1F5F9', fg: '#475569' },
  google: { bg: '#EEF4FF', fg: '#2F6BFF' },
  none: { bg: '#F1F5F9', fg: '#475569' },
};
const pushTone = (s) => (s === 'mis à jour' ? '#0F7A45' : s === 'en attente' ? '#64748B' : '#B42318');

const Title = ({ icon: Icon, children }) => (
  <p className="mb-2 flex items-center gap-2 text-[11.5px] font-semibold uppercase tracking-[0.04em] text-[#94A3B8]">
    <Icon size={13} /> {children}
  </p>
);

export default function ClientWallet({ clientId }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    setD(null);
    ownerAPI.clientWallet(clientId)
      .then(({ data }) => { if (alive) { setD(data); setError(''); } })
      .catch((e) => { if (alive) setError(e?.response?.data?.detail || "La carte Wallet n'a pas pu être chargée."); });
    return () => { alive = false; };
  }, [clientId]);

  if (error) return <p className="rounded-lg bg-[#FEF2F2] px-3 py-2.5 text-[13px] text-[#B91C1C]">{error}</p>;
  if (!d) return <p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</p>;

  const a = d.apple;
  const tone = TONE[a.state.key] || TONE.none;
  return (
    <div className="space-y-5" data-testid="client-wallet">
      <div>
        <span className="inline-flex rounded-md px-2.5 py-1 text-[12.5px] font-semibold" style={{ background: tone.bg, color: tone.fg }}
              data-testid="wallet-state" data-state={a.state.key}>{a.state.label}</span>
        {d.google.card && a.state.key !== 'google' && (
          <span className="ml-2 inline-flex rounded-md bg-[#EEF4FF] px-2.5 py-1 text-[12.5px] font-semibold text-[#2F6BFF]">Aussi dans Google Wallet</span>
        )}
      </div>

      <section>
        <Title icon={Smartphone}>iPhone{a.devices.length > 1 ? 's' : ''} inscrit{a.devices.length > 1 ? 's' : ''}</Title>
        {a.devices.length === 0 && <p className="text-[13px] text-[#64748B]">Aucun iPhone inscrit : cette carte ne reçoit pas de mise à jour automatique.</p>}
        <ul className="space-y-2">
          {a.devices.map((v) => (
            <li key={v.device} className="rounded-xl border border-[#EEF3FB] p-3 text-[12.5px] text-[#0B1C3F]" data-testid="wallet-device">
              <p className="font-semibold" translate="no">Appareil {v.device}</p>
              <p className="text-[#64748B]" translate="no">
                Inscrit le {when(v.registered_at)} · dernière notification {when(v.last_push_at)} · demandé {when(v.last_check_at)} · téléchargé {when(v.last_fetch_at)}
              </p>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <Title icon={Bell}>Dernières notifications</Title>
        {a.pushes.length === 0 && <p className="text-[13px] text-[#64748B]">Aucune notification envoyée à cette carte ces 30 derniers jours.</p>}
        <ul className="divide-y divide-[#EEF3FB]">
          {a.pushes.map((p, i) => (
            <li key={i} className="flex items-center justify-between gap-3 py-2 text-[12.5px]" data-testid="wallet-push">
              <span translate="no" className="text-[#0B1C3F]">{when(p.sent_at)}</span>
              <span className="font-semibold" style={{ color: pushTone(p.state) }}>{p.state}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <Title icon={History}>Historique</Title>
        {a.events.length === 0 && <p className="text-[13px] text-[#64748B]">Rien d&apos;enregistré pour l&apos;instant.</p>}
        <ul className="divide-y divide-[#EEF3FB]">
          {a.events.map((e, i) => (
            <li key={i} className="py-2 text-[12.5px]" data-testid="wallet-event">
              <span translate="no" className="mr-2 text-[#64748B]">{when(e.at)}</span>
              <span className="text-[#0B1C3F]">{e.label}</span>
              {e.detail && <span className="text-[#64748B]"> — {e.detail}</span>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
