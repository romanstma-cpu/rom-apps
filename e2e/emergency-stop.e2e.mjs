import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root=fs.mkdtempSync(path.join(os.tmpdir(),'rom-emergency-stop-'));
for(const d of ['Roaming','Local'])fs.mkdirSync(path.join(root,d));
const app=await electron.launch({
  executablePath:path.resolve('node_modules/electron/dist/electron.exe'),
  args:[process.cwd(),`--user-data-dir=${root}/profile`],
  env:{...process.env,APPDATA:path.join(root,'Roaming'),LOCALAPPDATA:path.join(root,'Local')},
});
try{
  const page=await app.firstWindow();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.getByRole('button',{name:'Continue to API setup'}).click();

  // No credentials are installed in this isolated profile. The real IPC path
  // must still disarm the local strategy before it reports that cancellation
  // could not reach the exchange.
  await page.evaluate(()=>window.rom.config.update({enableTrading:true}));
  await page.getByRole('button',{name:'Emergency stop',exact:true}).waitFor();
  await page.getByRole('button',{name:'Emergency stop',exact:true}).click();
  await page.getByRole('button',{name:'Emergency stop',exact:true}).waitFor({state:'detached'});
  const result=await page.evaluate(async()=>({
    enabled:(await window.rom.config.get()).enableTrading,
    paper:(await window.rom.config.get()).mainPaperTrading,
  }));
  assert.equal(result.enabled,false);
  assert.equal(result.paper,false);
  assert.deepEqual(errors,[]);
  console.log('PASS: emergency stop disarms main trading without credentials or live orders');
}finally{await app.close();}
