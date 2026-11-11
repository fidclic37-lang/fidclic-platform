import React, { useCallback, useEffect, useState } from 'react';
import { Settings2, CheckCircle2, XCircle, AlertTriangle, Loader2, PlayCircle, Server } from 'lucide-react';
import { settingsAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { can } from '../../lib/perms';
import { Card, Loading, Breadcrumb, nf } from '../crm/ui';

/* Super admin › Paramètres (user, 2026-11-11). Three tabs, built one PR at a
   time: Services (here), Plateforme, Mes paramètres.

   Services: every outside service FidClic runs on — set or missing (the
   NAMES of what is missing, never a value), what it powers, what stops
   without it — and « Tester », a real small check that never reaches a shop
   or a customer. Server: api/features/platform_services.py. */

const when = (s) => (s ? new Date(s).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'Europe/Paris' }) : '');

function Row({ s, editable }) {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const test = async () => {
    setBusy(true);
    try { const { data } = await settingsAPI.testService(s.key); setRes(data); }
    catch (e) { setRes({ ok: false, message: e?.response?.data?.detail || 'Le test a échoué.' }); }
    finally { setBusy(false); }
  };
  const Icon = s.present ? CheckCircle2 : (s.required ? XCircle : AlertTriangle);
  const tone = s.present ? '#10B981' : (s.required ? '#E11D48' : '#F59E0B');
  return (
    <li className="flex flex-wrap items-start gap-3 py-3" data-service={s.key}>
      <Icon size={18} style={{ color: tone }} className="mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] font-semibold text-[#0B1C3F]">
          <span translate="no">{s.label}</span>
          {s.required && <span className="ml-2 rounded bg-[#FDECEF] px-1.5 py-0.5 text-[10.5px] font-semibold text-[#E11D48]">Indispensable</span>}
          <span data-testid={`state-${s.key}`} className={`ml-2 rounded px-1.5 py-0.5 text-[10.5px] font-semibold ${s.present ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FFF4DB] text-[#B45309]'}`}>{s.present ? 'Configuré' : 'Manquant'}</span>
        </p>
        <p className="text-[12.5px] text-[#475569]">{s.powers}</p>
        {!s.present && (
          <>
            <p className="mt-1 text-[12.5px] text-[#B45309]">Sans lui : {s.without}</p>
            <p className="mt-1 flex flex-wrap gap-1 text-[11.5px] text-[#64748B]">À ajouter dans Vercel :
              {s.missing.map((m) => <code key={m} translate="no" className="rounded bg-[#F1F5F9] px-1.5 py-0.5 text-[11px] text-[#0B1C3F]">{m}</code>)}
            </p>
          </>
        )}
        {res && (
          <p data-testid={`result-${s.key}`} className={`mt-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] ${res.ok ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FEF2F2] text-[#B91C1C]'}`}>
            {res.ok ? '✓ ' : '✗ '}{res.message}{res.at && <span className="ml-1 opacity-70" translate="no">· {when(res.at)}{res.ms != null ? ` · ${res.ms} ms` : ''}</span>}
          </p>
        )}
      </div>
      {s.testable && editable && (
        <button type="button" onClick={test} disabled={busy} aria-label={`Tester ${s.label}`}
                className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-[#BFD3FF] px-2.5 text-[12.5px] font-medium text-[#2F6BFF] hover:bg-[#EFF5FF] disabled:opacity-50">
          {busy ? <Loader2 size={13} className="animate-spin" /> : <PlayCircle size={13} />} Tester
        </button>
      )}
    </li>
  );
}

function Services({ editable }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const load = useCallback(() => {
    settingsAPI.services().then(({ data }) => { setD(data); setErr(''); })
      .catch((e) => setErr(e?.response?.data?.detail || 'La liste n\'a pas pu être chargée.'));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (err) return <p className="rounded-xl bg-[#FEF2F2] px-3 py-2 text-[13px] text-[#B91C1C]">{err}</p>;
  if (!d) return <Loading />;
  const S = d.summary;
  return (
    <>
      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-4">
          <Server size={20} className="text-[#2F6BFF]" />
          <p className="flex-1 text-[14px] text-[#0B1C3F]" data-testid="services-summary">
            <b>{nf(S.ready)}</b> services sur {nf(S.total)} configurés
            {S.required_missing > 0 && <span className="ml-2 font-semibold text-[#E11D48]">· {nf(S.required_missing)} indispensable{S.required_missing > 1 ? 's' : ''} manquant{S.required_missing > 1 ? 's' : ''}</span>}
          </p>
          <p className="text-[12px] text-[#64748B]" translate="no">{[d.deployment.env, d.deployment.region, d.deployment.commit].filter(Boolean).join(' · ')}</p>
        </div>
        <p className="mt-2 text-[12px] text-[#64748B]">Les clés se règlent dans Vercel › Settings › Environment Variables, puis « Redeploy ». Leur valeur n'est jamais affichée ici. « Tester » ne contacte jamais un commerce ni un client : l'email de test part vers vous.</p>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        {d.groups.map((g) => (
          <Card key={g.key}>
            <h2 className="mb-1 flex items-center justify-between text-[14.5px] font-bold text-[#0B1C3F]">{g.label}
              <span className="text-[12px] font-medium text-[#64748B]">{g.items.filter((i) => i.present).length}/{g.items.length}</span></h2>
            <ul className="divide-y divide-[#F1F5F9]">{g.items.map((s) => <Row key={s.key} s={s} editable={editable} />)}</ul>
          </Card>
        ))}
      </div>
    </>
  );
}

const TABS = [['services', 'Services']];

export default function AdminSettingsPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState('services');
  const editable = can(user, 'parametres', 'edit');
  return (
    <div className="mx-auto max-w-[1400px] p-4 sm:p-6">
      <Breadcrumb items={[['Super Admin', '/admin'], ['Paramètres']]} />
      <div className="mb-4 flex items-center gap-2.5">
        <Settings2 size={22} className="text-[#2F6BFF]" />
        <div>
          <h1 className="text-[22px] font-bold text-[#0B1C3F]">Paramètres</h1>
          <p className="text-[13px] text-[#64748B]">Les services dont FidClic dépend, et leur état.</p>
        </div>
      </div>
      <nav className="mb-4 flex gap-1 border-b border-[#EDF1F7]" role="tablist">
        {TABS.map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                  className={`-mb-px border-b-2 px-3 py-2 text-[13.5px] font-medium ${tab === k ? 'border-[#2F6BFF] text-[#2F6BFF]' : 'border-transparent text-[#64748B]'}`}>{l}</button>
        ))}
      </nav>
      {tab === 'services' && <Services editable={editable} />}
    </div>
  );
}
