import { useStrategyActivity } from '../state/StrategyActivity';
import { Activity, CirclePause, FlaskConical, ShieldAlert } from 'lucide-react';
import type { TradingStatus } from '@shared/types';
import { Card } from './common';
import { cls, fmtRelative, fmtUsd } from '../utils/format';

const tone = {
  paused: 'text-rom-dim bg-rom-dim/10 border-rom-border',
  scanning: 'text-rom-win bg-rom-win/10 border-rom-win/25',
  waiting: 'text-rom-warn bg-rom-warn/10 border-rom-warn/25',
  blocked: 'text-rom-lossText bg-rom-loss/10 border-rom-loss/25',
};

export function MainActivity({ onOpenStrategy }: { onOpenStrategy: () => void }) {
  const {status,label,summary} = useStrategyActivity();
  if (!status) return <Card><h3 className="font-semibold">{label}</h3><p role="status" className="mt-2 text-sm text-rom-muted">{summary}</p><button className="rom-btn-default mt-4" onClick={onOpenStrategy}>Open strategy</button></Card>;
  const Icon = status.mainState === 'blocked'
    ? ShieldAlert : status.mainState === 'paused' ? CirclePause : Activity;
  const topFilters = Object.entries(status.mainFilterCounts || {})
    .sort((a, b) => b[1] - a[1]).slice(0, 3);
  const paper = status.mainPaper;
  const funnel = status.opportunityFunnel;
  const stream = status.executionHealth.marketStream;
  const whaleCategories = funnel?.categoryLimits.whale ?? [];
  const momentumCategories = funnel?.categoryLimits.momentum ?? [];
  const excludedCategories = funnel ? [
    ...Object.entries(funnel.excludedByCategory.whale).map(([category, count]) => `Large Trades: ${category} (${count})`),
    ...Object.entries(funnel.excludedByCategory.momentum).map(([category, count]) => `Momentum: ${category} (${count})`),
  ] : [];

  return <Card>
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 gap-3">
        <div className={cls('grid h-10 w-10 shrink-0 place-items-center rounded-xl border', tone[status.mainState])}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">What Polybot is doing</h3>
            <span className={cls('rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide', tone[status.mainState])}>
              {status.mainState}
            </span>
            {status.mainMode !== 'paused' && <span className="rounded-full border border-rom-border px-2 py-0.5 text-[11px] uppercase text-rom-muted">
              {status.mainMode === 'paper' ? 'Practice' : status.mainMode}
            </span>}
          </div>
          <p className="mt-2 text-sm text-rom-muted">{status.mainSummary}</p>
          <p className="mt-1 text-[11px] text-rom-dim">
            {status.mainLastCycleAt
              ? `Last decision cycle ${fmtRelative(new Date(status.mainLastCycleAt * 1000).toISOString())}`
              : 'No decision cycle recorded yet'}
          </p>
        </div>
      </div>
      <button className="rom-btn-default" onClick={onOpenStrategy}>Open strategy</button>
    </div>

    {status.mainMode === 'paper' && <div className="mt-5 grid gap-3 border-t border-rom-border pt-4 sm:grid-cols-4">
      <PaperStat label="Practice available" value={fmtUsd(paper.availableUsd)} />
      <PaperStat label="Recorded P&L" value={fmtUsd(paper.pnlUsd, { sign: true })} />
      <PaperStat label="Open practice" value={`${paper.open}`} />
      <PaperStat label="Resolved" value={`${paper.resolved}`} />
    </div>}

    {funnel && <section className="mt-5 border-t border-rom-border pt-4" aria-label="Opportunity funnel">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div><h4 className="text-sm font-semibold text-white">Opportunity funnel</h4><p className="mt-1 text-[11px] text-rom-dim">Feed activity covers the last {funnel.windowHours} hours; decisions are from the latest scan.</p></div>
        {stream.tradeFlowStalled && <span className="rounded-full border border-rom-loss/30 bg-rom-loss/10 px-2 py-1 text-[11px] font-semibold text-rom-lossText">Trade feed restarting</span>}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
        <FunnelStat label="Markets watched" value={funnel.watchedMarkets} />
        <FunnelStat label="Trades received" value={funnel.tradeEvents} warn={funnel.watchedMarkets > 0 && funnel.tradeEvents === 0} />
        <FunnelStat label="Signals created" value={funnel.signalEvents} warn={funnel.tradeEvents > 0 && funnel.signalEvents === 0} />
        <FunnelStat label="Candidates" value={funnel.candidates} warn={funnel.signalEvents > 0 && funnel.candidates === 0} />
        <FunnelStat label="Trades created" value={funnel.placed} />
      </div>
      {(funnel.primaryBlock || whaleCategories.length || momentumCategories.length) && <div className="mt-3 space-y-1 rounded-lg bg-rom-void/35 px-3 py-2.5 text-[11px] text-rom-muted">
        {funnel.primaryBlock && <p><span className="font-medium text-white">Latest block:</span> {funnel.primaryBlock}</p>}
        {whaleCategories.length > 0 && <p><span className="font-medium text-white">Large Trade categories:</span> {whaleCategories.join(', ')}</p>}
        {momentumCategories.length > 0 && <p><span className="font-medium text-white">Momentum categories:</span> {momentumCategories.join(', ')}</p>}
        {excludedCategories.length > 0 && <p className="text-rom-warn"><span className="font-medium">Recent signals excluded:</span> {excludedCategories.join(' · ')}. Choose Allow all or include these categories on the Strategy page.</p>}
      </div>}
    </section>}

    {(topFilters.length > 0 || status.mainCandidates > 0) && <details className="mt-4 border-t border-rom-border pt-3">
      <summary className="cursor-pointer text-xs text-rom-muted">Latest decisions</summary>
      <p className="mt-2 text-xs text-rom-dim">
        {status.mainCandidates} candidate(s) checked · {status.mainPlaced} {status.mainMode === 'paper' ? 'practice trade(s)' : 'order(s)'} created
      </p>
    </details>}
    {topFilters.length > 0 && <section className="mt-5 border-t border-rom-border pt-4" aria-label="Leading entry filters">
      <div className="mb-3 flex justify-between gap-4 text-xs text-rom-muted"><h4>Leading entry filters</h4><span>Latest cycle · counts may overlap</span></div>
      <ul className="space-y-3">{topFilters.map(([reason, count]) => <li key={reason}>
        <div className="mb-1.5 flex justify-between gap-4 text-xs"><span className="break-words text-rom-muted">{reason}</span><span className="font-mono text-rom-purple">{count}</span></div>
        <div aria-hidden="true" className="h-1 overflow-hidden rounded-full bg-rom-surface2"><div className="h-full rounded-full bg-rom-purple/70" style={{width: `${Math.min(100, count / Math.max(1, topFilters[0][1]) * 100)}%`}} /></div>
      </li>)}</ul>
    </section>}

    {status.mainMode === 'paper' && <p className="mt-4 flex gap-2 border-t border-rom-border pt-3 text-[11px] leading-5 text-rom-dim">
      <FlaskConical className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      Practice fills assume the selected entry price plus 1¢ per contract. They are estimates, not exchange fills.
    </p>}
  </Card>;
}

function PaperStat({ label, value }: { label: string; value: string }) {
  return <div><div className="text-[11px] uppercase tracking-wide text-rom-dim">{label}</div><div className="mt-1 text-sm font-semibold tabular-nums">{value}</div></div>;
}

function FunnelStat({ label, value, warn = false }: { label: string; value: number; warn?: boolean }) {
  return <div className={cls('rounded-lg border px-3 py-2.5', warn ? 'border-rom-warn/30 bg-rom-warn/5' : 'border-rom-border bg-rom-void/25')}>
    <div className="text-[10px] uppercase tracking-wide text-rom-dim">{label}</div>
    <div className={cls('mt-1 font-mono text-lg font-semibold tabular-nums', warn ? 'text-rom-warn' : 'text-white')}>{value.toLocaleString()}</div>
  </div>;
}
