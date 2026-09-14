import { useEffect, useRef, useState } from 'react';
import { ShieldCheck, X } from 'lucide-react';
import type { TraderConfig, TradingStatus } from '@shared/types';
import { fmtUsd } from '../utils/format';
export function LiveReview({config,readiness,open,busy,canStart,onClose,onConfirm}:{config:TraderConfig;readiness?:TradingStatus['practiceReadiness'];open:boolean;busy:boolean;canStart:boolean;onClose:()=>void;onConfirm:()=>void}) {
  const ref=useRef<HTMLDialogElement>(null);
  const [acknowledged,setAcknowledged]=useState(false);
  const [skipPractice,setSkipPractice]=useState(false);
  useEffect(()=>{const d=ref.current;if(!d)return;if(open&&!d.open)d.showModal();if(!open&&d.open)d.close();},[open]);
  useEffect(()=>{if(open){setAcknowledged(false);setSkipPractice(false);}},[open]);
  const hasCompletedPractice=!!readiness?.hasCompletedPractice;
  const needsPracticeAcknowledgement=!hasCompletedPractice;
  return <dialog ref={ref} aria-labelledby="live-review-title" className="rom-review" onCancel={e=>{e.preventDefault();if(!busy)onClose();}}>
    <div className="flex items-center justify-between"><ShieldCheck className="h-7 w-7 text-rom-purple"/><button autoFocus className="rom-btn-ghost" aria-label="Close live review" disabled={busy} onClick={onClose}><X className="h-5 w-5"/></button></div>
    <h2 id="live-review-title" className="mt-6 text-2xl font-semibold">Review before going live</h2>
    <p className="mt-3 text-sm leading-6 text-rom-muted">The main strategy can place real Polymarket US orders. Starting live pauses main-strategy practice. Other engines are controlled separately.</p>
    <dl className="my-6 space-y-4 rounded-xl bg-rom-void p-5 text-sm">{[['Maximum per position',fmtUsd(config.hardMaxPositionUsd)],['Portfolio exposure',`${Math.round(config.maxTotalExposureFraction*100)}%`],['Cash reserve',`${Math.round(config.minCashReserveFraction*100)}%`],['Loss limits',readiness?.lossLimitSummary || (config.stopLossOnDay ? `daily ${fmtUsd(Math.abs(config.stopLossOnDay))}` : 'None saved')],['Completed practice trades',hasCompletedPractice ? `${readiness?.completedPracticeTrades} completed` : 'None yet'],['Evidence allocation',config.evidenceAllocationEnabled?'On':'Off']].map(([k,v])=><div key={k} className="flex justify-between gap-4"><dt className="text-rom-muted">{k}</dt><dd className="font-semibold tabular-nums">{v}</dd></div>)}</dl>
    <p className="text-xs leading-5 text-rom-muted">Limits guide new entries; they do not guarantee a maximum loss or a profitable strategy.</p>
    {needsPracticeAcknowledgement&&<label className="mt-5 flex cursor-pointer items-start gap-3 rounded-xl border border-rom-purple/30 bg-rom-purple/[0.06] p-4 text-sm leading-5 text-rom-muted">
      <input type="checkbox" checked={skipPractice} onChange={(event)=>setSkipPractice(event.target.checked)} className="mt-0.5 h-4 w-4 accent-violet-400" />
      <span>I am choosing to continue without a completed practice trade. I understand practice uses the same entry checks and sizing but never sends an exchange order.</span>
    </label>}
    <label className="mt-5 flex cursor-pointer items-start gap-3 rounded-xl border border-rom-warn/30 bg-rom-warn/[0.06] p-4 text-sm leading-5 text-rom-muted">
      <input
        type="checkbox"
        checked={acknowledged}
        onChange={(event)=>setAcknowledged(event.target.checked)}
        className="mt-0.5 h-4 w-4 accent-amber-400"
      />
      <span>I understand this can place real orders and lose money. I reviewed these limits and know the Emergency stop pauses this main strategy and requests cancellation of its pending orders.</span>
    </label>
    {!canStart&&<p role="status" className="mt-3 text-sm text-rom-warn">Connection or setup changed. Close this review and check your starting setup.</p>}
    <div className="mt-6 flex justify-end gap-3"><button disabled={busy} className="rom-btn-default" onClick={onClose}>Keep paused</button><button disabled={busy||!canStart||!acknowledged||(needsPracticeAcknowledgement&&!skipPractice)} className="rom-btn-primary" onClick={onConfirm}>{busy?'Enabling…':'Enable live trading'}</button></div>
  </dialog>;
}
