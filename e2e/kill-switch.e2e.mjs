import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rom-kill-switch-'));
for (const dir of ['Roaming', 'Local']) fs.mkdirSync(path.join(root, dir));
const app = await electron.launch({
  executablePath: process.env.ROM_E2E_EXE || path.resolve('node_modules/electron/dist/electron.exe'),
  args: [...(process.env.ROM_E2E_EXE ? [] : [process.cwd()]), `--user-data-dir=${root}/profile`],
  env: { ...process.env, APPDATA: path.join(root, 'Roaming'), LOCALAPPDATA: path.join(root, 'Local') },
});
try {
  const page = await app.firstWindow();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));

  // Kill switch only arms when a filled position exists, so the dashboard is
  // seeded with one open fixture via the stubbed IPC handler (no real trades).
  const openPosition = {
    id: 1, signalSource: 'momentum', signalId: 1, ticker: 'fixture-open-kill',
    eventTicker: 'fixture-open-kill-evt', title: 'Fixture open kill', category: 'other',
    direction: 'yes', action: 'buy', targetContracts: 3, limitPriceCents: 50,
    filledContracts: 3, avgFillPriceCents: 50, costUsd: 1.5, feesUsd: 0.01,
    clientOrderId: 'kill-open', orderId: null, status: 'filled', confidence: 0.8,
    edgePts: 6, signalPriceCents: 49, resolved: false, outcomeCorrect: null,
    settlementUsd: null, pnlUsd: null, markPriceCents: 55, livePnlUsd: 0.15,
    balanceBeforeUsd: 1000, network: 'mainnet',
    createdAt: new Date().toISOString(), lastUpdated: new Date().toISOString(),
    resolvedAt: null, error: null,
  };
  await page.getByRole('button', { name: 'Continue to API setup' }).click();
  await app.evaluate(({ ipcMain }, rows) => {
    ipcMain.removeHandler('data:positions');
    ipcMain.handle('data:positions', () => rows);
    ipcMain.removeHandler('trading:flatten');
    ipcMain.handle('trading:flatten', () => ({ ok: false, message: 'Fixture exit rejected by mocked venue' }));
  }, [openPosition]);
  // The kill switch lives on the Detailed analytics (Dashboard) page,
  // which is under the collapsed "Advanced tools" group.
  const adv = page.getByRole('button', { name: /Advanced tools/ });
  if (await adv.count()) {
    const expanded = await adv.getAttribute('aria-expanded');
    if (expanded !== 'true') await adv.click();
  }
  await page.getByRole('navigation').getByRole('button', { name: 'Detailed analytics', exact: true }).click();
  // The position loads via the state poll; the kill switch only renders
  // once an open position is in state, so wait (with the default 12s poll)
  // for it to appear.
  await page.getByRole('button', { name: 'Kill switch', exact: true }).waitFor({ timeout: 25000 });
  await page.getByRole('button', { name: 'Kill switch', exact: true }).click();
  await page.getByRole('button', { name: 'Yes, flatten all', exact: true }).click();

  // A rejected exit must say so honestly — and never claim positions were sold.
  await page.getByRole('status').filter({ hasText: 'Exit request failed: Fixture exit rejected by mocked venue' }).first().waitFor();
  assert.equal(await page.getByText('All positions flattened', { exact: true }).count(), 0);

  // A zero-fill success is reported as a completed ATTEMPT, not as positions sold.
  await app.evaluate(({ ipcMain }) => {
    ipcMain.removeHandler('trading:flatten');
    ipcMain.handle('trading:flatten', () => ({ ok: true, data: { closed: 0 } }));
  });
  await page.getByRole('button', { name: 'Yes, flatten all', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Exit attempt completed.' }).first().waitFor();
  assert.equal(await page.getByText('All positions flattened', { exact: true }).count(), 0);
  assert.equal(await page.getByRole('button', { name: 'Kill switch', exact: true }).isVisible(), true);

  assert.equal((await page.evaluate(() => window.rom.config.get())).enableTrading, false);
  assert.deepEqual(errors, []);
  console.log('PASS: kill-switch rejected exit and zero-fill attempt feedback are honest; no live orders');
} finally {
  await app.close();
}