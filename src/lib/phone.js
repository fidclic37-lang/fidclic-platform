/**
 * Phone numbers on every signup form (user, 2026-10-09):
 *   • digits only — « # », « * », letters were accepted;
 *   • France: 0 then exactly 9 digits (06 12 34 56 78);
 *   • abroad: a country picked from the list, then the number.
 * The value handed to the API: « 0612345678 » for France, « +447700900123 »
 * abroad. The server applies the same rule (api/services/customer_fields.py,
 * with the same country codes in api/services/dial_codes.py).
 */

// [ISO 3166 code, name in French, dialling code] — France first, then A → Z.
const LIST = [
  ['FR', 'France', '33'],
  ['AF', 'Afghanistan', '93'], ['ZA', 'Afrique du Sud', '27'], ['AL', 'Albanie', '355'], ['DZ', 'Algérie', '213'],
  ['DE', 'Allemagne', '49'], ['AD', 'Andorre', '376'], ['AO', 'Angola', '244'], ['SA', 'Arabie saoudite', '966'],
  ['AR', 'Argentine', '54'], ['AM', 'Arménie', '374'], ['AU', 'Australie', '61'], ['AT', 'Autriche', '43'],
  ['AZ', 'Azerbaïdjan', '994'], ['BH', 'Bahreïn', '973'], ['BD', 'Bangladesh', '880'], ['BE', 'Belgique', '32'],
  ['BJ', 'Bénin', '229'], ['BY', 'Biélorussie', '375'], ['BO', 'Bolivie', '591'], ['BA', 'Bosnie-Herzégovine', '387'],
  ['BW', 'Botswana', '267'], ['BR', 'Brésil', '55'], ['BG', 'Bulgarie', '359'], ['BF', 'Burkina Faso', '226'],
  ['BI', 'Burundi', '257'], ['KH', 'Cambodge', '855'], ['CM', 'Cameroun', '237'], ['CA', 'Canada', '1'],
  ['CV', 'Cap-Vert', '238'], ['CL', 'Chili', '56'], ['CN', 'Chine', '86'], ['CY', 'Chypre', '357'],
  ['CO', 'Colombie', '57'], ['KM', 'Comores', '269'], ['CG', 'Congo', '242'], ['CD', 'Congo (RDC)', '243'],
  ['KR', 'Corée du Sud', '82'], ['CR', 'Costa Rica', '506'], ['CI', "Côte d'Ivoire", '225'], ['HR', 'Croatie', '385'],
  ['CU', 'Cuba', '53'], ['DK', 'Danemark', '45'], ['DJ', 'Djibouti', '253'], ['EG', 'Égypte', '20'],
  ['AE', 'Émirats arabes unis', '971'], ['EC', 'Équateur', '593'], ['ES', 'Espagne', '34'], ['EE', 'Estonie', '372'],
  ['US', 'États-Unis', '1'], ['ET', 'Éthiopie', '251'], ['FI', 'Finlande', '358'], ['GA', 'Gabon', '241'],
  ['GM', 'Gambie', '220'], ['GE', 'Géorgie', '995'], ['GH', 'Ghana', '233'], ['GR', 'Grèce', '30'],
  ['GT', 'Guatemala', '502'], ['GN', 'Guinée', '224'], ['GQ', 'Guinée équatoriale', '240'], ['GW', 'Guinée-Bissau', '245'], ['GP', 'Guadeloupe', '590'], ['GF', 'Guyane', '594'],
  ['HT', 'Haïti', '509'], ['HN', 'Honduras', '504'], ['HK', 'Hong Kong', '852'], ['HU', 'Hongrie', '36'],
  ['IN', 'Inde', '91'], ['ID', 'Indonésie', '62'], ['IQ', 'Irak', '964'], ['IR', 'Iran', '98'],
  ['IE', 'Irlande', '353'], ['IS', 'Islande', '354'], ['IL', 'Israël', '972'], ['IT', 'Italie', '39'],
  ['JM', 'Jamaïque', '1'], ['JP', 'Japon', '81'], ['JO', 'Jordanie', '962'], ['KZ', 'Kazakhstan', '7'],
  ['KE', 'Kenya', '254'], ['XK', 'Kosovo', '383'], ['KW', 'Koweït', '965'], ['LA', 'Laos', '856'],
  ['LV', 'Lettonie', '371'], ['LB', 'Liban', '961'], ['LR', 'Liberia', '231'], ['LY', 'Libye', '218'],
  ['LI', 'Liechtenstein', '423'], ['LT', 'Lituanie', '370'], ['LU', 'Luxembourg', '352'], ['MO', 'Macao', '853'],
  ['MK', 'Macédoine du Nord', '389'], ['MG', 'Madagascar', '261'], ['MY', 'Malaisie', '60'], ['MW', 'Malawi', '265'],
  ['MV', 'Maldives', '960'], ['ML', 'Mali', '223'], ['MT', 'Malte', '356'], ['MA', 'Maroc', '212'],
  ['MU', 'Maurice', '230'], ['MR', 'Mauritanie', '222'], ['MX', 'Mexique', '52'], ['MD', 'Moldavie', '373'],
  ['MC', 'Monaco', '377'], ['MN', 'Mongolie', '976'], ['ME', 'Monténégro', '382'], ['MZ', 'Mozambique', '258'],
  ['MM', 'Myanmar', '95'], ['NA', 'Namibie', '264'], ['NP', 'Népal', '977'], ['NI', 'Nicaragua', '505'],
  ['NE', 'Niger', '227'], ['NG', 'Nigeria', '234'], ['NO', 'Norvège', '47'], ['NC', 'Nouvelle-Calédonie', '687'],
  ['NZ', 'Nouvelle-Zélande', '64'], ['OM', 'Oman', '968'], ['UG', 'Ouganda', '256'], ['UZ', 'Ouzbékistan', '998'],
  ['PK', 'Pakistan', '92'], ['PS', 'Palestine', '970'], ['PA', 'Panama', '507'], ['PY', 'Paraguay', '595'],
  ['NL', 'Pays-Bas', '31'], ['PE', 'Pérou', '51'], ['PH', 'Philippines', '63'], ['PL', 'Pologne', '48'],
  ['PF', 'Polynésie française', '689'], ['PT', 'Portugal', '351'], ['QA', 'Qatar', '974'], ['DO', 'République dominicaine', '1'],
  ['CZ', 'République tchèque', '420'], ['RO', 'Roumanie', '40'], ['GB', 'Royaume-Uni', '44'], ['RU', 'Russie', '7'],
  ['RE', 'La Réunion', '262'], ['RW', 'Rwanda', '250'], ['MQ', 'Martinique', '596'], ['YT', 'Mayotte', '262'], ['SM', 'Saint-Marin', '378'], ['PM', 'Saint-Pierre-et-Miquelon', '508'], ['SV', 'Salvador', '503'],
  ['SN', 'Sénégal', '221'], ['RS', 'Serbie', '381'], ['SC', 'Seychelles', '248'], ['SL', 'Sierra Leone', '232'],
  ['SG', 'Singapour', '65'], ['SK', 'Slovaquie', '421'], ['SI', 'Slovénie', '386'], ['SO', 'Somalie', '252'],
  ['SD', 'Soudan', '249'], ['LK', 'Sri Lanka', '94'], ['SE', 'Suède', '46'], ['CH', 'Suisse', '41'],
  ['SR', 'Suriname', '597'], ['SY', 'Syrie', '963'], ['TW', 'Taïwan', '886'], ['TZ', 'Tanzanie', '255'],
  ['TD', 'Tchad', '235'], ['TH', 'Thaïlande', '66'], ['TG', 'Togo', '228'], ['TN', 'Tunisie', '216'],
  ['TR', 'Turquie', '90'], ['UA', 'Ukraine', '380'], ['UY', 'Uruguay', '598'], ['VE', 'Venezuela', '58'],
  ['VN', 'Viêt Nam', '84'], ['WF', 'Wallis-et-Futuna', '681'], ['YE', 'Yémen', '967'], ['ZM', 'Zambie', '260'],
  ['ZW', 'Zimbabwe', '263'],
];
export const COUNTRIES = [LIST[0], ...LIST.slice(1).sort((a, b) => a[1].localeCompare(b[1], 'fr'))];

export const flagOf = (iso) => String(iso || '').toUpperCase()
  .replace(/[A-Z]/g, (c) => String.fromCodePoint(0x1f1e6 + c.charCodeAt(0) - 65));

const byIso = Object.fromEntries(COUNTRIES.map(([iso, name, dial]) => [iso, { iso, name, dial }]));
export const country = (iso) => byIso[iso] || byIso.FR;

/** Keep digits only — « # », « * », letters, spaces never reach the field. */
export const onlyDigits = (s) => String(s ?? '').replace(/\D/g, '');

/**
 * A stored value (« 0612345678 », « +447700900123 », older « 06 12 34 56 78 »)
 * → { iso, national } for the field. The longest matching code wins; a code
 * shared by several countries (+1, +7) opens on the first of them.
 */
export function splitPhone(value, fallbackIso = 'FR') {
  const raw = String(value ?? '').trim();
  if (!raw.startsWith('+') && !raw.startsWith('00')) return { iso: fallbackIso, national: onlyDigits(raw) };
  let digits = onlyDigits(raw);
  if (raw.startsWith('00')) digits = digits.slice(2);
  if (digits.startsWith('33')) {
    const rest = digits.slice(2);
    return { iso: 'FR', national: rest.startsWith('0') ? rest : `0${rest}` };
  }
  for (let n = 3; n >= 1; n -= 1) {
    const hit = COUNTRIES.find(([, , dial]) => dial === digits.slice(0, n));
    if (hit) return { iso: hit[0], national: digits.slice(n) };
  }
  return { iso: fallbackIso, national: digits };
}

/** { iso, national } → the value the API stores. */
export function joinPhone(iso, national) {
  const digits = onlyDigits(national);
  if (!digits) return '';
  if (iso === 'FR') return digits;
  const { dial } = country(iso);
  // the trunk 0 (« 07700 900123 » in the UK) is not dialled from abroad — but Italy keeps it
  const rest = dial === '39' ? digits : digits.replace(/^0/, '');
  return `+${dial}${rest}`;
}

/** null when fine, otherwise the French message to show. */
export function phoneError(iso, national) {
  const digits = onlyDigits(national);
  if (!digits) return 'Indiquez votre numéro de téléphone.';
  if (iso === 'FR') {
    return /^0[1-9]\d{8}$/.test(digits)
      ? null
      : 'Numéro de téléphone français : 0 suivi de 9 chiffres (par exemple 06 12 34 56 78).';
  }
  const full = joinPhone(iso, digits).slice(1);
  const rest = full.length - country(iso).dial.length;
  return rest >= 4 && full.length <= 15 ? null : 'Numéro de téléphone invalide pour ce pays.';
}
