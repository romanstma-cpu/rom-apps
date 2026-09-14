import {_electron as electron} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root=fs.mkdtempSync(path.join(os.tmpdir(),'rom-api-preflight-'));
for(const d of ['Roaming','Local','profile'])fs.mkdirSync(path.join(root,d));
const app=await electron.launch({executablePath:path.resolve('node_modules/electron/dist/electron.exe'),args:[process.cwd(),`--user-data-dir=${path.join(root,'profile')}`],env:{...process.env,APPDATA:path.join(root,'Roaming'),LOCALAPPDATA:path.join(root,'Local')},timeout:30000});
try {
  const page=await app.firstWindow();
  const errors=[];page.on('pageerror',(error)=>errors.push(error.message));
  await page.getByRole('button',{name:'Continue to API setup'}).click();
  await app.evaluate(({ipcMain})=>{
    ipcMain.removeHandler('credentials:test');
    ipcMain.handle('credentials:test',()=>({ok:true,data:{env:'mainnet',balanceUsd:125.5,ready:true,issues:[]}}));
  });
  await page.getByRole('navigation').getByRole('button',{name:'API',exact:true}).click();
  await page.getByRole('button',{name:'Test saved credentials',exact:true}).click();
  await page.getByRole('heading',{name:'Connection preflight',exact:true}).waitFor();
  await page.getByText('$125.50',{exact:true}).waitFor();
  await page.getByText('No order was sent.',{exact:false}).waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS: read-only API preflight reports buying power and execution status');
} finally { await app.close(); }
