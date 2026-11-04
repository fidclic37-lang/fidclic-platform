// The brand is never translated (user, 2026-11-04: on French devices, translating
// the page turned the logo into « FidClick »). The wordmark is two text pieces,
// « Fid » and « Clic », and « Clic » alone is a French word to a translator.
// `translate="no"` is what Chrome's own translator obeys; the app's translator
// (lib/translator.js) obeys it too, and that one is played here with a fake Google.
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const STAFF = { email: 'demo.staff@fidelitour.com', password: 'Staff!Demo2026' };   // local seed only

async function fakeGoogle(page) {
  await page.route('https://translate.googleapis.com/**', async (route) => {
    const q = new URL(route.request().url()).searchParams.get('q') || '';
    const out = q.replace(/Clic/g, 'Click');
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify([[[out, q]]]) });
  });
}

async function signIn(page, request, who, lang = 'fr') {
  const login = await (await request.post('/api/auth/login', { data: who })).json();
  await page.goto('/login');
  await page.evaluate(([t, l]) => {
    localStorage.setItem('fidelitour_access_token', t);
    localStorage.setItem('fidclic:lang-chosen', '1');
    localStorage.setItem('fidelitour:lang', l);
  }, [login.access_token, lang]);
}

async function expectProtected(wordmark) {
  await expect(wordmark).toBeVisible({ timeout: 15_000 });
  await expect(wordmark).toHaveText('FidClic');
  await expect(wordmark).toHaveAttribute('translate', 'no');
  await expect(wordmark).toHaveClass(/notranslate/);
}

test.describe('the FidClic wordmark', () => {
  test('sidebar logo, app read in English: still « FidClic », never « FidClick »', async ({ page, request }) => {
    await page.setViewportSize({ width: 1536, height: 960 });
    await fakeGoogle(page);
    await signIn(page, request, OWNER, 'en');
    await page.goto('/dashboard');
    await expectProtected(page.getByTestId('brand-wordmark').first());
    await page.waitForTimeout(1500);   // the translator has had its pass
    await expect(page.getByTestId('brand-wordmark').first()).toHaveText('FidClic');
  });

  test('phone header of the staff', async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page, request, STAFF);
    await page.goto('/dashboard/scan');
    // the sidebar's logo is in the DOM too, inside the closed drawer
    await expectProtected(page.locator('[data-testid="brand-wordmark"]:visible').first());
    // and the closed one is protected as well
    await expect(page.getByTestId('brand-wordmark').first()).toHaveAttribute('translate', 'no');
  });

  test('« by FidClic » on the signup page', async ({ page }) => {
    await page.goto('/join/cafe-lumiere');
    await expectProtected(page.getByTestId('brand-wordmark').first());
  });
});
