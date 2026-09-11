import { useEffect, useState } from 'react';
import { ArrowRight, Check, ShieldCheck, SlidersHorizontal, Radio, ScanLine } from 'lucide-react';
import type { BlockedIntent } from '@shared/types';
import { Card, Page } from '../components/common';
import { useApp } from '../state/AppStateProvider';
import { fmtUsd } from '../utils/format';
import type { PageId } from '../App';
import { MainActivity } from '../components/MainActivity';
import { useStrategyActivity } from '../state/StrategyActivity';
import { OrderRecovery } from '../components/OrderRecovery';

export function OverviewPage({ onNav }: { onNav: (page: PageId) => void }) {
  const { backend, account, config, positions } = useApp();
  const activity = useStrategyActivity();
  const connected = backend.authOk;
  const open = positions.filter(p => !p.resolved && ['filled', 'partial', 'submitted'].includes(p.status));
  const practicing = !!config?.mainPaperTrading && !config?.enableTrading;
  // A halted journal stops every engine with no timeout and no automatic
  // forget path, so it is polled on the landing page rather than only where
  // trading status happens to be fetched.
  const [blockedIntents, setBlockedIntents] = useState<BlockedIntent[]>([]);
  useEffect(() => {
    let alive = true;
    // Replace state only when the set of halted orders actually changes.
    // Handing back a fresh array every five seconds re-renders the whole page
    // for nothing, and on a normal run the answer is empty forever.
    const sameAs = (prev: BlockedIntent[], next: BlockedIntent[]) =>
      prev.length === next.length
      && prev.every((a, i) => a.localId === next[i].localId && a.state === next[i].state);
    const pull = async () => {
      let next: BlockedIntent[] = [];
      try {
        const st = await window.rom.trading.status();
        next = st?.recovery?.intents ?? [];
      } catch {
        // Backend down: other banners already say so, and a stale list here
        // would claim a halt that may no longer exist.
        next = [];
      }
      if (alive) setBlockedIntents((prev) => (sameAs(prev, next) ? prev : next));
    };
    void pull();
    const t = setInterval(pull, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  return <Page title="Overview" subtitle="Your account, performance and risk limits." actions={<button className="rom-btn-default" onClick={()=>onNav('evidence')}>Review evidence</button>}>
      {/* Above everything else: a blocking journal row halts submissions from
          every engine, and this is the page the user lands on. */}
      <OrderRecovery intents={blockedIntents} />
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="terminal-command terminal-command-detailed">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-rom-borderHi pb-4 text-xs text-rom-muted">
          <span className="flex items-center gap-2 font-mono uppercase tracking-widest"><ScanLine className="h-4 w-4 text-rom-purple" />ROM / Strategy terminal</span>
          <span className="flex items-center gap-2"><Radio className="h-3.5 w-3.5" />{connected ? 'API authenticated' : 'API not connected'}</span>
        </div>
        <div className="grid items-center gap-6 xl:grid-cols-[1fr_260px]">
          <div className="max-w-xl"><div className="terminal-mode mb-5"><span className={`h-1.5 w-1.5 rounded-full ${activity.label==='Scanning'?'bg-rom-win':'bg-rom-purple'}`} />{config?.enableTrading ? 'Live enabled' : practicing ? 'Practice enabled' : 'Trading paused'} · Polymarket US</div>
            <h3 className="text-3xl font-semibold tracking-tight">Main strategy: {activity.label.toLowerCase()}.</h3>
            <p className="mt-3 text-sm leading-6 text-rom-muted">{activity.summary}</p>
          </div>
          <div className="rounded-xl border border-rom-borderHi bg-rom-void/40 p-5">
            <h4 className="mb-4 text-xs font-semibold uppercase tracking-widest text-rom-muted">Latest decision cycle</h4>
            <dl className="grid grid-cols-2 gap-4">
              <div><dt className="text-xs text-rom-muted">Candidates</dt><dd className="mt-1 font-mono text-2xl">{activity.status?.mainLastCycleAt ? activity.status.mainCandidates : '—'}</dd></div>
              <div><dt className="text-xs text-rom-muted">{activity.status?.mainMode === 'paper' ? 'Practice entries' : 'Orders created'}</dt><dd className="mt-1 font-mono text-2xl">{activity.status?.mainLastCycleAt ? activity.status.mainPlaced : '—'}</dd></div>
            </dl>
            <button className="rom-btn-primary mt-5 w-full" onClick={() => onNav(connected ? 'main' : 'api')}>{connected ? 'Review strategy' : 'Connect account'}<ArrowRight className="h-4 w-4" /></button>
          </div>
        </div>
        {!connected && <div className="mt-7 grid gap-3 border-t border-rom-border pt-5 sm:grid-cols-3">{['Connect your account', 'Review strategy & limits', 'Choose when to start'].map((label, i) => <div key={label} className="flex items-center gap-3 text-xs text-rom-muted"><span className="grid h-6 w-6 place-items-center rounded-full border border-rom-border text-rom-purple">{i + 1}</span>{label}</div>)}</div>}
      </div>
      <dl className="terminal-metrics" aria-label="Portfolio summary">
        <div><dt>{practicing?'Practice available':'Account value'}</dt><dd>{practicing ? (activity.status ? fmtUsd(activity.status.mainPaper.availableUsd) : '—') : connected ? fmtUsd(account?.totalUsd) : '—'}</dd><small>{practicing?'Simulated funds, separate from your account':'Cash and portfolio value'}</small></div>
        <div><dt>{practicing?'Practice recorded P&L':'Session return'}</dt><dd>{practicing ? (activity.status ? fmtUsd(activity.status.mainPaper.pnlUsd,{sign:true}) : '—') : connected ? fmtUsd(account?.sessionPnlUsd,{sign:true}) : '—'}</dd><small>{practicing?'Includes the simulated cost allowance':'Performance during this session'}</small></div>
        <div><dt>{practicing?'Open practice trades':'Open positions'}</dt><dd>{practicing ? activity.status?.mainPaper.open ?? '—' : connected ? open.length : '—'}</dd><small>{practicing?'No exchange orders':'Including pending orders'}</small></div>
      </dl>
      <MainActivity onOpenStrategy={() => onNav('main')} />
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Card><div className="mb-5 flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-rom-win" /><h3 className="font-semibold">Your limits</h3></div>
          <dl className="space-y-4 text-sm">{[['Maximum per position', fmtUsd(config?.hardMaxPositionUsd)], ['Portfolio exposure limit', config ? `${Math.round(config.maxTotalExposureFraction * 100)}%` : '—'], ['Cash reserve', config ? `${Math.round(config.minCashReserveFraction * 100)}%` : '—']].map(([k,v])=><div key={k} className="flex justify-between gap-4"><dt className="text-rom-muted">{k}</dt><dd className="font-medium tabular-nums">{v}</dd></div>)}</dl>
          <button className="rom-btn-default mt-6 w-full" onClick={()=>onNav('main')}><SlidersHorizontal className="h-4 w-4" />Review strategy & limits</button>
        </Card>
        <Card><h3 className="mb-5 font-semibold">How entries are checked</h3><div className="space-y-4">{['A current, two-sided quote is required.', 'Wide spreads and price chasing are rejected.', 'Trade size reflects the margin left at entry.'].map(label=><p key={label} className="flex gap-3 text-sm text-rom-muted"><Check className="mt-0.5 h-4 w-4 shrink-0 text-rom-win" />{label}</p>)}</div><p className="mt-5 border-t border-rom-border pt-4 text-xs leading-5 text-rom-dim">These checks apply to the main strategy. Signal scores are heuristics, not verified win probabilities.</p><button className="mt-4 text-xs text-rom-purple hover:text-white" onClick={()=>onNav('analytics')}>Open detailed analytics →</button></Card>
      </div>
    </div>
  </Page>;
}
