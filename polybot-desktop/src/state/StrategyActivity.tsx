import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import type { TradingStatus } from '@shared/types';
import { useApp } from './AppStateProvider';

const Context = createContext<{status: TradingStatus | null; label: string; summary: string; healthy: boolean}>({status:null,label:'Checking activity',summary:'Waiting for the engine status.',healthy:false});
export const useStrategyActivity = () => useContext(Context);

export function StrategyActivityProvider({children}: {children: ReactNode}) {
  const {backend, config} = useApp();
  const [status,setStatus] = useState<TradingStatus|null>(null);
  const [received,setReceived] = useState(0);
  const [failed,setFailed] = useState(false);
  const [now,setNow] = useState(Date.now());
  useEffect(()=>{
    let alive=true; let pending=false;
    setStatus(null);setReceived(0);setFailed(false);
    const pull=async()=>{
      if(pending||backend.status!=='running')return;
      pending=true;
      let timeout: ReturnType<typeof setTimeout> | undefined;
      try{const next=await Promise.race([window.rom.trading.status(),new Promise<never>((_,reject)=>{timeout=setTimeout(()=>reject(new Error('Activity timeout')),8000);})]);if(alive){setStatus(next);setReceived(Date.now());setFailed(false);}}
      catch{if(alive)setFailed(true);}
      finally{clearTimeout(timeout);pending=false;}
    };
    void pull();const timer=window.setInterval(()=>{setNow(Date.now());void pull();},5000);
    return()=>{alive=false;window.clearInterval(timer);};
  },[backend.status,config?.enableTrading,config?.mainPaperTrading]);
  const offline=backend.status!=='running';
  const unavailable=failed||(received>0&&now-received>15000);
  const cycleOld=!!status?.mainLastCycleAt && now-status.mainLastCycleAt*1000>Math.max(60000,(config?.tradeScanInterval||30)*3000);
  const cycleUnconfirmed=status?.mainState==='scanning'&&(!status.mainLastCycleAt||cycleOld);
  const healthy=!offline&&!unavailable&&!!status;
  const label=offline?'Engine offline':unavailable?'Activity unavailable':!status?'Checking activity':cycleUnconfirmed?'Waiting for cycle':status.mainState==='scanning'?'Scanning':status.mainState==='blocked'?'Blocked':status.mainState==='waiting'?'Waiting':'Paused';
  const summary=offline?'The backend is not running. Enabled settings do not mean trading is active.':unavailable?'Could not refresh activity. The last reported state is no longer reliable; check the engine connection.':cycleUnconfirmed?'Strategy enabled, but no recent decision cycle has been confirmed.':status?.mainSummary||'Waiting for a fresh engine status.';
  const visible=healthy&&status ? {...status,mainState:cycleUnconfirmed?'waiting' as const:status.mainState,mainSummary:summary}:null;
  return <Context.Provider value={{status:visible,label,summary,healthy}}>{children}</Context.Provider>;
}
