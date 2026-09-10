import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';

const sandbox=fs.mkdtempSync(path.join(os.tmpdir(),'rom-paper-activity-'));
for(const d of ['Roaming','Local','profile'])fs.mkdirSync(path.join(sandbox,d));
const app=await electron.launch({
  executablePath:path.resolve('node_modules/electron/dist/electron.exe'),
  args:[process.cwd(),`--user-data-dir=${path.join(sandbox,'profile')}`],
  env:{...process.env,APPDATA:path.join(sandbox,'Roaming'),LOCALAPPDATA:path.join(sandbox,'Local')},
  timeout:30000,
});
try {
  const p=await app.firstWindow();const errors=[];p.on('pageerror',e=>errors.push(e.message));
  await p.getByRole('button',{name:'Continue to API setup'}).click();
  await p.getByRole('navigation').getByRole('button',{name:'Strategy',exact:true}).click();
  const initial=await p.evaluate(()=>window.rom.config.get());
  assert.equal(initial.enableTrading,false);assert.equal(initial.mainPaperTrading,false);
  assert.equal(await p.getByRole('button',{name:'Start practice',exact:true}).isDisabled(),true);

  await p.evaluate(()=>window.rom.trading.setPaperEnabled(true));
  // WorkspaceStatus owns the header state line; practice shows as the
  // engine-count alternative once no live engine is enabled.
  await p.getByText(/Practice selected/).waitFor();
  let cfg=await p.evaluate(()=>window.rom.config.get());
  assert.equal(cfg.mainPaperTrading,true);assert.equal(cfg.enableTrading,false);

  await p.getByRole('navigation').getByRole('button',{name:'Overview',exact:true}).click();
  await p.getByRole('heading',{name:'What Polybot is doing',exact:true}).waitFor();
  await p.waitForFunction(async()=> (await window.rom.trading.status()).mainState==='blocked');
  await p.getByText('blocked',{exact:true}).waitFor();
  // The credential reason is shown in more than one card; assert it appears
  // rather than requiring a single match.
  await p.getByText(/auth failed/i).first().waitFor();
  await p.screenshot({path:'.work/overview-2.4.png'});
  const status=await p.evaluate(()=>window.rom.trading.status());
  assert.equal(status.mainMode,'paper');assert.equal(status.mainState,'blocked');
  assert.equal(status.mainPaper.bankrollUsd,1000);

  await p.evaluate(()=>window.rom.trading.setEnabled(true));
  cfg=await p.evaluate(()=>window.rom.config.get());
  assert.equal(cfg.enableTrading,true);assert.equal(cfg.mainPaperTrading,false);
  await p.evaluate(()=>window.rom.trading.setPaperEnabled(true));
  cfg=await p.evaluate(()=>window.rom.config.get());
  assert.equal(cfg.enableTrading,false);assert.equal(cfg.mainPaperTrading,true);
  await p.evaluate(()=>window.rom.trading.setPaperEnabled(false));
  assert.deepEqual(errors,[]);
  console.log('PASS: practice/live isolation, no-credential guard, activity state and clean renderer');
} finally { await app.close(); }
