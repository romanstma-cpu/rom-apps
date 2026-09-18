import { Activity, ArrowRight, BrainCircuit, ClipboardCheck, FlaskConical, ShieldCheck, Trophy } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { CandidateFunnelReport, ExecutionQualityReport, ExecutionShadowReport, ForwardValidationReport, MlPromotionReport, PracticePerformanceReport, ShadowRankerReport, SignalCalibrationReport } from '@shared/types';
import { Card, Page, StatCard } from '../components/common';
import { useApp } from '../state/AppStateProvider';
import { summarizeEvidence } from '../utils/evidence';
import { fmtPct, fmtUsd } from '../utils/format';
import type { PageId } from '../App';

export function EvidencePage({onNav}:{onNav:(p:PageId)=>void}) {
  const {positions}=useApp();const e=summarizeEvidence(positions);
  const [calibration,setCalibration]=useState<SignalCalibrationReport|null>(null);
  const [funnel,setFunnel]=useState<CandidateFunnelReport|null>(null);
  const [shadow,setShadow]=useState<ShadowRankerReport|null>(null);
  const [executionShadow,setExecutionShadow]=useState<ExecutionShadowReport|null>(null);
  const [forward,setForward]=useState<ForwardValidationReport|null>(null);
  const [promotion,setPromotion]=useState<MlPromotionReport|null>(null);
  const [practice,setPractice]=useState<PracticePerformanceReport|null>(null);
  const [execution,setExecution]=useState<ExecutionQualityReport|null>(null);
  const [executionError,setExecutionError]=useState('');
  const [error,setError]=useState('');
  const [funnelError,setFunnelError]=useState('');
  const [shadowError,setShadowError]=useState('');
  const [executionShadowError,setExecutionShadowError]=useState('');
  const [forwardError,setForwardError]=useState('');
  const [promotionError,setPromotionError]=useState('');
  const [practiceError,setPracticeError]=useState('');
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(true);
  useEffect(()=>{
    let active=true;
    setLoading(true);setError('');setFunnelError('');setShadowError('');setExecutionShadowError('');setForwardError('');setPromotionError('');setPracticeError('');setCalibration(null);setFunnel(null);setShadow(null);setExecutionShadow(null);setForward(null);setPromotion(null);setPractice(null);
    setExecution(null);setExecutionError('');
    Promise.allSettled([
      window.rom.trading.calibration(),
      window.rom.trading.candidateFunnel(),
      window.rom.trading.shadowRanker(),
      window.rom.trading.executionShadow(),
      window.rom.trading.forwardValidation(),
      window.rom.trading.mlPromotion(),
      window.rom.trading.practicePerformance(),
      window.rom.trading.executionQuality(),
    ]).then(([calibrationResult,funnelResult,shadowResult,executionShadowResult,forwardResult,promotionResult,practiceResult,executionResult])=>{
      if(!active)return;
      if(calibrationResult.status==='fulfilled')setCalibration(calibrationResult.value);
      else setError(calibrationResult.reason?.message || 'Calibration evidence is unavailable. Try again after reconnecting.');
      if(funnelResult.status==='fulfilled')setFunnel(funnelResult.value);
      else setFunnelError(funnelResult.reason?.message || 'The trade funnel is unavailable. Try again after reconnecting.');
      if(shadowResult.status==='fulfilled')setShadow(shadowResult.value);
      else setShadowError(shadowResult.reason?.message || 'The ML shadow report is unavailable. Try again after reconnecting.');
      if(executionShadowResult.status==='fulfilled')setExecutionShadow(executionShadowResult.value);
      else setExecutionShadowError(executionShadowResult.reason?.message || 'The execution shadow report is unavailable. Try again after reconnecting.');
      if(forwardResult.status==='fulfilled')setForward(forwardResult.value);
      else setForwardError(forwardResult.reason?.message || 'The forward-validation scorecard is unavailable. Try again after reconnecting.');
      if(promotionResult.status==='fulfilled')setPromotion(promotionResult.value);
      else setPromotionError(promotionResult.reason?.message || 'The ML promotion gate is unavailable. Try again after reconnecting.');
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
          </dl><p className="mt-4 text-xs leading-5 text-rom-dim">One recorded signal per event. Later outcomes test earlier estimates against market prices. Every live Large Trade and Momentum entry requires a qualified group and a positive margin after fees, regardless of sizing mode. Practice keeps collecting candidates that are not yet qualified. Enable main data collection in Backtest to build this record.</p></>}
        </div>
      </Card>
      <CandidateFunnel report={funnel} loading={loading} error={funnelError}/>
      <ShadowRanker report={shadow} loading={loading} error={shadowError}/>
      <MlPromotion report={promotion} loading={loading} error={promotionError}/>
      <ForwardValidation report={forward} loading={loading} error={forwardError}/>
      <ExecutionShadow report={executionShadow} loading={loading} error={executionShadowError}/>
      <PracticeRanking report={practice} loading={loading} error={practiceError}/>
      <ExecutionQuality report={execution} loading={loading} error={executionError}/>
      <Card><div className="flex items-start gap-4"><ClipboardCheck className="mt-1 h-6 w-6 shrink-0 text-rom-purple"/><div><h3 className="text-xl font-semibold">{e.count===0?'Your record starts here.':'A record to review, not a prediction.'}</h3><p className="mt-2 text-sm leading-6 text-rom-muted">{e.count===0?'No completed, filled main-strategy trades are available in the loaded history. Simulated results and unfilled orders are not counted as real performance.':`${e.count} completed trades across ${e.eventCount} distinct market or event identifiers. Correlated trades and changing settings can distort conclusions; a positive total does not demonstrate a repeatable edge.`}</p></div></div></Card>
      <div className="grid gap-4 md:grid-cols-3"><StatCard label="Recorded P&L" value={e.count?fmtUsd(e.pnl,{sign:true}):'—'} hint="Completed main-strategy positions only"/><StatCard label="Average per completed trade" value={e.average===null?'—':fmtUsd(e.average,{sign:true})} hint="Descriptive average, not an expected return"/><StatCard label="Largest realized drawdown" value={e.count?fmtUsd(e.maxDrawdown):'—'} hint="Peak-to-trough cumulative closed-trade P&L"/></div>
      <div className="grid gap-6 lg:grid-cols-2"><Card><h3 className="mb-5 font-semibold">Know your sample</h3><dl className="space-y-4 text-sm">{[['Completed trades',e.count],['Winning / losing / break-even',`${e.wins} / ${e.losses} / ${e.breakEven}`],['Distinct events or markets',e.eventCount],['Open filled positions',e.pending],['Profit factor',e.profitFactor===null?'Not available':e.profitFactor.toFixed(2)]].map(([label,value])=><div key={label} className="flex justify-between gap-4"><dt className="text-rom-muted">{label}</dt><dd className="font-medium">{value}</dd></div>)}</dl><p className="mt-5 border-t border-rom-border pt-4 text-xs leading-5 text-rom-dim">Uses up to 500 positions loaded by the app, not necessarily your entire account history. {e.excluded} main-strategy rows are outside this completed-trade sample. Fees follow the ledger’s recorded P&L; this is not an independent exchange reconciliation. Open-position fluctuations are excluded from drawdown.</p></Card>
      <Card><h3 className="mb-4 font-semibold">Test a strategy with context</h3><p className="text-sm leading-6 text-rom-muted">Use historical simulation to explore your settings. Compare several time periods, keep the parameters fixed when reviewing a later period, and include losing results in your assessment.</p><p className="mt-4 text-xs leading-5 text-rom-dim">The historical simulator uses fee assumptions. It cannot replay missing order-book snapshots or the current live quote checks. Its results must not be presented as live Polymarket US returns.</p><button className="rom-btn-primary mt-6" onClick={()=>onNav('backtest')}>Open historical simulation<ArrowRight className="h-4 w-4"/></button><button className="rom-btn-default mt-3" onClick={()=>onNav('history')}>Review trade history</button></Card></div>
    </div>
  </Page>;
}

function CandidateFunnel({report,loading,error}:{report:CandidateFunnelReport|null;loading:boolean;error:string}) {
  const total=Math.max(1,report?.observedEvents||0);
  const eligiblePct=report?100*report.eligibleEvents/total:0;
  return <Card>
    <div className="flex flex-wrap items-start justify-between gap-4"><div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-blue-400/10 text-blue-300"><Activity className="h-5 w-5"/></div><div><h3 className="text-lg font-semibold">Why trades are not firing</h3><p className="mt-1 text-sm text-rom-muted">Event-deduplicated candidates from the last {report?.lookbackDays||30} days.</p></div></div><span className="rounded-full border border-rom-border bg-rom-void/40 px-3 py-1.5 text-xs font-medium text-rom-muted">Diagnostic only · no live control</span></div>
    <div className="min-h-28 pt-5" aria-live="polite" aria-busy={loading}>
      {loading&&<p className="text-sm text-rom-muted">Tracing candidates through the entry gates…</p>}
      {error&&<p role="alert" className="text-sm text-rom-lossText">{error}</p>}
      {report&&<><p className="text-sm leading-6 text-rom-muted">{report.reason}</p><dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4"><Metric label="Candidates" value={`${report.observedEvents}`} detail="One per source and event"/><Metric label="Signal-gate eligible" value={`${report.eligibleEvents}`} detail={`${eligiblePct.toFixed(1)}% of candidates`}/><Metric label="Signal-gate blocked" value={`${report.blockedEvents}`} detail="Before execution checks"/><Metric label="Evidence span" value={`${report.observationSpanDays.toFixed(1)}d`} detail={Object.entries(report.sources).map(([source,count])=>`${source} ${count}`).join(' · ')||'Waiting for signals'}/></dl>
        {report.latestRuntimeBlocker&&<div className="mt-5 rounded-xl border border-amber-300/25 bg-amber-300/5 p-4"><p className="text-xs font-semibold uppercase tracking-wider text-amber-200">Latest engine blocker</p><p className="mt-2 text-sm text-rom-muted">{report.latestRuntimeBlocker.reason}</p></div>}
        {!!report.blockers.length&&<div className="mt-5"><p className="text-xs font-semibold uppercase tracking-wider text-rom-muted">Signal-stage blockers</p><div className="mt-3 space-y-2">{report.blockers.slice(0,5).map(item=><div key={item.reason} className="grid grid-cols-[minmax(130px,1fr)_minmax(120px,2fr)_auto] items-center gap-3 text-xs"><span className="text-rom-muted">{item.reason}</span><div className="h-2 overflow-hidden rounded-full bg-rom-void"><div className="h-full rounded-full bg-blue-400" style={{width:`${Math.max(2,item.sharePct)}%`}}/></div><span className="tabular-nums text-rom-dim">{item.count} · {item.sharePct.toFixed(1)}%</span></div>)}</div></div>}
        <p className="mt-4 text-xs leading-5 text-rom-dim">This report deduplicates repeated scans of the same event. It explains frequency; it does not recommend relaxing a gate or claim that rejected candidates would be profitable.</p></>}
    </div>
  </Card>;
}

function MlPromotion({report,loading,error}:{report:MlPromotionReport|null;loading:boolean;error:string}) {
  const eligible=report?.status==='eligible';
  const rejected=report?.status==='rejected';
  const tone=eligible?'border-rom-win/35 bg-rom-win/5':rejected?'border-rom-loss/35 bg-rom-loss/5':'border-amber-300/25 bg-amber-300/5';
  const label=eligible?'Eligible for review':rejected?'Rejected':'Collecting data';
  const labelTone=eligible?'text-rom-win':rejected?'text-rom-lossText':'text-amber-300';
  const progress=report?Math.round(100*report.passedGates/Math.max(1,report.totalGates)):0;
  return <Card>
    <div className="flex flex-wrap items-start justify-between gap-4"><div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-rom-purple/10 text-rom-purple"><ShieldCheck className="h-5 w-5"/></div><div><h3 className="text-lg font-semibold">ML promotion gate</h3><p className="mt-1 text-sm text-rom-muted">One decision across forward accuracy, fee-adjusted returns, drawdown, and live execution.</p></div></div><span className={`rounded-full border border-rom-border bg-rom-void/40 px-3 py-1.5 text-xs font-semibold ${labelTone}`}>{label}</span></div>
    <div className="min-h-32 pt-5" aria-live="polite" aria-busy={loading}>
      {loading&&<p className="text-sm text-rom-muted">Checking every promotion requirement…</p>}
      {error&&<p role="alert" className="text-sm text-rom-lossText">{error}</p>}
      {report&&<>
        <div className={`rounded-xl border p-4 ${tone}`}><div className="flex flex-wrap items-center justify-between gap-3"><p className="max-w-3xl text-sm leading-6 text-rom-muted">{report.reason}</p><span className="text-xs font-semibold tabular-nums">{report.passedGates}/{report.totalGates} passed</span></div><div className="mt-4 h-1.5 overflow-hidden rounded-full bg-rom-void"><div className={`h-full rounded-full ${eligible?'bg-rom-win':rejected?'bg-rom-loss':'bg-amber-300'}`} style={{width:`${progress}%`}}/></div></div>
        <dl className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4"><Metric label="Gate progress" value={`${progress}%`} detail="All gates required"/><Metric label="Suggested influence" value={`${report.recommendedInfluencePct.toFixed(0)}%`} detail="Ranking weight cap"/><Metric label="Risk cap" value={`${report.recommendedAccountRiskCapPct.toFixed(1)}%`} detail="Account per entry"/><Metric label="Activation" value="Locked" detail="No live control"/></dl>
        {!!report.blockingReasons.length&&<div className="mt-5"><p className="text-xs font-semibold uppercase tracking-wider text-rom-muted">What needs attention</p><ul className="mt-3 grid gap-2 md:grid-cols-2">{report.blockingReasons.slice(0,4).map((reason,index)=><li key={`${index}-${reason}`} className="rounded-lg border border-rom-border bg-rom-void/30 px-3 py-2 text-xs leading-5 text-rom-dim">{reason}</li>)}</ul></div>}
        <details className="mt-4 rounded-lg border border-rom-border bg-rom-void/30 px-4 py-2"><summary className="cursor-pointer text-xs font-medium text-rom-muted">Review all {report.totalGates} requirements</summary><div className="grid gap-2 pb-2 pt-3 md:grid-cols-2">{report.gates.map(gate=><div key={gate.id} className="flex items-start gap-3 rounded-lg border border-rom-border/70 bg-rom-panel/50 p-3"><span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${gate.status==='pass'?'bg-rom-win':gate.status==='fail'?'bg-rom-loss':'bg-amber-300'}`}/><div><p className="text-xs font-semibold">{gate.label}</p><p className="mt-1 text-[11px] leading-5 text-rom-dim">{gate.detail}</p></div></div>)}</div></details>
        <p className="mt-4 text-xs leading-5 text-rom-dim">Eligibility is a review signal, not automatic activation. The model remains unable to approve, reject, size, or route live orders. Any future rollout must start at the displayed caps and automatically return to zero when a rollback condition trips.</p>
      </>}
    </div>
  </Card>;
}

function ForwardValidation({report,loading,error}:{report:ForwardValidationReport|null;loading:boolean;error:string}) {
  const value=(number:number|null)=>number===null?'—':number.toFixed(4);
  const percent=(number:number|null)=>number===null?'—':`${number>=0?'+':''}${number.toFixed(1)}%`;
  return <Card>
    <div className="flex flex-wrap items-start justify-between gap-4"><div><h3 className="text-lg font-semibold">Forward ML scorecard</h3><p className="mt-1 text-sm text-rom-muted">Scores predictions frozen before their markets resolve.</p></div><span className="rounded-full border border-rom-border bg-rom-void/40 px-3 py-1.5 text-xs font-medium text-rom-muted">Append-only evidence</span></div>
    <div className="min-h-24 pt-5" aria-live="polite" aria-busy={loading}>
      {loading&&<p className="text-sm text-rom-muted">Matching frozen predictions with later settlements…</p>}
      {error&&<p role="alert" className="text-sm text-rom-lossText">{error}</p>}
      {report&&<>
        <p className="text-sm leading-6 text-rom-muted">{report.reason}</p>
        <dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
          <Metric label="Resolved" value={`${report.resolvedPredictions}`} detail={`${report.observationSpanDays.toFixed(1)} observation days`}/>
          <Metric label="Independent days" value={`${report.independentDays}`} detail="UTC resolution clusters"/>
          <Metric label="Pending" value={`${report.pendingPredictions}`} detail="Awaiting settlement"/>
          <Metric label="Model Brier" value={value(report.modelBrier)} detail="Frozen model"/>
          <Metric label="Market Brier" value={value(report.marketBrier)} detail="Same observations"/>
          <Metric label="Brier change" value={percent(report.brierImprovementPct)} detail={`95% floor ${percent(report.brierImprovementLowerPct)}`}/>
        </dl>
        <dl className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
          <Metric label="Log-loss change" value={percent(report.logLossImprovementPct)} detail={`95% floor ${percent(report.logLossImprovementLowerPct)}`}/>
          <Metric label="Shadow selections" value={`${report.forwardTrades}`} detail={`Edge at least ${report.minimumModelEdgePct.toFixed(0)}%`}/>
          <Metric label="Fee-adjusted return" value={percent(report.netReturnPct)} detail="Dated taker costs"/>
          <Metric label="Return confidence" value={percent(report.lowerConfidenceReturnPct)} detail={`One-sided ${report.confidenceLevelPct.toFixed(0)}% floor`}/>
          <Metric label="Time windows" value={`${report.windowsPassed}/${report.windowsEvaluated}`} detail="Beat both baselines"/>
          <Metric label="Resamples" value={report.bootstrapReplicates.toLocaleString()} detail="Deterministic clusters"/>
        </dl>
        <p className="mt-4 text-xs leading-5 text-rom-dim">Confidence bounds resample entire resolution days, so markets sharing one news and liquidity regime do not masquerade as independent proof. Return and drawdown use fixed {report.simulationRiskPct.toFixed(0)}% simulated account risk per selected event. Only the first prediction for each event and model version is retained. Retraining cannot rewrite this scorecard, and it never controls live orders.</p>
      </>}
    </div>
  </Card>;
}

function ExecutionShadow({report,loading,error}:{report:ExecutionShadowReport|null;loading:boolean;error:string}) {
  const model=(name:string,item:ExecutionShadowReport['fillModel'],samples:number)=><div className="rounded-xl border border-rom-border bg-rom-void/30 p-4"><div className="flex items-center justify-between gap-3"><h4 className="text-sm font-semibold">{name}</h4><span className={`text-xs font-medium ${item.status==='promising'?'text-rom-win':item.status==='not_better'?'text-rom-lossText':'text-amber-300'}`}>{item.status==='promising'?'Promising':item.status==='not_better'?'Below baseline':'Collecting'}</span></div><p className="mt-2 text-xs leading-5 text-rom-dim">{item.reason}</p><dl className="mt-4 grid grid-cols-3 gap-3"><Metric label="Evidence" value={`${samples}`} detail={`${item.trainEvents} train · ${item.testEvents} test`}/><Metric label="Model Brier" value={item.modelBrier===null?'—':item.modelBrier.toFixed(4)} detail="Lower is better"/><Metric label="Baseline" value={item.baselineBrier===null?'—':item.baselineBrier.toFixed(4)} detail={item.baselineRate===null?'Rate unavailable':`${(item.baselineRate*100).toFixed(1)}% prior rate`}/></dl></div>;
  return <Card><div className="flex flex-wrap items-start justify-between gap-4"><div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-cyan-400/10 text-cyan-300"><Activity className="h-5 w-5"/></div><div><h3 className="text-lg font-semibold">Execution intelligence lab</h3><p className="mt-1 text-sm text-rom-muted">Tests which book conditions lead to fills and unfavorable 120-second movement.</p></div></div><span className="rounded-full border border-rom-border bg-rom-void/40 px-3 py-1.5 text-xs font-medium text-rom-muted">Shadow only · risk controls unchanged</span></div><div className="min-h-32 pt-5" aria-live="polite" aria-busy={loading}>{loading&&<p className="text-sm text-rom-muted">Evaluating confirmed order and markout evidence…</p>}{error&&<p role="alert" className="text-sm text-rom-lossText">{error}</p>}{report&&<><p className="mb-4 text-sm leading-6 text-rom-muted">{report.reason}</p><div className="grid gap-4 lg:grid-cols-2">{model('Fill probability challenger',report.fillModel,report.orders)}{model('Adverse-movement challenger',report.adverseModel,report.markoutSamples)}</div><p className="mt-4 text-xs leading-5 text-rom-dim">Each entry stores spread, depth, imbalance, quote age, route, response time and signal movement before the outcome is known. Later orders form the untouched test set. These models cannot change an order.</p></>}</div></Card>;
}

function ShadowRanker({report,loading,error}:{report:ShadowRankerReport|null;loading:boolean;error:string}) {
  const metric=(value:number|null)=>value===null?'—':value.toFixed(4);
  const positive=report?.status==='promising';
  return <Card>
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-rom-purple/10 text-rom-purple"><BrainCircuit className="h-5 w-5"/></div><div><h3 className="text-lg font-semibold">ML shadow ranker</h3><p className="mt-1 text-sm text-rom-muted">Learns from settled events and tests itself on later data.</p></div></div>
      <span className="rounded-full border border-rom-border bg-rom-void/40 px-3 py-1.5 text-xs font-medium text-rom-muted">Observation only · no live control</span>
    </div>
    <div className="min-h-32 pt-5" aria-live="polite" aria-busy={loading}>
      {loading&&<p className="text-sm text-rom-muted">Evaluating the untouched chronological holdout…</p>}
      {error&&<p role="alert" className="text-sm text-rom-lossText">{error}</p>}
      {report&&<>
        <div className={`rounded-xl border p-4 ${positive?'border-rom-win/35 bg-rom-win/5':'border-rom-border bg-rom-void/35'}`}><div className="flex flex-wrap items-center justify-between gap-3"><p className="max-w-3xl text-sm leading-6 text-rom-muted">{report.reason}</p><span className={`rom-pill ${positive?'border-rom-win/35 bg-rom-win/10 text-rom-win':'border-rom-border bg-rom-surface2 text-rom-muted'}`}>{report.status==='promising'?'Promising holdout':'Shadow mode'}</span></div></div>
        <dl className="mt-5 grid grid-cols-2 gap-5 sm:grid-cols-4">
          <Metric label="Settled events" value={`${report.settledSamples}`} detail={`${report.trainEvents} train · ${report.testEvents} later test`}/>
          <Metric label="Model Brier" value={metric(report.modelBrier)} detail="Lower is better"/>
          <Metric label="Market Brier" value={metric(report.marketBrier)} detail="Market-price baseline"/>
          <Metric label="Brier change" value={report.brierImprovementPct===null?'—':`${report.brierImprovementPct>=0?'+':''}${report.brierImprovementPct.toFixed(1)}%`} detail={`${Math.round(report.shrinkage*100)}% model blend`}/>
        </dl>
        <details className="mt-4 rounded-lg border border-rom-border bg-rom-void/30 px-4 py-2"><summary className="cursor-pointer text-xs font-medium text-rom-muted">How this safety phase works</summary><p className="pb-2 pt-3 text-xs leading-5 text-rom-dim">The model uses regularized logistic regression, one candidate per event, a one-day embargo, and a later untouched test set. Its probability is pulled {Math.round((1-report.shrinkage)*100)}% back toward the market price. It cannot approve, reject, size, or route an order. A promising result is research evidence, not a profitability guarantee.</p></details>
      </>}
    </div>
  </Card>;
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
        <div className="mt-5 border-t border-rom-border pt-4"><p className="text-xs font-semibold uppercase tracking-wider text-rom-muted">Post-fill movement</p><div className="mt-3 grid gap-3 sm:grid-cols-3">{(report.markouts||[]).map(markout=><div key={markout.horizonSec} className="rounded-lg border border-rom-border bg-rom-void/30 p-3"><p className="text-xs text-rom-dim">After {markout.horizonSec}s</p><p className={`mt-1 font-mono text-lg ${markout.avgMarkoutCents===null?'text-rom-muted':markout.avgMarkoutCents>=0?'text-rom-win':'text-rom-lossText'}`}>{cents(markout.avgMarkoutCents)}</p><p className="mt-1 text-[11px] text-rom-dim">{markout.samples} sample{markout.samples===1?'':'s'}{markout.adversePct===null?'':` · ${markout.adversePct.toFixed(0)}% moved against`}</p></div>)}</div><p className="mt-3 text-xs leading-5 text-rom-dim">Side-aware midpoint change from the confirmed fill price, weighted by filled contracts. Positive is favorable. These observations measure adverse selection; they do not yet change trading.</p></div>
        <div className="mt-5 border-t border-rom-border pt-4"><p className="text-xs font-semibold uppercase tracking-wider text-rom-muted">Adverse-selection guard</p>{!(report.adverseGuards||[]).length?<p className="mt-3 text-sm text-rom-muted">Waiting for confirmed 120-second post-fill observations. The guard will stay inactive until it has a varied sample.</p>:<div className="mt-3 space-y-2">{report.adverseGuards.map(guard=><div key={`${guard.source}-${guard.style}-${guard.priceCents}`} className={`rounded-lg border p-3 ${guard.blocked?'border-rom-loss/40 bg-rom-loss/5':'border-rom-border bg-rom-void/30'}`}><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium capitalize">{guard.source} · {guard.style} · {guard.priceCents}¢</p><span className={`rom-pill ${guard.blocked?'border-rom-loss/40 bg-rom-loss/10 text-rom-lossText':'border-rom-border bg-rom-surface2 text-rom-muted'}`}>{guard.blocked?'New entries paused':'Collecting evidence'}</span></div><p className="mt-2 text-xs leading-5 text-rom-dim">{guard.samples}/{guard.minimums.samples} market-days · {guard.days}/{guard.minimums.days} days · {guard.markets}/{guard.minimums.markets} markets{guard.upper95Cents===null?'':` · upper confidence bound ${guard.upper95Cents.toFixed(2)}¢`}</p></div>)}</div>}<p className="mt-3 text-xs leading-5 text-rom-dim">The guard never enlarges a trade. It only pauses a comparable entry after enough varied evidence shows unfavorable post-fill movement.</p></div>
        <details className="mt-4 rounded-lg border border-rom-border px-4 py-2"><summary className="cursor-pointer text-xs font-medium text-rom-muted">How execution feedback works</summary><div className="space-y-3 pb-2 pt-3 text-xs leading-5 text-rom-dim">
          <p>New live entries include a fee reserve. After 20 completed orders across 10 days in the same market, source, price range and route, observed fees can tighten that reserve. Persistently poor fills can pause entries in that group. The post-fill guard also needs at least 30 comparable observations across 10 days and 8 markets, and pauses only when even the upper confidence bound remains unfavorable. Evidence ages out after 30 days. Existing positions and exits remain managed.</p>
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
