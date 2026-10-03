import React, { useCallback, useEffect, useState } from 'react';
import {
  Plug, KeyRound, Webhook, BookOpen, Plus, Copy, Check, Trash2, Loader2, Send, Eye, EyeOff, RotateCw, AlertTriangle,
  CheckCircle2, XCircle, Pencil, X,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { usePlanAccess, LockedSection } from '../components/PlanAccess';

/* Paramètres › API & Intégrations (features/merchant_api.py) — keys, webhooks
   and the documentation, for the plans whose « API & Intégrations » switch is
   on (Super admin › Plan Limits). */

const BLUE = '#2F6BFF';
const when = (iso) => (iso ? new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—');
const Card = ({ children, className = '' }) => (
  <section className={`rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)] ${className}`}>{children}</section>
);
const input = 'h-10 w-full rounded-lg border border-[#DCE3EE] bg-white px-3 text-[13.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';

function CopyBtn({ text, label = 'Copier' }) {
  const [ok, setOk] = useState(false);
  const copy = async () => { try { await navigator.clipboard.writeText(text); setOk(true); setTimeout(() => setOk(false), 1500); } catch { /* no clipboard */ } };
  return (
    <button type="button" onClick={copy} className="inline-flex items-center gap-1.5 rounded-lg border border-[#DCE3EE] bg-white px-2.5 py-1.5 text-[12px] font-medium text-[#2F6BFF]">
      {ok ? <Check size={13} /> : <Copy size={13} />} {ok ? 'Copié' : label}
    </button>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#0B1C3F]/40 p-4" onClick={onClose}>
      <div className="relative w-full max-w-lg rounded-2xl bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between"><h3 className="text-[17px] font-bold text-[#0B1C3F]">{title}</h3>
          <button type="button" aria-label="Fermer" onClick={onClose} className="rounded-lg p-1 text-[#94A3B8] hover:bg-[#F4F7FC]"><X size={18} /></button></div>
        {children}
      </div>
    </div>
  );
}

const Code = ({ children }) => (
  <pre className="overflow-x-auto rounded-xl bg-[#0B1C3F] px-4 py-3 text-[12px] leading-relaxed text-[#E2E8F0]"><code>{children}</code></pre>
);

export default function ApiIntegrationsPage() {
  const access = usePlanAccess();
  const allowed = access?.has ? access.has('api_access') : true;
  const [tab, setTab] = useState('keys');
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [modal, setModal] = useState(null);
  const [flash, setFlash] = useState('');

  const load = useCallback(() => {
    ownerAPI.integrations().then(({ data }) => { setD(data); setErr(''); })
      .catch((e) => setErr(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Chargement impossible.'));
  }, []);
  useEffect(() => { if (allowed && access?.ready !== false) load(); }, [allowed, access?.ready, load]);
  const say = (m) => { setFlash(m); setTimeout(() => setFlash(''), 3000); };
  const run = async (fn, ok) => { try { await fn(); if (ok) say(ok); load(); } catch (e) { say(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Action impossible.'); } };

  if (access?.ready !== false && !allowed) return <LockedSection detail={access?.locked?.api_access} />;
  if (!d) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p> : <p key="loading" className="py-10 text-center text-[13px] text-[#64748B]"><Loader2 size={16} className="mr-1 inline animate-spin" /> Chargement…</p>;

  const TABS = [['keys', 'Clés API', KeyRound], ['webhooks', 'Webhooks', Webhook], ['docs', 'Documentation', BookOpen]];
  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-4 border-[#D5F0E0] bg-gradient-to-r from-[#F1FBF5] to-white">
        <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-[#E7F7EE] text-[#0F8B58]"><Plug size={23} /></span>
        <div className="min-w-0 flex-1">
          <p className="text-[16px] font-bold text-[#0B1C3F]">Connectez votre caisse, votre site et vos outils à FidClic</p>
          <p className="text-[13px] text-[#475569]">Adresse de l'API : <code className="rounded bg-white px-1.5 py-0.5 text-[12.5px]">{d.base_url}</code></p>
        </div>
        <div className="flex gap-5 text-center text-[12px] text-[#64748B]">
          <p><strong className="block text-[20px] text-[#0B1C3F]">{d.stats.active_keys}</strong>clés actives</p>
          <p><strong className="block text-[20px] text-[#0B1C3F]">{d.stats.active_hooks}</strong>webhooks</p>
          <p><strong className="block text-[20px] text-[#0B1C3F]">{d.stats.calls_30d}</strong>passages via l'API (30 j)</p>
        </div>
      </Card>

      {flash && <p className="rounded-xl bg-[#E7F7EE] px-4 py-2.5 text-[13px] font-medium text-[#0F8B58]">{flash}</p>}

      <div className="flex gap-1 border-b border-[#E6EEFB]">
        {TABS.map(([k, l, I]) => (
          <button key={k} type="button" onClick={() => setTab(k)} className={`inline-flex items-center gap-1.5 border-b-2 px-3.5 py-2.5 text-[13px] font-semibold ${tab === k ? 'border-[#2F6BFF] text-[#2F6BFF]' : 'border-transparent text-[#64748B]'}`}><I size={15} /> {l}</button>
        ))}
      </div>

      {tab === 'keys' && (
        <Card>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div><h2 className="text-[16px] font-bold text-[#0B1C3F]">Clés API</h2><p className="text-[13px] text-[#64748B]">Une clé par outil (caisse, site, Zapier…). Elle ne s'affiche qu'une fois : gardez-la en lieu sûr.</p></div>
            <button type="button" onClick={() => setModal({ type: 'key' })} className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Créer une clé</button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-[12.5px]">
              <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['Nom', 'Clé', 'Droits', 'Créée le', 'Dernière utilisation', 'Appels', ''].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>
                {d.keys.map((k) => (
                  <tr key={k.id} className={`border-b border-[#F4F7FC] ${k.revoked ? 'opacity-50' : ''}`}>
                    <td className="px-2 py-2.5 font-semibold text-[#0B1C3F]">{k.name}</td>
                    <td className="px-2 py-2.5 font-mono text-[#475569]">{k.prefix}…</td>
                    <td className="px-2 py-2.5"><span className={`rounded-md px-2 py-0.5 text-[11.5px] font-medium ${k.scopes.includes('write') ? 'bg-[#EAF1FF] text-[#2F6BFF]' : 'bg-[#F1F5F9] text-[#475569]'}`}>{k.scopes.includes('write') ? 'Lecture + écriture' : 'Lecture'}</span></td>
                    <td className="px-2 py-2.5 text-[#475569]">{when(k.created_at)}</td>
                    <td className="px-2 py-2.5 text-[#475569]">{k.last_used_at ? when(k.last_used_at) : 'Jamais'}</td>
                    <td className="px-2 py-2.5 text-[#475569]">{k.calls}</td>
                    <td className="px-2 py-2.5 text-right">{k.revoked ? <span className="text-[12px] text-[#94A3B8]">Révoquée</span>
                      : <button type="button" onClick={() => window.confirm(`Révoquer « ${k.name} » ? L'outil qui l'utilise sera coupé tout de suite.`) && run(() => ownerAPI.revokeApiKey(k.id), 'Clé révoquée.')} className="inline-flex items-center gap-1 rounded-lg border border-[#FCA5A5] bg-[#FEF2F2] px-2.5 py-1 text-[12px] text-[#E11D48]"><Trash2 size={12} /> Révoquer</button>}</td>
                  </tr>
                ))}
                {!d.keys.length && <tr><td colSpan={7} className="py-8 text-center text-[#64748B]">Aucune clé pour le moment.</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[12px] text-[#94A3B8]">Limite : {d.rate_per_minute} requêtes par minute et par clé.</p>
        </Card>
      )}

      {tab === 'webhooks' && (
        <>
          <Card>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div><h2 className="text-[16px] font-bold text-[#0B1C3F]">Webhooks</h2><p className="text-[13px] text-[#64748B]">FidClic prévient votre outil à chaque événement, en temps réel.</p></div>
              <button type="button" onClick={() => setModal({ type: 'hook' })} className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Ajouter un webhook</button>
            </div>
            <div className="space-y-3">
              {d.webhooks.map((h) => <HookRow key={h.id} h={h} events={d.events} onEdit={() => setModal({ type: 'hook', hook: h })}
                onTest={() => run(async () => { const { data } = await ownerAPI.testWebhook(h.id); say(data.ok ? `Test reçu (HTTP ${data.status}, ${data.ms} ms).` : `Échec du test : ${data.error || `HTTP ${data.status}`}`); }, null)}
                onDelete={() => window.confirm('Supprimer ce webhook ?') && run(() => ownerAPI.deleteWebhook(h.id), 'Webhook supprimé.')} />)}
              {!d.webhooks.length && <p className="py-6 text-center text-[13px] text-[#64748B]">Aucun webhook pour le moment.</p>}
            </div>
          </Card>
          <Card>
            <h2 className="mb-2 text-[16px] font-bold text-[#0B1C3F]">Derniers envois</h2>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-[12.5px]">
                <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['Date', 'Événement', 'Résultat', 'Durée', 'Essais', ''].map((x) => <th key={x} className="px-2 py-2 font-medium">{x}</th>)}</tr></thead>
                <tbody>
                  {d.deliveries.map((x) => (
                    <tr key={x.id} className="border-b border-[#F4F7FC]">
                      <td className="px-2 py-2 text-[#475569]">{when(x.at)}</td>
                      <td className="px-2 py-2 font-mono text-[#0B1C3F]">{x.type}</td>
                      <td className="px-2 py-2">{x.ok ? <span className="inline-flex items-center gap-1 text-[#0F8B58]"><CheckCircle2 size={14} /> HTTP {x.status}</span>
                        : <span className="inline-flex items-center gap-1 text-[#E11D48]"><XCircle size={14} /> {x.status ? `HTTP ${x.status}` : (x.error || 'Échec')}</span>}</td>
                      <td className="px-2 py-2 text-[#475569]">{x.ms} ms</td>
                      <td className="px-2 py-2 text-[#475569]">{x.attempts}</td>
                      <td className="px-2 py-2 text-right">{!x.ok && <button type="button" onClick={() => run(() => ownerAPI.resendDelivery(x.id), 'Renvoyé.')} className="inline-flex items-center gap-1 rounded-lg border border-[#DCE3EE] px-2.5 py-1 text-[12px] text-[#2F6BFF]"><RotateCw size={12} /> Renvoyer</button>}</td>
                    </tr>
                  ))}
                  {!d.deliveries.length && <tr><td colSpan={6} className="py-6 text-center text-[#64748B]">Aucun envoi pour le moment.</td></tr>}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[12px] text-[#94A3B8]">Un envoi en échec est retenté automatiquement chaque jour (3 essais).</p>
          </Card>
        </>
      )}

      {tab === 'docs' && <Docs base={d.base_url} events={d.events} rate={d.rate_per_minute} />}

      {modal?.type === 'key' && <KeyModal onClose={() => setModal(null)} onDone={() => { load(); }} />}
      {modal?.type === 'hook' && <HookModal hook={modal.hook} events={d.events} onClose={() => setModal(null)} onDone={(m) => { setModal(null); say(m); load(); }} />}
    </div>
  );
}

function HookRow({ h, events, onEdit, onTest, onDelete }) {
  const [show, setShow] = useState(false);
  const label = Object.fromEntries(events.map((e) => [e.key, e.label]));
  return (
    <div className="rounded-xl border border-[#E6EEFB] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${!h.active ? 'bg-[#CBD5E1]' : h.last_ok === false ? 'bg-[#E11D48]' : 'bg-[#10B981]'}`} />
        <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-[#0B1C3F]">{h.url}</span>
        {!h.active && <span className="rounded-md bg-[#F1F5F9] px-2 py-0.5 text-[11.5px] text-[#475569]">En pause</span>}
        {h.failures > 0 && <span className="inline-flex items-center gap-1 rounded-md bg-[#FEF2F2] px-2 py-0.5 text-[11.5px] text-[#E11D48]"><AlertTriangle size={12} /> {h.failures} échec{h.failures > 1 ? 's' : ''}</span>}
        <button type="button" onClick={onTest} className="inline-flex items-center gap-1 rounded-lg border border-[#DCE3EE] px-2.5 py-1 text-[12px] text-[#2F6BFF]"><Send size={12} /> Tester</button>
        <button type="button" onClick={onEdit} className="rounded-lg border border-[#DCE3EE] p-1.5 text-[#2F6BFF]" aria-label="Modifier"><Pencil size={13} /></button>
        <button type="button" onClick={onDelete} className="rounded-lg border border-[#FCA5A5] bg-[#FEF2F2] p-1.5 text-[#E11D48]" aria-label="Supprimer"><Trash2 size={13} /></button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">{h.events.map((e) => <span key={e} className="rounded-md bg-[#EAF1FF] px-2 py-0.5 text-[11.5px] text-[#2F6BFF]">{label[e] || e}</span>)}</div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-[#64748B]">
        Clé de signature : <code className="rounded bg-[#F4F7FC] px-1.5 py-0.5">{show ? h.secret : 'whsec_••••••••••••'}</code>
        <button type="button" onClick={() => setShow((v) => !v)} className="text-[#2F6BFF]">{show ? <EyeOff size={14} /> : <Eye size={14} />}</button>
        <CopyBtn text={h.secret} />
        {h.last_at && <span className="ml-auto">Dernier envoi : {when(h.last_at)}{h.last_status ? ` · HTTP ${h.last_status}` : ''}</span>}
      </div>
    </div>
  );
}

function KeyModal({ onClose, onDone }) {
  const [f, setF] = useState({ name: '', write: true });
  const [key, setKey] = useState(null);
  const [err, setErr] = useState('');
  const save = async () => {
    try { const { data } = await ownerAPI.createApiKey(f); setKey(data.key); onDone(); }
    catch (e) { setErr(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Création impossible.'); }
  };
  return (
    <Modal title={key ? 'Votre nouvelle clé' : 'Créer une clé API'} onClose={onClose}>
      {key ? (
        <>
          <p className="mb-2 flex items-start gap-2 rounded-lg bg-[#FFFBEB] px-3 py-2 text-[12.5px] text-[#92400E]"><AlertTriangle size={15} className="mt-0.5 shrink-0" /> Copiez-la maintenant : elle ne sera plus jamais affichée. Ne la partagez qu'avec l'outil qui en a besoin.</p>
          <code className="block break-all rounded-lg bg-[#0B1C3F] px-3 py-2.5 text-[12.5px] text-white">{key}</code>
          <div className="mt-3 flex justify-between"><CopyBtn text={key} label="Copier la clé" /><button type="button" onClick={onClose} className="rounded-lg px-4 py-2 text-[13px] font-semibold text-white" style={{ background: BLUE }}>J'ai copié la clé</button></div>
        </>
      ) : (
        <div className="space-y-3 text-[13px]">
          <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Nom (pour la reconnaître)</span>
            <input className={input} value={f.name} maxLength={60} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Ex. Caisse du comptoir" /></label>
          <label className="flex items-start gap-2"><input type="checkbox" checked={f.write} onChange={(e) => setF({ ...f, write: e.target.checked })} className="mt-0.5 h-4 w-4 accent-[#2F6BFF]" />
            <span><strong>Lecture + écriture</strong> — créer des clients, enregistrer des passages, utiliser des récompenses. Sans : lecture seule.</span></label>
          {err && <p className="text-[13px] text-[#C0392B]">{err}</p>}
          <button type="button" disabled={!f.name.trim()} onClick={save} className="w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Créer la clé</button>
        </div>
      )}
    </Modal>
  );
}

function HookModal({ hook, events, onClose, onDone }) {
  const [f, setF] = useState({ url: hook?.url || 'https://', events: hook?.events || events.map((e) => e.key), active: hook ? hook.active : true });
  const [err, setErr] = useState('');
  const toggle = (k) => setF({ ...f, events: f.events.includes(k) ? f.events.filter((x) => x !== k) : [...f.events, k] });
  const save = async () => {
    try { if (hook) await ownerAPI.editWebhook(hook.id, f); else await ownerAPI.createWebhook(f); onDone(hook ? 'Webhook modifié.' : 'Webhook ajouté.'); }
    catch (e) { setErr(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Enregistrement impossible.'); }
  };
  return (
    <Modal title={hook ? 'Modifier le webhook' : 'Ajouter un webhook'} onClose={onClose}>
      <div className="space-y-3 text-[13px]">
        <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Adresse de votre outil (https)</span>
          <input className={input} value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://votre-outil.fr/fidclic" /></label>
        <div><span className="mb-1 block text-[11.5px] text-[#64748B]">Événements envoyés</span>
          {events.map((e) => <label key={e.key} className="flex items-center gap-2 py-1"><input type="checkbox" checked={f.events.includes(e.key)} onChange={() => toggle(e.key)} className="h-4 w-4 accent-[#2F6BFF]" /> {e.label} <code className="text-[11.5px] text-[#94A3B8]">{e.key}</code></label>)}</div>
        <label className="flex items-center gap-2"><input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} className="h-4 w-4 accent-[#2F6BFF]" /> Actif</label>
        {err && <p className="text-[13px] text-[#C0392B]">{err}</p>}
        <button type="button" disabled={!f.events.length} onClick={save} className="w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Enregistrer</button>
      </div>
    </Modal>
  );
}

function Docs({ base, events, rate }) {
  const ep = [
    ['GET', '/me', 'Votre commerce et les règles de la carte (nombre de passages pour la récompense).'],
    ['GET', '/customers?search=&updated_since=&page=&per_page=', 'Vos clients (100 par page au plus).'],
    ['GET', '/customers/{id | FT-… | téléphone}', 'Un client : points, tampons, récompense disponible, lien de sa carte.'],
    ['POST', '/customers', 'Créer une carte (name, phone, email, consent: true). Même téléphone → la carte existante.'],
    ['POST', '/visits', "Enregistrer un passage / achat (customer, amount, external_id). Mêmes règles qu'au comptoir."],
    ['GET', '/visits?customer=&since=', 'Les passages, du plus récent au plus ancien.'],
    ['POST', '/rewards/redeem', 'Le client utilise sa récompense (customer, reward_name).'],
  ];
  return (
    <div className="space-y-4">
      <Card>
        <h2 className="mb-1 text-[16px] font-bold text-[#0B1C3F]">Démarrer</h2>
        <p className="mb-3 text-[13px] text-[#475569]">Chaque appel porte votre clé dans l'en-tête <code>Authorization</code>. Réponses en JSON ; {rate} requêtes par minute et par clé.</p>
        <Code>{`curl ${base}/me \\\n  -H "Authorization: Bearer fc_live_VOTRE_CLE"`}</Code>
      </Card>
      <Card>
        <h2 className="mb-2 text-[16px] font-bold text-[#0B1C3F]">Points d'accès</h2>
        <ul className="divide-y divide-[#F1F5F9]">
          {ep.map(([m, p, t]) => (
            <li key={p} className="grid gap-1 py-2.5 sm:grid-cols-[70px_minmax(0,1.2fr)_1.5fr] sm:items-center">
              <span className={`w-fit rounded-md px-2 py-0.5 text-[11.5px] font-bold ${m === 'GET' ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#EAF1FF] text-[#2F6BFF]'}`}>{m}</span>
              <code className="break-all text-[12.5px] text-[#0B1C3F]">/api/v1{p}</code><span className="text-[12.5px] text-[#475569]">{t}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card>
        <h2 className="mb-1 text-[16px] font-bold text-[#0B1C3F]">Depuis votre caisse : un passage à chaque ticket</h2>
        <p className="mb-3 text-[13px] text-[#475569]">Le client montre sa carte (QR code FT-…) ; votre caisse envoie le ticket. <code>external_id</code> = le numéro du ticket : envoyé deux fois, il n'est compté qu'une fois.</p>
        <Code>{`curl -X POST ${base}/visits \\\n  -H "Authorization: Bearer fc_live_VOTRE_CLE" \\\n  -H "Content-Type: application/json" \\\n  -d '{"customer": "FT-AKSH0001", "amount": 12.50, "external_id": "TICKET-4521"}'`}</Code>
        <p className="mt-2 text-[12.5px] text-[#64748B]">Réponse : le passage, le client à jour (tampons, points, palier) et <code>reward_unlocked</code> quand la carte est complète.</p>
      </Card>
      <Card>
        <h2 className="mb-1 text-[16px] font-bold text-[#0B1C3F]">Webhooks</h2>
        <p className="mb-2 text-[13px] text-[#475569]">Événements : {events.map((e) => <code key={e.key} className="mr-1.5">{e.key}</code>)}. Chaque envoi est un POST JSON <code>{'{ id, type, created_at, data }'}</code>, signé :</p>
        <Code>{`X-FidClic-Signature: t=1727700000,v1=<HMAC-SHA256(clé de signature, "t.corps")>`}</Code>
        <p className="mb-2 mt-3 text-[13px] text-[#475569]">Vérifier la signature (Node.js) :</p>
        <Code>{`const [t, v1] = req.headers['x-fidclic-signature'].split(',').map((p) => p.split('=')[1]);\nconst attendu = crypto.createHmac('sha256', process.env.FIDCLIC_WHSEC)\n  .update(\`\${t}.\${corpsBrut}\`).digest('hex');\nif (!crypto.timingSafeEqual(Buffer.from(v1), Buffer.from(attendu))) return res.status(401).end();`}</Code>
        <p className="mb-2 mt-3 text-[13px] text-[#475569]">En Python :</p>
        <Code>{`t, v1 = [p.split("=")[1] for p in signature.split(",")]\nattendu = hmac.new(WHSEC.encode(), f"{t}.".encode() + corps_brut, hashlib.sha256).hexdigest()\nassert hmac.compare_digest(v1, attendu)`}</Code>
        <p className="mt-2 text-[12.5px] text-[#64748B]">Répondez 2xx en moins de 4 secondes. Un échec est retenté chaque jour (3 essais) et peut être renvoyé depuis l'onglet Webhooks.</p>
      </Card>
      <Card>
        <h2 className="mb-1 text-[16px] font-bold text-[#0B1C3F]">Zapier, Make, n8n</h2>
        <p className="text-[13px] text-[#475569]">Créez un « Webhook » dans votre outil, collez son adresse dans l'onglet Webhooks : chaque nouveau client ou passage déclenche votre scénario. Pour agir dans FidClic (créer un client, ajouter un passage), utilisez une étape « Requête HTTP » avec votre clé.</p>
      </Card>
      <Card>
        <h2 className="mb-1 text-[16px] font-bold text-[#0B1C3F]">Erreurs</h2>
        <ul className="space-y-1 text-[12.5px] text-[#475569]">
          <li><code>401</code> clé manquante, invalide ou révoquée · <code>403</code> clé en lecture seule, ou API non incluse dans votre offre</li>
          <li><code>404</code> client introuvable · <code>409</code> pas de récompense disponible · <code>429</code> trop de requêtes (réessayez dans une minute)</li>
          <li>Le corps d'erreur contient <code>detail.code</code> et <code>detail.message</code>.</li>
        </ul>
      </Card>
    </div>
  );
}
