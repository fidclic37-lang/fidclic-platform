// « Code de la caisse » (user, 2026-10-14): off by default. When a shop turns
// it on, the till really stops scanning until the code is typed — the server
// refuses, so it is a lock and not a screen anyone can walk past.
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test.describe.serial('the till code', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('off by default; on, the server refuses to scan until it is typed', async ({ page, request }) => {
    const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
    const H = { Authorization: `Bearer ${login.access_token}` };
    const br = await (await request.get('/api/owner/branches', { headers: H })).json();
    const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed');
    const clients = await (await request.get('/api/owner/clients/list?per_page=5', { headers: H })).json();
    const card = ((clients.rows || [])[0] || {}).barcode_id;
    expect(card, 'the seed has a client with a card').toBeTruthy();

    const ov = await (await request.get('/api/security/overview', { headers: H })).json();
    expect(ov.caisse_pin, 'a shop is asked nothing until it asks for it').toMatchObject({ on: false });

    // this session becomes the till, then the shop sets a code
    expect((await request.post('/api/security/caisse',
      { headers: H, data: { store_id: store.id } })).status()).toBe(200);
    expect((await request.put('/api/security/caisse/code',
      { headers: H, data: { on: true, mode: 'shop', code: '4812' } })).status()).toBe(200);

    const scan = () => request.post('/api/owner/scan',
      { headers: H, data: { barcode_id: card, amount_paid: 0, branch_id: store.id } });
    expect((await scan()).status(), 'locked, the till does not scan').toBe(423);

    expect((await request.post('/api/security/caisse/unlock',
      { headers: H, data: { code: '0000' } })).status(), 'a wrong code opens nothing').toBe(403);
    expect((await request.post('/api/security/caisse/unlock',
      { headers: H, data: { code: '4812' } })).status()).toBe(200);
    expect((await scan()).status(), 'typed, it scans again').toBe(200);

    // and the shop can see and change it where it lives
    await page.goto('/login');
    await page.evaluate(([t, s]) => {
      localStorage.setItem('fidelitour_access_token', t);
      localStorage.setItem('ft_selected_branch_v1', s);
    }, [login.access_token, store.id]);
    await page.goto('/dashboard/parametres/securite');
    await expect(page.getByText('Code de la caisse')).toBeVisible();
    await expect(page.getByText('Le même code pour la boutique')).toBeVisible();

    // put the shop back as it was
    await request.put('/api/security/caisse/code', { headers: H, data: { on: false } });
    await request.delete('/api/security/caisse', { headers: H });
  });
});
