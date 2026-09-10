import { _electron as electron } from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rom-terminal-review-'));
for (const dir of ['Roaming', 'Local']) fs.mkdirSync(path.join(root, dir));
const app = await electron.launch({executablePath: process.env.ROM_E2E_EXE || path.resolve('node_modules/electron/dist/electron.exe'), args: [...(process.env.ROM_E2E_EXE ? [] : [process.cwd()]), `--user-data-dir=${root}/profile`], env: {...process.env, APPDATA: path.join(root, 'Roaming'), LOCALAPPDATA: path.join(root, 'Local')}});
try {
  const p = await app.firstWindow();
  const errors = []; p.on('pageerror', e => errors.push(e.message));
  await p.keyboard.press('Control+3');
  await p.getByRole('dialog').waitFor();
  await p.getByRole('button', {name: 'Continue to API setup'}).click();
  await p.getByLabel('Key ID', {exact: true}).focus();
  await p.keyboard.press('Control+3');
  assert.equal(await p.getByLabel('Key ID', {exact: true}).isVisible(), true);
  await p.getByRole('navigation').getByRole('button', {name: 'Overview', exact: true}).click();
  await p.getByRole('heading', {name: 'Latest decision cycle'}).waitFor();
  await p.screenshot({path: '.work/terminal-review-desktop.png'});
  await app.evaluate(({BrowserWindow}) => { const w = BrowserWindow.getAllWindows()[0]; w.setMinimumSize(480, 500); w.setSize(600, 800); });
  await p.emulateMedia({reducedMotion: 'reduce'});
  await p.waitForTimeout(300);
  assert.equal(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await p.getByRole('button', {name: 'Review strategy & limits', exact: true}).scrollIntoViewIfNeeded();
  await p.screenshot({path: '.work/terminal-review-narrow.png'});
  await app.evaluate(({ipcMain}) => {
    ipcMain.removeHandler('data:positions');
    ipcMain.handle('data:positions', () => [{id: 1, ticker: 'fixture-market', title: 'Fixture position', status: 'filled', resolved: false, filledContracts: 10, costUsd: 4, direction: 'yes', signalSource: 'momentum', createdAt: new Date().toISOString()}]);
    ipcMain.removeHandler('trading:flatten');
    ipcMain.handle('trading:flatten', () => ({ok: false, message: 'Fixture exit rejected'}));
  });
  await p.getByRole('button', {name: 'Open detailed analytics →'}).click();
  await p.getByRole('button', {name: 'Kill switch', exact: true}).click({timeout: 20000});
  await p.getByRole('button', {name: 'Yes, flatten all', exact: true}).click();
  await p.getByRole('status').filter({hasText: 'Exit request failed: Fixture exit rejected'}).first().waitFor();
  assert.equal(await p.getByText('All positions flattened', {exact: true}).count(), 0);
  await app.evaluate(({ipcMain}) => {
    ipcMain.removeHandler('trading:flatten');
    ipcMain.handle('trading:flatten', () => ({ok: true, data: {closed: 0}}));
  });
  await p.getByRole('button', {name: 'Yes, flatten all', exact: true}).click();
  await p.getByRole('status').filter({hasText: 'Exit attempt completed.'}).first().waitFor();
  assert.equal(await p.getByRole('button', {name: 'Kill switch', exact: true}).isVisible(), true);
  assert.equal((await p.evaluate(() => window.rom.config.get())).enableTrading, false);
  assert.deepEqual(errors, []);
  console.log('PASS: terminal layout, narrow/reduced-motion, shortcut guards, failed and zero-fill exit feedback; no live orders');
} finally { await app.close(); }
