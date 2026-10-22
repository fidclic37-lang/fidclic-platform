import {
  Users, QrCode, UserCog, ShieldCheck, Wallet, Languages, Bell, Lock, Store, Plug, Target,
} from 'lucide-react';
import { canView } from '../../lib/pagePerms';

/* Paramètres — the eight sub-pages, in the sidebar's order. One list, read by
   the sidebar and by the page itself, so the two can never disagree.

   `legacy` is where the same settings live on the older all-in-one page
   (/dashboard/settings) until each sub-page is built — nothing the owner can
   set today goes out of reach in the meantime. */
export const PARAMETRES_SECTIONS = [
  { slug: 'etablissement', label: 'Établissement', icon: Store,
    title: 'Établissement',
    subtitle: 'Gérez les informations de votre commerce.' },
  { slug: 'objectifs', label: 'Objectifs et récompenses', icon: Target,
    title: 'Objectifs et récompenses',
    subtitle: 'Fixez vos propres paliers — à tant de visites, de points ou d\'euros, telle récompense.' },
  { slug: 'regles-clients', label: 'Règles clients', icon: Users,
    title: 'Règles clients',
    subtitle: 'Définissez comment FidClic classe automatiquement vos clients.' },
  { slug: 'lien-inscription', label: "Lien d'inscription & QR", icon: QrCode,
    title: "Lien d'inscription & QR code",
    subtitle: 'Là où vos clients créent leur carte — au comptoir ou sur vos réseaux.',
    legacy: 'settings-join' },
  { slug: 'equipe', label: 'Équipe & accès', icon: UserCog,
    title: 'Équipe & accès',
    subtitle: 'Donnez un accès à vos collaborateurs, chacun selon son rôle.' },
  { slug: 'donnees', label: 'Données & confidentialité', icon: ShieldCheck,
    title: 'Données & confidentialité',
    subtitle: 'Vos obligations RGPD et le nettoyage de votre fichier clients.',
    legacy: 'settings-cleanup' },
  { slug: 'abonnement', label: 'Abonnement & facturation', icon: Wallet,
    title: 'Abonnement & facturation',
    subtitle: 'Votre formule, votre essai et vos factures.',
    legacy: 'settings-billing' },
  { slug: 'preferences', label: 'Préférences', icon: Languages,
    title: 'Préférences',
    subtitle: 'Langue et formats d’affichage de votre espace.',
    legacy: 'settings-language' },
  { slug: 'notifications', label: 'Notifications', icon: Bell,
    title: 'Notifications',
    subtitle: 'Qui envoie, par quels canaux, et combien de messages au maximum.' },
  { slug: 'api', label: 'API & Intégrations', icon: Plug,
    title: 'API & Intégrations',
    subtitle: 'Reliez votre caisse, votre site et vos outils à FidClic.' },
  { slug: 'securite', label: 'Sécurité', icon: Lock,
    title: 'Sécurité',
    subtitle: 'Protégez l’accès à votre compte.' },
];

/* What each role sees of Paramètres. Administrateurs and managers manage
   their team here, and see their establishments (an administrateur edits its
   points de vente and the legal information; a manager reads). The shop-wide
   settings stay with the Propriétaire. */
export const SHARED = ['equipe', 'etablissement', 'securite', 'preferences'];

/* The owner sees every tab. Another account sees the ones its role always had,
   plus any whose own permission the owner granted it in « Équipe & accès » —
   otherwise granting « Objectifs et récompenses » showed nothing. `user` is
   optional so the old call with a bare role keeps working. */
/* Each tab's own permission (role_perms.PAGES): its own row where it has one,
   « Paramètres » for the rest. Every account sees EVERY tab (user, 2026-10-22);
   one it may not « Voir » opens on « Accès non autorisé » — never hidden, so a
   right given can never go unseen again. « Préférences » and « Sécurité » are
   the account's own: always open. */
const SECTION_PERM = { objectifs: 'milestones', equipe: 'team', abonnement: 'billing' };
export const ALWAYS_OPEN = ['preferences', 'securite'];
export const sectionAllowed = (slug, user) => {
  if (!user || user.role === 'business_owner' || user.role === 'super_admin') return true;
  if (ALWAYS_OPEN.includes(slug)) return true;
  if (slug === 'lien-inscription') return canView(user, 'employee_links') || canView(user, 'settings');
  return canView(user, SECTION_PERM[slug] || 'settings');
};
export const sectionsFor = (role, user = null) => PARAMETRES_SECTIONS.map((s) => ({
  ...s, locked: !sectionAllowed(s.slug, user || { role }),
}));

export const PARAMETRES_BASE = '/dashboard/parametres';
export const sectionPath = (slug) => `${PARAMETRES_BASE}/${slug}`;
