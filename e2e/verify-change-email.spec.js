// « Modifier l'adresse e-mail » on the sign-up code page (QA BUG-001), in a real
// browser. The local server sends no e-mail (no Brevo key), so the sign-up's
// own answers are played here, as production gives them; the page's behaviour
// is what is checked: the corrected address is sent, the new session is kept,
// and the code goes to the new address at once.
// Runs against the local server only (scripts/dev_local.py).
import { test, expect } from '@playwright/test';

test('a mistyped address can be corrected on the code page', async ({ page }) => {
  let email = 'ahmed@gmial.com';
  const calls = [];
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/auth/me', (r) => json(r, { email, role: 'business_owner', tenant_id: 't1', first_name: 'Ahmed',
    onboarding_status: 'verify' }));
  await page.route('**/api/onboarding/verify', (r) => json(r, { channels: { email: true, sms: false },
    email: email.replace(/^(..)[^@]*/, '$1•••'), phone: '' }));
  await page.route('**/api/onboarding/verify/send', (r) => { calls.push(['send', email]); return json(r, { ok: true, channel: 'email', to: email.replace(/^(..)[^@]*/, '$1•••'), expires_in: 600 }); });
  await page.route('**/api/onboarding/verify/email', async (r) => {
    const body = r.request().postDataJSON();
    calls.push(['email', body.email]);
    email = body.email.trim().toLowerCase();
    return json(r, { access_token: 'new-session-token', role: 'business_owner', tenant_id: 't1',
      onboarding_status: 'verify', email: email.replace(/^(..)[^@]*/, '$1•••') });
  });

  await page.goto('/login');
  await page.evaluate(() => localStorage.setItem('fidelitour_access_token', 'old-session-token'));
  await page.goto('/onboarding/verification');
  await expect(page.getByText('ah•••@gmial.com')).toBeVisible();

  // the code went to the typo — the page offers to correct the address
  await page.getByRole('button', { name: /Par e-mail/ }).click();
  await expect(page.getByText(/Code envoyé à ah•••@gmial\.com/)).toBeVisible();
  await page.getByRole('button', { name: /Modifier l'adresse e-mail/ }).click();
  const field = page.getByLabel('Votre adresse e-mail');
  await expect(field).toHaveValue('ahmed@gmial.com');
  await field.fill('ahmed@gmail.com');
  await page.getByRole('button', { name: /Envoyer le code à cette adresse/ }).click();

  await expect(page.getByText(/Code envoyé à ah•••@gmail\.com/)).toBeVisible();
  expect(calls).toEqual([['send', 'ahmed@gmial.com'], ['email', 'ahmed@gmail.com'], ['send', 'ahmed@gmail.com']]);
  expect(await page.evaluate(() => localStorage.getItem('fidelitour_access_token')), 'the new session is kept').toBe('new-session-token');
});
