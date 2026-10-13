// A window with something typed in it never closes on a tap beside it
// (QA BUG-003 « Ajouter un point de vente », BUG-007 « Modifier la fiche »;
// user 2026-10-13: « bahar tap kiya, sab mit gaya »), in a real browser.
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const br = await (await request.get('/api/owner/branches', { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store]);
}

const tapBeside = (page) => page.mouse.click(6, 6);      // the backdrop's corner, away from the window

test.describe.serial('typed input survives a tap beside the window', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('BUG-003 — the « point de vente » window', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard/parametres/etablissement');
    // the demo plan has one establishment more at most: the same window, editing one
    const actions = page.getByRole('button', { name: /^Actions — / }).first();
    await expect(actions).toBeVisible();
    const openIt = async () => { await actions.click(); await page.getByRole('button', { name: 'Modifier', exact: true }).click(); };
    const win = () => page.locator('div.fixed.inset-0').filter({ hasText: 'Code postal' }).last();

    // nothing typed: a tap beside still closes it, as before
    await openIt();
    await expect(win()).toBeVisible();
    await tapBeside(page);
    await expect(win()).toHaveCount(0);

    // something typed: it stays, with what was typed
    await openIt();
    const field = win().getByRole('textbox').nth(1);              // Adresse
    await field.fill('12 rue de la Paix');
    await tapBeside(page);
    await page.waitForTimeout(400);
    await expect(win(), 'still open after a tap beside it').toBeVisible();
    await expect(field).toHaveValue('12 rue de la Paix');
    // asked for: « Annuler » still closes it
    await win().getByRole('button', { name: 'Annuler' }).click();
    await expect(win()).toHaveCount(0);
  });

  test('BUG-007 — « Modifier la fiche »', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard/customers');
    await page.getByRole('button', { name: "Plus d'actions" }).first().click();
    await page.getByRole('button', { name: 'Modifier la fiche' }).click();
    const dialog = page.getByRole('dialog', { name: 'Modifier la fiche' });
    await expect(dialog).toBeVisible();
    const phone = dialog.getByLabel('Téléphone');
    await expect(phone).toBeVisible();
    await phone.fill('0612340000');
    await tapBeside(page);
    await page.waitForTimeout(400);
    await expect(dialog, 'still open after a tap beside it').toBeVisible();
    await expect(phone).toHaveValue(/0612340000|06 12 34 00 00/);
  });
});
