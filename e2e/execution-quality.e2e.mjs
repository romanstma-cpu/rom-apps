import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root=fs.mkdtempSync(path.join(os.tmpdir(),'rom-execution-quality-'));
for(const dir of ['Roaming','Local'])fs.mkdirSync(path.join(root,dir));
const app=await electron.launch({
  executablePath:path.resolve('node_modules/electron/dist/electron.exe'),
  args:[process.cwd(),`--user-data-dir=${root}/profile`],
  env:{...process.env,APPDATA:path.join(root,'Roaming'),LOCALAPPDATA:path.join(root,'Local')},
});
const empty={windowDays:30,attempts:0,completed:0,pending:0,rejected:0,unfilled:0,
  fillRatePct:null,responseP95Ms:null,costSamples:0,signalSlippageCents:null,
  feeCentsPerContract:null,routes:[]};
async function mock(value,fail=false,delay=0) {
  await app.evaluate(({ipcMain},{value,fail,delay})=>{
    ipcMain.removeHandler('trading:executionQuality');
    ipcMain.handle('trading:executionQuality',async()=>{
      await new Promise(resolve=>setTimeout(resolve,delay));
      if(fail)throw new Error('Execution evidence is unavailable. Start the engine, then refresh evidence.');
      return value;
    });
  },{value,fail,delay});
}
try {
  const page=await app.firstWindow();
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await mock(empty);
  await page.getByRole('button',{name:'Continue to API setup'}).click();
  await page.getByRole('button',{name:'Advanced tools'}).click();
  await page.getByRole('navigation').getByRole('button',{name:'Evidence',exact:true}).click();
  await page.getByText('No recorded live entries yet.',{exact:false}).waitFor();
  const card=page.locator('div').filter({has:page.getByRole('heading',{name:'Execution quality',exact:true})}).last();
  await mock({...empty,attempts:24,completed:20,unfilled:3,pending:3,rejected:1,
    fillRatePct:72.5,responseP95Ms:210,costSamples:17,signalSlippageCents:1.2,feeCentsPerContract:1.5,
    routes:[{...empty,style:'crossing',attempts:24,fillRatePct:72.5}]},false,800);
  await page.getByRole('button',{name:'Refresh evidence'}).click();
  await page.getByText('Checking confirmed order evidence…',{exact:true}).waitFor();
  await page.getByText('72.5%',{exact:true}).waitFor();
  await page.getByText('210 ms',{exact:true}).waitFor();
  const details=page.getByText('How execution feedback works',{exact:true});
  await details.focus();await page.keyboard.press('Enter');
  await page.getByText('Crossing: 24 attempts',{exact:false}).waitFor();
  await page.setViewportSize({width:420,height:900});
  await details.scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:'.work/execution-quality-narrow.png'});
  await mock(empty,true);
  await page.getByRole('button',{name:'Refresh evidence'}).click();
  await page.getByText('Execution evidence is unavailable.',{exact:false}).waitFor();
  assert.equal(await page.getByText('72.5%',{exact:true}).count(),0);
  await mock(empty);
  await page.getByRole('button',{name:'Refresh evidence'}).click();
  await page.getByText('No recorded live entries yet.',{exact:false}).waitFor();
  assert.equal((await page.evaluate(()=>window.rom.config.get())).enableTrading,false);
  assert.deepEqual(errors,[]);
  console.log('PASS execution quality: empty, loading, populated, error/retry, stale clearing, keyboard, narrow layout; no orders');
} finally {await app.close();}
