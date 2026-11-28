import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, AlertTriangle, Loader2, RotateCw, Unplug, Store, ExternalLink } from 'lucide-react';
import { ownerAPI } from '../../lib/api';

/* Paramètres › API & Intégrations › Caisse (api/features/pos_connectors.py).
   Connect a caisse (Square first), map its locations to the business's
   stores, see today's tickets, check now, disconnect. Never shows a token. */

const BLUE = '#2F6BFF';
const when = (iso) => (iso ? new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—');
const detail = (e, fb) => {
  const d = e?.response?.data?.detail;
  return typeof d === 'string' ? d : (d?.message || fb);
};
const REASONS = {
  lien: 'Le lien de connexion a expiré ou a déjà servi : recommencez.',
  refus: 'La connexion a été refusée sur la page de la caisse.',
  plan: "Votre offre n'inclut pas « API & Intégrations ».",
  code: "La caisse n'a pas validé la connexion : recommencez.",
  deja_liee: 'Ce compte de caisse est déjà relié à un autre commerce FidClic.',
};

function Status({ c }) {
  if (c.status === 'connected') {
    return <span className="inline-flex items-center gap-1 rounded-md bg-[#E7F7EE] px-2 py-0.5 text-[12px] font-semibold text-[#0F8B58]"><CheckCircle2 size={13} /> Connectée</span>;
  }
  return <span className="inline-flex items-center gap-1 rounded-md bg-[#FEF2F2] px-2 py-0.5 text-[12px] font-semibold text-[#B91C1C]"><AlertTriangle size={13} /> À reconnecter</span>;
}

export default function CaisseConnectors({ canEdit = true }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState(() => {
    try {
      const q = new URLSearchParams(window.location.search);
      if (q.get('caisse') === 'ok') return { ok: true, text: 'Caisse connectée. Les cartes partent vers la caisse, les ventes arrivent dans FidClic.' };
      if (q.get('caisse') === 'erreur') return { ok: false, text: REASONS[q.get('raison')] || 'La connexion n’a pas abouti : recommencez.' };
    } catch { /* no URL */ }
    return null;
  });

  const load = useCallback(() => {
    ownerAPI.posConnectors().then(({ data }) => { setD(data); setErr(''); })
      .catch((e) => setErr(detail(e, 'Chargement impossible.')));
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {        // the ?caisse= note is read once: a reload does not show it again
    try {
      const u = new URL(window.location.href);
      if (u.searchParams.has('caisse')) { u.searchParams.delete('caisse'); u.searchParams.delete('raison'); window.history.replaceState(null, '', u.toString()); }
    } catch { /* ignore */ }
  }, []);

  const act = async (key, fn, ok) => {
    setBusy(key);
    try { const r = await fn(); if (ok) setMsg({ ok: true, text: typeof ok === 'function' ? ok(r) : ok }); load(); } catch (e) { setMsg({ ok: false, text: detail(e, 'Action impossible.') }); }
    setBusy('');
  };
  const connect = (name) => act(`connect-${name}`, async () => {
    const { data } = await ownerAPI.posConnect(name);
    if (data?.url) window.location.assign(data.url);
  });

  if (!d) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p>
    : <p className="py-10 text-center text-[13px] text-[#64748B]"><Loader2 size={16} className="mr-1 inline animate-spin" /> Chargement…</p>;

  const connectedNames = new Set(d.connections.map((c) => c.provider));
  return (
    <div className="space-y-4" data-testid="caisse-connectors">
      {msg && <p role="status" className={`rounded-xl px-4 py-2.5 text-[13px] font-medium ${msg.ok ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FEF2F2] text-[#B91C1C]'}`}>{msg.text}</p>}

      {d.connections.map((c) => (
        <section key={c.id} className="rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)]" data-testid={`caisse-${c.provider}`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="flex items-center gap-2 text-[16px] font-bold text-[#0B1C3F]">{c.label} <Status c={c} /></p>
              <p className="text-[13px] text-[#64748B]">Compte : <span translate="no" className="notranslate font-medium text-[#0B1C3F]">{c.merchant_name}</span> · connectée le {when(c.connected_at)}</p>
            </div>
            {canEdit && (
              <div className="flex flex-wrap gap-2">
                {c.status !== 'connected' && <button type="button" onClick={() => connect(c.provider)} disabled={!!busy} className="inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-white" style={{ background: BLUE }}><ExternalLink size={14} /> Reconnecter</button>}
                <button type="button" disabled={!!busy || c.status !== 'connected'} onClick={() => act(`sync-${c.id}`, () => ownerAPI.posSync(c.id), (r) => `Vérification faite : ${r.data.tickets_applied} ticket(s), ${r.data.customers_pushed} carte(s) envoyée(s)${r.data.tickets_left ? ` — ${r.data.tickets_left} autre(s) cette nuit` : ''}.`)}
                  className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#DCE3EE] bg-white px-3 text-[13px] font-medium text-[#2F6BFF] disabled:opacity-50">
                  {busy === `sync-${c.id}` ? <Loader2 size={14} className="animate-spin" /> : <RotateCw size={14} />} Vérifier maintenant</button>
                <button type="button" disabled={!!busy} onClick={() => window.confirm(`Déconnecter ${c.label} ? Les ventes n'arriveront plus dans FidClic et les cartes envoyées à ${c.label} y seront effacées. L'historique reste dans FidClic.`) && act(`off-${c.id}`, () => ownerAPI.posDisconnect(c.id), `${c.label} déconnectée. Les cartes envoyées à ${c.label} y sont effacées dans les minutes qui viennent.`)}
                  className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#FCA5A5] bg-[#FEF2F2] px-3 text-[13px] font-medium text-[#E11D48]"><Unplug size={14} /> Déconnecter</button>
              </div>
            )}
          </div>

          {c.error?.message && <p className="mt-3 rounded-lg bg-[#FFF7E6] px-3 py-2 text-[12.5px] text-[#B45309]"><AlertTriangle size={13} className="mr-1 inline" />{c.error.message}</p>}

          <div className="mt-4 grid gap-3 sm:grid-cols-4">
            {[['Tickets aujourd’hui', c.today.tickets], ['Avec une carte FidClic', c.today.matched], ['Cartes envoyées à la caisse', c.customers_linked],
              ['Tickets en échec', c.failed_events]].map(([l, v]) => (
              <div key={l} className="rounded-xl bg-[#F7F9FD] px-3 py-2.5"><p className="text-[20px] font-bold text-[#0B1C3F]" translate="no">{v}</p><p className="text-[12px] text-[#64748B]">{l}</p></div>
            ))}
          </div>
          <p className="mt-2 text-[12px] text-[#94A3B8]">Dernière vente reçue : {when(c.last_ticket_at)} · vérification de nuit : {c.last_reconcile_day || 'pas encore'}</p>

          {c.locations.length > 0 && (
            <div className="mt-4">
              <p className="mb-2 flex items-center gap-1.5 text-[13.5px] font-semibold text-[#0B1C3F]"><Store size={15} /> Quel établissement pour chaque caisse ?</p>
              <div className="space-y-2">
                {c.locations.map((l) => (
                  <label key={l.id} className="flex flex-wrap items-center gap-3 text-[13px] text-[#475569]">
                    <span className="min-w-[160px] font-medium text-[#0B1C3F]" translate="no">{l.name}</span>
                    <select aria-label={`Établissement pour ${l.name}`} disabled={!canEdit || !!busy} value={c.location_map[l.id] || ''}
                      onChange={(e) => act(`map-${c.id}`, () => ownerAPI.posSetLocations(c.id, { ...c.location_map, [l.id]: e.target.value }), 'Établissement enregistré.')}
                      className="h-9 rounded-lg border border-[#DCE3EE] bg-white px-2 text-[13px]">
                      <option value="">Établissement principal</option>
                      {d.stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  </label>
                ))}
              </div>
            </div>
          )}
        </section>
      ))}

      <section className="rounded-2xl border border-[#EDF1F7] bg-white p-4">
        <h2 className="text-[16px] font-bold text-[#0B1C3F]">Connecter une caisse</h2>
        <p className="mb-3 text-[13px] text-[#64748B]">Le client montre sa carte FidClic, la caisse la scanne, et la vente arrive toute seule dans FidClic : passages, points et récompenses, sans rien retaper.</p>
        <div className="flex flex-wrap gap-2">
          {d.providers.filter((p) => !connectedNames.has(p.name)).map((p) => (
            <button key={p.name} type="button" disabled={!canEdit || !p.configured || !!busy} onClick={() => connect(p.name)}
              className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white disabled:opacity-50" style={{ background: BLUE }}>
              {busy === `connect-${p.name}` ? <Loader2 size={15} className="animate-spin" /> : <ExternalLink size={15} />} Connecter {p.label}{!p.configured && ' (bientôt)'}
            </button>
          ))}
          {d.providers.every((p) => connectedNames.has(p.name)) && <p className="text-[13px] text-[#64748B]">Toutes les caisses disponibles sont connectées. Zelty, L’Addition, Lightspeed… arrivent ensuite.</p>}
        </div>
      </section>
    </div>
  );
}
