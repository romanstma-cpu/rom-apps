import { AlertTriangle, CheckCircle2, ShieldCheck } from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { useStrategyActivity } from '../state/StrategyActivity';
import { cls, fmtUsd } from '../utils/format';

export function TradingCheck({ onOpenStrategy }: { onOpenStrategy: () => void }) {
  const { account, backend, config } = useApp();
  const activity = useStrategyActivity();
  const execution = activity.status?.executionHealth;
  const readiness = activity.status?.readiness;
  const dailyStop = Math.abs(config?.stopLossOnDay || 0);
  const todayPnl = account?.todayPnlUsd;
  const dailyLossUsed = Math.max(0, -(todayPnl || 0));
  const dailyRemaining = dailyStop > 0 ? Math.max(0, dailyStop - dailyLossUsed) : null;
  const live = !!config?.enableTrading;
  const practice = !!config?.mainPaperTrading && !live;
  const dailyStopped = dailyRemaining === 0 && dailyStop > 0 && dailyLossUsed >= dailyStop;
  const feedBlocked = execution?.marketStream.state === 'blocked' || ((live || practice) && !(execution?.marketStream.watchedMarkets || 0));
  const buyingPowerGate = activity.status?.main.find((gate) => gate.id === 'buyingPower');
  const evidenceGate = activity.status?.main.find((gate) => gate.id === 'qualifiedEdge');
  const evidenceReady = !!evidenceGate && !evidenceGate.reason;
  const buyingPowerReady = !!account && account.cashUsd > 0 && buyingPowerGate?.state !== 'blocked';
  const liveNeeds = [
    !evidenceReady ? evidenceGate?.reason || 'Qualified live evidence' : null,
    !buyingPowerReady ? buyingPowerGate?.reason || 'Available USD buying power' : null,
    dailyStopped ? 'Daily live loss stop has been reached' : null,
  ].filter((reason): reason is string => !!reason);
  const attention = !backend.authOk || !activity.healthy || !!execution?.blocked || feedBlocked || readiness?.status === 'not_ready' || readiness?.status === 'degraded' || (live && liveNeeds.length > 0);
  const statusLabel = attention ? 'Needs attention' : live ? 'Live checks clear' : practice ? 'Practice checks clear' : 'Trading paused';
  const streamDetail = execution?.blocked
    ? execution.reason
    : execution?.marketStream.state === 'blocked'
      ? execution.marketStream.lastSubscriptionError || 'Polymarket US rejected the live market-data subscription.'
      : (live || practice) && !(execution?.marketStream.watchedMarkets || 0)
        ? 'No active US markets are loaded, so the scanner cannot create candidates.'
    : execution?.marketStream.stale
      ? 'Live price stream is quiet; fresh REST quotes are being used.'
      : execution?.marketStream.connected
        ? 'Live price stream connected'
        : 'REST fallback ready while stream reconnects';
  const mode = live ? 'Live orders enabled' : practice ? 'Practice enabled' : 'Trading paused';
  const exposureCap = account && config
    ? account.totalUsd * config.maxTotalExposureFraction
    : null;

  const facts = [
    { label: 'Mode', value: mode, detail: backend.authOk ? 'Polymarket US API connected' : 'Connect API before live trading', tone: live ? 'text-rom-win' : 'text-white' },
    { label: 'Execution guard', value: execution?.blocked ? 'Paused for safety' : 'Controls clear', detail: streamDetail, tone: execution?.blocked ? 'text-rom-warn' : 'text-rom-win' },
    { label: 'System readiness', value: readiness?.status === 'not_ready' ? 'Not ready' : readiness?.status === 'degraded' ? 'Degraded' : readiness ? 'Ready' : 'Checking', detail: readiness ? `Deep check completed in ${Math.round(readiness.durationMs)} ms` : 'Checking database, disk, streams, and API lanes', tone: readiness?.status === 'not_ready' ? 'text-rom-warn' : readiness?.status === 'degraded' ? 'text-rom-warn' : readiness ? 'text-rom-win' : 'text-white' },
    { label: 'Buying power', value: account ? fmtUsd(account.cashUsd) : '—', detail: buyingPowerGate?.state === 'blocked' ? buyingPowerGate.reason : !buyingPowerReady ? 'Needed for live orders; Practice uses simulated funds' : live ? 'Available for live entry sizing' : 'Live account cash, separate from Practice', tone: buyingPowerReady ? 'text-white' : 'text-rom-warn' },
    { label: 'Exposure', value: account ? fmtUsd(account.openCostUsd) : '—', detail: exposureCap === null ? 'Account value unavailable' : `${fmtUsd(exposureCap)} maximum at current balance`, tone: 'text-white' },
    { label: 'Today’s P&L', value: fmtUsd(todayPnl, { sign: true }), detail: dailyRemaining === null ? 'Daily loss stop is off' : `${fmtUsd(dailyRemaining)} until daily loss stop`, tone: (todayPnl || 0) < 0 ? 'text-rom-loss' : (todayPnl || 0) > 0 ? 'text-rom-win' : 'text-white' },
    { label: 'Open orders', value: `${account?.pendingCount ?? 0}`, detail: `${account?.openCount ?? 0} filled position${(account?.openCount ?? 0) === 1 ? '' : 's'} open`, tone: 'text-white' },
    { label: 'Recorded fees', value: fmtUsd(account?.feesUsd), detail: 'From recorded main-strategy orders', tone: 'text-white' },
    { label: 'Position limit', value: fmtUsd(config?.hardMaxPositionUsd), detail: config ? `${Math.round(config.maxTotalExposureFraction * 100)}% portfolio cap` : 'Load strategy settings', tone: 'text-white' },
    { label: 'Loss limit', value: dailyStop > 0 ? fmtUsd(dailyStop) : 'Off', detail: dailyStopped ? 'Live daily stop has been reached' : 'Pauses new live main-strategy entries', tone: dailyStopped ? 'text-rom-warn' : 'text-white' },
  ];
  const primaryFacts = [facts[0], facts[1], facts[2], facts[3]];
  const supportingFacts = [facts[4], facts[5], facts[6], facts[7], facts[8], facts[9]];

  return <section className={cls('rounded-2xl border p-5', attention ? 'border-rom-warn/40 bg-rom-warn/[0.045]' : 'border-rom-win/30 bg-rom-win/[0.035]')} aria-labelledby="trading-check-title">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex gap-3">
        <div className={cls('grid h-10 w-10 shrink-0 place-items-center rounded-xl', attention ? 'bg-rom-warn/15 text-rom-warn' : 'bg-rom-win/10 text-rom-win')}>
          {attention ? <AlertTriangle className="h-5 w-5" /> : <ShieldCheck className="h-5 w-5" />}
        </div>
        <div>
          <div className="flex flex-wrap items-center gap-2"><h3 id="trading-check-title" className="font-semibold">Trade readiness</h3><span className={cls('rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide', attention ? 'border-rom-warn/30 text-rom-warn' : 'border-rom-win/30 text-rom-win')}>{statusLabel}</span></div>
          <p className="mt-1 max-w-2xl text-sm text-rom-muted">Practice uses simulated funds. Live orders need qualified evidence and available buying power. These checks do not predict performance.</p>
        </div>
      </div>
      <button className="rom-btn-default shrink-0" onClick={onOpenStrategy}>Review strategy</button>
    </div>
    <dl className="mt-5 grid gap-x-6 gap-y-5 border-t border-rom-border pt-5 sm:grid-cols-2 xl:grid-cols-4">
      {primaryFacts.map((fact) => <div key={fact.label}>
        <dt className="text-[11px] font-medium uppercase tracking-wide text-rom-dim">{fact.label}</dt>
        <dd className={cls('mt-1 text-sm font-semibold tabular-nums', fact.tone)}>{fact.value}</dd>
        <p className="mt-1 text-xs leading-4 text-rom-muted">{fact.detail}</p>
      </div>)}
    </dl>
    {liveNeeds.length > 0 && <div className="mt-5 rounded-lg border border-rom-warn/30 bg-rom-warn/[0.06] px-3 py-2.5 text-xs leading-5 text-rom-muted">
      <span className="font-semibold text-rom-warn">Live trading still needs: </span>{liveNeeds.join(' · ')}. Practice can run with simulated funds while these live requirements are unmet.
    </div>}
    <details className="group mt-5 rounded-xl border border-rom-border bg-rom-void/30 px-4 py-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-xs font-semibold text-rom-muted marker:hidden hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rom-purple/70">
        More safeguards and account detail
        <span className="font-mono text-rom-purple transition-transform duration-200 group-open:rotate-45" aria-hidden="true">+</span>
      </summary>
      <dl className="mt-4 grid gap-x-6 gap-y-5 border-t border-rom-border pt-4 sm:grid-cols-2 xl:grid-cols-5">
        {supportingFacts.map((fact) => <div key={fact.label}>
          <dt className="text-[11px] font-medium uppercase tracking-wide text-rom-dim">{fact.label}</dt>
          <dd className={cls('mt-1 text-sm font-semibold tabular-nums', fact.tone)}>{fact.value}</dd>
          <p className="mt-1 text-xs leading-4 text-rom-muted">{fact.detail}</p>
        </div>)}
      </dl>
    </details>
    {!attention && <p className="mt-5 flex gap-2 border-t border-rom-border pt-4 text-xs leading-5 text-rom-dim"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rom-win" />{live ? 'Live execution checks currently pass. Check positions and current market conditions before relying on them.' : practice ? 'Practice checks currently pass. Live requirements are shown separately above.' : 'Trading is paused. Review the Strategy page before starting Practice or live orders.'}</p>}
  </section>;
}
