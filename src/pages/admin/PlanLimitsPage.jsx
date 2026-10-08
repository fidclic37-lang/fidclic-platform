import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Plus, Crown, Sparkles, MoreHorizontal, PieChart, Store, CreditCard, Bell, MapPin, Wallet, GitBranch, Headphones, Megaphone,
  BarChart3, Download, Plug, Database, Zap, Share2, Users, Clock, Info, RotateCcw, Settings2, MessageSquare, History, Loader2,
  Building2, Mail,
} from 'lucide-react';
import { adminAPI } from '../../lib/api';
import { Card, Loading, Breadcrumb, Modal, useToast, nf, BLUE, inputCls } from '../crm/ui';
import DecimalInput from '../../components/DecimalInput';

/* Super admin › Plan Limits — built to the approved mockup. Every limit and
   switch here is enforced for the businesses (features/plan_limits.py):
   a locked section shows them the upgrade prompt, and the server refuses it. */

const ICONS = { store: Store, card: CreditCard, bell: Bell, sparkles: Sparkles, pin: MapPin, wallet: Wallet, branches: GitBranch,
  headset: Headphones, megaphone: Megaphone, chart: BarChart3, download: Download, plug: Plug, database: Database, pie: PieChart,
  zap: Zap, share: Share2, users: Users, clock: Clock, mail: Mail };
const tint = (hex, a) => `${hex}${Math.round(a * 255).toString(16).padStart(2, '0')}`;
const MAIN_ROWS = 12;          // the mockup's rows; the others follow under « Autres limites »

function Switch({ on, onChange, label }) {
  return (
    <button type="button" role="switch" aria-checked={!!on} aria-label={label} onClick={() => onChange(!on)}
            className={`relative h-6 w-11 shrink-0 rounded-full transition ${on ? 'bg-[#10B981]' : 'bg-[#E2E8F0]'}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${on ? 'left-[22px]' : 'left-0.5'}`} />
    </button>
  );
}

function Tip({ text }) {
  if (!text) return null;
  return (
    <span className="group relative inline-flex">
      <Info size={13} className="text-[#94A3B8]" />
      <span className="pointer-events-none absolute left-1/2 top-5 z-20 hidden w-60 -translate-x-1/2 rounded-lg bg-[#0B1C3F] px-2.5 py-1.5 text-[11.5px] font-normal leading-snug text-white shadow-lg group-hover:block">{text}</span>
    </span>
  );
}

const price = (p) => (p.on_quote ? 'Sur devis' : `${nf(p.price ?? 0)}€`);

export default function PlanLimitsPage() {
  const [d, setD] = useState(null);
  const [draft, setDraft] = useState({});
  const [msg, setMsg] = useState(null);
  const [menu, setMenu] = useState(null);
  const [modal, setModal] = useState(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [say, toast] = useToast();

  const load = useCallback(() => {
    adminAPI.planLimits().then(({ data }) => {
      setD(data); setDraft({});
      setMsg({ alert_threshold: data.settings.alert_threshold, alert_message: data.settings.alert_message });
    }).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger les offres.'));
  }, []);
  useEffect(() => { load(); }, [load]);

  const dirty = useMemo(() => Object.values(draft).some((x) => Object.keys(x).length), [draft]);
  if (!d) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{String(err)}</p> : <Loading />;

  const value = (p, k) => (draft[p.key] && k in draft[p.key] ? draft[p.key][k] : p.features[k]);
  const set = (p, k, v) => setDraft((x) => {
    const mine = { ...(x[p.key] || {}) };
    if (v === p.features[k]) delete mine[k]; else mine[k] = v;
    return { ...x, [p.key]: mine };
  });
  const save = async () => {
    setSaving(true);
    try {
      let kept = 0;
      for (const [plan, f] of Object.entries(draft)) {
        if (!Object.keys(f).length) continue;
        const { data } = await adminAPI.savePlanLimits(plan, f);
        kept += data.kept_until_renewal || 0;
      }
      say(kept ? `Limites enregistrées. ${kept} commerce${kept > 1 ? 's gardent' : ' garde'} les anciennes jusqu'à leur renouvellement.` : 'Limites enregistrées.');
      load();
    } catch (e) { say(e?.response?.data?.detail || 'Enregistrement impossible.'); }
    setSaving(false);
  };
  const saveSettings = async (patch) => {
    try { await adminAPI.savePlanLimitSettings({ ...d.settings, ...patch }); say('Paramètres enregistrés.'); load(); }
    catch (e) { say(e?.response?.data?.detail?.[0]?.msg || e?.response?.data?.detail || 'Enregistrement impossible.'); }
  };
  const msgDirty = msg && (Number(msg.alert_threshold) !== d.settings.alert_threshold || msg.alert_message !== d.settings.alert_message);
  const reset = async () => {
    if (!window.confirm('Revenir aux limites par défaut de Starter, Pro, Pro AI et Franchise ? Les offres créées ici ne changent pas.')) return;
    try { await adminAPI.resetPlanLimits(); say('Limites réinitialisées.'); load(); } catch (e) { say(e?.response?.data?.detail || 'Réinitialisation impossible.'); }
  };
  const toggleActive = async (p) => {
    setMenu(null);
    try { await adminAPI.savePlanMeta(p.key, { active: !p.active }); say(p.active ? 'Offre désactivée.' : 'Offre activée.'); load(); }
    catch (e) { say(e?.response?.data?.detail || 'Modification impossible.'); }
  };
  const remove = async (p) => {
    setMenu(null);
    if (!window.confirm(`Supprimer l'offre « ${p.label} » ?`)) return;
    try { await adminAPI.deletePlan(p.key); say('Offre supprimée.'); load(); } catch (e) { say(e?.response?.data?.detail || 'Suppression impossible.'); }
  };

  const plans = d.plans;
  const cell = (p, r) => {
    const v = value(p, r.key);
    if (r.type === 'bool') return <Switch on={!!v} onChange={(x) => set(p, r.key, x)} label={`${r.label} — ${p.label}`} />;
    if (r.type === 'ai') {
      return (
        <select value={v || 'none'} onChange={(e) => set(p, r.key, e.target.value)} className="h-9 w-full rounded-lg border border-[#DCE3EE] bg-white px-2.5 text-[13px] text-[#0B1C3F]">
          {d.ai_levels.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
        </select>
      );
    }
    return (
      <input type="number" min={0} value={v ?? ''} onChange={(e) => set(p, r.key, e.target.value === '' ? 0 : Number(e.target.value))}
             title={Number(v) === 0 && /per_month|max_/.test(r.key) ? 'Illimité' : undefined}
             className={`h-9 w-full rounded-lg border px-2.5 text-[13px] text-[#0B1C3F] ${draft[p.key] && r.key in draft[p.key] ? 'border-[#2F6BFF] bg-[#F4F8FF]' : 'border-[#DCE3EE] bg-white'}`} />
    );
  };
  const rowLine = (r) => { const I = ICONS[r.icon] || Settings2; return (
    <tr key={r.key} className="border-t border-[#EEF2F8]">
      <td className="px-3 py-2.5"><span className="flex items-center gap-2.5 text-[13px] text-[#334155]"><I size={16} className="shrink-0 text-[#2F6BFF]" />{r.label} <Tip text={r.help} /></span></td>
      {plans.map((p) => <td key={p.key} className="px-2 py-2 text-center"><span className="flex justify-center">{cell(p, r)}</span></td>)}
    </tr>); };

  return (
    <div className="crm">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', '/admin'], ['Plan Limits']]} />
          <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Plan Limits</h1>
          <p className="text-[15px] text-[#475569]">Définissez les limites et les fonctionnalités de chaque offre FIDCLIC.</p>
        </div>
        <button type="button" onClick={() => setModal({ type: 'new' })} className="inline-flex h-11 items-center gap-2 rounded-xl px-5 text-[14px] font-medium text-white" style={{ background: BLUE }}><Plus size={17} /> Ajouter un plan</button>
      </header>

      {/* 1 — the offers */}
      <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(270px,1fr))]">
        {plans.map((p) => { const c = p.color || BLUE; const I = p.key === 'vip' ? Sparkles : p.key === 'franchise' ? Building2 : Crown; return (
          <div key={p.key} className="relative rounded-2xl border p-4" style={{ background: `linear-gradient(135deg, ${tint(c, 0.07)}, #fff 70%)`, borderColor: tint(c, 0.35), opacity: p.active ? 1 : 0.65 }}>
            <div className="flex items-start gap-3">
              <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl" style={{ background: tint(c, 0.14), color: c }}><I size={24} /></span>
              <div className="min-w-0 flex-1">
                <p className="text-[19px] font-bold leading-tight text-[#0B1C3F]">{p.label}</p>
                <p className="truncate text-[12.5px] text-[#64748B]">{p.tagline || (p.custom ? 'Offre personnalisée' : '')}</p>
              </div>
              <span className={`rounded-md px-2 py-0.5 text-[11.5px] font-medium ${p.active ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#F1F5F9] text-[#64748B]'}`}>{p.active ? 'Actif' : 'Inactif'}</span>
              <button type="button" aria-label={`Actions ${p.label}`} onClick={() => setMenu(menu === p.key ? null : p.key)} className="rounded-md p-1 text-[#475569] hover:bg-white"><MoreHorizontal size={17} /></button>
              {menu === p.key && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setMenu(null)} />
                  <div className="absolute right-3 top-12 z-20 w-48 overflow-hidden rounded-xl border border-[#DCE3EE] bg-white py-1 text-[12.5px] shadow-lg">
                    <button type="button" onClick={() => { setMenu(null); setModal({ type: 'edit', plan: p }); }} className="block w-full px-3 py-2 text-left hover:bg-[#F4F7FC]">Modifier l'offre</button>
                    <button type="button" onClick={() => toggleActive(p)} className="block w-full px-3 py-2 text-left hover:bg-[#F4F7FC]">{p.active ? 'Désactiver' : 'Activer'}</button>
                    {p.custom && <button type="button" onClick={() => remove(p)} className="block w-full px-3 py-2 text-left text-[#E11D48] hover:bg-[#FFF5F6]">Supprimer</button>}
                  </div>
                </>
              )}
            </div>
            <div className="mt-4 grid grid-cols-[1.1fr_1fr_1fr] items-center gap-2">
              <p className="leading-tight"><span className="block text-[26px] font-bold" style={{ color: c }}>{price(p)}</span>{!p.on_quote && <span className="text-[12.5px] text-[#64748B]">/ mois</span>}</p>
              <p className="flex items-center gap-2 text-[12px] text-[#64748B]"><Store size={20} className="text-[#94A3B8]" /><span><strong className="block text-[16px] text-[#0B1C3F]">{nf(p.commerces)}</strong>commerces</span></p>
              <p className="flex items-center gap-2 text-[12px] text-[#64748B]"><PieChart size={20} style={{ color: c }} /><span><strong className="block text-[16px] text-[#0B1C3F]">{p.pct}%</strong>du total</span></p>
            </div>
          </div>); })}
      </div>

      <div className="mt-4 grid items-start gap-4 xl:grid-cols-[1fr_330px]">
        {/* 2 — the grid of limits */}
        <Card>
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div><h2 className="text-[19px] font-bold text-[#0B1C3F]">Détail des limites par plan</h2><p className="text-[13px] text-[#64748B]">Configurez les limites et les fonctionnalités pour chaque offre.</p></div>
            <button type="button" onClick={reset} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-3.5 text-[13px] font-medium text-[#2F6BFF]"><RotateCcw size={15} /> Réinitialiser aux valeurs par défaut</button>
          </div>
          <div className="overflow-x-auto rounded-xl border border-[#EEF2F8]">
            <table className="w-full min-w-[760px]">
              <thead><tr>
                <th className="w-[36%] bg-[#FAFCFF] px-3 py-3 text-left text-[14px] font-semibold text-[#0B1C3F]">Fonctionnalités / Limites</th>
                {plans.map((p) => { const c = p.color || BLUE; return (
                  <th key={p.key} className="px-2 py-2"><span className="block rounded-lg px-2 py-2 text-center" style={{ background: tint(c, 0.12) }}>
                    <span className="block text-[14px] font-semibold" style={{ color: c }}>{p.label}</span>
                    <span className="block text-[12px] font-normal" style={{ color: c }}>{p.on_quote ? 'Sur devis' : `${nf(p.price ?? 0)}€ / mois`}</span></span></th>); })}
              </tr></thead>
              <tbody>
                {d.rows.slice(0, MAIN_ROWS).map(rowLine)}
                <tr><td colSpan={plans.length + 1} className="bg-[#FAFCFF] px-3 py-2 text-[12px] font-semibold uppercase tracking-wide text-[#64748B]">Autres fonctionnalités et limites</td></tr>
                {d.rows.slice(MAIN_ROWS).map(rowLine)}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[12px] text-[#94A3B8]">0 = illimité pour les quotas mensuels. Une fonction désactivée reste visible pour le commerce, avec une invitation à changer d'offre.</p>
          {dirty && (
            <div className="sticky bottom-3 z-10 mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#C9DBFB] bg-[#F4F8FF] px-4 py-2.5 shadow-lg">
              <span className="text-[13px] text-[#0B1C3F]">Modifications non enregistrées.{!d.settings.auto_apply && ' Les commerces déjà sur ces offres garderont leurs limites jusqu\'à leur renouvellement.'}</span>
              <span className="flex gap-2">
                <button type="button" onClick={() => setDraft({})} className="h-9 rounded-lg border border-[#DCE3EE] bg-white px-3 text-[13px] text-[#475569]">Annuler</button>
                <button type="button" disabled={saving} onClick={save} className="inline-flex h-9 items-center gap-1.5 rounded-lg px-4 text-[13px] font-semibold text-white disabled:opacity-60" style={{ background: BLUE }}>{saving && <Loader2 size={14} className="animate-spin" />} Enregistrer les modifications</button>
              </span>
            </div>
          )}
        </Card>

        {/* 3 — settings, messages, history */}
        <div className="space-y-4">
          <Card>
            <h2 className="mb-3 flex items-center gap-2 text-[16px] font-bold text-[#0B1C3F]"><Settings2 size={18} className="text-[#2F6BFF]" /> Paramètres généraux</h2>
            {[['auto_apply', 'Appliquer automatiquement les limites aux nouveaux commerces',
               'Activé : une modification s\'applique tout de suite à tous les commerces. Désactivé : seulement aux nouveaux ; les autres gardent leurs limites jusqu\'à leur prochain renouvellement.'],
              ['notify_near_limit', 'Notifier les commerces quand ils approchent de leur limite', 'Bannière sur leur tableau de bord et un email par limite et par mois.']].map(([k, l, h]) => (
              <div key={k} className="flex items-center justify-between gap-3 border-t border-[#EEF2F8] py-3 first-of-type:border-0">
                <span className="text-[13px] leading-snug text-[#334155]">{l} <Tip text={h} /></span>
                <Switch on={d.settings[k]} onChange={(v) => saveSettings({ [k]: v })} label={l} />
              </div>
            ))}
          </Card>
          <Card>
            <h2 className="mb-3 flex items-center gap-2 text-[16px] font-bold text-[#0B1C3F]"><MessageSquare size={18} className="text-[#2F6BFF]" /> Messages de limite</h2>
            <label className="flex items-center justify-between gap-3 text-[13px] text-[#334155]">Seuil d'alerte
              <span className="flex items-center overflow-hidden rounded-lg border border-[#DCE3EE]">
                <input type="number" min={1} max={100} value={msg.alert_threshold} onChange={(e) => setMsg({ ...msg, alert_threshold: e.target.value })} className="h-9 w-24 px-2.5 text-[13px] outline-none" />
                <span className="bg-[#F4F7FC] px-2.5 py-2 text-[13px] text-[#64748B]">%</span></span></label>
            <p className="mt-1 text-[12px] text-[#94A3B8]">Envoyer une notification quand un commerce atteint ce pourcentage de sa limite.</p>
            <p className="mb-1 mt-3 text-[13px] text-[#334155]">Message aux commerces</p>
            <textarea maxLength={500} value={msg.alert_message} onChange={(e) => setMsg({ ...msg, alert_message: e.target.value })} className={`${inputCls} h-28 py-2 text-[13px]`} />
            <p className="mt-1 flex justify-between text-[11.5px] text-[#94A3B8]"><span>Variables : {'{pourcentage}'}, {'{fonctionnalité}'}</span><span>{msg.alert_message.length}/500</span></p>
            {msgDirty && <button type="button" onClick={() => saveSettings({ alert_threshold: Number(msg.alert_threshold) || 80, alert_message: msg.alert_message })} className="mt-2 w-full rounded-lg py-2 text-[13px] font-semibold text-white" style={{ background: BLUE }}>Enregistrer le message</button>}
          </Card>
          <Card>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-[16px] font-bold text-[#0B1C3F]"><History size={18} className="text-[#2F6BFF]" /> Historique des modifications</h2>
              <button type="button" onClick={() => setModal({ type: 'history' })} className="rounded-lg border border-[#2F6BFF] px-2.5 py-1 text-[12px] text-[#2F6BFF]">Voir tout</button>
            </div>
            <HistoryList rows={d.history} />
          </Card>
        </div>
      </div>

      {toast}
      {modal?.type === 'new' && <PlanModal plans={plans} onClose={() => setModal(null)} onDone={(m) => { setModal(null); say(m); load(); }} />}
      {modal?.type === 'edit' && <PlanModal plan={modal.plan} plans={plans} onClose={() => setModal(null)} onDone={(m) => { setModal(null); say(m); load(); }} />}
      {modal?.type === 'history' && <HistoryModal onClose={() => setModal(null)} />}
    </div>
  );
}

function HistoryList({ rows }) {
  if (!rows?.length) return <p className="py-3 text-[12.5px] text-[#94A3B8]">Aucune modification pour le moment.</p>;
  return (
    <ul className="space-y-2.5">
      {rows.map((h, i) => (
        <li key={i} className="grid grid-cols-[10px_1fr_auto] gap-2 text-[12.5px]">
          <span className="mt-1.5 h-2 w-2 rounded-full bg-[#2F6BFF]" />
          <span><span className="block text-[#0B1C3F]">{h.text}</span><span className="text-[11.5px] text-[#94A3B8]">{h.at ? new Date(h.at).toLocaleString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}</span></span>
          <span className="text-[11.5px] text-[#64748B]">{h.by}</span>
        </li>
      ))}
    </ul>
  );
}

function HistoryModal({ onClose }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { adminAPI.planLimitsHistory(100).then(({ data }) => setRows(data.rows)).catch(() => setRows([])); }, []);
  return <Modal title="Historique des modifications" onClose={onClose} wide>{rows ? <HistoryList rows={rows} /> : <Loading />}</Modal>;
}

const COLORS = ['#0EA5E9', '#2F6BFF', '#10B981', '#8B5CF6', '#F59E0B', '#E11D48', '#0F766E'];

function PlanModal({ plan, plans, onClose, onDone }) {
  const edit = !!plan;
  const [f, setF] = useState({ label: plan?.label || '', tagline: plan?.tagline || '', price: plan?.price ?? 0, color: plan?.color || COLORS[0], copy_from: 'silver' });
  const [err, setErr] = useState('');
  const save = async () => {
    setErr('');
    try {
      if (edit) {
        const body = { tagline: f.tagline, ...(plan.on_quote ? {} : { price: Number(f.price) || 0 }), ...(plan.custom ? { label: f.label, color: f.color } : {}) };
        await adminAPI.savePlanMeta(plan.key, body);
        onDone('Offre modifiée.');
      } else {
        await adminAPI.createPlan({ label: f.label, tagline: f.tagline, price: Number(f.price) || 0, color: f.color, copy_from: f.copy_from });
        onDone('Offre créée. Réglez ses limites dans le tableau.');
      }
    } catch (e) { setErr(e?.response?.data?.detail?.[0]?.msg || e?.response?.data?.detail || 'Enregistrement impossible.'); }
  };
  const fixedName = edit && !plan.custom;
  return (
    <Modal title={edit ? `Modifier — ${plan.label}` : 'Ajouter un plan'} onClose={onClose}>
      <div className="space-y-3 text-[13px]">
        <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Nom de l'offre</span>
          <input className={inputCls} value={f.label} disabled={fixedName} onChange={(e) => setF({ ...f, label: e.target.value })} placeholder="Ex. Pro Restauration" /></label>
        <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Description courte</span>
          <input className={inputCls} value={f.tagline} maxLength={120} onChange={(e) => setF({ ...f, tagline: e.target.value })} placeholder="Ex. Pour les restaurants en croissance" /></label>
        {!(edit && plan.on_quote) && (
          <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Prix (€ HT / mois)</span>
            <DecimalInput className={inputCls} value={f.price} onChange={(v) => setF({ ...f, price: v })} /></label>
        )}
        {(!edit || plan.custom) && (
          <div><span className="mb-1 block text-[11.5px] text-[#64748B]">Couleur</span>
            <div className="flex gap-2">{COLORS.map((c) => <button key={c} type="button" aria-label={c} onClick={() => setF({ ...f, color: c })} className={`h-7 w-7 rounded-full ${f.color === c ? 'ring-2 ring-offset-2' : ''}`} style={{ background: c, '--tw-ring-color': c }} />)}</div></div>
        )}
        {!edit && (
          <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Partir des limites de</span>
            <select className={inputCls} value={f.copy_from} onChange={(e) => setF({ ...f, copy_from: e.target.value })}>
              {plans.filter((p) => ['silver', 'gold', 'vip'].includes(p.key)).map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
            </select></label>
        )}
        {!edit && <p className="rounded-lg bg-[#F4F7FC] px-3 py-2 text-[12px] text-[#475569]">Vous pourrez donner cette offre à un commerce depuis sa fiche. Le paiement en ligne n'est pas encore disponible pour les offres créées ici.</p>}
        {fixedName && <p className="text-[12px] text-[#94A3B8]">Le nom des offres Starter, Pro, Pro AI et Franchise ne change pas.</p>}
      </div>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{String(err)}</p>}
      <button type="button" disabled={!f.label.trim()} onClick={save} className="mt-4 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>{edit ? 'Enregistrer' : "Créer l'offre"}</button>
    </Modal>
  );
}
