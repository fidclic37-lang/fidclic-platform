import React, { useEffect, useState } from 'react';
import { Wallet } from 'lucide-react';
import { adminAPI } from '../../lib/api';

/* Super Admin › Commerces: where each business's own Apple Wallet id stands
   (features/wallet_identities, 2026-10-30). The platform makes them by
   itself; this only says when it cannot — App Store Connect not set, or a
   business whose id Apple refused, with Apple's reason. When it cannot, the
   Super Admin imports a certificate made by hand (user, 2026-10-30). */
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { timeZone: 'Europe/Paris' }) : '');

function ImportForm({ businesses, onDone }) {
  const [tid, setTid] = useState('');
  const [identifier, setIdentifier] = useState('');
  const [cert, setCert] = useState('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const { data } = await adminAPI.walletIdentityUpload(tid, {
        certificate_pem: cert, key_pem: key, ...(identifier.trim() ? { identifier: identifier.trim() } : {}) });
      setMsg({ ok: true, text: `Identifiant ${data.identifier} prêt — certificat valable jusqu’au ${fmtDate(data.expires_at)}.` });
      setKey('');
      onDone();
    } catch (err) {
      setMsg({ ok: false, text: err?.response?.data?.detail || 'Import refusé.' });
    } finally {
      setBusy(false);
    }
  };
  const field = 'w-full rounded-lg border border-[#D9E2F1] bg-white px-3 py-2 text-[13px] text-[#0B1C3F]';
  return (
    <form onSubmit={submit} className="mt-3 space-y-2 rounded-xl bg-white/70 p-3 text-[#0B1C3F]" data-testid="wallet-identity-import">
      <label className="block text-[12px] font-semibold">Commerce
        <select required aria-label="Commerce" value={tid} onChange={(e) => setTid(e.target.value)} className={`${field} mt-1`}>
          <option value="">Choisir…</option>
          {businesses.map((b) => <option key={b.id} value={b.id}>{b.name || b.id}</option>)}
        </select>
      </label>
      <label className="block text-[12px] font-semibold">Identifiant (facultatif — sinon celui du commerce)
        <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} placeholder="pass.com.fidclic.…" className={`${field} mt-1`} />
      </label>
      <label className="block text-[12px] font-semibold">Certificat (PEM)
        <textarea required rows={3} value={cert} onChange={(e) => setCert(e.target.value)} placeholder="-----BEGIN CERTIFICATE-----" className={`${field} mt-1 font-mono`} />
      </label>
      <label className="block text-[12px] font-semibold">Clé privée (PEM, sans mot de passe)
        <textarea required rows={3} value={key} onChange={(e) => setKey(e.target.value)} placeholder="-----BEGIN PRIVATE KEY-----" className={`${field} mt-1 font-mono`} autoComplete="off" spellCheck={false} />
      </label>
      <button type="submit" disabled={busy || !tid} className="rounded-lg bg-[#2F6BFF] px-3 py-2 text-[13px] font-semibold text-white disabled:opacity-50">
        {busy ? 'Import…' : 'Importer'}
      </button>
      {msg && <p role="status" className={`text-[13px] font-medium ${msg.ok ? 'text-[#0F7A45]' : 'text-[#B42318]'}`}>{msg.text}</p>}
    </form>
  );
}

export default function WalletIdentitiesBanner() {
  const [d, setD] = useState(null);
  const [open, setOpen] = useState(false);
  const load = () => adminAPI.walletIdentities?.().then(({ data }) => setD(data)).catch(() => {});
  useEffect(() => { load(); }, []);
  if (!d) return null;
  const failed = (d.rows || []).filter((r) => r.status === 'failed');
  const manual = (d.rows || []).filter((r) => r.source === 'manual' && r.status === 'ready');
  const tone = !d.configured || failed.length ? { bg: '#FFF4DB', fg: '#92400E' } : { bg: '#E7F7EE', fg: '#0F7A45' };
  return (
    <div className="mt-4 rounded-2xl px-4 py-3 text-[13px]" style={{ background: tone.bg, color: tone.fg }} data-testid="wallet-identities">
      <div className="flex items-start justify-between gap-3">
        <p className="flex items-center gap-2 font-semibold">
          <Wallet size={15} />
          {!d.configured
            ? 'Apple Wallet : App Store Connect n’est pas configuré — les cartes restent sous l’identifiant commun.'
            : `Apple Wallet : ${d.counts?.ready || 0} commerce${(d.counts?.ready || 0) > 1 ? 's' : ''} avec leur propre identifiant`
              + (d.without ? ` · ${d.without} en attente` : '') + (failed.length ? ` · ${failed.length} en échec` : '')}
        </p>
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
                className="shrink-0 rounded-lg border border-current px-2.5 py-1 text-[12px] font-semibold">
          Importer un certificat
        </button>
      </div>
      {failed.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 pl-6">
          {failed.slice(0, 5).map((r) => (
            <li key={r.tenant_id}><span translate="no" className="notranslate font-medium">{r.name || r.tenant_id}</span> — {r.error} (nouvel essai automatique)</li>
          ))}
        </ul>
      )}
      {manual.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 pl-6" data-testid="wallet-identities-manual">
          {manual.slice(0, 5).map((r) => (
            <li key={r.tenant_id}><span translate="no" className="notranslate font-medium">{r.name || r.tenant_id}</span> — importé à la main, valable jusqu’au {fmtDate(r.expires_at)}</li>
          ))}
        </ul>
      )}
      {open && <ImportForm businesses={d.businesses || []} onDone={load} />}
    </div>
  );
}
