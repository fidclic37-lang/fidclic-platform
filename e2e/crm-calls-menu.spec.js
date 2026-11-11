/** Super admin › CRM › Appels › ⋯ opens whole on screen, one at a time (user, 2026-11-10). */
import { test, expect } from '@playwright/test';
import { SIZES, signIn, checkMenus } from './helpers/menuOnScreen.js';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only

for (const size of SIZES) {
  test(`every call's ⋯ menu opens whole on screen (${size.width}×${size.height})`, async ({ page, request }) => {
    test.setTimeout(120_000);
    await page.setViewportSize(size);
    const H = await signIn(page, request, ADMIN);
    // calls of its own, so the list has rows to the bottom (local only)
    const p = await (await request.post('/api/crm/prospects', { headers: H, data: { name: `Appels menu ${size.width}`, sector: 'Café', city: 'Tours' } })).json();
    for (let i = 1; i <= 6; i += 1) {
      const r = await request.post('/api/crm/calls', { headers: H, data: { prospect_id: p.id, status: 'termine', result: 'interesse', notes: `appel ${i}` } });
      expect(r.ok(), await r.text()).toBeTruthy();
    }
    await page.goto('/admin/crm/appels');
    await checkMenus(page, page.getByRole('button', { name: 'Actions', exact: true }));
  });
}
