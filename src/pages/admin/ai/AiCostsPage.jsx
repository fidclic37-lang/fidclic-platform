import React, { useCallback, useEffect, useState } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { adminAPI } from '../../../lib/api';
import { Breadcrumb, Loading, useToast } from '../../crm/ui';
import { AiTabs } from './shared';

/* FIDCLIC AI › Coûts IA (user, 2026-11-01): what every model call costs —
   per shop, per feature, per day — and the limits that hold it: each shop's
   monthly AI budget (plan default, or the one set here, enforced the same
   way), the platform's daily cap, the speed limits (features/ai_meter.py). */

const FEATURES = {
  copilot: 'Copilote (chat)', copilot_memory: 'Copilote (mémoire)', campaign_ai: 'Rédiger une campagne',
  automation_ai: 'Rédiger une automatisation', autopilot: 'Autopilot', support: 'Assistant support',
  admin_ai: 'FIDCLIC AI (super admin)', menu_import: 'Photo du menu', invoice_ocr: 'Lecture de facture',
  campaign_recap: 'Bilan de campagne', conseiller: 'Le Conseiller', autre: 'Autre',
};
const PLANS = { silver: 'Starter', gold: 'Pro', vip: 'Pro AI', franchise: 'Franchise' };
const STATE = {
  ok: ['OK', '#047857', '#ECFDF5'], near: ['80 %', '#B45309', '#FFFBEB'], budget: ['Limite atteinte', '#B91C1C', '#FEF2F2'],
  spike: ['Pic — en pause', '#B91C1C', '#FEF2F2'], global: ['Pause globale', '#B91C1C', '#FEF2F2'],
};
const euro = (v, d = 2) => (v == null ? '—' : `${Number(v).toLocaleString('fr-FR', { minimumFractionDigits: d, maximumFractionDigits: d })} €`);
const when = (iso) => new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });

function Card({ label, value, sub, tone = '#0B1C3F', testid }) {
  return (
    <div className="rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid={testid}>
      <p className="text-[12.5px] font-semibold text-[#64748B]">{label}</p>
      <p className="mt-1 text-[26px] font-bold tabular-nums" style={{ color: tone }}>{value}</p>
      {sub && <p className="text-[12px] text-[#94A3B8]">{sub}</p>}
    </div>
  );
}

function ShopRow({ s, onSave, onRelease }) {
  const [v, setV] = useState(s.custom_limit ? String(s.limit_eur) : '');
  const [label, fg, bg] = STATE[s.state] || STATE.ok;
  return (
    <tr className="border-t border-[#F1F5FB]" data-testid={`cost-shop-${s.tenant_id}`}>
      <td className="py-2 font-semibold text-[#0B1C3F]">{s.name}</td>
      <td>{PLANS[s.plan] || s.plan || '—'}</td>
      <td className="tabular-nums">{euro(s.month_eur)}</td>
      <td className="tabular-nums">{euro(s.limit_eur)}{s.custom_limit ? ' (réglé)' : ''}</td>
      <td className="tabular-nums">{s.pct} %</td>
      <td><span className="rounded-md px-2 py-0.5 text-[12px] font-medium" style={{ color: fg, background: bg }}>{label}</span></td>
      <td className="tabular-nums">{s.margin_pct == null ? '—' : `${s.margin_pct} %`}</td>
      <td>
        <div className="flex items-center gap-1.5">
          <input type="number" min="0" max="1000" step="1" value={v} placeholder="défaut" aria-label={`Budget IA de ${s.name}`}
                 onChange={(e) => setV(e.target.value)} className="w-20 rounded-md border border-[#DCE3EE] px-2 py-1 text-[12.5px]" />
          <button type="button" onClick={() => onSave(s, v === '' ? null : Number(v))}
                  className="rounded-md bg-[#2F6BFF] px-2.5 py-1 text-[12px] font-semibold text-white">Enregistrer</button>
          {s.state === 'spike' && (
            <button type="button" onClick={() => onRelease(s)} className="rounded-md bg-[#FEF2F2] px-2.5 py-1 text-[12px] font-semibold text-[#B91C1C]">Débloquer</button>
          )}
        </div>
      </td>
    </tr>
  );
}

function Settings({ s, onSave }) {
  const [f, setF] = useState(() => ({ ...s, plan_budgets: { ...s.plan_budgets } }));
  const num = (k, label, step = '1') => (
    <label className="text-[12.5px] text-[#475569]">{label}
      <input type="number" step={step} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })}
             className="mt-1 block w-28 rounded-md border border-[#DCE3EE] px-2 py-1 text-[13px]" data-testid={`cost-set-${k}`} />
    </label>
  );
  const save = () => onSave({
    global_day_eur: Number(f.global_day_eur), usd_eur: Number(f.usd_eur), user_per_min: Number(f.user_per_min),
    request_calls: Number(f.request_calls),
    plan_budgets: Object.fromEntries(Object.entries(f.plan_budgets).map(([k, x]) => [k, Number(x)])),
  });
  return (
    <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="cost-settings">
      <h2 className="text-[15px] font-bold text-[#0B1C3F]">Limites</h2>
      <p className="mt-0.5 text-[12.5px] text-[#64748B]">Budget IA par mois selon l&apos;offre (le coût pour FidClic, jamais facturé au commerçant).
        Une limite atteinte : FidClic IA répond avec les modèles simples et le commerçant voit « Limite IA du mois atteinte ».</p>
      <div className="mt-3 flex flex-wrap gap-4">
        {Object.keys(PLANS).map((k) => (
          <label key={k} className="text-[12.5px] text-[#475569]">{PLANS[k]} (€/mois)
            <input type="number" min="0" max="1000" value={f.plan_budgets[k] ?? ''} onChange={(e) => setF({ ...f, plan_budgets: { ...f.plan_budgets, [k]: e.target.value } })}
                   className="mt-1 block w-24 rounded-md border border-[#DCE3EE] px-2 py-1 text-[13px]" data-testid={`cost-plan-${k}`} />
          </label>
        ))}
        {num('global_day_eur', 'Plafond plateforme (€/jour, 0 = tout arrêter)', '0.5')}
        {num('usd_eur', '1 $ = … €', '0.01')}
        {num('user_per_min', 'Appels par personne et par minute')}
        {num('request_calls', 'Appels par requête')}
      </div>
      <button type="button" onClick={save} className="mt-3 rounded-lg bg-[#2F6BFF] px-3.5 py-2 text-[13px] font-semibold text-white" data-testid="cost-settings-save">Enregistrer les limites</button>
    </section>
  );
}

export default function AiCostsPage() {
  const [d, setD] = useState(null);
  const [say, toast] = useToast();
  const load = useCallback(() => {
    adminAPI.aiCosts().then(({ data }) => setD(data)).catch(() => setD({ error: true }));
  }, []);
  useEffect(() => { load(); }, [load]);

  const saveShop = async (s, budget) => {
    try {
      await adminAPI.aiCostsShop(s.tenant_id, { budget_eur: budget });
      say(budget == null ? `${s.name} : retour au budget de son offre.` : `${s.name} : budget IA ${euro(budget, 0)} par mois.`);
      load();
    } catch (e) { say('Budget refusé : entre 0 et 1 000 €.'); }
  };
  const release = async (s) => {
    try { await adminAPI.aiCostsRelease(s.tenant_id); say(`${s.name} : débloqué pour aujourd'hui.`); load(); } catch (e) { say("Le déblocage n'a pas pu être fait."); }
  };
  const saveSettings = async (body) => {
    try { await adminAPI.aiCostsSettings(body); say('Limites enregistrées.'); load(); } catch (e) { say('Valeurs refusées : vérifiez les limites.'); }
  };

  if (!d) return <Loading />;
  if (d.error) return <p className="text-[14px] text-[#B91C1C]">Les coûts IA n&apos;ont pas pu être chargés.</p>;
  const s = d.summary;

  return (
    <div className="crm">
      {toast}
      <Breadcrumb items={[['Super Admin', '/admin'], ['FIDCLIC AI', '/admin/ai'], ['Coûts IA']]} />
      <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Coûts IA</h1>
      <p className="mb-3 text-[15px] text-[#475569]">Chaque appel à un modèle : la boutique, la fonction, les tokens et ce qu&apos;il a coûté. Jours et mois à l&apos;heure de Paris.</p>
      <AiTabs />

      {s.paused && (
        <p className="mb-3 rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-2.5 text-[13.5px] font-semibold text-[#B91C1C]" data-testid="cost-paused">
          Plafond du jour atteint : toute l&apos;IA est en pause jusqu&apos;à minuit. Relevez le plafond ci-dessous pour la relancer.
        </p>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card label="Aujourd'hui" value={euro(s.today_eur)} sub={`plafond ${euro(s.global_day_eur, 0)}`} testid="cost-today" tone={s.paused ? '#B91C1C' : '#0B1C3F'} />
        <Card label="Ce mois-ci" value={euro(s.month_eur)} testid="cost-month" />
        <Card label="Appels aujourd'hui" value={s.calls_today.toLocaleString('fr-FR')} testid="cost-calls" />
        <Card label="Refusés aujourd'hui" value={s.blocked_today.toLocaleString('fr-FR')} sub="limite, vitesse, taille" testid="cost-blocked" tone={s.blocked_today ? '#B45309' : '#0B1C3F'} />
      </div>

      <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-4">
        <h2 className="text-[15px] font-bold text-[#0B1C3F]">30 derniers jours</h2>
        <div className="mt-2 h-[200px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={d.by_day.map((x) => ({ ...x, label: x.day.slice(8, 10) + '/' + x.day.slice(5, 7) }))}>
              <CartesianGrid vertical={false} stroke="#EEF2F8" />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#94A3B8' }} interval={4} />
              <YAxis tick={{ fontSize: 11, fill: '#94A3B8' }} width={40} />
              <Tooltip formatter={(v) => euro(v)} labelFormatter={(l) => `Jour ${l}`} />
              <Bar dataKey="eur" fill="#2F6BFF" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_2fr]">
        <section className="rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="cost-features">
          <h2 className="text-[15px] font-bold text-[#0B1C3F]">Par fonction (ce mois)</h2>
          <table className="mt-2 w-full text-[13px]">
            <thead><tr className="text-left text-[#94A3B8]"><th className="py-1.5">Fonction</th><th>Appels</th><th>Refusés</th><th>Coût</th></tr></thead>
            <tbody>
              {d.by_feature.map((f) => (
                <tr key={f.feature} className="border-t border-[#F1F5FB]"><td className="py-1.5">{FEATURES[f.feature] || f.feature}</td>
                  <td className="tabular-nums">{f.calls}</td><td className="tabular-nums">{f.blocked}</td><td className="tabular-nums">{euro(f.eur)}</td></tr>
              ))}
              {!d.by_feature.length && <tr><td colSpan={4} className="py-2 text-[#94A3B8]">Aucun appel ce mois-ci.</td></tr>}
            </tbody>
          </table>
        </section>
        <section className="overflow-x-auto rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="cost-shops">
          <h2 className="text-[15px] font-bold text-[#0B1C3F]">Par commerce (ce mois)</h2>
          <table className="mt-2 w-full text-[13px]">
            <thead><tr className="text-left text-[#94A3B8]"><th className="py-1.5">Commerce</th><th>Offre</th><th>Coût IA</th><th>Budget</th><th>Utilisé</th><th>État</th><th>Marge</th><th>Budget IA (€/mois)</th></tr></thead>
            <tbody>{d.shops.map((x) => <ShopRow key={`${x.tenant_id}-${x.limit_eur}`} s={x} onSave={saveShop} onRelease={release} />)}</tbody>
          </table>
        </section>
      </div>

      <Settings key={JSON.stringify(d.settings)} s={d.settings} onSave={saveSettings} />

      {d.alerts.length > 0 && (
        <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="cost-alerts">
          <h2 className="text-[15px] font-bold text-[#0B1C3F]">Alertes</h2>
          <ul className="mt-2 space-y-1.5 text-[13px] text-[#334155]">
            {d.alerts.map((a) => <li key={a.id}><span className="tabular-nums text-[#94A3B8]" translate="no">{when(a.at)}</span> · {a.text}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}
