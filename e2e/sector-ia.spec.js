/**
 * Sector playbooks PR2, in a real browser on the local server: the demo shop
 * is made a barbier, then a new « Client inactif » opens on the barbier's
 * words (« … votre coupe ? ✂️ ») and the café's words never show. Put back
 * as it was.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('a new automation opens on the shop’s own trade words', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const before = (await (await request.get('/api/owner/etablissement', { headers: H })).json()).business;
  const put = (business) => request.put('/api/owner/etablissement', { headers: { ...H, 'X-FidClic-Store': store }, data: { business } });
  const fields = () => page.evaluate(() => [...document.querySelectorAll('input, textarea')].map((x) => x.value).join(' | '));
  try {
    expect((await put({ sector: 'salon', activity_key: 'barbier' })).ok()).toBeTruthy();
    await page.goto('/login');
    await page.evaluate(([t, s]) => {
      localStorage.setItem('fidelitour_access_token', t);
      if (s) localStorage.setItem('ft_selected_branch_v1', s);
      try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
    }, [login.access_token, store]);
    await page.goto('/dashboard/automations/nouvelle?scenario=inactive&step=3');
    await expect.poll(fields, { timeout: 20_000 }).toContain('Il est temps de rafraîchir votre coupe ?');
    expect(await fields()).not.toContain('Votre pause vous attend');

    expect((await put({ sector: 'cafe', activity_key: 'cafe' })).ok()).toBeTruthy();
    await page.goto('/dashboard/automations/nouvelle?scenario=geo&step=3');
    await expect.poll(fields, { timeout: 20_000 }).toContain('Une petite pause ? ☕');

    // the trade's rules hold on the owner's own words (pentest 2026-10-28)
    expect((await put({ sector: 'retail', activity_key: 'tabac_presse' })).ok()).toBeTruthy();
    const draft = (title, message) => request.post('/api/owner/campaigns/compose', {
      headers: { ...H, 'X-FidClic-Store': store }, data: { title, message, draft: true } });
    const refused = await draft('Promo', 'Vos c1g@rettes à -10 %');
    expect(refused.status()).toBe(422);
    expect((await refused.json()).detail).toContain('loi Évin');
    expect((await draft('Presse', 'Votre bureau de tabac vous attend')).status()).not.toBe(422);
  } finally {
    await put({ sector: before.sector || 'cafe', activity_key: before.activity_key || '' });
  }
  expect(errors).toEqual([]);
});
