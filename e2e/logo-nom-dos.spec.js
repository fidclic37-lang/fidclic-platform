/**
 * L'en-tête Apple et le dos de la carte (user, 2026-10-20), dans un vrai
 * navigateur : le curseur « Taille du nom » existe et son réglage tient, et le
 * dos garde une ligne aussi longue que de vraies conditions d'utilisation.
 *
 * Tout passe par LA PAGE, jamais par un appel à côté : le commerce de
 * démonstration a plusieurs établissements, et un appel sans établissement ne
 * lit pas la même carte que la page (leçon de graph-detail, 2026-10-17).
 * Ce que les images deviennent est mesuré pixel par pixel dans
 * api/tests/test_logo_name_size.py.
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
}

const nameSize = (page) => page.getByLabel('Taille du nom', { exact: true });
const saveIt = (page) => page.getByRole('button', { name: /Enregistrer les modifications/ }).first().click();

test.use({ viewport: { width: 1536, height: 1000 } });

test.describe.serial('l\'en-tête et le dos', () => {
  test('« Taille du nom » est là, à côté de « Taille du logo », et tient', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard/card');
    await expect(page.getByLabel('Taille du logo à côté du nom')).toBeVisible({ timeout: 25000 });
    await expect(nameSize(page), 'le réglage qui manquait').toBeVisible();

    await nameSize(page).fill('40');
    await expect(page.getByText('40 %').first()).toBeVisible();
    await saveIt(page);

    await page.reload();
    await expect(nameSize(page)).toHaveValue('40', { timeout: 25000 });

    await nameSize(page).fill('100');        // remis comme avant
    await saveIt(page);
    await page.reload();
    await expect(nameSize(page)).toHaveValue('100', { timeout: 25000 });
  });

  test('le dos garde de vraies conditions d\'utilisation', async ({ page, request }) => {
    await asOwner(page, request);
    const terms = Array.from({ length: 9 }, (_, i) => `${i + 1}. Condition numéro ${i + 1}.`).join(' ');
    await page.goto('/dashboard/card');
    await page.getByRole('button', { name: /Options avancées/ }).first().click();
    await expect(page.getByText('Informations complémentaires')).toBeVisible({ timeout: 25000 });

    await page.getByRole('button', { name: /Ajouter une ligne/ }).click();
    const row = page.locator('input[placeholder="Horaires"]').last();
    await row.fill("Conditions d'utilisation");
    const box = page.getByLabel("Valeur — Conditions d'utilisation");
    await box.fill(terms);
    // une zone qui grandit avec le texte, pas une ligne qui coupe
    expect((await box.boundingBox()).height, 'la zone a grandi').toBeGreaterThan(40);
    await saveIt(page);

    await page.reload();
    await page.getByRole('button', { name: /Options avancées/ }).first().click();
    await expect(page.getByLabel("Valeur — Conditions d'utilisation"))
      .toHaveValue(terms, { timeout: 25000 });

    // remis comme avant : la ligne est retirée
    await page.getByRole('button', { name: 'Supprimer la ligne' }).last().click();
    await saveIt(page);
    await page.reload();
    await page.getByRole('button', { name: /Options avancées/ }).first().click();
    await expect(page.getByLabel("Valeur — Conditions d'utilisation")).toHaveCount(0, { timeout: 25000 });
  });
});
