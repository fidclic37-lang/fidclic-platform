/**
 * « Accéder au compte » — le bandeau du super admin (user, 2026-10-16 : « main
 * use nhi kr paa rha admin section se businesses k accounts ko »).
 *
 * Il couvrait le bas de chaque page. Il se réduit maintenant en une pastille
 * en bas à droite ; « Quitter » y reste à un clic, le choix est retenu après
 * un rechargement, et entrer dans un AUTRE commerce réaffiche l'avis entier
 * — il dit dans quel compte on est et que tout est journalisé.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
const FULL = /Vous êtes dans le compte de/;

async function viewAs(page, request, which = 0) {
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const list = await (await request.get('/api/admin/commerces', { headers: H })).json();
  const rows = list.rows || list.commerces || list.items || [];
  const t = rows[which];
  expect(t, 'un commerce à ouvrir').toBeTruthy();
  const got = await (await request.post(`/api/admin/commerces/${t.id}/view-as`, { headers: H })).json();
  await page.goto('/login');
  await page.evaluate((tok) => {
    localStorage.setItem('fidelitour_access_token', tok);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, got.token);
  await page.goto('/dashboard/customers');
  return got.name;
}

test.use({ viewport: { width: 1536, height: 960 } });

test('le bandeau se réduit, « Quitter » reste, et le choix tient au rechargement', async ({ page, request }) => {
  await viewAs(page, request, 0);
  await expect(page.getByText(FULL)).toBeVisible({ timeout: 20000 });

  // réduire
  await page.getByRole('button', { name: 'Réduire le bandeau' }).click();
  await expect(page.getByText(FULL)).toHaveCount(0);
  const pill = page.getByRole('button', { name: 'Quitter', exact: true });
  await expect(pill).toBeVisible();

  // la pastille ne couvre plus la page : elle est bien plus petite
  const box = await pill.boundingBox();
  expect(box.y + box.height).toBeLessThanOrEqual(960);

  // un rechargement ne le ramène pas
  await page.reload();
  await expect(page.getByRole('button', { name: 'Quitter', exact: true })).toBeVisible({ timeout: 20000 });
  await expect(page.getByText(FULL)).toHaveCount(0);

  // et on peut le rouvrir
  await page.getByRole('button', { name: /afficher le bandeau/ }).click();
  await expect(page.getByText(FULL)).toBeVisible();
});

test('un autre commerce réaffiche l\'avis en entier', async ({ page, request }) => {
  await viewAs(page, request, 0);
  await expect(page.getByText(FULL)).toBeVisible({ timeout: 20000 });
  await page.getByRole('button', { name: 'Réduire le bandeau' }).click();
  await expect(page.getByText(FULL)).toHaveCount(0);

  await viewAs(page, request, 1);
  await expect(page.getByText(FULL), "l'avis revient pour l'autre compte").toBeVisible({ timeout: 20000 });
});

test('« Quitter » depuis la pastille sort bien de la vue', async ({ page, request }) => {
  await viewAs(page, request, 0);
  await page.getByRole('button', { name: 'Réduire le bandeau' }).click();
  await page.getByRole('button', { name: 'Quitter', exact: true }).click();
  await expect(page).toHaveURL(/\/login/, { timeout: 20000 });
});
