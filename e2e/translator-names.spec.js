// A store's name is never translated (user, 2026-10-13: renamed « ROYAL TRIM
// LIBERTÉ », the app in English showed « ROYAL TRIM FREEDOM »). The new name
// showed on the page before the list of stores was read again, and the
// translator replaced it meanwhile — and never put it back.
//
// Google's answer is played here (no network), slow on purpose, so the race
// happens every run. Runs against the local server only (scripts/dev_local.py
// — demo data in memory). Never point it at production.
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const NAME = 'ROYAL TRIM LIBERTÉ';

// « Liberté » → « Freedom », the save button → « Save changes », the rest as
// itself; 600 ms late
async function fakeGoogle(page) {
  await page.route('https://translate.googleapis.com/**', async (route) => {
    const q = new URL(route.request().url()).searchParams.get('q') || '';
    const out = q.replace(/LIBERTÉ/g, 'FREEDOM').replace(/Liberté/g, 'Freedom')
      .replace(/Enregistrer les modifications/g, 'Save changes');
    await new Promise((r) => setTimeout(r, 600));
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify([[[out, q]]]) });
  });
}

const freedomNodes = (page) => page.evaluate(() => {
  const out = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) if (/FREEDOM/i.test(n.nodeValue)) out.push(n.nodeValue);
  return out;
});

test.describe.serial('store names stay as written in another language', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('renaming a store in English: the new name everywhere, never « FREEDOM »', async ({ page, request }) => {
    const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
    const H = { Authorization: `Bearer ${login.access_token}` };
    const br = await (await request.get('/api/owner/branches', { headers: H })).json();
    const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed');
    const before = store.name;
    // the owner reads the app in English (their preference, so a save keeps it)
    await request.put('/api/me/preferences', { headers: H, data: { language: 'en' } });

    await fakeGoogle(page);
    // the list of stores answers as slowly as on production's free database
    await page.route('**/api/owner/branches**', async (route) => {
      await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
    await page.goto('/login');
    await page.evaluate(([t, s]) => {
      localStorage.setItem('fidelitour_access_token', t);
      localStorage.setItem('ft_selected_branch_v1', s);
      localStorage.setItem('fidclic:lang-chosen', '1');
      localStorage.setItem('fidelitour:lang', 'en');
    }, [login.access_token, store.id]);
    await page.goto('/dashboard/parametres/etablissement');
    const save = page.getByRole('button', { name: /^(Save changes|Enregistrer les modifications)$/ });
    await expect(save).toBeVisible();
    await expect.poll(() => page.evaluate((v) => [...document.querySelectorAll('input')].some((i) => i.value === v), before)).toBe(true);
    await page.evaluate(([v, nv]) => {
      const i = [...document.querySelectorAll('input')].find((x) => x.value === v);
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, nv);
      i.dispatchEvent(new Event('input', { bubbles: true }));
    }, [before, NAME]);
    await save.click();

    // the menu and the list of points de vente show the new name, as written
    const menu = page.locator('aside, nav').getByText(NAME, { exact: true }).first();
    await expect(menu).toBeVisible();
    await page.waitForTimeout(2500);                  // every slow « translation » has come back
    expect(await freedomNodes(page)).toEqual([]);
    expect(await page.evaluate(() => localStorage.getItem('fidelitour:lang'))).toBe('en');
    await expect(page.getByRole('button', { name: /^Save changes$/ })).toBeVisible();   // the page itself is translated

    // and on a fresh load
    await page.reload();
    await expect(page.getByText(NAME, { exact: true }).first()).toBeVisible();
    await page.waitForTimeout(2500);
    expect(await freedomNodes(page)).toEqual([]);

    // back as it was
    await request.put('/api/me/preferences', { headers: H, data: { language: 'fr' } });
  });
});
