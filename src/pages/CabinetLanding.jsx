/**
 * CabinetLanding — the dedicated marketing page for accounting firms.
 * Route: /experts-comptables  (public)
 *
 * WHY A WHOLE PAGE
 *   The accountant is not a "segment" of the merchant story — they are the
 *   distribution channel. One cabinet brings 45 businesses. A page that speaks
 *   their language (dossiers, révision, FEC, période fiscale) does more for
 *   growth than any feature on the merchant side.
 *
 * TONE RULE
 *   Never sell them software. Sell them TIME and CONTROL — the two things they
 *   are actually short of. Every section answers "what does this remove from my
 *   week?".
 */
import React from 'react';
import { Link } from 'react-router-dom';
import {
  Building2, FolderKanban, AlertTriangle, Users, FileCheck2, ShieldCheck,
  Check, ArrowRight, Clock, Layers, Lock, ArrowUpRight,
} from 'lucide-react';
import { C, Eyebrow, MarketingNav, MarketingFooter, Faq } from '../components/MarketingChrome';

const PAINS = [
  { before: 'Vos clients seront répartis sur des dizaines de plateformes agréées différentes.',
    after: "Un seul écran pour tout le portefeuille — quelle que soit la plateforme de chaque client." },
  { before: 'Un rejet arrive par mail, se perd, et refait surface trois semaines plus tard.',
    after: "Chaque rejet devient un dossier assigné, avec une échéance. Rien ne se perd." },
  { before: "Vous découvrez les problèmes d'un dossier au moment de la clôture.",
    after: "Les dossiers à risque remontent en haut de la liste, tous les matins." },
  { before: 'Un collaborateur part, et la connaissance du dossier part avec lui.',
    after: "L'historique complet reste dans le dossier : qui a fait quoi, quand, et pourquoi." },
];

const FEATURES = [
  { icon: FolderKanban, c: C.lavender, bg: C.lilac, title: 'Portefeuille priorisé',
    body: "Tous vos dossiers sur un écran, triés par niveau de risque. Le score de conformité de chaque client se met à jour tout seul, avec le détail de ce qui cloche. Vous savez en trente secondes où passer votre journée." },
  { icon: AlertTriangle, c: C.terracotta, bg: C.shellPink, title: 'Rien ne se perd',
    body: "Rejet de plateforme, doublon, export échoué : chaque anomalie devient un dossier assigné à quelqu'un, avec une date. Fini le suivi par mail et les « je croyais que tu l'avais fait »." },
  { icon: Users, c: C.teal, bg: C.mint, title: 'Votre équipe, vos accès',
    body: "Créez les comptes de vos collaborateurs et attribuez-leur des dossiers. Chacun ne voit que les siens. Vous, vous voyez tout — y compris qui avance sur quoi, sans avoir à le demander." },
  { icon: FileCheck2, c: C.sage, bg: C.meadow, title: 'Export vers votre logiciel',
    body: "Gardez Sage, Cegid, ACD ou AGIRIS. FidClic ne remplace pas votre outil de production : il l'alimente, avec un export propre au format FEC et une protection contre les doublons." },
  { icon: ShieldCheck, c: C.ochre, bg: C.butter, title: 'Bouclier Fiscal par dossier',
    body: "Un indicateur de cohérence par client, expliqué ligne par ligne. Un argument concret à montrer en rendez-vous bilan — et un moyen de repérer un dossier qui dérape avant qu'il ne dérape vraiment." },
  { icon: Lock, c: C.sky, bg: C.azure, title: 'Cloisonnement vérifié',
    body: "Un collaborateur n'accède jamais à un dossier qui ne lui est pas attribué, et un cabinet jamais aux clients d'un autre. Ce n'est pas une promesse commerciale : c'est testé automatiquement à chaque mise en production." },
];

const STEPS = [
  { n: '1', t: 'Créez votre cabinet', d: "Quelques minutes : identité du cabinet, puis les comptes de vos collaborateurs, avec leur rôle. Vous gardez la main sur les accès." },
  { n: '2', t: 'Ajoutez vos dossiers', d: "Un numéro SIREN suffit : la raison sociale, l'adresse et le code NAF se remplissent automatiquement. Votre client reçoit son accès." },
  { n: '3', t: 'Répartissez le travail', d: "Attribuez les dossiers à vos collaborateurs. Chacun retrouve les siens en se connectant, avec ce qui reste à traiter." },
  { n: '4', t: 'Exportez, chaque mois', d: "Un export FEC par période, vérifié avant génération, importable directement dans votre logiciel de production." },
];

const FAQ_ITEMS = [
  { q: "Dois-je abandonner mon logiciel de production ?",
    a: "Non, et ce n'est pas l'objectif. FidClic se place en amont : collecte, facturation électronique, suivi des anomalies, préparation des écritures. Vous récupérez un export FEC propre et votre production continue là où elle est aujourd'hui." },
  { q: "Combien de temps pour ajouter un client ?",
    a: "Quelques minutes. Le SIREN déclenche la récupération automatique des informations légales, vous confirmez, le dossier est créé et votre client reçoit son accès. Pas de ressaisie." },
  { q: "Mes collaborateurs voient-ils tous les dossiers ?",
    a: "Uniquement ceux que vous leur attribuez. Vous, en tant qu'administrateur du cabinet, voyez l'ensemble du portefeuille ainsi que l'activité de chacun. Le cloisonnement est vérifié par des tests automatisés à chaque déploiement." },
  { q: "Et si un client change de cabinet ?",
    a: "L'accès est révocable des deux côtés, immédiatement. Les données appartiennent à l'entreprise cliente ; vous conservez la possibilité d'exporter votre travail. Aucune donnée n'est prise en otage." },
  { q: "Mes clients utilisent des plateformes agréées différentes.",
    a: "C'est justement le problème que nous adressons. Notre architecture est conçue pour agréger plusieurs plateformes dans une seule vue cabinet — un éditeur qui est lui-même plateforme agréée ne peut structurellement pas offrir cette neutralité." },
  { q: "Quel est le modèle tarifaire ?",
    a: "Par dossier et par mois, sans surprise et sans engagement caché. Nous avons vu ce que font les hausses de prix brutales dans cette profession ; notre promesse est l'inverse : un prix lisible et vos données exportables à tout moment." },
];

export default function CabinetLanding() {
  return (
    <div data-currency="eur" className="min-h-screen font-['Inter'] antialiased" style={{ background: C.cream, color: C.inkDeep }}>
      <MarketingNav active="/experts-comptables" />

      {/* ───────────── HERO ───────────── */}
      <section className="relative pt-32 pb-16 lg:pt-40 lg:pb-24 overflow-hidden">
        <div aria-hidden="true" className="absolute -top-24 -left-32 w-[32rem] h-[32rem] rounded-full blur-3xl opacity-50"
             style={{ background: `radial-gradient(circle, ${C.lilac}, transparent 70%)` }} />
        <div aria-hidden="true" className="absolute top-52 right-0 w-96 h-96 rounded-full blur-3xl opacity-40"
             style={{ background: `radial-gradient(circle, ${C.blush}, transparent 70%)` }} />
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative">
          <div className="grid lg:grid-cols-2 gap-14 items-center">
            <div>
              <Eyebrow color={C.lavender} bg={C.lilac}><Building2 size={12} /> Experts-comptables</Eyebrow>
              <h1 className="font-['Cormorant_Garamond'] text-5xl md:text-6xl font-bold leading-[1.08] mt-4">
                Tous vos dossiers.{' '}
                <span className="bg-clip-text text-transparent"
                      style={{ backgroundImage: `linear-gradient(135deg, ${C.lavender} 0%, ${C.rose} 100%)` }}>
                  Un seul écran.
                </span>
              </h1>
              <p className="mt-6 text-lg leading-relaxed" style={{ color: C.inkMute }}>
                La réforme va disperser vos clients sur des dizaines de plateformes.
                L'Espace Cabinet vous rend ce que la dispersion vous enlève : la vue
                d'ensemble, et le contrôle de votre semaine.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link to="/cabinet/inscription"
                      className="inline-flex items-center gap-2 text-white px-7 py-3.5 rounded-full font-semibold shadow-md transition-all hover:shadow-lg hover:-translate-y-0.5"
                      style={{ background: `linear-gradient(135deg, ${C.lavender} 0%, ${C.rose} 100%)` }}>
                  Créer mon cabinet <ArrowRight size={18} />
                </Link>
                <Link to="/facturation-electronique"
                      className="inline-flex items-center gap-2 px-7 py-3.5 rounded-full font-semibold border bg-white transition-all hover:-translate-y-0.5"
                      style={{ borderColor: C.hairline, color: C.inkSoft }}>
                  Voir le module Facturation <ArrowUpRight size={16} />
                </Link>
              </div>
              <div className="mt-7 flex flex-wrap gap-x-6 gap-y-2 text-sm" style={{ color: C.inkFaint }}>
                {['Vos données exportables à tout moment', 'Compatible avec votre logiciel de production', 'Cloisonnement testé automatiquement'].map((t) => (
                  <span key={t} className="flex items-center gap-1.5">
                    <Check size={14} style={{ color: C.sage }} /> {t}
                  </span>
                ))}
              </div>
            </div>

            {/* portfolio mockup */}
            <div className="relative">
              <div className="rounded-3xl bg-white border shadow-xl overflow-hidden" style={{ borderColor: C.hairline }}>
                <div className="flex items-center gap-2 px-4 py-3 border-b" style={{ background: C.sand, borderColor: C.hairline }}>
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: C.coral }} />
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: C.ochre }} />
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: C.sage }} />
                  <span className="flex-1 text-center text-[11px]" style={{ color: C.inkFaint }}>
                    Espace Cabinet — 45 dossiers
                  </span>
                </div>
                <div className="p-5">
                  <div className="grid grid-cols-3 gap-2.5 mb-4">
                    {[['3', 'Action requise', C.terracotta, C.shellPink],
                      ['9', 'À vérifier', C.ochre, C.butter],
                      ['33', 'Conformes', C.sage, C.meadow]].map(([n, l, c, bg]) => (
                      <div key={l} className="rounded-2xl p-3 text-center" style={{ background: bg }}>
                        <div className="text-xl font-extrabold" style={{ color: c }}>{n}</div>
                        <div className="text-[10px] mt-0.5" style={{ color: C.inkMute }}>{l}</div>
                      </div>
                    ))}
                  </div>
                  <div className="space-y-2">
                    {[['Café Lumière', '58/100', C.terracotta, '2 factures refusées', 'M'],
                      ['Boulangerie Dupont', '76/100', C.ochre, '3 à revoir', 'L'],
                      ['Salon Élise', '84/100', C.ochre, 'Aucune facture fournisseur', 'M'],
                      ['Garage Martin', '100/100', C.sage, 'Conforme', 'L'],
                      ['Menuiserie Petit', '100/100', C.sage, 'Conforme', 'L']].map(([name, score, c, note, who]) => (
                      <div key={name} className="flex items-center gap-2.5 rounded-2xl border px-3 py-2.5"
                           style={{ borderColor: C.hairline }}>
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: c }} />
                        <div className="flex-1 min-w-0">
                          <div className="text-[13px] font-bold truncate" style={{ color: C.inkDeep }}>{name}</div>
                          <div className="text-[11px]" style={{ color: c }}>{note}</div>
                        </div>
                        <span className="text-[11px] font-bold shrink-0" style={{ color: c }}>{score}</span>
                        <span className="w-6 h-6 rounded-full text-[10px] font-bold flex items-center justify-center shrink-0"
                              style={{ background: C.lilac, color: C.lavender }}>{who}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div className="absolute -bottom-5 -right-3 rounded-2xl bg-white border px-4 py-3 shadow-lg hidden sm:flex items-center gap-2"
                   style={{ borderColor: C.hairline }}>
                <Clock size={16} style={{ color: C.teal }} />
                <div>
                  <div className="text-[11px] font-bold" style={{ color: C.inkDeep }}>30 secondes</div>
                  <div className="text-[10px]" style={{ color: C.inkFaint }}>pour savoir où agir aujourd'hui</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ───────────── AVANT / APRÈS ───────────── */}
      <section className="py-20 lg:py-24 border-y" style={{ background: 'white', borderColor: C.hairline }}>
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <Eyebrow color={C.terracotta} bg={C.shellPink}>Le quotidien</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold mt-3">
              Ce que la réforme va casser,<br />et ce qu'on remet en place
            </h2>
          </div>
          <div className="space-y-3">
            {PAINS.map((p) => (
              <div key={p.before} className="grid md:grid-cols-2 gap-3">
                <div className="rounded-2xl p-5 border" style={{ background: C.cream, borderColor: C.hairline }}>
                  <div className="text-[11px] font-bold uppercase tracking-wide mb-2" style={{ color: C.inkFaint }}>Sans outil adapté</div>
                  <p className="text-sm leading-relaxed" style={{ color: C.inkMute }}>{p.before}</p>
                </div>
                <div className="rounded-2xl p-5 border" style={{ background: C.meadow + '66', borderColor: C.hairline }}>
                  <div className="text-[11px] font-bold uppercase tracking-wide mb-2" style={{ color: C.sage }}>Avec l'Espace Cabinet</div>
                  <p className="text-sm leading-relaxed" style={{ color: C.inkSoft }}>{p.after}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ───────────── FEATURES ───────────── */}
      <section className="py-20 lg:py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <Eyebrow color={C.lavender} bg={C.lilac}>Fonctionnalités</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold mt-3">
              Conçu avec le cabinet en tête,<br />pas le commerçant
            </h2>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map((f) => {
              const Icon = f.icon;
              return (
                <div key={f.title} className="rounded-3xl bg-white border p-7 transition-all hover:-translate-y-1 hover:shadow-lg"
                     style={{ borderColor: C.hairline }}>
                  <div className="w-12 h-12 rounded-2xl flex items-center justify-center mb-4" style={{ background: f.bg }}>
                    <Icon size={22} style={{ color: f.c }} />
                  </div>
                  <h3 className="font-bold text-lg mb-2" style={{ color: C.inkDeep }}>{f.title}</h3>
                  <p className="text-sm leading-relaxed" style={{ color: C.inkMute }}>{f.body}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ───────────── COMMENT ÇA MARCHE ───────────── */}
      <section className="py-20 lg:py-24" style={{ background: 'white' }}>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <Eyebrow color={C.teal} bg={C.mint}>Mise en route</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold mt-3">
              Quatre étapes, une après-midi
            </h2>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
            {STEPS.map((s) => (
              <div key={s.n} className="relative rounded-3xl border p-7" style={{ borderColor: C.hairline, background: C.cream }}>
                <div className="w-11 h-11 rounded-2xl flex items-center justify-center text-white font-extrabold text-lg mb-4"
                     style={{ background: `linear-gradient(135deg, ${C.lavender} 0%, ${C.rose} 100%)` }}>
                  {s.n}
                </div>
                <h3 className="font-bold text-base mb-2" style={{ color: C.inkDeep }}>{s.t}</h3>
                <p className="text-sm leading-relaxed" style={{ color: C.inkMute }}>{s.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ───────────── NEUTRALITÉ (the moat, stated plainly) ───────────── */}
      <section className="py-20 lg:py-24" style={{ background: `linear-gradient(180deg, ${C.cream} 0%, ${C.lilac}55 100%)` }}>
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <Eyebrow color={C.sky} bg={C.azure}><Layers size={12} /> Notre position</Eyebrow>
          <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold mt-4 mb-5">
            Nous ne sommes pas une plateforme agréée.<br />C'est volontaire.
          </h2>
          <p className="text-lg leading-relaxed" style={{ color: C.inkMute }}>
            Un éditeur qui est lui-même plateforme agréée a un intérêt : que vos clients
            viennent chez lui. Il ne construira jamais un écran qui affiche sereinement
            les dossiers hébergés chez ses concurrents.
          </p>
          <p className="text-lg leading-relaxed mt-4" style={{ color: C.inkMute }}>
            Nous, notre revenu ne dépend pas du tuyau emprunté par vos factures. C'est
            précisément ce qui nous permet de vous montrer <b>tous</b> vos dossiers,
            quelle que soit leur plateforme — et de rester du côté du cabinet.
          </p>
          <div className="mt-8 inline-flex flex-wrap justify-center gap-3">
            {['Neutralité vis-à-vis des plateformes', 'Aucun verrouillage de vos données', 'Tarif par dossier, lisible'].map((t) => (
              <span key={t} className="px-4 py-2 rounded-full text-sm font-semibold bg-white border"
                    style={{ borderColor: C.hairline, color: C.inkSoft }}>{t}</span>
            ))}
          </div>
        </div>
      </section>

      {/* ───────────── FAQ ───────────── */}
      <section className="py-20 lg:py-24" style={{ background: 'white' }}>
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-10">
            <Eyebrow color={C.terracotta} bg={C.shellPink}>Questions fréquentes</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold mt-3">
              Vos questions, nos réponses
            </h2>
          </div>
          <Faq items={FAQ_ITEMS} accent={C.lavender} />
        </div>
      </section>

      {/* ───────────── CTA ───────────── */}
      <section className="py-20" style={{ background: `linear-gradient(135deg, ${C.lavender} 0%, ${C.rose} 100%)` }}>
        <div className="max-w-3xl mx-auto px-4 text-center text-white">
          <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight">
            Vos clients vont vous poser<br />la question dans quelques mois.
          </h2>
          <p className="mt-5 text-lg opacity-95">
            Autant avoir la réponse — et l'outil — avant eux.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link to="/cabinet/inscription"
                  className="inline-flex items-center gap-2 px-8 py-4 rounded-full font-bold bg-white shadow-lg transition-all hover:-translate-y-0.5"
                  style={{ color: C.lavender }}>
              Créer mon cabinet <ArrowRight size={18} />
            </Link>
            <Link to="/facturation-electronique"
                  className="inline-flex items-center gap-2 px-8 py-4 rounded-full font-bold border-2 border-white/70 text-white transition-all hover:bg-white/10">
              Le module côté client
            </Link>
          </div>
        </div>
      </section>

      <MarketingFooter />
    </div>
  );
}
