// Équipe & accès shows only the stores the viewer should reach
// (docs/tasks/roles-access-own-store.md): the invite form offers the store open
// in the menu, and a non-owner sees its own store and nobody else's.
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const SIZES = [['phone', { width: 390, height: 844 }], ['desktop', { width: 1440, height: 900 }]];
let count = 0;
const created = [];                                  // the demo plan holds few accounts: each test gives its own back

async function setup(request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const stores = ((br && br.branches) || br || []).filter((b) => b.status !== 'closed');
  return { token: login.access_token, H, stores };
}

async function openTeam(page, token, store) {
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    localStorage.setItem('ft_selected_branch_v1', s);
  }, [token, store]);
  await page.goto('/dashboard/parametres/equipe');
  await expect(page.getByPlaceholder('exemple@entreprise.fr')).toBeVisible();
}

async function newAdmin(request, H, branchIds) {
  count += 1;
  const email = `own.store.${Date.now()}.${count}@example.test`;
  created.push(email);
  const r = await request.post('/api/owner/team-access/users', { headers: H,
    data: { email, first_name: 'Ada', last_name: 'Test', role: 'administrateur', branch_ids: branchIds } });
  expect(r.ok(), await r.text()).toBe(true);
  const { credentials } = await r.json();
  const login = await (await request.post('/api/auth/login', { data: { email, password: credentials.password } })).json();
  return { email, token: login.access_token };
}

const inviteCard = (page) => page.locator('section').filter({ has: page.getByRole('heading', { name: 'Inviter un utilisateur' }) });

async function offeredInInvite(page) {
  const card = inviteCard(page);
  const selects = card.locator('select');          // a one-store role: a list; several stores: a checklist
  if (await selects.count() > 1) {
    return (await selects.nth(1).locator('option').allTextContents()).filter((t) => t !== 'Choisir…');
  }
  await card.getByRole('button', { name: /établissement|Choisir|Café|Lumi/i }).first().click();
  const names = await card.locator('input[type="checkbox"]').evaluateAll((els) => els.map((el) => el.closest('label').textContent.trim()));
  await page.keyboard.press('Escape');
  return names;
}

for (const [label, viewport] of SIZES) {
  test.describe(label, () => {
    test.use({ viewport });

    test.afterEach(async ({ request }) => {
      const { H } = await setup(request);
      for (const email of created.splice(0)) {
        await request.delete(`/api/owner/team-access/users/${encodeURIComponent(email)}`, { headers: H });
      }
    });

    test('owner, one store open: the invite form offers it alone; Accès starts there and lists every store', async ({ page, request }) => {
      const { token, H, stores } = await setup(request);
      test.skip(stores.length < 2, 'a one-shop demo');
      const open = stores[1];
      await openTeam(page, token, open.id);

      const offered = await offeredInInvite(page);
      expect(offered, 'only the open store').toHaveLength(1);
      expect(offered[0]).toContain(open.name);

      // already chosen: only a name and an address to fill in, and it lands there
      const card = inviteCard(page);
      await card.getByPlaceholder('Prénom Nom').fill('Eve Test');
      const email = `own.store.owner.${Date.now()}.${label}@example.test`;
      created.push(email);
      await card.getByPlaceholder('exemple@entreprise.fr').fill(email);
      await card.getByRole('button', { name: "Créer l'accès" }).click();
      await expect(page.getByRole('dialog', { name: 'Identifiants prêts' })).toBeVisible();
      await page.getByRole('button', { name: 'Fermer' }).click();
      const saved = await (await request.get('/api/owner/team-access', { headers: H })).json();
      expect(saved.users.find((u) => u.email === email).branch_ids).toEqual([open.id]);

      const access = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Accès par établissement' }) }).last();
      const pick = access.locator('select');
      await expect(pick).toHaveValue(open.id);
      await expect(pick.locator('option')).toHaveCount(stores.length);
    });

    test('administrateur of one store: its store alone, nobody else\'s, and an invite lands there', async ({ page, request }) => {
      const { H, stores } = await setup(request);
      test.skip(stores.length < 2, 'a one-shop demo');
      const [mine, other] = [stores[1], stores[0]];
      const admin = await newAdmin(request, H, [mine.id]);
      await openTeam(page, admin.token, mine.id);

      await expect(page.locator('body')).not.toContainText(other.name);
      await page.getByRole('tab', { name: 'Accès par établissement' }).click();
      const section = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Accès par établissement' }) });
      await expect(section.locator('select'), 'nothing to choose from').toHaveCount(0);
      await expect(section).toContainText(mine.name);
      await expect(page.locator('body')).not.toContainText(other.name);

      await page.getByRole('tab', { name: 'Utilisateurs' }).click();
      const card = inviteCard(page);
      await card.getByPlaceholder('Prénom Nom').fill('Eve Test');
      const email = `own.store.emp.${Date.now()}.${label}@example.test`;
      created.push(email);
      await card.getByPlaceholder('exemple@entreprise.fr').fill(email);
      await card.getByLabel('Rôle du nouvel utilisateur').selectOption('staff');
      await card.getByRole('button', { name: "Créer l'accès" }).click();
      await expect(page.getByRole('dialog', { name: 'Identifiants prêts' })).toBeVisible();
      await page.getByRole('button', { name: 'Fermer' }).click();
      const list = await (await request.get('/api/owner/team-access', { headers: H })).json();
      expect(list.users.find((u) => u.email === email).branch_ids).toEqual([mine.id]);
    });

    test('a store taken away while the browser still holds it: the page moves to the store left', async ({ page, request }) => {
      const { H, stores } = await setup(request);
      test.skip(stores.length < 2, 'a one-shop demo');
      const [left, gone] = [stores[0], stores[1]];
      const admin = await newAdmin(request, H, [gone.id, left.id]);
      await openTeam(page, admin.token, gone.id);
      await setup(request);                          // a login's cookie speaks for this context: the owner's again
      const move = await request.put(`/api/owner/team-access/users/${encodeURIComponent(admin.email)}`, { headers: H,
        data: { first_name: 'Ada', last_name: 'Test', role: 'administrateur', branch_ids: [left.id] } });
      expect(move.ok(), await move.text()).toBe(true);
      await page.getByRole('tab', { name: 'Préférences' }).click();
      await page.getByRole('tab', { name: 'Équipe & accès' }).click();
      await expect(page.getByPlaceholder('exemple@entreprise.fr')).toBeVisible();
      await expect(page.locator('body')).not.toContainText(gone.name);
      expect(await page.evaluate(() => localStorage.getItem('ft_selected_branch_v1'))).toBe(left.id);
    });

    test('Sécurité: a new password for someone in the open store comes back', async ({ page, request }) => {
      const { H, stores } = await setup(request);
      test.skip(stores.length < 2, 'a one-shop demo');
      const admin = await newAdmin(request, H, [stores[1].id]);
      count += 1;
      const email = `own.store.sec.${Date.now()}.${count}@example.test`;
      created.push(email);
      const made = await request.post('/api/owner/team-access/users', { headers: { Authorization: `Bearer ${admin.token}`, 'X-FidClic-Store': stores[1].id },
        data: { email, first_name: 'Sam', last_name: 'Test', role: 'staff', branch_ids: [stores[1].id] } });
      expect(made.ok(), await made.text()).toBe(true);
      await page.goto('/login');
      await page.evaluate(([t, s]) => {
        localStorage.setItem('fidelitour_access_token', t);
        localStorage.setItem('ft_selected_branch_v1', s);
      }, [admin.token, stores[1].id]);
      await page.goto('/dashboard/parametres/securite');
      await page.getByRole('button', { name: 'Actions — Sam Test' }).click();
      await page.getByRole('button', { name: 'Nouveau mot de passe' }).click();
      await page.getByRole('button', { name: 'Créer le nouveau mot de passe' }).click();
      await expect(page.getByText(email).last()).toBeVisible();
      await expect(page.getByText('Il ne sera plus affiché')).toBeVisible();
    });

    test('an account with no store at all: the page says so', async ({ page, request }) => {
      const { H, stores } = await setup(request);
      test.skip(stores.length < 2, 'a one-shop demo');
      const admin = await newAdmin(request, H, [stores[1].id]);
      // what the server says of an account with no store (team_access.identity)
      await page.route('**/api/auth/me', async (route) => {
        const res = await route.fetch();
        await route.fulfill({ response: res, json: { ...(await res.json()), branch_ids: [], page_perms: {} } });
      });
      await page.goto('/login');
      await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), admin.token);
      await page.goto('/dashboard/parametres/equipe');
      await expect(page.getByText('Aucun établissement ne vous est attribué.')).toBeVisible();
      await expect(page.getByPlaceholder('exemple@entreprise.fr')).toHaveCount(0);
    });

    test('no store left while the page loads: it says so and offers no form', async ({ page, request }) => {
      const { H, stores } = await setup(request);
      test.skip(stores.length < 2, 'a one-shop demo');
      const admin = await newAdmin(request, H, [stores[1].id]);
      // the store taken away while the page is open: the reply a store-less account gets
      await page.route('**/api/owner/team-access', async (route) => {
        const res = await route.fetch();
        await route.fulfill({ response: res, json: { ...(await res.json()), stores: [], invite_stores: [] } });
      });
      await page.goto('/login');
      await page.evaluate(([t, st]) => {
        localStorage.setItem('fidelitour_access_token', t);
        localStorage.setItem('ft_selected_branch_v1', st);
      }, [admin.token, stores[1].id]);
      await page.goto('/dashboard/parametres/equipe');
      const card = inviteCard(page);
      await expect(card).toContainText('Aucun établissement ne vous est attribué.');
      await expect(page.getByPlaceholder('exemple@entreprise.fr')).toHaveCount(0);
      await page.getByRole('tab', { name: 'Accès par établissement' }).click();
      await expect(page.locator('section').filter({ has: page.getByRole('heading', { name: 'Accès par établissement' }) }))
        .toContainText('Aucun établissement ne vous est attribué.');
    });

    test('administrateur of two stores, one open: only that one here; a person on both shows it alone', async ({ page, request }) => {
      const { H, stores } = await setup(request);
      test.skip(stores.length < 2, 'a one-shop demo');
      const [open, second] = [stores[0], stores[1]];
      const admin = await newAdmin(request, H, [open.id, second.id]);
      await openTeam(page, admin.token, open.id);

      const offered = await offeredInInvite(page);
      expect(offered).toHaveLength(1);
      expect(offered[0]).toContain(open.name);
      await expect(page.locator('body')).not.toContainText(second.name);
      await page.getByRole('tab', { name: 'Accès par établissement' }).click();
      const section = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Accès par établissement' }) });
      await expect(section.locator('select')).toHaveCount(0);
      await expect(section).toContainText(open.name);
      await expect(page.locator('body')).not.toContainText(second.name);
    });
  });
}
