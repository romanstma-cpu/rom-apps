/**
 * Unit tests for electron/system/config-validate.ts.
 * Runs as a standalone Node script (pattern: e2e/evidence.test.mjs) —
 * transpiles the TS with typescript, loads in a vm context, asserts.
 * Run: node scripts/test-config-validate.mjs
 */
import assert from 'node:assert/strict';
import { deepEqual } from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
import vm from 'node:vm';

const srcPath = path.resolve('electron/system/config-validate.ts');
const output = ts.transpileModule(fs.readFileSync(srcPath, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const context = { exports: {} };
vm.runInNewContext(output, context);
const { validateConfigPatch } = context.exports;

// Load the actual defaults without starting Electron or touching saved settings.
const settingsOutput = ts.transpileModule(fs.readFileSync('electron/system/settings-store.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const settingsContext = {exports: {}, require: () => ({})};
vm.runInNewContext(settingsOutput, settingsContext);
const defaultsResult = validateConfigPatch(settingsContext.exports.DEFAULT_CONFIG);
assert.equal(defaultsResult.ok, true, `shipped defaults must be restorable: ${defaultsResult.errors?.join('; ')}`);
deepEqual(defaultsResult.value, settingsContext.exports.DEFAULT_CONFIG, 'restoring defaults must not silently drop settings');

// --- happy path: valid patch ---
{
  const r = validateConfigPatch({ enableTrading: true, minEdgePtsWhale: 3.5, maxOpenPositions: 10 });
  assert.equal(r.ok, true, 'valid patch accepted');
  deepEqual(r.value, { enableTrading: true, minEdgePtsWhale: 3.5, maxOpenPositions: 10 });
}

// --- non-object ---
{
  const r = validateConfigPatch(null);
  assert.equal(r.ok, false);
  assert.match(r.errors[0], /plain object/);
  assert.equal(validateConfigPatch('x').ok, false);
  assert.equal(validateConfigPatch(42).ok, false);
  assert.equal(validateConfigPatch([1, 2]).ok, false, 'array is not a config object');
}

// --- NaN / Infinity rejected ---
{
  const r = validateConfigPatch({ maxOpenPositions: NaN });
  assert.equal(r.ok, false, 'NaN rejected');
  assert.match(r.errors.join(' '), /maxOpenPositions/);
  const r2 = validateConfigPatch({ hardMaxPositionUsd: Infinity });
  assert.equal(r2.ok, false, 'Infinity rejected');
  const r3 = validateConfigPatch({ minSizeFraction: -Infinity });
  assert.equal(r3.ok, false, '-Infinity rejected');
}

// --- wrong type rejected ---
{
  const r = validateConfigPatch({ enableTrading: 'yes' });
  assert.equal(r.ok, false, 'string where boolean expected');
  assert.match(r.errors.join(' '), /enableTrading/);
  const r2 = validateConfigPatch({ enableTrading: 1 });
  assert.equal(r2.ok, false, 'number where boolean expected');
  const r3 = validateConfigPatch({ maxOpenPositions: 'ten' });
  assert.equal(r3.ok, false);
  const r4 = validateConfigPatch({ tradeScanInterval: {} });
  assert.equal(r4.ok, false, 'object where number expected');
}

// --- unknown keys dropped (forward-compatible) ---
{
  const r = validateConfigPatch({ definitelyNotAConfigKey: 1, enableTrading: true });
  assert.equal(r.ok, true);
  deepEqual(r.value, { enableTrading: true }, 'unknown key dropped');
}

// --- enum validation ---
{
  assert.equal(validateConfigPatch({ sizingMode: 'percent' }).ok, true);
  const r = validateConfigPatch({ sizingMode: 'huge' });
  assert.equal(r.ok, false, 'invalid enum rejected');
  assert.match(r.errors.join(' '), /sizingMode/);
  assert.equal(validateConfigPatch({ crypto15mInterval: '45m' }).ok, false);
  assert.equal(validateConfigPatch({ network: 'not-a-network' }).ok, false);
}

// --- string arrays ---
{
  for (const orderStyle of ['limit_cross', 'limit_mid', 'market']) {
    assert.equal(validateConfigPatch({orderStyle}).ok, true, `${orderStyle} is a supported price strategy`);
  }
  for (const orderStyle of ['FAK', 'FOK', 'GTC', 'IOC']) {
    assert.equal(validateConfigPatch({orderStyle}).ok, false, `${orderStyle} is time-in-force, not a price strategy`);
  }
}

{
  const r = validateConfigPatch({ allowedCategories: ['crypto', 'politics'] });
  assert.equal(r.ok, true);
  const r2 = validateConfigPatch({ allowedCategories: ['crypto', 42] });
  assert.equal(r2.ok, false, 'non-string array element rejected');
}

// --- null clears optional fields ---
{
  const r = validateConfigPatch({ orderExpirationSec: null });
  assert.equal(r.ok, true);
  assert.equal(r.value.orderExpirationSec, null);
}

// --- rules passthrough (deep-validated by backend) ---
{
  const r = validateConfigPatch({ rules: [{ field: 'minPrice', op: 'gt', value: 20 }] });
  assert.equal(r.ok, true);
  assert.equal(validateConfigPatch({ rules: [{ field: 'x' }] }).ok, true);
  assert.equal(validateConfigPatch({ rules: 'not-rules' }).ok, false);
  assert.equal(validateConfigPatch({ rules: [42] }).ok, false);
}

// --- object with unsupported type (nested object / function) rejected ---
{
  assert.equal(validateConfigPatch({ eventWebhookUrl: { url: 'x' } }).ok, false);
  assert.equal(validateConfigPatch({ rules: {} }).ok, false, 'rules must be array');
}

// --- full replace-style config with every kind of value ---
{
  const r = validateConfigPatch({
    network: 'mainnet', enableTrading: false, mainPaperBankrollUsd: 250,
    minEdgePtsWhale: 2.0, sizingMode: 'kelly', allowedCategories: null,
    eventWebhookUrl: 'https://example.com/hook', orderExpirationSec: 30,
  });
  assert.equal(r.ok, true, 'full replace-style accepted');
  assert.equal(r.value.eventWebhookUrl, 'https://example.com/hook');
}

console.log('PASS: config-validate — shape, NaN/Inf, enums, arrays, unknown-key drop, rules passthrough');
