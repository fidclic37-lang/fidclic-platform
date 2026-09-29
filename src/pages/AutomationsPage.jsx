import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Settings2, Wallet, Send, Users, Eye, BarChart3, List, Play, FileText,
  Plus, Search, ChevronDown, ChevronRight, MoreHorizontal, Loader2, X, Check,
  Cake, Star, Tag, ShoppingCart, Clock, Sparkles, Heart, CalendarDays, Bell,
  Trash2, Zap, Info,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * Automatisations · Push Wallet — built to the approved mockup.
 *
 * Eight scenarios that fire on their own and land on the card the customer
 * keeps in Apple or Google Wallet. Everything here is wired to
 * /api/owner/push-wallet/*: switching a row on arms it for tonight's run, and
 * the four figures are counted from sends that actually happened.
 *
 * One figure is worth reading carefully and the page says so under it: a
 * wallet push has no read receipt, so "Taux d'ouverture" measures cards opened
 * within 72 h of a push, not notifications seen.
 */
const SCENARIO_ICONS = {
  cake: Cake, star: Star, tag: Tag, cart: ShoppingCart, clock: Clock,
  new: Sparkles, heart: Heart, calendar: CalendarDays, bell: Bell,
};
const ICON_TONES = {
  cake: '#F43F5E', star: '#F59E0B', tag: '#F97316', cart: '#8B5CF6',
  clock: '#6366F1', new: '#2F6BFF', heart: '#EC4899', calendar: '#0EA5E9', bell: '#64748B',
};
const KPI_ICONS = { send: Send, users: Users, eye: Eye, chart: BarChart3 };
const KPI_TONES = [
  { bg: '#EAF1FF', fg: '#2F6BFF' },
  { bg: '#F3EEFF', fg: '#7C3AED' },
  { bg: '#E7F7EE', fg: '#0F8B58' },
  { bg: '#EAF1FF', fg: '#2F6BFF' },
];

const TABS = [
  { key: 'all', label: 'Tous les scénarios', icon: List },
  { key: 'active', label: 'Scénarios actifs', icon: Play },
  { key: 'draft', label: 'Brouillons', icon: FileText },
  { key: 'stats', label: 'Statistiques', icon: BarChart3 },
];

const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
const stamp = (iso) => {
  if (!iso) return '-';
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}. ${d.getFullYear()}\n${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

/* ── pieces ───────────────────────────────────────────────────────────── */
const KpiCard = ({ card, tone }) => {
  const Icon = KPI_ICONS[card.icon] || Send;
  const up = (card.delta_pct ?? 0) >= 0;
  return (
    <div className="flex items-start gap-3.5 rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl"
            style={{ background: tone.bg, color: tone.fg }}>
        <Icon size={22} />
      </span>
      <div className="min-w-0">
        <p className="text-[25px] font-bold leading-none tracking-tight text-[#0B1C3F] tabular-nums">
          {card.unit === '%' ? `${String(card.value).replace('.', ',')}%` : nf(card.value)}
        </p>
        <p className="mt-1 text-[12.5px] leading-tight text-[#64748B]">{card.label}</p>
        {card.delta_pct === null || card.delta_pct === undefined ? (
          <p className="mt-2 text-[11px] leading-tight text-[#94A3B8]">
            {card.note || 'pas encore de période précédente'}
          </p>
        ) : (
          <div className="mt-2">
            <span className="inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11.5px] font-semibold"
                  style={up ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#FEECEC', color: '#C0392B' }}>
              {up ? '↑' : '↓'} {up ? '+' : ''}{card.delta_pct}%
            </span>
            <span className="mt-1 block text-[11px] leading-tight text-[#94A3B8]">
              {card.note || 'vs période précédente'}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

const Switch = ({ on, onChange, busy }) => (
  <button
    type="button" role="switch" aria-checked={on} disabled={busy}
    onClick={() => onChange(!on)}
    className={`relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-50 ${on ? 'bg-[#2F6BFF]' : 'bg-[#DFE6F1]'}`}
  >
    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? 'left-[22px]' : 'left-0.5'}`} />
  </button>
);

const Field = ({ label, hint, children }) => (
  <label className="block">
    <span className="mb-1.5 block text-[12.5px] font-semibold text-[#334155]">{label}</span>
    {children}
    {hint && <span className="mt-1 block text-[11.5px] leading-snug text-[#94A3B8]">{hint}</span>}
  </label>
);

const inputCls = 'w-full rounded-xl border border-[#E6EEFB] bg-white px-3 py-2.5 text-[13px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';

/* What each trigger needs to be able to fire at all. Switching trigger used to
   clear the config to {}, so the form showed "14 h" as a placeholder value while
   saving nothing — and a plage horaire of 0h–0h never fires. These are the
   values actually written, so what is on screen is what is stored. */
const TRIGGER_DEFAULTS = {
  inactivity:    { days: 30 },
  date_event:    { day_of_month: 1 },
  specific_date: { date: '' },
  time_slot:     { weekdays: [1, 2, 3], from_hour: 14, to_hour: 17 },
  birthday:      {},
  tier_up:       {},
  new_product:   {},
};

/* ── the editor ───────────────────────────────────────────────────────── */
const WEEKDAYS = [['L', 0], ['M', 1], ['M', 2], ['J', 3], ['V', 4], ['S', 5], ['D', 6]];

const ScenarioModal = ({ scenario, triggers, examples, onClose, onSaved, messageOnly = false, scopeLabel = '' }) => {
  const creating = !scenario?.id;
  const [form, setForm] = useState(() => ({
    name: scenario?.name || '', subtitle: scenario?.subtitle || '',
    trigger: scenario?.trigger || 'inactivity', config: { ...(scenario?.config || {}) },
    title: scenario?.title || '', body: scenario?.body || '',
    enabled: scenario?.enabled ?? true,
    cooldown_days: scenario?.cooldown_days ?? 30,
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [reach, setReach] = useState(null);

  useEffect(() => {
    if (creating || !scenario?.id) return;
    ownerAPI.pushWalletPreview(scenario.id).then(({ data }) => setReach(data.count)).catch(() => {});
  }, [creating, scenario?.id]);

  const needs = triggers.find((t) => t.key === form.trigger)?.config || [];
  const setCfg = (k, v) => setForm((f) => ({ ...f, config: { ...f.config, [k]: v } }));

  const save = async () => {
    setSaving(true); setError('');
    try {
      if (creating) await ownerAPI.createPushWalletScenario(form);
      // An administrateur words the message for its establishments only.
      else if (messageOnly) await ownerAPI.updatePushWalletScenario(scenario.id, { title: form.title, body: form.body });
      else await ownerAPI.updatePushWalletScenario(scenario.id, form);
      onSaved();
    } catch (e) {
      setError(e?.response?.data?.detail || "L'enregistrement n'a pas abouti.");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/25 sm:items-center sm:p-6" onClick={onClose}>
      <div className="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-t-2xl bg-white shadow-2xl sm:rounded-2xl"
           onClick={(e) => e.stopPropagation()}>
        <header className="sticky top-0 flex items-center justify-between border-b border-[#E6EEFB] bg-white px-5 py-4">
          <h3 className="text-[15px] font-bold text-[#0B1C3F]">
            {creating ? 'Créer un scénario Push Wallet' : form.name || 'Scénario'}
          </h3>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#0B1C3F]">
            <X size={18} />
          </button>
        </header>

        <div className="space-y-4 px-5 py-4">
          {messageOnly && (
            <p className="flex items-start gap-1.5 rounded-xl border border-[#D7E6FF] bg-[#EEF5FF] px-3 py-2.5 text-[12px] leading-snug text-[#1D4ED8]">
              <Info size={13} className="mt-px shrink-0" />
              Votre message s'appliquera à : <strong className="ml-1">{scopeLabel}</strong>. Le propriétaire le verra.
              Le déclencheur et le délai restent ceux du commerce.
            </p>
          )}
          <fieldset disabled={messageOnly} className={`m-0 min-w-0 space-y-4 border-0 p-0 ${messageOnly ? 'opacity-60' : ''}`}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Nom du scénario">
              <input className={inputCls} value={form.name} maxLength={80}
                     onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="Sous-titre">
              <input className={inputCls} value={form.subtitle} maxLength={80}
                     placeholder="Ce que fait ce scénario"
                     onChange={(e) => setForm({ ...form, subtitle: e.target.value })} />
            </Field>
          </div>

          <Field label="Déclencheur" hint="Ce qui met le scénario en route.">
            <div className="relative">
              <select className={`${inputCls} appearance-none pr-9`} value={form.trigger}
                      onChange={(e) => setForm({ ...form, trigger: e.target.value,
                                                 config: { ...(TRIGGER_DEFAULTS[e.target.value] || {}) } })}>
                {triggers.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select>
              <ChevronDown size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            </div>
          </Field>

          {needs.includes('days') && (
            <Field label="Jours d'inactivité" hint="Le client n'est plus venu depuis ce nombre de jours.">
              <input type="number" min={1} max={365} className={inputCls}
                     value={form.config.days ?? 30}
                     onChange={(e) => setCfg('days', Math.max(1, Number(e.target.value) || 1))} />
            </Field>
          )}
          {needs.includes('day_of_month') && (
            <Field label="Jour du mois" hint="Le scénario part ce jour-là, chaque mois.">
              <input type="number" min={1} max={28} className={inputCls}
                     value={form.config.day_of_month ?? 1}
                     onChange={(e) => setCfg('day_of_month', Math.min(28, Math.max(1, Number(e.target.value) || 1)))} />
            </Field>
          )}
          {needs.includes('date') && (
            <Field label="Date" hint="Une seule fois, ce jour-là.">
              <input type="date" className={inputCls} value={(form.config.date || '').slice(0, 10)}
                     onChange={(e) => setCfg('date', e.target.value)} />
            </Field>
          )}
          {needs.includes('weekdays') && (
            <>
              <Field label="Jours">
                <div className="flex gap-1.5">
                  {WEEKDAYS.map(([letter, n], i) => {
                    const on = (form.config.weekdays || []).includes(n);
                    return (
                      <button key={i} type="button"
                              onClick={() => setCfg('weekdays', on
                                ? (form.config.weekdays || []).filter((d) => d !== n)
                                : [...(form.config.weekdays || []), n])}
                              className={`h-9 w-9 rounded-lg text-[12.5px] font-semibold transition ${
                                on ? 'bg-[#2F6BFF] text-white' : 'border border-[#E6EEFB] text-[#475569] hover:border-[#2F6BFF]'}`}>
                        {letter}
                      </button>
                    );
                  })}
                </div>
              </Field>
              <div className="grid grid-cols-2 gap-4">
                <Field label="De">
                  <input type="number" min={0} max={23} className={inputCls}
                         value={form.config.from_hour ?? 14}
                         onChange={(e) => setCfg('from_hour', Math.min(23, Math.max(0, Number(e.target.value) || 0)))} />
                </Field>
                <Field label="À">
                  <input type="number" min={1} max={24} className={inputCls}
                         value={form.config.to_hour ?? 17}
                         onChange={(e) => setCfg('to_hour', Math.min(24, Math.max(1, Number(e.target.value) || 1)))} />
                </Field>
              </div>
            </>
          )}
          </fieldset>

          <Field label="Titre du push Wallet">
            <input className={inputCls} value={form.title} maxLength={120}
                   onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Message"
                 hint="{first_name}, {points}, {visits} et {business_name} sont remplacés pour chaque client.">
            <textarea className={`${inputCls} min-h-[80px] resize-y`} value={form.body} maxLength={400}
                      onChange={(e) => setForm({ ...form, body: e.target.value })} />
          </Field>

          <div className="flex flex-wrap gap-2">
            {examples.map((ex) => (
              <button key={ex.title} type="button"
                      onClick={() => setForm({ ...form, title: ex.title, body: ex.body })}
                      className="rounded-lg border border-[#E6EEFB] px-2.5 py-1.5 text-[11.5px] text-[#475569] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                {ex.title}
              </button>
            ))}
          </div>

          <Field label="Ne pas recontacter avant (jours)"
                 hint="Un même client ne recevra pas deux fois ce scénario dans cet intervalle.">
            <input type="number" min={0} max={365} className={inputCls} value={form.cooldown_days} disabled={messageOnly}
                   onChange={(e) => setForm({ ...form, cooldown_days: Math.max(0, Number(e.target.value) || 0) })} />
          </Field>

          {reach !== null && (
            <p className="flex items-start gap-1.5 rounded-xl bg-[#F4F7FC] px-3 py-2.5 text-[12px] text-[#475569]">
              <Info size={13} className="mt-px shrink-0 text-[#2F6BFF]" />
              Aujourd'hui, ce scénario toucherait <strong className="mx-1">{nf(reach)}</strong> client{reach > 1 ? 's' : ''}.
            </p>
          )}
        </div>

        <footer className="sticky bottom-0 flex items-center justify-between gap-3 border-t border-[#E6EEFB] bg-white px-5 py-3.5">
          {error ? <span className="text-[12px] text-[#C0392B]">{error}</span> : <span />}
          <button type="button" onClick={save} disabled={saving || !form.name.trim() || !form.title.trim() || !form.body.trim()}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-60">
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Enregistrer
          </button>
        </footer>
      </div>
    </div>
  );
};

/* ── page ─────────────────────────────────────────────────────────────── */
export default function AutomationsPage() {
  const [tab, setTab] = useState('all');
  const [data, setData] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [trigger, setTrigger] = useState('');
  const [editing, setEditing] = useState(null);
  const [menuFor, setMenuFor] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [toast, setToast] = useState('');

  const load = useCallback(() => {
    setLoading(true); setError('');
    Promise.all([ownerAPI.pushWalletScenarios(), ownerAPI.pushWalletStats()])
      .then(([a, b]) => { setData(a.data); setStats(b.data); })
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger les automatisations.'))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const scenarios = data?.scenarios || [];
  const triggers = data?.triggers || [];
  // Owner: everything. Administrateur: the message and the switch, for its
  // establishments. Manager: reads.
  const can = data?.can || { create: false, edit: false, message_only: true };
  const scopeLabel = data?.scope?.label || '';

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return scenarios.filter((s) => {
      if (tab === 'active' && !s.enabled) return false;
      if (tab === 'draft' && s.enabled) return false;
      if (status === 'active' && !s.enabled) return false;
      if (status === 'draft' && s.enabled) return false;
      if (trigger && s.trigger !== trigger) return false;
      if (needle && !`${s.name} ${s.subtitle} ${s.title} ${s.body}`.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [scenarios, tab, status, trigger, q]);

  const dirty = q || status || trigger;
  const reset = () => { setQ(''); setStatus(''); setTrigger(''); };

  const flip = async (s, next) => {
    setBusyId(s.id);
    try {
      await ownerAPI.updatePushWalletScenario(s.id, { enabled: next });
      load();
    } catch { setError("Le changement n'a pas été enregistré."); }
    finally { setBusyId(null); }
  };

  const runNow = async (s) => {
    setMenuFor(null); setBusyId(s.id);
    try {
      const { data: res } = await ownerAPI.runPushWalletScenario(s.id);
      setToast(res.sent
        ? `« ${s.name} » envoyé à ${nf(res.sent)} client${res.sent > 1 ? 's' : ''}.`
        : `« ${s.name} » n'a personne à toucher aujourd'hui.`);
      setTimeout(() => setToast(''), 5000);
      load();
    } catch { setError("L'envoi n'a pas abouti."); }
    finally { setBusyId(null); }
  };

  const remove = async (s) => {
    setMenuFor(null);
    try { await ownerAPI.deletePushWalletScenario(s.id); load(); }
    catch { setError("La suppression n'a pas abouti."); }
  };

  return (
    <div className="aut" onClick={() => setMenuFor(null)}>
      {/* header */}
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#EAF1FF] text-[#2F6BFF]">
            <Settings2 size={22} />
          </span>
          <div className="max-w-2xl">
            <h1 className="text-[23px] font-bold leading-tight text-[#0B1C3F]">Automatisations</h1>
            <p className="text-[16px] font-bold leading-tight text-[#2F6BFF]">Push Wallet</p>
            <p className="mt-1 text-[13px] leading-snug text-[#64748B]">
              Créez des scénarios automatiques pour envoyer des notifications push directement
              sur le Wallet de vos clients.
            </p>
          </div>
        </div>
        <div className="flex items-start gap-3 rounded-2xl border border-[#D7E6FF] bg-[#EEF5FF] p-4">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-[#2F6BFF]">
            <Wallet size={19} />
          </span>
          <div className="max-w-[300px]">
            <p className="text-[13.5px] font-bold text-[#1D4ED8]">100% Wallet</p>
            <p className="text-[11.5px] leading-snug text-[#3B6CC7]">
              Toutes vos notifications sont envoyées directement sur le Wallet de vos clients
              (Apple Wallet / Google Wallet).
            </p>
          </div>
        </div>
      </header>

      {/* the four figures */}
      <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {(stats?.cards || []).map((c, i) => <KpiCard key={c.key} card={c} tone={KPI_TONES[i] || KPI_TONES[0]} />)}
        {!stats && Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-[118px] animate-pulse rounded-2xl border border-[#E6EEFB] bg-white" />
        ))}
      </div>

      {/* tabs + create */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <nav className="flex gap-1.5 overflow-x-auto rounded-2xl border border-[#E6EEFB] bg-white p-1.5">
          {TABS.map((t) => {
            const Icon = t.icon;
            const on = tab === t.key;
            return (
              <button key={t.key} type="button" onClick={() => setTab(t.key)}
                      className={`inline-flex shrink-0 items-center gap-2 rounded-xl px-3.5 py-2.5 text-[13px] font-semibold transition ${
                        on ? 'bg-[#2F6BFF] text-white' : 'text-[#475569] hover:bg-[#F4F7FC]'}`}>
                <Icon size={15} /> {t.label}
              </button>
            );
          })}
        </nav>
        {can.create && (
        <button type="button" onClick={() => setEditing({})}
                className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white transition hover:bg-[#2559DB]">
          <Plus size={16} /> Créer un scénario Push Wallet
        </button>
        )}
      </div>

      {data && can.message_only && (
        <p className="mb-4 flex items-start gap-1.5 rounded-xl border border-[#E6EEFB] bg-white px-4 py-2.5 text-[12.5px] text-[#475569]">
          <Info size={14} className="mt-px shrink-0 text-[#2F6BFF]" />
          {can.edit
            ? <>Vos changements (message, activation) s'appliquent à : <strong className="mx-1">{scopeLabel}</strong>. Le propriétaire les voit ; ses propres changements valent pour tous les établissements.</>
            : <>Les automatisations sont gérées par le propriétaire et les administrateurs. Chiffres de : <strong className="ml-1">{scopeLabel}</strong>.</>}
        </p>
      )}

      {error && <p className="mb-4 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</p>}
      {toast && <p className="mb-4 rounded-xl bg-[#E7F7EE] px-4 py-2.5 text-[12.5px] text-[#0F8B58]">{toast}</p>}

      <div className="grid items-start gap-4 xl:grid-cols-[1fr_320px]">
        {/* table */}
        <section className="rounded-2xl border border-[#E6EEFB] bg-white shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
          {tab !== 'stats' && (
            <div className="grid gap-3 border-b border-[#EEF3FB] p-4 md:grid-cols-[1.4fr_1fr_1fr_auto]">
              <div className="relative">
                <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher un scénario…"
                       className="w-full rounded-xl border border-[#E6EEFB] bg-white py-2.5 pl-9 pr-3 text-[13px] outline-none focus:border-[#2F6BFF]" />
              </div>
              <div className="relative">
                <select value={status} onChange={(e) => setStatus(e.target.value)}
                        className={`${inputCls} appearance-none pr-9`}>
                  <option value="">Tous les statuts</option>
                  <option value="active">Actifs</option>
                  <option value="draft">Brouillons</option>
                </select>
                <ChevronDown size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
              </div>
              <div className="relative">
                <select value={trigger} onChange={(e) => setTrigger(e.target.value)}
                        className={`${inputCls} appearance-none pr-9`}>
                  <option value="">Tous les déclencheurs</option>
                  {triggers.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                </select>
                <ChevronDown size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
              </div>
              <button type="button" onClick={reset} disabled={!dirty}
                      className="h-[42px] rounded-xl border border-[#E6EEFB] px-4 text-[13px] font-semibold text-[#475569] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF] disabled:opacity-45">
                Réinitialiser
              </button>
            </div>
          )}

          {tab === 'stats' ? (
            <div className="p-5">
              <h2 className="mb-3 text-[14px] font-bold text-[#0B1C3F]">Statistiques par scénario</h2>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] border-collapse">
                  <thead>
                    <tr className="border-b border-[#EEF3FB] text-left">
                      {['Scénario', 'Statut', 'Clients touchés', 'Dernière exécution'].map((h, i) => (
                        <th key={h} className={`px-3 py-2.5 text-[12px] font-semibold text-[#64748B] ${i === 2 ? 'text-right' : ''}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {scenarios.map((s) => (
                      <tr key={s.id} className="border-b border-[#F4F7FC] last:border-b-0">
                        <td className="px-3 py-3 text-[13px] font-medium text-[#0B1C3F]">{s.name}</td>
                        <td className="px-3 py-3">
                          <span className="inline-flex rounded-md px-2.5 py-1 text-[11.5px] font-semibold"
                                style={s.enabled ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#EEF2F8', color: '#64748B' }}>
                            {s.enabled ? 'Actif' : 'Brouillon'}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-right text-[13px] tabular-nums text-[#0B1C3F]">{nf(s.clients)}</td>
                        <td className="whitespace-pre-line px-3 py-3 text-[12px] text-[#64748B]">{stamp(s.last_run_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {stats && (
                <p className="mt-4 flex items-start gap-1.5 text-[11.5px] leading-snug text-[#94A3B8]">
                  <Info size={13} className="mt-px shrink-0" />
                  Un push Wallet n'a pas d'accusé de lecture. Le taux d'ouverture compte les cartes
                  ouvertes dans les {stats.open_window_hours} h suivant un envoi ; le taux de clic
                  compte les liens réellement suivis.
                </p>
              )}
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] border-collapse">
                  <thead>
                    <tr className="border-b border-[#EEF3FB] text-left">
                      {['Nom du scénario', 'Déclencheur', 'Message push Wallet', 'Statut', 'Clients', 'Dernière exécution', 'Actions'].map((h, i) => (
                        <th key={h} className={`px-4 py-3 text-[12px] font-semibold text-[#64748B] ${i === 4 ? 'text-center' : ''}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {loading && !scenarios.length && (
                      <tr><td colSpan={7} className="px-4 py-14 text-center text-[13px] text-[#64748B]">
                        <Loader2 size={16} className="mr-2 inline animate-spin" /> Chargement…
                      </td></tr>
                    )}
                    {!loading && shown.length === 0 && (
                      <tr><td colSpan={7} className="px-4 py-14 text-center">
                        <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Aucun scénario ici</p>
                        <p className="mt-1 text-[12.5px] text-[#64748B]">
                          {dirty ? 'Retirez un filtre pour en voir plus.' : 'Créez votre premier scénario Push Wallet.'}
                        </p>
                      </td></tr>
                    )}
                    {shown.map((s) => {
                      const Icon = SCENARIO_ICONS[s.icon] || Bell;
                      const tone = ICON_TONES[s.icon] || ICON_TONES.bell;
                      return (
                        <tr key={s.id} className="border-b border-[#F4F7FC] last:border-b-0 transition hover:bg-[#FAFCFF]">
                          <td className="px-4 py-3">
                            <span className="flex items-center gap-3">
                              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
                                    style={{ background: `${tone}1A`, color: tone }}>
                                <Icon size={17} />
                              </span>
                              <span className="min-w-0">
                                <span className="block truncate text-[13.5px] font-semibold text-[#0B1C3F]">{s.name}</span>
                                <span className="block truncate text-[11.5px] text-[#94A3B8]">{s.subtitle}</span>
                              </span>
                            </span>
                          </td>
                          <td className="px-4 py-3 text-[12.5px] text-[#475569]">{s.trigger_detail}</td>
                          <td className="max-w-[280px] px-4 py-3">
                            <span className="block truncate text-[12.5px] font-semibold text-[#0B1C3F]">{s.title}</span>
                            <span className="block text-[12px] leading-snug text-[#64748B]">{s.body}</span>
                            {(s.versions || []).length > 0 && (
                              <span className="mt-1.5 block space-y-1">
                                {s.versions.map((v) => (
                                  <span key={v.store_id} title={v.by ? `Modifié par ${v.by}` : ''}
                                        className="block rounded-lg bg-[#F4F7FC] px-2 py-1 text-[11.5px] leading-snug text-[#475569]">
                                    <strong className="text-[#2F6BFF]">{v.store}</strong>
                                    {v.enabled === false && ' · désactivé'}
                                    {v.enabled === true && ' · activé'}
                                    {(v.title || v.body) && <> · {[v.title, v.body].filter(Boolean).join(' — ')}</>}
                                  </span>
                                ))}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            {can.edit ? <Switch on={s.enabled} busy={busyId === s.id} onChange={(v) => flip(s, v)} />
                              : <span className="inline-flex rounded-md px-2.5 py-1 text-[11.5px] font-semibold"
                                      style={s.enabled ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#EEF2F8', color: '#64748B' }}>
                                  {s.enabled ? 'Actif' : 'Brouillon'}
                                </span>}
                          </td>
                          <td className="px-4 py-3 text-center text-[13px] tabular-nums text-[#0B1C3F]">{nf(s.clients)}</td>
                          <td className="whitespace-pre-line px-4 py-3 text-[12px] text-[#64748B]">{stamp(s.last_run_at)}</td>
                          <td className="px-4 py-3">
                            {can.edit && <span className="relative">
                              <button type="button" aria-label="Actions"
                                      onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === s.id ? null : s.id); }}
                                      className="rounded-lg px-1.5 py-1.5 text-[#94A3B8] transition hover:bg-[#F4F7FC] hover:text-[#0B1C3F]">
                                {busyId === s.id ? <Loader2 size={16} className="animate-spin" /> : <MoreHorizontal size={16} />}
                              </button>
                              {menuFor === s.id && (
                                <span onClick={(e) => e.stopPropagation()}
                                      className="absolute right-0 top-full z-20 mt-1 flex w-[190px] flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
                                  <button type="button" onClick={() => { setMenuFor(null); setEditing(s); }}
                                          className="px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F4F7FC]">
                                    Modifier
                                  </button>
                                  {can.create && <button type="button" onClick={() => runNow(s)}
                                          className="flex items-center gap-2 px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F4F7FC]">
                                    <Zap size={13} /> Envoyer maintenant
                                  </button>}
                                  {can.create && !s.builtin && (
                                    <button type="button" onClick={() => remove(s)}
                                            className="flex items-center gap-2 px-3 py-2 text-left text-[12.5px] text-[#C0392B] hover:bg-[#FEF2F2]">
                                      <Trash2 size={13} /> Supprimer
                                    </button>
                                  )}
                                </span>
                              )}
                            </span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="border-t border-[#EEF3FB] px-4 py-3.5">
                <p className="text-[12.5px] text-[#64748B]">
                  Affichage de {shown.length ? 1 : 0} à {shown.length} sur {shown.length} résultat{shown.length > 1 ? 's' : ''}
                </p>
              </div>
            </>
          )}
        </section>

        {/* right rail */}
        <div className="grid gap-4">
          <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
            <h2 className="mb-4 text-[14px] font-bold text-[#0B1C3F]">Créer un scénario</h2>
            <ol className="space-y-3.5">
              {[
                ['Choisissez un déclencheur', '(ex : anniversaire, inactivité, date…)'],
                ['Rédigez votre message push Wallet', 'avec une offre ou une information.'],
                ["Activez et laissez FidClic s'occuper", 'du reste !'],
              ].map(([title, sub], i) => (
                <li key={title} className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#2F6BFF] text-[11px] font-bold text-white">
                    {i + 1}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[12.5px] font-semibold leading-snug text-[#0B1C3F]">{title}</span>
                    <span className="block text-[11.5px] leading-snug text-[#94A3B8]">{sub}</span>
                  </span>
                </li>
              ))}
            </ol>
          </section>

          <section className="rounded-2xl border border-[#E6EEFB] bg-[#F8FAFF] p-5">
            <h2 className="mb-3 flex items-center gap-2 text-[14px] font-bold text-[#0B1C3F]">
              <span className="text-[#F59E0B]">💡</span> Exemples de messages
            </h2>
            <div className="space-y-2">
              {(data?.examples || []).map((ex) => (
                <button key={ex.title} type="button"
                        onClick={() => can.create && setEditing({ title: ex.title, body: ex.body, trigger: 'inactivity', config: { days: 30 } })}
                        className="flex w-full items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white p-3 text-left transition hover:border-[#2F6BFF]">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12.5px] font-semibold text-[#0B1C3F]">{ex.title}</span>
                    <span className="block truncate text-[11.5px] text-[#64748B]">{ex.body}</span>
                  </span>
                  <ChevronRight size={15} className="shrink-0 text-[#94A3B8]" />
                </button>
              ))}
            </div>
          </section>
        </div>
      </div>

      {editing && (
        <ScenarioModal scenario={editing} triggers={triggers} examples={data?.examples || []}
                       messageOnly={!!editing.id && can.message_only} scopeLabel={scopeLabel}
                       onClose={() => setEditing(null)}
                       onSaved={() => { setEditing(null); load(); }} />
      )}
    </div>
  );
}
