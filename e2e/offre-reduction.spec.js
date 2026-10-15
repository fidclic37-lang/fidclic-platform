// « Offre spéciale », step 1 (user, 2026-10-15): the « % » used to sit in the
// field before the merchant had chosen anything, and the phone beside the form
// ran its whole length.
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function openOffer(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const br = await (await request.get('/api/owner/branches',
    { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed');
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store.id]);
  await page.goto('/dashboard/campaigns');
  await page.getByText('Offre spéciale', { exact: false }).first().click();
  const choisir = page.getByRole('button', { name: 'Choisir' });
  for (let i = 0; i < await choisir.count(); i++) {
    const near = await choisir.nth(i).evaluate((b) => b.closest('div,section,article')?.textContent?.slice(0, 60) || '');
    if (/Offre/.test(near)) { await choisir.nth(i).click(); break; }
  }
  await expect(page.getByText('1. Définissez votre offre')).toBeVisible();
}

// what the value row shows, or null when there is no row at all
const row = (page) => page.evaluate(() => {
  const inp = [...document.querySelectorAll('input')].find((i) => ['20', '5'].includes(i.placeholder));
  return inp ? (inp.parentElement.innerText || '').trim() : null;
});

test.describe('the special offer, step 1', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('no discount type is chosen for the merchant, and the unit follows', async ({ page, request }) => {
    await openOffer(page, request);
    expect(await row(page), 'nothing is asked until a type is chosen').toBeNull();

    await page.getByRole('button', { name: /Montant fixe/ }).click();
    expect(await row(page), 'a fixed amount is in euros').toBe('€');

    await page.getByRole('button', { name: /Pourcentage/ }).click();
    expect(await row(page), 'a percentage is in percent').toBe('%');

    // clicking the chosen one again gives the choice back
    await page.getByRole('button', { name: /Pourcentage/ }).click();
    expect(await row(page), 'and the choice can be undone').toBeNull();
  });

  test('the phone beside the form stays a preview', async ({ page, request }) => {
    await openOffer(page, request);
    const box = await page.evaluate(() => {
      const el = [...document.querySelectorAll('div')].find((e) => /aspect-\[9/.test(e.className || ''));
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height) };
    });
    expect(box, 'the phone is drawn').toBeTruthy();
    expect(box.h, 'it no longer runs the length of the form').toBeLessThan(500);
    expect(box.w / box.h, 'and it is still a phone').toBeCloseTo(9 / 19.5, 1);
  });
});
