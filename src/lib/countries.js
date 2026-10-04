// Every country (ISO 3166-1 alpha-2). Names come from the browser in the
// page's language (Intl.DisplayNames), flags from the regional indicators,
// so nothing here needs translating. The countries FidClic sells in first.
const FIRST = ['FR', 'BE', 'CH', 'LU', 'MC', 'CA'];
const ALL = ('AD AE AF AG AI AL AM AO AR AT AU AW AZ BA BB BD BE BF BG BH BI BJ BM BN BO BR BS BT BW BY BZ CA CD CF CG CH CI CK CL CM CN CO CR CU CV CW CY CZ ' +
  'DE DJ DK DM DO DZ EC EE EG ER ES ET FI FJ FM FO FR GA GB GD GE GF GH GI GL GM GN GP GQ GR GT GU GW GY HK HN HR HT HU ID IE IL IN IQ IR IS IT JM JO JP ' +
  'KE KG KH KI KM KN KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MG MH MK ML MM MN MO MQ MR MT MU MV MW MX MY MZ NA NC NE NG NI NL NO NP NR NZ ' +
  'OM PA PE PF PG PH PK PL PM PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SI SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TG TH TJ TL TM TN TO TR TT TV TW TZ ' +
  'UA UG US UY UZ VA VC VE VG VI VN VU WF WS XK YE YT ZA ZM ZW').split(' ');

const flag = (code) => String.fromCodePoint(...[...code].map((c) => 0x1F1A5 + c.charCodeAt(0)));

export function countryOptions(lang = 'fr') {
  let names;
  try { names = new Intl.DisplayNames([lang, 'fr'], { type: 'region' }); } catch { names = null; }
  const label = (c) => (names ? names.of(c) : c) || c;
  const rest = ALL.filter((c) => !FIRST.includes(c))
    .map((c) => ({ code: c, flag: flag(c), label: label(c) }))
    .sort((a, b) => a.label.localeCompare(b.label, lang));
  return [...FIRST.map((c) => ({ code: c, flag: flag(c), label: label(c) })), ...rest];
}
