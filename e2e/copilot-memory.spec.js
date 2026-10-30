/**
 * La mémoire du Copilote (user, 2026-10-30): « Retiens que… » in the chat is
 * kept at once and listed in « Ce que FidClic IA retient » (the Copilote and
 * Paramètres › Préférences), where the owner edits and deletes it; the whole
 * conversation stays, older pages on demand. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('the Copilote remembers, and the owner keeps the last word', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const SH = { ...H, 'X-FidClic-Store': store };
  // a clean list for this run
  for (const it of (await (await request.get('/api/me/ai-memory', { headers: H })).json()).items) {
    await request.delete(`/api/me/ai-memory/${it.id}`, { headers: H });
  }
  // the demo shop is on Pro: 5 Copilote questions a day — 3 here, « Retiens que… » below
  for (let i = 0; i < 3; i += 1) {
    await request.post('/api/owner/copilot/chat', { headers: SH, data: { message: `Question numéro ${i}` } });
  }

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);

  // Copilote: « Retiens que… »
  await page.goto('/dashboard/ai-assistant');
  const box = page.getByPlaceholder('Posez votre question...');
  await expect(box).toBeVisible({ timeout: 20_000 });
  await box.fill('Retiens que je ferme le lundi');
  await page.getByRole('button', { name: 'Envoyer' }).click();
  await expect(page.getByText(/C'est noté : « je ferme le lundi »/)).toBeVisible({ timeout: 20_000 });
  await page.getByRole('button', { name: 'Ce que FidClic IA retient' }).click();
  await expect(page.getByTestId('ai-memory').getByText('je ferme le lundi', { exact: true })).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: 'test-results/copilot-memory.png' });
  await page.keyboard.press('Escape');
  await page.reload();

  // the conversation is kept (older pages on demand: api/tests/test_copilot_memory.py)
  await expect(page.getByText('Question numéro 0', { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('Retiens que je ferme le lundi')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Voir les messages précédents' })).toHaveCount(0);

  // Paramètres › Préférences: add, edit, delete
  await page.goto('/dashboard/parametres/preferences');
  const list = page.getByTestId('ai-memory');
  await expect(list.getByText('je ferme le lundi', { exact: true })).toBeVisible({ timeout: 20_000 });
  await page.getByLabel('Ajouter ce que FidClic IA doit retenir').fill('Ma cible : les étudiants');
  await list.getByRole('button', { name: 'Ajouter' }).click();
  await expect(list.getByText('Ma cible : les étudiants', { exact: true })).toBeVisible();
  await list.getByRole('button', { name: 'Modifier « Ma cible : les étudiants »' }).click();
  await list.getByLabel('Nouveau texte').fill('Ma cible : les étudiants et les familles');
  await list.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(list.getByText('Ma cible : les étudiants et les familles', { exact: true })).toBeVisible();
  await list.getByRole('button', { name: 'Supprimer « je ferme le lundi »' }).click();
  await expect(list.getByText('je ferme le lundi', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: 'test-results/ai-memory-preferences.png' });

  // a deleted fact: the message it came from is marked « oublié » in the chat
  await page.goto('/dashboard/ai-assistant');
  await expect(page.getByTestId('chat-forgotten').first()).toHaveText('Oublié par FidClic IA', { timeout: 20_000 });
  expect(errors).toEqual([]);
});
