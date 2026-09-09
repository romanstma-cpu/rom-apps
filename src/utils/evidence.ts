import type { BotPosition } from '@shared/types';

/** Descriptive results from the loaded main-strategy ledger, not a forward forecast. */
export function summarizeEvidence(positions: BotPosition[]) {
  const main=positions.filter(p=>['whale','momentum','convergence'].includes(p.signalSource));
  const eligible=main.filter(p=>p.resolved&&p.status!=='dry_run'&&p.filledContracts>0&&typeof p.pnlUsd==='number'&&Number.isFinite(p.pnlUsd)&&!!p.resolvedAt&&Number.isFinite(Date.parse(p.resolvedAt)));
  const rows=[...eligible].sort((a,b)=>Date.parse(a.resolvedAt!)-Date.parse(b.resolvedAt!)||a.id-b.id);
  let equity=0,peak=0,maxDrawdown=0,wins=0,losses=0,profit=0,loss=0;
  const events=new Set<string>();
  for(const row of rows){const pnl=row.pnlUsd!;equity+=pnl;peak=Math.max(peak,equity);maxDrawdown=Math.max(maxDrawdown,peak-equity);if(pnl>0){wins++;profit+=pnl;}if(pnl<0){losses++;loss-=pnl;}events.add(row.eventTicker||row.ticker);}
  return {rows,count:rows.length,pnl:equity,wins,losses,breakEven:rows.length-wins-losses,eventCount:events.size,maxDrawdown,profitFactor:loss>0?profit/loss:null,average:rows.length?equity/rows.length:null,pending:main.filter(p=>!p.resolved&&p.status!=='dry_run'&&p.filledContracts>0).length,excluded:main.length-rows.length};
}
