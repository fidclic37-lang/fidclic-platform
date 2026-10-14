// The registration page's image is shown in a circle. Saved as it came, a logo
// wider than it is tall lost its edges — « ROYAL TRIM » read « OYAL TRI »
// (user, 2026-10-13). The owner frames it now, opening on the whole image.
//
// The test image is wide, with a different colour at each far edge: if either
// edge survives the round trip, nothing was cut.
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const LEFT = [0, 80, 255];        // blue
const RIGHT = [0, 200, 60];       // green

const wide = (page) => page.evaluate(([l, r]) => {
  const c = document.createElement('canvas'); c.width = 1200; c.height = 300;
  const x = c.getContext('2d');
  x.fillStyle = '#C81E1E'; x.fillRect(0, 0, 1200, 300);
  x.fillStyle = `rgb(${l.join(',')})`; x.fillRect(0, 0, 60, 300);          // far left
  x.fillStyle = `rgb(${r.join(',')})`; x.fillRect(1140, 0, 60, 300);       // far right
  return c.toDataURL('image/png');
}, [LEFT, RIGHT]);

test.describe('the registration image keeps the whole picture', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('a wide logo is framed whole, not cropped to the circle', async ({ page, request }) => {
    const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
    const br = await (await request.get('/api/owner/branches',
      { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
    const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed');
    await page.goto('/login');
    const dataUrl = await wide(page);
    await page.evaluate(([t, s]) => {
      localStorage.setItem('fidelitour_access_token', t);
      localStorage.setItem('ft_selected_branch_v1', s);          // the shop is chosen after login
    }, [login.access_token, store.id]);

    await page.goto('/dashboard/parametres/lien-inscription');
    const section = page.locator('[data-testid="signup-image"]');
    await expect(section).toBeVisible();

    const bytes = await page.evaluate((u) => Array.from(atob(u.split(',')[1]), (c) => c.charCodeAt(0)), dataUrl);
    await section.locator('input[type="file"]').setInputFiles(
      { name: 'logo.png', mimeType: 'image/png', buffer: Buffer.from(bytes) });

    // the framing dialog opens on the whole image
    await expect(page.getByText("Cadrer l'image")).toBeVisible();
    await expect(page.getByRole('button', { name: "Toute l'image" })).toBeVisible();
    await page.getByRole('button', { name: 'Utiliser ce cadre' }).click();
    await expect(page.getByText("Cadrer l'image")).toHaveCount(0);

    // what was saved: a square, with both far edges of the logo still in it
    const read = () => page.evaluate(() => new Promise((done) => {
      const el = document.querySelector('[data-testid="signup-image"] img');
      if (!el || !el.src) return done(null);
      const im = new Image();
      im.onload = () => {
        const c = document.createElement('canvas');
        c.width = im.naturalWidth; c.height = im.naturalHeight;
        const ctx = c.getContext('2d');
        ctx.drawImage(im, 0, 0);
        const px = ctx.getImageData(0, 0, c.width, c.height).data;
        const near = (want) => {
          for (let i = 0; i < px.length; i += 4) {
            if (Math.abs(px[i] - want[0]) < 45 && Math.abs(px[i + 1] - want[1]) < 45
                && Math.abs(px[i + 2] - want[2]) < 45) return true;
          }
          return false;
        };
        done({ w: im.naturalWidth, h: im.naturalHeight,
               left: near([0, 80, 255]), right: near([0, 200, 60]) });
      };
      im.onerror = () => done(null);
      im.src = el.src;
    }));

    await expect.poll(read, { timeout: 15_000 }).toEqual({ w: 800, h: 800, left: true, right: true });
  });
});
