import React, { useCallback, useEffect, useState } from 'react';
import { X, Loader2, QrCode, Mail, Copy, Check, Search } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import api from '../lib/api';
import PhoneField from './PhoneField';

/* « Récupérer la carte » (user, 2026-10-09): a client who deleted their card
   — or removed it from Apple Wallet — gets it back with a one-time link,
   valid 48 hours (features/card_status.py):
     • a QR shown here, scanned by the client's own phone (every role);
     • the same link by e-mail (owner, administrateur, manager).
   From the Scan page (no client list for staff) the client is found by
   phone first: pass `findByPhone` instead of `customerId`. */

const err = (e, f) => e?.response?.data?.detail || f;
const when = (iso) => (iso ? new Date(iso).toLocaleString('fr-FR', {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
}) : '');
const LINK_STATE = { open: 'Valide', used: 'Utilisé', expired: 'Expiré' };
const btn = 'inline-flex h-10 items-center justify-center gap-2 rounded-xl px-4 text-[13px] font-semibold disabled:opacity-60';

export function CardStateBadge({ card, compact = false }) {
  if (!card || card.state === 'active') {
    return compact ? null : (
      <span className="inline-flex items-center gap-1 rounded-md bg-[#ECFDF3] px-2 py-0.5 text-[11px] font-semibold text-[#047857]">Carte active</span>
    );
  }
  return (
    <span title={card.at ? `Depuis le ${when(card.at)}` : undefined}
          className="inline-flex items-center gap-1 rounded-md bg-[#FEF2F2] px-2 py-0.5 text-[11px] font-semibold text-[#B91C1C]">
      {card.state === 'deleted' ? 'Carte supprimée'
        : card.state === 'google_removed' ? 'Retirée de Google Wallet' : 'Retirée d’Apple Wallet'}
      {card.at && !compact ? ` · ${new Date(card.at).toLocaleDateString('fr-FR')}` : ''}
    </span>
  );
}

export default function CardReaddModal({ customerId: initialId = null, findByPhone = false, onClose }) {
  const [customerId, setCustomerId] = useState(initialId);
  const [phone, setPhone] = useState('');
  const [info, setInfo] = useState(null);
  const [link, setLink] = useState(null);         // { url, expires_at }
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);

  const load = useCallback(async (id) => {
    try {
      const { data } = await api.get(`/owner/clients/${id}/card`);
      setInfo(data);
    } catch (e) { setError(err(e, 'Chargement impossible.')); }
  }, []);
  useEffect(() => { if (customerId) load(customerId); }, [customerId, load]);

  const find = async (e) => {
    e.preventDefault();
    setError(''); setBusy('find');
    try {
      const { data } = await api.post('/owner/card-readd/find', { phone });
      setCustomerId(data.id);
    } catch (e2) { setError(err(e2, 'Aucun client avec ce numéro.')); } finally { setBusy(''); }
  };

  const make = async (channel) => {
    setError(''); setMsg(''); setBusy(channel);
    try {
      const { data } = await api.post(`/owner/clients/${customerId}/card/readd`, { channel });
      if (channel === 'qr') setLink(data);
      else if (data.sent) setMsg(`E-mail envoyé à ${data.to}. Le lien vaut ${data.hours} heures, une seule fois.`);
      else setError(data.reason || 'L’e-mail n’a pas pu partir.');
      load(customerId);
    } catch (e) { setError(err(e, 'Action impossible.')); } finally { setBusy(''); }
  };

  const copy = async () => {
    try { await navigator.clipboard.writeText(link.url); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch (_e) { /* no clipboard */ }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/40 sm:items-center sm:p-4" onClick={onClose}
         role="dialog" aria-modal="true" aria-label="Récupérer la carte">
      <div className="max-h-[92vh] w-full max-w-md overflow-y-auto rounded-t-2xl bg-white p-5 shadow-[0_30px_70px_-30px_rgba(11,28,63,.6)] sm:rounded-2xl"
           onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-[16px] font-bold text-[#0B1C3F]">Récupérer la carte</h3>
            <p className="text-[12.5px] text-[#64748B]">
              {info ? <><span translate="no" className="notranslate">{info.name}</span> · </> : null}
              Un lien à usage unique, valable 48 heures, qui remet la carte sur le téléphone du client.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#334155]"><X size={18} /></button>
        </div>

        {findByPhone && !customerId && (
          <form onSubmit={find} className="space-y-2">
            <span className="block text-[12px] font-semibold text-[#475569]">Téléphone du client</span>
            <div className="flex h-11 items-stretch rounded-xl border border-[#E6EEFB] bg-white focus-within:border-[#2F6BFF]">
              <PhoneField value={phone} onChange={setPhone} aria-label="Téléphone du client"
                          selectClassName="shrink-0 cursor-pointer rounded-l-xl border-r border-[#E6EEFB] bg-transparent pl-2 pr-1 text-[13px] text-[#0B1C3F] outline-none"
                          inputClassName="min-w-0 flex-1 rounded-r-xl bg-transparent px-3 text-[13.5px] text-[#0B1C3F] outline-none" />
            </div>
            <button type="submit" disabled={busy === 'find' || !phone} className={`${btn} w-full bg-[#2F6BFF] text-white`}>
              {busy === 'find' ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />} Trouver le client
            </button>
          </form>
        )}

        {info && (
          <>
            <div className="mb-4 flex items-center justify-between rounded-xl bg-[#F8FAFF] px-3 py-2.5 text-[12.5px] text-[#334155]">
              <span>État de la carte</span>
              <CardStateBadge card={info.state} />
            </div>

            {link ? (
              <div className="rounded-2xl border border-[#E6EEFB] p-4 text-center">
                <p className="mb-3 text-[13px] font-semibold text-[#0B1C3F]">Le client scanne ce QR avec son téléphone</p>
                <div className="mx-auto inline-block rounded-xl bg-white p-2"><QRCodeSVG value={link.url} size={190} level="M" /></div>
                <p className="mt-3 text-[11.5px] text-[#64748B]">Valable jusqu’au {when(link.expires_at)} · une seule fois</p>
                <button type="button" onClick={copy} className={`${btn} mt-3 border border-[#E6EEFB] text-[#334155]`}>
                  {copied ? <Check size={15} /> : <Copy size={15} />} {copied ? 'Lien copié' : 'Copier le lien'}
                </button>
              </div>
            ) : (
              <div className="grid gap-2">
                <button type="button" onClick={() => make('qr')} disabled={!!busy} className={`${btn} bg-[#2F6BFF] text-white`}>
                  {busy === 'qr' ? <Loader2 size={15} className="animate-spin" /> : <QrCode size={15} />} Afficher le QR en caisse
                </button>
                {info.can_email && (
                  <button type="button" onClick={() => make('email')} disabled={!!busy || !info.email}
                          title={info.email ? undefined : 'Ce client n’a pas d’e-mail'}
                          className={`${btn} border border-[#E6EEFB] text-[#334155]`}>
                    {busy === 'email' ? <Loader2 size={15} className="animate-spin" /> : <Mail size={15} />}
                    {info.email ? <>Envoyer par e-mail à <span translate="no" className="notranslate">{info.email}</span></> : 'Pas d’e-mail pour ce client'}
                  </button>
                )}
              </div>
            )}

            {info.links?.length > 0 && (
              <div className="mt-5 border-t border-[#EEF3FB] pt-3">
                <p className="mb-2 text-[12px] font-semibold text-[#475569]">Liens envoyés</p>
                <ul className="space-y-1.5 text-[12px] text-[#334155]">
                  {info.links.map((l, i) => (
                    <li key={i} className="flex items-center justify-between gap-2">
                      <span>{l.channel === 'email' ? 'E-mail' : 'QR'} · {when(l.created_at)}</span>
                      <span className={l.state === 'open' ? 'font-semibold text-[#047857]' : 'text-[#94A3B8]'}>{LINK_STATE[l.state]}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}

        {msg && <p className="mt-3 rounded-xl bg-[#ECFDF3] px-3 py-2 text-[12.5px] text-[#065F46]" role="status">{msg}</p>}
        {error && <p className="mt-3 rounded-xl bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]" role="alert">{error}</p>}
      </div>
    </div>
  );
}
