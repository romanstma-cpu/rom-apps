/* Confirm the renderer reads real defaults for every config key.
 *
 * The parity test compares source files; this checks the running app. A key
 * that reads `undefined` here would leave its UI control empty on first run.
 */
import {_electron as electron} from 'playwright-core';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';

const sandbox=fs.mkdtempSync(path.join(os.tmpdir(),'rom-cfgdef-'));
for(const d of ['Roaming','Local','profile'])fs.mkdirSync(path.join(sandbox,d));
const app=await electron.launch({
  executablePath:path.resolve('node_modules/electron/dist/electron.exe'),
  args:[process.cwd(),`--user-data-dir=${path.join(sandbox,'profile')}`],
  env:{...process.env,APPDATA:path.join(sandbox,'Roaming'),LOCALAPPDATA:path.join(sandbox,'Local')},
  timeout:30000,
});
try {
  const p=await app.firstWindow();
  await p.getByRole('button',{name:'Continue to API setup'}).click();
  const cfg=await p.evaluate(()=>window.rom.config.get());

  // The keys this session added defaults for.
  const ADDED=['sizingMode','minContracts','maxContracts','takeProfitPct',
    'lifetimeLossLimitPct','lifetimeLossLimitUsd','copyAllowReentries',
    'copyOnlyNewEntries','copyLifetimeLossLimitPct','copyLifetimeLossLimitUsd',
    'crypto15mAssets','crypto15mInterval','crypto15mDailyLossLimit',
    'crypto15mLifetimeLossLimitPct','crypto15mLifetimeLossLimitUsd',
    'crypto15mMakerFillSec','crypto15mTakeProfitPct',
    'requireEntryDepth','exitPriceLossBudgetCents'];

  let undef=0;
  for(const k of ADDED){
    // crypto15mAssets is legitimately null (meaning "all assets").
    const missing = cfg[k]===undefined;
    if(missing) undef++;
    console.log(`  ${k.padEnd(32)} = ${JSON.stringify(cfg[k])}${missing?'   <-- UNDEFINED':''}`);
  }

  const total=Object.keys(cfg).length;
  const anyUndef=Object.entries(cfg).filter(([,v])=>v===undefined).map(([k])=>k);
  console.log(`\n${total} keys exposed to the renderer.`);
  if(undef){ console.log(`${undef} of the added keys still read undefined.`); process.exit(1); }
  if(anyUndef.length){ console.log(`Other undefined keys: ${anyUndef.join(', ')}`); process.exit(1); }
  console.log('PASS: every renderer config key has a defined default.');
} finally { await app.close(); }
