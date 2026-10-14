// Points de vente, QA R6 (2026-10-11), in a real browser:
//   F26 — Adresse / Code postal / Ville are required: an empty one is named and
//         nothing is saved;
//   F27 — a saved point de vente shows in the menu's list at once, without a
//         reload (the demo plan adds none: a rename goes through the same save).
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

test.use({ viewport: { width: 1536, height: 960 } });

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test('a point de vente: its address required, the menu up to date at once', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const list = (br && br.branches) || br || [];
  const main = list.find((b) => b.is_main) || list[0];
  const other = list.find((b) => b.id !== main.id && b.status !== 'closed');
  test.skip(!other, 'a one-shop demo');
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, main.id]);
  await page.goto('/dashboard/parametres/etablissement');

  await page.getByRole('button', { name: `Actions — ${other.name}` }).click();
  await page.getByRole('button', { name: 'Modifier', exact: true }).click();
  const win = page.locator('div.fixed.inset-0').filter({ hasText: 'Code postal' }).last();
  const address = win.getByRole('textbox').nth(1);
  const before = await address.inputValue();

  // F26 — the address emptied: named, not saved
  await address.fill('');
  await win.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(win.getByText(/^Complétez : Adresse/)).toBeVisible();
  const still = await (await request.get('/api/owner/branches', { headers: H })).json();
  expect(((still && still.branches) || still).find((b) => b.id === other.id).address, 'nothing saved').toContain(before);

  // F27 — saved: the menu's list knows it at once
  await address.fill(before || '1 rue Test');
  const city = win.getByRole('textbox').nth(3);
  if (!(await city.inputValue())) await city.fill('Tours');
  const name = `${other.name} (QA)`;
  await win.getByRole('textbox').first().fill(name);
  await win.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(win).toHaveCount(0);
  const switcher = page.locator('button[aria-haspopup="listbox"]').first();      // the menu's establishment switcher
  await switcher.click();
  await expect(switcher.locator('xpath=..').getByRole('button', { name, exact: true }), 'in the menu, no reload').toBeVisible();

  // back as it was
  await request.put(`/api/owner/etablissement/stores/${other.id}`, { headers: H, data: { name: other.name, street: before || '1 rue Test',
    postal_code: other.postal_code || '37000', city: other.city || 'Tours' } });
});
