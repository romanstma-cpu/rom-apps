import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { History as HistoryIcon, Download, Play, Receipt, Square, Timer, Trash2, Trophy } from 'lucide-react';
import type { BotRun, Crypto15mPosition } from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Card, Empty, Page, ShareableStat, StatCard } from '../components/common';
import { TickerLink } from '../components/PolymarketTicker';
import { cls, fmtPct, fmtUsd, fmtDateTime } from '../utils/format';

type HistoryTab = 'runs' | 'trades' | 'crypto15m';

export function HistoryPage() {
  const { positions, account, config } = useApp();
  const toast = useToast();
  const [tab, setTab] = useState<HistoryTab>('runs');
  const [runs, setRuns] = useState<BotRun[]>([]);
  const [c15Rows, setC15Rows] = useState<Crypto15mPosition[]>([]);
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    if (tab !== 'crypto15m') return;
    void window.rom.crypto15m.history({ limit: 300 })
      .then((r) => setC15Rows(r?.rows ?? []))
      .catch(() => setC15Rows([]));
  }, [tab]);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const r = await window.rom.data.botRuns(config?.network ?? null, 100);
        if (mounted) setRuns(r.runs);
      } catch {}
    };
    void load();
    const i = window.setInterval(load, 15000);
    return () => { mounted = false; window.clearInterval(i); };
  }, [config?.network]);

  const clearHistory = async (): Promise<void> => {
    if (!window.confirm(
      'Clear ALL trade history?\n\n'
      + 'This permanently wipes your trade ledger, P&L charts, and run/session '
      + 'history — and starts your session stats fresh from your current balance.\n\n'
      + 'Your settings, strategies, and wallet are kept. Open positions stay open '
      + 'on Polymarket. This cannot be undone.',
    )) return;
    setClearing(true);
    try {
      const r = await window.rom.app.clearHistory();
      if (!r.ok) {
        toast.error(r.message || 'Failed to clear history');
        return;
      }
      setRuns([]);
      toast.success(r.message || 'History cleared');
    } catch (e: any) {
      toast.error(`${e?.message || e}`);
    } finally {
      setClearing(false);
    }
  };

  const resolved = useMemo(() => {
    const env = config?.network;
    const ts = (p: { resolvedAt: string | null; lastUpdated: string; createdAt: string }) => {
      const cands = [p.resolvedAt, p.lastUpdated, p.createdAt];
      for (const c of cands) {
        if (!c) continue;
        const t = new Date(c).getTime();
        if (Number.isFinite(t)) return t;
      }
      return 0;
    };
    return positions
      .filter((p) =>
        p.resolved
        && p.status !== 'dry_run'

        && p.signalSource !== 'external'
        && (env ? p.network === env : true)
        && p.outcomeCorrect !== null,
      )
      .sort((a, b) => ts(b) - ts(a));
  }, [positions, config?.network]);

  return (
    <Page
      title="History"
      subtitle="Per-run rollups (the bot's session diary) and the full settled trade ledger."
      actions={(
        <button
          onClick={clearHistory}
          disabled={clearing}
          className="rom-btn-default border-rom-loss/40 text-rom-lossText hover:bg-rom-loss/10 disabled:opacity-50"
          title="Wipe trade history, P&L, and sessions — keeps your settings and wallet"
        >
          <Trash2 className="h-4 w-4" />
          {clearing ? 'Clearing…' : 'Clear history'}
        </button>
      )}
    >
      <div className="mb-4 inline-flex rounded-md border border-rom-border bg-rom-surface2 p-0.5">
        <TabButton active={tab === 'runs'} onClick={() => setTab('runs')} icon={<HistoryIcon className="h-3.5 w-3.5" />}>
          Run history
          <span className="ml-1.5 rounded bg-rom-surface px-1.5 py-0.5 text-[11px]">{runs.length}</span>
        </TabButton>
        <TabButton active={tab === 'trades'} onClick={() => setTab('trades')} icon={<Receipt className="h-3.5 w-3.5" />}>
          Trade history
          <span className="ml-1.5 rounded bg-rom-surface px-1.5 py-0.5 text-[11px]">{resolved.length}</span>
        </TabButton>
        <TabButton active={tab === 'crypto15m'} onClick={() => setTab('crypto15m')} icon={<Timer className="h-3.5 w-3.5" />}>
          15m trades
        </TabButton>
      </div>

      {tab === 'runs' && <RunHistory runs={runs} env={config?.network} />}
      {tab === 'trades' && <TradeHistory resolved={resolved} account={account} />}
      {tab === 'crypto15m' && <Crypto15mHistory rows={c15Rows} />}
    </Page>
  );
}

function Crypto15mHistory({ rows }: { rows: Crypto15mPosition[] }) {
  const total = rows.reduce((a, r) => a + (r.pnlUsd ?? 0), 0);
  const wins = rows.filter((r) => (r.pnlUsd ?? 0) > 0).length;
  if (rows.length === 0) {
    return <Empty title="No resolved 15m trades yet" description="Settled 15-minute crypto trades appear here, with the strategy that opened each one." />;
  }
  return (
    <Card>
      <div className="mb-3 flex flex-wrap gap-4 text-xs text-rom-dim">
        <span>{rows.length} trades</span>
        <span>{wins}W / {rows.length - wins}L</span>
        <span>P&L <span className={cls('font-mono', total >= 0 ? 'text-rom-win' : 'text-rom-lossText')}>{fmtUsd(total, { sign: true })}</span></span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-rom-dim">
              <th className="py-1 pr-3 font-normal">When</th>
              <th className="py-1 pr-3 font-normal">Asset</th>
              <th className="py-1 pr-3 font-normal">Side</th>
              <th className="py-1 pr-3 font-normal">Strategy</th>
              <th className="py-1 pr-3 font-normal">Size</th>
              <th className="py-1 pr-3 font-normal">Entry</th>
              <th className="py-1 pr-3 font-normal">Exit</th>
              <th className="py-1 font-normal">P&L</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-rom-border/50">
                <td className="py-1.5 pr-3 text-rom-dim">{fmtDateTime(r.resolvedAt ?? r.createdAt)}</td>
                <td className="py-1.5 pr-3 font-mono text-white">{r.asset}</td>
                <td className="py-1.5 pr-3 text-rom-dim">{r.side}</td>
                <td className="py-1.5 pr-3 text-rom-dim">{r.strategy || 'directional'}</td>
                <td className="py-1.5 pr-3 font-mono text-rom-dim">{r.filledContracts}</td>
                <td className="py-1.5 pr-3 font-mono text-rom-dim">{r.avgEntryCents != null ? `${Math.round(r.avgEntryCents)}¢` : '—'}</td>
                <td className="py-1.5 pr-3 text-rom-dim">{r.exitReason || r.status}</td>
                <td className={cls('py-1.5 font-mono', (r.pnlUsd ?? 0) >= 0 ? 'text-rom-win' : 'text-rom-lossText')}>
                  {fmtUsd(r.pnlUsd ?? 0, { sign: true })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function TabButton({
  active, onClick, icon, children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cls(
        'inline-flex items-center gap-1.5 rounded-[6px] px-3 py-1.5 text-xs font-medium transition-colors',
        active ? 'bg-rom-purple/15 text-rom-purple' : 'text-rom-muted hover:text-white',
      )}
    >
      {icon}
      {children}
    </button>
  );
}

function RunHistory({ runs, env }: { runs: BotRun[]; env?: string }) {
  const totals = useMemo(() => {
    let pnl = 0;
    let trades = 0;
    let wins = 0;
    let losses = 0;
    for (const r of runs) {
      pnl += r.pnlUsd;
      trades += r.tradesOpened;
      wins += r.tradesWon;
      losses += r.tradesLost;
    }
    const wr = wins + losses > 0 ? (wins / (wins + losses)) * 100 : 0;
    const completed = runs.filter((r) => !r.isActive);
    const winningRuns = completed.filter((r) => r.pnlUsd > 0).length;
    return { pnl, trades, wins, losses, wr, completed, winningRuns };
  }, [runs]);

  const bestRun = useMemo(
    () => runs.reduce((m, r) => (r.pnlUsd > (m?.pnlUsd ?? -Infinity) ? r : m), runs[0]),
    [runs],
  );
  const worstRun = useMemo(
    () => runs.reduce((m, r) => (r.pnlUsd < (m?.pnlUsd ?? Infinity) ? r : m), runs[0]),
    [runs],
  );

  return (
    <>
      <div className="grid gap-4 md:grid-cols-4">
        <ShareableStat
          label="P&L across all runs"
          value={fmtUsd(totals.pnl, { sign: true })}
          accent={totals.pnl >= 0 ? 'good' : 'bad'}
          hint={`${runs.length} run${runs.length === 1 ? '' : 's'} · ${env ?? 'all envs'}`}
          shareText={`ROM PolyBot has run ${runs.length}× and netted ${fmtUsd(totals.pnl, { sign: true })} `
            + `(${totals.wins}W / ${totals.losses}L). `
            + `ROM Polybot · Polymarket US`}
        />
        <ShareableStat
          label="Run win rate"
          value={fmtPct(totals.completed.length ? (totals.winningRuns / totals.completed.length) * 100 : 0)}
          hint={`${totals.winningRuns} green of ${totals.completed.length} finished`}
          accent={totals.winningRuns >= totals.completed.length / 2 ? 'good' : 'warn'}
          shareText={`${totals.winningRuns} out of ${totals.completed.length} ROM PolyBot sessions ended green. `
            + `ROM Polybot · Polymarket US`}
        />
        <StatCard
          label="Trades opened (total)"
          value={`${totals.trades}`}
          hint={`${totals.wins}W · ${totals.losses}L · ${fmtPct(totals.wr)} hit rate`}
        />
        <StatCard
          label="Avg run P&L"
          value={fmtUsd(runs.length ? totals.pnl / runs.length : 0, { sign: true })}
          accent={(runs.length ? totals.pnl / runs.length : 0) >= 0 ? 'good' : 'bad'}
          hint={runs.length ? `${runs.length} runs averaged` : 'no completed runs yet'}
        />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" header={
          <div className="flex items-center justify-between">
            <div className="text-sm text-white">P&amp;L per run</div>
            <div className="text-xs text-rom-muted">{runs.length} runs</div>
          </div>
        }>
          {runs.length === 0 ? (
            <Empty title="No runs yet" description="A new run starts every time you launch ROM PolyBot." />
          ) : (
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={[...runs].reverse().map((r) => ({
                  label: shortDate(r.startedAt),
                  pnl: r.pnlUsd,
                  ...r,
                }))}>
                  <XAxis dataKey="label" tick={{ fill: '#71717A', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(v) => `$${v}`} tick={{ fill: '#71717A', fontSize: 11 }} axisLine={false} tickLine={false} width={40} />
                  <Tooltip
                    contentStyle={{ background: '#171722', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8 }}
                    labelStyle={{ color: '#FFFFFF' }}
                    itemStyle={{ color: '#FFFFFF' }}
                    formatter={(v: number) => [fmtUsd(v, { sign: true }), 'P&L']}
                  />
                  <Bar dataKey="pnl">
                    {runs.map((r) => (
                      <Cell key={r.id} fill={r.pnlUsd >= 0 ? '#22C55E' : '#EF4444'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card>
          <div className="flex items-center gap-2 text-sm text-white">
            <Trophy className="h-4 w-4 text-rom-warn" />
            Standout runs
          </div>
          <div className="mt-3 space-y-2 text-xs">
            <RunStandout label="Best run" run={bestRun} accent="good" />
            <RunStandout label="Worst run" run={worstRun} accent="bad" />
          </div>
        </Card>
      </div>

      <div className="mt-6 overflow-hidden rounded-xl border border-rom-border">
        <table className="rom-table">
          <thead>
            <tr>
              <th>Started</th>
              <th>Ended</th>
              <th>Env</th>
              <th>Start → End</th>
              <th>P&amp;L</th>
              <th>Trades</th>
              <th>W/L</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className={cls(r.isActive && 'bg-rom-purple/5')}>
                <td className="text-xs text-rom-muted">
                  <span className="inline-flex items-center gap-1.5">
                    {r.isActive
                      ? <Play className="h-3 w-3 text-rom-purple" />
                      : <Square className="h-3 w-3 text-rom-muted" />}
                    {fmtDateTime(r.startedAt)}
                  </span>
                </td>
                <td className="text-xs text-rom-muted">
                  {r.isActive
                    ? <span className="text-rom-purple">running</span>
                    : fmtDateTime(r.endedAt || '')}
                </td>
                <td>
                  <span className="rounded-md bg-rom-purple/15 px-1.5 py-0.5 text-[11px] font-semibold uppercase text-rom-purple">
                    {r.network || 'mainnet'}
                  </span>
                </td>
                <td className="font-mono text-xs text-rom-muted">
                  {fmtUsd(r.startTotalUsd)} <span className="text-rom-dim">→</span> {fmtUsd(r.endTotalUsd ?? r.startTotalUsd)}
                </td>
                <td className={cls(
                  'font-mono text-xs',
                  r.pnlUsd >= 0 ? 'text-rom-win' : 'text-rom-lossText',
                )}>
                  {fmtUsd(r.pnlUsd, { sign: true })}
                </td>
                <td className="font-mono text-xs">{r.tradesOpened}</td>
                <td className="font-mono text-xs">
                  <span className="text-rom-win">{r.tradesWon}</span>
                  <span className="mx-0.5 text-rom-dim">/</span>
                  <span className="text-rom-lossText">{r.tradesLost}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {runs.length === 0 && (
          <div className="border-t border-rom-border bg-rom-surface2/40 px-5 py-6 text-center text-xs text-rom-muted">
            No bot runs recorded yet. They&apos;ll start showing up once you launch the bot.
          </div>
        )}
      </div>
    </>
  );
}

function RunStandout({
  label, run, accent,
}: {
  label: string;
  run?: BotRun;
  accent: 'good' | 'bad';
}) {
  if (!run) {
    return <div className="text-rom-muted">{label}: —</div>;
  }
  return (
    <div className="rounded-lg border border-rom-border bg-rom-surface2 p-2">
      <div className="text-[11px] uppercase tracking-wider text-rom-muted">{label}</div>
      <div className="mt-1 flex items-baseline justify-between">
        <span className="font-mono text-sm">{shortDate(run.startedAt)}</span>
        <span className={cls(
          'font-mono text-sm',
          accent === 'good' ? 'text-rom-win' : 'text-rom-lossText',
        )}>
          {fmtUsd(run.pnlUsd, { sign: true })}
        </span>
      </div>
      <div className="mt-0.5 text-[11px] text-rom-dim">
        {run.tradesOpened} trades · {run.tradesWon}W/{run.tradesLost}L
      </div>
    </div>
  );
}

function shortDate(iso: string): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${d.getMinutes().toString().padStart(2, '0')}`;
  } catch {
    return iso.slice(0, 16);
  }
}

function TradeHistory({ resolved, account }: {
  resolved: ReturnType<typeof Object>[] | any[];
  account: ReturnType<typeof Object> | null;
}) {
  const byDay = useMemo(() => {
    const map = new Map<string, { day: string; pnl: number; wins: number; losses: number; trades: number }>();
    for (const p of resolved) {
      const d = (p.resolvedAt || p.lastUpdated || '').slice(0, 10);
      if (!d) continue;
      const cur = map.get(d) || { day: d, pnl: 0, wins: 0, losses: 0, trades: 0 };
      cur.pnl += p.pnlUsd ?? 0;
      cur.trades += 1;
      if (p.outcomeCorrect === 1) cur.wins += 1;
      else if (p.outcomeCorrect === 0) cur.losses += 1;
      map.set(d, cur);
    }
    return Array.from(map.values()).sort((a, b) => a.day.localeCompare(b.day));
  }, [resolved]);

  const totals = useMemo(() => {
    const wins = resolved.filter((p: any) => p.outcomeCorrect === 1).length;
    const losses = resolved.filter((p: any) => p.outcomeCorrect === 0).length;
    const realized = resolved.reduce((s: number, p: any) => s + (p.pnlUsd ?? 0), 0);
    const cost = resolved.reduce((s: number, p: any) => s + (p.costUsd ?? 0), 0);
    const wr = wins + losses > 0 ? (wins / (wins + losses)) * 100 : 0;
    return { wins, losses, realized, cost, wr };
  }, [resolved]);

  const bestDay = byDay.reduce((m, d) => (d.pnl > (m?.pnl ?? -Infinity) ? d : m), byDay[0]);
    const worstDay = byDay.reduce((m, d) => (d.pnl < (m?.pnl ?? Infinity) ? d : m), byDay[0]);

    const downloadCsv = (): void => {
      const esc = (v: unknown): string => {
        const s = String(v ?? '');
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      };
      const header = ['resolvedAt', 'source', 'ticker', 'title', 'side', 'costUsd', 'outcome', 'pnlUsd'];
      const rows = resolved.map((p: any) => [
        p.resolvedAt || p.lastUpdated || '',
        esc(p.signalSource),
        esc(p.ticker),
        esc(p.title),
        p.direction,
        p.costUsd ?? '',
        p.outcomeCorrect === 1 ? 'won' : p.outcomeCorrect === 0 ? 'lost' : 'n/a',
        p.pnlUsd ?? '',
      ]);
      const csv = [header, ...rows].map((r) => r.join(',')).join('\n');
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `rom-polybot-trades-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    };

  return (
    <>
      <div className="grid gap-4 md:grid-cols-4">
        <ShareableStat
          label="Total Realized"
          value={fmtUsd(totals.realized, { sign: true })}
          accent={totals.realized >= 0 ? 'good' : 'bad'}
          hint={`${resolved.length} resolved trades`}
          shareText={`My ROM PolyBot history: ${fmtUsd(totals.realized, { sign: true })} `
            + `realized over ${resolved.length} trades · ${fmtPct(totals.wr)} win rate. `
            + `ROM Polybot · Polymarket US`}
        />
        <ShareableStat
          label="Win Rate"
          value={totals.wins + totals.losses > 0 ? fmtPct(totals.wr) : '—'}
          hint={`${totals.wins}W · ${totals.losses}L`}
          accent={totals.wr >= 50 ? 'good' : 'warn'}
          shareText={`ROM PolyBot hit rate: ${fmtPct(totals.wr)} `
            + `(${totals.wins}W / ${totals.losses}L). `
            + `ROM Polybot · Polymarket US`}
        />
        <StatCard
          label="Total Risked"
          value={fmtUsd(totals.cost)}
          hint={`avg ${fmtUsd(resolved.length ? totals.cost / resolved.length : 0)}/trade`}
        />
        <ShareableStat
          label="ROI on Capital"
          value={fmtPct(totals.cost > 0 ? (totals.realized / totals.cost) * 100 : 0)}
          accent={totals.realized >= 0 ? 'good' : 'bad'}
          shareText={`ROM PolyBot ROI on capital: `
            + `${fmtPct(totals.cost > 0 ? (totals.realized / totals.cost) * 100 : 0)} `
            + `over ${resolved.length} trades. `
            + `ROM Polybot · Polymarket US`}
        />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" header={
          <div className="flex items-center justify-between">
            <div className="text-sm text-white">Daily P&amp;L</div>
            <div className="text-xs text-rom-muted">{byDay.length} days</div>
          </div>
        }>
          {byDay.length === 0 ? (
            <Empty title="No history yet" description="Once trades resolve, they'll show here." />
          ) : (
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={byDay}>
                  <XAxis dataKey="day" tick={{ fill: '#71717A', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(v) => `$${v}`} tick={{ fill: '#71717A', fontSize: 11 }} axisLine={false} tickLine={false} width={40} />
                  <Tooltip
                    contentStyle={{ background: '#171722', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8 }}
                    labelStyle={{ color: '#FFFFFF' }}
                    itemStyle={{ color: '#FFFFFF' }}
                    formatter={(v: number) => [fmtUsd(v, { sign: true }), 'P&L']}
                  />
                  <Bar dataKey="pnl">
                    {byDay.map((d) => (
                      <Cell key={d.day} fill={d.pnl >= 0 ? '#22C55E' : '#EF4444'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card>
          <div className="flex items-center gap-2 text-sm text-white">
            <Trophy className="h-4 w-4 text-rom-warn" />
            Standout days
          </div>
          <div className="mt-3 space-y-2 text-xs">
            <Standout label="Best day" day={bestDay} accent="good" />
            <Standout label="Worst day" day={worstDay} accent="bad" />
          </div>
          <div className="mt-4 border-t border-rom-border pt-3">
            <div className="text-[11px] uppercase tracking-wider text-rom-muted">Network</div>
            <div className="mt-2 grid grid-cols-1 gap-2 text-xs">
              <EnvStat env="MAINNET" v={(account as any)?.byNetwork?.mainnet} />
            </div>
          </div>
        </Card>
              </div>

                <div className="mt-6 overflow-hidden rounded-xl border border-rom-border">
                  <div className="flex items-center justify-between border-b border-rom-border px-4 py-2">
                    <div className="text-xs text-rom-muted">All trade history ({resolved.length})</div>
                    <button
                      onClick={downloadCsv}
                      disabled={resolved.length === 0}
                      className="rom-btn-default px-2 py-1 text-xs disabled:opacity-50"
                      title="Download all resolved trades as CSV"
                    >
                      <Download className="h-3.5 w-3.5" /> Export CSV
                    </button>
                  </div>
                  <table className="rom-table">
                    <thead>
                      <tr>
                        <th>Resolved</th>
                        <th>Source</th>
                        <th>Ticker</th>
                        <th>Title</th>
                        <th>Side</th>
                        <th>Cost</th>
                        <th>Outcome</th>
                        <th>P&amp;L</th>
                      </tr>
                    </thead>
          <tbody>
            {resolved.slice(0, 200).map((p: any) => (
              <tr key={p.id}>
                <td className="text-xs text-rom-muted">{fmtDateTime(p.resolvedAt || p.lastUpdated)}</td>
                <td>
                  <span className={cls(
                    'inline-flex rounded-md px-1.5 py-0.5 text-[11px] uppercase',
                    p.signalSource === 'whale'
                      ? 'bg-rom-purple/15 text-rom-purple'
                      : 'bg-rom-pink/15 text-rom-pink',
                  )}>
                    {p.signalSource}
                  </span>
                </td>
                <td><TickerLink ticker={p.ticker} eventTicker={p.eventTicker} env={p.network} /></td>
                <td className="max-w-[260px] truncate text-xs text-rom-muted">{p.title}</td>
                <td>
                  <span className={cls(
                    'rounded-md px-1.5 py-0.5 text-[11px] font-semibold uppercase',
                    p.direction === 'yes' ? 'bg-rom-win/10 text-rom-win' : 'bg-rom-loss/10 text-rom-lossText',
                  )}>
                    {p.direction}
                  </span>
                </td>
                <td className="font-mono text-xs">{fmtUsd(p.costUsd)}</td>
                <td>
                  {p.outcomeCorrect === 1 ? (
                    <span className="rom-pill border-rom-win/40 bg-rom-win/10 text-rom-win">won</span>
                  ) : p.outcomeCorrect === 0 ? (
                    <span className="rom-pill border-rom-loss/40 bg-rom-loss/10 text-rom-lossText">lost</span>
                  ) : (
                    <span className="rom-pill text-rom-muted">n/a</span>
                  )}
                </td>
                <td className={cls(
                  'font-mono text-xs',
                  (p.pnlUsd ?? 0) >= 0 ? 'text-rom-win' : 'text-rom-lossText',
                )}>
                  {fmtUsd(p.pnlUsd, { sign: true })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {resolved.length === 0 && (
          <div className="border-t border-rom-border bg-rom-surface2/40 px-5 py-6 text-center text-xs text-rom-muted">
            No resolved trades yet. Wait for markets to settle.
          </div>
        )}
      </div>
    </>
  );
}

function Standout({
  label, day, accent,
}: {
  label: string;
  day?: { day: string; pnl: number; wins: number; losses: number; trades: number };
  accent: 'good' | 'bad';
}) {
  if (!day) {
    return <div className="text-rom-muted">{label}: —</div>;
  }
  return (
    <div className="rounded-lg border border-rom-border bg-rom-surface2 p-2">
      <div className="text-[11px] uppercase tracking-wider text-rom-muted">{label}</div>
      <div className="mt-1 flex items-baseline justify-between">
        <span className="font-mono text-sm">{day.day}</span>
        <span className={cls(
          'font-mono text-sm',
          accent === 'good' ? 'text-rom-win' : 'text-rom-lossText',
        )}>
          {fmtUsd(day.pnl, { sign: true })}
        </span>
      </div>
      <div className="mt-0.5 text-[11px] text-rom-dim">
        {day.trades} trades · {day.wins}W/{day.losses}L
      </div>
    </div>
  );
}

function EnvStat({ env, v }: { env: string; v?: { wins: number; losses: number; realizedPnl: number } }) {
  const wr = v && (v.wins + v.losses) ? (v.wins / (v.wins + v.losses)) * 100 : 0;
  return (
    <div className="rounded-lg border border-rom-border bg-rom-surface2 p-2">
      <div className="text-[11px] uppercase tracking-wider text-rom-dim">{env}</div>
      <div className={cls(
        'font-mono text-sm',
        (v?.realizedPnl ?? 0) >= 0 ? 'text-rom-win' : 'text-rom-lossText',
      )}>
        {fmtUsd(v?.realizedPnl ?? 0, { sign: true })}
      </div>
      <div className="text-[11px] text-rom-muted">
        {v?.wins ?? 0}W / {v?.losses ?? 0}L · {wr.toFixed(1)}%
      </div>
    </div>
  );
}
