/**
 * Clients › « Anniversaires du mois » (user, 2026-11-09): the table shows the
 * birthday itself in a column « Anniversaire », the list runs 1 → 31, and both
 * go away with the chip. The date further right is the last visit.
 * Local server and demo data only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const SETTLE = { timeout: 30_000 };

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) };
}

test.use({ viewport: { width: 1536, height: 1000 } });

test('the chip shows each birthday, in birthday order, and takes the column away again', async ({ page, request }) => {
  const SH = await asOwner(page, request);
  const mm = String(new Date(new Date().toLocaleString('en-US', { timeZone: 'Europe/Paris' })).getMonth() + 1).padStart(2, '0');
  // two clients get a birthday this month, the later day on the newer client
  const list = await (await request.get('/api/owner/clients/list?per_page=2&sort=recent', { headers: SH })).json();
  const [late, early] = list.rows;
  for (const [r, day] of [[late, '28'], [early, '02']]) {
    const f = await (await request.get(`/api/owner/clients/${r.id}/fiche`, { headers: SH })).json();
    const put = await request.put(`/api/owner/clients/${r.id}/fiche`, { headers: SH, data: { name: f.name || r.name, birthday: `${mm}-${day}` } });
    expect(put.ok(), await put.text()).toBeTruthy();
  }

  await page.goto('/dashboard/customers');
  const table = page.locator('#clients-list table');
  await expect(table.getByRole('columnheader', { name: 'Anniversaire' })).toHaveCount(0, SETTLE);
  // without the chip the menu does not offer the birthday order (2026-11-10)
  const sortMenu = page.getByLabel('Trier par');
  await expect(sortMenu.locator('option[value="birthday"]')).toHaveCount(0);

  await page.getByRole('button', { name: /Anniversaires du mois/ }).first().click();
  await expect(table.getByRole('columnheader', { name: 'Anniversaire' })).toBeVisible(SETTLE);
  // « Anniversaires du mois », never « 1er → 31 »: months have 28 to 31 days
  await expect(sortMenu).toHaveValue('birthday');
  await expect(sortMenu.locator('option[value="birthday"]')).toHaveText('Anniversaires du mois');

  // 1 → 31: the 2nd comes before the 28th, whatever their sign-up order
  // (the header turns at once; the rows follow when the new list arrives)
  const rows = table.locator('tbody tr');
  const order = async () => {
    const names = await rows.allInnerTexts();
    const iEarly = names.findIndex((t) => t.includes(early.name));
    const iLate = names.findIndex((t) => t.includes(late.name));
    return iEarly >= 0 && iLate >= 0 && iEarly < iLate;
  };
  await expect.poll(order, SETTLE).toBe(true);
  const iEarly = (await rows.allInnerTexts()).findIndex((t) => t.includes(early.name));
  const month = new Date(2000, Number(mm) - 1, 2).toLocaleDateString('fr-FR', { month: 'short' });
  await expect(rows.nth(iEarly)).toContainText(`2 ${month}`);

  // the chip off: the column and the birthday order go with it
  await page.getByRole('button', { name: 'Retirer ce filtre' }).first().click();
  await expect(table.getByRole('columnheader', { name: 'Anniversaire' })).toHaveCount(0, SETTLE);
  await expect(sortMenu).toHaveValue('recent');
  await expect(sortMenu.locator('option[value="birthday"]')).toHaveCount(0);
});
