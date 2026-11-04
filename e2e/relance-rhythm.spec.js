// « Client inactif » › Déclencheur (user, 2026-11-04: « jo apne rhythm pe hain,
// unhe mat bhejo »): a switch, on by default, sent with the live count and kept
// when saved. Local server only.
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('the rhythm switch: on by default, sent to the count, kept when saved', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed');
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store.id]);

  await page.goto('/dashboard/automations/nouvelle?scenario=inactive&step=2');
  const sw = page.getByRole('switch', { name: 'Respecter le rythme de chaque client' });
  await expect(sw).toBeVisible({ timeout: 15_000 });
  await expect(sw).toHaveAttribute('aria-checked', 'true');
  const sent = page.waitForRequest((r) => r.url().includes('/automations/preview')
    && r.postDataJSON()?.trigger?.respect_rhythm === false);
  await sw.click();
  await expect(sw).toHaveAttribute('aria-checked', 'false');
  await sent;
  await page.screenshot({ path: 'test-results/relance-rhythm.png' });

  const name = `Relance e2e ${Date.now()}`;
  const made = await request.post('/api/owner/automations', { headers: H, data: {
    scenario: 'inactive', name, status: 'paused', trigger: { days: 35, repeat: 'once', respect_rhythm: false },
    message: { title: 'On vous attend', body: 'Revenez nous voir !' },
    targeting: { mode: 'all', filters: {} }, schedule: { days: 'all', hour: '10:00' } } });
  expect(made.status()).toBe(200);
  const id = (await made.json()).id;
  await page.goto(`/dashboard/automations/${id}?step=2`);
  await expect(page.getByRole('switch', { name: 'Respecter le rythme de chaque client' })).toHaveAttribute('aria-checked', 'false', { timeout: 15_000 });
  expect(errors).toEqual([]);
});
