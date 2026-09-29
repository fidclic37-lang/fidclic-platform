import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Gift, Cake, Star, Target, Check, Loader2, ExternalLink, Zap } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * Messages automatiques — the four that go out without approval
 * (features/auto_messages.py): Bienvenue at sign-up, Anniversaire on the day,
 * Avis Google after a scan and « Récompense proche » two visits from the
 * reward. The owner sets them; everyone else reads.
 */
const inputCls = 'w-full rounded-xl border border-[#E6EEFB] bg-white px-3 py-2.5 text-[13px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF] disabled:bg-[#F8FAFF]';

const Switch = ({ on, onChange }) => (
  <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)}
          className={`relative h-6 w-11 shrink-0 rounded-full transition ${on ? 'bg-[#2F6BFF]' : 'bg-[#DFE6F1]'}`}>
    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? 'left-[22px]' : 'left-0.5'}`} />
  </button>
);

const Box = ({ icon: Icon, tone, title, when, on, children }) => (
  <section className="flex flex-col rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
    <header className="mb-3 flex items-start gap-3">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: `${tone}1A`, color: tone }}><Icon size={17} /></span>
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] font-bold text-[#0B1C3F]">{title}</p>
        <p className="text-[11.5px] leading-snug text-[#94A3B8]">{when}</p>
      </div>
      <span className="shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold"
            style={on ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#EEF2F8', color: '#64748B' }}>
        {on ? 'Actif' : 'Désactivé'}
      </span>
    </header>
    <div className="flex-1 space-y-2.5">{children}</div>
  </section>
);

const Label = ({ children }) => <span className="mb-1 block text-[11.5px] font-semibold text-[#334155]">{children}</span>;

export default function AutoMessagesPanel({ canEdit, onEditScenario }) {
  const [d, setD] = useState(null);
  const [g, setG] = useState(null);
  const [n, setN] = useState(null);
  const [link, setLink] = useState('');
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');

  const apply = (data) => { setD(data); setG(data.google_review); setN(data.near_reward); setLink(data.google_link?.url || ''); };
  useEffect(() => {
    ownerAPI.autoMessages().then(({ data }) => apply(data)).catch(() => setErr('Messages automatiques indisponibles.'));
  }, []);

  const save = async (key, body) => {
    setBusy(key); setErr(''); setMsg('');
    try { const { data } = await ownerAPI.saveAutoMessages({ [key]: body }); apply(data); setMsg('Enregistré.'); }
    catch (e) { setErr(e?.response?.data?.detail || "L'enregistrement n'a pas abouti."); }
    finally { setBusy(''); }
  };
  const saveLink = async () => {
    setBusy('link'); setErr(''); setMsg('');
    try {
      await ownerAPI.setGoogleReview({ url: link.trim(), enabled: !!link.trim() });
      const { data } = await ownerAPI.autoMessages(); apply(data); setMsg('Lien Google enregistré.');
    } catch (e) { setErr(e?.response?.data?.detail || "Le lien n'a pas pu être enregistré."); }
    finally { setBusy(''); }
  };

  if (!d) return err ? <p className="mb-4 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{err}</p> : null;

  const SaveBtn = ({ k, onClick }) => canEdit && (
    <button type="button" onClick={onClick} disabled={!!busy}
            className="inline-flex items-center gap-1.5 rounded-xl bg-[#2F6BFF] px-3 py-2 text-[12px] font-semibold text-white disabled:opacity-60">
      {busy === k ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Enregistrer
    </button>
  );

  return (
    <div className="mb-5">
      <div className="mb-3 flex items-center gap-2">
        <Zap size={16} className="text-[#2F6BFF]" />
        <h2 className="text-[15px] font-bold text-[#0B1C3F]">Messages automatiques</h2>
        <span className="text-[12px] text-[#64748B]">— envoyés sans validation. Tous les autres scénarios passent par « À valider ».</span>
      </div>
      {msg && <p className="mb-3 rounded-xl bg-[#E7F7EE] px-4 py-2 text-[12.5px] text-[#0F8B58]">{msg}</p>}
      {err && <p className="mb-3 rounded-xl bg-[#FEECEC] px-4 py-2 text-[12.5px] text-[#C0392B]">{err}</p>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Box icon={Gift} tone="#2F6BFF" title="Bienvenue" when="À l'inscription"
             on={d.welcome.enabled && (!!d.welcome.message || d.welcome.points > 0)}>
          <p className="rounded-xl bg-[#F4F7FC] px-3 py-2 text-[12px] leading-snug text-[#475569]">
            {d.welcome.message || 'Aucun message pour l\'instant.'}
            {d.welcome.points > 0 && <strong className="mt-1 block text-[#0B1C3F]">+{d.welcome.points} points offerts</strong>}
          </p>
          <Link to="/dashboard/card" className="inline-flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF] hover:underline">
            Modifier sur la Carte de fidélité <ExternalLink size={12} />
          </Link>
        </Box>

        <Box icon={Cake} tone="#F43F5E" title="Anniversaire" when="Le jour de l'anniversaire" on={d.birthday.enabled}>
          <p className="rounded-xl bg-[#F4F7FC] px-3 py-2 text-[12px] leading-snug text-[#475569]">
            <strong className="block text-[#0B1C3F]">{d.birthday.title}</strong>{d.birthday.body}
          </p>
          {canEdit && d.birthday.id && (
            <button type="button" onClick={() => onEditScenario?.(d.birthday.id)} className="text-[12px] font-semibold text-[#2F6BFF] hover:underline">
              Modifier le message
            </button>
          )}
        </Box>

        <Box icon={Star} tone="#F59E0B" title="Avis Google" when="Après un scan en caisse" on={g.enabled && d.google_link.on}>
          <fieldset disabled={!canEdit} className="m-0 min-w-0 space-y-2.5 border-0 p-0">
            <div>
              <Label>Lien de votre page d'avis Google</Label>
              <div className="flex gap-2">
                <input className={inputCls} value={link} placeholder="https://g.page/r/…/review" onChange={(e) => setLink(e.target.value)} />
                {canEdit && link.trim() !== (d.google_link.url || '') && (
                  <button type="button" onClick={saveLink} disabled={!!busy}
                          className="shrink-0 rounded-xl border border-[#2F6BFF] px-3 text-[12px] font-semibold text-[#2F6BFF]">OK</button>
                )}
              </div>
              {!d.google_link.on && <p className="mt-1 text-[11px] text-[#B45309]">Sans lien, ce message n'est pas envoyé.</p>}
            </div>
            <div className="flex items-center justify-between"><span className="text-[12px] text-[#334155]">Activé</span>
              <Switch on={!!g.enabled} onChange={(v) => setG({ ...g, enabled: v })} /></div>
            <div>
              <Label>Fréquence pour un même client</Label>
              <select className={inputCls} value={g.frequency} onChange={(e) => setG({ ...g, frequency: e.target.value })}>
                <option value="every_scan">À chaque scan</option>
                <option value="days">Au plus une fois tous les N jours</option>
                <option value="once">Une seule fois</option>
              </select>
            </div>
            {g.frequency === 'days' && (
              <div><Label>Nombre de jours</Label>
                <input type="number" min={1} max={365} className={inputCls} value={g.days}
                       onChange={(e) => setG({ ...g, days: Math.max(1, Math.min(365, Number(e.target.value) || 1)) })} /></div>
            )}
            <div className="flex items-center justify-between gap-2"><span className="text-[12px] leading-snug text-[#334155]">Ne plus demander après un clic sur le lien</span>
              <Switch on={!!g.stop_after_click} onChange={(v) => setG({ ...g, stop_after_click: v })} /></div>
            <div><Label>Titre</Label><input className={inputCls} maxLength={120} value={g.title} onChange={(e) => setG({ ...g, title: e.target.value })} /></div>
            <div><Label>Message</Label><textarea className={`${inputCls} min-h-[64px] resize-y`} maxLength={400} value={g.body}
                                                 onChange={(e) => setG({ ...g, body: e.target.value })} /></div>
          </fieldset>
          <SaveBtn k="google_review" onClick={() => save('google_review', {
            enabled: g.enabled, frequency: g.frequency, days: g.days, stop_after_click: g.stop_after_click, title: g.title, body: g.body })} />
        </Box>

        <Box icon={Target} tone="#8B5CF6" title="Récompense proche" when={`Quand il manque ${n.visits_left} visite${n.visits_left > 1 ? 's' : ''}`} on={n.enabled}>
          <fieldset disabled={!canEdit} className="m-0 min-w-0 space-y-2.5 border-0 p-0">
            <div className="flex items-center justify-between"><span className="text-[12px] text-[#334155]">Activé</span>
              <Switch on={!!n.enabled} onChange={(v) => setN({ ...n, enabled: v })} /></div>
            <div>
              <Label>Visites restantes avant la récompense</Label>
              <select className={inputCls} value={n.visits_left} onChange={(e) => setN({ ...n, visits_left: Number(e.target.value) })}>
                {[1, 2, 3, 4, 5].map((k) => <option key={k} value={k}>{k} visite{k > 1 ? 's' : ''}</option>)}
              </select>
              <p className="mt-1 text-[11px] leading-snug text-[#94A3B8]">Carte à points : compté au rythme moyen de chaque client.</p>
            </div>
            <div><Label>Titre</Label><input className={inputCls} maxLength={120} value={n.title} onChange={(e) => setN({ ...n, title: e.target.value })} /></div>
            <div><Label>Message</Label><textarea className={`${inputCls} min-h-[64px] resize-y`} maxLength={400} value={n.body}
                                                 onChange={(e) => setN({ ...n, body: e.target.value })} />
              <p className="mt-1 text-[11px] text-[#94A3B8]">{'{first_name}, {visits_left}, {reward} et {business_name} sont remplacés.'}</p></div>
          </fieldset>
          <SaveBtn k="near_reward" onClick={() => save('near_reward', {
            enabled: n.enabled, visits_left: n.visits_left, title: n.title, body: n.body })} />
        </Box>
      </div>
    </div>
  );
}
