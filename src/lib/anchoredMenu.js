// A ⋮ menu that always opens whole on the screen (user, 2026-11-10: « kisi
// bhi 3 dots mein click kro woh properly visible hona chahiye »).
//
// Drawn `position: fixed` — never inside a table's scroll box, which cut the
// menus of the last rows — below its button, or above it when there is no
// room below; its real height is measured once drawn, so a new line in it can
// never cut it again. Scrolling, resizing, Échap or a click elsewhere closes it. The same rules
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

  const toggle = (e, id) => {
    e.stopPropagation();
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
    const shut = () => setOpenId(null);                  // it stays by its button: scrolling closes it
    const key = (e) => { if (e.key === 'Escape') shut(); };
    // a click elsewhere (its own button stops its click, so it toggles instead)
    const away = (e) => { if (!ref.current || !ref.current.contains(e.target)) shut(); };
    window.addEventListener('scroll', shut, true);
    window.addEventListener('resize', shut);
    window.addEventListener('keydown', key);
    window.addEventListener('click', away);
    return () => {
      window.removeEventListener('scroll', shut, true);
      window.removeEventListener('resize', shut);
      window.removeEventListener('keydown', key);
      window.removeEventListener('click', away);
    };
  }, [openId]);

  const menuProps = {
    ref, role: 'menu',
    onClick: (e) => e.stopPropagation(),
    style: { position: 'fixed', right: pos?.right, top: pos?.top, visibility: pos?.ready ? 'visible' : 'hidden' },
  };
  return { openId, toggle, close, menuProps };
}
