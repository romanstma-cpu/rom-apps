import { useMemo, useState } from 'react';
import { Ban, RefreshCw } from 'lucide-react';
import type { BotPosition } from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Empty, Page } from '../components/common';
import { TickerLink } from '../components/PolymarketTicker';
import { cls, fmtCents, fmtRelative, fmtUsd } from '../utils/format';

const STATUS_COLORS: Record<string, string> = {
  submitted: 'bg-rom-warn/15 text-rom-warn border-rom-warn/30',
  partial: 'bg-rom-warn/15 text-rom-warn border-rom-warn/30',
  filled: 'bg-rom-indigo/15 text-rom-indigo border-rom-indigo/30',
  canceled: 'bg-rom-dim/15 text-rom-muted border-rom-border',
  expired: 'bg-rom-dim/15 text-rom-muted border-rom-border',
  gone: 'bg-rom-dim/15 text-rom-muted border-rom-border',
  error: 'bg-rom-loss/15 text-rom-loss border-rom-loss/30',
  dry_run: 'bg-rom-purple/15 text-rom-purple border-rom-purple/30',
};

type Tab = 'open' | 'pending' | 'practice' | 'won' | 'lost' | 'errors' | 'all';

export function PositionsPage() {
  const { positions, refresh } = useApp();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>('open');
  const [src, setSrc] = useState<'all' | 'whale' | 'momentum'>('all');
  const [busy, setBusy] = useState<string | null>(null);

  const filtered = useMemo(() => {
    return positions.filter((p) => {
      if (src !== 'all' && p.signalSource !== src) return false;
      switch (tab) {
        case 'open':
          return !p.resolved && (p.status === 'filled' || p.status === 'partial');
        case 'pending':
          return !p.resolved && p.status === 'submitted';
        case 'practice':
          return p.status === 'dry_run';
        case 'won':
          return p.status !== 'dry_run' && p.resolved && p.outcomeCorrect === 1;
        case 'lost':
          return p.status !== 'dry_run' && p.resolved && p.outcomeCorrect === 0;
        case 'errors':
          return p.status === 'error';
        case 'all':
        default:
          return true;
      }
    });
  }, [positions, tab, src]);

  const counts = useMemo(() => {
    let open = 0, pending = 0, practice = 0, won = 0, lost = 0, errors = 0;
    for (const p of positions) {
      if (!p.resolved && (p.status === 'filled' || p.status === 'partial')) open++;
      if (!p.resolved && p.status === 'submitted') pending++;
      if (p.status === 'dry_run') practice++;
      if (p.status !== 'dry_run' && p.resolved && p.outcomeCorrect === 1) won++;
      if (p.status !== 'dry_run' && p.resolved && p.outcomeCorrect === 0) lost++;
      if (p.status === 'error') errors++;
    }
    return { open, pending, practice, won, lost, errors, all: positions.length };
  }, [positions]);

  const cancelAll = async (): Promise<void> => {
    if (!window.confirm('Cancel ALL open orders on Polymarket?')) return;
    setBusy('cancel');
    try {
      const r = await window.rom.trading.cancelAllOpen();
      if (r.ok) toast.success(r.message || 'All open orders canceled');
      else toast.error(r.message || 'Failed');
    } finally {
      setBusy(null);
    }
  };

  const syncPositions = async (): Promise<void> => {
    setBusy('sync');
    try {
      const r = await window.rom.backend.runOnce('syncPositions');
      if (r.ok) {
        await refresh.positions();
        toast.success(r.data?.summary || r.message || 'Positions synced');
      } else {
        toast.error(r.message || 'Sync failed');
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <Page
      title="Positions"
      subtitle="Live, recent and practice positions. Practice rows never represent exchange orders."
      actions={
        <div className="flex items-center gap-2">
          <button onClick={syncPositions} disabled={!!busy} className="rom-btn-default">
            <RefreshCw className={cls('h-4 w-4', busy === 'sync' && 'animate-spin')} />
            {busy === 'sync' ? 'Syncing…' : 'Refresh'}
          </button>
          <button onClick={cancelAll} disabled={!!busy} className="rom-btn-danger">
            <Ban className="h-4 w-4" /> Cancel All
          </button>
        </div>
      }
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Tabs value={tab} onChange={setTab}
          options={[
            { value: 'open', label: `Open (${counts.open})` },
            { value: 'pending', label: `Pending (${counts.pending})` },
            { value: 'practice', label: `Practice (${counts.practice})` },
            { value: 'won', label: `Won (${counts.won})` },
            { value: 'lost', label: `Lost (${counts.lost})` },
            { value: 'errors', label: `Errors (${counts.errors})` },
            { value: 'all', label: `All (${counts.all})` },
          ]}
        />
        <div className="ml-auto flex gap-1">
          <Tabs value={src} onChange={setSrc}
            options={[
              { value: 'all', label: 'Both' },
              { value: 'whale', label: 'Whales' },
              { value: 'momentum', label: 'Momentum' },
            ]}
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <Empty
          title="No positions match"
          description="Switch tabs or wait for the trader to open something."
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-rom-border">
          <table className="rom-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Source</th>
                <th>Ticker</th>
                <th>Title</th>
                <th>Side</th>
                <th>Filled</th>
                <th>Cost</th>
                <th>Status</th>
                <th>Outcome</th>
                <th>Edge</th>
                <th>P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => <PositionRow key={p.id} p={p} />)}
            </tbody>
          </table>
        </div>
      )}
    </Page>
  );
}

function Tabs<T extends string>({
  value, onChange, options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div className="inline-flex rounded-md border border-rom-border bg-rom-surface2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cls(
            'rounded-[6px] px-3 py-1.5 text-xs font-medium transition-colors',
            value === o.value
              ? 'bg-white/10 text-white'
              : 'text-rom-muted hover:text-white',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function PositionRow({ p }: { p: BotPosition }) {
  const realized = p.resolved;
  const pnl = realized ? p.pnlUsd : p.livePnlUsd;
  return (
    <tr>
      <td className="text-xs text-rom-muted">{fmtRelative(p.createdAt)}</td>
      <td>
        <span
          className={cls(
            'inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] uppercase',
            p.signalSource === 'whale'
              ? 'bg-rom-purple/15 text-rom-purple'
              : p.signalSource === 'copy'
                ? 'bg-rom-indigo/15 text-rom-indigo'
                : p.signalSource === 'external'
                  ? 'bg-rom-dim/15 text-rom-muted'
                  : 'bg-rom-pink/15 text-rom-pink',
          )}
        >
          {p.signalSource}
        </span>
      </td>
      <td><TickerLink ticker={p.ticker} eventTicker={p.eventTicker} env={p.network} /></td>
      <td className="max-w-[280px] truncate text-xs text-rom-muted">{p.title}</td>
      <td>
        <span
          className={cls(
            'rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase',
            p.direction === 'yes'
              ? 'bg-rom-win/10 text-rom-win'
              : 'bg-rom-loss/10 text-rom-loss',
          )}
        >
          {p.direction}
        </span>
      </td>
      <td className="font-mono text-xs">
        {p.filledContracts}/{p.targetContracts}
        <span className="ml-2 text-rom-dim">
          @ {fmtCents(p.avgFillPriceCents ?? p.limitPriceCents)}
        </span>
      </td>
      <td className="font-mono text-xs">{fmtUsd(p.costUsd)}</td>
      <td>
        <span
          className={cls(
            'inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium uppercase',
            STATUS_COLORS[p.status] ?? 'border-rom-border bg-rom-surface2 text-rom-muted',
          )}
        >
          {p.status}
        </span>
      </td>
      <td>
        {!p.resolved ? (
          <span className="text-[10px] uppercase tracking-wider text-rom-dim">{p.status === 'dry_run' ? 'practice' : 'live'}</span>
        ) : p.outcomeCorrect === 1 ? (
          <span className="rom-pill border-rom-win/40 bg-rom-win/10 text-rom-win">won</span>
        ) : p.outcomeCorrect === 0 ? (
          <span className="rom-pill border-rom-loss/40 bg-rom-loss/10 text-rom-loss">lost</span>
        ) : (
          <span className="rom-pill text-rom-muted">closed</span>
        )}
      </td>
      <td className="font-mono text-xs text-rom-purple">
        {p.signalSource === 'external'
          ? <span className="text-rom-dim" title="Imported from your Polymarket US API — no entry signal">—</span>
          : `+${p.edgePts.toFixed(1)}`}
      </td>
      <td
        className={cls(
          'font-mono text-xs',
          pnl == null ? 'text-rom-dim' : pnl >= 0 ? 'text-rom-win' : 'text-rom-loss',
        )}
      >
        {pnl == null ? (
          '—'
        ) : (
          <span title={
            realized
              ? 'Realized P&L'
              : `Unrealized P&L at ${p.markPriceCents != null ? `${Math.round(p.markPriceCents)}¢` : 'current price'}`
          }>
            {fmtUsd(pnl, { sign: true })}
            {!realized && (
              <span className="ml-1 text-[10px] uppercase tracking-wide text-rom-dim">live</span>
            )}
          </span>
        )}
      </td>
    </tr>
  );
}
