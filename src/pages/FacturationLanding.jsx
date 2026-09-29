/**
 * FacturationLanding — the dedicated marketing page for the e-invoicing module.
 * Route: /facturation-electronique  (public)
 *
 * WHY A WHOLE PAGE
 *   The 2026 reform is a DEADLINE, and deadlines convert. A visitor arriving on
 *   this page has one question — "what exactly do I have to do, and by when?" —
 *   and deserves a full answer, not a teaser wedged between loyalty sections.
 *
 * STRUCTURE (deliberate order)
 *   hero → timeline (urgency) → what changes (jargon → plain French) →
 *   how FidClic handles it → Bouclier Fiscal (the differentiator) →
 *   who it's for → FAQ (objection handling) → CTA
 */
import React from 'react';
import { Link } from 'react-router-dom';
import {
  ReceiptText, Inbox, BarChart3, FileCheck2, ShieldCheck, Check, ArrowRight,
  CalendarClock, AlertTriangle, Building2, Sparkles, Zap,
} from 'lucide-react';
import { C, Eyebrow, MarketingNav, MarketingFooter, Faq } from '../components/MarketingChrome';

const TIMELINE = [
  { date: '1 septembre 2026', tag: 'Toutes les entreprises', color: C.terracotta, bg: C.shellPink,
    title: 'Réception obligatoire',
    body: "Votre entreprise doit être capable de RECEVOIR des factures électroniques. Vos fournisseurs commenceront à en envoyer — sans solution, elles n'arriveront nulle part." },
  { date: '1 septembre 2026', tag: 'Grandes entreprises & ETI', color: C.ochre, bg: C.butter,
    title: 'Émission + e-reporting',
    body: "Les grandes entreprises et ETI doivent émettre en électronique et transmettre leurs données de transaction." },
  { date: '1 janvier 2027', tag: 'Régime simplifié', color: C.teal, bg: C.mint,
    title: 'Fin de la CA12',
    body: "Le régime réel simplifié de TVA disparaît : passage à des déclarations trimestrielles (CA3). Un vrai changement de trésorerie que peu d'entreprises anticipent." },
  { date: '1 septembre 2027', tag: 'TPE, PME, micro', color: C.lavender, bg: C.lilac,
    title: 'Émission obligatoire pour tous',
    body: "À votre tour : toutes vos factures B2B devront partir au format électronique, via une plateforme agréée. Et vos ventes aux particuliers devront être déclarées (e-reporting)." },
];

const JARGON = [
  { term: 'Facture électronique', plain: "Ce n'est pas un PDF envoyé par mail. C'est un fichier structuré que les logiciels lisent automatiquement — et qui transite par un circuit officiel." },
  { term: 'Plateforme agréée (PA)', plain: "Le « bureau de poste recommandé » des factures : une plateforme validée par l'État par laquelle vos factures doivent obligatoirement passer." },
  { term: 'Factur-X', plain: "Le format retenu en France : un PDF que vous lisez normalement, avec les données cachées à l'intérieur pour les machines. Le meilleur des deux mondes." },
  { term: 'E-reporting', plain: "Vos ventes aux particuliers ne donnent pas lieu à une facture électronique — vous transmettez simplement des totaux à l'administration, à échéances fixes." },
  { term: 'Annuaire', plain: "Le répertoire national qui sait sur quelle plateforme se trouve chaque entreprise, pour router les factures au bon endroit." },
  { term: 'Avoir', plain: "En France, on ne supprime jamais une facture envoyée : on l'annule ou on la corrige par un avoir. FidClic applique cette règle automatiquement." },
];

const PILLARS = [
  { icon: ReceiptText, c: C.sky, bg: C.azure, title: 'Émettre',
    lines: ['Facture créée comme avant : un formulaire, trois champs',
            'Conversion au format légal et transmission via plateforme agréée',
            'Suivi du cycle de vie : envoyée, reçue, acceptée, refusée, payée'] },
  { icon: Inbox, c: C.teal, bg: C.mint, title: 'Recevoir',
    lines: ['Les factures fournisseurs arrivent directement dans votre espace',
            'Classées, horodatées, prêtes pour votre comptable',
            'Plus de PDF perdus au fond de la boîte mail'] },
  { icon: BarChart3, c: C.lavender, bg: C.lilac, title: 'Déclarer',
    lines: ['E-reporting de vos ventes aux particuliers, aux bonnes échéances',
            'Totaux calculés automatiquement par taux de TVA',
            'Historique conservé, prêt en cas de contrôle'] },
  { icon: FileCheck2, c: C.sage, bg: C.meadow, title: 'Corriger',
    lines: ['Une erreur ? Un avoir, comme la loi l\'exige',
            'La facture d\'origine reste intacte et traçable',
            'Le score de conformité se met à jour immédiatement'] },
];

const FAQ_ITEMS = [
  { q: "Je suis une petite entreprise, suis-je vraiment concerné ?",
    a: "Oui. Toutes les entreprises assujetties à la TVA sont concernées, quelle que soit leur taille. Vous devez pouvoir recevoir des factures électroniques dès le 1er septembre 2026, et les émettre à partir du 1er septembre 2027." },
  { q: "Dois-je changer de logiciel de caisse ?",
    a: "Non. Votre caisse continue son travail (elle doit simplement être certifiée NF525). FidClic s'occupe des factures — celles que vous émettez à des entreprises, et surtout celles que vos fournisseurs vous envoient : votre caisse, elle, ne sait pas les recevoir." },
  { q: "Est-ce que je dois comprendre Factur-X, l'annuaire, les plateformes ?",
    a: "Non, et c'est tout l'intérêt. Vous remplissez une facture comme aujourd'hui. Le format légal, la plateforme agréée, le routage et la transmission à l'administration sont gérés en arrière-plan. Vous ne verrez jamais un fichier XML." },
  { q: "Et si une facture est rejetée ?",
    a: "Vous le voyez immédiatement, avec la raison en français clair — et souvent avant l'envoi, puisque nous vérifions les identifiants (SIREN/SIRET) en amont. Une facture rejetée n'est jamais perdue : elle devient une tâche à traiter." },
  { q: "Mes données restent-elles les miennes ?",
    a: "Oui, sans condition. Vous pouvez exporter l'intégralité de vos factures et documents à tout moment, dans des formats standards. Aucun verrouillage, aucune négociation." },
  { q: "Je travaille déjà avec un expert-comptable.",
    a: "Parfait — invitez-le. Il accède à votre dossier depuis son Espace Cabinet, voit vos factures et exporte vos écritures vers son propre logiciel de production. Il n'a rien à changer de son côté." },
];

export default function FacturationLanding() {
  return (
    <div data-currency="eur" className="min-h-screen font-['Inter'] antialiased" style={{ background: C.cream, color: C.inkDeep }}>
      <MarketingNav active="/facturation-electronique" />

      {/* ───────────── HERO ───────────── */}
      <section className="relative pt-32 pb-16 lg:pt-40 lg:pb-24 overflow-hidden">
        <div aria-hidden="true" className="absolute -top-32 right-0 w-[34rem] h-[34rem] rounded-full blur-3xl opacity-50"
             style={{ background: `radial-gradient(circle, ${C.azure}, transparent 70%)` }} />
        <div aria-hidden="true" className="absolute top-40 -left-24 w-96 h-96 rounded-full blur-3xl opacity-40"
             style={{ background: `radial-gradient(circle, ${C.lilac}, transparent 70%)` }} />
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative">
          <div className="grid lg:grid-cols-2 gap-14 items-center">
            <div>
              <Eyebrow color={C.sky} bg={C.azure}>Réforme 2026-2027</Eyebrow>
              <h1 className="font-['Cormorant_Garamond'] text-5xl md:text-6xl font-bold leading-[1.08] mt-4">
                La facturation<br />électronique,{' '}
                <span className="bg-clip-text text-transparent"
                      style={{ backgroundImage: `linear-gradient(135deg, ${C.sky} 0%, ${C.lavender} 100%)` }}>
                  sans jargon<br />et sans stress
                </span>
              </h1>
              <p className="mt-6 text-lg leading-relaxed" style={{ color: C.inkMute }}>
                Une loi arrive. Elle change la façon dont chaque entreprise française
                facture. Vous n'avez ni le temps ni l'envie de devenir expert du sujet —
                c'est exactement pour ça que FidClic existe.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link to="/register"
                      className="inline-flex items-center gap-2 text-white px-7 py-3.5 rounded-full font-semibold shadow-md transition-all hover:shadow-lg hover:-translate-y-0.5"
                      style={{ background: `linear-gradient(135deg, ${C.sky} 0%, ${C.lavender} 100%)` }}>
                  Préparer mon entreprise <ArrowRight size={18} />
                </Link>
                <Link to="/experts-comptables"
                      className="inline-flex items-center gap-2 px-7 py-3.5 rounded-full font-semibold border bg-white transition-all hover:-translate-y-0.5"
                      style={{ borderColor: C.hairline, color: C.inkSoft }}>
                  <Building2 size={18} /> Je suis expert-comptable
                </Link>
              </div>
              <div className="mt-7 flex flex-wrap gap-x-6 gap-y-2 text-sm" style={{ color: C.inkFaint }}>
                {['Module optionnel', 'Vos données exportables à tout moment', 'Conçu pour les TPE'].map((t) => (
                  <span key={t} className="flex items-center gap-1.5">
                    <Check size={14} style={{ color: C.sage }} /> {t}
                  </span>
                ))}
              </div>
            </div>

            {/* hero mockup — invoice with 4 status chips (the real product) */}
            <div className="relative">
              <div className="rounded-3xl bg-white border shadow-xl overflow-hidden" style={{ borderColor: C.hairline }}>
                <div className="flex items-center gap-2 px-4 py-3 border-b" style={{ background: C.sand, borderColor: C.hairline }}>
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: C.coral }} />
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: C.ochre }} />
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: C.sage }} />
                  <span className="flex-1 text-center text-[11px]" style={{ color: C.inkFaint }}>Mes factures</span>
                </div>
                <div className="p-5 space-y-2.5">
                  {[
                    ['FAC-2026-0012', 'Solutions RH SARL', '1 200,00 €', [['Envoyée', C.sky], ['Validée', C.sage], ['Impayée', C.inkFaint]]],
                    ['FAC-2026-0011', 'Traiteur Belleville', '3 480,00 €', [['Acceptée', C.sage], ['Validée', C.sage], ['Payée', C.sage]]],
                    ['FAC-2026-0010', 'byblos', '3 000,00 €', [['Refusée', C.terracotta], ['À corriger', C.ochre], ['Impayée', C.inkFaint]]],
                  ].map(([num, who, amt, chips]) => (
                    <div key={num} className="rounded-2xl border px-3.5 py-3" style={{ borderColor: C.hairline }}>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-[13px] font-bold" style={{ color: C.inkDeep }}>{num}</span>
                        <span className="text-[12px] flex-1 truncate" style={{ color: C.inkMute }}>{who}</span>
                        <span className="text-[13px] font-semibold" style={{ color: C.inkDeep }}>{amt}</span>
                      </div>
                      <div className="flex gap-1.5">
                        {chips.map(([label, col]) => (
                          <span key={label} className="text-[10px] font-bold px-2 py-0.5 rounded"
                                style={{ color: col, background: col + '1A' }}>{label}</span>
                        ))}
                      </div>
                    </div>
                  ))}
                  <p className="text-[11px] pt-1" style={{ color: C.inkFaint }}>
                    Chaque facture a plusieurs vies : la plateforme, la révision, le paiement.
                    Vous les voyez toutes, en même temps.
                  </p>
                </div>
              </div>
              <div className="absolute -bottom-5 -left-3 rounded-2xl bg-white border px-4 py-3 shadow-lg hidden sm:flex items-center gap-2"
                   style={{ borderColor: C.hairline }}>
                <Zap size={16} style={{ color: C.ochre }} />
                <div>
                  <div className="text-[11px] font-bold" style={{ color: C.inkDeep }}>Rejet évité</div>
                  <div className="text-[10px]" style={{ color: C.inkFaint }}>SIRET vérifié avant l'envoi</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ───────────── TIMELINE ───────────── */}
      <section className="py-20 lg:py-24 border-y" style={{ background: 'white', borderColor: C.hairline }}>
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <Eyebrow color={C.terracotta} bg={C.shellPink}>Le calendrier</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold mt-3">
              Ce qui vous attend, et quand
            </h2>
            <p className="mt-4 text-lg" style={{ color: C.inkMute }}>
              Quatre dates. Trois vous concernent directement.
            </p>
          </div>
          <div className="relative">
            <div aria-hidden="true" className="absolute left-[19px] top-3 bottom-3 w-0.5 hidden sm:block"
                 style={{ background: C.hairline }} />
            <div className="space-y-5">
              {TIMELINE.map((t) => (
                <div key={t.date + t.title} className="relative flex gap-5">
                  <div className="hidden sm:flex w-10 h-10 rounded-full items-center justify-center shrink-0 border-4 border-white shadow-sm"
                       style={{ background: t.bg }}>
                    <CalendarClock size={17} style={{ color: t.color }} />
                  </div>
                  <div className="flex-1 rounded-3xl border bg-white p-6" style={{ borderColor: C.hairline }}>
                    <div className="flex flex-wrap items-center gap-3 mb-2">
                      <span className="text-sm font-extrabold" style={{ color: t.color }}>{t.date}</span>
                      <span className="text-[11px] font-bold px-2.5 py-1 rounded-full"
                            style={{ color: t.color, background: t.bg }}>{t.tag}</span>
                    </div>
                    <h3 className="text-xl font-bold mb-1.5" style={{ color: C.inkDeep }}>{t.title}</h3>
                    <p className="text-sm leading-relaxed" style={{ color: C.inkMute }}>{t.body}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-8 rounded-2xl p-5 flex items-start gap-3" style={{ background: C.butter }}>
            <AlertTriangle size={18} className="mt-0.5 shrink-0" style={{ color: C.ochre }} />
            <p className="text-sm leading-relaxed" style={{ color: C.inkSoft }}>
              <b>Le point que personne ne mentionne :</b> la fin du régime simplifié au
              1<sup>er</sup> janvier 2027 change votre trésorerie. Vous passerez d'un acompte
              deux fois par an à une déclaration tous les trimestres. Si vos clients sont
              concernés, mieux vaut le savoir maintenant qu'en mai 2027.
            </p>
          </div>
        </div>
      </section>

      {/* ───────────── JARGON → FRANÇAIS ───────────── */}
      <section className="py-20 lg:py-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <Eyebrow color={C.teal} bg={C.mint}>Le vocabulaire</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold mt-3">
              Six mots compliqués,<br />expliqués une bonne fois
            </h2>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {JARGON.map((j) => (
              <div key={j.term} className="rounded-3xl bg-white border p-6" style={{ borderColor: C.hairline }}>
                <div className="text-sm font-extrabold mb-2" style={{ color: C.teal }}>{j.term}</div>
                <p className="text-sm leading-relaxed" style={{ color: C.inkMute }}>{j.plain}</p>
              </div>
            ))}
          </div>
          <p className="text-center text-sm mt-8 italic" style={{ color: C.inkFaint }}>
            Bonne nouvelle : avec FidClic, vous n'aurez à retenir aucun de ces mots.
          </p>
        </div>
      </section>

      {/* ───────────── LES 4 PILIERS ───────────── */}
      <section className="py-20 lg:py-24" style={{ background: 'white' }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <Eyebrow color={C.sky} bg={C.azure}>Ce que fait FidClic</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold mt-3">
              Quatre choses, très bien faites
            </h2>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
            {PILLARS.map((p) => {
              const Icon = p.icon;
              return (
                <div key={p.title} className="rounded-3xl border p-6 transition-all hover:-translate-y-1 hover:shadow-lg"
                     style={{ borderColor: C.hairline, background: C.cream }}>
                  <div className="w-12 h-12 rounded-2xl flex items-center justify-center mb-4" style={{ background: p.bg }}>
                    <Icon size={22} style={{ color: p.c }} />
                  </div>
                  <h3 className="font-bold text-xl mb-3" style={{ color: C.inkDeep }}>{p.title}</h3>
                  <ul className="space-y-2">
                    {p.lines.map((l) => (
                      <li key={l} className="flex items-start gap-2 text-sm leading-relaxed" style={{ color: C.inkMute }}>
                        <Check size={14} className="mt-0.5 shrink-0" style={{ color: p.c }} /> {l}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ───────────── BOUCLIER FISCAL ───────────── */}
      <section className="py-20 lg:py-24" style={{ background: `linear-gradient(180deg, ${C.cream} 0%, ${C.sand} 100%)` }}>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="rounded-[2rem] border bg-white overflow-hidden shadow-sm" style={{ borderColor: C.hairline }}>
            <div className="grid lg:grid-cols-2">
              <div className="p-8 lg:p-12">
                <Eyebrow color={C.terracotta} bg={C.shellPink}><Sparkles size={12} /> Exclusivité FidClic</Eyebrow>
                <h2 className="font-['Cormorant_Garamond'] text-4xl font-bold mt-4 mb-4">Le Bouclier Fiscal</h2>
                <p className="text-base leading-relaxed mb-6" style={{ color: C.inkMute }}>
                  Tous les logiciels vous diront « c'est envoyé ». Aucun ne vous dit
                  <b> si vos chiffres tiennent debout</b>. Le Bouclier surveille la cohérence
                  de votre facturation en continu et vous montre exactement ce qui cloche —
                  avant que l'administration ne le remarque.
                </p>
                <ul className="space-y-3">
                  {['Factures refusées ou en erreur, repérées le jour même',
                    "Conformité DGFiP et état de votre plateforme, en un coup d'œil",
                    'Cohérence entre vos achats et vos ventes, surveillée chaque mois',
                    'Chaque point du score expliqué — jamais de boîte noire'].map((li) => (
                    <li key={li} className="flex items-start gap-2.5 text-sm" style={{ color: C.inkSoft }}>
                      <ShieldCheck size={16} className="mt-0.5 shrink-0" style={{ color: C.sage }} /> {li}
                    </li>
                  ))}
                </ul>
                <p className="text-xs italic mt-6" style={{ color: C.inkFaint }}>
                  Indicateur informatif de cohérence — ni conseil fiscal, ni ECF.
                </p>
              </div>
              <div className="p-8 lg:p-12 flex items-center justify-center"
                   style={{ background: `linear-gradient(135deg, ${C.sand} 0%, ${C.butter}99 100%)` }}>
                <div className="w-full max-w-sm rounded-3xl bg-white border p-6 shadow-sm" style={{ borderColor: C.hairline }}>
                  <div className="flex items-start gap-5">
                    <div className="shrink-0 text-center">
                      <div className="w-24 h-24 rounded-full flex items-center justify-center"
                           style={{ background: `conic-gradient(${C.ochre} 76%, ${C.hairline} 0)` }}>
                        <div className="w-[76px] h-[76px] rounded-full bg-white flex flex-col items-center justify-center">
                          <span className="text-2xl font-extrabold" style={{ color: C.ochre }}>76</span>
                          <span className="text-[10px]" style={{ color: C.inkFaint }}>/100</span>
                        </div>
                      </div>
                      <div className="mt-2 text-xs font-bold" style={{ color: C.ochre }}>À vérifier</div>
                    </div>
                    <div className="flex-1">
                      <div className="text-sm font-bold mb-2" style={{ color: C.inkDeep }}>Pourquoi ce score ?</div>
                      {[['Base', '100', C.inkMute],
                        ['1 facture refusée non corrigée', '−15', C.terracotta],
                        ['Aucune facture fournisseur reçue', '−8', C.ochre],
                        ['Conformité DGFiP activée', '±0', C.sage]].map(([l, v, col]) => (
                        <div key={l} className="flex items-center justify-between text-xs py-1 gap-3">
                          <span style={{ color: C.inkMute }}>{l}</span>
                          <span className="font-bold shrink-0" style={{ color: col }}>{v}</span>
                        </div>
                      ))}
                      <div className="flex items-center justify-between text-xs pt-2 mt-1 border-t" style={{ borderColor: C.hairline }}>
                        <span className="font-bold" style={{ color: C.inkDeep }}>Score</span>
                        <span className="font-bold" style={{ color: C.ochre }}>76/100</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ───────────── POUR QUI ───────────── */}
      <section className="py-20 lg:py-24" style={{ background: 'white' }}>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <Eyebrow color={C.sage} bg={C.meadow}>Pour qui</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold mt-3">
              Pensé pour les entreprises<br />qui n'ont pas de service comptable
            </h2>
          </div>
          <div className="grid md:grid-cols-3 gap-5">
            {[
              { t: 'Restaurants & commerces', d: "Vos fournisseurs vous enverront des factures électroniques dès 2026. Votre caisse ne sait pas les recevoir — FidClic si. Et votre programme de fidélité vit dans le même outil.", c: C.terracotta, bg: C.shellPink },
              { t: 'Artisans & services', d: "Devis, facture, relance : le cycle complet, avec la conformité incluse. Vos factures aux entreprises partent au bon format, sans que vous ayez à y penser.", c: C.teal, bg: C.mint },
              { t: 'Micro-entrepreneurs', d: "Franchise en base de TVA gérée nativement : mentions légales automatiques, aucune TVA appliquée par erreur. La réforme vous concerne aussi, dès 2026 pour la réception.", c: C.lavender, bg: C.lilac },
            ].map((x) => (
              <div key={x.t} className="rounded-3xl border p-7" style={{ borderColor: C.hairline, background: C.cream }}>
                <div className="w-10 h-1.5 rounded-full mb-5" style={{ background: x.c }} />
                <h3 className="font-bold text-lg mb-2" style={{ color: C.inkDeep }}>{x.t}</h3>
                <p className="text-sm leading-relaxed" style={{ color: C.inkMute }}>{x.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ───────────── FAQ ───────────── */}
      <section className="py-20 lg:py-24">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-10">
            <Eyebrow color={C.lavender} bg={C.lilac}>Questions fréquentes</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold mt-3">
              Ce qu'on nous demande le plus
            </h2>
          </div>
          <Faq items={FAQ_ITEMS} accent={C.sky} />
        </div>
      </section>

      {/* ───────────── CTA ───────────── */}
      <section className="py-20" style={{ background: `linear-gradient(135deg, ${C.sky} 0%, ${C.lavender} 100%)` }}>
        <div className="max-w-3xl mx-auto px-4 text-center text-white">
          <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight">
            La date ne bougera pas.<br />Votre tranquillité, si.
          </h2>
          <p className="mt-5 text-lg opacity-95">
            Activez le module quand vous voulez. Votre programme de fidélité continue
            exactement comme avant.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link to="/register"
                  className="inline-flex items-center gap-2 px-8 py-4 rounded-full font-bold bg-white shadow-lg transition-all hover:-translate-y-0.5"
                  style={{ color: C.lavender }}>
              Créer mon compte <ArrowRight size={18} />
            </Link>
            <Link to="/experts-comptables"
                  className="inline-flex items-center gap-2 px-8 py-4 rounded-full font-bold border-2 border-white/70 text-white transition-all hover:bg-white/10">
              <Building2 size={18} /> Espace expert-comptable
            </Link>
          </div>
        </div>
      </section>

      <MarketingFooter />
    </div>
  );
}
