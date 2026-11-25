import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Users, Info, Plus, Pencil, Trash2, X,
  Clock, Moon, UserPlus, BarChart3, Star, Crown, Heart, Gift, Tag, Zap, Coffee,
  ShoppingBag, TrendingUp, Loader2, Check, RotateCcw,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import DecimalInput from '../components/DecimalInput';
import { rangeText, impactText, suggestStart, newStep } from '../lib/statusLadder';

/* Paramètres › Règles clients — how FidClic sorts the shop's clients.

   Every change is saved on its own (no Save button in the design): a figure or
   a description a moment after the owner stops typing, a switch at once. The
   server checks the whole list on each save, so a figure that would make two
   rules cross is refused with its reason and the row keeps what the owner
   typed until they fix it.

   Two ladders (user, 2026-11-25): a client's one Statut is read from the time
   line first, then from the owner's mixed rules, then from frequency. A step
   says only where it starts; the server sends where it ends (`range`) and
   how many clients it holds (`count`). The order IS the ladder — no drag. */

const ICONS = {
  users: Users, clock: Clock, moon: Moon, 'user-plus': UserPlus, 'bar-chart': BarChart3,
  star: Star, crown: Crown, heart: Heart, gift: Gift, tag: Tag, zap: Zap, coffee: Coffee,
  'shopping-bag': ShoppingBag, 'trending-up': TrendingUp,
};
const TONES = {
  green:  { bg: '#E7F7EE', fg: '#10B981' },
  orange: { bg: '#FFF3E8', fg: '#F97316' },
  rose:   { bg: '#FFF1F3', fg: '#F43F5E' },
  blue:   { bg: '#EAF1FF', fg: '#2F6BFF' },
  violet: { bg: '#F3EEFF', fg: '#7C3AED' },
  amber:  { bg: '#FFF7E6', fg: '#F59E0B' },
  slate:  { bg: '#F1F5F9', fg: '#64748B' },
};
const SAVE_DELAY = 700;

// The page in the order a client's Statut is read (customer_rules.primary).
const GROUPS = [
  { key: 'absence', title: "1 · D'abord : depuis quand n'est-il pas venu ?",
    note: 'Le temps depuis la dernière visite. Un client absent reçoit l’étape où il se trouve.',
    add: 'Ajouter une étape au temps' },
  { key: 'frequency', title: '2 · Puis : à quelle fréquence vient-il ?',
    note: 'Pour les clients qui ne sont pas absents, la plus haute étape atteinte.',
    add: 'Ajouter une étape à la fréquence' },
  { key: 'custom', title: 'Vos règles à plusieurs critères',
    note: 'Lues après le temps et avant la fréquence, dans cet ordre.' },
];

const unitFor = (criterion, value) => {
  if (!criterion) return '';
  const n = Number(value);
  if (criterion.unit === 'jours') return n === 1 ? 'jour' : 'jours';
  if (criterion.unit === 'visite' || criterion.unit === 'visites') return n <= 1 ? 'visite' : 'visites';
  return criterion.unit;
};

const toPayload = (rules) => rules.map((r) => ({
  id: r.id, key: r.key || null, name: r.name, icon: r.icon, tone: r.tone,
  description: r.description || '', enabled: !!r.enabled,
  conditions: r.conditions.map((c) => ({ type: c.type, value: Number(c.value) })),
}));

const valid = (rules) => rules.every((r) => r.conditions.every(
  (c) => c.value !== '' && c.value !== null && !Number.isNaN(Number(c.value))));

function Toggle({ on, onChange, label }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label}
      onClick={() => onChange(!on)}
      className="relative h-[26px] w-[46px] shrink-0 rounded-full transition-colors"
      style={{ background: on ? '#2F6BFF' : '#CBD5E1' }}>
      <span className="absolute top-[3px] h-5 w-5 rounded-full bg-white shadow transition-all"
        style={{ left: on ? 23 : 3 }} />
    </button>
  );
}

function NumberField({ value, unit, onChange, invalid, label }) {
  return (
    <div className="flex h-11 w-full max-w-[190px] overflow-hidden rounded-lg border bg-white"
      style={{ borderColor: invalid ? '#F87171' : '#E2E8F0' }}>
      <DecimalInput aria-label={label} value={value}
        onChange={onChange}
        className="min-w-0 flex-1 border-0 bg-transparent px-3 text-[14.5px] text-[#0B1C3F] outline-none" />
      <span className="flex min-w-[70px] items-center justify-center bg-[#F1F5F9] px-2.5 text-[13.5px] text-[#64748B]">
        {unit}
      </span>
    </div>
  );
}

function RuleIcon({ rule, size = 48 }) {
  const Icon = ICONS[rule.icon] || Users;
  const t = TONES[rule.tone] || TONES.blue;
  return (
    <span className="flex shrink-0 items-center justify-center rounded-xl"
      style={{ width: size, height: size, background: t.bg, color: t.fg }}>
      <Icon size={Math.round(size * 0.5)} strokeWidth={2} />
    </span>
  );
}

/* ---------------------------------------------------------------- modal -- */
function RuleModal({ initial, criteria, limits, onClose, onSave }) {
  const builtin = !!initial?.key;
  const [draft, setDraft] = useState(() => initial ? JSON.parse(JSON.stringify(initial)) : {
    name: '', icon: 'star', tone: 'blue', description: '', enabled: true,
    conditions: [{ type: 'visits_min', value: 5 }],
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const offered = criteria.filter((c) => !c.builtin_only);
  const byType = Object.fromEntries(criteria.map((c) => [c.type, c]));
  const set = (patch) => setDraft((d) => ({ ...d, ...patch }));
  const setCond = (i, patch) => set({
    conditions: draft.conditions.map((c, j) => (j === i ? { ...c, ...patch } : c)),
  });

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const submit = async (e) => {
    e.preventDefault();
    if (!draft.name.trim()) { setError('Donnez un nom à la règle.'); return; }
    if (!valid([draft])) { setError('Chaque critère a besoin d’une valeur.'); return; }
    setSaving(true); setError('');
    const problem = await onSave(draft);
    setSaving(false);
    if (problem) setError(problem);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/40 p-4" role="dialog"
      aria-modal="true" aria-label={builtin || initial ? 'Modifier la règle' : 'Ajouter une règle'}>
      <form onSubmit={submit}
        className="max-h-[92vh] w-full max-w-[560px] overflow-y-auto rounded-2xl bg-white p-6 shadow-[0_40px_90px_-40px_rgba(11,28,63,.6)]">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <RuleIcon rule={draft} size={44} />
            <div>
              <h2 className="text-[19px] font-bold text-[#0B1C3F]">
                {initial ? 'Modifier la règle' : 'Ajouter une règle'}
              </h2>
              <p className="text-[13px] text-[#64748B]">
                {builtin ? 'Règle de base : ses critères restent les mêmes, leurs valeurs se règlent.'
                  : 'Un client entre dans la règle quand tous ses critères sont remplis.'}
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer"
            className="flex h-9 w-9 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F4F7FC]">
            <X size={18} />
          </button>
        </div>

        <label className="mb-1.5 flex justify-between text-[13px] font-semibold text-[#334155]">
          Nom de la règle <span className="font-normal text-[#94A3B8]">{draft.name.length}/{limits.name}</span>
        </label>
        <input value={draft.name} maxLength={limits.name} onChange={(e) => set({ name: e.target.value })}
          placeholder="Ex. Gros dépensiers"
          className="mb-4 h-11 w-full rounded-lg border border-[#E2E8F0] px-3 text-[14.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />

        <div className="mb-4 grid gap-4 sm:grid-cols-2">
          <div>
            <p className="mb-1.5 text-[13px] font-semibold text-[#334155]">Icône</p>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(ICONS).map(([key, Icon]) => (
                <button key={key} type="button" onClick={() => set({ icon: key })} aria-label={key}
                  className="flex h-9 w-9 items-center justify-center rounded-lg border"
                  style={{ borderColor: draft.icon === key ? '#2F6BFF' : '#E2E8F0',
                           background: draft.icon === key ? '#EAF1FF' : '#fff',
                           color: draft.icon === key ? '#2F6BFF' : '#64748B' }}>
                  <Icon size={16} />
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1.5 text-[13px] font-semibold text-[#334155]">Couleur</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(TONES).map(([key, t]) => (
                <button key={key} type="button" onClick={() => set({ tone: key })} aria-label={key}
                  className="flex h-9 w-9 items-center justify-center rounded-full border-2"
                  style={{ background: t.bg, borderColor: draft.tone === key ? t.fg : 'transparent' }}>
                  <span className="h-4 w-4 rounded-full" style={{ background: t.fg }} />
                </button>
              ))}
            </div>
          </div>
        </div>

        <p className="mb-1.5 text-[13px] font-semibold text-[#334155]">Critères de classification</p>
        <div className="mb-2 space-y-2">
          {draft.conditions.map((c, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 rounded-xl border border-[#EEF3FB] bg-[#F6F9FF] p-2.5">
              {i > 0 && <span className="text-[12px] font-bold uppercase text-[#2F6BFF]">et</span>}
              <select value={c.type} disabled={builtin}
                onChange={(e) => setCond(i, { type: e.target.value })}
                className="h-11 min-w-0 flex-1 rounded-lg border border-[#E2E8F0] bg-white px-2.5 text-[13.5px] text-[#0B1C3F] disabled:bg-[#F8FAFC]">
                {(builtin ? criteria : offered).map((o) => <option key={o.type} value={o.type}>{o.label}</option>)}
              </select>
              <NumberField value={c.value} unit={unitFor(byType[c.type], c.value)} label="Valeur"
                onChange={(v) => setCond(i, { value: v })} />
              {!builtin && draft.conditions.length > 1 && (
                <button type="button" aria-label="Retirer ce critère"
                  onClick={() => set({ conditions: draft.conditions.filter((_, j) => j !== i) })}
                  className="flex h-9 w-9 items-center justify-center rounded-lg text-[#94A3B8] hover:bg-white hover:text-[#EF4444]">
                  <X size={16} />
                </button>
              )}
            </div>
          ))}
        </div>
        {!builtin && draft.conditions.length < limits.conditions && (
          <button type="button"
            onClick={() => set({ conditions: [...draft.conditions, { type: 'visited_within', value: 30 }] })}
            className="mb-4 inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#2F6BFF]">
            <Plus size={15} /> Ajouter un critère
          </button>
        )}

        <label className="mb-1.5 mt-2 flex justify-between text-[13px] font-semibold text-[#334155]">
          Description <span className="font-normal text-[#94A3B8]">{(draft.description || '').length}/{limits.description}</span>
        </label>
        <textarea value={draft.description} maxLength={limits.description} rows={2}
          onChange={(e) => set({ description: e.target.value })}
          className="mb-4 w-full resize-y rounded-lg border border-[#E2E8F0] px-3 py-2.5 text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />

        <div className="mb-5 flex items-center justify-between rounded-xl border border-[#EEF3FB] px-4 py-3">
          <div>
            <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Règle active</p>
            <p className="text-[12px] text-[#64748B]">Désactivée, elle ne classe plus personne.</p>
          </div>
          <Toggle on={draft.enabled} onChange={(v) => set({ enabled: v })} label="Règle active" />
        </div>

        {error && <p className="mb-4 rounded-lg bg-[#FEF2F2] px-3 py-2.5 text-[13px] text-[#B91C1C]">{error}</p>}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose}
            className="h-11 rounded-xl border border-[#E2E8F0] px-5 text-[14px] font-semibold text-[#334155]">Annuler</button>
          <button type="submit" disabled={saving}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[14px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-60">
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
            {initial ? 'Enregistrer' : 'Ajouter la règle'}
          </button>
        </div>
      </form>
    </div>
  );
}

/* ------------------------------------------------------------ step modal -- */
const STEP_COPY = {
  absence: { title: 'Nouvelle étape', unit: 'jours', hint: "N'a pas visité depuis au moins", placeholder: 'Ex. À relancer' },
  frequency: { title: 'Nouvelle étape', unit: 'visites / mois', hint: 'Vient au moins', placeholder: 'Ex. Habitué' },
};

/** Where a new absence step would end, from the steps already on (the page's own reading). */
function stepSentence(group, value, rules) {
  const v = Number(value);
  if (value === '' || Number.isNaN(v)) return '';
  if (group === 'frequency') return `Cette étape commencera à ${String(v).replace('.', ',')} visites par mois.`;
  const next = rules
    .filter((r) => r.group === 'absence' && r.enabled !== false && r.key !== 'actif' && r.range && r.range.from > v)
    .map((r) => r.range.from).sort((a, b) => a - b)[0];
  return next === undefined ? `Cette étape commencera à ${v} jours, sans limite.` : `Cette étape ira de ${v} à ${next - 1} jours.`;
}

function StepModal({ group, rules, limits, onClose, onSave }) {
  const copy = STEP_COPY[group];
  const [draft, setDraft] = useState(() => newStep(group, suggestStart(rules, group)));
  const [impact, setImpact] = useState({ state: 'idle', text: '' });
  const [saving, setSaving] = useState(false);
  const value = draft.conditions[0].value;
  const setValue = (v) => setDraft((d) => ({ ...d, conditions: [{ ...d.conditions[0], value: v }] }));

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Who would move, said before saving — and why it cannot be saved, if so.
  useEffect(() => {
    if (value === '' || Number.isNaN(Number(value))) { setImpact({ state: 'error', text: 'Indiquez un chiffre.' }); return undefined; }
    let live = true;
    setImpact((i) => ({ ...i, state: 'loading' }));
    const t = setTimeout(() => {
      const named = { ...draft, name: draft.name.trim() || copy.placeholder.replace('Ex. ', '') };
      ownerAPI.previewCustomerRules({ rules: toPayload([...rules, named]) })
        .then(({ data }) => { if (live) setImpact({ state: 'ok', text: impactText(data) }); })
        .catch((e) => {
          const detail = e?.response?.data?.detail;
          if (live) setImpact({ state: 'error', text: typeof detail === 'string' ? detail : 'Ce chiffre ne convient pas.' });
        });
    }, 350);
    return () => { live = false; clearTimeout(t); };
  }, [value, draft.name]); // eslint-disable-line react-hooks/exhaustive-deps

  const ready = draft.name.trim() && impact.state === 'ok' && !saving;
  const submit = async (e) => {
    e.preventDefault();
    if (!ready) return;
    setSaving(true);
    const problem = await onSave({ ...draft, name: draft.name.trim(), conditions: [{ ...draft.conditions[0], value: Number(value) }] });
    setSaving(false);
    if (problem) setImpact({ state: 'error', text: problem });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/40 p-4" role="dialog"
      aria-modal="true" aria-label={copy.title}>
      <form onSubmit={submit}
        className="max-h-[92vh] w-full max-w-[480px] overflow-y-auto rounded-2xl bg-white p-6 shadow-[0_40px_90px_-40px_rgba(11,28,63,.6)]">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <RuleIcon rule={draft} size={44} />
            <div>
              <h2 className="text-[19px] font-bold text-[#0B1C3F]">{copy.title}</h2>
              <p className="text-[13px] text-[#64748B]">
                {group === 'absence' ? 'Sur le temps depuis la dernière visite.' : 'Sur le nombre de visites par mois.'}
                {' '}Elle s’arrête où commence la suivante.
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer"
            className="flex h-9 w-9 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F4F7FC]">
            <X size={18} />
          </button>
        </div>

        <label htmlFor="step-name" className="mb-1.5 flex justify-between text-[13px] font-semibold text-[#334155]">
          Nom de l'étape <span className="font-normal text-[#94A3B8]">{draft.name.length}/{limits.name}</span>
        </label>
        <input id="step-name" value={draft.name} maxLength={limits.name} placeholder={copy.placeholder}
          onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          className="mb-4 h-11 w-full rounded-lg border border-[#E2E8F0] px-3 text-[14.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />

        <p className="mb-1.5 text-[13px] font-semibold text-[#334155]">{copy.hint}</p>
        <NumberField value={value} unit={copy.unit} label="À partir de" onChange={setValue}
          invalid={impact.state === 'error'} />
        <p data-testid="step-range" className="mt-2 text-[13px] text-[#334155]">{stepSentence(group, value, rules)}</p>

        <div className="mt-4 rounded-xl px-4 py-3 text-[13px]"
          style={{ background: impact.state === 'error' ? '#FEF2F2' : '#F6F9FF', color: impact.state === 'error' ? '#B91C1C' : '#1E3A8A' }}>
          <p className="mb-0.5 font-semibold">{impact.state === 'error' ? 'Impossible' : 'Si vous ajoutez cette étape'}</p>
          <p data-testid="step-impact" aria-live="polite">
            {impact.state === 'loading' && !impact.text ? 'Calcul…' : impact.text}
          </p>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose}
            className="h-11 rounded-xl border border-[#E2E8F0] px-5 text-[14px] font-semibold text-[#334155]">Annuler</button>
          <button type="submit" disabled={!ready}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[14px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-50">
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
            Ajouter l'étape
          </button>
        </div>
      </form>
    </div>
  );
}

function ConfirmDelete({ rule, onCancel, onConfirm }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/40 p-4" role="alertdialog"
      aria-modal="true" aria-label="Supprimer la règle">
      <div className="w-full max-w-[420px] rounded-2xl bg-white p-6 shadow-[0_40px_90px_-40px_rgba(11,28,63,.6)]">
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-[#FEF2F2] text-[#EF4444]">
          <Trash2 size={20} />
        </div>
        <h2 className="text-[18px] font-bold text-[#0B1C3F]">Supprimer « {rule.name} » ?</h2>
        <p className="mt-1.5 text-[13.5px] leading-relaxed text-[#475569]">
          {rule.key
            ? 'Ses clients ne seront plus classés ainsi. C’est une règle de base : vous pourrez la rétablir à tout moment.'
            : 'Ses clients ne seront plus classés ainsi. Cette règle personnalisée sera définitivement supprimée.'}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel}
            className="h-11 rounded-xl border border-[#E2E8F0] px-5 text-[14px] font-semibold text-[#334155]">Annuler</button>
          <button type="button" onClick={onConfirm}
            className="h-11 rounded-xl bg-[#EF4444] px-5 text-[14px] font-semibold text-white hover:bg-[#DC2626]">Supprimer</button>
        </div>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- page -- */
export default function ReglesClientsPage() {
  const [d, setD] = useState(null);
  const [rules, setRules] = useState([]);
  const [loadError, setLoadError] = useState('');
  const [save, setSave] = useState({ state: 'idle', message: '' });
  const [modal, setModal] = useState(null);      // null | { rule } | { rule: null } for a new one
  const [deleting, setDeleting] = useState(null);
  const [stepFor, setStepFor] = useState(null);   // 'absence' | 'frequency' while adding a step
  const timer = useRef(null);
  const latest = useRef([]);

  const load = useCallback(() => {
    ownerAPI.customerRules()
      .then(({ data }) => { setD(data); setRules(data.rules); latest.current = data.rules; setLoadError(''); })
      .catch((e) => setLoadError(e?.response?.data?.detail || 'Impossible de charger les règles.'));
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const criteria = useMemo(() => Object.fromEntries((d?.criteria || []).map((c) => [c.type, c])), [d]);

  const persist = useCallback(async (next) => {
    clearTimeout(timer.current);
    if (!valid(next)) return 'Chaque critère a besoin d’une valeur.';
    setSave({ state: 'saving', message: '' });
    try {
      const { data } = await ownerAPI.saveCustomerRules({ rules: toPayload(next) });
      setD(data);
      // Keep what is on screen if the owner typed again while this was in flight.
      if (latest.current === next) { setRules(data.rules); latest.current = data.rules; }
      // what the save did to the clients (« 3 clients ont changé de statut »)
      const n = data.changed || 0;
      setSave({ state: 'saved', message: n ? `${n} client${n > 1 ? 's ont' : ' a'} changé de statut` : '' });
      return null;
    } catch (e) {
      const message = e?.response?.data?.detail || 'Enregistrement impossible.';
      setSave({ state: 'error', message: typeof message === 'string' ? message : 'Valeur invalide.' });
      return typeof message === 'string' ? message : 'Valeur invalide.';
    }
  }, []);

  const change = (next, { now = false } = {}) => {
    setRules(next); latest.current = next;
    clearTimeout(timer.current);
    if (now) persist(next);
    else timer.current = setTimeout(() => persist(next), SAVE_DELAY);
  };

  const patchRule = (id, patch, opts) => change(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)), opts);
  const patchCond = (id, i, value) => {
    const r = rules.find((x) => x.id === id);
    patchRule(id, { conditions: r.conditions.map((c, j) => (j === i ? { ...c, value } : c)) });
  };

  const saveFromModal = async (draft) => {
    const exists = rules.some((r) => r.id && r.id === draft.id);
    const next = exists ? rules.map((r) => (r.id === draft.id ? draft : r)) : [...rules, { ...draft, key: null }];
    setRules(next); latest.current = next;
    const problem = await persist(next);
    if (problem) { load(); return problem; }
    setModal(null);
    setStepFor(null);
    return null;
  };

  const confirmDelete = async () => {
    const next = rules.filter((r) => r.id !== deleting.id);
    setDeleting(null);
    change(next, { now: true });
  };

  const restore = async () => {
    setSave({ state: 'saving', message: '' });
    try {
      const { data } = await ownerAPI.restoreCustomerRules();
      setD(data); setRules(data.rules); latest.current = data.rules;
      setSave({ state: 'saved', message: '' });
    } catch (e) {
      setSave({ state: 'error', message: e?.response?.data?.detail || 'Rétablissement impossible.' });
    }
  };

  const renderRow = (r) => {
    const first = criteria[r.conditions[0]?.type];
    return (
                    <tr key={r.id}
                      className="border-b border-[#EEF3FB] align-middle transition-colors"
                      style={{ opacity: r.enabled ? 1 : 0.6 }}>
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-4">
                          <RuleIcon rule={r} />
                          <div className="min-w-0">
                            <span data-testid="rule-name" className="text-[15.5px] font-bold text-[#0B1C3F]">{r.name}</span>
                            <p className="mt-0.5 text-[12.5px] text-[#64748B]">
                              {[rangeText(r), r.enabled ? `${r.count || 0} client${(r.count || 0) > 1 ? 's' : ''}` : '']
                                .filter(Boolean).join(' · ')}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="border-l border-[#EEF3FB] px-4 py-3 text-[14.5px] leading-snug text-[#334155]">
                        {first?.label}
                      </td>
                      <td className="border-l border-[#EEF3FB] px-4 py-3">
                        <div className="space-y-1.5">
                          {r.conditions.map((c, i) => {
                            const crit = criteria[c.type];
                            return (
                              <div key={i}>
                                {i > 0 && <p className="mb-1.5 text-[13.5px] text-[#475569]">{crit?.label}</p>}
                                <NumberField value={c.value} unit={unitFor(crit, c.value)} label={`${r.name} — ${crit?.label}`}
                                  invalid={c.value === '' || Number.isNaN(Number(c.value))}
                                  onChange={(v) => patchCond(r.id, i, v)} />
                              </div>
                            );
                          })}
                        </div>
                      </td>
                      <td className="border-l border-[#EEF3FB] px-4 py-3">
                        <textarea value={r.description || ''} maxLength={d.limits.description}
                          rows={Math.max(2, Math.ceil((r.description || '').length / 36))}
                          aria-label={`Description — ${r.name}`}
                          onChange={(e) => patchRule(r.id, { description: e.target.value })}
                          className="block w-full resize-y rounded-lg border border-[#E2E8F0] px-3 py-2.5 text-[14px] leading-snug text-[#334155] outline-none focus:border-[#2F6BFF]" />
                        <p className="mt-1 text-right text-[12.5px] text-[#64748B]">
                          {(r.description || '').length}/{d.limits.description}
                        </p>
                      </td>
                      <td className="border-l border-[#EEF3FB] px-4 py-3">
                        <Toggle on={!!r.enabled} label={`Activer ${r.name}`}
                          onChange={(v) => patchRule(r.id, { enabled: v }, { now: true })} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-center gap-3">
                          <button type="button" onClick={() => setModal({ rule: r })} aria-label={`Modifier ${r.name}`}
                            className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#E2E8F0] bg-white text-[#0B1C3F] hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                            <Pencil size={17} />
                          </button>
                          <button type="button" onClick={() => setDeleting(r)} aria-label={`Supprimer ${r.name}`}
                            className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#FECACA] bg-[#FEF2F2] text-[#EF4444] hover:bg-[#FEE2E2]">
                            <Trash2 size={17} />
                          </button>
                        </div>
                      </td>
                    </tr>
    );
  };

  if (!d && !loadError) {
    return (
      <div key="loading" className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]">
        <Loader2 size={16} className="animate-spin" /> Chargement…
      </div>
    );
  }

  return (
    <div>
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3.5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#E6EEFB] text-[#2F6BFF]">
            <Users size={22} />
          </span>
          <div>
            <h2 className="text-[21px] font-bold leading-tight text-[#0B1C3F]">Règles clients</h2>
            <p className="mt-0.5 text-[14px] text-[#475569]">Définissez comment FidClic classe automatiquement vos clients.</p>
          </div>
        </div>
        <button type="button" onClick={() => setModal({ rule: null })}
          className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[14.5px] font-medium text-white shadow-[0_10px_24px_-14px_rgba(47,107,255,.9)] hover:bg-[#2559DB]">
          <Plus size={18} /> Ajouter une règle
        </button>
      </header>

      <div className="mb-5 flex items-center gap-4 rounded-xl border border-[#C9DBFB] bg-[#EFF5FF] px-5 py-4">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#2F6BFF] text-white">
          <Info size={17} strokeWidth={2.5} />
        </span>
        <p className="text-[14.5px] leading-snug text-[#1E4FD8]">
          Chaque client reçoit <b>un seul statut</b>. FidClic regarde d'abord depuis quand il n'est pas venu (1),
          puis vos règles à plusieurs critères, puis à quelle fréquence il vient (2). Chaque étape commence à
          son chiffre et s'arrête où commence la suivante : deux étapes ne se cachent jamais.{' '}
          La segmentation détaillée (filtres,
          critères avancés, listes) se fait dans la section{' '}
          <Link to="/dashboard/segmentation" className="font-bold hover:underline">Segmentation</Link>.
          {' '}Les paliers de la carte (Bronze, Argent, Or, VIP) sont autre chose : ils se règlent dans{' '}
          <Link to="/dashboard/parametres/objectifs" className="font-bold hover:underline">Objectifs et récompenses</Link>.
        </p>
      </div>

      {loadError && (
        <p className="mb-4 rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{loadError}</p>
      )}
      {save.state === 'error' && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">
          <span><b>Non enregistré :</b> {save.message}</span>
          <button type="button" onClick={() => { setSave({ state: 'idle', message: '' }); load(); }}
            className="inline-flex items-center gap-1.5 font-semibold hover:underline">
            <RotateCcw size={14} /> Revenir aux valeurs enregistrées
          </button>
        </div>
      )}

      {d && (
        <div className="overflow-hidden rounded-2xl border border-[#E6EEFB] bg-white">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] border-collapse">
              <thead>
                <tr className="border-b border-[#EEF3FB] text-left text-[14.5px] font-semibold text-[#0B1C3F]">
                  <th className="w-[20%] px-5 py-4 font-semibold">Type de client</th>
                  <th className="w-[18%] border-l border-[#EEF3FB] px-4 py-4 font-semibold">Critères de classification</th>
                  <th className="w-[18%] border-l border-[#EEF3FB] px-4 py-4 font-semibold">Paramètres</th>
                  <th className="w-[24%] border-l border-[#EEF3FB] px-4 py-4 font-semibold">Description</th>
                  <th className="w-[7%] border-l border-[#EEF3FB] px-4 py-4 font-semibold">Statut</th>
                  <th className="w-[13%] px-4 py-4 text-center font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {GROUPS.map((g) => {
                  const mine = rules.filter((r) => (r.group || 'custom') === g.key);
                  if (g.key === 'custom' && !mine.length) return null;
                  return (
                    <React.Fragment key={g.key}>
                      <tr className="border-b border-[#EEF3FB] bg-[#F6F9FF]">
                        <td colSpan={6} className="px-5 py-2.5">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div>
                              <p className="text-[14px] font-bold text-[#0B1C3F]">{g.title}</p>
                              <p className="text-[12.5px] text-[#64748B]">{g.note}</p>
                            </div>
                            {g.add && (
                              <button type="button" onClick={() => setStepFor(g.key)} aria-label={g.add}
                                className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#C9DBFB] bg-white px-3 text-[13px] font-semibold text-[#2F6BFF] hover:bg-[#EFF5FF]">
                                <Plus size={15} /> Ajouter une étape
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {mine.map(renderRow)}
                    </React.Fragment>
                  );
                })}
                {!rules.length && (
                  <tr><td colSpan={6} className="px-5 py-10 text-center text-[14px] text-[#64748B]">
                    Aucune règle. Ajoutez-en une, ou rétablissez les règles de base.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="m-3 rounded-xl border border-dashed border-[#C9DBFB] px-4 py-3 text-center">
            <button type="button" onClick={() => setModal({ rule: null })}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-[#2F6BFF] px-3.5 text-[13.5px] font-medium text-white hover:bg-[#2559DB]">
              <Plus size={15} /> Ajouter une règle
            </button>
            <p className="mt-2 text-[12.5px] text-[#64748B]">
              Vous pouvez créer vos propres règles de classification selon vos besoins.
            </p>
            {d.deleted_builtins?.length > 0 && (
              <p className="mt-1.5 text-[12.5px] text-[#64748B]">
                Règles de base supprimées : {d.deleted_builtins.map((x) => x.name).join(', ')} —{' '}
                <button type="button" onClick={restore} className="font-semibold text-[#2F6BFF] hover:underline">
                  Rétablir
                </button>
              </p>
            )}
          </div>
        </div>
      )}

      {/* quiet save indicator */}
      <div aria-live="polite"
        className="pointer-events-none fixed bottom-5 left-1/2 z-40 -translate-x-1/2 transition-opacity"
        style={{ opacity: save.state === 'saving' || save.state === 'saved' ? 1 : 0 }}>
        <span className="inline-flex items-center gap-2 rounded-full bg-[#0B1C3F] px-4 py-2 text-[13px] font-medium text-white shadow-lg">
          {save.state === 'saving' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
          {save.state === 'saving' ? 'Enregistrement…' : `Enregistré${save.message ? ` · ${save.message}` : ''}`}
        </span>
      </div>

      {modal && d && (
        <RuleModal initial={modal.rule} criteria={d.criteria} limits={d.limits}
          onClose={() => setModal(null)} onSave={saveFromModal} />
      )}
      {stepFor && d && (
        <StepModal group={stepFor} rules={rules} limits={d.limits}
          onClose={() => setStepFor(null)} onSave={saveFromModal} />
      )}
      {deleting && (
        <ConfirmDelete rule={deleting} onCancel={() => setDeleting(null)} onConfirm={confirmDelete} />
      )}
    </div>
  );
}
