/**
 * Les outils du Copilote (user, 2026-10-30): under an answer built from the
 * shop's data, « J'ai consulté : … » names what was read, each a link to its
 * page. The local server has no language model, so the chat's answer is
 * given here; what the tools read is tested in api/tests/test_copilot_tools.py.
 * Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('the answer says what it read, and each source opens its page', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);

  await page.route('**/api/owner/copilot/chat', (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        reply: 'Karim Benali est venu 3 fois ce mois-ci.', actions: [], source: 'model',
        sources: [{ label: 'Clients (« Karim »)', to: '/dashboard/customers?q=Karim' },
                  { label: 'Chiffres (ce mois)', to: '/dashboard/analytics' }],
      }),
    });
  });
  await page.goto('/dashboard/ai-assistant');
  const box = page.getByPlaceholder('Posez votre question...');
  await expect(box).toBeVisible({ timeout: 20_000 });
  await box.fill('Karim est venu combien de fois ?');
  await page.getByRole('button', { name: 'Envoyer' }).click();
  const line = page.getByTestId('chat-sources').last();
  await expect(line).toHaveText("J'ai consulté : Clients (« Karim ») · Chiffres (ce mois)", { timeout: 20_000 });
  await line.scrollIntoViewIfNeeded();
  await line.locator('xpath=../..').screenshot({ path: 'test-results/copilot-sources.png' });
  await line.getByRole('link', { name: 'Clients (« Karim »)' }).click();
  await expect(page).toHaveURL(/\/dashboard\/customers\?q=Karim$/);
  expect(errors).toEqual([]);
});
