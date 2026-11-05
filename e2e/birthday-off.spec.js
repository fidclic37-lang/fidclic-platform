/**
 * « Business ne off kr rakha hai, fir bhi jaa rha hai » (user, 2026-11-05): the
 * Carte's « Notification anniversaire » is the switch of the automation that
 * really sends, both ways, and another save never puts it back. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function setup(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) };
}

const birthdayRow = async (request, SH) => {
  const { rows } = await (await request.get('/api/owner/automations', { headers: SH })).json();
  return rows.find((r) => r.scenario === 'birthday');
};

async function openSwitch(page) {
  await page.goto('/dashboard/card');
  await page.getByRole('button', { name: /Paramètres/ }).first().click();
  return page.getByRole('button', { name: /Notification anniversaire/ });
}

const isOn = (sw) => sw.locator('span.rounded-full').first();

async function save(page) {
  const put = page.waitForResponse((r) => r.url().includes('/owner/card/settings') && r.request().method() === 'PUT' && r.ok());
  await page.getByRole('button', { name: /Enregistrer les (modifications|options)/ }).first().click();
  return JSON.parse((await put).request().postData() || '{}');
}

test.describe('the Carte switch stops the birthday automation', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('off on the Carte: paused everywhere; on again: active; another save keeps it', async ({ page, request }) => {
    const SH = await setup(page, request);
    const row = await birthdayRow(request, SH);
    const on = await request.post(`/api/owner/automations/${row.id}/status`, { headers: SH, data: { status: 'active' } });
    expect(on.ok(), await on.text()).toBeTruthy();

    // on → off
    let sw = await openSwitch(page);
    await expect(isOn(sw)).toHaveClass(/bg-\[#2F6BFF\]/, { timeout: 20_000 });
    await sw.click();
    const off = await save(page);
    expect(off.birthday_switch).toBe(false);
    await expect.poll(async () => (await birthdayRow(request, SH)).status, { timeout: 15_000 }).toBe('paused');

    // the Automatisations page shows the same switch, off
    await page.goto('/dashboard/automations');
    await expect(page.getByRole('switch', { name: `Activer ${row.name}` })).toHaveAttribute('aria-checked', 'false', { timeout: 20_000 });

    // back on the Carte it reads off; a save of something else does not send it, and leaves it off
    sw = await openSwitch(page);
    await expect(isOn(sw)).toHaveClass(/bg-\[#CBD5E1\]/, { timeout: 20_000 });
    await page.getByRole('button', { name: /Afficher le message sur la carte/ }).click();
    const other = await save(page);
    expect('birthday_switch' in other).toBe(false);
    expect((await birthdayRow(request, SH)).status).toBe('paused');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: /Afficher le message sur la carte/ }).click();
    await save(page);

    // off → on
    await page.waitForLoadState('networkidle');
    await sw.click();
    const back = await save(page);
    expect(back.birthday_switch).toBe(true);
    await expect.poll(async () => (await birthdayRow(request, SH)).status, { timeout: 15_000 }).toBe('active');

    // leave the demo shop as it should be: off
    await request.post(`/api/owner/automations/${row.id}/status`, { headers: SH, data: { status: 'paused' } });
  });

  test('Paramètres: « Birthday wishes » is the same switch, and a save that flips nothing leaves it', async ({ page, request }) => {
    const SH = await setup(page, request);
    const row = await birthdayRow(request, SH);
    await request.post(`/api/owner/automations/${row.id}/status`, { headers: SH, data: { status: 'active' } });
    const putBody = async () => {
      const put = page.waitForResponse((r) => r.url().includes('/owner/auto-campaigns/config') && r.request().method() === 'PUT' && r.ok());
      await card.getByRole('button', { name: 'Save configuration' }).click();
      return JSON.parse((await put).request().postData() || '{}');
    };
    await page.goto('/dashboard/settings');
    const card = page.locator('#settings-auto');
    const box = card.getByRole('checkbox').first();
    await expect(box).toBeChecked({ timeout: 20_000 });

    // a save with nothing flipped sends no switch at all
    await expect(card.getByRole('button', { name: 'Save configuration' })).toBeEnabled();
    const plain = await putBody();
    expect(Object.keys(plain).filter((k) => /_switch$|_enabled$/.test(k))).toEqual([]);
    expect((await birthdayRow(request, SH)).status).toBe('active');

    // unticked: the automation that really sends is paused
    await box.uncheck();
    const off = await putBody();
    expect(off.birthday_switch).toBe(false);
    await expect.poll(async () => (await birthdayRow(request, SH)).status, { timeout: 15_000 }).toBe('paused');

    // it reads off after a reload
    await page.reload();
    await expect(page.locator('#settings-auto').getByRole('checkbox').first()).not.toBeChecked({ timeout: 20_000 });
  });
});
