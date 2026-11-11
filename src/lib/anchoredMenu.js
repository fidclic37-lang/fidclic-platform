// A ⋮ menu that always opens whole on the screen (user, 2026-11-10: « kisi
// bhi 3 dots mein click kro woh properly visible hona chahiye »).
//
// Drawn `position: fixed` — never inside a table's scroll box, which cut the
// menus of the last rows — below its button, or above it when there is no
// room below; its real height is measured once drawn, so a new line in it can
// never cut it again. A scroll moves it with its button; resizing, Échap or a
// press elsewhere (another ⋮ too) closes it. The same rules
// as the Clients page's menu (2026-10-16), in one place for any page.
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { fitRect, viewW, viewH } from './fit';

import { placeMenu, GAP, EDGE } from './placeMenu.js';

export { placeMenu };

/** { openId, toggle(event, id), close(), menuProps } — spread menuProps on the menu. */
export function useAnchoredMenu() {
  const [openId, setOpenId] = useState(null);
  const [pos, setPos] = useState(null);
  const ref = useRef(null);
  const anchor = useRef(null);                         // the button that opened it

  const toggle = (e, id) => {
    e.stopPropagation();
    anchor.current = e.currentTarget;
    if (openId === id) { setOpenId(null); return; }
    const r = fitRect(e.currentTarget);
    setPos({ right: Math.max(EDGE, viewW() - r.right), anchorTop: r.top, anchorBottom: r.bottom,
             top: r.bottom + GAP, ready: false });
    setOpenId(id);
  };
  const close = () => setOpenId(null);

  useLayoutEffect(() => {
    if (openId === null || !ref.current || !pos || pos.ready) return;
    const top = placeMenu({ anchorTop: pos.anchorTop, anchorBottom: pos.anchorBottom,
                            height: ref.current.offsetHeight, viewH: viewH() });
    setPos((p) => ({ ...p, top, ready: true }));
  }, [openId, pos]);

  useEffect(() => {
    if (openId === null) return undefined;
    const shut = () => setOpenId(null);
    // a scroll moves it with its button (a page nudged by a pixel as the menu
    // opens must not close it); it closes once its button leaves the screen
    const follow = () => {
      const a = anchor.current;
      if (!a || !a.isConnected) { shut(); return; }
      const r = fitRect(a);
      if (r.bottom < 0 || r.top > viewH()) { shut(); return; }
      setPos((p) => (p && Math.abs(p.anchorTop - r.top) < 1 ? p
        : { right: Math.max(EDGE, viewW() - r.right), anchorTop: r.top, anchorBottom: r.bottom,
            top: r.bottom + GAP, ready: false }));
    };
    const key = (e) => { if (e.key === 'Escape') shut(); };
    // a press elsewhere — another row's ⋮ included, so two menus never stay
    // open; its own button is left to toggle it
    const away = (e) => {
      const t = e.target;
      if (ref.current && ref.current.contains(t)) return;
      if (anchor.current && anchor.current.contains(t)) return;
      shut();
    };
    window.addEventListener('scroll', follow, true);
    window.addEventListener('resize', shut);
    window.addEventListener('keydown', key);
    document.addEventListener('mousedown', away, true);
    return () => {
      window.removeEventListener('scroll', follow, true);
      window.removeEventListener('resize', shut);
      window.removeEventListener('keydown', key);
      document.removeEventListener('mousedown', away, true);
    };
  }, [openId]);

  const menuProps = {
    ref, role: 'menu',
    onClick: (e) => e.stopPropagation(),
    style: { position: 'fixed', right: pos?.right, top: pos?.top, visibility: pos?.ready ? 'visible' : 'hidden' },
  };
  return { openId, toggle, close, menuProps };
}
