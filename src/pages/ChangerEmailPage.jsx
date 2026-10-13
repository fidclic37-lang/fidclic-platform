import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, Loader2, AlertTriangle } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * Where the « Confirmer cette adresse » link of the e-mail lands.
 *
 * The confirmation needs the session: the link proves the new inbox is real,
 * the session proves it is this account asking. Opened on a device that is not
 * signed in, it says so and sends the person to the login page — the request
 * stays open, so the same link still works afterwards (30 minutes).
 */
export default function ChangerEmailPage() {
  const [state, setState] = useState('working');     // working | done | error | signin
  const [msg, setMsg] = useState('');
  const [email, setEmail] = useState('');
  const once = useRef(false);

  useEffect(() => {
    if (once.current) return;                        // a link is single use: never fire twice
    once.current = true;
    const token = new URLSearchParams(window.location.search).get('token');
    if (!token) { setState('error'); setMsg('Lien incomplet.'); return; }
    ownerAPI.emailConfirm({ token })
      .then(({ data }) => { setEmail(data.email); setState('done'); })
      .catch((e) => {
        if (e?.response?.status === 401) { setState('signin'); return; }
        setState('error');
        setMsg(e?.response?.data?.detail || "Ce lien n'est plus valable.");
      });
  }, []);

  const Box = ({ icon, tone, title, children }) => (
    <div className="mx-auto mt-24 max-w-md rounded-2xl border border-[#E6EEFB] bg-white p-8 text-center">
      <span className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full" style={{ background: tone.bg, color: tone.fg }}>{icon}</span>
      <p className="text-[18px] font-bold text-[#0B1C3F]">{title}</p>
      <div className="mt-2 text-[14px] text-[#475569]">{children}</div>
    </div>
  );

  if (state === 'working') {
    return <Box icon={<Loader2 size={22} className="animate-spin" />} tone={{ bg: '#EAF1FF', fg: '#2F6BFF' }} title="Confirmation en cours…">
      <p>Un instant.</p>
    </Box>;
  }
  if (state === 'done') {
    return <Box icon={<CheckCircle2 size={22} />} tone={{ bg: '#E7F7EE', fg: '#10B981' }} title="Adresse confirmée">
      <p>Vous vous connectez désormais avec <strong translate="no" className="notranslate">{email}</strong>.</p>
      <Link to="/dashboard/parametres/securite" className="mt-4 inline-block rounded-xl bg-[#2F6BFF] px-4 py-2 text-[14px] font-medium text-white">Retour à la sécurité</Link>
    </Box>;
  }
  if (state === 'signin') {
    return <Box icon={<AlertTriangle size={22} />} tone={{ bg: '#FFF4DB', fg: '#B45309' }} title="Connectez-vous d'abord">
      <p>Ouvrez ce lien depuis l'appareil où vous êtes connecté, ou connectez-vous puis rouvrez-le. Votre demande reste valable 30 minutes.</p>
      <Link to="/login" className="mt-4 inline-block rounded-xl bg-[#2F6BFF] px-4 py-2 text-[14px] font-medium text-white">Se connecter</Link>
    </Box>;
  }
  return <Box icon={<AlertTriangle size={22} />} tone={{ bg: '#FEF2F2', fg: '#B91C1C' }} title="Lien inutilisable">
    <p>{msg}</p>
    <Link to="/dashboard/parametres/securite" className="mt-4 inline-block rounded-xl border border-[#DCE3EE] px-4 py-2 text-[14px] text-[#334155]">Recommencer</Link>
  </Box>;
}
