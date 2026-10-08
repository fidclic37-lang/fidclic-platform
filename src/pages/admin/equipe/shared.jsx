import React, { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, User, X, UserPlus } from 'lucide-react';

/* Super admin › Suivi d'équipe — the pieces the board, the history and the
   task window share (features/team_tasks.py). Colours from the approved
   mockup: blue #2F6BFF, navy ink, soft grey-blue chips. */

export const INK = '#0B1C3F';
export const BLUE = '#2F6BFF';


export const STATUS = {
  a_faire: { label: 'À faire', dot: '#F5B70B', bg: '#FFF6DE', fg: '#B7791F' },
  en_retard: { label: 'En retard', dot: '#EF4444', bg: '#FEECEC', fg: '#DC2626' },
  terminee: { label: 'Terminée', dot: '#22C55E', bg: '#E8F8EE', fg: '#15803D' },
  terminee_retard: { label: 'Terminée en retard', dot: '#F97316', bg: '#FFF1E6', fg: '#C2410C' },
  supprimee: { label: 'Supprimée', dot: '#94A3B8', bg: '#F1F5F9', fg: '#64748B' },
};

export const DAYS_SHORT = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim'];

export const initials = (name) => (name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?';

export function frDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Paris' })} ${d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Paris' })}`;
}

export function lateText(min) {
  if (!min) return '';
  if (min < 60) return `${min} min`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h`;
  return `${Math.round(h / 24)} j`;
}

export const todayParis = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Europe/Paris' });
export const nowTimeParis = () => {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Paris' });
};

export function Avatar({ name, size = 36 }) {
  return (
    <span className="flex shrink-0 items-center justify-center rounded-full bg-[#EAF1FF] font-bold text-[#1E3A8A]"
          style={{ width: size, height: size, fontSize: size * 0.36 }}>{initials(name)}</span>
  );
}

export function TypeChip({ type }) {
  if (!type) return <span className="inline-flex rounded-md bg-[#F1F5F9] px-2 py-[2px] text-[11px] text-[#94A3B8]">Sans type</span>;
  return (
    <span className="inline-flex max-w-full items-center truncate rounded-md px-2 py-[2px] text-[11px] font-medium"
          style={{ background: `${type.color}17`, color: type.color }}>{type.name}</span>
  );
}

/* A priority is the team's own (name, colour): the pill tints itself from it. */
export function PriorityPill({ label, color }) {
  const c = color || '#94A3B8';
  return (
    <span className="inline-flex max-w-full items-center gap-1 truncate rounded-md px-1.5 py-[2px] text-[11px] font-medium" style={{ background: `${c}1F`, color: shade(c) }}>
      <span className="h-[7px] w-[7px] shrink-0 rounded-full" style={{ background: c }} />{label || '—'}
    </span>
  );
}

/* a darker tone of a colour, for text on its own light tint */
export function shade(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return '#475569';
  const v = parseInt(m[1], 16);
  const f = (x) => Math.round(x * 0.72).toString(16).padStart(2, '0');
  return `#${f((v >> 16) & 255)}${f((v >> 8) & 255)}${f(v & 255)}`;
}

export function StatusBadge({ s, late }) {
  const st = STATUS[s] || STATUS.a_faire;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-[3px] text-[11.5px] font-semibold" style={{ background: st.bg, color: st.fg }}>
      <span className="h-[7px] w-[7px] rounded-full" style={{ background: st.dot }} />{st.label}{late ? ` · ${lateText(late)}` : ''}
    </span>
  );
}

/* A small ring, as on the mockup's figure cards. */
export function Ring({ pct = 0, color, size = 46, stroke = 6 }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} className="shrink-0 -rotate-90" aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#EEF2F8" strokeWidth={stroke} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
              strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(100, Math.max(0, pct)) / 100)} />
    </svg>
  );
}

export const field = 'h-11 w-full rounded-xl border border-[#E3E9F3] bg-white px-3 text-[13.5px] text-[#0B1C3F] outline-none transition placeholder:text-[#94A3B8] focus:border-[#2F6BFF]';

/* « Assigner à »: one or more people of the team. */
export function PeoplePicker({ members, value, onChange, placeholder = 'Assigner à', className = '', onAddMember }) {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);
  const names = members.filter((m) => value.includes(m.email)).map((m) => m.name.split(' ')[0]);
  const toggle = (email) => onChange(value.includes(email) ? value.filter((e) => e !== email) : [...value, email]);
  return (
    <div ref={box} className={`relative ${className}`}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open}
              className={`${field} flex items-center justify-between gap-2 text-left`}>
        <span className={`truncate ${names.length ? 'text-[#0B1C3F]' : 'text-[#64748B]'}`}>{names.length ? names.join(', ') : placeholder}</span>
        <ChevronDown size={16} className="shrink-0 text-[#64748B]" />
      </button>
      {open && (
        <div role="listbox" aria-multiselectable="true"
             className="absolute left-0 top-full z-30 mt-1 max-h-72 w-full min-w-[220px] overflow-y-auto rounded-xl border border-[#E3E9F3] bg-white p-1 shadow-[0_18px_40px_-20px_rgba(11,28,63,.35)]">
          {!members.length && <p className="px-3 py-2 text-[12.5px] text-[#64748B]">Ajoutez d'abord des membres à l'équipe.</p>}
          {members.map((m) => {
            const on = value.includes(m.email);
            return (
              <button key={m.email} type="button" role="option" aria-selected={on} onClick={() => toggle(m.email)}
                      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-[#F4F7FC]">
                <span className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] border ${on ? 'border-[#2F6BFF] bg-[#2F6BFF] text-white' : 'border-[#CBD5E1]'}`}>
                  {on && <Check size={12} strokeWidth={3} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-[#0B1C3F]">{m.name}</span>
                  {m.fonction && <span className="block truncate text-[11px] text-[#64748B]">{m.fonction}</span>}
                </span>
                {!m.access && <span title="Sans accès à Suivi d'équipe" className="text-[#F59E0B]"><User size={13} /></span>}
              </button>
            );
          })}
          {onAddMember && (
            <button type="button" onClick={() => { setOpen(false); onAddMember(); }}
                    className="mt-1 flex w-full items-center gap-2 rounded-lg border-t border-[#EEF2F8] px-2.5 py-2 text-left text-[12.5px] font-semibold text-[#2F6BFF] hover:bg-[#F4F8FF]">
              <UserPlus size={14} /> Ajouter un membre à l'équipe
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* A window: centred, or a drawer on the right (side). */
export function Shell({ title, onClose, children, wide, side }) {
  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  return (
    <div className={`fixed inset-0 z-50 flex bg-[#0B1C3F]/30 ${side ? 'justify-end' : 'items-end justify-center sm:items-center sm:p-6'}`}
         onClick={onClose} role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : undefined}>
      <div onClick={(e) => e.stopPropagation()}
           className={side
             ? 'flex h-full w-full max-w-[560px] flex-col overflow-hidden bg-white shadow-2xl'
             : `max-h-[92vh] w-full ${wide ? 'max-w-3xl' : 'max-w-lg'} overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl sm:rounded-2xl`}>
        {!side && (
          <header className="mb-4 flex items-center justify-between gap-3">
            <h3 className="text-[16px] font-bold text-[#0B1C3F]">{title}</h3>
            <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#0B1C3F]"><X size={18} /></button>
          </header>
        )}
        {children}
      </div>
    </div>
  );
}

