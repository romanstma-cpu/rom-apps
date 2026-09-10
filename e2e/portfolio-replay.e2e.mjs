import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const root=fs.mkdtempSync(path.join(os.tmpdir(),'rom-replay-'));
for(const dir of ['Roaming','Local'])fs.mkdirSync(path.join(root,dir));
const app=await electron.launch({executablePath:process.env.ROM_E2E_EXE || path.resolve('node_modules/electron/dist/electron.exe'),args:[...(process.env.ROM_E2E_EXE ? [] : [process.cwd()]),`--user-data-dir=${root}/profile`],env:{...process.env,APPDATA:path.join(root,'Roaming'),LOCALAPPDATA:path.join(root,'Local')}});
try {
  const page=await app.firstWindow(); const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.getByRole('button',{name:'Continue to API setup'}).click();
  await page.waitForFunction(async () => (await window.rom.backend.info()).status === 'running');
  const actual=await page.evaluate(()=>window.rom.crypto15m.backtestMain({sinceDays:7,config:{replayScenario:'stress'}}));
  assert.equal(actual.dataStatus,'insufficient_data');
  assert.equal(actual.assumptions.latencyMs,2000);
  await app.evaluate(({ipcMain})=>{
    ipcMain.removeHandler('main:backtest');
    ipcMain.handle('main:backtest',(_e,args)=>{
      if(args.config.replayScenario==='base')return {windowsScanned:1,dataStatus:'insufficient_data',caveats:['Not enough recorded order-book evidence.']};
      return {mode:'portfolio',dataStatus:'recorded',n:0,wins:0,winRate:0,netEvCentsPerContract:0,totalPnlUsd:-.39,maxDrawdownUsd:-.39,contracts:0,windowsScanned:1,byAsset:{},equity:[{at:'2026-08-01T00:00:00Z',value:0},{at:'2026-08-01T00:00:01Z',value:-.39}],byHourUtc:[],byDay:[],trades:[],caveats:['Synthetic UI fixture.'],cashUsd:93.86,reservedUsd:0,feesUsd:.14,openPositions:1,independentEvents:0};
    });
  });
  await page.getByRole('button',{name:'Advanced tools'}).click();
  await page.getByRole('navigation').getByRole('button',{name:'Backtest',exact:true}).click();
  await page.getByRole('button',{name:'Run backtest',exact:true}).click();
  await page.getByText('Not enough recorded order-book evidence.',{exact:true}).waitFor();
  assert.equal(await page.getByText('Total P&L',{exact:true}).count(),0);
  await page.getByLabel('Execution scenario').selectOption('delayed');
  assert.equal(await page.getByText('No collected data yet',{exact:true}).count(),0);
  await page.getByRole('button',{name:'Run backtest',exact:true}).click();
  await page.getByText('Reserved for orders',{exact:true}).waitFor();
  await page.screenshot({path:'.work/portfolio-replay-2.9.png',fullPage:true});
  await page.getByLabel('Execution scenario').selectOption('stress');
  assert.equal(await page.getByText('Reserved for orders',{exact:true}).count(),0);
  assert.equal((await page.evaluate(()=>window.rom.config.get())).enableTrading,false);
  assert.deepEqual(errors,[]);
  console.log('PASS: insufficient evidence, portfolio metrics, scenario invalidation, clean renderer; no live trading');
} finally {await app.close();}
