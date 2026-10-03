import React, { useEffect, useState } from 'react';
import { X, ClipboardList } from 'lucide-react';
import { grilleAPI } from '../lib/api';
import LiveText from './LiveText';

/**
 * GrilleModal — the "grille de répartition des tâches" of one dossier.
 *
 * WHY A LIVE GRID AND NOT AN ONBOARDING FORM
 *   French cabinets already write this matrix on paper at onboarding — and the
 *   documented failure is that it is never looked at again: tasks silently
 *   become "the other side's responsibility" and fall through. So this grid
 *   lives ON the dossier, editable any day, and assigning a task actually
 *   grants the person sight of the dossier — the paper never did that.
 */

const FREQ = { monthly: 'Mensuel', annual: 'Annuel', continuous: 'Continu' };
const DOMAIN_COLORS = {
  compta: { c: '#7C7CF8', bg: 'rgba(124,124,248,.10)', label: 'Compta' },
  social: { c: '#3DDC97', bg: 'rgba(61,220,151,.10)', label: 'Paie' },
  juridique: { c: '#C77DFF', bg: 'rgba(199,125,255,.10)', label: 'Juridique' },
};

export default function GrilleModal({ tenantId, clientName, members, onClose }) {
  const [rows, setRows] = useState(null);
  const [canEdit, setCanEdit] = useState(false);
  const [busy, setBusy] = useState(null);
  const [toast, setToast] = useState(null);

  const load = async () => {
    const r = await grilleAPI.get(tenantId).catch(() => null);
    setRows(r?.data?.tasks || []);
    setCanEdit(r?.data?.can_edit || false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [tenantId]);

  const flash = (ok, msg) => { setToast({ ok, msg }); setTimeout(() => setToast(null), 5000); };

  const setTask = async (taskType, value) => {
    setBusy(taskType);
    try {
      let body;
      if (value === '__client') body = { task_type: taskType, assignee_kind: 'client' };
      else if (value === '__tiers') {
        const label = window.prompt('Qui est ce tiers ? (ex. « Cabinet juridique Durand »)');
        if (!label) { setBusy(null); return; }
        body = { task_type: taskType, assignee_kind: 'tiers', label };
      } else if (value === '') body = { task_type: taskType, assignee_kind: 'none' };
      else body = { task_type: taskType, assignee_kind: 'member', membership_id: value };

      const r = await grilleAPI.set(tenantId, body);
      if (r?.data?.domain_warning) {
        flash(true, 'Attribué — attention : cette personne n’est pas du pôle habituel pour cette tâche.');
      }
      await load();
    } catch (e) {
      flash(false, e?.response?.data?.detail || 'Attribution impossible.');
    } finally { setBusy(null); }
  };

  const activeMembers = (members || []).filter((m) => m.status === 'active' && m.role !== 'agent');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
         style={{ background: 'rgba(4,6,15,.82)' }} onClick={onClose}>
      <div className="mc-surface rounded-3xl w-full max-w-2xl max-h-[88vh] overflow-auto p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-1">
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center"
                 style={{ background: 'linear-gradient(135deg,#C77DFF,#C77DFF)' }}>
              <ClipboardList size={16} color="#fff" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-[#F8FAFC] leading-tight">Répartition des tâches</h3>
              <div className="text-xs text-[#7C879F]">{clientName}</div>
            </div>
          </div>
          <button onClick={onClose} className="text-[#7C879F] hover:text-[#F8FAFC]"><X size={18} /></button>
        </div>
        <p className="text-xs text-[#7C879F] mb-4 mt-2">
          Qui fait quoi sur ce dossier — cabinet, client ou tiers. Attribuer une tâche à un
          membre lui donne accès au dossier. Sans choix explicite, la tâche revient au
          responsable du dossier (<em>défaut</em>).
        </p>

        {toast && (
          <div className="mb-3 rounded-xl px-3 py-2 text-xs border"
               style={toast.ok
                 ? { background: 'rgba(245,184,81,.08)', borderColor: 'rgba(245,184,81,.3)', color: '#F5B851' }
                 : { background: 'rgba(255,107,107,.08)', borderColor: 'rgba(255,107,107,.3)', color: '#FF6B6B' }}>
            <LiveText>{toast.msg}</LiveText>
          </div>
        )}

        {rows === null ? (
          <div key="loading" className="py-10 text-center text-sm text-[#7C879F]">Chargement…</div>
        ) : (
          <div className="divide-y" style={{ borderColor: 'rgba(255,255,255,.10)' }}>
            {rows.map((t) => {
              const dom = DOMAIN_COLORS[t.domain] || DOMAIN_COLORS.compta;
              return (
                <div key={t.task_type} className="py-2.5 flex items-center gap-3 flex-wrap">
                  <div className="flex-1 min-w-[200px]">
                    <div className="text-sm font-semibold text-[#F8FAFC] flex items-center gap-2">
                      <LiveText>{t.label_fr}</LiveText>
                      <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full"
                            style={{ color: dom.c, background: dom.bg }}>{dom.label}</span>
                    </div>
                    <div className="text-[10px] text-[#7C879F]">
                      {FREQ[t.frequency] || t.frequency}
                      {!t.explicit && t.assignee_name ? ' · défaut' : ''}
                    </div>
                  </div>
                  {canEdit ? (
                    <select className="fld-sm" disabled={busy === t.task_type}
                            value={t.explicit
                              ? (t.assignee_kind === 'member' ? (t.assignee_membership_id || '')
                                : t.assignee_kind === 'client' ? '__client' : '__tiers')
                              : ''}
                            onChange={(e) => setTask(t.task_type, e.target.value)}>
                      <option value="">{t.assignee_kind === 'client' && !t.explicit
                        ? 'Client (défaut)'
                        : `Défaut${t.assignee_name && !t.explicit ? ` — ${t.assignee_name}` : ''}`}</option>
                      {activeMembers.map((m) => (
                        <option key={m.id} value={m.id}>{m.full_name}</option>
                      ))}
                      <option value="__client">Client</option>
                      <option value="__tiers">Tiers…</option>
                    </select>
                  ) : (
                    <span className="text-xs font-semibold text-[#B9C2D6]">
                      {t.assignee_name || 'Non attribué'}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
        <style>{`.fld-sm{border:1px solid rgba(255,255,255,.10);border-radius:10px;padding:6px 10px;font-size:12px;color:#F8FAFC;background:rgba(255,255,255,.05);outline:none;max-width:220px}.fld-sm:focus{border-color:#C77DFF}`}</style>
      </div>
    </div>
  );
}
