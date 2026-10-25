/**
 * Groupe témoin (user, 2026-10-25): 15 % of a group send, drawn at random,
 * get nothing, to measure what FidClic really brings in — and the owner is
 * told: in the composer, in Paramètres › Notifications (with its switch) and
 * on Analyses (« Ce que FidClic vous rapporte vraiment »). Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('the owner is told about the groupe témoin, and can switch it', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const SH = { ...H, 'X-FidClic-Store': store };
  const all = await (await request.post('/api/owner/campaigns/audience-preview', { headers: SH, data: { audience: { mode: 'all' } } })).json();
  expect(all.temoin).toBe(Math.floor(all.count * 0.15));

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);

  // the composer: « Tous les clients » → how many are kept out, and why
  await page.goto('/dashboard/campaigns?template=ia:en_retard');
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible({ timeout: 20_000 });
  await dialog.getByRole('button', { name: /^Suivant/ }).click();
  await dialog.getByRole('button', { name: /Tous les clients/ }).click();
  const note = dialog.getByTestId('temoin-note');
  await expect(note).toContainText(`Groupe témoin : ${all.temoin.toLocaleString('fr-FR')} clients`, { timeout: 20_000 });
  await expect(note).toContainText('tirés au hasard');
  await page.screenshot({ path: 'test-results/temoin-composer.png' });
  await dialog.getByRole('button', { name: 'Fermer' }).first().click().catch(() => {});

  // Paramètres › Notifications: what it is, and the switch
  await page.goto('/dashboard/parametres/notifications');
  const card = page.getByTestId('temoin-settings');
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(card).toContainText('15 % des clients');
  await expect(card).toContainText('anniversaire, récompense, bienvenue');
  const sw = card.getByRole('switch', { name: 'Groupe témoin' });
  await expect(sw).toHaveAttribute('aria-checked', 'true');
  await card.scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'test-results/temoin-parametres.png' });
  await sw.click();
  await expect(card).toContainText('Désactivé');
  expect((await (await request.post('/api/owner/campaigns/audience-preview', { headers: SH, data: { audience: { mode: 'all' } } })).json()).temoin).toBe(0);
  await sw.click();
  await expect(sw).toHaveAttribute('aria-checked', 'true');

  // Analyses: « Ce que FidClic vous rapporte vraiment », with how it is computed
  await page.goto('/dashboard/analytics');
  const panel = page.getByTestId('uplift-panel');
  await expect(panel).toBeVisible({ timeout: 20_000 });
  await panel.getByRole('button', { name: /Comment c'est calculé/ }).click();
  await expect(panel.getByTestId('temoin-how')).toContainText('groupe témoin');
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'test-results/temoin-analyses.png' });
  expect(errors).toEqual([]);
});
