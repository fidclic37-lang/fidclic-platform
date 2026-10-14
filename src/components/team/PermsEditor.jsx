import React, { useState } from 'react';
import { Copy, Lock } from 'lucide-react';

/**
 * « Voir » / « Modifier » for each sidebar page (user, 2026-10-13), for one
 * role template (value = {page: level}) or for an account, establishment by
 * establishment (value = {storeId: {page: level}}, `stores` given).
 * Levels: 'none' | 'view' | 'edit'. Modifier switches Voir on; Voir off
 * switches Modifier off. `max` (same shape as value) greys out what the
 * person filling the form may not hand out.
 */
const RANK = { none: 0, view: 1, edit: 2 };

function Switch({ on, onChange, label, disabled }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled}
            onClick={() => onChange(!on)}
            className="relative h-[22px] w-[38px] shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-40"
            style={{ background: on ? '#2F6BFF' : '#D5DCE6' }}>
      <span className="absolute top-[3px] h-[16px] w-[16px] rounded-full bg-white shadow transition-all" style={{ left: on ? 19 : 3 }} />
    </button>
  );
}

export function PageTable({ pages, levels, onChange, maxLevels, readOnly = false, idPrefix = '' }) {
  const set = (k, lv) => onChange({ ...levels, [k]: lv });
  return (
    <div className="overflow-hidden rounded-xl border border-[#EEF3FB]">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-[#EEF3FB] bg-[#F8FAFC] text-left text-[12px] font-semibold text-[#475569]">
            <th className="py-2 pl-3">Page</th><th className="w-[84px] text-center">Voir</th><th className="w-[84px] pr-3 text-center">Modifier</th>
          </tr>
        </thead>
        <tbody>
          {pages.map((p) => {
            const lv = levels?.[p.key] || 'none';
            const cap = maxLevels ? (maxLevels[p.key] || 'none') : 'edit';
            return (
              <tr key={p.key} className="border-b border-[#F1F5F9] last:border-0">
                <td className="py-2 pl-3 text-[#0B1C3F]">{p.label}</td>
                <td className="text-center">
                  {p.edit_only ? <span className="text-[11.5px] text-[#94A3B8]">—</span> : (
                    <span className="inline-flex justify-center">
                      <Switch on={RANK[lv] >= 1} label={`${idPrefix}Voir — ${p.label}`} disabled={readOnly || RANK[cap] < 1}
                              onChange={(v) => set(p.key, v ? 'view' : 'none')} />
                    </span>
                  )}
                </td>
                <td className="pr-3 text-center">
                  <span className="inline-flex justify-center">
                    <Switch on={lv === 'edit'} label={`${idPrefix}Modifier — ${p.label}`} disabled={readOnly || RANK[cap] < 2}
                            onChange={(v) => set(p.key, v ? 'edit' : (p.edit_only ? 'none' : 'view'))} />
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function PermsEditor({ pages, stores, value, onChange, max }) {
  const [sel, setSel] = useState(stores[0]?.id || '');
  const sid = stores.some((s) => s.id === sel) ? sel : stores[0]?.id;
  if (!sid) return <p className="text-[12.5px] text-[#64748B]">Choisissez d&apos;abord le ou les établissements.</p>;
  const levels = value?.[sid] || {};
  const copyAll = () => onChange(Object.fromEntries(stores.map((s) => [s.id, { ...levels }])));
  return (
    <div data-testid="perms-editor">
      {stores.length > 1 && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          {stores.map((s) => (
            <button key={s.id} type="button" onClick={() => setSel(s.id)} aria-pressed={s.id === sid}
                    className={`rounded-lg px-3 py-1.5 text-[12.5px] font-semibold ${s.id === sid ? 'bg-[#2F6BFF] text-white' : 'bg-[#F1F5F9] text-[#334155] hover:bg-[#E6EEFB]'}`}>
              {s.name}
            </button>
          ))}
          <button type="button" onClick={copyAll} className="ml-auto inline-flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF] hover:underline">
            <Copy size={13} /> Mêmes droits partout
          </button>
        </div>
      )}
      <PageTable pages={pages} levels={levels} maxLevels={max ? (max[sid] || {}) : null}
                 idPrefix={stores.length > 1 ? `${stores.find((s) => s.id === sid)?.name} · ` : ''}
                 onChange={(lv) => onChange({ ...(value || {}), [sid]: lv })} />
      {max && <p className="mt-1.5 flex items-center gap-1 text-[11.5px] text-[#94A3B8]"><Lock size={12} /> Les droits grisés dépassent les vôtres.</p>}
    </div>
  );
}

// the role's template, copied to each establishment
export function fromTemplate(tpl, storeIds) {
  return Object.fromEntries(storeIds.map((id) => [id, { ...(tpl?.perms || {}) }]));
}
