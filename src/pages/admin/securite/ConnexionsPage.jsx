import React, { useEffect, useState } from 'react';
import { Search, AlertTriangle, Monitor, Smartphone, Tablet } from 'lucide-react';
import { securityAPI } from '../../../lib/api';
import { Card, Loading, Breadcrumb, Select, Pager, nf, inputCls } from '../../crm/ui';
import { RangePicker, useRange, SecuTabs, flag, LOGIN_TONE, Pill, when } from './shared';

/* Super admin › Sécurité › Connexions — every login of FidClic's team. */

export default function ConnexionsPage() {
  const [range, setRange] = useRange();
  const [f, setF] = useState({ q: '', user: '', status: '' });
  const [page, setPage] = useState(1);
  const [d, setD] = useState(null);
  const [users, setUsers] = useState([]);
  useEffect(() => { securityAPI.users().then(({ data }) => setUsers(data.rows)).catch(() => {}); }, []);
  useEffect(() => {
    securityAPI.logins({ ...range, ...f, page, per_page: 20 }).then(({ data }) => setD(data)).catch(() => setD({ rows: [], total: 0, pages: 1 }));
  }, [range, f, page]);
  const setFilter = (k) => (v) => { setPage(1); setF({ ...f, [k]: v }); };
  const Device = ({ kind }) => React.createElement(kind === 'iPhone' || kind === 'Android' ? Smartphone : kind === 'iPad' ? Tablet : Monitor, { size: 14, className: 'text-[#94A3B8]' });

  return (
    <div className="crm">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', '/admin'], ['Sécurité', '/admin/securite'], ['Connexions']]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Connexions</h1>
          <p className="text-[15px] text-[#475569]">Chaque connexion de l'équipe FidClic : lieu, appareil, et celles qui ont été refusées.</p>
        </div>
        <RangePicker value={range} onChange={(v) => { setPage(1); setRange(v); }} />
      </header>
      <Card className="p-0">
        <SecuTabs />
        <div className="p-4">
          <div className="mb-3 grid gap-2 md:grid-cols-[1.6fr_1fr_1fr]">
            <label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
              <input className={`${inputCls} pl-9`} placeholder="Rechercher un nom, un pays, une ville, une IP…" value={f.q} onChange={(e) => setFilter('q')(e.target.value)} /></label>
            <Select value={f.user} onChange={setFilter('user')}><option value="">Tous les utilisateurs</option>{users.map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
            <Select value={f.status} onChange={setFilter('status')}><option value="">Tous les statuts</option><option value="ok">Réussies</option><option value="failed">Échouées</option><option value="blocked">Bloquées</option><option value="suspicious">Suspectes</option></Select>
          </div>
          {!d ? <Loading /> : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] text-[13px]">
                  <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['Date & heure', 'Utilisateur', 'Lieu', 'Adresse IP', 'Appareil', 'Statut'].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
                  <tbody>
                    {d.rows.map((r) => (
                      <tr key={r.id} className="border-b border-[#F4F7FC]">
                        <td className="whitespace-nowrap px-2 py-2.5 text-[#475569]">{when(r.at)}</td>
                        <td className="px-2 py-2.5"><span className="block font-medium text-[#0B1C3F]">{r.user}</span><span className="text-[11.5px] text-[#94A3B8]">{r.email}</span></td>
                        <td className="px-2 py-2.5"><span className="flex items-center gap-2"><span className="text-[18px] leading-none">{flag(r.cc)}</span>{[r.city, r.country].filter(Boolean).join(', ')}</span></td>
                        <td className="px-2 py-2.5 font-mono text-[12px] text-[#475569]">{r.ip || '—'}</td>
                        <td className="px-2 py-2.5 text-[#475569]"><span className="flex items-center gap-1.5"><Device kind={r.device} />{[r.device, r.browser, r.os].filter(Boolean).join(' · ') || '—'}</span></td>
                        <td className="px-2 py-2.5">
                          <span className="flex flex-wrap items-center gap-1.5"><Pill tone={LOGIN_TONE[r.status]}>{r.status}</Pill>
                            {r.suspicious && r.status !== 'Bloquée' && <span className="flex items-center gap-1 text-[11.5px] font-medium text-[#E11D48]"><AlertTriangle size={12} /> Nouveau pays</span>}
                            {r.reason && <span className="text-[11.5px] text-[#64748B]">{r.reason}</span>}</span>
                        </td>
                      </tr>
                    ))}
                    {!d.rows.length && <tr><td colSpan={6} className="py-10 text-center text-[#94A3B8]">Aucune connexion sur la période.</td></tr>}
                  </tbody>
                </table>
              </div>
              <Pager page={page} pages={d.pages} total={d.total} perPage={20} onPage={setPage} what="connexions" />
              <p className="mt-2 text-[11.5px] text-[#94A3B8]">{nf(d.total)} connexion(s). Le pays et la ville sont donnés par l'hébergeur à chaque connexion ; en local ils sont inconnus.</p>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}
