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

  // Clients › « Contacter (N) »: the same 15 %, said in its window
  await page.goto('/dashboard/customers');
  const contact = page.getByRole('button', { name: /^Contacter \(\d+\)/ });
  await expect(contact).toBeEnabled({ timeout: 20_000 });
  const n = Number((await contact.innerText()).replace(/\D/g, ''));
  await contact.click();
  const held = Math.floor(n * 0.15);
  if (held > 0) {
    await expect(page.getByTestId('temoin-note')).toContainText(`Groupe témoin : ${held.toLocaleString('fr-FR')} client`);
    await expect(page.getByText(`${(n - held).toLocaleString('fr-FR')} clients recevront ce message.`)).toBeVisible();
  }
  await page.screenshot({ path: 'test-results/temoin-contacter.png' });
  await page.getByRole('button', { name: 'Annuler' }).click();

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
  // « attendus de toute façon » (2026-10-25): set apart from CA FidClic, said in the panel
  const vue = (await (await request.get('/api/owner/analyses?tab=vue&days=30', { headers: SH })).json()).data.impact;
  expect(vue.note).toContain('attendus de toute façon');
  if (vue.attendus?.visits > 0) await expect(page.getByTestId('attendus')).toContainText('Attendus de toute façon');
  await page.locator('#impact').scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'test-results/attendus-analyses.png' });
  expect(errors).toEqual([]);
});
