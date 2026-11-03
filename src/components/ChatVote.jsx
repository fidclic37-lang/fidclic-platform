import React, { useState } from 'react';
import { ThumbsUp, ThumbsDown } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* 👍 / 👎 under a Copilote answer (learning log, user 2026-11-02): the owner
   says whether it helped; on 👎 a reason and a note. What FidClic IA learns
   from (api/features/learning_log.py) — names, phones and e-mails are
   removed before anything is kept. */

const REASONS = [['faux_chiffre', 'Chiffre faux'], ['pas_utile', 'Pas utile'], ['pas_clair', 'Pas clair'], ['autre', 'Autre']];

export default function ChatVote({ id, vote: initial }) {
  const [vote, setVote] = useState(initial || null);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState(null);
  const [note, setNote] = useState('');
  const [thanks, setThanks] = useState(false);

  const send = async (v, why = null, text = '') => {
    try {
      await ownerAPI.aiFeedback({ id, vote: v, ...(why ? { reason: why } : {}), ...(text.trim() ? { text: text.trim().slice(0, 500) } : {}) });
      setVote(v);
      setThanks(true);
    } catch { /* a lost vote is not worth an error */ }
  };
  const up = () => { setAsking(false); send('up'); };
  const down = () => { setVote('down'); setAsking(true); setThanks(false); send('down'); };

  return (
    <div className="mt-1 text-[11px] text-[#64748B]" data-testid="chat-vote">
      <div className="flex items-center gap-1">
        <button type="button" aria-label="Réponse utile" aria-pressed={vote === 'up'} onClick={up} data-testid="vote-up"
                className={`rounded-md p-1 hover:bg-[#EEF3FF] ${vote === 'up' ? 'text-[#047857]' : ''}`}><ThumbsUp size={13} /></button>
        <button type="button" aria-label="Réponse pas utile" aria-pressed={vote === 'down'} onClick={down} data-testid="vote-down"
                className={`rounded-md p-1 hover:bg-[#EEF3FF] ${vote === 'down' ? 'text-[#B91C1C]' : ''}`}><ThumbsDown size={13} /></button>
        {thanks && !asking && <span>Merci, FidClic IA en tient compte.</span>}
      </div>
      {asking && (
        <div className="mt-1 rounded-lg border border-[#E6EEFB] bg-white p-2" data-testid="vote-why">
          <p className="mb-1 font-semibold text-[#334155]">Qu'est-ce qui n'allait pas ?</p>
          <div className="flex flex-wrap gap-1">
            {REASONS.map(([k, l]) => (
              <button key={k} type="button" onClick={() => setReason(k)} aria-pressed={reason === k}
                      className={`rounded-full border px-2 py-0.5 ${reason === k ? 'border-[#2F6BFF] bg-[#EEF3FF] text-[#2F6BFF]' : 'border-[#DCE3EE]'}`}>{l}</button>
            ))}
          </div>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} rows={2} placeholder="Un détail (facultatif)"
                    className="mt-1 w-full rounded-md border border-[#DCE3EE] px-2 py-1 text-[12px]" aria-label="Détail" />
          <div className="mt-1 flex gap-1.5">
            <button type="button" onClick={() => { send('down', reason, note); setAsking(false); }} data-testid="vote-send"
                    className="rounded-md bg-[#2F6BFF] px-2.5 py-1 font-semibold text-white">Envoyer</button>
            <button type="button" onClick={() => setAsking(false)} className="rounded-md px-2 py-1">Fermer</button>
          </div>
        </div>
      )}
    </div>
  );
}
