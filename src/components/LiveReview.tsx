import { useEffect, useRef } from 'react';
import { ShieldCheck, X } from 'lucide-react';
import type { TraderConfig } from '@shared/types';
import { fmtUsd } from '../utils/format';
export function LiveReview({config,open,busy,canStart,onClose,onConfirm}:{config:TraderConfig;open:boolean;busy:boolean;canStart:boolean;onClose:()=>void;onConfirm:()=>void}) {
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const d=ref.current;if(!d)return;if(open&&!d.open)d.showModal();if(!open&&d.open)d.close();},[open]);
  return <dialog ref={ref} aria-labelledby="live-review-title" className="rom-review" onCancel={e=>{e.preventDefault();if(!busy)onClose();}}>
    <div className="flex items-center justify-between"><ShieldCheck className="h-7 w-7 text-rom-purple"/><button autoFocus className="rom-btn-ghost" aria-label="Close live review" disabled={busy} onClick={onClose}><X className="h-5 w-5"/></button></div>
    <h2 id="live-review-title" className="mt-6 text-2xl font-semibold">Review before going live</h2>
    <p className="mt-3 text-sm leading-6 text-rom-muted">The main strategy can place real Polymarket US orders. Starting live pauses main-strategy practice. Other engines are controlled separately.</p>
    <dl className="my-6 space-y-4 rounded-xl bg-rom-void p-5 text-sm">{[['Maximum per position',fmtUsd(config.hardMaxPositionUsd)],['Portfolio exposure',`${Math.round(config.maxTotalExposureFraction*100)}%`],['Cash reserve',`${Math.round(config.minCashReserveFraction*100)}%`],['Daily loss stop',config.stopLossOnDay?fmtUsd(Math.abs(config.stopLossOnDay)):'Off']].map(([k,v])=><div key={k} className="flex justify-between gap-4"><dt className="text-rom-muted">{k}</dt><dd className="font-semibold tabular-nums">{v}</dd></div>)}</dl>
    <p className="text-xs leading-5 text-rom-muted">Limits guide new entries; they do not guarantee a maximum loss or a profitable strategy.</p>
    {!canStart&&<p role="status" className="mt-3 text-sm text-rom-warn">Connection or setup changed. Close this review and check your starting setup.</p>}
    <div className="mt-6 flex justify-end gap-3"><button disabled={busy} className="rom-btn-default" onClick={onClose}>Keep paused</button><button disabled={busy||!canStart} className="rom-btn-primary" onClick={onConfirm}>{busy?'Enabling…':'Enable live trading'}</button></div>
  </dialog>;
}
