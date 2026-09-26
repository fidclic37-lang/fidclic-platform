import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users, Plus, ArrowRight, Star, Gift, ShoppingCart, MapPin, Target, Send,
  Search, MoreVertical, Loader2, X, Trash2, CalendarDays, Coins, Info,
  BarChart3, ChevronDown, Check,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * Segmentation — built to the approved mockups.
 *
 * Nothing on this page is materialised: a segment is a name and a list of
 * conditions, re-counted every time it is read. A client who came in this
 * morning has already left "Clients inactifs" by the time the page loads,
 * which is also why a segment can be handed straight to a campaign.
 *
 * "Potentiel de CA" is the one figure that is an estimate rather than a count,
 * so the page prints how it was reached underneath the table.
 */
const ICONS = {
  users: Users, star: Star, gift: Gift, cart: ShoppingCart, pin: MapPin,
  target: Target, send: Send, segments: BarChart3, calendar: CalendarDays,
  coins: Coins,
};
const TONES = {
  blue:   { bg: '#EAF1FF', fg: '#1D4ED8' },
  green:  { bg: '#E7F7EE', fg: '#0F8B58' },
  rose:   { bg: '#FFF1F3', fg: '#E11D48' },
  amber:  { bg: '#FFF7E6', fg: '#B45309' },
  violet: { bg: '#F3EEFF', fg: '#6D28D9' },
  slate:  { bg: '#EEF2F8', fg: '#475569' },
};
const TONE_ORDER = ['blue', 'violet', 'green', 'amber', 'rose', 'slate'];
const BADGES = {
  tres_eleve: { bg: '#E7F7EE', fg: '#0F8B58' },
  eleve:      { bg: '#E7F7EE', fg: '#0F8B58' },
  moyen:      { bg: '#FFF7E6', fg: '#B45309' },
  faible:     { bg: '#FEECEC', fg: '#C0392B' },
};
const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
const money = (n) => `${(n ?? 0).toLocaleString('fr-FR', { maximumFractionDigits: 0 })} €`;
const dateLabel = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
};

const Panel = ({ children, className = '' }) => (
  <section className={`rounded-2xl border border-[#E6EEFB] bg-white shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] ${className}`}>
    {children}
  </section>
);

const PanelHead = ({ icon: Icon, title, sub, action, tone = 'blue' }) => {
  const t = TONES[tone];
  return (
    <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
              style={{ background: t.bg, color: t.fg }}>
          <Icon size={19} />
        </span>
        <div>
          <h2 className="text-[15.5px] font-bold text-[#0B1C3F]">{title}</h2>
          {sub && <p className="text-[12.5px] text-[#64748B]">{sub}</p>}
        </div>
      </div>
      {action}
    </header>
  );
};

/* ── the four figures ─────────────────────────────────────────────────── */
const Stat = ({ s, i }) => {
  const Icon = ICONS[s.icon] || Users;
  const t = TONES[TONE_ORDER[i % TONE_ORDER.length]];
  const up = (s.delta_pct ?? 0) >= 0;
  return (
    <div className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <div className="flex items-start gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl"
              style={{ background: t.bg, color: t.fg }}>
          <Icon size={20} />
        </span>
        <div className="min-w-0">
          <p className="text-[12.5px] text-[#64748B]">{s.label}</p>
          {s.text !== undefined ? (
            <p className="mt-0.5 truncate text-[19px] font-bold leading-tight text-[#0B1C3F]">{s.text}</p>
          ) : (
            <p className="mt-0.5 text-[24px] font-bold leading-none text-[#0B1C3F] tabular-nums">{nf(s.value)}</p>
          )}
          {s.chip ? (
            <span className="mt-1 inline-block rounded-md bg-[#E7F7EE] px-1.5 py-0.5 text-[11px] font-semibold text-[#0F8B58]">
              {s.chip}
            </span>
          ) : s.delta_pct !== null && s.delta_pct !== undefined ? (
            <span className="mt-1 inline-block text-[11.5px] font-semibold"
                  style={{ color: up ? '#0F8B58' : '#C0392B' }}>
              {up ? '↑ +' : '↓ '}{s.delta_pct}%
            </span>
          ) : null}
          {s.hint && <p className="text-[11px] text-[#94A3B8]">{s.hint}</p>}
        </div>
      </div>
    </div>
  );
};

/* ── the builder ──────────────────────────────────────────────────────── */
const emptyRule = (fields) => {
  const f = fields[0];
  return { field: f.key, op: f.ops[0].key, value: f.type === 'choice' ? f.choices[0].key : '' };
};

const Builder = ({ fields, total, onClose, onCreated }) => {
  const [name, setName] = useState('');
  const [rules, setRules] = useState(() => [emptyRule(fields)]);
  const [preview, setPreview] = useState({ count: total, share: 100, summary: [] });
  const [counting, setCounting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // The count follows the criteria as they are typed, from the same evaluator
  // the segment itself will use — so the number approved here is the number
  // the segment holds.
  useEffect(() => {
    const ready = rules.filter((r) => r.value !== '' && r.value !== null);
    const id = setTimeout(() => {
      setCounting(true);
      ownerAPI.segmentPreview({ rules: ready })
        .then(({ data }) => setPreview(data))
        .catch(() => {})
        .finally(() => setCounting(false));
    }, 300);
    return () => clearTimeout(id);
  }, [rules]);

  const setRule = (i, patch) => setRules((rs) => rs.map((r, n) => (n === i ? { ...r, ...patch } : r)));
  const pickField = (i, key) => {
    const f = fields.find((x) => x.key === key);
    setRule(i, { field: key, op: f.ops[0].key, value: f.type === 'choice' ? f.choices[0].key : '' });
  };

  const submit = async () => {
    setBusy(true); setError('');
    try {
      const { data } = await ownerAPI.createSegment({
        name: name.trim(),
        rules: rules.filter((r) => r.value !== '' && r.value !== null),
      });
      onCreated(data);
    } catch (e) {
      setError(e?.response?.data?.detail || "Le segment n'a pas pu être créé.");
      setBusy(false);
    }
  };

  const Step = ({ n, title, sub, right }) => (
    <div className="mb-3 flex items-start gap-2.5">
      <span className="mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-[#2F6BFF] text-[11px] font-bold text-white">
        {n}
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex items-center justify-between gap-2 text-[14px] font-bold text-[#0B1C3F]">
          {title}
          {right && <span className="text-[11px] font-normal text-[#94A3B8]">{right}</span>}
        </p>
        <p className="text-[12px] leading-snug text-[#64748B]">{sub}</p>
      </div>
    </div>
  );

  // The backdrop deliberately does NOT close this one. It is a long form —
  // a name and up to ten conditions — and one stray click outside it would
  // throw all of that away with no warning. Leaving is explicit: the cross,
  // Annuler, or Échap.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[#0B1C3F]/40 p-4 py-10">
      <div className="w-full max-w-4xl rounded-2xl bg-white shadow-[0_40px_90px_-40px_rgba(11,28,63,.6)]">
        <header className="flex items-start justify-between gap-3 p-6 pb-4">
          <div className="flex items-start gap-3.5">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#EAF1FF] text-[#2F6BFF]">
              <Users size={22} />
            </span>
            <div>
              <h2 className="text-[21px] font-bold leading-tight text-[#0B1C3F]">Créer un segment</h2>
              <p className="text-[13px] text-[#64748B]">
                Définissez vos critères pour identifier les clients qui correspondent à votre cible.
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="text-[#94A3B8] transition hover:text-[#334155]">
            <X size={20} />
          </button>
        </header>

        <div className="grid gap-6 border-t border-[#EEF3FB] p-6 lg:grid-cols-[1.25fr_1fr]">
          {/* left: name + conditions */}
          <div className="lg:border-r lg:border-[#EEF3FB] lg:pr-6">
            <Step n={1} title="Nom du segment" right="Obligatoire"
                  sub="Choisissez un nom clair pour retrouver facilement ce segment." />
            <input value={name} maxLength={50} onChange={(e) => setName(e.target.value)}
                   placeholder="Clients à réactiver"
                   className="w-full rounded-xl border border-[#E6EEFB] px-3.5 py-2.5 text-[13.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
            <p className="mb-5 mt-1 text-right text-[11px] text-[#94A3B8]">{name.length}/50</p>

            <Step n={2} title="Conditions"
                  sub="Ajoutez un ou plusieurs critères pour affiner votre segment." />
            <div className="space-y-2.5">
              {rules.map((r, i) => {
                const f = fields.find((x) => x.key === r.field) || fields[0];
                const Icon = ICONS[f.icon] || Target;
                return (
                  <div key={i} className="flex flex-wrap items-center gap-2">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#EAF1FF] text-[#2F6BFF]">
                      <Icon size={15} />
                    </span>
                    <Select value={r.field} onChange={(v) => pickField(i, v)} className="min-w-[150px] flex-1"
                            options={fields.map((x) => ({ value: x.key, label: x.label }))} />
                    <Select value={r.op} onChange={(v) => setRule(i, { op: v })} className="min-w-[140px] flex-1"
                            options={f.ops.map((o) => ({ value: o.key, label: o.label }))} />
                    {f.type === 'choice' ? (
                      <Select value={r.value} onChange={(v) => setRule(i, { value: v })}
                              className="min-w-[130px] flex-1"
                              options={f.choices.map((c) => ({ value: c.key, label: c.label }))} />
                    ) : (
                      <span className="flex min-w-[130px] flex-1 items-center gap-1.5">
                        <input type="number" min="0" value={r.value}
                               onChange={(e) => setRule(i, { value: e.target.value })}
                               className="w-full rounded-xl border border-[#E6EEFB] px-3 py-2.5 text-[13px] tabular-nums outline-none focus:border-[#2F6BFF]" />
                        {f.unit && (
                          <span className="shrink-0 rounded-xl border border-[#E6EEFB] px-2.5 py-2.5 text-[12.5px] text-[#64748B]">
                            {f.unit}
                          </span>
                        )}
                      </span>
                    )}
                    <button type="button" onClick={() => setRules((rs) => rs.filter((_, n) => n !== i))}
                            disabled={rules.length === 1} title="Supprimer ce critère"
                            className="shrink-0 rounded-lg p-2 text-[#94A3B8] transition hover:bg-[#FEECEC] hover:text-[#C0392B] disabled:opacity-30 disabled:hover:bg-transparent">
                      <Trash2 size={15} />
                    </button>
                  </div>
                );
              })}
            </div>
            <button type="button" onClick={() => setRules((rs) => [...rs, emptyRule(fields)])}
                    disabled={rules.length >= 10}
                    className="mt-3 inline-flex items-center gap-2 rounded-xl border border-dashed border-[#C9DBFB] px-4 py-2.5 text-[13px] font-semibold text-[#2F6BFF] transition hover:border-[#2F6BFF] disabled:opacity-40">
              <Plus size={15} /> Ajouter un critère
            </button>
          </div>

          {/* right: live preview */}
          <div>
            <Step n={3} title="Aperçu du segment"
                  sub="Le nombre de clients se met à jour automatiquement selon vos critères." />
            <div className="mb-4 flex items-center gap-3.5 rounded-2xl bg-[#F6F9FF] p-4">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#2F6BFF] text-white">
                {counting ? <Loader2 size={20} className="animate-spin" /> : <Users size={22} />}
              </span>
              <div className="min-w-0">
                <p className="text-[27px] font-bold leading-none text-[#0B1C3F] tabular-nums">
                  {nf(preview.count)}
                </p>
                <p className="text-[12px] text-[#64748B]">clients correspondants</p>
              </div>
              <span className="ml-auto shrink-0 rounded-lg bg-[#E7F7EE] px-2.5 py-1.5 text-center text-[12px] font-semibold text-[#0F8B58]">
                ≈ {preview.share}%
                <span className="block text-[10px] font-normal">de votre base</span>
              </span>
            </div>

            <div className="mb-4 rounded-2xl border border-[#E6EEFB] p-4">
              <p className="mb-2.5 text-[13px] font-bold text-[#0B1C3F]">Résumé des critères</p>
              {preview.summary?.length ? (
                <ul className="space-y-2">
                  {preview.summary.map((x, i) => {
                    const Icon = ICONS[x.icon] || Target;
                    return (
                      <li key={i} className="flex items-start gap-2 text-[12.5px] text-[#475569]">
                        <Icon size={14} className="mt-0.5 shrink-0 text-[#94A3B8]" /> {x.text}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="text-[12.5px] italic text-[#94A3B8]">
                  Aucun critère pour l'instant : ce segment contiendrait tous vos clients.
                </p>
              )}
            </div>

            <div className="flex items-start gap-2.5 rounded-2xl bg-[#F6F9FF] p-4">
              <Target size={16} className="mt-0.5 shrink-0 text-[#2F6BFF]" />
              <p className="text-[12px] leading-snug text-[#475569]">
                <strong className="text-[#0B1C3F]">Utiliser ce segment pour une campagne</strong><br />
                Une fois créé, vous pourrez lancer une campagne ciblée (push notification, offre
                spéciale, etc.) auprès de ces {nf(preview.count)} clients.
              </p>
            </div>
          </div>
        </div>

        {error && (
          <p className="mx-6 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</p>
        )}
        <footer className="flex justify-end gap-2.5 border-t border-[#EEF3FB] p-5">
          <button type="button" onClick={onClose}
                  className="rounded-xl border border-[#E6EEFB] px-5 py-2.5 text-[13px] font-semibold text-[#334155] transition hover:border-[#2F6BFF]">
            Annuler
          </button>
          <button type="button" onClick={submit} disabled={!name.trim() || busy}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 py-2.5 text-[13px] font-semibold text-white transition hover:bg-[#2559DB] disabled:opacity-50">
            {busy && <Loader2 size={15} className="animate-spin" />} Créer le segment
          </button>
        </footer>
      </div>
    </div>
  );
};

const Select = ({ value, onChange, options, className = '' }) => (
  <span className={`relative ${className}`}>
    <select value={value} onChange={(e) => onChange(e.target.value)}
            className="w-full appearance-none rounded-xl border border-[#E6EEFB] bg-white py-2.5 pl-3 pr-8 text-[13px] text-[#334155] outline-none focus:border-[#2F6BFF]">
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
    <ChevronDown size={14} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
  </span>
);

/* ── "Voir" ───────────────────────────────────────────────────────────── */
const MembersModal = ({ segment, onClose, onCampaign }) => (
  <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[#0B1C3F]/40 p-4 py-10"
       onClick={onClose}>
    <div className="w-full max-w-2xl rounded-2xl bg-white p-5 shadow-[0_40px_90px_-40px_rgba(11,28,63,.6)]"
         onClick={(e) => e.stopPropagation()}>
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[17px] font-bold text-[#0B1C3F]">{segment.name}</h3>
          <p className="text-[12.5px] text-[#64748B]">
            {nf(segment.count)} client{segment.count > 1 ? 's' : ''} — recomptés à l'instant.
          </p>
        </div>
        <button type="button" onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]">
          <X size={18} />
        </button>
      </header>
      {segment.summary?.length > 0 && (
        <ul className="mb-3 flex flex-wrap gap-1.5">
          {segment.summary.map((x, i) => (
            <li key={i} className="rounded-md bg-[#F6F9FF] px-2 py-1 text-[11.5px] text-[#475569]">{x.text}</li>
          ))}
        </ul>
      )}
      <div className="max-h-[50vh] overflow-y-auto rounded-xl border border-[#E6EEFB]">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 bg-white">
            <tr className="border-b border-[#EEF3FB] text-left">
              {['Client', 'Palier', 'Visites', 'Dépensé'].map((h, i) => (
                <th key={h} className={`px-3 py-2 text-[11.5px] font-semibold text-[#64748B] ${i > 1 ? 'text-right' : ''}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {segment.clients?.map((c) => (
              <tr key={c.id} className="border-b border-[#F4F7FC] last:border-b-0">
                <td className="px-3 py-2 text-[12.5px] font-medium text-[#0B1C3F]">{c.name}</td>
                <td className="px-3 py-2 text-[12px] capitalize text-[#64748B]">{c.tier}</td>
                <td className="px-3 py-2 text-right text-[12.5px] tabular-nums text-[#475569]">{nf(c.visits)}</td>
                <td className="px-3 py-2 text-right text-[12.5px] tabular-nums text-[#0B1C3F]">{money(c.spend)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!segment.clients?.length && (
          <p className="py-10 text-center text-[13px] text-[#94A3B8]">Ce segment est vide pour l'instant.</p>
        )}
      </div>
      <div className="mt-4 flex justify-end gap-2.5">
        <button type="button" onClick={onClose}
                className="rounded-xl border border-[#E6EEFB] px-4 py-2.5 text-[13px] font-semibold text-[#334155]">
          Fermer
        </button>
        <button type="button" onClick={onCampaign} disabled={!segment.count}
                className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-50">
          <Send size={14} /> Créer une campagne
        </button>
      </div>
    </div>
  </div>
);

/* ── page ─────────────────────────────────────────────────────────────── */
export default function SegmentationPage() {
  const navigate = useNavigate();
  const [d, setD] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [flash, setFlash] = useState('');
  const [typed, setTyped] = useState('');
  const [builder, setBuilder] = useState(false);
  const [menuFor, setMenuFor] = useState(null);
  const [viewing, setViewing] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    ownerAPI.segmentationPage()
      .then(({ data }) => { setD(data); setError(''); })
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger la segmentation.'))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    const q = typed.trim().toLowerCase();
    const all = d?.segments || [];
    return q ? all.filter((s) => s.name.toLowerCase().includes(q)
                              || (s.description || '').toLowerCase().includes(q)) : all;
  }, [d, typed]);

  const useModel = async (model) => {
    try {
      const { data } = await ownerAPI.createSegment({ name: '', model: model.key });
      setFlash(`Segment « ${data.name} » créé — ${nf(data.count)} clients.`);
      load();
    } catch (e) {
      setError(e?.response?.data?.detail || "Le segment n'a pas pu être créé.");
    }
  };

  const open = async (row) => {
    try {
      const { data } = await ownerAPI.segmentClients(row.id);
      setViewing(data);
    } catch { setError('Impossible d\'ouvrir ce segment.'); }
  };

  const remove = async (row) => {
    setMenuFor(null);
    try { await ownerAPI.deleteSegment(row.id); setFlash(`« ${row.name} » supprimé.`); load(); }
    catch (e) { setError(e?.response?.data?.detail || 'Suppression impossible.'); }
  };

  const toCampaign = (row) => navigate('/dashboard/campaigns');

  if (loading && !d) {
    return (
      <div className="sg flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]">
        <Loader2 size={16} className="animate-spin" /> Chargement…
      </div>
    );
  }

  return (
    <div className="sg" onClick={() => setMenuFor(null)}>
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-[0.14em] text-[#2F6BFF]">
            <Target size={13} /> Segmentation
          </p>
          <h1 className="mt-1 text-[30px] font-bold leading-tight text-[#0B1C3F]">
            Segmentez vos clients pour des actions plus efficaces
          </h1>
          <p className="mt-1 max-w-3xl text-[13.5px] leading-snug text-[#64748B]">
            Identifiez les bons clients, au bon moment, avec le bon message. FidClic vous aide à
            créer des segments intelligents pour augmenter votre chiffre d'affaires.
          </p>
        </div>
        <button type="button" onClick={() => setBuilder(true)}
                className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 py-3 text-[13.5px] font-semibold text-white transition hover:bg-[#2559DB]">
          <Plus size={16} /> Créer un segment
        </button>
      </header>

      {flash && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-[#E7F7EE] px-4 py-2.5 text-[12.5px] font-medium text-[#0F8B58]">
          <Check size={15} /> {flash}
          <button type="button" onClick={() => setFlash('')} className="ml-auto opacity-70 hover:opacity-100">
            <X size={14} />
          </button>
        </div>
      )}
      {error && <p className="mb-4 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</p>}

      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {(d?.strip || []).map((s, i) => <Stat key={s.key} s={s} i={i} />)}
      </div>

      {/* models */}
      <Panel className="mb-4 p-5">
        <PanelHead icon={Star} title="Segments recommandés pour vous"
                   sub="Des segments prêts à l'emploi, basés sur les performances de commerces similaires."
                   action={(
                     <button type="button" onClick={() => setBuilder(true)}
                             className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">
                       Voir tous les modèles <ArrowRight size={13} />
                     </button>
                   )} />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {(d?.models || []).map((m) => {
            const Icon = ICONS[m.icon] || Target;
            const t = TONES[m.tone] || TONES.blue;
            return (
              <div key={m.key} className="flex flex-col rounded-2xl p-4" style={{ background: `${t.bg}80` }}>
                <span className="mb-3 flex h-9 w-9 items-center justify-center rounded-xl bg-white"
                      style={{ color: t.fg }}>
                  <Icon size={17} />
                </span>
                <p className="text-[13.5px] font-bold text-[#0B1C3F]">{m.name}</p>
                <p className="mt-0.5 flex-1 text-[11.5px] leading-snug text-[#64748B]">{m.description}</p>
                <p className="mt-2 text-[12px] font-semibold text-[#334155]">
                  {nf(m.count)} client{m.count > 1 ? 's' : ''}
                </p>
                <button type="button" onClick={() => useModel(m)}
                        className="mt-2.5 rounded-xl border bg-white px-3 py-2 text-[12.5px] font-semibold transition hover:opacity-80"
                        style={{ borderColor: t.fg, color: t.fg }}>
                  Utiliser ce segment
                </button>
              </div>
            );
          })}
        </div>
      </Panel>

      {/* the table */}
      <Panel className="mb-4 p-5">
        <PanelHead icon={Users} title="Vos segments"
                   sub="Gérez vos segments et lancez des campagnes ciblées."
                   action={(
                     <span className="relative">
                       <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
                       <input value={typed} onChange={(e) => setTyped(e.target.value)}
                              placeholder="Rechercher un segment…"
                              className="w-56 rounded-xl border border-[#E6EEFB] py-2 pl-9 pr-3 text-[12.5px] outline-none focus:border-[#2F6BFF]" />
                     </span>
                   )} />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse">
            <thead>
              <tr className="border-b border-[#EEF3FB] text-left">
                {['Nom du segment', 'Nombre de clients', '% de la base', 'Potentiel de CA',
                  'Dernière activité', 'Actions'].map((h, i) => (
                  <th key={h} className={`px-3 py-2.5 text-[11.5px] font-semibold text-[#64748B] ${i === 1 || i === 2 ? 'text-right' : ''}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const Icon = ICONS[s.icon] || Target;
                const t = TONES[s.tone] || TONES.blue;
                const b = BADGES[s.potential?.badge?.key] || BADGES.faible;
                return (
                  <tr key={s.id} className="border-b border-[#F4F7FC] last:border-b-0">
                    <td className="px-3 py-3">
                      <span className="flex items-center gap-2.5">
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                              style={{ background: t.bg, color: t.fg }}>
                          <Icon size={15} />
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-[13px] font-semibold text-[#0B1C3F]">{s.name}</span>
                          <span className="block truncate text-[11px] text-[#94A3B8]">{s.description}</span>
                        </span>
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right text-[13px] font-medium tabular-nums text-[#0B1C3F]">{nf(s.count)}</td>
                    <td className="px-3 py-3 text-right text-[13px] tabular-nums text-[#475569]">{s.share}%</td>
                    <td className="px-3 py-3">
                      <span className="rounded-md px-2 py-0.5 text-[11.5px] font-semibold"
                            style={{ background: b.bg, color: b.fg }}
                            title={`${money(s.potential?.amount)} — ${s.potential?.badge?.basis || ''}`}>
                        {s.potential?.badge?.label}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-[12.5px] text-[#64748B]">{dateLabel(s.last_used_at)}</td>
                    <td className="px-3 py-3">
                      <span className="flex items-center gap-1.5">
                        <button type="button" onClick={() => open(s)}
                                className="rounded-xl border border-[#E6EEFB] px-4 py-1.5 text-[12.5px] font-semibold text-[#334155] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                          Voir
                        </button>
                        <span className="relative">
                          <button type="button"
                                  onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === s.id ? null : s.id); }}
                                  className="rounded-lg p-1.5 text-[#94A3B8] transition hover:bg-[#F4F7FC]">
                            <MoreVertical size={15} />
                          </button>
                          {menuFor === s.id && (
                            <span onClick={(e) => e.stopPropagation()}
                                  className="absolute right-0 top-8 z-20 w-52 overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_18px_40px_-20px_rgba(11,28,63,.4)]">
                              <button type="button" onClick={() => { setMenuFor(null); toCampaign(s); }}
                                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F6F9FF]">
                                <Send size={13} /> Créer une campagne
                              </button>
                              {s.builtin ? (
                                <button type="button" onClick={() => { setMenuFor(null); useModel({ key: s.id.split(':')[1] }); }}
                                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F6F9FF]">
                                  <Plus size={13} /> Enregistrer dans mes segments
                                </button>
                              ) : (
                                <button type="button" onClick={() => remove(s)}
                                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] text-[#C0392B] hover:bg-[#FEECEC]">
                                  <Trash2 size={13} /> Supprimer
                                </button>
                              )}
                            </span>
                          )}
                        </span>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!rows.length && (
          <p className="py-12 text-center text-[13px] text-[#64748B]">
            {typed ? 'Aucun segment ne porte ce nom.' : "Créez votre premier segment ci-dessus."}
          </p>
        )}
        <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]">
          <Info size={12} className="mt-px shrink-0" /> {d?.potential_note}
        </p>
      </Panel>

      {/* tips + goal */}
      <div className="grid gap-4 xl:grid-cols-[1.7fr_1fr]">
        <Panel className="p-5">
          <PanelHead icon={BarChart3} title="Conseils segmentation"
                     sub="Nos recommandations pour mieux cibler vos clients." />
          <div className="grid gap-3 sm:grid-cols-3">
            {(d?.tips || []).map((t, i) => (
              <div key={t.segment_id} className="flex flex-col rounded-2xl border border-[#E6EEFB] p-3.5">
                <p className="mb-1.5 flex items-center gap-2 text-[12.5px] font-bold text-[#0B1C3F]">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-[#EAF1FF] text-[11px] font-bold text-[#2F6BFF]">
                    {i + 1}
                  </span>
                  {t.title}
                </p>
                <p className="mb-3 flex-1 text-[11.5px] leading-snug text-[#64748B]">{t.body}</p>
                <button type="button" onClick={() => toCampaign(t)}
                        className="rounded-xl border border-[#E6EEFB] px-3 py-2 text-[12.5px] font-semibold text-[#2F6BFF] transition hover:border-[#2F6BFF]">
                  Créer la campagne
                </button>
              </div>
            ))}
            {!d?.tips?.length && (
              <p className="py-6 text-[12.5px] text-[#94A3B8] sm:col-span-3">
                Les conseils apparaîtront dès que vos segments contiendront des clients.
              </p>
            )}
          </div>
        </Panel>

        <Panel className="p-5">
          <PanelHead icon={Target} title="Objectif du mois" tone="green"
                     sub={d?.goal?.is_set ? null : 'Fixez-le dans Paramètres.'} />
          {d?.goal?.is_set ? (
            <>
              <p className="text-[27px] font-bold leading-none text-[#0B1C3F] tabular-nums">
                {money(d.goal.target)}
              </p>
              <div className="mt-3 flex items-center gap-2.5">
                <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-[#EEF3FB]">
                  <span className="block h-full rounded-full bg-[#2F6BFF]"
                        style={{ width: `${d.goal.pct || 0}%` }} />
                </span>
                <span className="shrink-0 text-[12.5px] font-bold text-[#2F6BFF] tabular-nums">{d.goal.pct || 0}%</span>
              </div>
              <p className="mt-2.5 text-[12px] leading-snug text-[#64748B]">
                {d.goal.remaining > 0
                  ? <>Il vous manque <strong className="text-[#0B1C3F]">{money(d.goal.remaining)}</strong> pour
                     atteindre votre objectif. Ciblez vos segments à fort potentiel pour y arriver !</>
                  : <>Objectif atteint — {money(d.goal.reached)} ce mois-ci.</>}
              </p>
            </>
          ) : (
            <p className="text-[12.5px] leading-snug text-[#64748B]">
              Aucun objectif fixé pour le moment. Définissez-en un et cette page suivra votre
              progression au fil du mois.
            </p>
          )}
          <button type="button" onClick={() => navigate('/dashboard/insights')}
                  className="mt-4 w-full rounded-xl bg-[#F6F9FF] px-4 py-2.5 text-[13px] font-semibold text-[#2F6BFF] transition hover:bg-[#EAF1FF]">
            Voir les recommandations
          </button>
        </Panel>
      </div>

      {builder && (
        <Builder fields={d?.fields || []} total={d?.total_clients || 0}
                 onClose={() => setBuilder(false)}
                 onCreated={(seg) => {
                   setBuilder(false);
                   setFlash(`Segment « ${seg.name} » créé — ${nf(seg.count)} clients.`);
                   load();
                 }} />
      )}
      {viewing && (
        <MembersModal segment={viewing} onClose={() => setViewing(null)}
                      onCampaign={() => { setViewing(null); toCampaign(viewing); }} />
      )}
    </div>
  );
}
