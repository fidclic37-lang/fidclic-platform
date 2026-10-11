import { fitRect, viewW, viewH } from '../../lib/fit';
/**
 * CoachMarks — a spotlight tour over the REAL interface.
 *
 * Why not a video or a doc: people learn a tool by touching it. This dims the
 * page, cuts a hole around the actual button being explained, and puts one
 * short sentence next to it. The user sees where the thing is, not a picture of
 * where it was.
 *
 * Usage:
 *   <CoachMarks steps={[{ sel: '[data-tour="stats"]', title: '…', body: '…' }]}
 *               storageKey="cabinet-home" onClose={…} />
 * A step whose selector matches nothing is skipped automatically, so the tour
 * survives a screen where a button is role-hidden (an assistant has no
 * "validate" button — the tour just moves on).
 */
import { useEffect, useLayoutEffect, useState, useCallback } from 'react';
import { MC, EASE } from './mc';

const PAD = 8;

export function tourSeen(key) {
  try { return localStorage.getItem(`fidclic:tour:${key}`) === 'done'; } catch { return true; }
}
export function markTourSeen(key) {
  try { localStorage.setItem(`fidclic:tour:${key}`, 'done'); } catch { /* private mode */ }
}
export function resetTour(key) {
  try { localStorage.removeItem(`fidclic:tour:${key}`); } catch { /* ignore */ }
}

export default function CoachMarks({ steps = [], storageKey, onClose }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState(null);

  // resolve the current step's target, skipping steps whose element is absent
  const resolve = useCallback((from) => {
    for (let k = from; k < steps.length; k++) {
      const el = steps[k].sel ? document.querySelector(steps[k].sel) : null;
      if (!steps[k].sel) return { k, el: null };          // centred, no target
      if (el) return { k, el };
    }
    return null;
  }, [steps]);

  useLayoutEffect(() => {
    const found = resolve(i);
    if (!found) { finish(); return; }
    if (found.k !== i) { setI(found.k); return; }
    if (!found.el) { setRect(null); return; }
    found.el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    const measure = () => {
      const r = fitRect(found.el);                 // the app's pixels, even when it is scaled to fit
      setRect({ top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 });
    };
    measure();
    const t = setTimeout(measure, 320);            // after smooth scroll settles
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => { clearTimeout(t); window.removeEventListener('resize', measure);
                   window.removeEventListener('scroll', measure, true); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [i, steps]);

  const finish = () => { if (storageKey) markTourSeen(storageKey); onClose && onClose(); };

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') finish();
      if (e.key === 'ArrowRight' || e.key === 'Enter') next();
      if (e.key === 'ArrowLeft') setI((v) => Math.max(0, v - 1));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const next = () => (i >= steps.length - 1 ? finish() : setI(i + 1));
  const step = steps[i];
  if (!step) return null;

  // tooltip placement: below the hole, or above if it would fall off-screen
  const tipW = 320;
  let tipStyle;
  if (rect) {
    const below = rect.top + rect.height + 14;
    const above = rect.top - 14;
    const placeBelow = below + 190 < viewH();
    tipStyle = {
      top: placeBelow ? below : Math.max(12, above - 178),
      left: Math.min(Math.max(12, rect.left + rect.width / 2 - tipW / 2), viewW() - tipW - 12),
    };
  } else {
    tipStyle = { top: '50%', left: '50%', transform: 'translate(-50%,-50%)' };
  }

  return (
    <div className="fixed inset-0 z-[100]" role="dialog" aria-modal="true" aria-label="Visite guidée">
      {/* dim + spotlight hole (box-shadow trick keeps the hole crisp) */}
      {rect ? (
        <div onClick={next}
             style={{ position: 'fixed', top: rect.top, left: rect.left, width: rect.width, height: rect.height,
                      borderRadius: 16, boxShadow: '0 0 0 9999px rgba(4,6,15,.82)',
                      border: `2px solid ${MC.indigo}`, transition: `all .38s ${EASE}`,
                      pointerEvents: 'auto', cursor: 'pointer' }} />
      ) : (
        <div onClick={next} style={{ position: 'fixed', inset: 0, background: 'rgba(4,6,15,.82)' }} />
      )}

      <div style={{ position: 'fixed', width: tipW, ...tipStyle, transition: `all .38s ${EASE}`,
                    background: 'rgba(18,22,40,.96)', border: `1px solid ${MC.strokeStrong}`,
                    borderRadius: 16, padding: 16, backdropFilter: 'blur(14px)',
                    boxShadow: '0 24px 60px -24px rgba(0,0,0,.95)' }}>
        <div key={`t-${step.title}`} style={{ color: MC.ink, fontWeight: 700, fontSize: 14.5, marginBottom: 6 }}>
          {step.title}
        </div>
        <div key={`b-${step.body}`} style={{ color: MC.ink2, fontSize: 13, lineHeight: 1.55 }}>
          {step.body}
        </div>
        {step.example && (
          <div key={`e-${step.example}`} style={{ marginTop: 10, padding: '8px 11px', borderRadius: 10,
            background: 'rgba(124,124,248,.12)', color: '#CFCBFF', fontSize: 12, lineHeight: 1.5 }}>
            <b>Exemple :</b> {step.example}
          </div>
        )}
        <div className="flex items-center gap-2 mt-3">
          <div key={`c-${i}-${steps.length}`} style={{ fontSize: 11.5, color: MC.ink3 }}>
            {`${i + 1} / ${steps.length}`}
          </div>
          <button onClick={finish} style={{ marginLeft: 'auto', fontSize: 12, color: MC.ink3,
            background: 'none', cursor: 'pointer', padding: '6px 8px' }}>Passer</button>
          {i > 0 && (
            <button onClick={() => setI(i - 1)} style={{ fontSize: 12, color: MC.ink2, cursor: 'pointer',
              background: 'rgba(255,255,255,.06)', border: `1px solid ${MC.stroke}`,
              borderRadius: 10, padding: '6px 11px' }}>Retour</button>
          )}
          <button onClick={next} style={{ fontSize: 12.5, fontWeight: 700, color: '#fff', cursor: 'pointer',
            background: `linear-gradient(135deg, ${MC.indigo}, #5B5BE8)`, border: 'none',
            borderRadius: 10, padding: '7px 14px' }}>
            {i >= steps.length - 1 ? 'Terminer' : 'Suivant'}
          </button>
        </div>
      </div>
    </div>
  );
}
