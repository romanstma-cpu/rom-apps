import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'rom-practice-zero-'));
for (const dir of ['Roaming', 'Local', 'profile']) {
  fs.mkdirSync(path.join(sandbox, dir));
}
const app = await electron.launch({
  executablePath: path.resolve('node_modules/electron/dist/electron.exe'),
  args: [process.cwd(), `--user-data-dir=${path.join(sandbox, 'profile')}`],
  env: {...process.env, APPDATA: path.join(sandbox, 'Roaming'), LOCALAPPDATA: path.join(sandbox, 'Local')},
  timeout: 30000,
});
try {
  const page = await app.firstWindow();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.getByRole('button', {name: 'Continue to API setup'}).click();
  const [backend, account, status] = await page.evaluate(async () => Promise.all([
    window.rom.backend.info(), window.rom.data.account(), window.rom.trading.status(),
  ]));
  assert.equal(backend.status, 'running');
  const zeroAccount = {...account, cashUsd: 0};
  const blockedStatus = {
    ...status,
    executionHealth: {...status.executionHealth, blocked: true},
    readiness: {
      ...status.readiness,
      status: 'not_ready',
      checks: {
        ...status.readiness?.checks,
        database: {status: 'up'},
        disk: {status: 'up'},
      },
    },
    main: status.main.map(gate => gate.id === 'qualifiedEdge'
      ? {...gate, state: 'blocked', reason: 'More settled evidence needed'} : gate),
  };
  await app.evaluate(({ipcMain, BrowserWindow}, fixtures) => {
    ipcMain.removeHandler('trading:status');
    ipcMain.handle('trading:status', () => fixtures.status);
    const win = BrowserWindow.getAllWindows()[0];
    win.webContents.send('backend:info', fixtures.backend);
    win.webContents.send('data:account', fixtures.account);
  }, {status: blockedStatus, backend: {...backend, authOk: true}, account: zeroAccount});
  await page.getByRole('navigation').getByRole('button', {name: 'Strategy', exact: true}).click();
  const practice = page.getByRole('button', {name: 'Start practice', exact: true});
  const live = page.getByRole('button', {name: 'Start live', exact: true});
  await page.waitForFunction(() => {
    const buttons = [...document.querySelectorAll('button')];
    const practice = buttons.find(button => button.textContent?.trim() === 'Start practice');
    const live = buttons.find(button => button.textContent?.trim() === 'Start live');
    return practice && !practice.disabled && live?.disabled;
  });
  assert.equal(await practice.isEnabled(), true);
  assert.equal(await live.isDisabled(), true);
  await practice.click();
  await page.waitForFunction(async () => (await window.rom.config.get()).mainPaperTrading === true);
  const config = await page.evaluate(() => window.rom.config.get());
  assert.equal(config.enableTrading, false);
  assert.deepEqual(errors, []);
  console.log('PASS: zero-balance Practice can start while live execution and evidence are blocked');
} finally {
  await app.close();
}
