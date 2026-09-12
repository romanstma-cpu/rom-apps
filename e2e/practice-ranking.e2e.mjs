import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root=fs.mkdtempSync(path.join(os.tmpdir(),'rom-practice-ranking-'));
for(const dir of ['Roaming','Local'])fs.mkdirSync(path.join(root,dir));
const app=await electron.launch({
  executablePath:process.env.ROM_E2E_EXE || path.resolve('node_modules/electron/dist/electron.exe'),
  args:[...(process.env.ROM_E2E_EXE ? [] : [process.cwd()]),`--user-data-dir=${root}/profile`],
  env:{...process.env,APPDATA:path.join(root,'Roaming'),LOCALAPPDATA:path.join(root,'Local')},
});

try {
  const page=await app.firstWindow();
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await app.evaluate(({ipcMain})=>{
    ipcMain.removeHandler('trading:calibration');
    ipcMain.handle('trading:calibration',()=>({
      status:'collecting',reason:'Calibration is still collecting.',eventSamples:0,
      trainEvents:0,testEvents:0,qualifiedBuckets:0,asOf:Date.now()/1000,
    }));
    ipcMain.removeHandler('trading:practicePerformance');
    ipcMain.handle('trading:practicePerformance',()=>({
      status:'qualified',
      reason:'1 practice strategy has enough evidence for a risk-adjusted comparison.',
      asOf:Date.now()/1000,resolvedSamples:38,qualifiedStrategies:1,
      leadingKey:'main:whale',
      thresholds:{resolved:30,distinctMarkets:20,spanDays:7},
      method:'Score balances return on recorded capital at risk and realized drawdown.',
      candidates:[
        {key:'main:whale',name:'Main · Whale',kind:'main',rank:1,status:'qualified',
          reason:'Enough recorded practice evidence for comparison.',resolved:30,open:2,
          wins:20,losses:10,breakEven:0,distinctMarkets:25,spanDays:10,pnlUsd:18.5,
          riskedUsd:300,returnOnRiskPct:6.17,averagePnlUsd:.6167,maxDrawdownUsd:5,
          profitFactor:2.4,score:2.25},
        {key:'script:new',name:'Election Value Scout',kind:'script',rank:null,status:'collecting',
          reason:'Needs 22 more settled fills, 12 more distinct markets, 5.0 more observation days.',
          resolved:8,open:1,wins:5,losses:3,breakEven:0,distinctMarkets:8,spanDays:2,
          pnlUsd:2.1,riskedUsd:80,returnOnRiskPct:2.63,averagePnlUsd:.2625,
          maxDrawdownUsd:2.2,profitFactor:1.5,score:null},
      ],
    }));
  });
  await page.getByRole('button',{name:'Continue to API setup'}).click();
  await page.getByRole('button',{name:'Advanced tools'}).click();
  await page.getByRole('navigation').getByRole('button',{name:'Evidence',exact:true}).click();
  await page.getByRole('heading',{name:'Practice strategy ranking'}).waitFor();
  await page.getByText('Main · Whale',{exact:true}).waitFor();
  assert.equal(await page.getByText('#1',{exact:true}).count(),1);
  await page.getByText('Election Value Scout',{exact:true}).waitFor();
  await page.getByText('Collecting',{exact:true}).waitFor();
  await page.getByText('Needs 22 more settled fills, 12 more distinct markets, 5.0 more observation days.',{exact:true}).waitFor();
  await page.setViewportSize({width:420,height:900});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
  await page.screenshot({path:'.work/practice-ranking-2.15.png',fullPage:true});
  assert.equal((await page.evaluate(()=>window.rom.config.get())).enableTrading,false);
  assert.deepEqual(errors,[]);
  console.log('PASS: qualified leader, collecting candidate, evidence explanation, mobile-width layout; no trading enabled');
} finally {
  await app.close();
}
