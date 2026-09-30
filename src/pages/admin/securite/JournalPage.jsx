import React, { useEffect, useState } from 'react';
import { Search, Download } from 'lucide-react';
import { securityAPI } from '../../../lib/api';
import { Card, Loading, Breadcrumb, Select, Pager, useToast, downloadBlob, inputCls } from '../../crm/ui';
import { RangePicker, useRange, SecuTabs } from './shared';
import { JournalTable } from './SecuriteOverviewPage';

/* Super admin › Sécurité › Journal d'activité — every change made by
   FidClic's team, including the refused ones. */

const CATEGORIES = ['Plans & abonnements', 'Commerces', 'Utilisateurs', 'Paramètres', 'Sécurité', 'CRM de prospection', 'Autres'];

export default function JournalPage() {
  const [range, setRange] = useRange();
  const [f, setF] = useState({ q: '', user: '', category: '', status: '' });
  const [page, setPage] = useState(1);
  const [d, setD] = useState(null);
  const [users, setUsers] = useState([]);
  const [say, toast] = useToast();
  useEffect(() => { securityAPI.users().then(({ data }) => setUsers(data.rows)).catch(() => {}); }, []);
  useEffect(() => {
    securityAPI.journal({ ...range, ...f, page, per_page: 20 }).then(({ data }) => setD(data)).catch(() => setD({ rows: [], total: 0, pages: 1 }));
  }, [range, f, page]);
  const setFilter = (k) => (v) => { setPage(1); setF({ ...f, [k]: v }); };

  return (
    <div className="crm">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', '/admin'], ['Admin', '/admin/securite'], ["Journal d'activité"]]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Journal d'activité</h1>
          <p className="text-[15px] text-[#475569]">Tout ce que l'équipe FidClic a modifié, qui, quand, depuis où — y compris les tentatives refusées.</p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => downloadBlob(securityAPI.journalExport({ ...range, ...f }), 'journal-securite.csv').catch(() => say('Export impossible.'))} className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF]"><Download size={16} /> Exporter (CSV)</button>
          <RangePicker value={range} onChange={(v) => { setPage(1); setRange(v); }} />
        </div>
      </header>
      <Card className="p-0">
        <SecuTabs />
        <div className="p-4">
          <div className="mb-3 grid gap-2 md:grid-cols-[1.6fr_1fr_1fr_1fr]">
            <label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
              <input className={`${inputCls} pl-9`} placeholder="Rechercher une action, une cible, une IP…" value={f.q} onChange={(e) => setFilter('q')(e.target.value)} /></label>
            <Select value={f.user} onChange={setFilter('user')}><option value="">Tous les utilisateurs</option>{users.map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
            <Select value={f.category} onChange={setFilter('category')}><option value="">Toutes les actions</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</Select>
            <Select value={f.status} onChange={setFilter('status')}><option value="">Tous les statuts</option><option>Succès</option><option>Refusé</option><option>Bloqué</option></Select>
          </div>
          {!d ? <Loading /> : <><JournalTable rows={d.rows} /><Pager page={page} pages={d.pages} total={d.total} perPage={20} onPage={setPage} what="actions" /></>}
          <p className="mt-2 text-[11.5px] text-[#94A3B8]">Les consultations ne sont pas journalisées ; chaque modification l'est, avec son résultat.</p>
        </div>
      </Card>
      {toast}
    </div>
  );
}
