import React, { useEffect, useMemo, useRef, useState } from 'react';
import api, { ownerAPI } from '../lib/api';
import { Search, X, Filter, Users, Eye, ChevronDown, ChevronUp } from 'lucide-react';
import { C as C_PS } from './PageShell';
import DecimalInput from './DecimalInput';

/**
 * Unified Campaign Audience Builder.
 *
 * Replaces the old "By filter" / "By selected customers" tab UI in
 * CampaignsPage with a single section. Two complementary inputs:
 *
 *   1) Search-and-add chip picker  — pick specific customers without typing
 *      their info manually. Backed by GET /api/owner/customers?search=X.
 *
 *   2) Filter grid                 — every filter dimension the platform
 *      supports, in one place. Live preview count updates as filters change.
 *
 * If the picker has any chips, the campaign sends to those exact customers.
 * Otherwise the filter grid drives the audience.
 *
 * Controlled component — the parent owns these state variables (which map
 * onto the existing CampaignsPage state, so the existing submit logic
 * continues to work without changes):
 *   - formData / setFormData          (filter values)
 *   - campaignCustomers / setCampaignCustomers   (newline-separated IDs)
 *   - selectedCampaignTab / setSelectedCampaignTab  ('by-filter' | 'by-customers')
 */
const TIERS = ['bronze', 'silver', 'gold', 'vip'];
const STATUS_OPTIONS = [
  { value: '',         label: 'Any status' },
  { value: 'active',   label: 'Active (visited recently)' },
  { value: 'inactive', label: 'Inactive (slowing down)' },
  { value: 'dormant',  label: 'Dormant (likely churned)' },
  { value: 'new',      label: 'New (no visits yet)' },
];
const MONTHS = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December',
];

const useDebounced = (value, ms = 250) => {
  const [v, setV] = useState(value);
  useEffect(() => { const id = setTimeout(() => setV(value), ms); return () => clearTimeout(id); }, [value, ms]);
  return v;
};

const CampaignAudienceBuilder = ({
  formData,
  setFormData,
  campaignCustomers,
  setCampaignCustomers,
  setSelectedCampaignTab,
}) => {
  // ---- Search & specific-customer picker ----
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounced(search, 250);
  const [searchResults, setSearchResults] = useState([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [picked, setPicked] = useState([]);  // [{ id, name, email, tier }, ...]
  const blurTimerRef = useRef(null);

  // Hydrate `picked` from any existing campaignCustomers (e.g. campaign-map handoff).
  useEffect(() => {
    if (!campaignCustomers || picked.length > 0) return;
    const lines = campaignCustomers.split('\n').map(s => s.trim()).filter(Boolean);
    if (lines.length === 0) return;
    // We don't have full info here; show as minimal chips and the parent submits as-is.
    setPicked(lines.map((id) => ({ id, name: id, tier: '', email: '' })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!debouncedSearch || debouncedSearch.length < 2) {
      setSearchResults([]);
      return;
    }
    const run = async () => {
      try {
        const res = await ownerAPI.getCustomers({ search: debouncedSearch });
        if (cancelled) return;
        const rows = Array.isArray(res.data) ? res.data : (res.data?.customers || []);
        setSearchResults(rows.slice(0, 25));
      } catch (e) {
        if (!cancelled) setSearchResults([]);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [debouncedSearch]);

  const addPick = (c) => {
    if (picked.find((p) => p.id === c.id)) return;
    const next = [...picked, c];
    setPicked(next);
    setCampaignCustomers(next.map((p) => p.id).join('\n'));
    setSelectedCampaignTab('by-customers');
    setSearch('');
    setSearchResults([]);
  };

  const removePick = (id) => {
    const next = picked.filter((p) => p.id !== id);
    setPicked(next);
    setCampaignCustomers(next.map((p) => p.id).join('\n'));
    setSelectedCampaignTab(next.length > 0 ? 'by-customers' : 'by-filter');
  };

  const clearPicks = () => {
    setPicked([]);
    setCampaignCustomers('');
    setSelectedCampaignTab('by-filter');
  };

  // ---- Filter helpers ----
  const F = formData.filters || {};
  const setF = (patch) => setFormData((prev) => ({ ...prev, filters: { ...prev.filters, ...patch } }));

  const toggleTier = (tier) => {
    const tiers = (F.tiers || []).includes(tier)
      ? F.tiers.filter((t) => t !== tier)
      : [...(F.tiers || []), tier];
    setF({ tiers });
  };

  const toggleBirthMonth = (m) => {
    const arr = F.birthMonths || [];
    const next = arr.includes(m) ? arr.filter((x) => x !== m) : [...arr, m];
    setF({ birthMonths: next });
  };

  // ---- Live preview ----
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const previewTimerRef = useRef(null);

  const buildPreviewFilters = () => {
    if (picked.length > 0) return null;     // explicit list short-circuits
    // Match the existing buildFilterPayload() convention in CampaignsPage so
    // the backend recognises the field names. Extra dimensions (max-visits,
    // customer_status, has_wallet_pass, etc.) are forwarded too — backends
    // that don't yet understand them simply ignore them.
    const out = {};
    if (F.tiers?.length)            out.tiers = F.tiers;
    if (F.minVisits)                out.minVisits = F.minVisits;
    if (F.maxVisits)                out.maxVisits = F.maxVisits;
    if (F.minPoints)                out.minPoints = F.minPoints;
    if (F.minAmountPaid)            out.minAmountPaid = F.minAmountPaid;
    if (F.maxAmountPaid)            out.maxAmountPaid = F.maxAmountPaid;
    if (F.postalCodes)              out.postalCodes = F.postalCodes.split(',').map(s => s.trim()).filter(Boolean);
    if (F.hasWalletPass === true)   out.hasWalletPass = true;
    if (F.hasWalletPass === false)  out.hasWalletPass = false;
    if (F.customerStatus)           out.customerStatus = F.customerStatus;
    if (F.daysSinceLastVisitMax)    out.daysSinceLastVisitMax = F.daysSinceLastVisitMax;
    if (F.daysSinceLastVisitMin)    out.daysSinceLastVisitMin = F.daysSinceLastVisitMin;
    if (F.birthMonths?.length)      out.birthMonths = F.birthMonths;
    return out;
  };

  // Debounced preview — re-counts whenever filters or picks change.
  useEffect(() => {
    if (previewTimerRef.current) clearTimeout(previewTimerRef.current);
    previewTimerRef.current = setTimeout(async () => {
      try {
        if (picked.length > 0) {
          setPreview({ count: picked.length, mode: 'specific' });
          return;
        }
        setPreviewLoading(true);
        const res = await ownerAPI.previewSegment({ filters: buildPreviewFilters() || {} });
        setPreview({ count: res.data?.matching_customers ?? 0, mode: 'filter' });
      } catch (e) {
        setPreview(null);
      } finally {
        setPreviewLoading(false);
      }
    }, 350);
    return () => previewTimerRef.current && clearTimeout(previewTimerRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(F), picked.length]);

  const [advOpen, setAdvOpen] = useState(false);

  return (
    <div className="border-t pt-6 space-y-5" style={{ borderColor: '#E9E5E0' }}>
      <div className="flex items-center gap-2">
        <Users size={18} className="text-[#B85C38]" />
        <h3 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond', color: '#171412' }}>
          Audience
        </h3>
        <span className="text-xs ml-auto" style={{ color: C_PS.inkMute }}>
          Pick specific customers, or use filters. Both update the live preview below.
        </span>
      </div>

      {/* ---- Search picker ---- */}
      <div className="rounded-lg p-4 space-y-3" style={{ background: '#F5F4F1', border: `1px solid ${C_PS.hairline}` }}>
        <label className="text-xs font-bold uppercase tracking-widest block" style={{ color: C_PS.inkMute }}>
          Pick specific customers (optional)
        </label>
        <div className="relative">
          <div className="flex items-center gap-2 bg-white rounded-lg px-3 py-2" style={{ border: `1px solid ${C_PS.hairline}` }}>
            <Search size={16} className="text-[#B85C38] shrink-0" />
            <input
              type="text"
              value={search}
              placeholder="Type a name or email — no manual typing of details, just search and click to add"
              onChange={(e) => setSearch(e.target.value)}
              onFocus={() => setSearchOpen(true)}
              onBlur={() => { blurTimerRef.current = setTimeout(() => setSearchOpen(false), 200); }}
              className="flex-1 outline-none text-sm bg-transparent"
            />
            {picked.length > 0 && (
              <button type="button" onClick={clearPicks}
                className="text-xs font-semibold text-[#991B1B] hover:underline shrink-0">
                Clear all
              </button>
            )}
          </div>
          {searchOpen && search.length >= 2 && searchResults.length > 0 && (
            <div className="absolute z-30 left-0 right-0 mt-1 max-h-72 overflow-y-auto bg-white rounded-lg shadow-lg"
              style={{ border: `1px solid ${C_PS.hairline}` }}>
              {searchResults.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onMouseDown={() => addPick({
                    id: c.id, name: c.name, email: c.email, tier: c.tier,
                  })}
                  className="w-full text-left px-3 py-2 hover:bg-[#F5F4F1] flex items-center justify-between gap-3"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-semibold truncate" style={{ color: C_PS.inkDeep }}>{c.name}</p>
                    <p className="text-xs truncate" style={{ color: C_PS.inkMute }}>{c.email}</p>
                  </div>
                  <span className="text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 rounded-full"
                    style={{ background: `${C_PS.terracotta}1A`, color: C_PS.terracotta }}>
                    {c.tier || 'bronze'} · {c.visits ?? 0}v
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {picked.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {picked.map((p) => (
              <span key={p.id}
                className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold"
                style={{ background: 'white', color: C_PS.inkDeep, border: `1px solid ${C_PS.terracotta}55` }}>
                {p.name}
                <button type="button" onClick={() => removePick(p.id)} aria-label="Remove" className="text-[#991B1B] hover:scale-110">
                  <X size={12} />
                </button>
              </span>
            ))}
            <span className="text-xs self-center" style={{ color: C_PS.inkMute }}>
              {picked.length} customer{picked.length === 1 ? '' : 's'} selected — filters below are ignored.
            </span>
          </div>
        ) : (
          <p className="text-xs" style={{ color: C_PS.inkMute }}>
            No specific customers picked. The campaign will use the filters below.
          </p>
        )}
      </div>

      {/* ---- Filter grid ---- */}
      <div className={`rounded-lg p-4 space-y-4 ${picked.length > 0 ? 'opacity-50 pointer-events-none' : ''}`}
        style={{ border: `1px solid ${C_PS.hairline}` }}>
        <div className="flex items-center gap-2">
          <Filter size={14} className="text-[#B85C38]" />
          <span className="text-xs font-bold uppercase tracking-widest" style={{ color: C_PS.inkMute }}>
            Filters {picked.length > 0 && '(disabled — clear specific picks to use filters)'}
          </span>
        </div>

        {/* Tier */}
        <Row label="Tier">
          <div className="flex flex-wrap gap-2">
            {TIERS.map((t) => {
              const on = (F.tiers || []).includes(t);
              return (
                <button key={t} type="button" onClick={() => toggleTier(t)}
                  className="px-3 py-1.5 rounded-full text-xs font-semibold transition border"
                  style={{
                    background: on ? '#B85C38' : 'white',
                    color: on ? 'white' : '#57504A',
                    borderColor: on ? '#B85C38' : '#E9E5E0',
                  }}>
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              );
            })}
          </div>
        </Row>

        {/* Visits range */}
        <Row label="Visits">
          <RangePair
            minVal={F.minVisits || ''} maxVal={F.maxVisits || ''}
            onMinChange={(v) => setF({ minVisits: v })}
            onMaxChange={(v) => setF({ maxVisits: v })}
            unit="visits"
          />
        </Row>

        {/* Spend range */}
        <Row label="Total spend">
          <RangePair
            minVal={F.minAmountPaid || ''} maxVal={F.maxAmountPaid || ''}
            onMinChange={(v) => setF({ minAmountPaid: v })}
            onMaxChange={(v) => setF({ maxAmountPaid: v })}
            unit="€" step="0.01"
          />
        </Row>

        {/* Status (configurable definition) */}
        <Row label="Customer status" hint="Uses the definition you set in Settings.">
          <select
            value={F.customerStatus || ''}
            onChange={(e) => setF({ customerStatus: e.target.value || null })}
            className="border rounded-lg px-3 py-1.5 text-sm bg-white"
            style={{ borderColor: '#E9E5E0', minWidth: 220 }}>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </Row>

        <button
          type="button"
          onClick={() => setAdvOpen((s) => !s)}
          className="text-xs font-semibold flex items-center gap-1"
          style={{ color: C_PS.terracotta }}>
          {advOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          Advanced filters {advOpen ? '— hide' : '— show'}
        </button>

        {advOpen && (
          <div className="space-y-4 pt-2">
            <Row label="Minimum points">
              <input type="number" min={0} value={F.minPoints || ''}
                onChange={(e) => setF({ minPoints: parseInt(e.target.value || '0', 10) || 0 })}
                className="w-32 border rounded-lg px-3 py-1.5 text-sm bg-white" style={{ borderColor: '#E9E5E0' }} />
            </Row>

            <Row label="Postal codes" hint="Comma-separated, e.g. 75001,75002">
              <input type="text" value={F.postalCodes || ''}
                onChange={(e) => setF({ postalCodes: e.target.value })}
                placeholder="75001,75002,75003"
                className="w-full md:w-72 border rounded-lg px-3 py-1.5 text-sm bg-white" style={{ borderColor: '#E9E5E0' }} />
            </Row>

            <Row label="Inactive for at least"
              hint="Target customers who haven't visited for this many days. Empty = no constraint.">
              <div className="flex items-center gap-2">
                <input
                  type="number" min={0}
                  value={F.daysSinceLastVisitMin || ''}
                  onChange={(e) => setF({
                    daysSinceLastVisitMin: e.target.value === '' ? null : parseInt(e.target.value, 10),
                  })}
                  placeholder="e.g. 30"
                  className="w-32 border rounded-lg px-3 py-1.5 text-sm bg-white"
                  style={{ borderColor: '#E9E5E0' }}
                />
                <span className="text-xs" style={{ color: C_PS.inkMute }}>days</span>
              </div>
            </Row>

            <Row label="Birthday in month">
              <div className="flex flex-wrap gap-1.5">
                {MONTHS.map((m, idx) => {
                  const monthNum = idx + 1;
                  const on = (F.birthMonths || []).includes(monthNum);
                  return (
                    <button key={m} type="button" onClick={() => toggleBirthMonth(monthNum)}
                      className="px-2.5 py-1 rounded-full text-[11px] font-semibold transition border"
                      style={{
                        background: on ? '#B85C38' : 'white',
                        color: on ? 'white' : '#57504A',
                        borderColor: on ? '#B85C38' : '#E9E5E0',
                      }}>
                      {m.slice(0, 3)}
                    </button>
                  );
                })}
              </div>
            </Row>
          </div>
        )}
      </div>

      {/* ---- Live preview ---- */}
      <div className="rounded-lg p-4 flex items-center gap-3"
        style={{ background: `${C_PS.terracotta}0D`, border: `1px solid ${C_PS.terracotta}33` }}>
        <Eye size={18} className="text-[#B85C38] shrink-0" />
        <div className="flex-1">
          <p className="text-sm font-semibold" style={{ color: C_PS.inkDeep }}>
            {previewLoading ? 'Counting…'
              : preview ? (
                preview.mode === 'specific'
                  ? `Will reach ${preview.count} specific customer${preview.count === 1 ? '' : 's'} (you picked them).`
                  : `Will reach approximately ${preview.count} customer${preview.count === 1 ? '' : 's'} matching the filters above.`
              ) : 'Adjust filters or pick customers to see the projected reach.'
            }
          </p>
        </div>
      </div>
    </div>
  );
};

const Row = ({ label, hint, children }) => (
  <div>
    <label className="text-xs font-bold uppercase tracking-widest mb-1.5 block" style={{ color: C_PS.inkMute }}>
      {label}
    </label>
    {children}
    {hint && <p className="text-[11px] mt-1" style={{ color: C_PS.inkMute }}>{hint}</p>}
  </div>
);

const RangePair = ({ minVal, maxVal, onMinChange, onMaxChange, unit, step, minLabel = 'min', maxLabel = 'max' }) => (
  <div className="flex items-center gap-2 flex-wrap">
    <div className="flex items-center gap-1">
      <span className="text-[10px] uppercase font-bold tracking-widest" style={{ color: C_PS.inkMute }}>{minLabel}</span>
      <DecimalInput value={minVal ?? ''}
        onChange={(v) => onMinChange(v === '' ? null : parseFloat(v))}
        className="w-24 border rounded-lg px-2 py-1.5 text-sm bg-white" style={{ borderColor: '#E9E5E0' }} />
    </div>
    <span style={{ color: C_PS.inkMute }}>–</span>
    <div className="flex items-center gap-1">
      <span className="text-[10px] uppercase font-bold tracking-widest" style={{ color: C_PS.inkMute }}>{maxLabel}</span>
      <DecimalInput value={maxVal ?? ''}
        onChange={(v) => onMaxChange(v === '' ? null : parseFloat(v))}
        className="w-24 border rounded-lg px-2 py-1.5 text-sm bg-white" style={{ borderColor: '#E9E5E0' }} />
    </div>
    <span className="text-xs" style={{ color: C_PS.inkMute }}>{unit}</span>
  </div>
);

export default CampaignAudienceBuilder;
