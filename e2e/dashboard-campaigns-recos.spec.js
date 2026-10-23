// The dashboard (user, 2026-10-23):
//  1. « Performance des campagnes »: a card opened the Campagnes page instead
//     of what it counts — it now opens the campaigns, clients, clicks or sales
//     behind it, and a campaign opens its detail;
//  2. « Créer une offre » under « Recommandations pour vous » opened the
//     loyalty card page — every recommendation now opens the composer itself.
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test.use({ viewport: { width: 1536, height: 960 } });

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store]);
  return { H: { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) }, store };
}

test('the campaign cards open what they count', async ({ page, request }) => {
  const { H, store } = await asOwner(page, request);
  const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
  const slug = (pub.stores || []).find((x) => x.id === store)?.slug;
  const name = `Tableau ${Date.now() % 100000}`;
  const made = await (await request.post('/api/join/cafe-lumiere', { data: {
    name, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '03/04/1992',
    consent: true, ...(slug ? { store: slug } : {}) } })).json();
  const rows = (await (await request.get(`/api/owner/clients/list?per_page=20&search=${encodeURIComponent(name)}`, { headers: H })).json()).rows || [];
  const cid = made.customer_id || rows.find((c) => c.name === name)?.id;
  const title = `Pour le tableau ${Date.now() % 100000}`;
  const sent = await request.post('/api/owner/campaigns/compose', { headers: H,
    data: { kind: 'nouveaute', title, message: 'Bonjour !', customer_ids: [cid] } });
  expect(sent.ok(), await sent.text()).toBeTruthy();

  await page.goto('/dashboard');
  await page.getByRole('button', { name: 'Campagnes envoyées : voir le détail' }).click();
  const box = page.getByRole('dialog', { name: 'Performance des campagnes' });
  await expect(box).toBeVisible();
  await expect(page).toHaveURL(/\/dashboard(\?|$)/);                     // not sent off to Campagnes
  await expect(box.getByText(title)).toBeVisible();

  await box.getByRole('tab', { name: /Clients touchés/ }).click();
  await expect(box.getByText(name)).toBeVisible();
  await box.getByRole('tab', { name: /^Clics/ }).click();
  await expect(box.getByText(/n'est pas un clic/)).toBeVisible();
  await box.getByRole('tab', { name: /Ventes attribuées/ }).click();
  await expect(box.getByText(/même sans avoir cliqué/)).toBeVisible();

  await box.getByRole('tab', { name: /Campagnes envoyées/ }).click();
  await box.getByText(title).click();                                     // a campaign → its detail
  await expect(page.getByTestId('campaign-recipients')).toContainText(name);
});

test('« Créer une offre » opens the composer, never the card page', async ({ page, request }) => {
  await asOwner(page, request);
  // the link the dashboard's recommendation carries (api/features/dashboard_home)
  await page.goto(`/dashboard/campaigns?template=${encodeURIComponent('produit:Café crème')}`);
  const wizard = page.getByRole('dialog', { name: /Nouvelle notification/ });
  await expect(wizard).toBeVisible({ timeout: 15_000 });
  await expect(page).toHaveURL(/\/dashboard\/campaigns/);
  await expect(wizard.getByText('Durée de l\'offre')).toBeVisible();     // step 1: the offer, to set
  await expect(wizard).toContainText('« Café crème » à l\'honneur');     // its title, on the phone preview

  await page.goto('/dashboard/campaigns?nouveau=offre');
  await expect(page.getByRole('dialog', { name: /Nouvelle notification/ })).toBeVisible();

  // and on the dashboard itself, whichever recommendation is shown
  await page.goto('/dashboard');
  const offer = page.getByRole('button', { name: /^(Créer une offre|Créer la campagne|Relancer ces clients)$/ }).first();
  if (await offer.count()) {
    await offer.click();
    await expect(page).toHaveURL(/\/dashboard\/campaigns/);
    await expect(page.getByRole('dialog', { name: /Nouvelle notification/ })).toBeVisible({ timeout: 15_000 });
  }
});
