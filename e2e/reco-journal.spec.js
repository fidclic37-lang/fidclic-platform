/**
 * Le journal des recommandations (user, 2026-10-29): an idea taken from a
 * surface opens the composer with ?from=<surface>; the campaign sent keeps
 * which idea it came from; Super admin › FIDCLIC AI › Recommandations shows
 * adoption, acceptance, execution and ROI. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };       // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

test('an idea is followed from the page to the send, and counted for the super admin', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const admin = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const AH = { Authorization: `Bearer ${admin.access_token}` };
  const before = await (await request.get('/api/admin/ai/recos?days=1', { headers: AH })).json();
  const surf = (d, s) => (d.by_surface || []).find((r) => r.surface === s) || { opened: 0, sent: 0, shown: 0 };

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);

  // Copilote: its « Créer… » opens the composer saying where it came from
  await page.goto('/dashboard/ai-assistant');
  const cta = page.locator('[data-testid="reco-cta"]').first();
  await expect(cta).toBeVisible({ timeout: 20_000 });
  const [req] = await Promise.all([
    page.waitForRequest((r) => r.url().includes('/owner/insights/templates/') && r.url().includes('from=copilote'), { timeout: 20_000 }),
    cta.click(),
  ]);
  expect(req.url()).toContain('from=copilote');
  await page.keyboard.press('Escape').catch(() => {});

  // « FidClic IA a repéré » → the composer → sent: the campaign keeps its idea
  await page.goto('/dashboard/campaigns?template=ia:en_retard&from=repere');
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible({ timeout: 20_000 });
  await dialog.getByRole('button', { name: /^Suivant/ }).click();
  // the demo store may have nobody late today: everyone, the idea stays « ia:en_retard »
  await dialog.getByRole('button', { name: /Tous les clients/ }).click();
  await expect(dialog.getByTestId('temoin-note')).toBeVisible({ timeout: 20_000 });   // counted: there are clients
  await dialog.getByRole('button', { name: /^Suivant/ }).click();
  await dialog.getByRole('button', { name: /Envoi immédiat/ }).click();
  const until = page.getByLabel("Sur la carte jusqu'au");
  const in3 = new Date(); in3.setDate(in3.getDate() + 3);
  await until.fill(ymd(in3));
  const composed = page.waitForRequest((r) => r.url().includes('/owner/campaigns/compose') && r.method() === 'POST', { timeout: 30_000 });
  await dialog.getByRole('button', { name: /Envoyer maintenant/ }).click();
  // « Déjà contactés » (clients messaged lately in the demo): send to them all the same
  const again = page.getByRole('button', { name: /^Envoyer à \d+ clients?$/ });
  await again.waitFor({ state: 'visible', timeout: 10_000 }).then(() => again.click()).catch(() => {});
  const compose = await composed;
  const body = compose.postDataJSON();
  expect(body.reco_key).toBe('ia:en_retard');
  expect(body.reco_surface).toBe('repere');
  await expect(page.getByText(/Notification envoyée/)).toBeVisible({ timeout: 20_000 });

  const after = await (await request.get('/api/admin/ai/recos?days=1', { headers: AH })).json();
  expect(surf(after, 'copilote').opened).toBeGreaterThanOrEqual(surf(before, 'copilote').opened);
  expect(surf(after, 'repere').sent).toBe(surf(before, 'repere').sent + 1);
  expect((after.by_key || []).some((r) => r.key === 'ia:en_retard' && r.sent >= 1)).toBeTruthy();

  expect(errors).toEqual([]);
});

test('Super admin › FIDCLIC AI › Recommandations', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const admin = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), admin.access_token);
  await page.goto('/admin/ai/recommandations');
  await expect(page.getByRole('heading', { name: 'Recommandations de FidClic IA' })).toBeVisible({ timeout: 20_000 });
  const kp = page.getByTestId('reco-kpis');
  for (const label of ['Adoption', 'Acceptation', 'Exécution', 'Gain mesuré']) await expect(kp).toContainText(label);
  await expect(page.getByTestId('reco-by-key')).toContainText('ia:en_retard');
  await page.screenshot({ path: 'test-results/reco-admin.png' });
  expect(errors).toEqual([]);
});
