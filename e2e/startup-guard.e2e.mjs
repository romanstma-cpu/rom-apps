import { _electron as electron } from 'playwright-core';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

const APP_DIR = path.resolve(import.meta.dirname, '..');
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'rom-e2e-'));
const userData = path.join(SANDBOX, 'userData');
const APPDATA = path.join(SANDBOX, 'Roaming');
const LOCALAPPDATA = path.join(SANDBOX, 'Local');
for (const d of [userData, APPDATA, LOCALAPPDATA]) fs.mkdirSync(d, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!fs.existsSync(path.join(APP_DIR, 'dist', 'index.html'))) {
  console.error('dist/index.html missing — run `npm run build` first.');
  process.exit(1);
}

const app = await electron.launch({
  executablePath: path.join(APP_DIR, 'node_modules', 'electron', 'dist',
    process.platform === 'win32' ? 'electron.exe' : 'electron'),
  args: [APP_DIR, `--user-data-dir=${userData}`],
  cwd: APP_DIR,
  env: { ...process.env, APPDATA, LOCALAPPDATA },
  timeout: 90_000,
});

const pageErrors = [];
let passed = 0;
const failures = [];

function check(label, cond, extra = '') {
  if (cond) { passed++; console.log(`  ok   ${label}`); }
  else { failures.push(label); console.log(`  FAIL ${label}${extra ? '  — ' + extra : ''}`); }
}

try {
  const page = await app.firstWindow({ timeout: 60_000 });
  await page.waitForLoadState('domcontentloaded');

  page.on('pageerror', (err) => {
    pageErrors.push(err.message || String(err));
  });

  // Wait long enough for the app to render its initial UI.
  await sleep(8000);

  const bodyNonEmpty = await page.evaluate(() => {
    const body = document.body;
    if (!body) return false;
    // Appliance rendered if the body has any child elements.
    return body.childElementCount > 0;
  });
  check('document.body is non-empty (app rendered)', bodyNonEmpty,
    bodyNonEmpty ? `children=${await page.evaluate(() => document.body?.childElementCount ?? 0)}` : 'body was empty or missing');

  const badErrors = pageErrors.filter((msg) =>
    msg.includes('useContext') || msg.includes('Cannot read properties of null (reading')
  );
  check('no useContext / null-reading pageerror emitted', badErrors.length === 0,
    badErrors.length ? badErrors.map((m) => m.slice(0, 120)).join(' | ') : '');

  console.log(`\ncaptured pageerrors (${pageErrors.length}):`);
  for (const m of pageErrors) console.log('  -', m.slice(0, 200));
} catch (e) {
  failures.push('driver error: ' + e.message);
  console.log('\nDRIVER ERROR:', e.message);
} finally {
  await app.close().catch(() => {});
  fs.rmSync(SANDBOX, { recursive: true, force: true });
}

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length) {
  for (const f of failures) console.log('  FAILED:', f);
  process.exit(1);
}
process.exit(0);
