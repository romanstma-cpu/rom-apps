// The operator's escape hatch from a halted order journal.
//
// A blocking intent stops submissions from EVERY engine with no timeout and no
// automatic forget path. Until this panel existed the documented recovery route
// was reachable only by writing JSON-RPC to the backend's stdin with the app
// shut down, so the whole chain is worth pinning down.
//
// The intent is seeded directly into the backend's own SQLite file rather than
// stubbed in the renderer: window.rom is frozen by contextBridge, and a seeded
// row proves the real path - order_journal.blocked_intents -> trading status ->
// IPC -> panel - instead of proving a mock.
import { _electron as electron } from 'playwright-core';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rom-recovery-'));
for (const d of ['Roaming', 'Local']) fs.mkdirSync(path.join(root, d));

const PY = path.resolve('python/.venv/Scripts/python.exe');
const INTENT = {
  localId: 'rom-whale-42-ab12cd34', ticker: 'TEST-MARKET-2026',
  side: 'yes', action: 'buy', quantity: 3, limitPrice: 0.42,
};

const findDb = () => {
  const hits = [];
  const walk = (dir, depth) => {
    if (depth > 6) return;
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) walk(full, depth + 1);
      else if (e.name === 'rom-polybot.db') hits.push(full);
    }
  };
  walk(root, 0);
  return hits[0] ?? null;
};

let passed = 0;
const check = (what, cond) => {
  assert.equal(cond, true, what);
  console.log(`  ok   ${what}`);
  passed++;
};

const app = await electron.launch({
  executablePath: path.resolve('node_modules/electron/dist/electron.exe'),
  args: [process.cwd(), `--user-data-dir=${root}/profile`],
  env: { ...process.env, APPDATA: path.join(root, 'Roaming'), LOCALAPPDATA: path.join(root, 'Local') },
});

try {
  const p = await app.firstWindow();
  const errors = [];
  p.on('pageerror', (e) => errors.push(e.message));

  await p.getByRole('button', { name: 'Continue to API setup' }).click();
  await p.getByRole('navigation').getByRole('button', { name: 'Overview', exact: true }).click();
  await p.waitForTimeout(2500); // let the backend create and migrate the db

  console.log('\nclean journal');
  check('no recovery panel while nothing is blocked',
    (await p.getByRole('region', { name: /recovery/i }).count()) === 0);

  const db = findDb();
  check('backend created its database', db !== null);

  console.log('\nblocked journal');
  // `sending` is the state a process death between the pre-POST journal commit
  // and the exchange's answer leaves behind - the case the operator is most
  // likely to meet, and the one with no order id to reconcile against.
  execFileSync(PY, ['-c', `
import sqlite3, time, sys
c = sqlite3.connect(sys.argv[1])
c.execute("""CREATE TABLE IF NOT EXISTS us_order_intents (
 local_id TEXT PRIMARY KEY, order_id TEXT UNIQUE, ticker TEXT NOT NULL,
 side TEXT NOT NULL, action TEXT NOT NULL, quantity REAL NOT NULL,
 limit_price REAL NOT NULL, reserved_usd REAL NOT NULL,
 state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
 filled REAL NOT NULL DEFAULT 0, avg_price REAL, fees_usd REAL, error TEXT)""")
now = time.time()
c.execute("INSERT OR REPLACE INTO us_order_intents (local_id,order_id,ticker,side,action,"
          "quantity,limit_price,reserved_usd,state,created_at,updated_at) "
          "VALUES (?,NULL,?,?,?,?,?,?, 'sending', ?, ?)",
          ("${INTENT.localId}", "${INTENT.ticker}", "${INTENT.side}", "${INTENT.action}",
           ${INTENT.quantity}, ${INTENT.limitPrice}, 1.29, now-45, now-45))
c.commit(); c.close()
`, db], { stdio: 'pipe' });

  await p.waitForTimeout(6500); // the page polls trading status every 5s

  const panel = p.getByRole('region', { name: /recovery/i });
  await panel.waitFor({ timeout: 8000 });
  check('recovery panel appears once the journal is blocked', await panel.isVisible());

  fs.mkdirSync('.work', { recursive: true });
  await p.screenshot({ path: '.work/order-recovery.png' });

  const text = await panel.innerText();
  check('names the halted market', text.includes(INTENT.ticker));
  check('says every engine has stopped', /every engine/i.test(text));
  check('explains what the sending state means', /before the exchange answered/i.test(text));
  check('warns against guessing an order id', /do not guess/i.test(text));
  check('shows the local id the operator must quote', text.includes(INTENT.localId));

  // An unlabelled field here would make the only route out of a halt unusable
  // with a screen reader.
  const field = p.getByLabel(new RegExp(`Exchange order ID for ${INTENT.ticker}`, 'i'));
  check('the id field has an accessible name', (await field.count()) === 1);

  const submit = panel.getByRole('button', { name: /Link and reconcile/i });
  check('submit is disabled while the field is empty', await submit.isDisabled());
  await field.fill('   ');
  check('submit stays disabled for whitespace only', await submit.isDisabled());
  await field.fill('EXCHANGE-ORDER-9f8e7d');
  check('submit enables once an id is entered', !(await submit.isDisabled()));

  // With no credentials configured the backend cannot verify the order, so the
  // click must surface a legible refusal. Before this work the same handler
  // raised KeyError on a missing argument; a halted operator must never be met
  // with an opaque crash.
  await submit.click();
  await p.waitForTimeout(2500);
  const body = await p.evaluate(() => document.body.innerText);
  check('a failed recovery reports something legible, not a crash',
    /credential|not configured|refus|unable|error|failed/i.test(body));
  check('the panel is still shown so the operator can retry', await panel.isVisible());

  console.log('\nhealth');
  check('no renderer console errors', errors.length === 0);

  console.log(`\n${passed} passed, 0 failed`);
} catch (e) {
  console.error('\nFAILED:', e.message);
  process.exitCode = 1;
} finally {
  await app.close();
}
