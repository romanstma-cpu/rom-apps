import { _electron as electron } from 'playwright-core';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'rom-referral-e2e-'));
const appData = path.join(sandbox, 'Roaming');
const localAppData = path.join(sandbox, 'Local');
fs.mkdirSync(appData, { recursive: true });
fs.mkdirSync(localAppData, { recursive: true });

const app = await electron.launch({
  executablePath: path.join(root, 'node_modules', 'electron', 'dist', 'electron.exe'),
  args: [root, `--user-data-dir=${path.join(sandbox, 'profile')}`],
  cwd: root,
  env: { ...process.env, APPDATA: appData, LOCALAPPDATA: localAppData },
  timeout: 60_000,
});

try {
  const page = await app.firstWindow({ timeout: 60_000 });
  await page.waitForLoadState('domcontentloaded');
  const errors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });

  await page.getByText('New to Polymarket US? See the current offer.').waitFor();
  await page.getByText('ROMANR', { exact: true }).waitFor();
  await page.getByText('amount, eligibility and qualifying steps', { exact: false }).waitFor();
  await page.getByRole('button', { name: 'View current offer' }).waitFor();
  await page.getByRole('button', { name: 'Continue to API setup' }).click();
  await page.getByRole('button', { name: 'API', exact: true }).click();
  await page.getByRole('heading', { name: 'See the current offer' }).waitFor();
  await page.getByRole('button', { name: 'View current offer' }).waitFor();

  if (errors.length) throw new Error(`renderer console errors: ${errors.join(' | ')}`);
  console.log('Current referral offer is visible in onboarding and API setup with code ROMANR.');
} finally {
  await app.close();
  fs.rmSync(sandbox, { recursive: true, force: true });
}
