import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root=fs.mkdtempSync(path.join(os.tmpdir(),'rom-evidence-allocation-'));
for(const dir of ['Roaming','Local'])fs.mkdirSync(path.join(root,dir));
const app=await electron.launch({
  executablePath:path.resolve('node_modules/electron/dist/electron.exe'),
  args:[process.cwd(),`--user-data-dir=${root}/profile`],
  env:{...process.env,APPDATA:path.join(root,'Roaming'),LOCALAPPDATA:path.join(root,'Local')},
});

try {
  const page=await app.firstWindow();const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await app.evaluate(({ipcMain})=>{
    ipcMain.removeHandler('trading:allocationPlan');
    ipcMain.handle('trading:allocationPlan',()=>({
      status:'active',reason:'2 sources receive an evidence adjustment.',asOf:Date.now()/1000,
      enabled:['whale','momentum'],limits:{minimumMultiplier:.25,maximumMultiplier:1.5},
      method:'Uses both 30-day and 90-day independent practice events.',
      candidates:[
        {source:'whale',name:'Whale',status:'qualified',multiplier:1.5,
          conservativeReturnPct:4.2,reason:'Positive in both windows; allocation reflects its share of conservative evidence.',
          shortWindow:{days:30,events:28,spanDays:25,pnlUsd:12,riskedUsd:280,returnPct:4.29,lowerReturnPct:2.1,qualified:true,reason:'Qualified.'},
          longWindow:{days:90,events:55,spanDays:70,pnlUsd:30,riskedUsd:550,returnPct:5.45,lowerReturnPct:4.2,qualified:true,reason:'Qualified.'}},
        {source:'momentum',name:'Momentum',status:'qualified',multiplier:.25,
          conservativeReturnPct:-2.5,reason:'Conservative return is not positive in both windows; live size is reduced to 25%.',
          shortWindow:{days:30,events:25,spanDays:24,pnlUsd:-8,riskedUsd:250,returnPct:-3.2,lowerReturnPct:-5,qualified:true,reason:'Qualified.'},
          longWindow:{days:90,events:50,spanDays:68,pnlUsd:-5,riskedUsd:500,returnPct:-1,lowerReturnPct:-2.5,qualified:true,reason:'Qualified.'}},
      ],
    }));
  });
  await page.getByRole('button',{name:'Continue to API setup'}).click();
  await page.getByRole('navigation').getByRole('button',{name:'Strategy',exact:true}).click();
  await page.getByRole('heading',{name:'Evidence-based allocation'}).waitFor();
  await page.getByText('1.50×',{exact:true}).waitFor();
  await page.getByText('0.25×',{exact:true}).waitFor();
  const toggle=page.getByRole('switch',{name:/Use evidence allocation/});
  assert.equal(await toggle.getAttribute('aria-checked'),'false');
  await toggle.click();
  await page.waitForFunction(async()=> (await window.rom.config.get()).evidenceAllocationEnabled===true);
  assert.equal((await page.evaluate(()=>window.rom.config.get())).enableTrading,false);
  await page.setViewportSize({width:420,height:900});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
  await page.screenshot({path:'.work/evidence-allocation-2.16.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: evidence allocation plan, opt-in persistence, narrow layout; live trading remains disabled');
} finally { await app.close(); }
