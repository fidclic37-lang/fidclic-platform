// The search bar at the top (user, 2026-10-15: « kuch bhi search kro toh
// clients page pr le jaata hai »). Its list of pages was a hand-kept copy of
// the sidebar and had drifted, so almost nothing matched and everything fell
// through to the client list.
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const br = await (await request.get('/api/owner/branches',
    { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed');
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store.id]);
}

// The bar lives in the layout, so it is still there after it has taken us
// somewhere: one page load for the whole walk, not one per word. (Reloading
// each time made the run long enough to tip the timing-sensitive specs over.)
const search = async (page, term) => {
  const box = page.getByRole('textbox', { name: /Rechercher/i });
  await box.fill(term);
  await box.press('Enter');
};

test.describe('the search bar at the top', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('each word opens its own section, not the client list', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard');
    const cases = [
      ['automatisations', '/dashboard/automations'],
      ['segmentation', '/dashboard/segmentation'],
      ['parrainage', '/dashboard/referral'],
      ['geolocalisation', '/dashboard/map'],     // typed without its accent
      ['catalogue', '/dashboard/catalogue'],
      ['carte de fidélité', '/dashboard/card'],
      ['equipe', '/dashboard/parametres/equipe'],
      ['historique', '/dashboard/history'],
    ];
    for (const [term, route] of cases) {
      await search(page, term);
      await expect(page, `« ${term} » opens its section`).toHaveURL(new RegExp(`${route}(\\?|$)`));
    }
  });

  test('what it found is outlined on the page it opened', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard');
    await search(page, 'catalogue');
    await expect(page.locator('.fid-hl').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('.fid-hl').first()).toContainText(/catalogue/i);
  });

  test('a name still searches the clients', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard');
    await search(page, 'Zzz Personne Inconnue');
    await expect(page).toHaveURL(/\/dashboard\/customers\?q=/);
  });
});
