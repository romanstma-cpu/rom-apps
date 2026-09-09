import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
const sandbox=fs.mkdtempSync(path.join(os.tmpdir(),'rom-clarity-'));
for(const d of ['Roaming','Local','profile'])fs.mkdirSync(path.join(sandbox,d));
const app=await electron.launch({executablePath:path.resolve('node_modules/electron/dist/electron.exe'),args:[process.cwd(),`--user-data-dir=${path.join(sandbox,'profile')}`],env:{...process.env,APPDATA:path.join(sandbox,'Roaming'),LOCALAPPDATA:path.join(sandbox,'Local')},timeout:30000});
try{
 const p=await app.firstWindow();const errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.getByRole('button',{name:'Continue to API setup'}).click();
 await p.getByRole('navigation').getByRole('button',{name:'Strategy',exact:true}).click();
 await p.getByRole('heading',{name:'Your starting setup'}).waitFor();
 assert.equal(await p.getByRole('button',{name:'Start live',exact:true}).isDisabled(),true);
 await p.getByText('Advanced strategy settings',{exact:false}).click();
 assert.equal(await p.getByText('Auto-trading enabled',{exact:true}).count(),0);
 await p.getByLabel('Maximum per position ($)',{exact:false}).fill('23');
 await p.getByText('Needed: Risk limits saved',{exact:true}).waitFor();
 await p.getByRole('button',{name:'Discard changes'}).click();
 await p.getByText('Ready: Risk limits saved',{exact:true}).waitFor();
 await app.evaluate(({ipcMain})=>{ipcMain.removeHandler('trading:status');ipcMain.handle('trading:status',()=>({main:[],mainMode:'paper',mainState:'scanning',mainSummary:'Fixture scanning',mainLastCycleAt:Date.now()/1000,mainFilterCounts:{},mainCandidates:0,mainPlaced:0,mainPaper:{bankrollUsd:1000,availableUsd:1000,pnlUsd:0,open:0,resolved:0}}));});
 await p.getByRole('navigation').getByRole('button',{name:'Overview',exact:true}).click();
 await p.getByRole('heading',{name:'Main strategy: scanning.'}).waitFor({timeout:15000});
 await app.evaluate(({ipcMain})=>{ipcMain.removeHandler('trading:status');ipcMain.handle('trading:status',()=>{throw Error('Fixture unavailable');});});
 await p.getByRole('heading',{name:'Main strategy: activity unavailable.'}).waitFor({timeout:15000});
 assert.equal(await p.getByText('Fixture scanning',{exact:true}).count(),0);
 await p.evaluate(()=>window.rom.backend.stop());
 await p.getByRole('heading',{name:'Main strategy: engine offline.'}).waitFor({timeout:15000});
 assert.deepEqual(errors,[]);
 console.log('PASS: shared scanning status, failed-refresh invalidation, offline precedence, setup, draft gating and no duplicate start switches');
}finally{await app.close();}
