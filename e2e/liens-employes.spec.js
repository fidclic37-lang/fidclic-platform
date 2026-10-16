/**
 * « Un lien par employé » — Paramètres › Lien d'inscription (user, 2026-10-16),
 * in a real browser, end to end on the local server:
 *   • the owner writes an employee down and gets their link;
 *   • a client signs up through THAT link — and the page, the leaderboard and
 *     the Clients list all say it was that employee, and not another;
 *   • a second employee's link is counted apart;
 *   • the two sections the user asked to remove are gone, and « Personnaliser
 *     la page » is still reachable.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const PAGE = '/dashboard/parametres/lien-inscription';
const uniq = String(Date.now()).slice(-6);

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
  return { H, store };
}

async function addAgent(page, name) {
  await page.getByRole('button', { name: 'Ajouter un employé' }).click();
  await page.getByLabel(/^Nom/).fill(name);
  await page.getByRole('button', { name: 'Créer le lien' }).click();
  await expect(page.getByText(name, { exact: true }).first()).toBeVisible();
}

// sign up a client through a word, as the real signup page does
async function signUp(request, H, word, name, store) {
  const t = await (await request.get('/api/owner/tenant', { headers: H })).json();
  const slug = t.slug || t.tenant?.slug || 'cafe-lumiere';
  const r = await request.post(`/api/join/${slug}`, {
    data: {
      name, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000',
      birthday: '1990-05-04', accepted_terms: true, consent: true, acquisition_source: word,
      ...(store ? { store } : {}),
    },
  });
  return { status: r.status(), body: await r.json() };
}

test.describe.serial('liens par employé', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('les deux sections retirées ne sont plus là, « Personnaliser la page » reste', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto(PAGE);
    await expect(page.getByRole('heading', { name: /Lien d'inscription/ }).first()).toBeVisible({ timeout: 20000 });
    await expect(page.getByText('Personnalisation du lien')).toHaveCount(0);
    await expect(page.getByText("Aperçu de la page d'inscription")).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Personnaliser la page' })).toBeVisible();
    await expect(page.getByText('Un lien par employé')).toBeVisible();
    await expect(page.getByText("Classement de l'équipe")).toBeVisible();
  });

  test('chaque employé a SON lien, et chaque client va au bon', async ({ page, request }) => {
    const { H } = await asOwner(page, request);
    await page.goto(PAGE);
    const a = `Alice ${uniq}`;
    const b = `Bruno ${uniq}`;
    await addAgent(page, a);
    await addAgent(page, b);

    const agents = (await (await request.get('/api/owner/signup-agents', { headers: H })).json()).agents;
    const alice = agents.find((x) => x.name === a);
    const bruno = agents.find((x) => x.name === b);
    expect(alice.word, 'son propre mot').not.toBe(bruno.word);
    // the page writes the link for ITS own address; what must match is the word
    await expect(page.getByText(new RegExp(`/${alice.word}$`))).toBeVisible();
    await expect(page.getByText(new RegExp(`/${bruno.word}$`))).toBeVisible();

    // two clients for Alice, one for Bruno
    for (const n of [`Client A1 ${uniq}`, `Client A2 ${uniq}`]) {
      const r = await signUp(request, H, alice.word, n);
      expect(r.status, JSON.stringify(r.body)).toBe(200);
    }
    expect((await signUp(request, H, bruno.word, `Client B1 ${uniq}`)).status).toBe(200);

    // the leaderboard, on the page, after a reload
    await page.reload();
    await expect(page.getByText("Classement de l'équipe")).toBeVisible({ timeout: 20000 });
    const board = (await (await request.get('/api/owner/signup-agents', { headers: H })).json()).leaderboard;
    const rowA = board.find((r) => r.agent_id === alice.id);
    const rowB = board.find((r) => r.agent_id === bruno.id);
    expect(rowA.month, 'Alice: deux clients').toBe(2);
    expect(rowB.month, 'Bruno: un seul, pas ceux d\'Alice').toBe(1);
    const li = page.locator('li', { hasText: a }).first();
    await expect(li).toContainText('2');

    // Clients: who brought them
    const clients = await (await request.get(
      `/api/owner/clients/list?search=${encodeURIComponent(`Client A1 ${uniq}`)}`, { headers: H })).json();
    const row = (clients.rows || []).find((c) => c.name === `Client A1 ${uniq}`);
    expect(row, 'le client est dans la liste').toBeTruthy();
    expect(row.brought_by?.name).toBe(a);
    expect(row.source_label).toBe(a);
    expect(row.brought_by?.at).toBeTruthy();
  });

  test('archivé : son lien n\'amène plus personne, et surtout pas quelqu\'un d\'autre', async ({ page, request }) => {
    const { H } = await asOwner(page, request);
    const agents = (await (await request.get('/api/owner/signup-agents', { headers: H })).json()).agents;
    const alice = agents.find((x) => x.name === `Alice ${uniq}`);
    await request.delete(`/api/owner/signup-agents/${alice.id}`, { headers: H });
    // no employee left on that word, so the establishment must be given as it
    // is for the shop's bare link — the signup itself still works
    const { store } = await asOwner(page, request);
    const r = await signUp(request, H, alice.word, `Client Après ${uniq}`, store);
    expect(r.status, JSON.stringify(r.body)).toBe(200);
    const clients = await (await request.get(
      `/api/owner/clients/list?search=${encodeURIComponent(`Client Après ${uniq}`)}`, { headers: H })).json();
    const row = (clients.rows || []).find((c) => c.name === `Client Après ${uniq}`);
    expect(row.brought_by, 'plus aucun employé').toBeFalsy();
    // and her own clients keep her name
    const kept = await (await request.get(
      `/api/owner/clients/list?search=${encodeURIComponent(`Client A1 ${uniq}`)}`, { headers: H })).json();
    const old = (kept.rows || []).find((c) => c.name === `Client A1 ${uniq}`);
    expect(old.brought_by?.name).toBe(`Alice ${uniq}`);
  });
});
