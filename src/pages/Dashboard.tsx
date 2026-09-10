import { useEffect, useState } from 'react';
import { Activity, AlertTriangle, ArrowRight, Ban, CheckCircle2, RefreshCw, Sparkles, TrendingDown, TrendingUp } from 'lucide-react';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { PnlPoint } from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Card, Empty, Page, ShareableStat, StatCard } from '../components/common';
import { cls, fmtPct, fmtRelative, fmtUsd } from '../utils/format';
import { WhyNotTrading } from '../components/WhyNotTrading';
import type { PageId } from '../App';

interface DashboardProps {
  onNav: (p: PageId) => void;
}

export function DashboardPage({ onNav }: DashboardProps) {
  const { account, scannerStats, signals, positions, backend, credentials, config, refresh } = useApp();
  const toast = useToast();
  const [series, setSeries] = useState<PnlPoint[]>([]);
  const [restarting, setRestarting] = useState(false);
  const [killArmed, setKillArmed] = useState(false);
  const [killBusy, setKillBusy] = useState(false);
  const [killResult, setKillResult] = useState('');

  const engineDown = backend.status === 'crashed' || backend.status === 'stopped';

  const restartEngine = async (): Promise<void> => {
    setRestarting(true);
    toast.info('Restarting engine…');
    try {
      const result = await window.rom.backend.restart();
      if (!result.ok) throw new Error(result.message || 'Engine restart rejected');

      window.setTimeout(() => { void refresh.backend(); }, 1200);
    } catch (e: any) {
      toast.error(`Restart failed: ${e?.message || e}`);
    } finally {
      window.setTimeout(() => setRestarting(false), 1200);
    }
  };

  const openPositions = positions.filter((p) => !p.resolved && p.filledContracts > 0);

  const flattenAll = async (): Promise<void> => {
    setKillBusy(true);
    setKillResult('Requesting exits. Positions may remain open.');
    try {
      const result = await window.rom.trading.flatten();
      if (!result.ok) throw new Error(result.message || 'Exit request rejected');
      const message = 'Exit attempt completed. Check Positions for remaining holdings and pending orders.';
      setKillResult(message);
      toast.info(message);
      await refresh.positions();
      setKillArmed(false);
    } catch (e: any) {
      const message = `Exit request failed: ${e?.message || e}`;
      setKillResult(message);
      toast.error(message);
    } finally {
      setKillBusy(false);
    }
  };

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const s = await window.rom.data.pnlSeries(168);
        if (mounted) setSeries(s);
      } catch {}
    };
    void load();
    const i = window.setInterval(load, 30000);
    return () => {
      mounted = false;
      window.clearInterval(i);
    };
  }, []);

  const openPos = positions.filter(
    (p) => !p.resolved
      && p.status !== 'dry_run'
      && (p.status === 'filled' || p.status === 'partial' || p.status === 'submitted'),
  );
  const recentResolved = positions
    .filter((p) => p.resolved)
    .slice(0, 5);

  const issues: { label: string; tone: 'warn' | 'bad' | 'good'; cta?: { label: string; page: PageId } }[] = [];
  const walletConnected = !!credentials?.hasWalletKey;
  if (!walletConnected) {
    issues.push({
      label: 'No API credentials connected — live trading is unavailable',
      tone: 'bad',
      cta: { label: 'Connect API', page: 'api' },
    });
  } else if (!backend.authOk) {
    issues.push({
      label: 'Saved API credentials could not connect to Polymarket US',
      tone: 'bad',
      cta: { label: 'Re-test', page: 'api' },
    });
  }
  if (config && !config.enableTrading && walletConnected) {
    issues.push({
      label: 'Auto-trading is paused — flip the switch in the top bar to enable',
      tone: 'warn',
    });
  }

  if (!engineDown && backend.status !== 'running' && backend.status !== 'starting') {
    issues.push({
      label: `Backend is ${backend.status}${backend.lastError ? ` — ${backend.lastError}` : ''}`,
      tone: 'bad',
    });
  }
  if (issues.length === 0) {
    issues.push({ label: 'Everything looks good. Bot is online and watching.', tone: 'good' });
  }

  const sessionPnl = account?.sessionPnlUsd ?? 0;
  const sessionBaseline = account?.sessionBaselineUsd ?? null;
  const sessionRoi = account?.sessionRoiPct ?? 0;
  const sessionStartedAt = account?.sessionStartedAt;
  const alltimePnl = account?.alltimePnlUsd ?? 0;
  const realizedPos = account?.realizedPnlUsd ?? 0;
  const alltimeBaseline = account?.alltimeBaselineUsd ?? null;

  return (
    <Page title="Dashboard" subtitle="Live snapshot of your portfolio, signals, and bot health.">
      {engineDown && (
        <div className="mb-4 flex flex-col gap-3 rounded-xl border border-rom-loss/50 bg-rom-loss/10 p-4 sm:flex-row sm:items-center">
          <AlertTriangle className="h-6 w-6 shrink-0 text-rom-loss" />
          <div className="flex-1">
            <div className="text-sm font-semibold text-rom-loss">
              Trading engine is {backend.status === 'stopped' ? 'stopped' : 'offline'}
            </div>
            <div className="mt-0.5 text-xs text-rom-muted">
              No trades, reconciliation, or balance updates are running while the
              engine is down.
              {backend.lastError ? ` Last error: ${backend.lastError}` : ''}
            </div>
          </div>
          <button
            onClick={restartEngine}
            disabled={restarting}
            className="rom-btn-primary shrink-0 disabled:opacity-50"
          >
            <RefreshCw className={cls('h-4 w-4', restarting && 'animate-spin')} />
            {restarting ? 'Restarting…' : 'Restart engine'}
          </button>
        </div>
      )}
      {killResult && <p role="status" className="mb-4 rounded-xl border border-rom-border bg-rom-surface p-4 text-sm text-rom-muted">{killResult}</p>}
      {openPositions.length > 0 && (
        <div className="mb-4 flex flex-col gap-3 rounded-xl border border-rom-loss/30 bg-rom-loss/5 p-4 sm:flex-row sm:items-center">
          <Ban className="h-6 w-6 shrink-0 text-rom-loss" />
          <div className="flex-1">
            <div className="text-sm font-semibold text-rom-loss">
              {killArmed
                ? `Confirm: flatten ${openPositions.length} open position${openPositions.length > 1 ? 's' : ''}?`
                : `${openPositions.length} open position${openPositions.length > 1 ? 's' : ''} active`}
            </div>
            <div className="mt-0.5 text-xs text-rom-muted">
              {killArmed
                ? 'Requests cancellation of open orders and exits for filled main-strategy positions. Sales cannot be undone. Missing quotes or limited depth can leave holdings open. This does not pause the strategy.'
                : 'Request exits for the main strategy. Execution depends on current quotes and available depth; holdings may remain open.'}
            </div>
          </div>
          {killArmed ? (
            <>
              <button
                onClick={flattenAll}
                disabled={killBusy}
                className="rom-btn-danger shrink-0 disabled:opacity-50"
              >
                <Ban className="h-4 w-4" />
                {killBusy ? 'Flattening…' : 'Yes, flatten all'}
              </button>
              <button
                onClick={() => setKillArmed(false)}
                disabled={killBusy}
                className="rom-btn-default shrink-0"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={() => setKillArmed(true)}
              className="rom-btn-danger shrink-0"
            >
              <Ban className="h-4 w-4" />
              Kill switch
            </button>
          )}
        </div>
      )}
      {account?.tradingGeoblocked && (
        <div className="mb-4 flex flex-col gap-3 rounded-xl border border-rom-bad/50 bg-rom-bad/10 p-4 sm:flex-row sm:items-center">
          <AlertTriangle className="h-6 w-6 shrink-0 text-rom-bad" />
          <div className="flex-1">
            <div className="text-sm font-semibold text-rom-bad">
              Polymarket is blocking orders from your region
            </div>
            <div className="mt-0.5 text-xs text-rom-muted">
              Every recent order was rejected with Polymarket’s region-restriction error.
              Market data still flows, so everything else looks normal — but no trade can
              fill until your connection exits the blocked region (e.g. your VPN reconnects).
              This clears automatically once orders go through again.
            </div>
          </div>
        </div>
      )}
      {account?.unredeemedWinningsStale && (
        <div className="mb-4 flex flex-col gap-3 rounded-xl border border-rom-warn/50 bg-rom-warn/10 p-4 sm:flex-row sm:items-center">
          <AlertTriangle className="h-6 w-6 shrink-0 text-rom-warn" />
          <div className="flex-1">
            <div className="text-sm font-semibold text-rom-warn">
              {fmtUsd(account?.unredeemedWinningsUsd)} in winnings waiting to be redeemed
            </div>
            <div className="mt-0.5 text-xs text-rom-muted">
              Your won {(account?.unredeemedWinningsCount ?? 0) === 1 ? 'position is' : 'positions are'} still
              held as outcome tokens, so the bot can’t size trades with that cash. Turn on{' '}
              <span className="font-semibold text-rom-warn">Auto-Redeem</span> in Polymarket
              (Settings → Trading), or redeem on polymarket.us — your balance updates automatically
              once the winnings are redeemed.
            </div>
          </div>
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        <ShareableStat
          label="Total Balance"
          value={fmtUsd(account?.totalUsd)}
          hint={account?.balanceSyncing
            ? '⏳ syncing — an order just filled or settled; the venue reflects it in a moment'
            : `cash ${fmtUsd(account?.cashUsd)} · port ${fmtUsd(account?.portfolioUsd)}`}
          shareText={`ROM PolyBot balance: ${fmtUsd(account?.totalUsd)} `
            + `(${fmtUsd(alltimePnl, { sign: true })} since I started). `
            + `ROM Polybot · Polymarket US`}
        />
        <ShareableStat
          label="Session P&L"
          value={fmtUsd(sessionPnl, { sign: true })}
          hint={
            account?.balanceSyncing
              ? '⏳ syncing — a fill/settlement is landing; this number self-corrects in a moment'
              : sessionBaseline
                ? `${fmtUsd(sessionBaseline)} → ${fmtUsd(account?.totalUsd)} · ${fmtPct(sessionRoi)} · since ${fmtRelative(sessionStartedAt)}`
                : 'session baseline pending'
          }
          accent={account?.balanceSyncing ? undefined : sessionPnl >= 0 ? 'good' : 'bad'}
          shareText={`This session on ROM PolyBot: ${sessionPnl >= 0 ? '+' : ''}${fmtUsd(sessionPnl)} `
            + `(${fmtPct(sessionRoi)} ROI). `
            + `ROM Polybot · Polymarket US`}
        />
        <StatCard
          label="Open Positions"
          value={`${openPos.length} / ${config?.maxOpenPositions ?? 25}`}
          hint={`${account?.pendingCount ?? 0} pending · ${account?.openCount ?? 0} filled`}
        />
      </div>

      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <ShareableStat
          label="All-time P&L"
          value={fmtUsd(alltimePnl, { sign: true })}
          hint={
            alltimeBaseline
              ? `${fmtUsd(alltimeBaseline)} → ${fmtUsd(account?.totalUsd)} · balance delta`
              : 'pending baseline'
          }
          accent={alltimePnl >= 0 ? 'good' : 'bad'}
          shareText={`All-time on ROM PolyBot: ${alltimePnl >= 0 ? '+' : ''}${fmtUsd(alltimePnl)} `
            + `(${fmtPct(account?.roiPct ?? 0)}). `
            + `ROM Polybot · Polymarket US`}
        />
        <ShareableStat
          label="Win Rate"
          value={(account?.wins ?? 0) + (account?.losses ?? 0) > 0
            ? `${(account?.winRate ?? 0).toFixed(1)}%`
            : '—'}
          hint={`${account?.wins ?? 0}W / ${account?.losses ?? 0}L · pos-derived realized ${fmtUsd(realizedPos, { sign: true })}`}
          shareText={`ROM PolyBot win rate: ${(account?.winRate ?? 0).toFixed(1)}% `
            + `(${account?.wins ?? 0}W / ${account?.losses ?? 0}L). `
            + `ROM Polybot · Polymarket US`}
        />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" header={
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-wider text-rom-muted">Equity curve</div>
              <div className="mt-0.5 text-sm text-white">
                Last {Math.min(168, Math.floor(((Date.now() - new Date(series[0]?.at ?? Date.now()).getTime()) / 3600000) || 168))}h
              </div>
            </div>
            <div className="text-xs text-rom-muted">
              {series.length} samples
            </div>
          </div>
        }>
          {series.length < 3 ? (
            <Empty
              title="Not enough data yet"
              description="The equity curve fills in as the bot runs. Come back in a few cycles."
            />
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={series}>
                  <defs>
                    <linearGradient id="fillGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3B82F6" stopOpacity={0.55} />
                      <stop offset="100%" stopColor="#3B82F6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis
                    dataKey="at"
                    hide
                  />
                  <YAxis
                    domain={['dataMin - 5', 'dataMax + 5']}
                    tickFormatter={(v) => `$${Math.round(v)}`}
                    width={50}
                    tick={{ fill: '#71717A', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#171722',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    formatter={(v: number) => [`$${v.toFixed(2)}`, 'Equity']}
                    labelFormatter={(v) => fmtRelative(String(v))}
                  />
                  <Area
                    type="monotone"
                    dataKey="totalUsd"
                    stroke="#3B82F6"
                    strokeWidth={2}
                    fill="url(#fillGrad)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card header={<div className="text-xs uppercase tracking-wider text-rom-muted">Status</div>}>
          <div className="flex flex-col gap-2">
            {issues.map((i, idx) => (
              <div
                key={idx}
                className={cls(
                  'flex items-start gap-2 rounded-lg border p-2 text-xs',
                  i.tone === 'good' && 'border-rom-win/30 bg-rom-win/5 text-rom-win',
                  i.tone === 'warn' && 'border-rom-warn/30 bg-rom-warn/5 text-rom-warn',
                  i.tone === 'bad' && 'border-rom-loss/30 bg-rom-loss/5 text-rom-loss',
                )}
              >
                {i.tone === 'good' ? (
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                ) : (
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                )}
                <div className="flex-1">{i.label}</div>
                {i.cta && (
                  <button
                    onClick={() => onNav(i.cta!.page)}
                    className="rounded-md border border-current px-2 py-0.5 text-[11px] hover:bg-current/10"
                  >
                    {i.cta.label}
                  </button>
                )}
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
            <Mini label="Whales seen" value={`${scannerStats?.whales.total ?? 0}`} />
            <Mini label="Whales hit" value={`${(scannerStats?.whales.winRate ?? 0).toFixed(1)}%`} />
            <Mini label="Momentum seen" value={`${scannerStats?.momentum.total ?? 0}`} />
            <Mini label="Momentum hit" value={`${(scannerStats?.momentum.winRate ?? 0).toFixed(1)}%`} />
            <Mini label="Markets" value={`${scannerStats?.marketsTracked ?? 0}`} />
            <Mini label="Last scan" value={fmtRelative(scannerStats?.lastTradeScanAt)} />
          </div>
          <div className="mt-4">
            <WhyNotTrading />
          </div>
        </Card>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card header={
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-rom-purple" />
              <span className="text-sm text-white">Latest signals</span>
            </div>
            <button onClick={() => onNav('signals')} className="text-xs text-rom-muted hover:text-white">
              View all <ArrowRight className="ml-1 inline h-3 w-3" />
            </button>
          </div>
        }>
          {signals.length === 0 ? (
            <Empty title="No signals yet" description="The scanners need a few minutes after launch." />
          ) : (
            <div className="flex flex-col divide-y divide-rom-border">
              {signals.slice(0, 7).map((s) => (
                <div key={`${s.source}:${s.id}`} className="flex items-center gap-3 py-2 text-sm">
                  <span className={cls(
                    'inline-flex h-6 w-14 items-center justify-center rounded-md text-[10px] font-medium uppercase',
                    s.source === 'whale' ? 'bg-rom-purple/15 text-rom-purple' : 'bg-rom-pink/15 text-rom-pink',
                  )}>
                    {s.source}
                  </span>
                  <span className="font-mono text-xs text-rom-muted">{s.ticker}</span>
                  <span className="ml-auto truncate text-xs text-rom-muted">{s.title}</span>
                  <span className={cls(
                    'min-w-[44px] text-right font-mono text-xs',
                    s.direction === 'yes' ? 'text-rom-win' : 'text-rom-loss',
                  )}>
                    {s.direction.toUpperCase()} {s.priceCents}¢
                  </span>
                  <span className="min-w-[40px] text-right font-mono text-xs text-rom-purple">
                    +{s.edgePts.toFixed(1)}
                  </span>
                  {s.traded && (
                    <span className="rom-pill border-rom-indigo/40 bg-rom-indigo/10 text-rom-indigo">
                      traded
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card header={
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-rom-pink" />
              <span className="text-sm text-white">Recent resolutions</span>
            </div>
            <button onClick={() => onNav('history')} className="text-xs text-rom-muted hover:text-white">
              View all <ArrowRight className="ml-1 inline h-3 w-3" />
            </button>
          </div>
        }>
          {recentResolved.length === 0 ? (
            <Empty
              title="No resolved trades yet"
              description="Wins and losses show up here as markets settle."
            />
          ) : (
            <div className="flex flex-col divide-y divide-rom-border">
              {recentResolved.map((p) => (
                <div key={p.id} className="flex items-center gap-3 py-2 text-sm">
                  {p.outcomeCorrect === 1 ? (
                    <TrendingUp className="h-4 w-4 text-rom-win" />
                  ) : p.outcomeCorrect === 0 ? (
                    <TrendingDown className="h-4 w-4 text-rom-loss" />
                  ) : (
                    <span className="h-4 w-4" />
                  )}
                  <span className="font-mono text-xs text-rom-muted">{p.ticker}</span>
                  <span className="ml-auto truncate text-xs text-rom-muted">{p.title}</span>
                  <span className={cls(
                    'min-w-[60px] text-right font-mono text-sm',
                    (p.pnlUsd ?? 0) >= 0 ? 'text-rom-win' : 'text-rom-loss',
                  )}>
                    {fmtUsd(p.pnlUsd, { sign: true })}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </Page>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-rom-border bg-rom-surface2 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-rom-muted">{label}</div>
      <div className="font-mono text-sm text-white">{value}</div>
    </div>
  );
}
