/**
 * BusinessHoursCard — owner-editable opening rhythm + closures.
 *
 * Three independent sub-sections, each with its own save:
 *   1. Weekly schedule    — Mon-Sun open/closed + hours
 *   2. French holidays    — auto-listed for next 24 months, owner ticks closures
 *   3. Annual closures    — free-form date ranges (vacances)
 *
 * Backend: features/business_hours.py
 *   GET  /api/owner/settings/hours
 *   PUT  /api/owner/settings/hours/weekly
 *   PUT  /api/owner/settings/hours/holidays
 *   PUT  /api/owner/settings/hours/annual
 */
import React, { useEffect, useState } from 'react';
import api from '../lib/api';
import { Calendar, Clock, Save, Plus, Trash2, Check } from 'lucide-react';
import { C as C_PS } from './PageShell';

const DAY_LABELS = {
  monday: 'Lundi', tuesday: 'Mardi', wednesday: 'Mercredi', thursday: 'Jeudi',
  friday: 'Vendredi', saturday: 'Samedi', sunday: 'Dimanche',
};

const BusinessHoursCard = () => {
  const [loading, setLoading] = useState(true);
  const [weekly, setWeekly] = useState([]);
  const [holidays, setHolidays] = useState([]);     // [{ key, name, date, weekday, closed }]
  const [annual, setAnnual] = useState([]);         // [{ start, end, label }]
  const [savingPart, setSavingPart] = useState(null); // 'weekly' | 'holidays' | 'annual'
  const [savedAt, setSavedAt] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get('/owner/settings/hours');
      setWeekly(res.data?.weekly_schedule || []);
      setHolidays(res.data?.upcoming_holidays || []);
      setAnnual(res.data?.annual_closures || []);
    } catch (e) {
      console.error('hours load failed', e);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  /* ─── Weekly ───────────────────────────────────────────── */
  const updateDay = (i, patch) => {
    setWeekly((curr) => curr.map((d, idx) => (idx === i ? { ...d, ...patch } : d)));
  };
  const saveWeekly = async () => {
    setSavingPart('weekly');
    try {
      await api.put('/owner/settings/hours/weekly', { weekly_schedule: weekly });
      setSavedAt(new Date());
    } catch (e) {
      alert('Échec : ' + (e?.response?.data?.detail || e.message));
    } finally {
      setSavingPart(null);
    }
  };

  /* ─── Holidays ─────────────────────────────────────────── */
  const toggleHoliday = (h) => {
    setHolidays((curr) => curr.map((x) => (x.date === h.date ? { ...x, closed: !x.closed } : x)));
  };
  const saveHolidays = async () => {
    setSavingPart('holidays');
    try {
      const closures = {};
      holidays.forEach((h) => { if (h.closed) closures[h.date] = true; });
      await api.put('/owner/settings/hours/holidays', { holiday_closures: closures });
      setSavedAt(new Date());
    } catch (e) {
      alert('Échec : ' + (e?.response?.data?.detail || e.message));
    } finally {
      setSavingPart(null);
    }
  };

  /* ─── Annual ───────────────────────────────────────────── */
  const addRange = () => {
    const today = new Date().toISOString().slice(0, 10);
    setAnnual([...annual, { start: today, end: today, label: 'Vacances' }]);
  };
  const updateRange = (i, patch) => {
    setAnnual((curr) => curr.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  };
  const removeRange = (i) => setAnnual(annual.filter((_, idx) => idx !== i));
  const saveAnnual = async () => {
    setSavingPart('annual');
    try {
      await api.put('/owner/settings/hours/annual', { annual_closures: annual });
      setSavedAt(new Date());
    } catch (e) {
      alert('Échec : ' + (e?.response?.data?.detail || e.message));
    } finally {
      setSavingPart(null);
    }
  };

  if (loading) {
    return (
      <div key="loading" className="rounded-xl bg-white p-6 mt-6" style={{ border: `1px solid ${C_PS.hairline}` }}>
        <p className="text-sm" style={{ color: C_PS.inkMute }}>Chargement des horaires…</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-white p-6 mt-6 space-y-8" style={{ border: `1px solid ${C_PS.hairline}` }}>
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
             style={{ background: `${C_PS.terracotta}1A`, color: C_PS.terracotta }}>
          <Clock size={18} />
        </div>
        <div>
          <h2 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond', color: C_PS.inkDeep }}>
            Horaires &amp; jours fériés
          </h2>
          <p className="text-sm mt-1" style={{ color: C_PS.inkMute }}>
            Définissez vos horaires hebdomadaires, vos jours de fermeture sur les jours fériés
            français, et vos vacances annuelles. <b>FidClic ne déclenche aucune notification
            « venez aujourd'hui » un jour où vous êtes fermé.</b>
          </p>
        </div>
      </div>

      {/* ─── 1. WEEKLY ────────────────────────────────────── */}
      <section>
        <h3 className="text-base font-bold mb-3" style={{ color: C_PS.inkDeep, fontFamily: 'Cormorant Garamond' }}>
          1 · Horaires de la semaine
        </h3>
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: C_PS.hairline }}>
          <div className="grid grid-cols-12 gap-2 px-3 py-2 text-[10px] font-bold uppercase tracking-widest"
               style={{ color: C_PS.inkMute, background: 'var(--flc-paper2, #FAFAF8)', borderBottom: `1px solid ${C_PS.hairline}` }}>
            <span className="col-span-3">Jour</span>
            <span className="col-span-3">Ouverture</span>
            <span className="col-span-3">Fermeture</span>
            <span className="col-span-3 text-right">Statut</span>
          </div>
          {weekly.map((d, i) => (
            <div key={d.day} className="grid grid-cols-12 gap-2 px-3 py-2 items-center"
                 style={{ borderBottom: i < weekly.length - 1 ? `1px solid ${C_PS.hairline}` : 'none',
                          background: d.closed ? 'color-mix(in srgb, var(--flc-accent, #C73E2C) 12%, var(--flc-card, #FFFFFF))' : 'var(--flc-card, #FFFFFF)' }}>
              <span className="col-span-3 text-sm font-bold" style={{ color: C_PS.inkDeep }}>
                {DAY_LABELS[d.day] || d.day}
              </span>
              <input
                type="time"
                value={d.open_from || '07:00'}
                disabled={d.closed}
                onChange={(e) => updateDay(i, { open_from: e.target.value })}
                className="col-span-3 border rounded px-2 py-1 text-sm disabled:opacity-50"
                style={{ borderColor: C_PS.hairline }}
              />
              <input
                type="time"
                value={d.open_to || '19:00'}
                disabled={d.closed}
                onChange={(e) => updateDay(i, { open_to: e.target.value })}
                className="col-span-3 border rounded px-2 py-1 text-sm disabled:opacity-50"
                style={{ borderColor: C_PS.hairline }}
              />
              <button
                type="button"
                onClick={() => updateDay(i, { closed: !d.closed })}
                className="col-span-3 text-xs font-bold py-1.5 rounded-full transition"
                style={{
                  background: d.closed ? '#B85C38' : '#E5F0DC',
                  color: d.closed ? 'white' : '#2d5016',
                  border: `1px solid ${d.closed ? '#B85C38' : '#6FA89C55'}`,
                }}
              >
                {d.closed ? 'FERMÉ' : '✓ OUVERT'}
              </button>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 mt-3">
          <button
            type="button"
            onClick={saveWeekly}
            disabled={savingPart === 'weekly'}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-white text-sm font-bold disabled:opacity-50"
            style={{ background: C_PS.terracotta }}
          >
            <Save size={14} />
            {savingPart === 'weekly' ? 'Enregistrement…' : 'Enregistrer la semaine'}
          </button>
        </div>
      </section>

      {/* ─── 2. PUBLIC HOLIDAYS ───────────────────────────── */}
      <section>
        <h3 className="text-base font-bold mb-1" style={{ color: C_PS.inkDeep, fontFamily: 'Cormorant Garamond' }}>
          2 · Jours fériés français
        </h3>
        <p className="text-xs mb-3" style={{ color: C_PS.inkMute }}>
          Cochez les jours où vous fermez. La liste se met à jour automatiquement chaque année.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-72 overflow-y-auto">
          {holidays.map((h) => {
            const dt = new Date(h.date);
            const dateLabel = dt.toLocaleDateString('fr-FR', {
              day: 'numeric', month: 'long', year: 'numeric',
            });
            return (
              <button
                key={h.date}
                type="button"
                onClick={() => toggleHoliday(h)}
                className="text-left p-3 rounded-lg border transition"
                style={{
                  background: h.closed ? '#F6E9E2' : 'white',
                  borderColor: h.closed ? '#E3A86988' : C_PS.hairline,
                }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold" style={{ color: C_PS.inkDeep }}>
                      {h.name}
                    </p>
                    <p className="text-[11px]" style={{ color: C_PS.inkMute }}>{dateLabel}</p>
                  </div>
                  <span
                    className="w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5"
                    style={{
                      background: h.closed ? '#E3A869' : 'white',
                      border: `1.5px solid ${h.closed ? '#E3A869' : '#C0BAB0'}`,
                    }}
                  >
                    {h.closed && <Check size={12} strokeWidth={3} color="white" />}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-3 mt-3">
          <button
            type="button"
            onClick={saveHolidays}
            disabled={savingPart === 'holidays'}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-white text-sm font-bold disabled:opacity-50"
            style={{ background: C_PS.terracotta }}
          >
            <Save size={14} />
            {savingPart === 'holidays' ? 'Enregistrement…' : 'Enregistrer les jours fériés'}
          </button>
        </div>
      </section>

      {/* ─── 3. ANNUAL CLOSURES ───────────────────────────── */}
      <section>
        <h3 className="text-base font-bold mb-1" style={{ color: C_PS.inkDeep, fontFamily: 'Cormorant Garamond' }}>
          3 · Vacances &amp; fermetures annuelles
        </h3>
        <p className="text-xs mb-3" style={{ color: C_PS.inkMute }}>
          Ajoutez des plages de dates où vous serez fermé (vacances d'été, travaux, etc.).
        </p>
        <div className="space-y-2">
          {annual.length === 0 && (
            <p className="text-sm italic" style={{ color: C_PS.inkFaint }}>
              Aucune fermeture annuelle prévue.
            </p>
          )}
          {annual.map((r, i) => (
            <div key={i} className="grid grid-cols-12 gap-2 items-center p-2 rounded-lg border"
                 style={{ background: 'var(--flc-paper2, #FAFAF8)', borderColor: C_PS.hairline }}>
              <input
                className="col-span-4 border rounded px-2 py-1.5 text-sm"
                style={{ borderColor: C_PS.hairline }}
                value={r.label || ''}
                onChange={(e) => updateRange(i, { label: e.target.value })}
                placeholder="Vacances août"
              />
              <input
                type="date"
                className="col-span-3 border rounded px-2 py-1.5 text-sm"
                style={{ borderColor: C_PS.hairline }}
                value={r.start}
                onChange={(e) => updateRange(i, { start: e.target.value })}
              />
              <span className="col-span-1 text-center text-xs" style={{ color: C_PS.inkMute }}>→</span>
              <input
                type="date"
                className="col-span-3 border rounded px-2 py-1.5 text-sm"
                style={{ borderColor: C_PS.hairline }}
                value={r.end}
                onChange={(e) => updateRange(i, { end: e.target.value })}
              />
              <button
                type="button"
                onClick={() => removeRange(i)}
                className="col-span-1 text-xs py-1.5 rounded transition"
                style={{ background: '#FEF2F2', color: '#991B1B', border: '1px solid #FECACA' }}
                aria-label="Retirer cette plage"
              >
                <Trash2 size={12} className="inline" />
              </button>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 mt-3 flex-wrap">
          <button
            type="button"
            onClick={addRange}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-bold border"
            style={{ borderColor: C_PS.hairline, color: C_PS.inkSoft, background: 'var(--flc-card, #FFFFFF)' }}
          >
            <Plus size={12} /> Ajouter une plage
          </button>
          <button
            type="button"
            onClick={saveAnnual}
            disabled={savingPart === 'annual'}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-white text-sm font-bold disabled:opacity-50"
            style={{ background: C_PS.terracotta }}
          >
            <Save size={14} />
            {savingPart === 'annual' ? 'Enregistrement…' : 'Enregistrer les vacances'}
          </button>
        </div>
      </section>

      {savedAt && (
        <p className="text-xs" style={{ color: '#4A5D23' }}>
          ✓ Enregistré à {savedAt.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
        </p>
      )}
    </div>
  );
};

export default BusinessHoursCard;
