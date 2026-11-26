import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Check, Gift, Loader2, ArrowRight } from 'lucide-react';
import api from '../lib/api';
import { addMine, keyOf, ownerLink } from '../lib/myCards';
import WalletButtons from '../components/WalletButtons';

/* /carte/recuperer/:token — a client gets their card back (user, 2026-10-09).
   The shop showed a QR or sent an e-mail (components/CardReaddModal). The
   link works once, for 48 hours; opening the page uses nothing — only the
   button does, so a mail scanner that opens links cannot spend it. Then
   this phone holds the card with its owner key (lib/myCards).

   After the button (user, 2026-11-26): the « Ajouter à Apple Wallet / Google
   Wallet » screen of THAT card — components/WalletButtons, as on the signup's
   « Félicitations » and the add page (#521), every Wallet this card has, the
   phone's own first — so the client puts the card back in their Wallet; the
   card page is a link under it. The card's page has no Wallet button any more.
   A reload on this phone keeps the screen: the card's number (never its key)
   is remembered for this tab, its key is the phone's (lib/myCards). */
const DONE = 'fidclic:readd:';
const CARD = /^FT-[A-Z0-9]+$/;

function remembered(token) {
  try {
    const bc = String(window.sessionStorage.getItem(DONE + token) || '');
    return CARD.test(bc) && keyOf(bc) ? bc : null;
  } catch (_e) { return null; }
}

export default function ReaddCardPage() {
  const { token } = useParams();
  const [back, setBack] = useState(() => remembered(token));   // the card given back on this phone
  const [info, setInfo] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState('');

  useEffect(() => {
    if (back) return;
    api.get(`/card-readd/${encodeURIComponent(token)}`)
      .then(({ data }) => setInfo(data))
      .catch((e) => setError(e?.response?.data?.detail || 'Ce lien ne fonctionne pas.'));
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  const take = async () => {
    setBusy(true); setError('');
    try {
      const { data } = await api.post(`/card-readd/${encodeURIComponent(token)}`);
      const bc = String(data?.barcode_id || '').toUpperCase();
      if (!CARD.test(bc) || !data?.card_key) throw new Error('bad answer');
      addMine(bc, data.card_key);
      try { window.sessionStorage.setItem(DONE + token, bc); } catch (_e) { /* private mode: no reload memory */ }
      setBack(bc);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Ce lien ne fonctionne plus.');
      setBusy(false);
    }
  };
  const say = (m) => { setToast(m); setTimeout(() => setToast(''), 3500); };

  if (back) {
    return (
      <div className="flex min-h-screen items-start justify-center bg-[#F6F9FF] px-4 pt-10 pb-8">
        <div className="w-full max-w-sm rounded-2xl border border-[#E6EEFB] bg-white p-7 text-center shadow-[0_24px_60px_-34px_rgba(11,28,63,.45)]"
             data-testid="readd-wallet">
          <span className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#E7F6EC] text-[#15803D]">
            <Check size={24} strokeWidth={3} aria-hidden="true" />
          </span>
          <h1 className="text-[20px] font-bold text-[#0B1C3F]">Votre carte est de retour !</h1>
          <p className="mt-2 text-[14px] text-[#475569]">Ajoutez-la à votre Wallet : vos points et vos tampons y sont déjà.</p>
          <div className="mx-auto mt-2 max-w-[360px] text-left">
            <WalletButtons barcodeId={back} onError={say} big />
          </div>
          <Link to={ownerLink(back)} className="mt-5 inline-flex min-h-[44px] items-center justify-center gap-1.5 text-[14px] font-semibold text-[#1D4ED8]">
            Ouvrir ma carte <ArrowRight size={16} aria-hidden="true" />
          </Link>
          {toast && <p role="status" className="mt-3 rounded-xl bg-[#0B1C3F] px-4 py-2.5 text-[13px] text-white">{toast}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F6F9FF] px-4">
      <div className="w-full max-w-sm rounded-2xl border border-[#E6EEFB] bg-white p-7 text-center shadow-[0_24px_60px_-34px_rgba(11,28,63,.45)]">
        <span className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#EAF1FF] text-[#2F6BFF]">
          <Gift size={22} />
        </span>
        {!info && !error && <p className="flex items-center justify-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Chargement…</p>}
        {info && (
          <>
            <h1 className="text-[18px] font-bold text-[#0B1C3F]">
              Récupérez votre carte{info.business_name ? <> <span translate="no" className="notranslate">{info.business_name}</span></> : null}
            </h1>
            <p className="mt-2 text-[13.5px] text-[#475569]">
              {info.first_name ? <>Bonjour <span translate="no" className="notranslate">{info.first_name}</span>, vos</> : 'Vos'} points et vos tampons vous attendent.
              La carte s’ouvrira sur ce téléphone.
            </p>
            <button type="button" onClick={take} disabled={busy}
                    className="mt-5 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#2F6BFF] text-[14px] font-semibold text-white disabled:opacity-60">
              {busy ? <Loader2 size={16} className="animate-spin" /> : null} Récupérer ma carte
            </button>
            <p className="mt-3 text-[11.5px] text-[#94A3B8]">Ce lien fonctionne une seule fois.</p>
          </>
        )}
        {error && <p className="mt-2 rounded-xl bg-[#FEF2F2] px-3 py-2 text-[13px] text-[#B91C1C]" role="alert">{error}</p>}
      </div>
    </div>
  );
}
