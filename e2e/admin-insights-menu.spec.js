/** Super admin › Insights › ⋯ opens whole on screen, one at a time (user, 2026-11-10). */
import { test } from '@playwright/test';
import { SIZES, signIn, checkMenus } from './helpers/menuOnScreen.js';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only

for (const size of SIZES) {
  test(`every line's ⋯ menu opens whole on screen (${size.width}×${size.height})`, async ({ page, request }) => {
    test.setTimeout(120_000);
    await page.setViewportSize(size);
    await signIn(page, request, ADMIN);
    await page.goto('/admin/insights');
    // the first type with businesses in it (the demo data fills some, not all)
    const tabs = page.getByRole('button', { name: /^(Opportunités|À surveiller|Risque|Upgrade potentiel) \(\d+\)$/ });
    await tabs.first().waitFor({ timeout: 60_000 });
    let picked = false;
    for (const t of await tabs.all()) {
      if (Number(((await t.innerText()).match(/\((\d+)\)/) || [])[1] || 0) > 0) { await t.click(); picked = true; break; }
    }
    test.skip(!picked, 'no business in any Insights type in the local demo data');
    await checkMenus(page, page.getByRole('button', { name: /^Actions pour / }), { min: 1 });
  });
}
