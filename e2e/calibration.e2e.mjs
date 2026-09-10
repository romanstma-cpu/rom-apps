import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const root=fs.mkdtempSync(path.join(os.tmpdir(),'rom-calibration-'));
for(const dir of ['Roaming','Local'])fs.mkdirSync(path.join(root,dir));
const app=await electron.launch({executablePath:process.env.ROM_E2E_EXE || path.resolve('node_modules/electron/dist/electron.exe'),args:[...(process.env.ROM_E2E_EXE ? [] : [process.cwd()]),`--user-data-dir=${root}/profile`],env:{...process.env,APPDATA:path.join(root,'Roaming'),LOCALAPPDATA:path.join(root,'Local')}});
try {
  const page=await app.firstWindow();const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.getByRole('button',{name:'Continue to API setup'}).click();
  await page.getByRole('button',{name:'Save and connect',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'Enter both your Key ID and Secret Key.'}).waitFor();
  assert.equal(await page.getByLabel('Key ID',{exact:true}).evaluate(e=>e===document.activeElement),true);
  await page.waitForFunction(async()=> (await window.rom.backend.info()).status==='running');
  const actual=await page.evaluate(()=>window.rom.trading.calibration());
  assert.equal(actual.status,'collecting');assert.equal(actual.eventSamples,0);
  await page.getByRole('button',{name:'Advanced tools'}).click();
  await page.getByRole('navigation').getByRole('button',{name:'Evidence',exact:true}).click();
  await page.getByText(actual.reason,{exact:true}).waitFor();
  await page.screenshot({path:'.work/calibration-empty-2.10.png'});
  await app.evaluate(({ipcMain})=>{
    ipcMain.removeHandler('trading:calibration');
    ipcMain.handle('trading:calibration',()=>{throw new Error('Calibration test connection failure');});
  });
  await page.getByRole('button',{name:'Refresh evidence',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'Calibration test connection failure'}).waitFor();
  assert.equal(await page.getByText('Settled event samples',{exact:true}).count(),0);
  await app.evaluate(({ipcMain})=>{
    ipcMain.removeHandler('trading:calibration');
    ipcMain.handle('trading:calibration',async()=>{
      await new Promise(resolve=>setTimeout(resolve,400));
      return {status:'qualified',reason:'Synthetic qualified group; not proof of profitable execution.',eventSamples:400,trainEvents:268,testEvents:120,qualifiedBuckets:1,asOf:Date.now()/1000};
    });
  });
  const refresh=page.getByRole('button',{name:'Refresh evidence',exact:true});
  await refresh.focus();await page.keyboard.press('Enter');
  await page.getByText('Checking recorded event outcomes…',{exact:true}).waitFor();
  assert.equal(await refresh.isDisabled(),true);
  await page.getByText('Synthetic qualified group; not proof of profitable execution.',{exact:true}).waitFor();
  await page.setViewportSize({width:1000,height:800});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
  await page.screenshot({path:'.work/calibration-qualified-2.10.png'});
  assert.equal((await page.evaluate(()=>window.rom.config.get())).enableTrading,false);
  assert.deepEqual(errors,[]);
  console.log('PASS: real calibration RPC, collecting, failure, retry, loading, keyboard, qualified evidence, narrow layout; no trading enabled');
}finally{await app.close();}
