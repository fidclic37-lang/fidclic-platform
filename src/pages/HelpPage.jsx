import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  LifeBuoy, MessageCircle, Mail, Phone, Search, ChevronDown, ArrowRight,
  Loader2, Clock, BookOpen,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import SupportChat from '../components/SupportChat';
// SupportModal (the older email form) is kept for rollback: requests now open a
// conversation in « Mes demandes » (Centre de support, 2026-10-01).
import MyRequests from '../components/support/MyRequests';

/**
 * Besoin d'aide ? — the support page, built to the approved mockup.
 *
 * Three ways to reach a human across the top, the assistant on the right, and
 * the FAQ on the left. Everything on this page reads the same knowledge base
 * (/api/support/kb): the FAQ list *is* what the assistant answers from, so an
 * article added on the backend appears in both at once — the accordion can
 * never drift from what the chat says.
 *
 * A question opened in the FAQ can be handed to the assistant with one click
 * ("Demander à l'assistant"), which is how a merchant goes from reading to a
 * follow-up question without retyping anything.
 */
const BLUE = '#2F6BFF';

/* ── mockup building blocks ───────────────────────────────────────────── */
const ContactCard = ({ icon: Icon, title, body, meta, cta, onClick, href, tone = 'blue' }) => {
  const tones = {
    blue:  { bg: '#EAF1FF', fg: BLUE },
    green: { bg: '#E7F7EE', fg: '#0F8B58' },
    amber: { bg: '#FFF3E3', fg: '#B45309' },
  }[tone];
  const Wrap = href ? 'a' : 'button';
  return (
    <Wrap
      {...(href ? { href } : { type: 'button', onClick })}
      className="group flex w-full flex-col rounded-2xl border border-[#E6EEFB] bg-white p-5 text-left shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] transition hover:border-[#2F6BFF] hover:shadow-[0_22px_48px_-30px_rgba(47,107,255,.5)]"
    >
      <span
        className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl"
        style={{ background: tones.bg, color: tones.fg }}
      >
        <Icon size={20} />
      </span>
      <h3 className="text-[15px] font-bold text-[#0B1C3F]">{title}</h3>
      <p className="mt-1 text-[12.5px] leading-snug text-[#64748B]">{body}</p>
      {meta && (
        <p className="mt-2.5 inline-flex items-center gap-1.5 text-[11.5px] font-medium" style={{ color: tones.fg }}>
          <Clock size={12} /> {meta}
        </p>
      )}
      <span className="mt-4 inline-flex items-center gap-1 text-[12.5px] font-semibold text-[#2F6BFF]">
        {cta} <ArrowRight size={13} className="transition group-hover:translate-x-0.5" />
      </span>
    </Wrap>
  );
};

const FaqRow = ({ item, open, onToggle, onAsk, onGo }) => (
  <div className="border-b border-[#EEF3FB] last:border-b-0">
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center gap-3 px-1 py-3.5 text-left"
      aria-expanded={open}
    >
      <span className="min-w-0 flex-1">
        <span className="block text-[13.5px] font-semibold leading-snug text-[#0B1C3F]">{item.title}</span>
        <span className="mt-0.5 block text-[11px] uppercase tracking-[0.08em] text-[#94A3B8]">{item.section}</span>
      </span>
      <ChevronDown
        size={17}
        className="shrink-0 text-[#94A3B8] transition-transform"
        style={{ transform: open ? 'rotate(180deg)' : 'none' }}
      />
    </button>
    {open && (
      <div className="px-1 pb-4">
        <p className="text-[13px] leading-relaxed text-[#475569]">{renderBody(item.body)}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onAsk(item.title)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#EAF1FF] px-3 py-1.5 text-[12px] font-semibold text-[#2F6BFF] transition hover:bg-[#DCE8FF]"
          >
            <MessageCircle size={13} /> Demander à l'assistant
          </button>
          {item.link && (
            <button
              type="button"
              onClick={() => onGo(item.link.to)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[#E6EEFB] px-3 py-1.5 text-[12px] font-semibold text-[#334155] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]"
            >
              {item.link.label} <ArrowRight size={13} />
            </button>
          )}
        </div>
      </div>
    )}
  </div>
);

/** The knowledge base marks page names with **bold** — render that, nothing else. */
function renderBody(body) {
  return String(body || '').split(/(\*\*[^*]+\*\*)/g).map((chunk, i) =>
    chunk.startsWith('**') && chunk.endsWith('**')
      ? <strong key={i} className="font-semibold text-[#0B1C3F]">{chunk.slice(2, -2)}</strong>
      : <React.Fragment key={i}>{chunk}</React.Fragment>);
}

/* ── page ─────────────────────────────────────────────────────────────── */
export default function HelpPage() {
  const navigate = useNavigate();
  const [kb, setKb] = useState(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [openId, setOpenId] = useState(null);
  const [seed, setSeed] = useState(null);
  const [emailOpen, setEmailOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    ownerAPI.supportKb()
      .then(({ data }) => { if (alive) setKb(data); })
      .catch(() => { if (alive) setKb({ faq: [], quick_replies: [], channels: {} }); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const faq = kb?.faq || [];
  const channels = kb?.channels || {};

  // Search is a plain accent-insensitive contains over title + body + section:
  // small list, instant, no request per keystroke.
  const fold = (s) => (s || '').normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
  const filtered = useMemo(() => {
    const q = fold(query.trim());
    if (!q) return faq;
    return faq.filter((a) => fold(`${a.title} ${a.body} ${a.section}`).includes(q));
  }, [faq, query]);

  const askAssistant = (question) => setSeed(question);

  return (
    <div className="hlp">
      <header className="mb-6">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]">
            <LifeBuoy size={21} />
          </span>
          <div>
            <h1 className="text-[22px] font-bold leading-tight text-[#0B1C3F]">Besoin d'aide ?</h1>
            <p className="text-[13px] text-[#64748B]">
              Notre équipe est là pour vous accompagner, du lundi au vendredi.
            </p>
          </div>
        </div>
      </header>

      {/* Three ways to reach us — the mockup's top row */}
      <div className="grid gap-4 md:grid-cols-3">
        <ContactCard
          icon={MessageCircle}
          tone="blue"
          title="Chat en direct"
          body="Posez votre question à l'assistant FidClic, il répond à partir de notre documentation."
          meta={`Temps de réponse moyen : ${channels.chat?.delay || 'moins de 5 min.'}`}
          cta="Démarrer le chat"
          onClick={() => document.getElementById('hlp-chat')?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
        />
        <ContactCard
          icon={Mail}
          tone="green"
          title="Nous envoyer un email"
          body="Décrivez votre situation en détail, nous vous répondons ici, dans « Mes demandes », et par email."
          meta={`Réponse ${channels.email?.delay || 'sous 24h'}`}
          cta="Écrire à l'équipe"
          onClick={() => setEmailOpen(true)}
        />
        <ContactCard
          icon={Phone}
          tone="amber"
          title="Nous appeler"
          body={channels.phone?.number || '01 84 80 10 20'}
          meta={channels.phone?.hours || 'Lun. – Ven. : 9h – 18h'}
          cta="Appeler maintenant"
          href={`tel:${(channels.phone?.number || '01 84 80 10 20').replace(/\s/g, '')}`}
        />
      </div>

      <MyRequests newOpen={emailOpen} setNewOpen={setEmailOpen} />

      <div className="mt-5 grid items-start gap-5 lg:grid-cols-[1.15fr_1fr]">
        {/* FAQ */}
        <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
          <header className="mb-4 flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]">
              <BookOpen size={19} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-[15px] font-bold leading-tight text-[#0B1C3F]">Questions fréquentes</h2>
              <p className="mt-0.5 text-[12.5px] text-[#64748B]">
                {faq.length} réponses, les mêmes que celles de l'assistant.
              </p>
            </div>
          </header>

          <div className="relative mb-2">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Rechercher une question…"
              className="w-full rounded-xl border border-[#E6EEFB] bg-[#F8FAFF] py-2.5 pl-9 pr-3 text-[13px] text-[#0B1C3F] outline-none transition placeholder:text-[#94A3B8] focus:border-[#2F6BFF]"
            />
          </div>

          {loading ? (
            <div className="flex items-center justify-center gap-2 py-10 text-[13px] text-[#64748B]">
              <Loader2 size={15} className="animate-spin" /> Chargement des réponses…
            </div>
          ) : filtered.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[#D9E4F7] px-4 py-8 text-center">
              <p className="text-[13px] font-medium text-[#0B1C3F]">Aucune réponse pour « {query} »</p>
              <p className="mt-1 text-[12.5px] text-[#64748B]">
                Posez la question à l'assistant — il cherche autrement.
              </p>
              <button
                type="button"
                onClick={() => askAssistant(query)}
                className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-[#2F6BFF] px-3.5 py-2 text-[12.5px] font-semibold text-white"
              >
                <MessageCircle size={14} /> Demander à l'assistant
              </button>
            </div>
          ) : (
            <div>
              {filtered.map((item) => (
                <FaqRow
                  key={item.id}
                  item={item}
                  open={openId === item.id}
                  onToggle={() => setOpenId(openId === item.id ? null : item.id)}
                  onAsk={askAssistant}
                  onGo={(to) => navigate(to)}
                />
              ))}
            </div>
          )}
        </section>

        {/* Assistant */}
        <div id="hlp-chat" className="lg:sticky lg:top-4">
          <SupportChat
            greeting={kb?.greeting}
            quickReplies={kb?.quick_replies || []}
            onNavigate={(to) => navigate(to)}
            onEscalate={() => { /* the merchant decides; the email card stays one click away */ }}
            seedQuestion={seed}
            onSeedConsumed={() => setSeed(null)}
          />
          <p className="mt-2.5 px-1 text-[11.5px] leading-snug text-[#94A3B8]">
            L'assistant répond à partir de la documentation FidClic. Pour un cas particulier,
            écrivez-nous — réponse {channels.email?.delay || 'sous 24h'}.
          </p>
        </div>
      </div>

    </div>
  );
}
