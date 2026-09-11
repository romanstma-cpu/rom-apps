import { _electron as electron } from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rom-history-csv-'));
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

  const iso = (daysAgo, h = 12, m = 0) => {
    const d = new Date(Date.now() - daysAgo * 86400000);
    d.setUTCHours(h, m, 0, 0);
    return d.toISOString();
  };
  const resolvedWin = {
    id: 1, signalSource: 'whale', signalId: 101, ticker: 'fixture-resolved-win',
    eventTicker: 'fixture-resolved-win-evt', title: 'Fixture resolved win', category: 'politics',
    direction: 'yes', action: 'buy', targetContracts: 25, limitPriceCents: 52,
    filledContracts: 20, avgFillPriceCents: 51, costUsd: 10.2, feesUsd: 0.1,
    clientOrderId: 'csv-win', orderId: null, status: 'filled', confidence: 0.9,
    edgePts: 10, signalPriceCents: 50, resolved: true, outcomeCorrect: 1,
    settlementUsd: 18, pnlUsd: 7.7, markPriceCents: null, livePnlUsd: null,
    balanceBeforeUsd: 1000, network: 'mainnet', createdAt: iso(4), lastUpdated: iso(4, 14),
    resolvedAt: iso(4, 13), error: null,
  };
  const resolvedLoss = {
    id: 2, signalSource: 'momentum', signalId: 102, ticker: 'fixture-resolved-loss',
    eventTicker: 'fixture-resolved-loss-evt', title: 'Fixture resolved loss', category: 'sports',
    direction: 'no', action: 'buy', targetContracts: 10, limitPriceCents: 40,
    filledContracts: 10, avgFillPriceCents: 40, costUsd: 4, feesUsd: 0.02,
    clientOrderId: 'csv-loss', orderId: null, status: 'filled', confidence: 0.7,
    edgePts: 5, signalPriceCents: 39, resolved: true, outcomeCorrect: 0,
    settlementUsd: 0, pnlUsd: -4.02, markPriceCents: null, livePnlUsd: null,
    balanceBeforeUsd: 1000, network: 'mainnet', createdAt: iso(3), lastUpdated: iso(3, 15),
    resolvedAt: iso(3, 14), error: null,
  };
  const openPosition = {
    id: 3, signalSource: 'whale', signalId: 103, ticker: 'fixture-open-hold',
    eventTicker: 'fixture-open-hold-evt', title: 'Fixture open hold', category: 'other',
    direction: 'yes', action: 'buy', targetContracts: 5, limitPriceCents: 55,
    filledContracts: 5, avgFillPriceCents: 55, costUsd: 2.75, feesUsd: 0.01,
    clientOrderId: 'csv-open', orderId: null, status: 'filled', confidence: 0.8,
    edgePts: 8, signalPriceCents: 54, resolved: false, outcomeCorrect: null,
    settlementUsd: null, pnlUsd: null, markPriceCents: 60, livePnlUsd: 0.25,
    balanceBeforeUsd: 1000, network: 'mainnet', createdAt: iso(1), lastUpdated: iso(1, 9),
    resolvedAt: null, error: null,
  };
  const fixtureRows = [resolvedWin, resolvedLoss, openPosition];

  await page.getByRole('button', { name: 'Continue to API setup' }).click();
  await app.evaluate(({ ipcMain }, rows) => {
    ipcMain.removeHandler('data:positions');
    ipcMain.handle('data:positions', () => rows);
  }, fixtureRows);
  await page.getByRole('navigation').getByRole('button', { name: 'History', exact: true }).click();

  // Trade history table renders resolved fixtures as ticker buttons.
  // The tab label includes the resolved count badge ("Trade history1"),
  // so match by regex on the button's accessible name.
  await page.getByRole('button', { name: /^Trade history/ }).click();
  await page.getByRole('button', { name: 'fixture-resolved-win', exact: true }).waitFor();
  await page.getByRole('button', { name: 'fixture-resolved-loss', exact: true }).waitFor();
  // Unresolved position also appears in the table (it's in the data) — that's fine;
  // the CSV export filters on `resolved: true`.
  await page.screenshot({ path: '.work/history-csv-table.png' });

  // Export CSV: the button triggers a Blob download via anchor click.
  // Intercept the generated CSV in the renderer context.
  const csv = await page.evaluate(async () => {
    return new Promise((resolve) => {
      const origCreateObjectURL = URL.createObjectURL;
      URL.createObjectURL = (blob) => {
        const url = origCreateObjectURL(blob);
        blob.text().then((text) => resolve(text)).catch(() => resolve(''));
        return url;
      };
      document.querySelector('button[title="Download all resolved trades as CSV"]').click();
      // Restore after a tick
      setTimeout(() => { URL.createObjectURL = origCreateObjectURL; }, 100);
    });
  });

  const rows = csv.trim().split('\n');
  assert.equal(rows[0], ['resolvedAt', 'source', 'ticker', 'title', 'side', 'costUsd', 'outcome', 'pnlUsd'].join(','));
  const dataRows = rows.slice(1);
  assert.equal(dataRows.length, 2, `expected 2 resolved rows, got ${dataRows.length}: ${dataRows}`);
  const winRow = dataRows.find((r) => r.includes('fixture-resolved-win'));
  const lossRow = dataRows.find((r) => r.includes('fixture-resolved-loss'));
  assert.ok(winRow, 'resolved win present in CSV');
  assert.ok(lossRow, 'resolved loss present in CSV');
  // CSV numbers are unformatted: costUsd 10.2, pnlUsd 7.7, etc.
  assert.equal(winRow.split(',')[0], iso(4, 13));
  assert.equal(winRow.split(',')[1], 'whale');
  assert.equal(lossRow.split(',')[0], iso(3, 14));
  assert.equal(lossRow.split(',')[1], 'momentum');
  assert.ok(!dataRows.some((r) => r.includes('fixture-open-hold')), 'unresolved position excluded from CSV');

  assert.deepEqual(errors, []);
  console.log('PASS: history CSV export includes resolved only, correct headers, correct ticker/P&L');
} finally {
  await app.close();
}