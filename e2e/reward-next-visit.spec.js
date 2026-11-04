/**
 * A reward is claimed at the visit after the one that earned it (user,
 * 2026-11-04). Real till, real server, local seed only: the scan that fills the
 * card says so and offers nothing to pick; the next scan hands it over.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

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
  return { H: { ...H, 'X-FidClic-Store': store || 'all' }, store };
}

const openCard = async (page, card) => {
  await page.goto('/dashboard/scan');
  await page.getByRole('button', { name: 'Saisir le code' }).click();
  await page.getByLabel('Code de la carte').fill(card);
  await expect(page.getByPlaceholder('0,00')).toBeVisible({ timeout: 10_000 });
  await page.getByPlaceholder('0,00').fill('5');
  await page.getByRole('button', { name: /Suivant/ }).click();
  await expect(page.getByTestId('visit-review')).toBeVisible();
};

test('the scan that fills the card announces it, the next one hands it over', async ({ page, request }) => {
  test.setTimeout(120_000);
  const { H, store } = await asOwner(page, request);
  const s = await (await request.get('/api/owner/card/settings', { headers: H })).json();
  test.skip(s.programme?.programme && s.programme.programme !== 'stamps', 'the demo store is not a Tampons card');

  // a client with an empty row at the till, brought one stamp short by real scans
  const rowOf = async (card) => {
    const c = await (await request.get(`/api/owner/scan/card?barcode=${card}`, { headers: H })).json();
    return (c.applicables || []).find((a) => a.kind === 'card') || null;
  };
  const list = await (await request.get('/api/owner/clients/list?per_page=50', { headers: H })).json();
  let card = null;
  for (const c of list.rows || []) {
    if (c.barcode_id && !(await rowOf(c.barcode_id))) { card = c.barcode_id; break; }
  }
  expect(card, 'a client with no reward waiting').toBeTruthy();
  for (let i = 0; i < 60 && !(await rowOf(card)); i += 1) {
    const r = await request.post('/api/owner/scan', { headers: H, data: { barcode_id: card, amount_paid: 1, branch_id: store || undefined } });
    expect(r.status(), await r.text()).toBe(200);
  }
  expect((await rowOf(card)).after_visit).toBe(true);

  // one stamp short: shown, for later, cannot be picked
  await openCard(page, card);
  const review = page.getByTestId('visit-review');
  await expect(review.getByText('Disponible à la prochaine visite')).toBeVisible();
  await expect(review.getByRole('button', { name: /Disponible à la prochaine visite/ })).toBeDisabled();
  await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
  const summary = page.getByTestId('visit-summary');
  await expect(summary).toBeVisible({ timeout: 15_000 });
  await expect(summary.getByTestId('cards-completed')).toContainText('récompense à la prochaine visite');

  // the next visit: it can be picked, and it is handed over
  const row = await rowOf(card);
  expect(row.available).toBe(true);
  await openCard(page, card);
  const pick = page.getByTestId('visit-review').getByRole('button', { name: new RegExp(row.title) });
  await expect(pick).toBeEnabled();
  await expect(page.getByTestId('visit-review').getByText('Disponible à la prochaine visite')).toHaveCount(0);
  await pick.click();
  await expect(pick).toHaveAttribute('aria-pressed', 'true');
  const answer = page.waitForResponse((r) => r.url().endsWith('/api/owner/scan') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
  const body = await (await answer).json();
  expect(body.applied.ok).toBe(true);
  expect(body.stamps_in_cycle).toBe(1);
  await expect(page.getByTestId('visit-summary')).toContainText(row.title);
  expect(await rowOf(card)).toBeNull();
});
