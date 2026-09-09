import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
const root=fs.mkdtempSync(path.join(os.tmpdir(),'rom-public-'));
for(const d of ['Roaming','Local'])fs.mkdirSync(path.join(root,d));
const app=await electron.launch({executablePath:path.resolve('node_modules/electron/dist/electron.exe'),args:[process.cwd(),`--user-data-dir=${root}/profile`],env:{...process.env,APPDATA:path.join(root,'Roaming'),LOCALAPPDATA:path.join(root,'Local')}});
try{
 const p=await app.firstWindow();const errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.getByRole('button',{name:'Continue to API setup'}).click();
 await p.getByRole('navigation').getByRole('button',{name:'Overview',exact:true}).click();
 await p.waitForTimeout(5500);
 await p.screenshot({path:'.work/overview-2.7.png'});
 await p.getByRole('navigation').getByRole('button',{name:'Strategy',exact:true}).click();
 await app.evaluate(({BrowserWindow})=>{BrowserWindow.getAllWindows()[0].webContents.send('backend:info',{status:'running',authOk:true,pid:1,pythonOk:true,startedAt:null,lastError:null});});
 await p.getByRole('button',{name:'Start live',exact:true}).click();
 await p.getByRole('dialog',{name:'Review before going live'}).waitFor();
 assert.equal(await p.getByRole('button',{name:'Close live review'}).evaluate(e=>e===document.activeElement),true);
 await p.screenshot({path:'.work/live-review-2.7.png'});
 await app.evaluate(({BrowserWindow})=>{BrowserWindow.getAllWindows()[0].webContents.send('backend:info',{status:'stopped',authOk:false,pid:null,pythonOk:false,startedAt:null,lastError:null});});
 assert.equal(await p.getByRole('button',{name:'Enable live trading'}).isDisabled(),true);
 await p.keyboard.press('Escape');
 assert.equal(await p.getByRole('dialog').count(),0);
 assert.equal((await p.evaluate(()=>window.rom.config.get())).enableTrading,false);
 assert.deepEqual(errors,[]);
 console.log('PASS: review focus, connection-loss guard, Escape, no trading enabled, clean renderer');
}finally{await app.close();}
