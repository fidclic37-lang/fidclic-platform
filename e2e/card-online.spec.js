/**
 * « Ma carte en ligne » redesign (user, 2026-11-25; mockup « Carte en ligne
 * claire »): the card's own photo — the shop's name on top, « Bonjour,
 * <prénom> ! » at its bottom just above the points box —, the points box in
 * the programme's words, three tiles (the 3rd one the store's button, set by
 * the super admin), the last activities, « Suivez-nous » always with the 4
 * networks, and the bottom bar Accueil · Historique · Récompenses · Mon
 * compte. No « Ma carte » anywhere (user, 2026-11-25). Colours come from the
 * card itself.
 *
 * The card's answer is reshaped in the browser (photo, networks, activity) —
 * the demo shop is left alone. Local server and demo data only.
 *   npx vite build && E2E_PORT=8811 npx playwright test e2e/card-online.spec.js
 */
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const SHOTS = process.env.CARD_SHOT_DIR || '';
const HERO = '/e2e-assets/hero.svg';
const LOGO = '/e2e-assets/logo.svg';
const svg = (w, h, fill) => `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">`
  + `<rect width="${w}" height="${h}" fill="${fill}"/><circle cx="${w / 2}" cy="${h / 2}" r="${h / 3}" fill="#d9b26a"/></svg>`;

const minutesAgo = (m) => new Date(Date.now() - m * 60_000).toISOString();
const daysAgo = (d) => new Date(Date.now() - d * 864e5).toISOString();

async function newCard(request, name) {
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const store = (pub.stores || [])[0]?.slug;
  const made = await (await request.post(`/api/join/${SLUG}`, { data: {
    name, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '03/04/1992',
    consent: true, ...(store ? { store } : {}) } })).json();
  expect(made.barcode_id, JSON.stringify(made).slice(0, 200)).toBeTruthy();
  return made;
}

/** Reshape GET /card/{bc}, answer /activity and the status, count what is asked. */
async function stage(page, bc, { card = {}, customer = {}, extra = {}, activity = [], status = null }) {
  const asked = [];
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith(`/api/card/${bc}`)) asked.push(`${r.method()} ${u.pathname}${u.search}`);
  });
  await page.route('**/e2e-assets/*', (route) => route.fulfill({ contentType: 'image/svg+xml',
    body: route.request().url().includes('hero') ? svg(800, 600, '#3a2a1c') : svg(120, 120, '#15120e') }));
  await page.route((u) => u.pathname === `/api/card/${bc}`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    const res = await route.fetch();
    const body = await res.json();
    body.card = { ...body.card, ...card };
    body.customer = { ...body.customer, ...customer };
    Object.assign(body, extra);
    await route.fulfill({ response: res, json: body });
  });
  await page.route((u) => u.pathname === `/api/card/${bc}/activity`, (route) => {
    const q = new URL(route.request().url()).searchParams;
    if (typeof activity === 'function') return route.fulfill({ json: activity(q) });
    const limit = Number(q.get('limit')) || 20;
    return route.fulfill({ json: { items: activity.slice(0, limit), next: null } });
  });
  if (status) {
    await page.route((u) => u.pathname === `/api/card/${bc}/notification-status`, (route) => route.fulfill({ json: status }));
  }
  return asked;
}

const noSideScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
async function shots(page, name) {
  if (!SHOTS) return;
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${SHOTS}/${name}-top.png` });
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.screenshot({ path: `${SHOTS}/${name}-bottom.png` });
  await page.evaluate(() => window.scrollTo(0, 0));
}
const cssVar = (page, name) => page.getByTestId('card-page').evaluate((el, n) => getComputedStyle(el).getPropertyValue(n).trim(), name);

test.use({ viewport: { width: 390, height: 844 } });

test('a points card: photo, greeting, the programme\'s words, activities, networks, its own colours', async ({ page, request }) => {
  const made = await newCard(request, 'Thomas Photo');
  const bc = made.barcode_id;
  const items = [
    { kind: 'visit', at: minutesAgo(3), points: 150, amount: 15, store: 'Centre' },
    { kind: 'reward', at: daysAgo(1), title: 'Café offert ☕' },
    { kind: 'referral', at: daysAgo(13), role: 'parrain', points: 300, friend: 'Léa' },
  ];
  const asked = await stage(page, bc, {
    card: { programme: 'points_euro', programme_kind: 'points_euro', points_mode: 'per_euro', points_per_euro: 10,
      reward_points: 1000, reward_description: 'Café offert', brand_color: '#1450B8', accent_color: '#F8B008',
      // the Wallet card's own colours (GET /api/card → card.pass_colors, round 4): blue band, yellow labels
      pass_colors: { background: '#1450b8', foreground: '#ffffff', label: '#f8b008', footer: '#1450b8', name: '#f8b008', poster: true },
      hero_photo_url: HERO, logo_url: LOGO, tagline: 'Votre fidélité, notre priorité',
      socials: [{ network: 'instagram', url: 'https://instagram.com/fidclic' }, { network: 'tiktok', url: 'https://www.tiktok.com/@fidclic' }],
      cta: { label: 'Prendre rendez-vous', url: 'https://www.planity.com/fidclic-tours' } },
    customer: { first_name: 'Thomas', points: 650 },
    // the home asks for 3; Historique asks for a page, then the next one (`before`)
    activity: (q) => {
      if (q.get('before') === 'c1') {
        return { items: [
          { kind: 'visit', at: daysAgo(20), points: 80 },
          { kind: 'referral', at: daysAgo(40), role: 'filleul', friend: 'Max', points: 50 },
        ], next: null };
      }
      if (q.get('limit') === '3') return { items, next: 'c1' };
      return { items: [...items, { kind: 'visit', at: daysAgo(15), points: 40 }], next: 'c1' };
    },
  });

  await page.goto(`/card/${bc}?k=${made.card_key}`);
  const hero = page.getByTestId('card-hero');
  await expect(page.getByRole('heading', { name: 'Bonjour, Thomas !' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Bonjour, Thomas !' }), 'white on the photo').toHaveCSS('color', 'rgb(255, 255, 255)');
  await expect(page.locator('body')).not.toContainText('Ravi de vous revoir');
  await expect(hero.getByTestId('hero-photo')).toHaveCSS('background-image', /hero\.svg/);
  // user, 2026-11-25: the photo fills the whole hero (cover), no blurred copy beside it
  await expect(hero.getByTestId('hero-photo')).toHaveCSS('background-size', 'cover');
  const before = await hero.evaluate((el) => {
    const b = getComputedStyle(el, '::before');
    return { content: b.content, filter: b.filter, image: b.backgroundImage };
  });
  expect(before.content === 'none' || (before.filter === 'none' && !/hero\.svg/.test(before.image)), JSON.stringify(before)).toBe(true);
  await expect(hero.getByTestId('hero-tagline')).toHaveText('Votre fidélité, notre priorité');
  // no bell, no account button in the header (user, 2026-11-25)
  await expect(hero.getByRole('link', { name: 'Notifications' })).toHaveCount(0);
  await expect(hero.getByRole('button', { name: 'Mon compte' })).toHaveCount(0);
  await expect(hero.locator('.round')).toHaveCount(0);
  const heroBox = await hero.boundingBox();
  // the shop's name at the TOP of the photo; « Bonjour, Thomas ! » at its BOTTOM,
  // just above the points box (as in PR #519 — user, 2026-11-25)
  const hello = await page.getByRole('heading', { name: 'Bonjour, Thomas !' }).boundingBox();
  const head = await hero.locator('header').boundingBox();
  expect(head.y + head.height / 2, 'shop name in the photo\'s top half').toBeLessThan(heroBox.y + heroBox.height / 2);
  // round 4 (user, 2026-11-26): compact, in the TOP-LEFT corner right under the status bar
  const brand = await hero.getByTestId('hero-brand').locator('.brand').boundingBox();
  expect(brand.y - heroBox.y, 'right under the top edge').toBeLessThan(24);
  expect(brand.x - heroBox.x, 'at the left edge').toBeLessThan(24);
  expect(brand.height, 'compact').toBeLessThan(48);
  expect(hello.y + hello.height / 2, 'greeting in the photo\'s bottom half').toBeGreaterThan(heroBox.y + heroBox.height / 2);
  expect(heroBox.height, 'hero about the mockup\'s height').toBeGreaterThan(290);
  expect(heroBox.height).toBeLessThan(400);

  const box = page.getByTestId('points-box');
  const boxTop0 = (await box.boundingBox()).y;
  expect(hello.y + hello.height, 'greeting above the points box').toBeLessThanOrEqual(boxTop0 + 1);
  expect(boxTop0 - (hello.y + hello.height), 'greeting just above the box').toBeLessThan(40);
  await expect(box).toContainText('Mes points fidélité');
  await expect(box).toContainText('650');
  await expect(box).toContainText('Plus que 350 points pour obtenir votre récompense !');
  await expect(box).toContainText(/650\s\/\s1\s000 points/);
  const boxTop = (await box.boundingBox()).y;
  expect(heroBox.y + heroBox.height - boxTop, 'the box overlaps the photo').toBeGreaterThan(30);

  // round 4: both tiles stay in this page (no link to another page)
  await expect(page.getByRole('button', { name: /Mes offres exclusives/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Parrainer un proche/ })).toBeVisible();
  await expect(page.locator(`a[href*="/card/${bc}/offres"], a[href*="/card/${bc}/partager"]`)).toHaveCount(0);
  // the 3rd tile: the store's button (super admin), opened in a new tab
  const cta = page.getByTestId('card-cta');
  await expect(cta).toHaveText(/Prendre rendez-vous/);
  await expect(cta).toHaveAttribute('href', 'https://www.planity.com/fidclic-tours');
  await expect(cta).toHaveAttribute('target', '_blank');
  await expect(cta).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(page.locator('.tiles').getByText('Historique')).toHaveCount(0);

  const acts = page.getByTestId('activity-list');
  await expect(acts.getByRole('listitem')).toHaveCount(3);
  await expect(acts.getByRole('listitem').nth(0)).toContainText('+ 150 points');
  await expect(acts.getByRole('listitem').nth(0)).toContainText('Achat en magasin');
  await expect(acts.getByRole('listitem').nth(0)).toContainText(/Aujourd’hui · \d{2}:\d{2}/);
  await expect(acts.getByRole('listitem').nth(1)).toContainText('Récompense débloquée');
  await expect(acts.getByRole('listitem').nth(1)).toContainText(/Hier · \d{2}:\d{2}/);
  await expect(acts.getByRole('listitem').nth(2)).toContainText('Parrainage validé');
  await expect(acts.getByRole('listitem').nth(2)).toContainText('Léa a rejoint');
  await expect(acts.getByRole('listitem').nth(2)).toContainText('+ 300 points');
  await expect(acts).not.toContainText(/AM|PM/);

  const follow = page.getByTestId('follow-us');
  await expect(follow.getByRole('heading', { name: 'Suivez-nous' })).toBeVisible();
  await expect(follow.getByRole('link', { name: /Nous rejoindre/ })).toHaveAttribute('href', 'https://instagram.com/fidclic');
  for (const name of ['Instagram', 'TikTok']) {
    const a = follow.getByRole('link', { name });
    await expect(a).toHaveAttribute('target', '_blank');
    await expect(a).toHaveAttribute('rel', 'noopener noreferrer');
  }
  // the 4 networks always; one not added yet says so, calmly, then goes away
  await expect(follow.locator('.so > *')).toHaveCount(4);
  for (const name of ['Facebook', 'Snapchat']) {
    await expect(follow.getByRole('link', { name })).toHaveCount(0);
    await follow.getByRole('button', { name }).click();
    const say = page.getByRole('status').filter({ hasText: 'Lien pas encore ajouté' });
    await expect(say).toBeVisible();
    await expect(say).toHaveAttribute('aria-live', 'polite');
    await expect(say).toBeHidden({ timeout: 6000 });
  }

  // its own colours: the card's blue band = the button and the fade under the photo, a pale blue page
  expect((await cssVar(page, '--btn')).toLowerCase()).toBe('#1450b8');
  expect((await cssVar(page, '--hero-fade')).toLowerCase()).toBe('#1450b8');
  expect((await cssVar(page, '--accent')).toLowerCase()).toBe('#f8b008');
  const page_ = await cssVar(page, '--page');
  expect(parseInt(page_.slice(1, 3), 16), `a pale page (${page_})`).toBeGreaterThan(225);
  expect(parseInt(page_.slice(5, 7), 16)).toBeGreaterThanOrEqual(parseInt(page_.slice(1, 3), 16));   // blue-ish
  expect(await noSideScroll(page), 'no sideways scroll at 390 px').toBeLessThanOrEqual(0);
  await shots(page, 'card-online-points-390');

  await page.waitForTimeout(800);
  expect(asked.filter((a) => a.startsWith(`GET /api/card/${bc}/activity`)), asked.join('\n')).toEqual([`GET /api/card/${bc}/activity?limit=3`]);

  // « Voir tout » — the whole history, with « Voir plus »
  await page.getByRole('button', { name: /Voir tout/ }).click();
  await expect(page).toHaveURL(/onglet=historique/);
  const all = page.getByTestId('history-list');
  await expect(all.getByRole('listitem')).toHaveCount(4);
  await page.getByRole('button', { name: 'Voir plus' }).click();
  await expect(all.getByRole('listitem')).toHaveCount(6);
  await expect(all).toContainText('Bienvenue');
  await expect(all).toContainText('parrainé par Max');
  await expect(page.getByRole('button', { name: 'Voir plus' })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: 'Historique' }), 'a real tab now, lit').toHaveAttribute('aria-selected', 'true');
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Bonjour, Thomas !' })).toBeVisible();
  // the bottom Historique opens the same list
  await page.getByRole('tab', { name: 'Historique' }).click();
  await expect(page.getByTestId('history-list')).toBeVisible();
});

test('a tampons card on a black + gold card: no photo, no networks added, no button link, calm empty history', async ({ page, request }) => {
  const made = await newCard(request, 'Inès Tampons');
  const bc = made.barcode_id;
  await stage(page, bc, {
    card: { programme: 'stamps', programme_kind: 'stamps', reward_threshold: 10, reward_description: 'Coupe offerte',
      card_bg_color: '#15120E', brand_color: null, primary_color: null, accent_color: '#C9A04A',
      hero_photo_url: null, logo_url: LOGO, tagline: '', socials: [] },
    customer: { first_name: 'Inès', cycle_visits: 3, visits: 13 },
    activity: [],
  });
  await page.goto(`/card/${bc}?k=${made.card_key}`);
  await expect(page.getByRole('heading', { name: 'Bonjour, Inès !' })).toBeVisible();
  const hero = page.getByTestId('card-hero');
  await expect(hero.getByTestId('hero-photo')).toHaveCount(0);
  await expect(hero.getByTestId('hero-logo')).toBeVisible();
  await expect(hero.getByTestId('hero-tagline')).toHaveCount(0);

  const box = page.getByTestId('points-box');
  await expect(box).toContainText('Mes tampons');
  await expect(box).toContainText(/3\s*\/ 10 tampons/);
  await expect(box).toContainText('Plus que 7 tampons pour obtenir votre récompense !');
  await expect(box).not.toContainText('points');

  await expect(page.getByTestId('activity-empty')).toBeVisible();
  await expect(page.getByTestId('activity-list').getByRole('listitem')).toHaveCount(0);
  // « Suivez-nous » is always there: the 4 networks, none added — they say so
  const follow = page.getByTestId('follow-us');
  await expect(follow.getByRole('heading', { name: 'Suivez-nous' })).toBeVisible();
  await expect(follow.getByRole('link')).toHaveCount(0);
  for (const name of ['Instagram', 'Facebook', 'TikTok', 'Snapchat']) await expect(follow.getByRole('button', { name })).toBeVisible();
  await follow.getByRole('button', { name: /Nous rejoindre/ }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Lien pas encore ajouté' })).toBeVisible();
  // the store's button: default name, no link yet → the same calm message
  const cta = page.getByTestId('card-cta');
  await expect(cta).toHaveText(/Prendre rendez-vous/);
  await expect(cta).not.toHaveAttribute('href', /./);
  await page.waitForTimeout(3000);
  await cta.click();
  await expect(page.getByRole('status').filter({ hasText: 'Lien pas encore ajouté' })).toBeVisible();

  // its own colours: a black button with gold ink, a warm page, a near-black fade
  const btn = (await cssVar(page, '--btn')).toLowerCase();
  expect(btn).toBe('#15120e');
  const ink = await cssVar(page, '--btn-ink');
  expect(parseInt(ink.slice(1, 3), 16), `gold ink (${ink})`).toBeGreaterThan(parseInt(ink.slice(5, 7), 16));
  const pg = await cssVar(page, '--page');
  expect(parseInt(pg.slice(1, 3), 16), `a warm page (${pg})`).toBeGreaterThan(parseInt(pg.slice(5, 7), 16));
  const fade = await cssVar(page, '--hero-fade');
  expect(parseInt(fade.slice(1, 3), 16), `dark fade (${fade})`).toBeLessThan(50);
  expect(await noSideScroll(page)).toBeLessThanOrEqual(0);
  await shots(page, 'card-online-stamps-390');
});

test('no « Ma carte » anywhere; the bottom bar is Accueil · Historique · Récompenses · Mon compte', async ({ page, request }) => {
  const made = await newCard(request, 'Onglets Test');
  const bc = made.barcode_id;
  await stage(page, bc, {
    card: { programme: 'points_euro', programme_kind: 'points_euro', points_mode: 'per_euro', points_per_euro: 2,
      reward_points: 100, reward_description: 'Un dessert offert', show_points: true },
    customer: { first_name: 'Onglets', points: 25, rewards_pending: 1, last_visit_date: new Date().toISOString() },
    extra: {
      auto_message: { log_id: 'am-1', title: 'Un message de la boutique', body: 'À bientôt !' },
      defis: { running: [{ id: 'd1', title: 'Défi de novembre', target: 3, progress: 1, end_date: '2026-12-31', reward: 'Un café' }], won: [] },
    },
    status: { subscribed: false, missed_count: 2, since_days: 30 },
  });
  await page.goto(`/card/${bc}?k=${made.card_key}`);
  const tab = (name) => page.getByRole('tab', { name });
  await expect(tab('Accueil')).toHaveAttribute('aria-selected', 'true');
  // Accueil: today's banners stay on the home
  await expect(page.getByText('Vous avez raté 2 offres')).toBeVisible();
  await expect(page.getByText('Un message de la boutique')).toBeVisible();

  // the bottom bar: exactly these four, in this order
  const nav = page.getByRole('navigation', { name: 'Ma carte en ligne' });
  await expect(nav.locator('[role="tablist"] > *')).toHaveText(['Accueil', 'Historique', 'Récompenses', 'Mon compte']);
  // « Ma carte » is gone: no tab, no button in the points box, no pass, no Wallet buttons, no share row
  const noMaCarte = async () => {
    await expect(page.getByText('Ma carte', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Ma carte/ })).toHaveCount(0);
    await expect(page.getByRole('tab', { name: 'Ma carte' })).toHaveCount(0);
    await expect(page.getByTestId('wallet-pass-preview')).toHaveCount(0);
    await expect(page.getByText(/Ajouter à (Apple|Google|Samsung) Wallet/)).toHaveCount(0);
    for (const name of [/Partager \/ copier/, /écran d’accueil/, /Imprimer/]) await expect(page.getByRole('button', { name })).toHaveCount(0);
  };
  await noMaCarte();

  // Historique: a real tab, lit, in the address bar
  await tab('Historique').click();
  await expect(page).toHaveURL(/onglet=historique/);
  await expect(tab('Historique')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('history-list')).toBeAttached();
  await noMaCarte();
  expect(await noSideScroll(page)).toBeLessThanOrEqual(0);

  // Récompenses: « Vos offres » as a tab of this page (round 4, user 2026-11-26)
  await expect(nav.getByRole('link')).toHaveCount(0);
  await tab('Récompenses').click();
  await expect(page).toHaveURL(/onglet=recompenses/);
  await expect(tab('Récompenses')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('offers-tab')).toBeVisible();
  await noMaCarte();

  // Mon compte: paramètres, avis, à propos, RGPD
  await tab('Mon compte').click();
  await expect(page).toHaveURL(/onglet=compte/);
  for (const text of ['Mise à jour automatique', 'Autoriser les notifications', 'Envoyer une notification test',
    'Donner mon avis', 'Télécharger mes données', 'Supprimer la carte', 'Supprimer mes données personnelles']) {
    await expect(page.getByText(text, { exact: false }).first()).toBeVisible();
  }
  await expect(page.getByRole('heading', { name: /À propos de/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Envoyer mon avis' })).toBeVisible();
  await noMaCarte();
  await shots(page, 'card-online-tab-compte');
  expect(await noSideScroll(page)).toBeLessThanOrEqual(0);

  // the back button walks the tabs back
  await page.goBack();
  await expect(tab('Récompenses')).toHaveAttribute('aria-selected', 'true');
  await page.goBack();
  await expect(tab('Historique')).toHaveAttribute('aria-selected', 'true');
  await page.goBack();
  await expect(tab('Accueil')).toHaveAttribute('aria-selected', 'true');

  // an old « Ma carte » link (?onglet=carte) lands on Accueil
  await page.goto(`/card/${bc}?onglet=carte`);
  await expect(tab('Accueil')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('heading', { name: 'Bonjour, Onglets !' })).toBeVisible();
  await noMaCarte();
});

test('the store\'s button and the networks render text, never markup', async ({ page, request }) => {
  const made = await newCard(request, 'Xss Test');
  const bc = made.barcode_id;
  const dialogs = [];
  page.on('dialog', (d) => { dialogs.push(d.message()); d.dismiss(); });
  await stage(page, bc, {
    card: { cta: { label: '<img src=x onerror=alert(1)>', url: 'javascript:alert(2)' },
      socials: [{ network: 'instagram', url: 'javascript:alert(3)' }, { network: 'facebook', url: 'https://www.facebook.com/ok' }] },
    customer: { first_name: '<b>Eve</b>' },
  });
  await page.goto(`/card/${bc}?k=${made.card_key}`);
  const cta = page.getByTestId('card-cta');
  await expect(cta).toHaveText('<img src=x onerror=alert(1)>');
  await expect(page.locator('.tiles img')).toHaveCount(0);
  await expect(cta, 'a javascript: link is no link').not.toHaveAttribute('href', /./);
  await cta.click();
  await expect(page.getByRole('status').filter({ hasText: 'Lien pas encore ajouté' })).toBeVisible();
  const follow = page.getByTestId('follow-us');
  await expect(follow.getByRole('button', { name: 'Instagram' })).toBeVisible();
  await expect(follow.getByRole('link', { name: /Nous rejoindre/ })).toHaveAttribute('href', 'https://www.facebook.com/ok');
  await expect(page.locator('a[href^="javascript"]')).toHaveCount(0);
  await page.waitForTimeout(300);
  expect(dialogs).toEqual([]);
});

test('the bottom « Récompenses » shows « Vos offres » IN the card page, Accueil comes back', async ({ page, request }) => {
  const made = await newCard(request, 'Lien Recompenses');
  const bc = made.barcode_id;
  await stage(page, bc, {
    card: { reward_description: 'Un café offert', reward_threshold: 10 },
    customer: { rewards_pending: 1 },
    extra: {
      offers: [{ id: 'o1', kind: 'campaign', title: 'Bonjour {prenom} : -20 %', body: 'Sur tout, ce week-end https://example.org/o', sent_at: daysAgo(1),
        image_url: '/e2e-assets/hero.svg' }],
      defis: { running: [{ id: 'd1', title: 'Défi de décembre', target: 3, progress: 1, end_date: '2026-12-31', reward: 'Un dessert' }],
        won: [{ id: 'w1', kind: 'parrainage', reward: 'Une boisson', expires_at: '2026-12-20' }] },
    },
  });
  const pixel = [];
  const clicks = [];
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (/\/api\/campaigns\/o1\/pixel\//.test(u.pathname)) pixel.push(u.pathname);
    if (/\/api\/campaigns\/o1\/track-click/.test(u.pathname)) clicks.push(u.pathname);
  });
  await page.goto(`/card/${bc}?k=${made.card_key}`);
  await expect(page.getByRole('heading', { name: /Bonjour/ })).toBeVisible();
  const nav = page.getByRole('navigation', { name: 'Ma carte en ligne' });
  await nav.getByRole('tab', { name: 'Récompenses' }).click();
  await expect(page).toHaveURL(new RegExp(`/card/${bc}\\?onglet=recompenses$`));
  await expect(page.getByRole('heading', { name: /^Vos offres/ })).toBeVisible();
  await expect(nav, 'the bottom bar stays').toBeVisible();
  await expect(page.getByTestId('offers-reward')).toContainText('Un café offert');
  await expect(page.getByTestId('offers-pending')).toContainText('Une récompense vous attend');
  await expect(page.getByTestId('defi-running')).toContainText('Défi de décembre');
  await expect(page.getByTestId('defi-won')).toContainText('Une boisson');
  const row = page.getByTestId('offer-row');
  await expect(row).toHaveCount(1);
  await expect(row).toContainText('Bonjour Lien : -20 %');
  // the offer's sheet: its photo, its words, the open counted (pixel), the link counted (click)
  await row.click();
  const sheet = page.getByTestId('offer-sheet');
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole('heading')).toHaveText('Bonjour Lien : -20 %');
  await expect.poll(() => pixel.length).toBe(1);
  const go = sheet.getByRole('link', { name: /En profiter/ });
  await expect(go).toHaveAttribute('href', 'https://example.org/o');
  await expect(go).toHaveAttribute('rel', 'noopener noreferrer');
  await page.context().route('https://example.org/**', (r) => r.fulfill({ body: 'ok' }));
  await go.click();
  await expect.poll(() => clicks.length).toBe(1);
  await sheet.getByRole('button', { name: 'Fermer' }).click();
  await expect(sheet).toHaveCount(0);
  // themed: the offers panel paints with the card's own variables
  const shown = await page.getByTestId('offers-reward').evaluate((el) => getComputedStyle(el.querySelector('.pic')).backgroundColor);
  const btn = await cssVar(page, '--btn');
  const hex = (rgb) => `#${rgb.match(/\d+/g).slice(0, 3).map((n) => Number(n).toString(16).padStart(2, '0')).join('')}`;
  expect(hex(shown)).toBe(btn.toLowerCase());
  expect(await noSideScroll(page)).toBeLessThanOrEqual(0);
  await shots(page, 'card-online-recompenses-tab');
  await nav.getByRole('tab', { name: 'Accueil' }).click();
  await expect(page).toHaveURL(new RegExp(`/card/${bc}$`));
  await expect(page.getByRole('tab', { name: 'Accueil' })).toHaveAttribute('aria-selected', 'true');
  // « Mes offres exclusives » → the same tab, at its offers
  await page.getByRole('button', { name: /Mes offres exclusives/ }).click();
  await expect(page).toHaveURL(/onglet=recompenses/);
  await expect(page.getByTestId('offers-list')).toBeInViewport();
});

test('« Parrainer un proche » → the Parrainage view in the card page, the old /partager address too', async ({ page, request }) => {
  const made = await newCard(request, 'Vue Parrainage');
  const bc = made.barcode_id;
  const asked = await stage(page, bc, {});
  await page.goto(`/card/${bc}?k=${made.card_key}`);
  await expect(page.getByRole('heading', { name: /Bonjour/ })).toBeVisible();
  await page.getByRole('button', { name: /Parrainer un proche/ }).click();
  await expect(page).toHaveURL(new RegExp(`/card/${bc}\\?onglet=parrainage$`));
  const view = page.getByTestId('share-view');
  await expect(view).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Parrainage');
  await expect(view).toContainText('partagez votre carte');
  await expect(view.getByTestId('share-qr').locator('svg')).toBeVisible();
  const url = `${new URL(page.url()).origin}/card/${bc}`;
  await expect(view.getByTestId('share-url')).toHaveText(url);
  const wa = await view.getByRole('link', { name: 'Partager sur WhatsApp' }).getAttribute('href');
  expect(decodeURIComponent(wa)).toContain(url);
  expect(wa, 'never the owner key').not.toContain(made.card_key);
  // the bottom bar stays, no item lit (a hidden view), a way back
  const nav = page.getByRole('navigation', { name: 'Ma carte en ligne' });
  await expect(nav).toBeVisible();
  await expect(page.locator('.wcp-nav [aria-selected="true"]')).toHaveCount(0);
  expect(asked.filter((a) => a === `GET /api/card/${bc}/inviter`)).toHaveLength(1);
  expect(asked.filter((a) => a === `GET /api/card/${bc}`), 'the card is not asked again').toHaveLength(1);
  await shots(page, 'card-online-parrainage-view');
  expect(await noSideScroll(page)).toBeLessThanOrEqual(0);
  await page.getByRole('button', { name: 'Retour' }).click();
  await expect(page.getByRole('tab', { name: 'Accueil' })).toHaveAttribute('aria-selected', 'true');
  // the old address (Wallet back, SMS): the same view of the card page, the key kept on the phone
  await page.goto(`/card/${bc}/partager`);
  await expect(page).toHaveURL(new RegExp(`/card/${bc}\\?onglet=parrainage$`));
  await expect(page.getByTestId('share-view')).toBeVisible();
  await expect(page.getByTestId('card-page')).toBeVisible();
  // and /offres with the owner key (the Wallet tile)
  await page.goto(`/card/${bc}/offres?k=${made.card_key}`);
  await expect(page).toHaveURL(new RegExp(`/card/${bc}\\?onglet=recompenses$`));
  await expect(page.getByRole('tab', { name: 'Récompenses' })).toHaveAttribute('aria-selected', 'true');
});

test('the Wallet « Avantages membres » tile (?onglet=programme) still opens the programme view', async ({ page, request }) => {
  const made = await newCard(request, 'Tuile Programme');
  const bc = made.barcode_id;
  await stage(page, bc, {
    card: { programme: 'points_euro', programme_kind: 'points_euro', points_mode: 'per_euro', points_per_euro: 2,
      reward_points: 100, reward_description: 'Un dessert offert', show_points: true },
    customer: { points: 25, rewards_pending: 1 },
    extra: { defis: { running: [{ id: 'd1', title: 'Défi de novembre', target: 3, progress: 1, end_date: '2026-12-31', reward: 'Un café' }], won: [] } },
  });
  {
    await page.goto(`/card/${bc}?onglet=programme&k=${made.card_key}`);
    const panel = page.getByRole('tabpanel', { name: 'Le programme' });
    await expect(panel).toContainText('Le programme');
    await expect(page.getByTestId('programme-earning')).toContainText('2 pts par euro dépensé');
    await expect(page.getByTestId('programme-progress')).toContainText('Débloquée dès 100 points — 25 / 100');
    await expect(page.getByTestId('pending-reward')).toContainText('1 récompense à récupérer');
    await expect(page.getByTestId('defi-running')).toContainText('Défi de novembre');
    // a hidden view: no bottom item lit, and a way back
    await expect(page.locator('.wcp-nav [aria-selected="true"]')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Retour' })).toBeVisible();
  }
  await shots(page, 'card-online-programme-view');
  expect(await noSideScroll(page)).toBeLessThanOrEqual(0);
  await page.getByRole('button', { name: 'Retour' }).click();
  await expect(page.getByRole('tab', { name: 'Accueil' })).toHaveAttribute('aria-selected', 'true');
});
