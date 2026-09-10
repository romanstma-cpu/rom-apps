import { ArrowRight, ClipboardCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { SignalCalibrationReport } from '@shared/types';
import { Card, Page, StatCard } from '../components/common';
import { useApp } from '../state/AppStateProvider';
import { summarizeEvidence } from '../utils/evidence';
import { fmtUsd } from '../utils/format';
import type { PageId } from '../App';

export function EvidencePage({onNav}:{onNav:(p:PageId)=>void}) {
  const {positions}=useApp();const e=summarizeEvidence(positions);
  const [calibration,setCalibration]=useState<SignalCalibrationReport|null>(null);
  const [error,setError]=useState('');
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(true);
  useEffect(()=>{
    let active=true;
    setLoading(true);setError('');setCalibration(null);
    window.rom.trading.calibration().then(value=>{if(active)setCalibration(value);})
      .catch(err=>{if(active)setError(err?.message || 'Calibration evidence is unavailable. Try again after reconnecting.');})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[revision]);
  return <Page title="Evidence" subtitle="What your recorded trades show — with the limits of the data kept visible.">
    <div className="mx-auto max-w-6xl space-y-6">
      <Card><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-lg font-semibold">Can the signal scores be trusted?</h3><button className="rom-btn-default" disabled={loading} onClick={()=>setRevision(value=>value+1)}>Refresh evidence</button></div>
        <div className="min-h-28 pt-4" aria-live="polite" aria-busy={loading}>
          {loading && <p className="text-sm text-rom-muted">Checking recorded event outcomes…</p>}
          {error && <p role="alert" className="text-sm text-rom-loss">{error}</p>}
          {calibration && <><p className="text-sm leading-6 text-rom-muted">{calibration.reason}</p><dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            {[['Settled event samples',calibration.eventSamples],['Training events',calibration.trainEvents],['Later test events',calibration.testEvents],['Qualified score groups',calibration.qualifiedBuckets]].map(([label,value])=><div key={label}><dt className="text-xs text-rom-dim">{label}</dt><dd className="mt-1 font-semibold tabular-nums">{value}</dd></div>)}
          </dl><p className="mt-4 text-xs leading-5 text-rom-dim">One recorded signal per event. Later outcomes test earlier estimates against market prices. Kelly requires a qualified group and a positive margin after fees; other sizing modes still use heuristic scores. Enable main data collection in Backtest to build this record.</p></>}
        </div>
      </Card>
      <Card><div className="flex items-start gap-4"><ClipboardCheck className="mt-1 h-6 w-6 shrink-0 text-rom-purple"/><div><h3 className="text-xl font-semibold">{e.count===0?'Your record starts here.':'A record to review, not a prediction.'}</h3><p className="mt-2 text-sm leading-6 text-rom-muted">{e.count===0?'No completed, filled main-strategy trades are available in the loaded history. Simulated results and unfilled orders are not counted as real performance.':`${e.count} completed trades across ${e.eventCount} distinct market or event identifiers. Correlated trades and changing settings can distort conclusions; a positive total does not demonstrate a repeatable edge.`}</p></div></div></Card>
      <div className="grid gap-4 md:grid-cols-3"><StatCard label="Recorded P&L" value={e.count?fmtUsd(e.pnl,{sign:true}):'—'} hint="Completed main-strategy positions only"/><StatCard label="Average per completed trade" value={e.average===null?'—':fmtUsd(e.average,{sign:true})} hint="Descriptive average, not an expected return"/><StatCard label="Largest realized drawdown" value={e.count?fmtUsd(e.maxDrawdown):'—'} hint="Peak-to-trough cumulative closed-trade P&L"/></div>
      <div className="grid gap-6 lg:grid-cols-2"><Card><h3 className="mb-5 font-semibold">Know your sample</h3><dl className="space-y-4 text-sm">{[['Completed trades',e.count],['Winning / losing / break-even',`${e.wins} / ${e.losses} / ${e.breakEven}`],['Distinct events or markets',e.eventCount],['Open filled positions',e.pending],['Profit factor',e.profitFactor===null?'Not available':e.profitFactor.toFixed(2)]].map(([label,value])=><div key={label} className="flex justify-between gap-4"><dt className="text-rom-muted">{label}</dt><dd className="font-medium">{value}</dd></div>)}</dl><p className="mt-5 border-t border-rom-border pt-4 text-xs leading-5 text-rom-dim">Uses up to 500 positions loaded by the app, not necessarily your entire account history. {e.excluded} main-strategy rows are outside this completed-trade sample. Fees follow the ledger’s recorded P&L; this is not an independent exchange reconciliation. Open-position fluctuations are excluded from drawdown.</p></Card>
      <Card><h3 className="mb-4 font-semibold">Test a strategy with context</h3><p className="text-sm leading-6 text-rom-muted">Use historical simulation to explore your settings. Compare several time periods, keep the parameters fixed when reviewing a later period, and include losing results in your assessment.</p><p className="mt-4 text-xs leading-5 text-rom-dim">The historical simulator uses fee assumptions. It cannot replay missing order-book snapshots or the current live quote checks. Its results must not be presented as live Polymarket US returns.</p><button className="rom-btn-primary mt-6" onClick={()=>onNav('backtest')}>Open historical simulation<ArrowRight className="h-4 w-4"/></button><button className="rom-btn-default mt-3" onClick={()=>onNav('history')}>Review trade history</button></Card></div>
    </div>
  </Page>;
}
