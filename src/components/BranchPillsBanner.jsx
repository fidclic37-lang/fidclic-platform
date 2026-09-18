import React, { useEffect, useState } from 'react';
import { Sun } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useBranch } from '../contexts/BranchContext';

/**
 * BranchPillsBanner — the "DONNÉES EN TEMPS RÉEL · TOUTES VOS BRANCHES"
 * panel that sits at the top of the Analytics / Dashboard pages.
 *
 * Visual: warm-cream gradient surface, a dark icon chip on the left, a
 * two-line title ("eyebrow + subtitle"), and a row of branch pills on
 * the right. The first pill is always "Toutes les branches" (network-wide).
 *
 * Behaviour:
 *   - Pulls the branch list from the same context as BranchSelectorBar so
 *     picking a pill filters every chart on the page in lockstep.
 *   - Hides itself entirely if the tenant has only one branch (single-shop
 *     account doesn't need the noise).
 *   - Active pill carries the brand colour; idle pills carry a hairline.
 */
export default function BranchPillsBanner({ compact = false } = {}) {
  const { branchId, setBranchId, branches: ctxBranches, setBranches } = useBranch();
  const [localBranches, setLocalBranches] = useState(ctxBranches || []);

  // Branches may not be in context yet on the first paint (the Dashboard
  // populates it). Fetch directly as a fallback so the banner can render
  // independently of page-load order.
  useEffect(() => {
    if (ctxBranches && ctxBranches.length > 0) {
      setLocalBranches(ctxBranches);
      return;
    }
    let alive = true;
    ownerAPI.getBranches?.()
      .then((r) => {
        if (!alive) return;
        const list = Array.isArray(r?.data) ? r.data : (r?.data?.branches || []);
        setLocalBranches(list);
        if (typeof setBranches === 'function') setBranches(list);
      })
      .catch(() => { /* silent — banner will fall back to empty pills */ });
    return () => { alive = false; };
  }, [ctxBranches, setBranches]);

  // Single-branch tenants don't need a banner taking up vertical space.
  if (!Array.isArray(localBranches) || localBranches.length < 2) return null;

  const activeBranch = localBranches.find((b) => b.id === branchId);
  const isAll = !branchId;

  // Compact variant — lives inside the top toolbar between the search
  // and the bell. Two-line text on the left, chips on the right.
  if (compact) {
    return (
      <div className="flex items-center justify-between gap-3 min-w-0 w-full">
        <div className="flex items-center gap-2.5 min-w-0">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: 'var(--flc-accent, #2F6BFF)', color: '#FFFFFF' }}
          >
            <Sun size={14} />
          </div>
          <div className="min-w-0">
            <p
              className="text-[9.5px] uppercase tracking-[0.14em] truncate"
              style={{ color: 'var(--flc-accent-deep, #1D4ED8)', fontWeight: 700, letterSpacing: '0.14em' }}
            >
              Données en temps réel · {isAll ? 'toutes vos branches' : (activeBranch?.name || 'branche')}
            </p>
            <p className="text-[11px] truncate mt-0.5" style={{ color: 'var(--flc-ink3, #64748B)' }}>
              Suivez vos performances, comprenez vos clients, optimisez vos campagnes.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1 flex-wrap shrink-0 justify-end">
          <button
            type="button"
            onClick={() => setBranchId('')}
            title="Toutes les branches"
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] transition-all"
            style={
              isAll
                ? { background: 'var(--flc-ink, #171412)', color: 'var(--flc-paper, #FFFFFF)', fontWeight: 500 }
                : { background: 'var(--flc-card, #FFFFFF)', color: 'var(--flc-ink, #171412)', border: '1px solid var(--flc-line, #E2DAC4)', fontWeight: 400 }
            }
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
            </svg>
            Toutes
          </button>
          {localBranches.slice(0, 3).map((b) => {
            const isActive = branchId === b.id;
            const short = (b.name || b.id || '').split('-').pop().trim() || b.name || b.id;
            return (
              <button
                key={b.id}
                type="button"
                onClick={() => setBranchId(b.id)}
                title={b.name || b.id}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] transition-all max-w-[160px] truncate"
                style={
                  isActive
                    ? { background: 'var(--flc-accent-deep, #9C4427)', color: 'var(--flc-card, #FFFFFF)', fontWeight: 500 }
                    : { background: 'var(--flc-card, #FFFFFF)', color: 'var(--flc-ink, #171412)', border: '1px solid var(--flc-line, #E2DAC4)', fontWeight: 400 }
                }
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                </svg>
                {short}
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-2xl px-4 py-3 mb-4 flex items-center justify-between gap-3 flex-wrap"
      style={{
        background: 'var(--flc-accent-soft, #EAF0FF)',
        border: '1px solid #C7D7FF',
      }}
    >
      <div className="flex items-center gap-3 min-w-0">
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: 'var(--flc-accent, #2F6BFF)', color: '#FFFFFF' }}
        >
          <Sun size={18} />
        </div>
        <div className="min-w-0">
          <p
            className="text-[10px] uppercase"
            style={{ color: 'var(--flc-accent-deep, #1D4ED8)', fontWeight: 600, letterSpacing: '0.16em' }}
          >
            Données en temps réel · {isAll ? 'toutes vos branches' : activeBranch?.name || 'branche'}
          </p>
          <p className="text-[12px] mt-0.5" style={{ color: 'var(--flc-ink2, #334155)' }}>
            Suivez vos performances, comprenez vos clients, optimisez vos campagnes.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        {/* "All branches" master pill — dark when active, hairline when idle */}
        <button
          type="button"
          onClick={() => setBranchId('')}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] transition-all"
          style={
            isAll
              ? { background: 'var(--flc-ink, #171412)', color: 'var(--flc-paper, #FFFFFF)', fontWeight: 500 }
              : { background: 'var(--flc-card, #FFFFFF)', color: 'var(--flc-ink, #171412)', border: '1px solid var(--flc-line, #E2DAC4)', fontWeight: 400 }
          }
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
            <polyline points="9 22 9 12 15 12 15 22" />
          </svg>
          Toutes les branches
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>

        {/* Individual branch pills — terracotta when active, hairline when idle.
            Limit to the first 4 so the banner doesn't wrap on busy chains. */}
        {localBranches.slice(0, 4).map((b) => {
          const isActive = branchId === b.id;
          return (
            <button
              key={b.id}
              type="button"
              onClick={() => setBranchId(b.id)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] transition-all"
              style={
                isActive
                  ? { background: 'var(--flc-accent-deep, #9C4427)', color: 'var(--flc-card, #FFFFFF)', fontWeight: 500 }
                  : { background: 'var(--flc-card, #FFFFFF)', color: 'var(--flc-ink, #171412)', border: '1px solid var(--flc-line, #E2DAC4)', fontWeight: 400 }
              }
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
              </svg>
              {b.name || b.id}
            </button>
          );
        })}
      </div>
    </div>
  );
}
