import { useStrategyActivity } from '../state/StrategyActivity';
import { Activity, CirclePause, FlaskConical, ShieldAlert } from 'lucide-react';
import type { TradingStatus } from '@shared/types';
import { Card } from './common';
import { cls, fmtRelative, fmtUsd } from '../utils/format';

const tone = {
  paused: 'text-rom-dim bg-rom-dim/10 border-rom-border',
  scanning: 'text-rom-win bg-rom-win/10 border-rom-win/25',
  waiting: 'text-rom-warn bg-rom-warn/10 border-rom-warn/25',
  blocked: 'text-rom-loss bg-rom-loss/10 border-rom-loss/25',
};

export function MainActivity({ onOpenStrategy }: { onOpenStrategy: () => void }) {
  const {status,label,summary} = useStrategyActivity();
  if (!status) return <Card><h3 className="font-semibold">{label}</h3><p role="status" className="mt-2 text-sm text-rom-muted">{summary}</p><button className="rom-btn-default mt-4" onClick={onOpenStrategy}>Open strategy</button></Card>;
  const Icon = status.mainState === 'blocked'
    ? ShieldAlert : status.mainState === 'paused' ? CirclePause : Activity;
  const topFilters = Object.entries(status.mainFilterCounts || {})
    .sort((a, b) => b[1] - a[1]).slice(0, 3);
  const paper = status.mainPaper;

  return <Card>
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 gap-3">
        <div className={cls('grid h-10 w-10 shrink-0 place-items-center rounded-xl border', tone[status.mainState])}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">What Polybot is doing</h3>
            <span className={cls('rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide', tone[status.mainState])}>
              {status.mainState}
            </span>
            {status.mainMode !== 'paused' && <span className="rounded-full border border-rom-border px-2 py-0.5 text-[10px] uppercase text-rom-muted">
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

    {(topFilters.length > 0 || status.mainCandidates > 0) && <details className="mt-4 border-t border-rom-border pt-3">
      <summary className="cursor-pointer text-xs text-rom-muted">Latest decisions</summary>
      <p className="mt-2 text-xs text-rom-dim">
        {status.mainCandidates} candidate(s) checked · {status.mainPlaced} {status.mainMode === 'paper' ? 'practice trade(s)' : 'order(s)'} created
      </p>
      {topFilters.length > 0 && <ul className="mt-2 space-y-1">
        {topFilters.map(([reason, count]) => <li key={reason} className="text-xs text-rom-dim">{reason} ×{count}</li>)}
      </ul>}
    </details>}

    {status.mainMode === 'paper' && <p className="mt-4 flex gap-2 border-t border-rom-border pt-3 text-[11px] leading-5 text-rom-dim">
      <FlaskConical className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      Practice fills assume the selected entry price plus 1¢ per contract. They are estimates, not exchange fills.
    </p>}
  </Card>;
}

function PaperStat({ label, value }: { label: string; value: string }) {
  return <div><div className="text-[10px] uppercase tracking-wide text-rom-dim">{label}</div><div className="mt-1 text-sm font-semibold tabular-nums">{value}</div></div>;
}
