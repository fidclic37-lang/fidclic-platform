/** Catalogue › products › ⋮ opens whole on screen, one at a time (user, 2026-11-10). */
import { test, expect } from '@playwright/test';
import { SIZES, signIn, checkMenus } from './helpers/menuOnScreen.js';

for (const size of SIZES) {
  test(`every product's ⋮ menu opens whole on screen (${size.width}×${size.height})`, async ({ page, request }) => {
    await page.setViewportSize(size);
    const H = await signIn(page, request);
    // a catalogue long enough to have rows at the bottom (local demo shop only; a name already there is skipped)
    const items = Array.from({ length: 12 }, (_, i) => ({ name: `Produit test menu ${i + 1}`, price: 3 + i, category: 'Tests' }));
    const r = await request.post('/api/owner/catalogue/products/import', { headers: H, data: { items } });
    expect(r.ok(), await r.text()).toBeTruthy();
    await page.goto('/dashboard/catalogue');
    await checkMenus(page, page.getByRole('button', { name: /^Plus d'actions — / }));
  });
}
