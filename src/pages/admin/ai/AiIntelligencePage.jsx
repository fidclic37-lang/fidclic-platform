import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Search, Send, RotateCw, Lightbulb, ChevronRight, ArrowRight, Download, Bookmark, Loader2, ShieldAlert, Gauge, Crown, Layers,
  Megaphone, Clock, GitCompare, Target, MessageCircleQuestion,
} from 'lucide-react';
import { adminAPI } from '../../../lib/api';
import { Breadcrumb, Loading, Modal, useToast, downloadBlob, BLUE, inputCls } from '../../crm/ui';
import { RangePicker, useRange } from '../securite/shared';
import { Robot, ResultTable, ResultCharts, AiTabs } from './shared';

/* Super admin › FIDCLIC AI Intelligence — built to the approved mockup.
   Answers come from features/admin_ai.py: exact figures from the platform's
   data; the language model only understands free questions. */

const QUICK_ICON = { risque: ShieldAlert, limite: Gauge, upgrade: Crown, secteurs: Layers, sans_campagne: Megaphone, inactifs: Clock,
  comparaison: GitCompare, recommandations: Target };
const CHIP_TONE = ['#8B5CF6', '#8B5CF6', '#2F6BFF', '#2F6BFF', '#F59E0B', '#10B981', '#8B5CF6', '#2F6BFF'];
const time = (iso) => { const d = new Date(iso); return `${d.toDateString() === new Date().toDateString() ? "Aujourd'hui" : d.toLocaleDateString('fr-FR')} ${d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`; };

export default function AiIntelligencePage() {
  const [range, setRange] = useRange();
  const [meta, setMeta] = useState(null);
  const [q, setQ] = useState('');
  const [thread, setThread] = useState([]);
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);
  const [saving, setSaving] = useState(null);
  const [say, toast] = useToast();
  const top = useRef(null);

  useEffect(() => { adminAPI.aiPage().then(({ data }) => setMeta(data)).catch(() => setMeta({ analyses: [], suggestions: [], first_name: '' })); }, []);

  const push = (item) => { setThread((t) => [item, ...t.filter((x) => x.id !== item.id)].slice(0, 12)); setTimeout(() => top.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60); };
  const ask = useCallback(async (question) => {
    const text = (question || '').trim();
    if (!text || busy) return;
    setBusy(true);
    const id = `${Date.now()}`;
    try { const { data } = await adminAPI.aiAsk(text, range); push({ id, asked: new Date().toISOString(), question: text, res: data }); setQ(''); }
    catch (e) { say(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : "L'analyse n'a pas pu être faite."); }
    setBusy(false);
  }, [busy, range]); // eslint-disable-line react-hooks/exhaustive-deps
  const quick = async (key, question) => {
    if (busy) return;
    setBusy(true);
    try { const { data } = await adminAPI.aiAnalysis(key, { ...range, question }); push({ id: `${Date.now()}`, asked: new Date().toISOString(), question: data.question, res: data }); }
    catch (e) { say("L'analyse n'a pas pu être faite."); }
    setBusy(false);
  };
  const refresh = async () => {
    if (!thread.length || busy) return;
    const last = thread[0];
    setBusy(true);
    try {
      const { data } = last.res.key in (QUICK_ICON) ? await adminAPI.aiAnalysis(last.res.key, { ...range, question: last.question }) : await adminAPI.aiAsk(last.question, range);
      setThread((t) => [{ ...last, res: data, asked: new Date().toISOString() }, ...t.slice(1)]);
      say('Données rafraîchies.');
    } catch (e) { say('Rafraîchissement impossible.'); }
    setBusy(false);
  };

  if (!meta) return <Loading />;
  const chips = (more ? meta.suggestions : meta.suggestions.slice(0, 8));
  return (
    <div className="crm">
      <header className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', '/admin'], ['FIDCLIC AI']]} />
          <h1 className="text-[30px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">FIDCLIC AI Intelligence</h1>
          <p className="text-[15px] text-[#475569]">Votre assistant de pilotage pour analyser, comprendre et agir avec vos données réelles.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={refresh} disabled={!thread.length || busy} className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF] disabled:opacity-50"><RotateCw size={16} className={busy ? 'animate-spin' : ''} /> Rafraîchir les données</button>
          <RangePicker value={range} onChange={setRange} />
        </div>
      </header>
      <AiTabs />

      <div className="grid gap-4 xl:grid-cols-[1fr_300px]">
        <section className="rounded-2xl border border-[#EDF1F7] bg-white p-5 shadow-[0_1px_2px_rgba(11,28,63,.03)]">
          <div className="flex flex-wrap items-center gap-4 border-b border-[#EEF2F8] pb-4">
            <Robot size={110} />
            <div className="min-w-0 flex-1">
              <h2 className="text-[24px] font-bold text-[#0B1C3F]">Bonjour {meta.first_name || ''} !</h2>
              <p className="text-[14px] leading-relaxed text-[#475569]">Je suis votre assistant IA. Je peux analyser toutes les données de votre plateforme FIDCLIC et vous aider à identifier des opportunités, des risques et des actions concrètes.</p>
            </div>
          </div>
          <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="relative mt-4">
            <Search size={17} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={500} placeholder="Posez votre question sur vos données…"
                   className="h-12 w-full rounded-xl border border-[#DCE3EE] bg-white pl-11 pr-14 text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
            <button type="submit" disabled={!q.trim() || busy} aria-label="Envoyer" className="absolute right-1.5 top-1/2 grid h-9 w-10 -translate-y-1/2 place-items-center rounded-lg text-white disabled:opacity-50" style={{ background: BLUE }}>
              {busy ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}</button>
          </form>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {chips.map((s, i) => (
              <button key={s} type="button" onClick={() => ask(s)} disabled={busy} className="flex items-start gap-2 rounded-xl border border-[#E6EEFB] bg-[#FAFCFF] px-3 py-2.5 text-left text-[12.5px] leading-snug text-[#334155] hover:border-[#2F6BFF] disabled:opacity-60">
                <MessageCircleQuestion size={15} className="mt-0.5 shrink-0" style={{ color: CHIP_TONE[i % CHIP_TONE.length] }} /> {s}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => setMore((v) => !v)} className="mt-2 inline-flex items-center gap-1 text-[12.5px] font-medium text-[#2F6BFF]">{more ? "Moins d'exemples" : "Voir plus d'exemples"} <ArrowRight size={13} /></button>
          {!meta.llm && <p className="mt-2 text-[11.5px] text-[#94A3B8]">Les questions sont comprises par leurs mots-clés ; branchez un modèle IA (variable d'environnement) pour les questions libres.</p>}
        </section>

        <section className="rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)]">
          <h2 className="mb-2 flex items-center gap-2 text-[15px] font-bold text-[#0B1C3F]"><Lightbulb size={18} className="text-[#2F6BFF]" /> Analyses rapides</h2>
          <ul className="space-y-1.5">
            {meta.analyses.map((a) => { const I = QUICK_ICON[a.key] || Target; return (
              <li key={a.key}><button type="button" onClick={() => quick(a.key, a.question)} disabled={busy} className="flex w-full items-center gap-2.5 rounded-lg border border-[#EEF2F8] px-3 py-2.5 text-left text-[13px] text-[#334155] hover:border-[#2F6BFF] disabled:opacity-60">
                <I size={16} className="shrink-0 text-[#2F6BFF]" /><span className="flex-1">{a.label}</span><ChevronRight size={15} className="text-[#94A3B8]" /></button></li>); })}
          </ul>
        </section>
      </div>

      <div ref={top} className="scroll-mt-4" />
      {busy && !thread.length && <p className="mt-4 text-center text-[13px] text-[#64748B]"><Loader2 size={15} className="mr-1 inline animate-spin" /> Analyse de vos données…</p>}
      {thread.map((it) => (
        <div key={it.id} className="mt-4 space-y-4">
          <div className="flex items-start gap-3 rounded-2xl border border-[#EDF1F7] bg-white p-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#2F6BFF] text-[14px] font-semibold text-white">{(meta.first_name || 'S')[0]}</span>
            <div className="rounded-xl bg-[#F4F8FF] px-3 py-2"><p className="text-[14px] text-[#0B1C3F]">{it.question}</p><p className="text-[11.5px] text-[#94A3B8]">{time(it.asked)}</p></div>
          </div>
          <section className="rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)]">
            <div className="mb-3 flex flex-wrap items-start gap-3">
              <Robot size={44} />
              <div className="min-w-0 flex-1">
                <p className="text-[15px] font-semibold text-[#0B1C3F]">{it.res.headline}</p>
                {it.res.detail && <p className="text-[13px] text-[#64748B]">{it.res.detail}</p>}
                {it.res.suggestions && <div className="mt-2 flex flex-wrap gap-2">{it.res.suggestions.map((s) => <button key={s} type="button" onClick={() => ask(s)} className="rounded-lg border border-[#DCE3EE] px-2.5 py-1 text-[12px] text-[#2F6BFF]">{s}</button>)}</div>}
              </div>
              {it.res.key in QUICK_ICON && (
                <span className="flex gap-2">
                  <button type="button" onClick={() => setSaving(it)} className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-[#DCE3EE] bg-white px-3 text-[13px] text-[#475569]"><Bookmark size={15} /> Sauvegarder</button>
                  {it.res.rows?.length > 0 && (
                    <button type="button" onClick={() => downloadBlob(adminAPI.aiExport(it.res.key, { ...range, question: it.question }), `fidclic-ai-${it.res.key}.csv`)}
                            className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-[#2F6BFF] bg-white px-3 text-[13px] font-medium text-[#2F6BFF]"><Download size={15} /> Exporter la liste (CSV)</button>
                  )}
                </span>
              )}
            </div>
            <ResultTable res={it.res} onOpen={(key) => quick(key)} />
          </section>
          <ResultCharts charts={it.res.charts} />
        </div>
      ))}
      {toast}
      {saving && <SaveModal it={saving} range={range} onClose={() => setSaving(null)} onDone={() => { setSaving(null); say('Analyse sauvegardée — retrouvez-la dans « Analyses sauvegardées ».'); }} />}
    </div>
  );
}

function SaveModal({ it, range, onClose, onDone }) {
  const days = Math.max(1, Math.round((new Date(range.to) - new Date(range.from)) / 86400000) + 1);
  const [title, setTitle] = useState(it.res.title);
  const [err, setErr] = useState('');
  const save = async () => {
    try { await adminAPI.aiSave({ key: it.res.key, question: it.question, title, days: Math.min(366, days) }); onDone(); }
    catch (e) { setErr(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Enregistrement impossible.'); }
  };
  return (
    <Modal title="Sauvegarder l'analyse" onClose={onClose}>
      <label className="block text-[13px]"><span className="mb-1 block text-[11.5px] text-[#64748B]">Nom</span><input className={inputCls} value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} /></label>
      <p className="mt-2 text-[12.5px] text-[#64748B]">Elle sera recalculée sur les {days} derniers jours à chaque ouverture, et peut être envoyée par email (« Rapports automatiques »).</p>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={!title.trim()} onClick={save} className="mt-3 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Sauvegarder</button>
    </Modal>
  );
}
