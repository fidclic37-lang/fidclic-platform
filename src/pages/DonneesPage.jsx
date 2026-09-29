import React, { useEffect, useState } from 'react';
import {
  Lock, ShieldCheck, CheckCircle2, FileText, User, Send, MapPin, Pencil, ArrowRight, Database, Star,
  CalendarDays, Settings, ChevronRight, Download, Clock, Trash2, Search, Cookie, X, Loader2, AlertTriangle, Check,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* Paramètres › Données & confidentialité — built to the approved mockup.
   Every switch does something (features/privacy_page.py): marketing off
   stops campaigns and automations, geolocation off stops proximity
   reminders, the consent sentence and the policy show on the join page,
   the durations anonymise stale data every night once saved. */

const BLUE = '#2F6BFF';
const COLLECTED_ICON = { identity: User, loyalty: Star, visits: CalendarDays, preferences: Settings, location: MapPin };
const EXPORTS = [['identity', "Informations d'identité"], ['loyalty', 'Données de fidélité'], ['purchases', "Historique d'achats"],
                 ['consents', 'Consentements'], ['visits', 'Données de visite']];

const Card = ({ children, className = '' }) => (
  <section className={`rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)] ${className}`}>{children}</section>
);
const Head = ({ icon: Icon, title, sub, tone = BLUE, bg = '#EEF4FF', right }) => (
  <header className="mb-3 flex items-start gap-3">
    <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: bg, color: tone }}><Icon size={23} /></span>
    <div className="min-w-0 flex-1">
      <h2 className="text-[16px] font-bold text-[#0B1C3F]">{title}</h2>
      {sub && <p className="text-[13px] leading-snug text-[#64748B]">{sub}</p>}
    </div>
    {right}
  </header>
);
const Switch = ({ on, onChange, disabled, label }) => (
  <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
          className={`relative h-7 w-[50px] shrink-0 rounded-full transition disabled:cursor-not-allowed ${on ? 'bg-[#2F6BFF]' : 'bg-[#DFE6F1]'} ${disabled ? 'opacity-70' : ''}`}>
    <span className={`absolute top-[3px] h-[22px] w-[22px] rounded-full bg-white shadow transition-all ${on ? 'left-[25px]' : 'left-[3px]'}`} />
  </button>
);
function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/30 sm:items-center sm:p-6" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="mb-4 flex items-center justify-between">
          <h3 className="text-[16px] font-bold text-[#0B1C3F]">{title}</h3>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#0B1C3F]"><X size={18} /></button>
        </header>
        {children}
      </div>
    </div>
  );
}

export default function DonneesPage() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [toast, setToast] = useState('');
  const [modal, setModal] = useState(null);           // {type, ...}
  const [fmt, setFmt] = useState('csv');
  const [sections, setSections] = useState(['identity', 'loyalty', 'purchases', 'consents']);
  const [exporting, setExporting] = useState(false);
  const [q, setQ] = useState('');
  const [results, setResults] = useState(null);
  const [text, setText] = useState('');
  const [policy, setPolicy] = useState({ url: '', text: '' });

  useEffect(() => {
    ownerAPI.privacy().then(({ data }) => setD(data)).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger la page.'));
  }, []);
  const say = (m) => { setToast(m); setTimeout(() => setToast(''), 3500); };
  const save = async (body, ok) => {
    setErr('');
    try { const { data } = await ownerAPI.savePrivacy(body); setD(data); if (ok) say(ok); return true; }
    catch (e) { setErr(e?.response?.data?.detail || "L'enregistrement n'a pas abouti."); return false; }
  };

  if (!d) {
    return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p>
      : <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>;
  }
  const edit = d.can_edit;

  const doExport = async () => {
    setExporting(true); setErr('');
    try {
      const { data, headers } = await ownerAPI.exportPrivacy({ format: fmt, sections });
      const name = /filename="([^"]+)"/.exec(headers['content-disposition'] || '')?.[1] || `clients.${fmt}`;
      const url = URL.createObjectURL(data);
      const a = document.createElement('a'); a.href = url; a.download = name; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch { setErr("L'export n'a pas abouti."); }
    finally { setExporting(false); }
  };
  const doSearch = async () => {
    try { const { data } = await ownerAPI.searchPrivacy(q); setResults(data.results || []); }
    catch { setResults([]); }
  };
  const setRetention = (patch) => {
    if (!d.retention.active) { setModal({ type: 'retention', patch }); return; }
    save({ retention: patch }, 'Conservation enregistrée — appliquée chaque nuit.');
  };

  return (
    <div className="rgpd">
      <header className="mb-4 flex items-start gap-3">
        <span className="mt-0.5 flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#2F6BFF] text-white"><Lock size={22} /></span>
        <div>
          <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Données & confidentialité</h1>
          <p className="text-[15px] text-[#475569]">Gérez les données de vos clients et assurez la conformité au RGPD.</p>
        </div>
      </header>
      {err && <p className="mb-4 rounded-xl bg-[#FEF2F2] px-4 py-2.5 text-[13px] text-[#B91C1C]">{err}</p>}

      <section className={`mb-4 flex flex-wrap items-center gap-4 rounded-2xl border p-4 ${d.compliance.ok ? 'border-[#D5F0E0] bg-gradient-to-r from-[#F1FBF5] to-white' : 'border-[#FDE68A] bg-[#FFFBEB]'}`}>
        <span className={`flex h-14 w-14 items-center justify-center rounded-xl ${d.compliance.ok ? 'bg-[#DDF4E7] text-[#10B981]' : 'bg-[#FEF3C7] text-[#D97706]'}`}><ShieldCheck size={28} /></span>
        <div className="min-w-0 flex-1">
          <p className="text-[17px] font-bold text-[#0B1C3F]">Conformité RGPD</p>
          <p className="text-[14px] text-[#475569]">{d.compliance.ok ? 'Votre établissement respecte les exigences du RGPD.'
            : 'Fixez vos durées de conservation (ci-dessous) pour être pleinement conforme.'}</p>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-[13.5px] font-medium ${d.compliance.ok ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FEF3C7] text-[#92400E]'}`}>
          {d.compliance.ok ? <CheckCircle2 size={16} className="text-white" fill="#10B981" /> : <AlertTriangle size={15} />} {d.compliance.ok ? 'Conforme' : 'À compléter'}
        </span>
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <Head icon={FileText} title="Consentement des clients" sub="Gérez la collecte et l'utilisation des données de vos clients." />
          <div className="divide-y divide-[#F1F5F9] rounded-xl border border-[#EDF1F7]">
            {[
              [User, "Collecte du consentement lors de l'inscription", "Demander le consentement pour l'utilisation des données.", true, null, true],
              [Send, 'Communications marketing', "Autoriser l'envoi de notifications et d'offres.", d.consent.marketing, 'marketing'],
              [MapPin, 'Géolocalisation', 'Utiliser la localisation pour des offres personnalisées.', d.consent.geo, 'geo'],
            ].map(([Icon, title, sub, on, key, locked]) => (
              <div key={title} className="flex items-center gap-3 p-3.5">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#EEF4FF] text-[#2F6BFF]"><Icon size={19} /></span>
                <div className="min-w-0 flex-1"><p className="text-[14px] text-[#0B1C3F]">{title}</p><p className="text-[12.5px] text-[#64748B]">{sub}</p></div>
                <span title={locked ? 'Obligatoire : aucune carte sans consentement.' : ''}>
                  <Switch on={on} disabled={locked || !edit} label={title}
                          onChange={(v) => save({ consent: { [key]: v } }, v ? 'Activé.' : 'Désactivé.')} />
                </span>
              </div>
            ))}
          </div>
          <button type="button" disabled={!edit} onClick={() => { setText(d.consent.text || d.default_consent_text); setModal({ type: 'consent' }); }}
                  className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl border border-[#DCE3EE] py-2.5 text-[13.5px] font-medium text-[#2F6BFF] disabled:opacity-50">
            <Pencil size={15} /> Personnaliser le texte de consentement <ArrowRight size={15} className="ml-auto mr-3" />
          </button>
        </Card>

        <Card>
          <Head icon={Database} title="Données collectées" sub="Consultez les types de données que vous collectez." />
          <div className="divide-y divide-[#F1F5F9] rounded-xl border border-[#EDF1F7]">
            {d.collected.map((c) => {
              const Icon = COLLECTED_ICON[c.key] || Database;
              return (
                <button key={c.key} type="button" onClick={() => setModal({ type: 'collected', item: c })}
                        className="flex w-full items-center gap-3 p-3 text-left hover:bg-[#F8FAFF]">
                  <Icon size={21} className="shrink-0 text-[#2F6BFF]" />
                  <span className="min-w-0 flex-1"><span className="block text-[14px] text-[#0B1C3F]">{c.label}</span>
                    <span className="block text-[12.5px] text-[#64748B]">{c.sub}</span></span>
                  <span className={`rounded-md px-2.5 py-1 text-[12px] ${c.status === 'collected' ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#EEF2F8] text-[#64748B]'}`}>
                    {c.status === 'collected' ? 'Collectées' : c.status === 'optional' ? 'Optionnelles' : 'Désactivées'}
                  </span>
                  <ChevronRight size={17} className="text-[#0B1C3F]" />
                </button>
              );
            })}
          </div>
        </Card>

        <Card>
          <Head icon={Download} title="Export des données" sub="Exportez les données de vos clients au format souhaité." />
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block"><span className="mb-1 block text-[13.5px] text-[#0B1C3F]">Format d'export</span>
              <select value={fmt} onChange={(e) => setFmt(e.target.value)} className="h-11 w-full rounded-lg border border-[#DCE3EE] bg-white px-3 text-[14px] text-[#0B1C3F]">
                <option value="csv">CSV (Excel)</option><option value="json">JSON</option>
              </select></label>
            <div>
              <p className="mb-1 text-[12.5px] font-semibold text-[#0B1C3F]">Données à exporter</p>
              {EXPORTS.map(([k, label]) => (
                <label key={k} className="flex items-center gap-2 py-0.5 text-[13px] text-[#475569]">
                  <input type="checkbox" checked={sections.includes(k)} className="h-4 w-4 accent-[#2F6BFF]"
                         onChange={(e) => setSections(e.target.checked ? [...sections, k] : sections.filter((x) => x !== k))} /> {label}
                </label>
              ))}
            </div>
          </div>
          <button type="button" onClick={doExport} disabled={!edit || exporting || !sections.length}
                  className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl py-3 text-[15px] font-medium text-white disabled:opacity-50" style={{ background: BLUE }}>
            {exporting ? <Loader2 size={17} className="animate-spin" /> : <Download size={17} />} Exporter les données
          </button>
        </Card>

        <Card>
          <Head icon={Clock} title="Conservation des données" sub="Définissez la durée de conservation des données." tone="#F59E0B" bg="#FFF4DB" />
          {[['inactive_years', 'Données des clients inactifs', 'Suppression automatique après cette période.', d.choices.inactive_years],
            ['transactions_years', 'Données de transaction', 'Conservation pour des raisons légales et comptables.', d.choices.transactions_years]].map(([k, title, sub, opts]) => (
            <div key={k} className="flex items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1"><p className="text-[14px] text-[#0B1C3F]">{title}</p><p className="text-[12.5px] text-[#64748B]">{sub}</p></div>
              <select value={d.retention[k]} disabled={!edit} onChange={(e) => setRetention({ [k]: Number(e.target.value) })}
                      className="h-11 w-40 rounded-lg border border-[#DCE3EE] bg-white px-3 text-[14px] text-[#0B1C3F]">
                {opts.map((n) => <option key={n} value={n}>{n} an{n > 1 ? 's' : ''}</option>)}
              </select>
            </div>
          ))}
          <p className={`mt-1 text-[12px] ${d.retention.active ? 'text-[#64748B]' : 'text-[#B45309]'}`}>
            {d.retention.active ? 'Appliqué chaque nuit : les clients concernés sont anonymisés, les montants restent pour vos comptes.'
              : 'Pas encore activé : choisissez vos durées pour les appliquer.'}
          </p>
          {!d.retention.active && edit && (
            <button type="button" onClick={() => setModal({ type: 'retention', patch: {} })}
                    className="mt-2 rounded-lg border border-[#F59E0B] px-3 py-1.5 text-[12.5px] font-medium text-[#B45309]">Activer ces durées</button>
          )}
        </Card>

        <Card>
          <Head icon={Trash2} title="Suppression d'un client" sub="Supprimez définitivement toutes les données d'un client." tone="#E11D48" bg="#FDECEF" />
          <div className="flex gap-2">
            <label className="relative flex-1">
              <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
              <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && doSearch()} disabled={!edit}
                     placeholder="Rechercher un client (nom, email, téléphone)..."
                     className="h-11 w-full rounded-lg border border-[#DCE3EE] bg-white pl-9 pr-3 text-[14px] outline-none focus:border-[#2F6BFF]" />
            </label>
            <button type="button" onClick={doSearch} disabled={!edit || q.trim().length < 2}
                    className="rounded-lg px-6 text-[14px] font-medium text-white disabled:opacity-50" style={{ background: BLUE }}>Rechercher</button>
          </div>
          {results && (
            <ul className="mt-3 divide-y divide-[#F1F5F9]">
              {results.length === 0 && <li className="py-3 text-[13px] text-[#64748B]">Aucun client trouvé.</li>}
              {results.map((c) => (
                <li key={c.id} className="flex items-center gap-3 py-2.5">
                  <div className="min-w-0 flex-1"><p className="text-[14px] text-[#0B1C3F]">{c.name}</p>
                    <p className="truncate text-[12px] text-[#64748B]">{[c.phone, c.email, c.barcode_id].filter(Boolean).join(' · ')}</p></div>
                  <button type="button" onClick={() => setModal({ type: 'erase', client: c })}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-[#FCA5A5] px-3 py-1.5 text-[12.5px] text-[#E11D48]"><Trash2 size={14} /> Supprimer</button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="grid content-start gap-4">
          <Card>
            <Head icon={Cookie} title="Cookies" sub="Gérez l'utilisation des cookies sur votre page d'inscription." tone="#F59E0B" bg="#FFF4DB"
                  right={<button type="button" disabled={!edit} onClick={() => setModal({ type: 'cookies' })}
                                 className="inline-flex shrink-0 items-center gap-1.5 self-center rounded-xl border border-[#2F6BFF] px-4 py-2 text-[13px] font-medium text-[#2F6BFF] disabled:opacity-50">Configurer les cookies <ArrowRight size={14} /></button>} />
          </Card>
          <Card>
            <Head icon={FileText} title="Politique de confidentialité" sub="Consultez et modifiez votre politique de confidentialité."
                  right={<button type="button" onClick={() => { setPolicy(d.policy); setModal({ type: 'policy' }); }}
                                 className="inline-flex shrink-0 items-center gap-1.5 self-center rounded-xl border border-[#2F6BFF] px-4 py-2 text-[13px] font-medium text-[#2F6BFF]">Voir / Modifier la politique <ArrowRight size={14} /></button>} />
          </Card>
        </div>
      </div>

      <div aria-live="polite" className="pointer-events-none fixed bottom-5 left-1/2 z-40 -translate-x-1/2 transition-opacity" style={{ opacity: toast ? 1 : 0 }}>
        <span className="inline-flex items-center gap-2 rounded-full bg-[#0B1C3F] px-4 py-2 text-[13px] font-medium text-white shadow-lg"><Check size={14} /> {toast}</span>
      </div>

      {modal?.type === 'consent' && (
        <Modal title="Texte de consentement" onClose={() => setModal(null)}>
          <p className="mb-2 text-[12.5px] text-[#64748B]">Affiché sur votre page d'inscription, à côté de la case que le client doit cocher. {'{business_name}'} est remplacé par le nom de votre commerce.</p>
          <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={600}
                    className="min-h-[140px] w-full rounded-lg border border-[#DCE3EE] px-3 py-2 text-[13.5px] leading-snug outline-none focus:border-[#2F6BFF]" />
          <div className="mt-3 flex justify-between gap-2">
            <button type="button" onClick={() => setText(d.default_consent_text)} className="text-[12.5px] text-[#64748B] underline">Texte standard</button>
            <button type="button" onClick={async () => { if (await save({ consent: { text } }, 'Texte enregistré.')) setModal(null); }}
                    className="rounded-lg px-4 py-2 text-[13.5px] font-medium text-white" style={{ background: BLUE }}>Enregistrer</button>
          </div>
        </Modal>
      )}
      {modal?.type === 'collected' && (
        <Modal title={modal.item.label} onClose={() => setModal(null)}>
          <ul className="space-y-2">{modal.item.fields.map((f) => <li key={f} className="flex items-center gap-2 text-[13.5px] text-[#475569]"><Check size={15} className="text-[#10B981]" /> {f}</li>)}</ul>
          {modal.item.key === 'location' && <p className="mt-3 text-[12.5px] text-[#64748B]">{modal.item.count || 0} client(s) ont partagé leur position.</p>}
        </Modal>
      )}
      {modal?.type === 'retention' && (
        <Modal title="Activer la conservation" onClose={() => setModal(null)}>
          <p className="text-[13.5px] leading-snug text-[#475569]">
            Chaque nuit, les clients sans activité depuis <strong>{modal.patch.inactive_years || d.retention.inactive_years} ans</strong> seront
            anonymisés (nom, téléphone, e-mail supprimés), et les visites de plus de <strong>{modal.patch.transactions_years || d.retention.transactions_years} ans</strong> ne
            seront plus liées à un client. Les montants restent pour vos comptes. C'est irréversible.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={() => setModal(null)} className="rounded-lg border border-[#DCE3EE] px-4 py-2 text-[13.5px]">Annuler</button>
            <button type="button" onClick={async () => { if (await save({ retention: { inactive_years: d.retention.inactive_years, transactions_years: d.retention.transactions_years, ...modal.patch } }, 'Conservation activée.')) setModal(null); }}
                    className="rounded-lg px-4 py-2 text-[13.5px] font-medium text-white" style={{ background: BLUE }}>Activer</button>
          </div>
        </Modal>
      )}
      {modal?.type === 'erase' && (
        <Modal title="Supprimer ce client ?" onClose={() => setModal(null)}>
          <p className="text-[13.5px] leading-snug text-[#475569]">Toutes les données personnelles de <strong>{modal.client.name}</strong> seront supprimées
            (nom, contact, notifications, avis). Sa carte ne fonctionnera plus. C'est irréversible.</p>
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={() => setModal(null)} className="rounded-lg border border-[#DCE3EE] px-4 py-2 text-[13.5px]">Annuler</button>
            <button type="button" onClick={async () => {
              try { await ownerAPI.eraseCustomer(modal.client.id); setResults((r) => (r || []).filter((x) => x.id !== modal.client.id)); say('Client supprimé.'); setModal(null); }
              catch (e) { setErr(e?.response?.data?.detail || 'Suppression impossible.'); setModal(null); }
            }} className="rounded-lg bg-[#E11D48] px-4 py-2 text-[13.5px] font-medium text-white">Supprimer définitivement</button>
          </div>
        </Modal>
      )}
      {modal?.type === 'cookies' && (
        <Modal title="Cookies" onClose={() => setModal(null)}>
          <p className="text-[13.5px] leading-snug text-[#475569]">Votre page d'inscription et la carte de vos clients n'utilisent que le stockage
            nécessaire à leur fonctionnement : aucun cookie publicitaire, aucune mesure d'audience. Aucun bandeau d'acceptation n'est donc requis.</p>
          <label className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-[#EDF1F7] p-3">
            <span className="text-[13.5px] text-[#0B1C3F]">Afficher une note d'information sur la page d'inscription</span>
            <Switch on={d.cookies.notice} label="Note d'information" onChange={(v) => save({ cookie_notice: v }, 'Enregistré.')} />
          </label>
        </Modal>
      )}
      {modal?.type === 'policy' && (
        <Modal title="Politique de confidentialité" onClose={() => setModal(null)}>
          <p className="mb-3 text-[12.5px] text-[#64748B]">Le lien s'affiche à côté du consentement sur votre page d'inscription. Sans lien, la politique FidClic s'applique.</p>
          <fieldset disabled={!edit} className="m-0 space-y-3 border-0 p-0">
            <label className="block"><span className="mb-1 block text-[13px] text-[#0B1C3F]">Lien vers votre politique (https://…)</span>
              <input value={policy.url} onChange={(e) => setPolicy({ ...policy, url: e.target.value })} placeholder="https://moncommerce.fr/confidentialite"
                     className="h-10 w-full rounded-lg border border-[#DCE3EE] px-3 text-[13.5px] outline-none focus:border-[#2F6BFF]" /></label>
            <label className="block"><span className="mb-1 block text-[13px] text-[#0B1C3F]">Ou votre texte</span>
              <textarea value={policy.text} onChange={(e) => setPolicy({ ...policy, text: e.target.value })}
                        className="min-h-[140px] w-full rounded-lg border border-[#DCE3EE] px-3 py-2 text-[13px] outline-none focus:border-[#2F6BFF]" /></label>
          </fieldset>
          <div className="mt-3 flex items-center justify-between">
            <a href="https://fidclic.com/confidentialite" target="_blank" rel="noopener noreferrer" className="text-[12.5px] text-[#2F6BFF] underline">Politique FidClic</a>
            {edit && <button type="button" onClick={async () => { if (await save({ policy }, 'Politique enregistrée.')) setModal(null); }}
                             className="rounded-lg px-4 py-2 text-[13.5px] font-medium text-white" style={{ background: BLUE }}>Enregistrer</button>}
          </div>
        </Modal>
      )}
    </div>
  );
}
