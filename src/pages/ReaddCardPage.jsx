import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Gift, Loader2 } from 'lucide-react';
import api from '../lib/api';
import { addMine } from '../lib/myCards';

/* /carte/recuperer/:token — a client gets their card back (user, 2026-10-09).
   The shop showed a QR or sent an e-mail (components/CardReaddModal). The
   link works once, for 48 hours; opening the page uses nothing — only the
   button does, so a mail scanner that opens links cannot spend it. Then
   this phone holds the card with its owner key (lib/myCards). */
export default function ReaddCardPage() {
  const { token } = useParams();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get(`/card-readd/${encodeURIComponent(token)}`)
      .then(({ data }) => setInfo(data))
      .catch((e) => setError(e?.response?.data?.detail || 'Ce lien ne fonctionne pas.'));
  }, [token]);

  const take = async () => {
    setBusy(true); setError('');
    try {
      const { data } = await api.post(`/card-readd/${encodeURIComponent(token)}`);
      addMine(data.barcode_id, data.card_key);
      window.location.replace(`/card/${data.barcode_id}?k=${encodeURIComponent(data.card_key)}`);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Ce lien ne fonctionne plus.');
      setBusy(false);
    }
  };

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
