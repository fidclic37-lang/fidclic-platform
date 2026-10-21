// « Sur la carte jusqu'au » is asked for every campaign (user, 2026-10-20: « campaign
// chala gya and expire ho gya toh hatao »): a one-client « Contacter » message
// stayed on the card a hidden 30 days and rang again a week later. The last
// step now always shows the date — a week ahead to start with — and nothing
// is sent without one.
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const ymd = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);

test.use({ viewport: { width: 1536, height: 960 } });

test('« Contacter »: the date is shown, required, and kept', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
  const slug = (pub.stores || []).find((x) => x.id === store)?.slug;
  const name = `Jusquau ${Date.now() % 100000}`;
  const made = await (await request.post('/api/join/cafe-lumiere', { data: {
    name, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '03/04/1992',
    consent: true, ...(slug ? { store: slug } : {}) } })).json();
  const SH = { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) };
  const rows = (await (await request.get(`/api/owner/clients/list?per_page=20&search=${encodeURIComponent(name)}`, { headers: SH })).json()).rows || [];
  const cid = made.customer_id || rows.find((c) => c.name === name)?.id;
  expect(cid, 'a client of this establishment').toBeTruthy();

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store]);
  await page.goto(`/dashboard/campaigns?template=client:${encodeURIComponent(cid)}&from=clients`);
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: /^Suivant/ }).click();                 // message → destinataires
  await expect(dialog.getByText('1 client choisi')).toBeVisible({ timeout: 20_000 });   // its count, before going on
  await dialog.getByRole('button', { name: /^Suivant/ }).click();                 // → planification
  await dialog.getByRole('button', { name: /Envoi immédiat/ }).click();

  const until = page.getByLabel("Sur la carte jusqu'au");
  const week = new Date(); week.setDate(week.getDate() + 7);
  await expect(until, 'a week ahead to start with').toHaveValue(ymd(week));
  await until.fill('');
  await dialog.getByRole('button', { name: /Envoyer maintenant/ }).click();
  await expect(dialog.getByText(/date de fin|jusqu'à quand/i).first()).toBeVisible();

  const in3 = new Date(); in3.setDate(in3.getDate() + 3);
  await until.fill(ymd(in3));
  await dialog.getByRole('button', { name: /Envoyer maintenant/ }).click();
  await expect(page.getByText(/Notification envoyée/)).toBeVisible({ timeout: 15_000 });

  const list = await (await request.get('/api/owner/campaigns/list?per_page=50', { headers: SH })).json();
  const sent = (list.rows || []).find((c) => (c.title || c.name || '').includes('Une attention'));
  expect(sent, 'the « Contacter » campaign is listed').toBeTruthy();
  const det = await (await request.get(`/api/owner/campaigns/${sent.id}/detail`, { headers: SH })).json();
  expect(String(det.live_until || '').slice(0, 10) >= ymd(in3) && String(det.live_until || '').slice(0, 10) <= ymd(new Date(in3.getTime() + 86400000)),
    `on the card until the day chosen (${det.live_until})`).toBeTruthy();
});
