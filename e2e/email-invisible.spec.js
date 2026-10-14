// A copied e-mail address can carry an invisible character (zero-width space,
// non-breaking space…). The browser then refuses it with « A part followed by
// '@' should not contain the symbol '' » and nobody can see what to remove
// (user, 2026-10-14, giving a team member access). Every e-mail field now
// drops those characters as they arrive.
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

test.use({ viewport: { width: 1536, height: 960 } });

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const PASTED = 'mza1989fr\u200b@gmail.com\u00a0';

test('the business sign-up: the pasted address is clean and valid', async ({ page }) => {
  await page.goto('/register');
  const mail = page.locator('input[type="email"]');
  await mail.fill(PASTED);
  await expect(mail).toHaveValue('mza1989fr@gmail.com');
  expect(await mail.evaluate((el) => el.checkValidity()), 'the browser accepts it').toBe(true);  // a plain space typed between two words stays (visible, refused), never glued
  await mail.fill('');
  await mail.pressSequentially('marie dupont@gmail.com');
  await expect(mail).toHaveValue('marie dupont@gmail.com');
});

test('« Équipe & accès »: inviting a member with a pasted address', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const br = await (await request.get('/api/owner/branches', { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, st]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (st) localStorage.setItem('ft_selected_branch_v1', st);
  }, [login.access_token, store]);
  await page.goto('/dashboard/parametres/equipe');
  const mail = page.getByPlaceholder('exemple@entreprise.fr');   // the « new member » form
  await expect(mail).toBeVisible();
  await mail.click();
  await page.keyboard.insertText(PASTED);                        // as a paste does
  await expect(mail).toHaveValue('mza1989fr@gmail.com');
  expect(await mail.evaluate((el) => el.checkValidity())).toBe(true);
});
