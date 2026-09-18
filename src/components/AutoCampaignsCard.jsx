import React, { useEffect, useState } from 'react';
import api from '../lib/api';
import { Cake, BellOff, Play, Save, Eye, Coffee, Smartphone, Send } from 'lucide-react';
import { C as C_PS } from './PageShell';
import PushNotificationPreviewModal from './PushNotificationPreviewModal';
import PhonePushPreview from './PhonePushPreview';

/**
 * Drop-in card for SettingsPage: configure auto-generated messages for
 * birthdays and inactive customers. Talks to features/auto_campaigns.py.
 *
 * "Run now (dry-run)" lets the owner preview exactly which customers would
 * be messaged and what they'd say, before any real send.
 */
const AutoCampaignsCard = () => {
  const [cfg, setCfg] = useState({
    birthday_enabled: true,
    birthday_title: '',
    birthday_message: '',
    birthday_bonus_points: 50,
    inactive_enabled: true,
    inactive_title: '',
    inactive_message: '',
    inactive_trigger_days: 0,
    inactive_cooldown_days: 30,
    almost_there_enabled: true,
    almost_there_title: '',
    almost_there_message: '',
    almost_there_visits_left: 1,
    almost_there_cooldown_days: 7,
  });
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(null);
  const [running, setRunning] = useState(null);   // 'birthdays' | 'inactive' | null
  const [previews, setPreviews] = useState(null);
  // PushNotificationPreviewModal state — confirm-before-send for every auto run
  const [confirmFor, setConfirmFor] = useState(null);  // { which, count, title, body }
  const [businessName, setBusinessName] = useState('Votre commerce');

  const load = async () => {
    try {
      const res = await api.get('/owner/auto-campaigns/config');
      setCfg(res.data);
    } catch (e) { console.error('auto-campaigns load failed', e); }
    // Get business name for the preview modal
    try {
      const settingsRes = await api.get('/owner/settings');
      setBusinessName(settingsRes.data?.name || 'Votre commerce');
    } catch (_e) { /* ignore */ }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.put('/owner/auto-campaigns/config', cfg);
      setSavedAt(new Date());
    } catch (e) {
      alert('Failed to save: ' + (e?.response?.data?.detail || e.message));
    } finally { setSaving(false); }
  };

  const ENDPOINTS = {
    birthdays:    '/owner/auto-campaigns/run-birthdays',
    inactive:     '/owner/auto-campaigns/run-inactive',
    almost_there: '/owner/auto-campaigns/run-almost-there',
  };

  const runDry = async (which) => {
    setRunning(which); setPreviews(null);
    try {
      const res = await api.post(ENDPOINTS[which], null, { params: { dry_run: true } });
      setPreviews({ which, ...res.data });
    } catch (e) {
      alert('Dry-run failed: ' + (e?.response?.data?.detail || e.message));
    } finally { setRunning(null); }
  };

  // Step 1 — open the preview/confirmation modal with the proposed message + recipient count.
  // Step 2 — when the owner clicks "Send" inside the modal, sendConfirmed() actually fires the run.
  const sendNow = async (which) => {
    setRunning(which);
    try {
      // Re-run as dry to get fresh recipient count + the canonical templated message
      const res = await api.post(ENDPOINTS[which], null, { params: { dry_run: true } });
      const samples = res.data?.samples || res.data?.previews || [];
      const firstSample = samples[0] || {};
      const count = res.data?.would_send ?? res.data?.count ?? samples.length;
      // Pull the title/body from the first sample so the owner sees the real templated text
      const title = firstSample.title || (which === 'birthdays' ? '🎂 Joyeux anniversaire !' : which === 'inactive' ? '👋 Vous nous manquez' : 'Plus qu\'une visite !');
      const body = firstSample.body || firstSample.message || '';
      setConfirmFor({ which, count, title, body });
    } catch (e) {
      alert('Échec de la préparation : ' + (e?.response?.data?.detail || e.message));
    } finally { setRunning(null); }
  };

  // Owner clicked Send inside the modal — fire the real auto-run for real this time.
  const sendConfirmed = async ({ title, body }) => {
    if (!confirmFor) return;
    const which = confirmFor.which;
    setRunning(which);
    try {
      const res = await api.post(ENDPOINTS[which], { title, body });
      alert(`✓ ${res.data.sent || 0} message${(res.data.sent || 0) === 1 ? '' : 's'} envoyé${(res.data.sent || 0) === 1 ? '' : 's'}.`);
      setPreviews(null);
    } catch (e) {
      alert('Échec de l\'envoi : ' + (e?.response?.data?.detail || e.message));
    } finally {
      setRunning(null);
      setConfirmFor(null);
    }
  };

  return (
    <div className="rounded-xl bg-white p-6 mt-6" style={{ border: `1px solid ${C_PS.hairline}` }}>
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: `${C_PS.terracotta}1A`, color: C_PS.terracotta }}>
          <Cake size={18} />
        </div>
        <div>
          <h2 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond', color: C_PS.inkDeep }}>
            Automatic messages
          </h2>
          <p className="text-sm mt-1" style={{ color: C_PS.inkMute }}>
            Birthday wishes and inactive-customer rescue messages — generated automatically from templates and your customer data.
            Available variables: <code>{'{first_name} {name} {business_name} {tier} {points} {visits}'}</code>
          </p>
        </div>
      </div>

      {/* Birthday block */}
      <Section
        title="Birthday wishes"
        enabled={cfg.birthday_enabled}
        onToggle={(v) => setCfg({ ...cfg, birthday_enabled: v })}
        icon={Cake}
      >
        <div className="grid md:grid-cols-[1fr_auto] gap-4 items-start">
          <div className="min-w-0 space-y-3">
            <Field label="Notification title" type="text"
              value={cfg.birthday_title}
              onChange={(v) => setCfg({ ...cfg, birthday_title: v })}
              hint="Use {first_name} and {business_name} as placeholders." />
            <Field label="Message body" type="textarea"
              value={cfg.birthday_message}
              onChange={(v) => setCfg({ ...cfg, birthday_message: v })} />
            <Field label="Bonus points to credit" suffix="points" type="number"
              value={cfg.birthday_bonus_points}
              onChange={(v) => setCfg({ ...cfg, birthday_bonus_points: parseInt(v || '0', 10) })}
              hint="0 = no bonus, just the message." />
          </div>
          <PhonePushPreview
            businessName="Your shop"
            title={cfg.birthday_title || 'Happy birthday! 🎂'}
            body={cfg.birthday_message || 'Our whole team wishes you a happy birthday. A treat is waiting for you!'}
            primaryColor={C_PS.terracotta}
            width={200}
            caption="Preview — birthday"
          />
        </div>
        <RunButtons which="birthdays" running={running} onDry={runDry} onSend={sendNow} disabled={!cfg.birthday_enabled} />
      </Section>

      {/* Inactive block */}
      <Section
        title="Inactive-customer rescue"
        enabled={cfg.inactive_enabled}
        onToggle={(v) => setCfg({ ...cfg, inactive_enabled: v })}
        icon={BellOff}
      >
        <div className="grid md:grid-cols-[1fr_auto] gap-4 items-start">
          <div className="min-w-0 space-y-3">
            <Field label="Notification title" type="text"
              value={cfg.inactive_title}
              onChange={(v) => setCfg({ ...cfg, inactive_title: v })}
              hint="Placeholders {first_name} and {business_name} work here too." />
            <Field label="Message body" type="textarea"
              value={cfg.inactive_message}
              onChange={(v) => setCfg({ ...cfg, inactive_message: v })} />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Trigger after silence of" suffix="days" type="number"
                value={cfg.inactive_trigger_days}
                onChange={(v) => setCfg({ ...cfg, inactive_trigger_days: parseInt(v || '0', 10) })}
                hint="0 = use the dormant threshold from your customer-status definition." />
              <Field label="Cool-down between sends" suffix="days" type="number"
                value={cfg.inactive_cooldown_days}
                onChange={(v) => setCfg({ ...cfg, inactive_cooldown_days: parseInt(v || '0', 10) })}
                hint="Don't message the same person more often than this." />
            </div>
          </div>
          <PhonePushPreview
            businessName="Your shop"
            title={cfg.inactive_title || "We've missed you!"}
            body={cfg.inactive_message || "It's been a while… Drop back in, a treat is waiting for you."}
            primaryColor={C_PS.terracotta}
            width={200}
            caption="Preview — inactive rescue"
          />
        </div>
        <RunButtons which="inactive" running={running} onDry={runDry} onSend={sendNow} disabled={!cfg.inactive_enabled} />
      </Section>

      {/* Almost-there block — nudge customers one visit away from the next reward */}
      <Section
        title="Almost there — one visit from a reward"
        enabled={cfg.almost_there_enabled}
        onToggle={(v) => setCfg({ ...cfg, almost_there_enabled: v })}
        icon={Coffee}
      >
        <div className="grid md:grid-cols-[1fr_auto] gap-4 items-start">
          <div className="min-w-0 space-y-3">
            <Field label="Notification title" type="text"
              value={cfg.almost_there_title}
              onChange={(v) => setCfg({ ...cfg, almost_there_title: v })}
              hint="Use {first_name}, {visits_left} as placeholders." />
            <Field label="Message body" type="textarea"
              value={cfg.almost_there_message}
              onChange={(v) => setCfg({ ...cfg, almost_there_message: v })} />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Trigger when this many visits remain" suffix="visit(s)" type="number"
                value={cfg.almost_there_visits_left}
                onChange={(v) => setCfg({ ...cfg, almost_there_visits_left: parseInt(v || '1', 10) })}
                hint="1 = 'one more visit and the reward is yours'." />
              <Field label="Cool-down between sends" suffix="days" type="number"
                value={cfg.almost_there_cooldown_days}
                onChange={(v) => setCfg({ ...cfg, almost_there_cooldown_days: parseInt(v || '0', 10) })}
                hint="Avoid spamming the same person on repeat cycles." />
            </div>
          </div>
          <PhonePushPreview
            businessName="Your shop"
            title={cfg.almost_there_title || 'Just one more visit! 🎁'}
            body={cfg.almost_there_message || 'One more visit and you unlock your reward. See you soon!'}
            primaryColor={C_PS.terracotta}
            width={200}
            caption="Preview — almost there"
          />
        </div>
        <RunButtons which="almost_there" running={running} onDry={runDry} onSend={sendNow} disabled={!cfg.almost_there_enabled} />
      </Section>

      <div className="flex items-center gap-3 mt-6">
        <button type="button" onClick={save} disabled={saving}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-white font-semibold disabled:opacity-50"
          style={{ background: C_PS.terracotta }}>
          <Save size={14} /> {saving ? 'Saving…' : 'Save configuration'}
        </button>
        {savedAt && <span className="text-xs" style={{ color: C_PS.inkMute }}>Saved {savedAt.toLocaleTimeString()}</span>}
      </div>

      {/* Twilio test bench — one-shot SMS to any number for end-to-end verification. */}
      <TwilioTestBench />

      {previews && (
        <div className="mt-5 pt-5 border-t" style={{ borderColor: C_PS.hairline }}>
          <p className="text-[10px] uppercase font-bold tracking-widest mb-2" style={{ color: C_PS.inkMute }}>
            Dry-run preview — {previews.which === 'birthdays' ? 'birthdays today' : 'inactive customers'}
          </p>
          <p className="text-sm mb-3" style={{ color: C_PS.inkDeep }}>
            <Eye size={14} className="inline mr-1" />
            {previews.found ?? previews.candidates ?? 0} candidate{((previews.found ?? previews.candidates ?? 0) === 1) ? '' : 's'} — {(previews.preview || []).length} would receive a message.
          </p>
          <div className="space-y-2 max-h-72 overflow-y-auto">
            {(previews.preview || []).map((p) => (
              <div key={p.customer_id} className="rounded-lg p-3 text-sm" style={{ background: 'var(--flc-paper2, #F5F4F1)' }}>
                <p className="font-semibold" style={{ color: C_PS.inkDeep }}>{p.name}</p>
                <p style={{ color: C_PS.inkSoft }}>{p.body}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Confirm-before-send modal (item #5 + #6).
          MUST be inside AutoCampaignsCard so confirmFor / setConfirmFor /
          sendConfirmed / businessName are in scope. Was previously placed
          inside TwilioTestBench by mistake — caused 'confirmFor is not
          defined' at runtime. */}
      <PushNotificationPreviewModal
        open={!!confirmFor}
        onClose={() => setConfirmFor(null)}
        onConfirm={sendConfirmed}
        businessName={businessName}
        primaryColor={C_PS.terracotta}
        recipientCount={confirmFor?.count ?? 0}
        trigger={
          confirmFor?.which === 'birthdays' ? 'Anniversaires automatiques'
          : confirmFor?.which === 'inactive' ? 'Relance des clients endormis'
          : confirmFor?.which === 'almost_there' ? 'Plus qu\'une visite — récompense'
          : 'Campagne automatique'
        }
        defaultTitle={confirmFor?.title || ''}
        defaultBody={confirmFor?.body || ''}
        editable={true}
      />
    </div>
  );
};

const Section = ({ title, enabled, onToggle, icon: Icon, children }) => (
  <div className="mb-5 pb-5 last:mb-0 last:pb-0 last:border-b-0 border-b" style={{ borderColor: C_PS.hairline }}>
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
        <Icon size={16} className="text-[#B85C38]" />
        <h3 className="font-bold" style={{ color: C_PS.inkDeep }}>{title}</h3>
      </div>
      <label className="inline-flex items-center gap-2 cursor-pointer text-xs font-semibold">
        <input type="checkbox" checked={enabled} onChange={(e) => onToggle(e.target.checked)} className="w-4 h-4" />
        <span style={{ color: C_PS.inkMute }}>{enabled ? 'Enabled' : 'Disabled'}</span>
      </label>
    </div>
    <div className={`space-y-3 ${enabled ? '' : 'opacity-50 pointer-events-none'}`}>{children}</div>
  </div>
);

const Field = ({ label, value, onChange, type = 'text', suffix, hint }) => (
  <div>
    <label className="text-xs font-bold uppercase tracking-widest mb-1 block" style={{ color: C_PS.inkMute }}>{label}</label>
    {type === 'textarea' ? (
      <textarea rows={3} value={value || ''} onChange={(e) => onChange(e.target.value)}
        className="w-full border rounded-lg px-3 py-2 text-sm" style={{ borderColor: C_PS.hairline }} />
    ) : (
      <div className="flex items-center gap-2">
        <input type={type} value={value} onChange={(e) => onChange(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm" style={{ borderColor: C_PS.hairline }} />
        {suffix && <span className="text-xs font-semibold shrink-0" style={{ color: C_PS.inkMute }}>{suffix}</span>}
      </div>
    )}
    {hint && <p className="text-[11px] mt-1" style={{ color: C_PS.inkMute }}>{hint}</p>}
  </div>
);

const RunButtons = ({ which, running, onDry, onSend, disabled }) => (
  <div className="flex gap-2 pt-1">
    <button type="button" onClick={() => onDry(which)} disabled={disabled || !!running}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-40"
      style={{ background: 'var(--flc-card, #FFFFFF)', color: C_PS.terracotta, border: `1px solid ${C_PS.terracotta}55` }}>
      <Eye size={12} /> {running === which ? 'Running…' : 'Preview (dry-run)'}
    </button>
    <button type="button" onClick={() => onSend(which)} disabled={disabled || !!running}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white disabled:opacity-40"
      style={{ background: C_PS.terracotta }}>
      <Play size={12} /> Send now
    </button>
  </div>
);

/* Test-bench widget: send a single real SMS via Twilio to any number,
   so the owner can verify their TWILIO_* env vars are wired correctly
   on Render before relying on auto-campaigns. */
const TwilioTestBench = () => {
  const [phone, setPhone] = React.useState('');
  const [msg, setMsg] = React.useState('Test SMS from FidClic — Twilio is wired correctly! 🎉');
  const [busy, setBusy] = React.useState(false);
  const [last, setLast] = React.useState(null);

  const send = async () => {
    if (!phone.trim()) { alert('Enter a phone number first.'); return; }
    if (!window.confirm(`Send a real SMS to ${phone} now?`)) return;
    setBusy(true); setLast(null);
    try {
      const res = await api.post('/owner/auto-campaigns/test-sms', { to: phone, message: msg });
      setLast(res.data);
    } catch (e) {
      setLast({ sent: false, error: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  return (
    <div className="mt-5 pt-5 border-t" style={{ borderColor: C_PS.hairline }}>
      <div className="flex items-start gap-2 mb-3">
        <Smartphone size={16} className="text-[#B85C38] mt-0.5" />
        <div className="flex-1">
          <p className="text-sm font-bold" style={{ color: C_PS.inkDeep }}>Test SMS delivery</p>
          <p className="text-xs" style={{ color: C_PS.inkMute }}>
            Send a single real SMS to verify your Twilio credentials work.
            Set <code>TWILIO_ACCOUNT_SID</code>, <code>TWILIO_AUTH_TOKEN</code>, <code>TWILIO_FROM_NUMBER</code> on
            Render first. Without those env vars this just no-ops.
          </p>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        <input
          type="tel" placeholder="+33612345678 (E.164)"
          value={phone} onChange={(e) => setPhone(e.target.value)}
          className="border rounded-lg px-3 py-2 text-sm" style={{ borderColor: C_PS.hairline }}
        />
        <input
          type="text" placeholder="Message" value={msg}
          onChange={(e) => setMsg(e.target.value)}
          className="md:col-span-2 border rounded-lg px-3 py-2 text-sm" style={{ borderColor: C_PS.hairline }}
        />
      </div>
      <button type="button" onClick={send} disabled={busy}
        className="mt-2 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-white text-xs font-semibold disabled:opacity-50"
        style={{ background: C_PS.terracotta }}>
        <Send size={12} /> {busy ? 'Sending…' : 'Send test SMS'}
      </button>
      {last && (
        <div className="mt-3 rounded-lg p-3 text-xs"
          style={{
            background: last.sent ? '#ECFDF5' : '#FEF3C7',
            color: last.sent ? '#065F46' : '#92400E',
          }}>
          {last.sent
            ? <>✓ Sent — Twilio SID <code>{last.sid}</code> to <code>{last.to}</code> · status {last.status}</>
            : <>⚠ {last.error || 'Failed'}{last.hint ? ' — ' + last.hint : ''}</>}
        </div>
      )}
    </div>
  );
};

export default AutoCampaignsCard;
