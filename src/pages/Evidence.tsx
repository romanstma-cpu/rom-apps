import { ArrowRight, ClipboardCheck, FlaskConical, Trophy } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { ExecutionQualityReport, PracticePerformanceReport, SignalCalibrationReport } from '@shared/types';
import { Card, Page, StatCard } from '../components/common';
import { useApp } from '../state/AppStateProvider';
import { summarizeEvidence } from '../utils/evidence';
import { fmtPct, fmtUsd } from '../utils/format';
import type { PageId } from '../App';

export function EvidencePage({onNav}:{onNav:(p:PageId)=>void}) {
  const {positions}=useApp();const e=summarizeEvidence(positions);
  const [calibration,setCalibration]=useState<SignalCalibrationReport|null>(null);
  const [practice,setPractice]=useState<PracticePerformanceReport|null>(null);
  const [execution,setExecution]=useState<ExecutionQualityReport|null>(null);
  const [executionError,setExecutionError]=useState('');
  const [error,setError]=useState('');
  const [practiceError,setPracticeError]=useState('');
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(true);
  useEffect(()=>{
    let active=true;
    setLoading(true);setError('');setPracticeError('');setCalibration(null);setPractice(null);
    setExecution(null);setExecutionError('');
    Promise.allSettled([
      window.rom.trading.calibration(),
      window.rom.trading.practicePerformance(),
      window.rom.trading.executionQuality(),
    ]).then(([calibrationResult,practiceResult,executionResult])=>{
      if(!active)return;
      if(calibrationResult.status==='fulfilled')setCalibration(calibrationResult.value);
      else setError(calibrationResult.reason?.message || 'Calibration evidence is unavailable. Try again after reconnecting.');
      if(practiceResult.status==='fulfilled')setPractice(practiceResult.value);
      else setPracticeError(practiceResult.reason?.message || 'Practice performance is unavailable. Try again after reconnecting.');
      if(executionResult.status==='fulfilled')setExecution(executionResult.value);
      else setExecutionError(executionResult.reason?.message || 'Execution evidence is unavailable. Start the engine, then refresh evidence.');
    }).finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[revision]);
  return <Page title="Evidence" subtitle="What your recorded trades show — with the limits of the data kept visible.">
    <div className="mx-auto max-w-6xl space-y-6">
      <Card><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-lg font-semibold">Can the signal scores be trusted?</h3><button className="rom-btn-default" disabled={loading} onClick={()=>setRevision(value=>value+1)}>Refresh evidence</button></div>
        <div className="min-h-28 pt-4" aria-live="polite" aria-busy={loading}>
          {loading && <p className="text-sm text-rom-muted">Checking recorded event outcomes…</p>}
          {error && <p role="alert" className="text-sm text-rom-lossText">{error}</p>}
          {calibration && <><p className="text-sm leading-6 text-rom-muted">{calibration.reason}</p><dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            {[['Settled event samples',calibration.eventSamples],['Training events',calibration.trainEvents],['Later test events',calibration.testEvents],['Qualified score groups',calibration.qualifiedBuckets]].map(([label,value])=><div key={label}><dt className="text-xs text-rom-dim">{label}</dt><dd className="mt-1 font-semibold tabular-nums">{value}</dd></div>)}
          </dl><p className="mt-4 text-xs leading-5 text-rom-dim">One recorded signal per event. Later outcomes test earlier estimates against market prices. Kelly requires a qualified group and a positive margin after fees; other sizing modes still use heuristic scores. Enable main data collection in Backtest to build this record.</p></>}
        </div>
      </Card>
      <PracticeRanking report={practice} loading={loading} error={practiceError}/>
      <ExecutionQuality report={execution} loading={loading} error={executionError}/>
      <Card><div className="flex items-start gap-4"><ClipboardCheck className="mt-1 h-6 w-6 shrink-0 text-rom-purple"/><div><h3 className="text-xl font-semibold">{e.count===0?'Your record starts here.':'A record to review, not a prediction.'}</h3><p className="mt-2 text-sm leading-6 text-rom-muted">{e.count===0?'No completed, filled main-strategy trades are available in the loaded history. Simulated results and unfilled orders are not counted as real performance.':`${e.count} completed trades across ${e.eventCount} distinct market or event identifiers. Correlated trades and changing settings can distort conclusions; a positive total does not demonstrate a repeatable edge.`}</p></div></div></Card>
      <div className="grid gap-4 md:grid-cols-3"><StatCard label="Recorded P&L" value={e.count?fmtUsd(e.pnl,{sign:true}):'—'} hint="Completed main-strategy positions only"/><StatCard label="Average per completed trade" value={e.average===null?'—':fmtUsd(e.average,{sign:true})} hint="Descriptive average, not an expected return"/><StatCard label="Largest realized drawdown" value={e.count?fmtUsd(e.maxDrawdown):'—'} hint="Peak-to-trough cumulative closed-trade P&L"/></div>
      <div className="grid gap-6 lg:grid-cols-2"><Card><h3 className="mb-5 font-semibold">Know your sample</h3><dl className="space-y-4 text-sm">{[['Completed trades',e.count],['Winning / losing / break-even',`${e.wins} / ${e.losses} / ${e.breakEven}`],['Distinct events or markets',e.eventCount],['Open filled positions',e.pending],['Profit factor',e.profitFactor===null?'Not available':e.profitFactor.toFixed(2)]].map(([label,value])=><div key={label} className="flex justify-between gap-4"><dt className="text-rom-muted">{label}</dt><dd className="font-medium">{value}</dd></div>)}</dl><p className="mt-5 border-t border-rom-border pt-4 text-xs leading-5 text-rom-dim">Uses up to 500 positions loaded by the app, not necessarily your entire account history. {e.excluded} main-strategy rows are outside this completed-trade sample. Fees follow the ledger’s recorded P&L; this is not an independent exchange reconciliation. Open-position fluctuations are excluded from drawdown.</p></Card>
      <Card><h3 className="mb-4 font-semibold">Test a strategy with context</h3><p className="text-sm leading-6 text-rom-muted">Use historical simulation to explore your settings. Compare several time periods, keep the parameters fixed when reviewing a later period, and include losing results in your assessment.</p><p className="mt-4 text-xs leading-5 text-rom-dim">The historical simulator uses fee assumptions. It cannot replay missing order-book snapshots or the current live quote checks. Its results must not be presented as live Polymarket US returns.</p><button className="rom-btn-primary mt-6" onClick={()=>onNav('backtest')}>Open historical simulation<ArrowRight className="h-4 w-4"/></button><button className="rom-btn-default mt-3" onClick={()=>onNav('history')}>Review trade history</button></Card></div>
    </div>
  </Page>;
}

function ExecutionQuality({report,loading,error}:{report:ExecutionQualityReport|null;loading:boolean;error:string}) {
  const cents=(value:number|null)=>value===null?'—':`${value.toFixed(2)}¢`;
  return <Card>
    <h3 className="text-lg font-semibold">Execution quality</h3>
    <p className="mt-1 text-sm text-rom-muted">How live main-strategy orders reached the market over the last 30 days.</p>
    <div className="min-h-36 pt-5" aria-live="polite" aria-busy={loading}>
      {loading&&<p className="text-sm text-rom-muted">Checking confirmed order evidence…</p>}
      {error&&<p role="alert" className="text-sm text-rom-lossText">{error}</p>}
      {report&&<>
        {!report.attempts&&<p className="mb-4 text-sm text-rom-muted">No recorded live entries yet. New orders build this record automatically; practice fills are excluded.</p>}
        <dl className="grid grid-cols-2 gap-5 sm:grid-cols-4">
          {[
            ['Quantity filled',report.fillRatePct===null?'—':`${report.fillRatePct.toFixed(1)}%`],
            ['Response time · p95',report.responseP95Ms===null?'—':`${Math.round(report.responseP95Ms)} ms`],
            ['Signal-to-fill change',cents(report.signalSlippageCents)],
            ['Fee per contract',cents(report.feeCentsPerContract)],
          ].map(([label,value])=><div key={label}><dt className="text-xs text-rom-dim">{label}</dt><dd className="mt-2 font-mono text-lg tabular-nums">{value}</dd></div>)}
        </dl>
        <p className="mt-5 border-t border-rom-border pt-4 text-xs leading-5 text-rom-muted">{report.completed} completed · {report.unfilled} ended without a fill · {report.pending} awaiting final evidence · {report.rejected} rejected. Cost figures use {report.costSamples} completed orders with confirmed fills and fees. Positive price change means a more expensive entry.</p>
        <details className="mt-4 rounded-lg border border-rom-border px-4 py-2"><summary className="cursor-pointer text-xs font-medium text-rom-muted">How execution feedback works</summary><div className="space-y-3 pb-2 pt-3 text-xs leading-5 text-rom-dim">
          <p>New live entries include a fee reserve. After 20 completed orders across 10 days in the same market, source, price range and route, observed fees can tighten that reserve. Persistently poor fills can pause entries in that group until the evidence ages out of the 30-day window. Existing positions and exits remain managed.</p>
          <p>Crossing and resting describe the quote at submission, not an exchange-confirmed maker or taker role. Routing stays unchanged. Open or uncertain orders are never counted as failed fills. These observations do not establish future profitability.</p>
          {report.routes.map(route=><p key={route.style}>{route.style==='crossing'?'Crossing':'Resting'}: {route.attempts} attempts · {route.fillRatePct===null?'fill rate unavailable':`${route.fillRatePct.toFixed(1)}% of completed-order quantity filled`}</p>)}
        </div></details>
      </>}
    </div>
  </Card>;
}

function PracticeRanking({report,loading,error}:{report:PracticePerformanceReport|null;loading:boolean;error:string}) {
  return <Card>
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-rom-purple/10 text-rom-purple"><Trophy className="h-5 w-5"/></div><div><h3 className="text-lg font-semibold">Practice strategy ranking</h3><p className="mt-1 text-sm text-rom-muted">Compare recorded practice fills after fees. Small samples stay unranked.</p></div></div>
      <span className="rounded-full border border-rom-border bg-rom-void/40 px-3 py-1.5 text-xs font-medium text-rom-muted">Practice only · no live orders</span>
    </div>
    <div className="min-h-32 pt-5" aria-live="polite" aria-busy={loading}>
      {loading&&<p className="text-sm text-rom-muted">Ranking recorded practice outcomes…</p>}
      {error&&<p role="alert" className="text-sm text-rom-lossText">{error}</p>}
      {report&&<>
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rom-border bg-rom-void/35 p-4"><div><p className="text-sm font-semibold">{report.reason}</p><p className="mt-1 text-xs text-rom-dim">Qualification needs {report.thresholds.resolved} settled fills, {report.thresholds.distinctMarkets} distinct markets, and {report.thresholds.spanDays} observation days.</p></div><div className="flex gap-2"><span className="rounded-lg bg-rom-surface px-3 py-2 text-xs text-rom-muted"><strong className="mr-1 text-rom-text">{report.resolvedSamples}</strong>settled</span><span className="rounded-lg bg-rom-surface px-3 py-2 text-xs text-rom-muted"><strong className="mr-1 text-rom-text">{report.qualifiedStrategies}</strong>ranked</span></div></div>
        <div className="mt-4 space-y-2">{report.candidates.map(candidate=><div key={candidate.key} className={`grid gap-4 rounded-xl border p-4 md:grid-cols-[minmax(180px,1.3fr)_repeat(4,minmax(84px,.55fr))] md:items-center ${candidate.rank===1?'border-rom-win/35 bg-rom-win/5':'border-rom-border bg-rom-panel/50'}`}>
          <div className="flex min-w-0 items-center gap-3"><span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg font-mono text-sm font-bold ${candidate.rank===1?'bg-rom-win/15 text-rom-win':'bg-rom-void text-rom-muted'}`}>{candidate.rank?`#${candidate.rank}`:'—'}</span><div className="min-w-0"><p className="truncate text-sm font-semibold">{candidate.name}</p><div className="mt-1 flex flex-wrap items-center gap-2"><span className={`text-xs font-medium ${candidate.status==='qualified'?'text-rom-win':'text-amber-300'}`}>{candidate.status==='qualified'?'Ranked':'Collecting'}</span><span className="text-xs text-rom-dim">{candidate.kind==='script'?'Custom script':'Main strategy'}</span></div></div></div>
          <Metric label="Settled" value={`${candidate.resolved}`} detail={`${candidate.distinctMarkets} markets · ${candidate.spanDays.toFixed(1)}d`}/>
          <Metric label="Return on risk" value={fmtPct(candidate.returnOnRiskPct)} detail={`${candidate.wins}W / ${candidate.losses}L`}/>
          <Metric label="Net P&L" value={candidate.resolved?fmtUsd(candidate.pnlUsd,{sign:true}):'—'} detail={`Avg ${candidate.averagePnlUsd===null?'—':fmtUsd(candidate.averagePnlUsd,{sign:true})}`}/>
          <Metric label="Drawdown" value={candidate.resolved?fmtUsd(candidate.maxDrawdownUsd):'—'} detail={candidate.score===null?'Not scored':`Score ${candidate.score.toFixed(2)}`}/>
          {candidate.status==='collecting'&&<p className="text-xs leading-5 text-rom-dim md:col-span-5">{candidate.reason}</p>}
        </div>)}</div>
        <details className="mt-4 rounded-lg border border-rom-border bg-rom-void/30 px-4 py-2"><summary className="cursor-pointer text-xs font-medium text-rom-muted">How ranking works</summary><div className="flex gap-2 pb-2 pt-3 text-xs leading-5 text-rom-dim"><FlaskConical className="mt-0.5 h-4 w-4 shrink-0"/><p>{report.method} Practice fills approximate execution at the selected price; they do not prove that a live order would fill.</p></div></details>
      </>}
    </div>
  </Card>;
}

function Metric({label,value,detail}:{label:string;value:string;detail:string}) {
  return <div><p className="text-xs text-rom-dim">{label}</p><p className="mt-1 text-sm font-semibold tabular-nums">{value}</p><p className="mt-1 text-xs text-rom-dim">{detail}</p></div>;
}
