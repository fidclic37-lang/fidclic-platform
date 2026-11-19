// Avis Google with several établissements (user, 2026-11-19): only the
// établissement open in the menu needs its Google link; another one's may be
// typed now, with its own « Activer »; typed but not switched on, it waits —
// and turns on from its own établissement without asking for the link again.
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const SIZES = [['phone', { width: 390, height: 844 }], ['desktop', { width: 1440, height: 900 }]];

async function setup(request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const stores = ((br && br.branches) || br || []).filter((b) => b.status !== 'closed');
  return { token: login.access_token, H, stores };
}

const avisRow = async (request, H, store) => {
  const page = await (await request.get('/api/owner/automations', { headers: { ...H, 'X-FidClic-Store': store } })).json();
  return { row: page.rows.find((r) => r.scenario === 'google_review'), page };
};

async function open(page, token, store, path) {
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    localStorage.setItem('ft_selected_branch_v1', s);
  }, [token, store]);
  await page.goto(path);
}

for (const [label, viewport] of SIZES) {
  test.describe(label, () => {
    test.use({ viewport });

    test('only the open établissement needs its link; another waits until switched on there', async ({ page, request }) => {
      const { token, H, stores } = await setup(request);
      expect(stores.length, 'the demo shop has 2+ établissements').toBeGreaterThan(1);
      const [A, B] = stores;
      const linkA = `https://g.page/r/e2e-a-${label}/review`;
      const linkB = `https://g.page/r/e2e-b-${label}/review`;
      // a clean start: both off, no links (local demo data only)
      for (const s of [A, B]) {
        const { row } = await avisRow(request, H, s.id);
        if (row && row.status === 'active') {
          await request.post(`/api/owner/automations/${row.id}/status`, { headers: { ...H, 'X-FidClic-Store': s.id }, data: { status: 'paused' } });
        }
      }
      const { row: rowA } = await avisRow(request, H, A.id);
      await request.put(`/api/owner/automations/${rowA.id}`, { headers: { ...H, 'X-FidClic-Store': A.id },
        data: { ...rowA, status: 'draft', google_links: { [A.id]: '', [B.id]: '' }, google_on: { [B.id]: false } } });

      await open(page, token, A.id, `/dashboard/automations/${rowA.id}`);
      const own = page.getByTestId(`google-store-${A.id}`);
      const other = page.getByTestId(`google-store-${B.id}`);
      await expect(own).toContainText('établissement ouvert *');
      await expect(other).toContainText('(facultatif)');
      const otherSwitch = other.getByRole('switch');
      await expect(otherSwitch, 'no link yet: nothing to switch on').toBeDisabled();

      await own.getByRole('textbox').fill(linkA);
      await other.getByRole('textbox').fill(linkB);
      await expect(otherSwitch).toBeEnabled();
      await expect(otherSwitch).toHaveAttribute('aria-checked', 'false');
      await page.getByRole('button', { name: 'Enregistrer les modifications' }).first().click();
      await expect(page).toHaveURL(/\/dashboard\/automations(\?|$)/);
      await expect(page.getByText(/Ajoutez le lien Google/)).toHaveCount(0);

      const after = await avisRow(request, H, B.id);
      expect(after.page.google.links[A.id]).toBe(linkA);
      expect(after.page.google.links[B.id]).toBe(linkB);
      expect(after.row.status, 'B only got its link: still off').not.toBe('active');

      // B open: its switch turns on with the link already there
      await open(page, token, B.id, '/dashboard/automations');
      const sw = page.getByRole('switch', { name: `Activer ${after.row.name}` }).first();
      await expect(sw).toHaveAttribute('aria-checked', 'false');
      await sw.click();
      await expect(sw).toHaveAttribute('aria-checked', 'true');
      await expect(page.getByText(/Ajoutez le lien Google/)).toHaveCount(0);

      // back in A's editor: B reads « activé »
      await open(page, token, A.id, `/dashboard/automations/${rowA.id}`);
      await expect(page.getByTestId(`google-store-${B.id}`).getByRole('switch')).toHaveAttribute('aria-checked', 'true');
    });
  });
}
