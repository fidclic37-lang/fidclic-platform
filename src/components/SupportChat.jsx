import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Send, Loader2, Sparkles, ArrowRight, MessageCircle, X } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * SupportChat — the assistant on the "Besoin d'aide ?" page.
 *
 * It talks to /api/owner/support/chat, which answers out of the FidClic
 * knowledge base (see api/features/support_assistant.py). The backend always
 * returns an answer — the model only rephrases what the documentation already
 * says — so this component has no "sorry, something went wrong" happy path to
 * rely on. It still handles a network failure honestly: the question stays in
 * the input so nothing is lost, and the thread says what happened.
 *
 * Rendered in two shapes from the same state:
 *   variant="panel"  — the column on the help page
 *   variant="bubble" — a floating launcher, available on every dashboard page
 */
const BLUE = '#2F6BFF';

const Bubble = ({ role, text, link, onLink }) => {
  const mine = role === 'user';
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div
        className={[
          'max-w-[85%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed',
          mine
            ? 'bg-[#2F6BFF] text-white rounded-br-md'
            : 'bg-white text-[#0B1C3F] border border-[#E6EEFB] rounded-bl-md shadow-[0_10px_24px_-20px_rgba(11,28,63,.5)]',
        ].join(' ')}
      >
        <p className="whitespace-pre-wrap">{text}</p>
        {!mine && link && (
          <button
            type="button"
            onClick={() => onLink?.(link.to)}
            className="mt-2 inline-flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF] hover:underline"
          >
            {link.label} <ArrowRight size={13} />
          </button>
        )}
      </div>
    </div>
  );
};

const Typing = () => (
  <div className="flex justify-start">
    <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-md border border-[#E6EEFB] bg-white px-3.5 py-3">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-[#9CB3D9]"
          style={{ animation: `hlpDot 1.2s ${i * 0.15}s infinite ease-in-out` }}
        />
      ))}
    </div>
  </div>
);

export default function SupportChat({
  variant = 'panel',
  greeting = 'Bonjour 👋 Comment pouvons-nous vous aider aujourd\'hui ?',
  quickReplies = [],
  onNavigate,
  onEscalate,
  seedQuestion = null,       // a question pushed in from the FAQ list
  onSeedConsumed,
}) {
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(variant === 'panel');
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  // Replay this merchant's recent thread so the conversation survives a reload.
  useEffect(() => {
    let alive = true;
    ownerAPI.supportHistory(12)
      .then(({ data }) => {
        if (!alive) return;
        const past = (data?.messages || []).flatMap((m) => ([
          { role: 'user', text: m.question },
          { role: 'bot', text: m.answer },
        ]));
        setMessages(past);
      })
      .catch(() => { /* an empty thread is a perfectly good starting point */ });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, busy, open]);

  const ask = useCallback(async (question) => {
    const q = (question || '').trim();
    if (!q || busy) return;
    setMessages((m) => [...m, { role: 'user', text: q }]);
    setDraft('');
    setBusy(true);
    try {
      const { data } = await ownerAPI.supportAsk(q);
      setMessages((m) => [...m, {
        role: 'bot',
        text: data?.answer || '',
        link: data?.link || null,
        escalate: !!data?.escalate,
      }]);
      if (data?.escalate) onEscalate?.(q);
    } catch (err) {
      // Keep the question — the merchant retypes nothing.
      setDraft(q);
      setMessages((m) => [...m, {
        role: 'bot',
        text: "La connexion n'a pas abouti. Votre question est toujours dans le champ ci-dessous, "
            + 'réessayez dans un instant — ou contactez-nous directement, nous répondons en moins de 5 min.',
      }]);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }, [busy, onEscalate]);

  // A click on a FAQ card sends its question straight into the thread.
  useEffect(() => {
    if (!seedQuestion) return;
    setOpen(true);
    ask(seedQuestion);
    onSeedConsumed?.();
  }, [seedQuestion, ask, onSeedConsumed]);

  const thread = (
    <>
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        <Bubble role="bot" text={greeting} />
        {messages.map((m, i) => (
          <Bubble key={i} role={m.role} text={m.text} link={m.link} onLink={onNavigate} />
        ))}
        {busy && <Typing />}
        {messages.length === 0 && quickReplies.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {quickReplies.map((q) => (
              <button
                key={q.id}
                type="button"
                onClick={() => (q.question ? ask(q.question) : inputRef.current?.focus())}
                className="rounded-full border border-[#E6EEFB] bg-white px-3 py-1.5 text-[12px] font-medium text-[#334155] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]"
              >
                {q.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); ask(draft); }}
        className="flex items-center gap-2 border-t border-[#E6EEFB] bg-white px-3 py-3"
      >
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          // Enter sends. Spelled out rather than left to the form's implicit
          // submit, which some mobile keyboards never trigger.
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(draft); }
          }}
          placeholder="Posez votre question…"
          maxLength={1000}
          className="min-w-0 flex-1 rounded-xl border border-[#E6EEFB] bg-[#F8FAFF] px-3 py-2.5 text-[13px] text-[#0B1C3F] outline-none transition placeholder:text-[#94A3B8] focus:border-[#2F6BFF]"
        />
        <button
          type="submit"
          disabled={!draft.trim() || busy}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#2F6BFF] text-white transition disabled:opacity-40"
          aria-label="Envoyer"
        >
          {busy ? <Loader2 size={17} className="animate-spin" /> : <Send size={16} />}
        </button>
      </form>
    </>
  );

  if (variant === 'bubble') {
    return (
      <>
        {open && (
          <div className="fixed bottom-24 right-6 z-50 flex h-[480px] w-[360px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-[#E6EEFB] bg-[#F8FAFF] shadow-[0_30px_70px_-30px_rgba(11,28,63,.55)]">
            <header className="flex items-center justify-between bg-[#2F6BFF] px-4 py-3 text-white">
              <span className="flex items-center gap-2 text-[13.5px] font-semibold">
                <Sparkles size={15} /> Assistant FidClic
              </span>
              <button type="button" onClick={() => setOpen(false)} aria-label="Fermer">
                <X size={17} />
              </button>
            </header>
            {thread}
          </div>
        )}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-[#2F6BFF] text-white shadow-[0_18px_40px_-16px_rgba(47,107,255,.8)] transition hover:scale-105"
          aria-label="Ouvrir l'assistant"
        >
          {open ? <X size={22} /> : <MessageCircle size={22} />}
        </button>
      </>
    );
  }

  return (
    <section className="flex h-[560px] flex-col overflow-hidden rounded-2xl border border-[#E6EEFB] bg-[#F8FAFF] shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <header className="flex items-center gap-3 border-b border-[#E6EEFB] bg-white px-4 py-3.5">
        <span className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]">
          <Sparkles size={17} />
          <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-[#16A34A]" />
        </span>
        <div className="min-w-0">
          <h2 className="text-[14px] font-bold leading-tight text-[#0B1C3F]">Assistant FidClic</h2>
          <p className="text-[11.5px] text-[#16A34A]">En ligne · répond instantanément</p>
        </div>
      </header>
      {thread}
      <style>{`@keyframes hlpDot{0%,60%,100%{opacity:.25;transform:translateY(0)}30%{opacity:1;transform:translateY(-3px)}}`}</style>
    </section>
  );
}

export { BLUE as SUPPORT_BLUE };
