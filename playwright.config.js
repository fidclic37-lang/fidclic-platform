// Customer-journey smoke test (2026-10-09, after #176 shipped a « Carte
// introuvable » no test saw): a real browser walks what a customer does —
// signup, the card, the Wallet tiles, a friend's QR, getting a card back —
// against the local server (scripts/dev_local.py: dist + API, in-memory demo
// data). Run: npx vite build && npm run e2e
//   Local Chrome instead of the bundled Chromium: PW_CHANNEL=chrome npm run e2e
import { defineConfig } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT || 8790);
const PY = process.env.PYTHON || 'python3';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    viewport: { width: 390, height: 844 },          // a phone — customers are on phones
    locale: 'fr-FR',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {}),
  },
  webServer: {
    command: `${PY} scripts/dev_local.py`,
    env: { PORT: String(PORT) },
    url: `http://localhost:${PORT}/login`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
