import React, { useEffect, useState } from 'react';
import api from '../lib/api';
import { Sparkles, Save } from 'lucide-react';
import { C as C_PS } from './PageShell';

/**
 * Drop-in card for SettingsPage: configure the message + bonus points that
 * fire automatically when a new customer joins. Talks to the existing
 * `features/welcome_bonus.py` backend module via /api/owner/earn-rules.
 *
 * Self-contained — does not affect any other Settings card.
 */
const WelcomeBonusCard = () => {
  const [cfg, setCfg] = useState({
    welcome_bonus_points: 50,
    welcome_bonus_message: 'Welcome! Here are some bonus points to start.',
    welcome_bonus_only_first_visit: true,
    points_per_visit: 10,
    max_redemption_pct: 100,
    accrual_delay_minutes: 0,
    enabled: true,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get('/owner/earn-rules');
        if (r.data) setCfg((c) => ({ ...c, ...r.data }));
      } catch (_e) { /* fall back to defaults */ }
      finally { setLoading(false); }
    })();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.put('/owner/earn-rules', cfg);
      setSavedAt(new Date());
    } catch (e) {
      alert('Failed to save: ' + (e?.response?.data?.detail || e.message));
    } finally { setSaving(false); }
  };

  return (
    <div className="rounded-xl bg-white p-6 mt-6" style={{ border: `1px solid ${C_PS.hairline}` }}>
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: `${C_PS.lavender}1A`, color: C_PS.lavender }}>
          <Sparkles size={18} />
        </div>
        <div>
          <h2 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond', color: C_PS.inkDeep }}>
            Welcome message + bonus points
          </h2>
          <p className="text-sm mt-1" style={{ color: C_PS.inkMute }}>
            The first thing a new customer sees after they join. A friendly note + a credit of bonus points to start their loyalty journey on a high note.
            Available variables: <code>{'{first_name} {name} {business_name}'}</code>
          </p>
        </div>
      </div>

      {loading ? (
        <div className="py-8 text-center text-sm" style={{ color: C_PS.inkMute }}>Loading…</div>
      ) : (
        <>
          <label className="flex items-center gap-2 mb-4 cursor-pointer">
            <input
              type="checkbox"
              checked={!!cfg.enabled}
              onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
              className="w-4 h-4"
            />
            <span className="text-sm font-semibold" style={{ color: C_PS.inkDeep }}>
              {cfg.enabled ? 'Enabled — every new joiner receives this' : 'Disabled — new joiners receive nothing extra'}
            </span>
          </label>

          <div className={`space-y-4 ${cfg.enabled ? '' : 'opacity-50 pointer-events-none'}`}>
            <div>
              <label className="text-xs font-bold uppercase tracking-widest mb-1 block" style={{ color: C_PS.inkMute }}>
                Welcome message
              </label>
              <textarea
                rows={3}
                value={cfg.welcome_bonus_message}
                onChange={(e) => setCfg({ ...cfg, welcome_bonus_message: e.target.value })}
                placeholder="Bienvenue {first_name} ! 50 points pour bien commencer chez {business_name}."
                className="w-full border rounded-lg px-3 py-2 text-sm"
                style={{ borderColor: C_PS.hairline }}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-bold uppercase tracking-widest mb-1 block" style={{ color: C_PS.inkMute }}>
                  Bonus points to credit
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="number" min={0}
                    value={cfg.welcome_bonus_points}
                    onChange={(e) => setCfg({ ...cfg, welcome_bonus_points: parseInt(e.target.value || '0', 10) })}
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    style={{ borderColor: C_PS.hairline }}
                  />
                  <span className="text-xs font-semibold shrink-0" style={{ color: C_PS.inkMute }}>points</span>
                </div>
                <p className="text-[11px] mt-1" style={{ color: C_PS.inkMute }}>
                  Credited once, on the first claim. 0 = message only, no points.
                </p>
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-widest mb-1 block" style={{ color: C_PS.inkMute }}>
                  Eligibility
                </label>
                <label className="inline-flex items-center gap-2 mt-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!cfg.welcome_bonus_only_first_visit}
                    onChange={(e) => setCfg({ ...cfg, welcome_bonus_only_first_visit: e.target.checked })}
                    className="w-4 h-4"
                  />
                  <span style={{ color: C_PS.inkDeep }}>Only on first visit (recommended)</span>
                </label>
                <p className="text-[11px] mt-1" style={{ color: C_PS.inkMute }}>
                  Prevents the bonus from being claimed by long-time customers retrofitting the program.
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3 mt-6">
            <button type="button" onClick={save} disabled={saving}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-white font-semibold disabled:opacity-50"
              style={{ background: C_PS.terracotta }}>
              <Save size={14} /> {saving ? 'Saving…' : 'Save welcome rule'}
            </button>
            {savedAt && <span className="text-xs" style={{ color: C_PS.inkMute }}>Saved {savedAt.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</span>}
          </div>
        </>
      )}
    </div>
  );
};

export default WelcomeBonusCard;
