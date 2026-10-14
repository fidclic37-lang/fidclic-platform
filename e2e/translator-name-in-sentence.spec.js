// A shop's name inside a sentence must survive translation, while the sentence
// around it is translated (user, 2026-10-13: « ROYAL TRIM LIBERTÉ » read
// « ROYAL TRIM FREEDOM » in English).
//
// The fix shipped in #262 without a test that could fail without it — the
// attempts made then were run against a stale dist/ and passed either way.
// This one is built first, and verified to fail on the translator as it was
// before that change.
//
// Google's answer is played here (no network): « Lumière » becomes « Light »,
// « Établissement » becomes « Shop ». The page must end up saying
// « Shop : Café Lumière - Main » — sentence translated, name untouched.
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test.describe('a name inside a sentence', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('is kept as written while the sentence around it is translated', async ({ page, request }) => {
    const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
    const H = { Authorization: `Bearer ${login.access_token}` };
    const br = await (await request.get('/api/owner/branches', { headers: H })).json();
    const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed');
    await request.put('/api/me/preferences', { headers: H, data: { language: 'en' } });

    await page.route('https://translate.googleapis.com/**', async (route) => {
      const q = new URL(route.request().url()).searchParams.get('q') || '';
      const out = q.replace(/Lumière/g, 'Light').replace(/Établissement/g, 'Shop');
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify([[[out, q]]]) });
    });

    await page.goto('/login');
    await page.evaluate(([t, s]) => {
      localStorage.setItem('fidelitour_access_token', t);
      localStorage.setItem('ft_selected_branch_v1', s);
      localStorage.setItem('fidclic:lang-chosen', '1');
      localStorage.setItem('fidelitour:lang', 'en');
    }, [login.access_token, store.id]);

    // « Établissement : <nom> » and « …page d'inscription de <nom>. » both live here
    await page.goto('/dashboard/parametres/lien-inscription');
    await expect(page.getByTestId('signup-image')).toBeVisible();

    const nodes = () => page.evaluate(() => {
      const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const out = [];
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        const t = (n.nodeValue || '').trim();
        if (t) out.push(t);
      }
      return out;
    });

    // the sentence was translated — without this the check below proves nothing
    await expect.poll(async () => (await nodes()).some((t) => t.includes('Shop')),
      { timeout: 15_000 }).toBe(true);
    await page.waitForTimeout(2500);               // every slow « translation » has come back

    const all = await nodes();
    expect(all.filter((t) => /Light/.test(t)), 'the shop name is never translated').toEqual([]);
    expect(all.some((t) => t.includes('Café Lumière')), 'and it is still on the page').toBe(true);

    await request.put('/api/me/preferences', { headers: H, data: { language: 'fr' } });
  });
});
