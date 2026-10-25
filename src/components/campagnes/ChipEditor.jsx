import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from 'react';

/**
 * The message box of the Campagnes wizard (mockup step 2): plain text with
 * the variables shown as chips — « {prénom} × » — that never break apart.
 * The value stays a string with {tokens}; the server fills them per client
 * (server.render_template). Enter does nothing (one paragraph), a paste keeps
 * only the text, Backspace next to a chip removes the whole chip.
 */
export const TOKENS = {
  'prénom': { label: '{prénom}', tone: 'blue' },
  nom_commerce: { label: '{nom_commerce}', tone: 'violet' },
  points: { label: '{points}', tone: 'green' },
  'prochaine_récompense': { label: '{prochaine_récompense}', tone: 'rose' },
  points_manquants: { label: '{points_manquants}', tone: 'amber' },
  visites: { label: '{visites}', tone: 'violet' },
  produit_habituel: { label: '{produit_habituel}', tone: 'green' },
};
const TONE = {
  blue: 'background:#E6EEFF;color:#1D4ED8',
  violet: 'background:#F1EAFF;color:#6D28D9',
  green: 'background:#E3F6EC;color:#047857',
  rose: 'background:#FFE8EE;color:#BE123C',
  amber: 'background:#FFF1DC;color:#B45309',
};
const RE = new RegExp(`\\{(${Object.keys(TOKENS).join('|')})\\}`, 'g');

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function chipHtml(key) {
  const t = TOKENS[key];
  return `<span data-token="${key}" contenteditable="false" class="cg-chip" style="${TONE[t.tone]}">`
    + `${esc(t.label)}<button type="button" data-remove="1" aria-label="Retirer ${esc(t.label)}" tabindex="-1">×</button></span>`;
}

function toHtml(value) {
  let out = '';
  let last = 0;
  String(value || '').replace(RE, (m, key, idx) => {
    out += esc(value.slice(last, idx)) + chipHtml(key);
    last = idx + m.length;
    return m;
  });
  return out + esc(String(value || '').slice(last));
}

function serialize(root) {
  let s = '';
  root.childNodes.forEach((n) => {
    if (n.nodeType === 3) s += n.nodeValue;
    else if (n.dataset && n.dataset.token) s += `{${n.dataset.token}}`;
    else if (n.nodeName === 'BR') s += ' ';
    else s += serialize(n);
  });
  return s.replace(/ /g, ' ');
}

const ChipEditor = forwardRef(function ChipEditor({ value, onChange, placeholder, max = 160, id }, ref) {
  const el = useRef(null);
  const lastRange = useRef(null);

  // write the value only when it is not what is already on screen (the caret stays)
  useEffect(() => {
    if (el.current && serialize(el.current) !== (value || '')) el.current.innerHTML = toHtml(value || '');
  }, [value]);

  const emit = useCallback(() => {
    if (!el.current) return;
    let v = serialize(el.current);
    if (v.length > max) {
      v = v.slice(0, max);
      el.current.innerHTML = toHtml(v);
    }
    onChange(v);
  }, [onChange, max]);

  const remember = () => {
    const sel = window.getSelection();
    if (sel && sel.rangeCount && el.current?.contains(sel.anchorNode)) lastRange.current = sel.getRangeAt(0).cloneRange();
  };

  const insert = (html) => {
    const node = el.current;
    if (!node) return;
    node.focus();
    const sel = window.getSelection();
    let range = lastRange.current && node.contains(lastRange.current.startContainer) ? lastRange.current : null;
    if (!range) {
      range = document.createRange();
      range.selectNodeContents(node);
      range.collapse(false);
    }
    const frag = range.createContextualFragment(html);
    const lastNode = frag.lastChild;
    range.deleteContents();
    range.insertNode(frag);
    if (lastNode) {
      const after = document.createRange();
      after.setStartAfter(lastNode);
      after.collapse(true);
      sel.removeAllRanges();
      sel.addRange(after);
      lastRange.current = after.cloneRange();
    }
    emit();
  };

  useImperativeHandle(ref, () => ({
    insertToken: (key) => insert(`${chipHtml(key)}&nbsp;`),
    insertText: (text) => insert(esc(text)),
    focus: () => el.current?.focus(),
  }));

  const onKeyDown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); return; }
    if (e.key === 'Backspace') {
      const sel = window.getSelection();
      if (sel && sel.isCollapsed && sel.anchorNode) {
        const { anchorNode, anchorOffset } = sel;
        let prev = null;
        if (anchorNode === el.current) prev = el.current.childNodes[anchorOffset - 1];
        else if (anchorNode.nodeType === 3 && anchorOffset === 0) prev = anchorNode.previousSibling;
        if (prev && prev.dataset && prev.dataset.token) {
          e.preventDefault();
          prev.remove();
          emit();
        }
      }
    }
  };

  const onPaste = (e) => {
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text').replace(/\s+/g, ' ');
    insert(toHtml(text));
  };

  const onClick = (e) => {
    const btn = e.target.closest && e.target.closest('[data-remove]');
    if (btn) {
      e.preventDefault();
      btn.parentElement.remove();
      emit();
    }
    remember();
  };

  return (
    <div className="relative">
      <style>{`.cg-chip{display:inline-flex;align-items:center;gap:6px;margin:0 2px;padding:2px 8px;border-radius:8px;font-size:14px;font-weight:600;white-space:nowrap;vertical-align:baseline}
.cg-chip button{border:0;background:transparent;color:inherit;font-size:15px;line-height:1;cursor:pointer;padding:0 0 1px}`}</style>
      <div id={id} ref={el} role="textbox" aria-multiline="false" contentEditable suppressContentEditableWarning
           onInput={emit} onKeyDown={onKeyDown} onPaste={onPaste} onClick={onClick}
           onKeyUp={remember} onMouseUp={remember} onBlur={remember}
           data-placeholder={placeholder}
           className="cg-editor min-h-[92px] w-full rounded-xl border border-[#D9E2F2] bg-white px-4 py-3 text-[16px] leading-[2] text-[#0B1C3F] outline-none focus:border-[#2F6BFF] focus:ring-2 focus:ring-[#2F6BFF]/15" />
      <style>{`.cg-editor:empty:before{content:attr(data-placeholder);color:#94A3B8}`}</style>
    </div>
  );
});

export default ChipEditor;
