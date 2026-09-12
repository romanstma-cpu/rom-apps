import { _electron as electron } from 'playwright-core';
import assert from 'node:assert/strict';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const executablePath = process.argv[2];
if (!executablePath) throw new Error('Pass the packaged app executable path');
const profile = mkdtempSync(join(tmpdir(), 'rom-mac-smoke-'));
const app = await electron.launch({executablePath, args: [`--user-data-dir=${profile}`]});
try {
  const page = await app.firstWindow();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const continueButton = page.getByRole('button', {name: 'Continue to API setup'});
  await continueButton.waitFor({state: 'visible', timeout: 5000}).catch(() => {});
  if (await continueButton.isVisible()) await continueButton.click();
  await page.waitForFunction(async () => (await window.rom.backend.info()).status === 'running', {timeout: 30000});
  const config = await page.evaluate(() => window.rom.config.get());
  assert.equal(config.enableTrading, false);
  assert.equal((await page.evaluate(() => window.rom.backend.info())).authOk, false);
  const practice = await page.evaluate(() => window.rom.trading.practicePerformance());
  assert.ok(['collecting', 'qualified'].includes(practice.status));
  assert.ok(Array.isArray(practice.candidates));
  const allocation = await page.evaluate(() => window.rom.trading.allocationPlan());
  assert.ok(['collecting', 'active'].includes(allocation.status));
  assert.ok(Array.isArray(allocation.candidates));
  const execution = await page.evaluate(() => window.rom.trading.executionQuality());
  assert.equal(execution.windowDays, 30);
  assert.equal(execution.attempts, 0);
  assert.equal(execution.fillRatePct, null);
  await page.getByRole('navigation').getByRole('button', {name: 'Overview', exact: true}).click();
  await page.getByRole('heading', {name: 'Latest decision cycle'}).waitFor();
  assert.deepEqual(errors, []);
  console.log('PASS: packaged renderer, backend, startup, navigation; trading disabled');
} finally { await app.close(); }
