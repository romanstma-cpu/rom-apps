import { useEffect, useRef, useState } from 'react';
import { Bitcoin, FolderPlus, RefreshCw, RotateCcw, SlidersHorizontal, Wallet, Zap } from 'lucide-react';
import { C15_PRESET_CORE } from '@shared/c15Presets';
import type {
  Crypto15mAsset, Crypto15mPosition,
  Crypto15mSizing, Crypto15mSnapshot, Crypto15mStatus, RuleCondition, TraderConfig,
} from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Empty, NameDialog, Page, RuleBuilder, Switch } from '../components/common';
import { TickerLink } from '../components/PolymarketTicker';
import { BacktestPanel } from '../components/BacktestPanel';
import { cls, fmtUsd } from '../utils/format';

const POLL_MS = 2500;

let cachedSnap: Crypto15mSnapshot | null = null;
let cachedStatus: Crypto15mStatus | null = null;

function fmtSpot(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const dp = v >= 100 ? 2 : v >= 1 ? 4 : 6;
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: dp })}`;
}

function fmtDelta(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const dp = v >= 100 ? 2 : v >= 1 ? 3 : 5;
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: dp })}`;
}

function fmtMins(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${v.toFixed(1)}m`;
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${Math.round(v * 100)}%`;
}

export function Crypto15mPage() {
  const { config } = useApp();
  const [snap, setSnap] = useState<Crypto15mSnapshot | null>(cachedSnap);
  const [status, setStatus] = useState<Crypto15mStatus | null>(cachedStatus);
  const [loading, setLoading] = useState(cachedSnap === null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  const inFlight = useRef(false);

  async function load() {
    const api = window.rom?.crypto15m;
    if (!api) {
      setErr('15m crypto API unavailable (restart the app after this update).');
      setLoading(false);
      return;
    }
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const [s, st] = await Promise.all([api.snapshot(), api.status()]);
      cachedSnap = s;
      cachedStatus = st;
      setSnap(s);
      setStatus(st);
      setErr(null);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    timer.current = window.setInterval(() => void load(), POLL_MS) as unknown as number;
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  async function patchAndReload(patch: Partial<TraderConfig>) {
    setBusy(true);
    try {
      await window.rom.config.update(patch);
      await load();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggleEnabled(next: boolean) {
    if (next && !window.confirm(
      'Enable the 15-minute crypto executor?\n\nIt will place REAL orders with your '
      + 'Polymarket balance whenever your wallet is connected. This runs independently '
      + 'of the main bot. There is no paper mode.',
    )) return;
    await patchAndReload({ crypto15mEnabled: next });
  }

  const [uiMode, setUiMode] = useState<'simple' | 'advanced'>(
    () => (localStorage.getItem('c15UiMode') === 'advanced' ? 'advanced' : 'simple'),
  );
  const setMode = (m: 'simple' | 'advanced') => {
    setUiMode(m);
    localStorage.setItem('c15UiMode', m);
  };

  const live = snap?.assets.filter((a) => a.signal).length ?? 0;
  const enabled = !!config?.crypto15mEnabled;
  const authed = !!status?.authed;
  const trading = !!status?.trading;
  const mode: 'OFF' | 'LIVE' | 'WAITING' = !enabled ? 'OFF' : (trading ? 'LIVE' : 'WAITING');
  const openPos = status?.open ?? [];
  const recentPos = (status?.recent ?? []).filter((p) => p.resolved);

  return (
    <Page
      title="15m Crypto"
      subtitle="Polymarket 15-minute crypto markets. A configurable momentum strategy — tune the entry window, favorite threshold, delta filter, and stop-loss below."
      actions={
        <>
          <div className="inline-flex overflow-hidden rounded-md border border-rom-border">
            {(['simple', 'advanced'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                title={m === 'simple'
                  ? 'Presets and the essential money knobs only'
                  : 'Every setting the engine has'}
                className={cls(
                  'px-3 py-1.5 text-xs capitalize transition-colors',
                  uiMode === m
                    ? 'bg-rom-glow text-white'
                    : 'bg-rom-surface2 text-rom-muted hover:text-white',
                )}
              >
                {m}
              </button>
            ))}
          </div>
          <button
            onClick={() => void load()}
            className="inline-flex items-center gap-2 rounded-md border border-rom-border bg-rom-surface2 px-3 py-1.5 text-xs text-rom-muted transition-colors hover:border-rom-purple/40 hover:text-white"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </>
      }
    >
      <div className="mb-4 rounded-xl border border-rom-border bg-rom-surface p-3">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <div className="min-w-[260px] flex-1">
            <Switch
              checked={enabled}
              disabled={busy}
              onChange={(v) => void toggleEnabled(v)}
              label="Enable 15-minute crypto executor"
              description={
                mode === 'LIVE'
                  ? 'LIVE — placing real orders on your Polymarket account.'
                  : mode === 'WAITING'
                    ? 'Enabled — will trade once your wallet is connected.'
                    : 'Off — monitor only.'
              }
            />
          </div>
          <ModePill mode={mode} />
          <div className="flex items-center gap-4 text-xs">
            <KV label="Size" value={`${status?.orderSize ?? 1}c`} />
            <KV label="Max open" value={`${status?.maxConcurrent ?? 7}`} />
            <KV label="Open" value={`${status?.stats.openCount ?? 0}`} />
            <KV label="W / L" value={`${status?.stats.wins ?? 0} / ${status?.stats.losses ?? 0}`} />
          </div>
        </div>
        {status && enabled && !authed && (
          <div className="mt-2 text-[11px] text-rom-warn">
            Enabled, but Polymarket isn't connected — connect your wallet on the
            <span className="text-rom-muted"> Wallet</span> page to start trading.
          </div>
        )}
        {enabled && status?.modelCalibration && !status.modelCalibration.ok && (
          <div className="mt-2 rounded-lg border border-rom-loss/40 bg-rom-loss/10 px-3 py-2 text-[11px] leading-relaxed text-rom-lossText">
            ⛔ <span className="font-semibold">Model calibration degraded</span> — high-confidence
            calls hit {Math.round((status.modelCalibration.rate ?? 0) * 100)}% over the last{' '}
            {status.modelCalibration.n} windows, and the statistical floor on that record
            ({Math.round((status.modelCalibration.lb ?? 0) * 100)}%) is below the bar the sniper
            needs to stay armed. Model entries are auto-paused and resume as newer windows
            restore calibration.
          </div>
        )}
        {enabled && (status?.byStrategy?.length ?? 0) > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {status!.byStrategy!.map((st) => (
              <span key={st.strategy} className="rounded bg-rom-surface2 px-1.5 py-0.5 font-mono text-[11px] text-rom-dim" title={st.fees_usd > 0 ? `fees $${st.fees_usd.toFixed(2)}` : undefined}>
                {st.strategy} {st.wins}/{st.n}{' '}
                <span className={st.pnl_usd >= 0 ? 'text-rom-win' : 'text-rom-lossText'}>
                  {st.pnl_usd >= 0 ? '+' : ''}${st.pnl_usd.toFixed(2)}
                </span>
              </span>
            ))}
          </div>
        )}
      </div>

      {status?.haltReason && (
        <div className="mb-4 rounded-lg border border-rom-warn/50 bg-rom-warn/10 px-3 py-2 text-xs text-rom-warn">
          <span className="font-semibold">Engine paused by circuit-breaker: </span>
          {status.haltReason}
        </div>
      )}

      <StrategySettings
        config={config}
        liveSignals={live}
        spotSource={snap?.spotSource ?? 'cryptocompare'}
        spotOk={snap?.spotOk ?? true}
        hoursOk={snap?.hoursOk ?? true}
        sizing={status?.sizing ?? null}
        uiMode={uiMode}
      />

      {uiMode === 'advanced' && <Crypto15mRules config={config} />}

      {uiMode === 'advanced' && <BacktestPanel />}

      {err && (
        <div className="mb-4 rounded-lg border border-rom-loss/40 bg-rom-loss/10 px-3 py-2 text-xs text-rom-lossText">
          {err}
        </div>
      )}

      <MarketControls config={config} busy={busy} onPatch={patchAndReload} />

      {snap && snap.assets.length > 0
        && snap.assets.every((a) => !a.hasMarket)
        && snap.assets.some((a) => /unreachable|blocked|region/i.test(a.error || '')) && (
        <div className="mb-4 rounded-lg border border-rom-warn/40 bg-rom-warn/10 px-3 py-2 text-xs text-rom-warn">
          <strong>Polymarket market data is unreachable.</strong> Spot prices come from a
          different source (so they still show), but the markets load from Polymarket's API,
          which may be unavailable in your region. Your wallet and funds are unaffected.
        </div>
      )}

      {!snap && loading ? (
        <Empty title="Loading 15-minute crypto markets…" description="Fetching Polymarket markets and spot prices." />
      ) : snap && snap.assets.length === 0 ? (
        <Empty title="No data" description="Could not load any 15-minute crypto series." />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {snap?.assets.map((a) => <AssetCard key={a.series} a={a} />)}
        </div>
      )}

      {(openPos.length > 0 || recentPos.length > 0) && (
        <div className="mt-6 space-y-4">
          {openPos.length > 0 && <PositionsTable title="Open positions" rows={openPos} />}
          {recentPos.length > 0 && <PositionsTable title="Recent (resolved)" rows={recentPos.slice(0, 20)} />}
        </div>
      )}
    </Page>
  );
}

const C15_INTERVALS: Array<{ id: '5m' | '15m' | 'hourly'; label: string }> = [
  { id: '5m', label: '5 min' },
  { id: '15m', label: '15 min' },
  { id: 'hourly', label: '1 hour' },
];
const C15_ALL_ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'HYPE', 'BNB'];

function MarketControls({
  config, busy, onPatch,
}: {
  config?: TraderConfig | null;
  busy: boolean;
  onPatch: (p: Partial<TraderConfig>) => Promise<void> | void;
}) {
  const interval = config?.crypto15mInterval ?? '15m';
  const enabledAssets = config?.crypto15mAssets ?? C15_ALL_ASSETS;
  const toggleAsset = (s: string) => {
    const cur = config?.crypto15mAssets ?? [...C15_ALL_ASSETS];
    const next = cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s];
    void onPatch({ crypto15mAssets: next });
  };
  return (
    <div className="mb-4 flex flex-col gap-3 rounded-xl border border-rom-border bg-rom-surface p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2">
        <span className="text-[11px] uppercase tracking-wider text-rom-dim">Window</span>
        <div className="inline-flex overflow-hidden rounded-lg border border-rom-border">
          {C15_INTERVALS.map((iv) => (
            <button
              key={iv.id}
              disabled={busy}
              onClick={() => void onPatch({ crypto15mInterval: iv.id })}
              className={cls(
                'px-3 py-1 text-xs transition-colors',
                interval === iv.id
                  ? 'bg-rom-glow text-white'
                  : 'bg-rom-surface2 text-rom-muted hover:text-white',
              )}
            >
              {iv.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[11px] uppercase tracking-wider text-rom-dim">Trade</span>
        {C15_ALL_ASSETS.map((s) => (
          <button
            key={s}
            disabled={busy}
            onClick={() => toggleAsset(s)}
            className={cls(
              'rounded-md border px-2 py-0.5 text-[11px] font-semibold transition-colors',
              enabledAssets.includes(s)
                ? 'border-rom-purple/40 bg-rom-purple/10 text-white'
                : 'border-rom-border bg-rom-surface2 text-rom-dim line-through',
            )}
            title={enabledAssets.includes(s) ? `Trading ${s} — click to disable` : `${s} disabled — click to enable`}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

const C15_RULE_FIELDS = [
  { key: 'favoritePrice', label: 'Favorite price (0–1)', dflt: 0.9 },
  { key: 'entryCost', label: 'Entry cost (0–1)', dflt: 0.9 },
  { key: 'upProb', label: 'Up probability (0–1)', dflt: 0.5 },
  { key: 'bookImbalance', label: 'Order-flow imbalance (−1…1)', dflt: 0.3 },
  { key: 'arbEdgeCents', label: 'Arb edge (¢)', dflt: 2 },
  { key: 'deltaPct', label: 'Underlying move % / vol (0–1)', dflt: 0.0 },
  { key: 'minsLeft', label: 'Minutes to close', dflt: 8 },
  { key: 'hourUtc', label: 'Hour of day (UTC, 0–23)', dflt: 13 },
  { key: 'peersAgree', label: 'Peer agreement (0–1)', dflt: 0.6 },
  { key: 'marketBias', label: 'Market up-bias (−1…1)', dflt: 0.0 },
  { key: 'macd', label: 'MACD line (underlying, scales w/ price)', dflt: 0.0 },
  { key: 'macdSignal', label: 'MACD signal line (underlying)', dflt: 0.0 },
  { key: 'macdHist', label: 'MACD histogram (underlying)', dflt: 0.0 },
  { key: 'macdCross', label: 'MACD cross (+1 up / −1 down)', dflt: 1 },
  { key: 'rsi', label: 'RSI (underlying, 0–100)', dflt: 70 },
  { key: 'deltaSignedPct', label: 'Signed move from open (fraction)', dflt: 0.0 },
  { key: 'upAsk', label: 'Up token ask (0–1)', dflt: 0.9 },
  { key: 'downAsk', label: 'Down token ask (0–1)', dflt: 0.9 },
  { key: 'sigma1m', label: '1-min realized vol (fraction)', dflt: 0.001 },
  { key: 'modelProb', label: 'Model P(up) (0–1)', dflt: 0.97 },
  { key: 'edgeNetCents', label: 'Model net edge (¢)', dflt: 2 },
];

const C15_EXAMPLE_STRATEGIES: {
  id: string; name: string; blurb: string; rules: RuleCondition[];
}[] = [
  {
    id: 'macd-up-momentum',
    name: 'MACD up-momentum (longs)',
    blurb:
      'Enter Up only when Up is favored (upProb ≥ 0.55) and the underlying’s 1-min MACD is bullish (histogram > 0), in the last 6 minutes. A trend-confirmation long. Best on the 15-min window (on 5-min, “≤6 min” covers the whole window — lower it). Use with Direction = favorite; lower Favorite≥ so the rule, not the floor, drives.',
    rules: [
      { field: 'upProb', op: '>=', value: 0.55 },
      { field: 'macdHist', op: '>', value: 0 },
      { field: 'minsLeft', op: '<=', value: 6 },
    ],
  },
  {
    id: 'fav-not-overbought',
    name: 'Strong favorite, not overbought',
    blurb:
      'Buy strong favorites (≥ 0.92) but skip when the underlying RSI is extended (≥ 78) — a crude exhaustion filter to avoid chasing a stretched move into settlement.',
    rules: [
      { field: 'favoritePrice', op: '>=', value: 0.92 },
      { field: 'rsi', op: '<=', value: 78 },
    ],
  },
];

function Crypto15mRules({ config }: { config?: TraderConfig | null }) {
  const [loading, setLoading] = useState<string | null>(null);
  const loadExample = async (ex: typeof C15_EXAMPLE_STRATEGIES[number]) => {
    setLoading(ex.id);
    try {
      await window.rom.config.update({ crypto15mUseRules: true, crypto15mRules: ex.rules });
    } finally {
      setLoading(null);
    }
  };
  return (
    <div className="mb-4">
      <div className="mb-3 rounded-lg border border-rom-border bg-rom-surface2/40 p-3">
        <div className="mb-1 text-[11px] font-bold uppercase tracking-wider text-rom-muted">
          Example strategies — learning templates
        </div>
        <p className="mb-2 text-xs text-rom-dim">
          One-click rule-sets that show how to wire the underlying MACD/RSI signals into an entry.
          These are <span className="font-semibold text-rom-warn">illustrations, not proven edges</span> —
          nothing here is backtested. Load one, watch it on the cards, then run the 15m backtest
          (<span className="font-mono">python backtest.py</span>) before trusting it with money.
        </p>
        <div className="flex flex-col gap-2">
          {C15_EXAMPLE_STRATEGIES.map((ex) => (
            <div key={ex.id} className="flex items-start justify-between gap-3 rounded-md border border-rom-border bg-rom-surface px-3 py-2">
              <div>
                <div className="text-sm font-semibold text-white">{ex.name}</div>
                <div className="text-xs text-rom-dim">{ex.blurb}</div>
              </div>
              <button
                onClick={() => void loadExample(ex)}
                disabled={loading === ex.id}
                className="shrink-0 rounded-md border border-rom-accent/50 bg-rom-accent/10 px-3 py-1 text-xs font-semibold text-rom-accent hover:bg-rom-accent/20 disabled:opacity-50"
              >
                {loading === ex.id ? 'Loading…' : 'Load'}
              </button>
            </div>
          ))}
        </div>
      </div>
      <RuleBuilder
        config={config}
        fields={C15_RULE_FIELDS}
        useRulesKey="crypto15mUseRules"
        rulesKey="crypto15mRules"
        label="Custom entry rules (advanced)"
        description="Compose your own entry from any signal — every condition must pass (AND). Replaces the favorite/threshold gate; the side bought still follows Direction mode."
        tip={
          <>Tip: <span className="font-mono">Hour of day</span> gates by UTC time (e.g. ≥13 and &lt;21
          for the US session); <span className="font-mono">Peer agreement ≥ 0.6</span> trades only when
          the other coins lean the same way (momentum), <span className="font-mono">≤ 0.3</span> only when
          this one diverges; <span className="font-mono">MACD histogram &gt; 0</span> = bullish underlying
          momentum, <span className="font-mono">RSI</span> flags overbought/oversold.</>
        }
      />
    </div>
  );
}

function ModePill({ mode }: { mode: 'OFF' | 'WAITING' | 'LIVE' }) {
  const sty =
    mode === 'LIVE'
      ? 'border-rom-loss/50 bg-rom-loss/15 text-rom-lossText'
      : mode === 'WAITING'
        ? 'border-rom-warn/50 bg-rom-warn/15 text-rom-warn'
        : 'border-rom-border bg-rom-surface2 text-rom-muted';
  return (
    <span className={cls('rounded-full border px-3 py-1 text-[11px] font-bold uppercase tracking-wider', sty)}>
      {mode}
    </span>
  );
}

function KV({ label, value, accent }: { label: string; value: string; accent?: 'good' | 'bad' }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-rom-dim">
      {label}
      <span className={cls('font-mono', accent === 'good' ? 'text-rom-win' : accent === 'bad' ? 'text-rom-lossText' : 'text-white')}>
        {value}
      </span>
    </span>
  );
}

const C15_DEFAULTS = {
  directionMode: 'favorite' as 'favorite' | 'contrarian',
  timeDelayMin: 8,
  entryThreshold: 0.95,
  entryMax: 0.98,
  exitThreshold: 0.4,
  takeProfit: 0,
  stopLossPct: 0,
  takeProfitPct: 0,
  takeProfitTotal: 0,
  minRsi: 0,
  minMacdHist: 0,
  minDeltaPct: 0,
  entryDiff: 0.02,
  entryStyle: 'maker' as 'maker' | 'taker',
  makerCancelMin: 1,
  hoursStartUtc: 0,
  hoursEndUtc: 24,
  orderSize: 5,
  maxConcurrent: 7,
};

const MIN_CONTRACTS = 5;

const C15_PRESETS: { id: string; name: string; hint: string; patch: Partial<TraderConfig> }[] = [
  {
    id: 'sniper', name: 'Settlement Sniper',
    hint: 'The validated config: only strike in the FINAL 2 MINUTES when the live-spot model is ≥99.85% sure (≈3σ) and the lagging book still leaves ≥2¢ of fee-net edge. Real-book replay: +3.2¢/contract, 91% win rate (n=151, Jul 3–5). Raising "Model certainty" back down (e.g. 0.5) turns this into early-window model-following, which measured NEGATIVE (−1.4¢/ct) — don\'t.',
    patch: {
      ...C15_PRESET_CORE.sniper,

      crypto15mModelMinProb: 0.9985, crypto15mTimeDelayMin: 2, crypto15mEntryMax: 0.99,

      crypto15mPairedMode: false, crypto15mIndicatorDetect: true,
      crypto15mSpotWs: true, crypto15mRtdsWs: true,
      crypto15mEntryStyle: 'taker', crypto15mExitThreshold: 0,
    },
  },
  {
    id: 'sniper-5m', name: '5m Sniper (BTC)',
    hint: 'Switches the engine to the 5-MINUTE BTC series (recording follows). Modeled on a verified profitable public bot (PRR "BTC5MScour", +$26.5k over 27 days, 95.8% win): in the final 2 minutes, when spot has moved ≥0.05% off the open, buy the 90–99¢ favorite and hold to settlement — never touch the 40–90¢ band (it measured −5.5% ROI even for that bot). NOT validated in this app: the identical trade measured ZERO edge on the 15m series, and that bot wins on sub-second execution. Let the recorder collect several days of 5m data and backtest it here BEFORE arming.',
    patch: {
      ...C15_PRESET_CORE['sniper-5m'],

      crypto15mExitThreshold: 0, crypto15mStopLossPct: 0, crypto15mTakeProfit: 0,
      crypto15mEntryStyle: 'taker', crypto15mTakerFak: true,
      crypto15mSpotWs: true, crypto15mRtdsWs: true,
    },
  },
  {
    id: 'paired', name: 'Paired + Tilt',
    hint: 'Experimental both-sides + model tilt. The combined-cost cap is 100¢: at 100¢ it catches the at-the-money cluster (up≈down≈50¢) that is the bulk of the fills; the 99¢ cap excludes it. Buying both sides only caps the loss at tilt=1x — at 2x/3x the extra contracts on the tilted side make this a DIRECTIONAL bet that can lose a substantial fraction of the stake if that side loses. Any backtest figures are in-sample over a very short panel (well below a meaningful sample) and are not evidence of a live edge — validate on the Backtest page before arming, and arm small. Do NOT raise the cap above 100 — a >$1 pair pays less than it costs.',
    patch: {
      ...C15_PRESET_CORE.paired,

      crypto15mIndicatorDetect: true, crypto15mSpotWs: true, crypto15mRtdsWs: true,
      crypto15mEntryStyle: 'taker', crypto15mExitThreshold: 0,
      crypto15mOrderSize: 5, crypto15mSizingMode: 'fixed',
    },
  },
  {
    id: 'favorite', name: 'Deep Favorite',
    hint: 'Buy 95–98¢ favorites, hold to settle. Real-book replay: about −0.7¢/contract after fees (96% win rate doesn\'t clear the fee at these prices). Kept as a baseline to experiment against, not a recommendation.',

    patch: { ...C15_PRESET_CORE.favorite, crypto15mPairedMode: false, crypto15mExitThreshold: 0.4, crypto15mEntryStyle: 'taker' },
  },

  {
    id: 'fav-90-95', name: 'Favorite 90–95¢',
    hint: 'Was the strongest pocket on Gamma-mid pricing (~99% win in-sample), but on REAL-book fills it measured −0.5¢/contract — the mid was phantom. Kept for comparison; validate before arming.',
    patch: { crypto15mInterval: '15m', crypto15mPairedMode: false, crypto15mDirectionMode: 'favorite', crypto15mEntryThreshold: 0.90, crypto15mEntryMax: 0.95, crypto15mExitThreshold: 0.4, crypto15mEntryStyle: 'taker', crypto15mUseRules: false },
  },
];

function StrategySettings({
  config, liveSignals, spotSource, spotOk, hoursOk, sizing, uiMode,
}: {
  config: TraderConfig | null;
  liveSignals: number;
  spotSource: string;
  spotOk: boolean;
  hoursOk: boolean;
  sizing: Crypto15mSizing | null;
  uiMode: 'simple' | 'advanced';
}) {
  const sizingMode = config?.crypto15mSizingMode ?? 'fixed';
  const [savingPreset, setSavingPreset] = useState<string | null>(null);
  const [saveProfileOpen, setSaveProfileOpen] = useState(false);
  const toast = useToast();
  const update = async (patch: Partial<TraderConfig>) => {
    try { await window.rom.config.update(patch); } catch {}
  };
  const saveProfile = async (name: string): Promise<void> => {
    setSaveProfileOpen(false);
    const r = await window.rom.profiles.save(name, undefined, 'crypto');
    if (r.ok) toast.success(r.message || 'Saved crypto profile');
    else toast.error(r.message || 'Failed to save profile');
  };
  const num = (k: keyof TraderConfig, d: number) => {
    const v = config?.[k] as number | undefined;
    return typeof v === 'number' && !Number.isNaN(v) ? v : d;
  };
  const dir = (config?.crypto15mDirectionMode ?? C15_DEFAULTS.directionMode);
  const entryStyle = (config?.crypto15mEntryStyle ?? C15_DEFAULTS.entryStyle);

  const applyPreset = async (p: typeof C15_PRESETS[number]) => {
    setSavingPreset(p.id);
    try { await window.rom.config.update(p.patch); } finally { setSavingPreset(null); }
  };

  const resetDefaults = () => void update({
    crypto15mDirectionMode: C15_DEFAULTS.directionMode,
    crypto15mTimeDelayMin: C15_DEFAULTS.timeDelayMin,
    crypto15mEntryThreshold: C15_DEFAULTS.entryThreshold,
    crypto15mEntryMax: C15_DEFAULTS.entryMax,
    crypto15mExitThreshold: C15_DEFAULTS.exitThreshold,
    crypto15mStopLossPct: C15_DEFAULTS.stopLossPct,
    crypto15mMinRsi: C15_DEFAULTS.minRsi,
    crypto15mMinMacdHist: C15_DEFAULTS.minMacdHist,
    crypto15mMinDeltaPct: C15_DEFAULTS.minDeltaPct,
    crypto15mEntryDiff: C15_DEFAULTS.entryDiff,
    crypto15mEntryStyle: C15_DEFAULTS.entryStyle,
    crypto15mMakerCancelMin: C15_DEFAULTS.makerCancelMin,
    crypto15mHoursStartUtc: C15_DEFAULTS.hoursStartUtc,
    crypto15mHoursEndUtc: C15_DEFAULTS.hoursEndUtc,
  });

  return (
    <div className="mb-4 rounded-xl border border-rom-border bg-rom-surface p-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-rom-muted">
          <SlidersHorizontal className="h-3.5 w-3.5" /> Strategy settings
        </span>
        <span className="text-[11px] text-rom-dim">changes apply live</span>
        <div className="ml-auto flex items-center gap-3">
          {liveSignals > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-rom-win/10 px-2 py-0.5 text-[11px] font-semibold text-rom-win">
              <Zap className="h-3 w-3" /> {liveSignals} live signal{liveSignals === 1 ? '' : 's'}
            </span>
          )}
          {!hoursOk && (
            <span className="inline-flex items-center gap-1 rounded-full bg-rom-warn/10 px-2 py-0.5 text-[11px] font-semibold text-rom-warn">
              outside trading hours
            </span>
          )}
          <span className={cls('inline-flex items-center gap-1.5 text-[11px]', spotOk ? 'text-rom-muted' : 'text-rom-warn')}>
            <span className={cls('h-1.5 w-1.5 rounded-full', spotOk ? 'bg-rom-win' : 'bg-rom-warn')} />
            spot: {spotSource}{spotOk ? '' : ' (down)'}
          </span>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        {C15_PRESETS.map((p) => (
          <button
            key={p.id}
            onClick={() => void applyPreset(p)}
            disabled={savingPreset !== null}
            title={p.hint}
            className="rounded-md border border-rom-border bg-rom-surface2 px-2.5 py-1 text-[11px] text-rom-muted transition-colors hover:border-rom-purple/40 hover:text-white disabled:opacity-50"
          >
            {p.name}
          </button>
        ))}
        <button
          onClick={() => setSaveProfileOpen(true)}
          title="Save these crypto settings as a profile (Profiles → Crypto market)"
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-rom-border bg-rom-surface2 px-2.5 py-1 text-[11px] text-rom-muted transition-colors hover:border-rom-purple/40 hover:text-white"
        >
          <FolderPlus className="h-3 w-3" /> Save as profile
        </button>
        <button
          onClick={resetDefaults}
          className="inline-flex items-center gap-1 rounded-md border border-rom-border bg-rom-surface2 px-2.5 py-1 text-[11px] text-rom-dim transition-colors hover:border-rom-warn/40 hover:text-rom-warn"
        >
          <RotateCcw className="h-3 w-3" /> Reset
        </button>
      </div>

      <NameDialog
        open={saveProfileOpen}
        title="Save crypto profile"
        label="Saves your current 15m-crypto settings as a profile (find it under Profiles → Crypto market)."
        placeholder="Profile name"
        confirmLabel="Save"
        onSubmit={(name) => void saveProfile(name)}
        onClose={() => setSaveProfileOpen(false)}
      />

      {config?.crypto15mUseRules && (
        <div className="mb-3 rounded-lg border border-rom-warn/40 bg-rom-warn/10 px-3 py-2 text-[11px] leading-relaxed text-rom-warn">
          <span className="font-semibold">Custom entry rules are ON</span> — the conditions in
          “Custom entry rules (advanced)” decide entry. The <span className="font-mono">Entry window</span> and
          {' '}<span className="font-mono">Min move Δ</span> here are <span className="font-semibold">ignored</span>;
          {' '}<span className="font-mono">Favorite≥</span> and <span className="font-mono">Skip above</span> still apply
          as a safety floor/cap.
          <button
            onClick={() => void update({ crypto15mUseRules: false })}
            className="ml-1.5 rounded border border-rom-warn/50 px-1.5 py-0.5 font-semibold underline-offset-2 transition-colors hover:bg-rom-warn/20"
          >
            Turn rules off
          </button>
          {' '}to trade by these knobs instead.
        </div>
      )}

      {uiMode === 'simple' && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            <SelectField
              label="Direction" value={dir}
              options={[['favorite', 'Favorite-follow'], ['contrarian', 'Contrarian fade'], ['model', 'Model — settlement sniper']]}
              hint="Buy the favorite, fade it, or let the spot-vs-open model call the side (needs Detect MACD/RSI + live spot feed on)."
              onCommit={(v) => void update({ crypto15mDirectionMode: v as 'favorite' | 'contrarian' | 'model' })}
            />
            <NumField
              label="Entry window" suffix="min" min={1} max={15} step={1}
              value={num('crypto15mTimeDelayMin', C15_DEFAULTS.timeDelayMin)}
              hint="Only act inside the last N minutes of the 15-min quarter."
              onCommit={(v) => void update({ crypto15mTimeDelayMin: v })}
            />
            <NumField
              label="Favorite ≥" suffix="¢" min={1} max={99} step={1}
              value={Math.round(num('crypto15mEntryThreshold', C15_DEFAULTS.entryThreshold) * 100)}
              hint="The favorite side must be at least this likely to enter."
              onCommit={(v) => void update({ crypto15mEntryThreshold: v / 100 })}
            />
            <NumField
              label="Skip above" suffix="¢" min={1} max={99} step={1}
              value={Math.round(num('crypto15mEntryMax', C15_DEFAULTS.entryMax) * 100)}
              hint="Don't pay more than this — too little room left to profit."
              onCommit={(v) => void update({ crypto15mEntryMax: v / 100 })}
            />
            <NumField
              label="Stop-loss" suffix="¢" min={0} max={99} step={1}
              value={Math.round(num('crypto15mExitThreshold', C15_DEFAULTS.exitThreshold) * 100)}
              hint="Executor sells if the held side falls to this price. 0 = hold to settlement."
              onCommit={(v) => void update({ crypto15mExitThreshold: v / 100 })}
            />
            <SelectField
              label="Bet size by" value={sizingMode}
              options={[['fixed', 'Fixed contracts'], ['balance_pct', '% of balance']]}
              hint="Buy a fixed number of contracts, or spend a % of your balance each bet."
              onCommit={(v) => void update({ crypto15mSizingMode: v as 'fixed' | 'balance_pct' })}
            />
            {sizingMode === 'balance_pct' ? (
              <NumField
                label="Per bet" suffix="% bal" min={0.1} max={100} step={0.1}
                value={+(num('crypto15mBalancePct', 0.02) * 100).toFixed(2)}
                hint="Spend this % of your balance on each entry."
                onCommit={(v) => void update({ crypto15mBalancePct: v / 100 })}
              />
            ) : (
              <NumField
                label="Bet size" suffix="ct" min={MIN_CONTRACTS} max={1000} step={1}
                value={num('crypto15mOrderSize', C15_DEFAULTS.orderSize)}
                hint={`Contracts per bet. Polymarket minimum is ${MIN_CONTRACTS}.`}
                onCommit={(v) => void update({ crypto15mOrderSize: Math.round(v) })}
              />
            )}
            <NumField
              label="Max loss / bet" suffix="% bal" min={0} max={100} step={0.5}
              value={+(num('crypto15mMaxLossPct', 0) * 100).toFixed(2)}
              hint="Never risk more than this % of balance on one bet. 0 = off."
              onCommit={(v) => void update({ crypto15mMaxLossPct: v / 100 })}
            />
            <NumField
              label="Max open bets" min={1} max={50} step={1}
              value={num('crypto15mMaxConcurrent', C15_DEFAULTS.maxConcurrent)}
              hint="Most positions open at once (across all coins)."
              onCommit={(v) => void update({ crypto15mMaxConcurrent: Math.round(v) })}
            />
            <NumField
              label="Daily loss stop" suffix="$" min={0} max={100000} step={5}
              value={Math.abs(num('crypto15mDailyLossLimit', -50))}
              hint="Stop opening new bets for the day once you're down this much. 0 = off."
              onCommit={(v) => void update({ crypto15mDailyLossLimit: -Math.abs(v) })}
            />
            <NumField
              label="Take-profit (total)" suffix="$" min={0} max={1000000} step={1}
              value={num('crypto15mTakeProfitTotal', C15_DEFAULTS.takeProfitTotal)}
              hint="Turn the engine off once you're up this much. 0 = off."
              onCommit={(v) => void update({ crypto15mTakeProfitTotal: v })}
            />
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-rom-dim">
            Pick a preset above, tune the direction and entry band, set your bet
            size and safety caps, flip the executor on — that&apos;s it.
            Take-profits, streak sizing, indicator gates, model tuning, custom
            rules, and backtesting live in{' '}
            <span className="font-semibold text-rom-muted">Advanced</span> (top right).
          </p>
        </>
      )}

      {uiMode === 'advanced' && (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        <SelectField
          label="Direction" value={dir}
          options={[['favorite', 'Favorite-follow'], ['contrarian', 'Contrarian fade'], ['model', 'Model — settlement sniper']]}
          hint="Buy the favorite, fade it, or let the spot-vs-open model call the side (needs Detect MACD/RSI + live spot feed on)."
          onCommit={(v) => void update({ crypto15mDirectionMode: v as 'favorite' | 'contrarian' | 'model' })}
        />
        {dir === 'model' && (
          <>
            <NumField
              label="Model certainty ≥" suffix="%" min={50} max={100} step={0.5}
              value={+((config?.crypto15mModelMinProb ?? 0.97) * 100).toFixed(1)}
              hint="Enter only when the model calls the side at least this likely."
              onCommit={(v) => void update({ crypto15mModelMinProb: v / 100 })}
            />
            <NumField
              label="Min net edge" suffix="¢" min={0} max={50} step={0.5}
              value={config?.crypto15mModelMinEdgeCents ?? 2}
              hint="Model probability minus the ask minus the taker fee must clear this."
              onCommit={(v) => void update({ crypto15mModelMinEdgeCents: v })}
            />
            <NumField
              label="Max book gap" suffix="¢" min={0} max={100} step={1}
              value={config?.crypto15mModelMaxBookGapCents ?? 25}
              hint="Safety guard: outside the final minute, skip when the model claims MORE edge than this against the live book — a live book that disagrees that much usually knows the open price better than we do (bad strike after a restart, etc). 0 = off."
              onCommit={(v) => void update({ crypto15mModelMaxBookGapCents: v })}
            />
            <SelectField
              label="Final-minute strikes" value={(config?.crypto15mModelFinalMinute ?? true) ? 'on' : 'off'}
              options={[['on', 'On (3-sigma gate)'], ['off', 'Off']]}
              hint="Allow entries inside the last 60s when the model is near-certain, the spot feed is live, and there's order runway."
              onCommit={(v) => void update({ crypto15mModelFinalMinute: v === 'on' })}
            />
            <SelectField
              label="Calibration guard" value={(config?.crypto15mModelAutopause ?? true) ? 'on' : 'off'}
              options={[['on', 'Auto-pause on drift'], ['off', 'Off']]}
              hint="Pause model entries when recent high-confidence calls stop landing; resumes when calibration recovers."
              onCommit={(v) => void update({ crypto15mModelAutopause: v === 'on' })}
            />
            <SelectField
              label="Paired both-sides" value={(config?.crypto15mPairedMode ?? false) ? 'on' : 'off'}
              options={[['off', 'Off (single side)'], ['on', 'On (tilt ladder)']]}
              hint="Buy BOTH sides when their combined cost is under the cap, and tilt 1x/2x/3x toward the model's underpriced side as its edge grows (3¢/6¢/10¢). Only at tilt=1x (equal contracts) does the paired position cap the loss at roughly fees. At 2x/3x the extra contracts on the tilted side make it a directional bet — if that side loses you can lose a substantial fraction of the stake, not just fees."
              onCommit={(v) => void update({ crypto15mPairedMode: v === 'on' })}
            />
            {config?.crypto15mPairedMode && (
              <NumField
                label="Pair cost ≤" suffix="¢" min={50} max={100} step={0.5}
                value={config?.crypto15mPairedMaxCombinedCents ?? 100}
                hint="Enter only when Up ask + Down ask totals at most this. 100¢ is the sweet spot (catches the at-the-money cluster); below ~99¢ starves it. The max is 100 — a >$1 pair pays less than it costs."
                onCommit={(v) => void update({ crypto15mPairedMaxCombinedCents: v })}
              />
            )}
          </>
        )}
        <NumField
          label="Entry window" suffix="min" min={1} max={15} step={1}
          value={num('crypto15mTimeDelayMin', C15_DEFAULTS.timeDelayMin)}
          hint="Only act inside the last N minutes of the 15-min quarter."
          onCommit={(v) => void update({ crypto15mTimeDelayMin: v })}
        />
        <NumField
          label="Favorite ≥" suffix="¢" min={1} max={99} step={1}
          value={Math.round(num('crypto15mEntryThreshold', C15_DEFAULTS.entryThreshold) * 100)}
          hint="The favorite side must be at least this likely to enter."
          onCommit={(v) => void update({ crypto15mEntryThreshold: v / 100 })}
        />
        <NumField
          label="Skip above" suffix="¢" min={1} max={99} step={1}
          value={Math.round(num('crypto15mEntryMax', C15_DEFAULTS.entryMax) * 100)}
          hint="Don't pay more than this — too little room left to profit."
          onCommit={(v) => void update({ crypto15mEntryMax: v / 100 })}
        />
        <NumField
          label="Min move Δ" suffix="%" min={0} max={50} step={0.05}
          value={+(num('crypto15mMinDeltaPct', C15_DEFAULTS.minDeltaPct) * 100).toFixed(2)}
          hint="Required underlying move from the 15-min open (CoinGecko spot). 0 = off."
          onCommit={(v) => void update({ crypto15mMinDeltaPct: v / 100 })}
        />
        <NumField
          label="Stop-loss" suffix="¢" min={0} max={99} step={1}
          value={Math.round(num('crypto15mExitThreshold', C15_DEFAULTS.exitThreshold) * 100)}
          hint="Executor sells if the held side falls to this price. 0 = hold to settlement."
          onCommit={(v) => void update({ crypto15mExitThreshold: v / 100 })}
        />
        <NumField
          label="Take-profit" suffix="¢" min={0} max={99} step={1}
          value={Math.round(num('crypto15mTakeProfit', C15_DEFAULTS.takeProfit) * 100)}
          hint="Cash out a bet when our side's real best bid reaches this price (e.g. 95¢) — locks in the win instead of riding to settlement. 0 = off."
          onCommit={(v) => void update({ crypto15mTakeProfit: v / 100 })}
        />
        <SelectField
          label="Sell into strength" value={(config?.crypto15mSellIntoStrength ?? false) ? 'on' : 'off'}
          options={[['off', 'Off'], ['on', 'On (resting ask)']]}
          hint="On fill, rest a sell order at the target below so any price spike lifts it — fills as a maker (no fee) and catches moves between engine ticks. Only bets entered below the target qualify, so high-priced sniper entries are unaffected."
          onCommit={(v) => void update({ crypto15mSellIntoStrength: v === 'on' })}
        />
        {config?.crypto15mSellIntoStrength && (
          <NumField
            label="Strength target" suffix="¢" min={50} max={99} step={1}
            value={config?.crypto15mSellStrengthCents ?? 80}
            hint="The resting sell price. The PRR winners' pattern sells winners at ~80¢ instead of riding to settlement."
            onCommit={(v) => void update({ crypto15mSellStrengthCents: v })}
          />
        )}
        <NumField
          label="Stop-loss %" suffix="%" min={0} max={100} step={1}
          value={Math.round(num('crypto15mStopLossPct', C15_DEFAULTS.stopLossPct) * 100)}
          hint="Sell once a position is down this % from what it cost (e.g. 20 = exit at −20%). Applies to every timeframe (5m/15m/1h) and works alongside the cents Stop-loss above — whichever hits first exits. 0 = off."
          onCommit={(v) => void update({ crypto15mStopLossPct: Math.max(0, Math.min(100, Math.round(v))) / 100 })}
        />
        <NumField
          label="Take-profit %" suffix="%" min={0} max={100} step={1}
          value={Math.round(num('crypto15mTakeProfitPct', C15_DEFAULTS.takeProfitPct) * 100)}
          hint="Cash out once a position is up this % from what it cost (e.g. 20 = sell at +20%), measured on the real best bid. Works alongside the cents Take-profit above — whichever hits first sells. 0 = off."
          onCommit={(v) => void update({ crypto15mTakeProfitPct: Math.max(0, Math.min(100, Math.round(v))) / 100 })}
        />
        <NumField
          label="Daily loss limit" suffix="$" min={0} max={100000} step={5}
          value={Math.abs(num('crypto15mDailyLossLimit', -50))}
          hint="Pause NEW crypto entries for the rest of the UTC day once today's realized P&L (plus open exposure) is down this much. Open positions are still managed. 0 = off."
          onCommit={(v) => void update({ crypto15mDailyLossLimit: -Math.abs(v) })}
        />
        <NumField
          label="Lifetime loss limit" suffix="% bankroll" min={0} max={100} step={5}
          value={Math.round(num('crypto15mLifetimeLossLimitPct', 0.5) * 100)}
          hint="Circuit-breaker: pause the engine once CUMULATIVE realized crypto loss reaches this % of your starting bankroll (survives history wipes). Default 50%. Raise it (or set 0 = off) to resume a tripped engine — this is the setting the 'lifetime loss limit reached' pause refers to."
          onCommit={(v) => void update({ crypto15mLifetimeLossLimitPct: Math.max(0, Math.min(100, Math.round(v))) / 100 })}
        />
        <NumField
          label="Lifetime limit $" suffix="$ (overrides %)" min={0} max={1000000} step={10}
          value={num('crypto15mLifetimeLossLimitUsd', 0)}
          hint="Absolute-dollar version of the lifetime breaker. When > 0 it takes precedence over the % setting. 0 = use the %."
          onCommit={(v) => void update({ crypto15mLifetimeLossLimitUsd: Math.max(0, v) })}
        />
        <SelectField
          label="Entry style" value={entryStyle}
          options={[['maker', 'Rest at bid (maker)'], ['taker', 'Cross spread (taker)']]}
          hint="Maker rests a limit at the bid: no spread paid, ~zero Polymarket fee, but it may not fill. Taker crosses the ask: always fills, pays spread + the full taker fee."
          onCommit={(v) => void update({ crypto15mEntryStyle: v as 'maker' | 'taker' })}
        />
        {entryStyle === 'maker' ? (
          <>
            <NumField
              label="Cancel unfilled" suffix="min left" min={0} max={15} step={0.5}
              value={num('crypto15mMakerCancelMin', C15_DEFAULTS.makerCancelMin)}
              hint="Give up on a resting entry this many minutes before the market closes. 0 = keep it until close."
              onCommit={(v) => void update({ crypto15mMakerCancelMin: v })}
            />
            <SelectField
              label="If still unfilled"
              value={config?.crypto15mMakerEscalate === false ? 'off' : 'on'}
              options={[['on', 'Cross to taker'], ['off', 'Cancel it']]}
              hint="At the cancel lead, a maker that hasn't filled rests no better — cross the spread (capped at 'Skip above') to actually get filled before close, or just cancel."
              onCommit={(v) => void update({ crypto15mMakerEscalate: v === 'on' })}
            />
          </>
        ) : (
          <NumField
            label="Entry markup" suffix="¢" min={0} max={20} step={1}
            value={Math.round(num('crypto15mEntryDiff', C15_DEFAULTS.entryDiff) * 100)}
            hint="How far through the spread the limit order crosses to get filled."
            onCommit={(v) => void update({ crypto15mEntryDiff: v / 100 })}
          />
        )}
        <NumField
          label="Trade from" suffix="UTC h" min={0} max={24} step={1}
          value={num('crypto15mHoursStartUtc', C15_DEFAULTS.hoursStartUtc)}
          hint="Only enter between these UTC hours (collected data leans positive 00–12 UTC, negative in the US session). Same start/end or 0–24 = always."
          onCommit={(v) => void update({ crypto15mHoursStartUtc: Math.round(v) })}
        />
        <NumField
          label="…until" suffix="UTC h" min={0} max={24} step={1}
          value={num('crypto15mHoursEndUtc', C15_DEFAULTS.hoursEndUtc)}
          hint="End of the UTC entry window. A start later than the end wraps overnight (e.g. 22 → 6)."
          onCommit={(v) => void update({ crypto15mHoursEndUtc: Math.round(v) })}
        />
        <SelectField
          label="Bet size by" value={sizingMode}
          options={[['fixed', 'Fixed contracts'], ['balance_pct', '% of balance']]}
          hint="Buy a fixed number of contracts, or spend a % of your balance each bet."
          onCommit={(v) => void update({ crypto15mSizingMode: v as 'fixed' | 'balance_pct' })}
        />
        {sizingMode === 'balance_pct' ? (
          <NumField
            label="Per bet" suffix="% bal" min={0.1} max={100} step={0.1}
            value={+(num('crypto15mBalancePct', 0.02) * 100).toFixed(2)}
            hint="Spend this % of your balance on each entry (contracts = budget ÷ price)."
            onCommit={(v) => void update({ crypto15mBalancePct: v / 100 })}
          />
        ) : (
          <NumField
            label="Order size" suffix="ct" min={MIN_CONTRACTS} max={1000} step={1}
            value={num('crypto15mOrderSize', C15_DEFAULTS.orderSize)}
            hint={`Contracts per entry. Polymarket minimum is ${MIN_CONTRACTS}.`}
            onCommit={(v) => void update({ crypto15mOrderSize: Math.round(v) })}
          />
        )}
        <NumField
          label="Max loss / bet" suffix="% bal" min={0} max={100} step={0.5}
          value={+(num('crypto15mMaxLossPct', 0) * 100).toFixed(2)}
          hint="Never risk more than this % of balance on one bet (it's bought outright, so cost = max loss). 0 = off."
          onCommit={(v) => void update({ crypto15mMaxLossPct: v / 100 })}
        />
        <SelectField
          label="Streak sizing" value={config?.crypto15mStreakSizing ? 'on' : 'off'}
          options={[['off', 'Off'], ['on', 'On']]}
          hint="Scale the next bet by your settled win/loss run: each consecutive loss multiplies size by (1 + on-loss %), each win by (1 + on-win %). Reshapes variance (martingale-style recovery vs bigger drawdowns) — it does NOT add edge; recorded outcomes are streak-free. Max loss/bet and balance caps still apply."
          onCommit={(v) => void update({ crypto15mStreakSizing: v === 'on' })}
        />
        {config?.crypto15mStreakSizing && (
          <>
            <NumField
              label="On loss" suffix="%/loss" min={-90} max={300} step={5}
              value={num('crypto15mStreakLossPct', 20)}
              hint="Size change per consecutive loss, compounding: +20 → 1.2× after one loss, 1.44× after two. Negative shrinks after losses instead."
              onCommit={(v) => void update({ crypto15mStreakLossPct: v })}
            />
            <NumField
              label="On win" suffix="%/win" min={-90} max={300} step={5}
              value={num('crypto15mStreakWinPct', 0)}
              hint="Size change per consecutive win. 0 = any win resets to base size. Positive presses winning streaks (anti-martingale); negative banks down after wins."
              onCommit={(v) => void update({ crypto15mStreakWinPct: v })}
            />
            <NumField
              label="Streak cap" suffix="× base" min={1} max={100} step={0.5}
              value={num('crypto15mStreakMaxMult', 4)}
              hint="Hard ceiling on the streak multiplier. At +20%/loss a 4× cap is reached after ~8 straight losses; the ramp holds there until the streak breaks."
              onCommit={(v) => void update({ crypto15mStreakMaxMult: v })}
            />
          </>
        )}
        <NumField
          label="Max concurrent" min={1} max={50} step={1}
          value={num('crypto15mMaxConcurrent', C15_DEFAULTS.maxConcurrent)}
          hint="Most open 15-min positions at once (across the 7 assets)."
          onCommit={(v) => void update({ crypto15mMaxConcurrent: Math.round(v) })}
        />
        <NumField
          label="Take-profit (total)" suffix="$" min={0} max={1000000} step={1}
          value={num('crypto15mTakeProfitTotal', C15_DEFAULTS.takeProfitTotal)}
          hint="Turn the crypto engine OFF once realized P&L gained since you set this reaches $X. Open bets still ride to settlement. 0 = off."
          onCommit={(v) => void update({ crypto15mTakeProfitTotal: v })}
        />
        <SelectField
          label="Order-flow gate" value={config?.crypto15mImbalanceGate ? 'on' : 'off'}
          options={[['off', 'Off'], ['on', 'Require confirm']]}
          hint="Optional entry gate: only enter when the order-book imbalance backs the side being bought (buy-pressure for Up, sell-pressure for Down). The first composable signal gate — off by default until you've validated the signal on recorded data."
          onCommit={(v) => void update({ crypto15mImbalanceGate: v === 'on' })}
        />
        <NumField
          label="Gate confirm" suffix="imb" min={0} max={1} step={0.05}
          value={num('crypto15mImbalanceGateMin', 0.2)}
          hint="Minimum |imbalance| (0–1) needed to confirm an entry. Higher = stricter. Only used when the order-flow gate is on."
          onCommit={(v) => void update({ crypto15mImbalanceGateMin: v })}
        />
        <NumField
          label="Min RSI" suffix="0–100" min={0} max={100} step={1}
          value={num('crypto15mMinRsi', 0)}
          hint="Direction-aware momentum gate: an Up bet needs RSI ≥ this; a Down bet needs RSI ≤ (100 − this). Pair with a wide Entry window to enter early only on strong momentum. Needs Detect MACD/RSI (auto-enabled). 0 = off."
          onCommit={(v) => void update({ crypto15mMinRsi: Math.round(v), ...(v > 0 ? { crypto15mIndicatorDetect: true } : {}) })}
        />
        <NumField
          label="Min MACD" suffix="|hist|" min={0} max={100000} step={0.1}
          value={num('crypto15mMinMacdHist', 0)}
          hint="Direction-aware: an Up bet needs MACD histogram ≥ this; a Down bet needs ≤ −this. Uses the signal-line histogram — its sign is scale-free across assets, unlike the raw MACD line. Needs Detect MACD/RSI (auto-enabled). 0 = off."
          onCommit={(v) => void update({ crypto15mMinMacdHist: v, ...(v > 0 ? { crypto15mIndicatorDetect: true } : {}) })}
        />
      </div>
      )}

      <SizingPreview sizing={sizing} mode={sizingMode} orderSize={config?.crypto15mOrderSize ?? 5} />
      {dir === 'contrarian' && (
        <p className="mt-2 text-[11px] text-rom-warn/90">
          Contrarian: when a side is an extreme favorite (≥ threshold) the executor buys the CHEAP opposite side — a low-win, high-payoff longshot. Set stop-loss to 0 to hold to settlement.
        </p>
      )}
    </div>
  );
}

function SizingPreview({ sizing, mode, orderSize }: {
  sizing: Crypto15mSizing | null;
  mode: 'fixed' | 'balance_pct';
  orderSize: number;
}) {
  if (!sizing) return null;
  const { estContracts, estCostUsd, estPriceCents, balanceUsd, balancePct, maxLossPct, streakMult, note } = sizing;
  const known = balanceUsd > 0;

  const belowMin = estContracts >= 1 && estContracts < MIN_CONTRACTS;
  const balanceLimited = known && (mode === 'balance_pct' || estContracts < orderSize);
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-rom-border bg-rom-surface2 px-3 py-2 text-[11px]">
      <span className="inline-flex items-center gap-1.5 font-semibold uppercase tracking-wider text-rom-dim">
        <Wallet className="h-3.5 w-3.5" /> Per bet
      </span>
      <span className="font-mono text-sm text-white">≈ {fmtUsd(estCostUsd)}</span>
      <span className="text-rom-muted">
        {estContracts} contract{estContracts === 1 ? '' : 's'} @ ~{estPriceCents}¢
      </span>
      {mode === 'balance_pct' && (
        <span className="text-rom-dim">
          {(balancePct * 100).toFixed(1)}% of {known ? fmtUsd(balanceUsd) : 'balance'}
        </span>
      )}
      {maxLossPct > 0 && (
        <span className="text-rom-dim">
          max risk {(maxLossPct * 100).toFixed(1)}%{known ? ` · ${fmtUsd(balanceUsd * maxLossPct)}` : ''}
        </span>
      )}
      {streakMult != null && streakMult !== 1 && (
        <span className={streakMult > 1 ? 'text-rom-warn' : 'text-rom-dim'}>
          streak ×{streakMult.toFixed(2)}
        </span>
      )}
      {known && <span className="ml-auto text-rom-dim">balance {fmtUsd(balanceUsd)}</span>}
      {note && <span className="w-full text-rom-warn">{note}</span>}
      {belowMin && (
        <span className="w-full text-rom-lossText">
          {balanceLimited
            ? `Your ${fmtUsd(balanceUsd)} balance only funds ${estContracts} contract${estContracts === 1 ? '' : 's'} at ~${estPriceCents}¢ — below Polymarket's ${MIN_CONTRACTS}-contract minimum, so orders won't place. Add funds to trade.`
            : `Below Polymarket's ${MIN_CONTRACTS}-contract minimum — orders won't place. Raise your order size to ${MIN_CONTRACTS}+ contracts.`}
        </span>
      )}
    </div>
  );
}

function NumField({
  label, value, onCommit, suffix, min, max, step, hint,
}: {
  label: string;
  value: number;
  onCommit: (v: number) => void;
  suffix?: string;
  min: number;
  max: number;
  step: number;
  hint?: string;
}) {
  const [text, setText] = useState(String(value));

  useEffect(() => { setText(String(value)); }, [value]);

  const commit = () => {
    const parsed = Number(text);
    if (Number.isNaN(parsed)) { setText(String(value)); return; }
    const clamped = Math.min(max, Math.max(min, parsed));
    setText(String(clamped));
    if (clamped !== value) onCommit(clamped);
  };

  return (
    <label className="block rounded-lg border border-rom-border bg-rom-surface2 px-2.5 py-1.5" title={hint}>
      <div className="flex items-center justify-between text-[11px] uppercase tracking-wider text-rom-dim">
        <span>{label}</span>
        {suffix && <span className="text-rom-dim">{suffix}</span>}
      </div>
      <input
        type="number"
        inputMode="decimal"
        value={text}
        min={min}
        max={max}
        step={step}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
        className="mt-0.5 w-full bg-transparent font-mono text-sm text-white outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
      />
    </label>
  );
}

function SelectField({
  label, value, options, onCommit, hint,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onCommit: (v: string) => void;
  hint?: string;
}) {
  return (
    <label className="block rounded-lg border border-rom-border bg-rom-surface2 px-2.5 py-1.5" title={hint}>
      <div className="text-[11px] uppercase tracking-wider text-rom-dim">{label}</div>
      <select
        value={value}
        onChange={(e) => onCommit(e.target.value)}
        className="mt-0.5 w-full cursor-pointer bg-transparent font-mono text-sm text-white outline-none"
      >
        {options.map(([v, lbl]) => (
          <option key={v} value={v} className="bg-rom-surface text-white">{lbl}</option>
        ))}
      </select>
    </label>
  );
}

type CardState = 'signal' | 'window' | 'watching' | 'idle';

function cardState(a: Crypto15mAsset): CardState {
  if (a.signal) return 'signal';
  if (a.inWindow) return 'window';
  if (a.hasMarket) return 'watching';
  return 'idle';
}

function AssetCard({ a }: { a: Crypto15mAsset }) {
  const state = cardState(a);
  const ring = cls(
    a.enabled === false && 'opacity-50',
    state === 'signal'
      ? 'border-rom-win/60 shadow-[0_0_22px_rgba(34,197,94,0.18)]'
      : state === 'window'
        ? 'border-rom-warn/50'
        : 'border-rom-border',
  );

  const upFav = a.favorite === 'up';
  const downFav = a.favorite === 'down';

  return (
    <div className={cls('rom-card flex flex-col gap-3 border', ring)}>
      <div className="flex items-center gap-2">
        <div className="grid h-8 w-8 place-items-center rounded-lg bg-rom-surface2 text-rom-purple">
          <Bitcoin className="h-4 w-4" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-white">{a.asset}</div>
          <div className="font-mono text-[11px] text-rom-dim">{a.series}</div>
        </div>
        <div className="ml-auto">
          <StatePill state={state} />
        </div>
      </div>

      {a.error ? (
        <div className="rounded-md border border-rom-loss/30 bg-rom-loss/5 px-2 py-1.5 text-[11px] text-rom-lossText">
          {a.error}
        </div>
      ) : !a.hasMarket ? (
        <div className="py-2 text-center text-xs text-rom-dim">No open contract right now.</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <SideBox label="UP" prob={a.upProb} fav={upFav} good />
            <SideBox label="DOWN" prob={a.downProb} fav={downFav} />
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-rom-muted">
              closes in <span className="font-mono text-white">{fmtMins(a.minsLeft)}</span>
            </span>
            <span className="text-rom-muted">
              entry <span className="font-mono text-white">{pct(a.entryCost)}</span>
            </span>
          </div>
          {a.arbEdgeCents != null && (
            <div className={cls(
              'flex items-center justify-between rounded-md border px-2 py-1 text-[11px]',
              a.arbSignal
                ? 'border-rom-win/50 bg-rom-win/10 text-rom-win'
                : 'border-rom-border bg-rom-surface2 text-rom-dim',
            )}>
              <span>Up+Down asks</span>
              <span className="font-mono">
                {a.upAsk != null && a.downAsk != null
                  ? `${Math.round(a.upAsk * 100)}¢ + ${Math.round(a.downAsk * 100)}¢`
                  : '—'}
                {a.arbSignal && <span className="ml-2 font-semibold">ARB +{a.arbEdgeCents}¢</span>}
              </span>
            </div>
          )}
          {a.modelProb != null && (
            <div className={cls(
              'flex items-center justify-between rounded-md border px-2 py-1 text-[11px]',
              (a.edgeNetCents ?? -1) >= 2
                ? 'border-rom-purple/50 bg-rom-purple/10 text-rom-purple'
                : 'border-rom-border bg-rom-surface2 text-rom-dim',
            )}>
              <span>Model</span>
              <span className="font-mono">
                {Math.round(a.modelProb * 100)}%{a.modelProb >= 0.5 ? '↑' : '↓'}
                {a.edgeNetCents != null && (
                  <span className={cls('ml-2', a.edgeNetCents >= 0 ? 'text-rom-win' : 'text-rom-lossText')}>
                    {a.edgeNetCents >= 0 ? '+' : ''}{a.edgeNetCents.toFixed(1)}¢
                  </span>
                )}
                {!a.spotLive && <span className="ml-2 text-rom-dim">rest spot</span>}
              </span>
            </div>
          )}
          {a.bookImbalance != null && (
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-rom-muted">Order-flow (Up book)</span>
              <span className={cls(
                'font-mono',
                a.bookImbalance > 0.15 ? 'text-rom-win'
                  : a.bookImbalance < -0.15 ? 'text-rom-lossText'
                    : 'text-rom-dim',
              )}>
                {a.bookImbalance > 0 ? '+' : ''}{a.bookImbalance.toFixed(2)}
                {a.bookImbalance > 0.15 ? ' buy' : a.bookImbalance < -0.15 ? ' sell' : ''}
              </span>
            </div>
          )}
          {a.peersAgree != null && (
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-rom-muted">Peers agree ({a.favorite})</span>
              <span className={cls(
                'font-mono',
                a.peersAgree >= 0.6 ? 'text-rom-win'
                  : a.peersAgree <= 0.3 ? 'text-rom-lossText'
                    : 'text-rom-dim',
              )}>
                {Math.round(a.peersAgree * 100)}%
              </span>
            </div>
          )}
          {a.macdHist != null && (
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-rom-muted">MACD (underlying)</span>
              <span className={cls(
                'font-mono',
                a.macdHist > 0 ? 'text-rom-win' : a.macdHist < 0 ? 'text-rom-lossText' : 'text-rom-dim',
              )}>
                {a.macdHist > 0 ? 'bull' : a.macdHist < 0 ? 'bear' : 'flat'}
                {a.macdCross === 1 ? ' ↑' : a.macdCross === -1 ? ' ↓' : ''}
                {a.rsi != null ? ` · RSI ${Math.round(a.rsi)}` : ''}
              </span>
            </div>
          )}
          {a.wsAsk != null && a.favoritePrice != null && (() => {
            const gammaC = Math.round(a.favoritePrice * 100);
            const gap = a.wsAsk - gammaC;
            return (
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-rom-muted">
                  Real book {a.priceSource === 'ws'
                    ? <span className="text-rom-win">● deciding</span>
                    : <span className="text-rom-dim">(ref)</span>}
                </span>
                <span className={cls(
                  'font-mono',
                  Math.abs(gap) >= 5 ? 'text-rom-lossText' : 'text-rom-dim',
                )}>
                  {a.wsAsk}¢ <span className="text-rom-muted">vs {gammaC}¢ Gamma</span>
                  {` (${gap >= 0 ? '+' : ''}${gap}¢)`}
                </span>
              </div>
            );
          })()}
        </>
      )}

      <div className="-mx-5 -mb-5 mt-1 grid grid-cols-3 gap-px border-t border-rom-border bg-rom-border/40 text-center text-[11px]">
        <Foot label="Spot" value={fmtSpot(a.spotUsd)} />
        <Foot label="Open" value={fmtSpot(a.open15mUsd)} />
        <Foot label="Δ move" value={fmtDelta(a.deltaUsd)} />
      </div>
    </div>
  );
}

function StatePill({ state }: { state: CardState }) {
  if (state === 'signal') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-rom-win/15 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-rom-win">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rom-win shadow-[0_0_8px_currentColor]" />
        Signal
      </span>
    );
  }
  if (state === 'window') {
    return (
      <span className="rounded-full bg-rom-warn/15 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-rom-warn">
        In window
      </span>
    );
  }
  if (state === 'watching') {
    return (
      <span className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] uppercase tracking-wider text-rom-muted">
        watching
      </span>
    );
  }
  return <span className="text-[11px] uppercase tracking-wider text-rom-dim">idle</span>;
}

function SideBox({
  label, prob, fav, good,
}: { label: string; prob: number | null; fav: boolean; good?: boolean }) {
  return (
    <div
      className={cls(
        'rounded-lg border px-2 py-1.5 text-center',
        fav
          ? good
            ? 'border-rom-win/40 bg-rom-win/10'
            : 'border-rom-loss/40 bg-rom-loss/10'
          : 'border-rom-border bg-rom-surface2',
      )}
    >
      <div className={cls('text-[11px] uppercase tracking-wider', fav ? (good ? 'text-rom-win' : 'text-rom-lossText') : 'text-rom-dim')}>
        {label}{fav ? ' ★' : ''}
      </div>
      <div className="font-mono text-lg text-white">{pct(prob)}</div>
    </div>
  );
}

function Foot({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-rom-surface px-2 py-2">
      <div className="text-[11px] uppercase tracking-wider text-rom-dim">{label}</div>
      <div className="mt-0.5 font-mono text-white">{value}</div>
    </div>
  );
}

const C15_SKIP_LABELS: Record<string, { label: string; tip: string }> = {
  above_cap: { label: 'above cap', tip: 'Favorite was priced above your Skip-above cap — skipped (too expensive to enter).' },
  no_liquidity: { label: 'no fill', tip: 'Taker crossed but found no resting liquidity at/under your price — 0 fill. Enter earlier (wider window) or use maker.' },
  favorite_flipped: { label: 'flipped', tip: 'Favorite fell below your Favorite≥ floor before the order landed — skipped.' },
  unfilled_expired: { label: 'expired', tip: "Order didn't fill before the window closed." },
  stop_loss: { label: 'stopped', tip: 'Stop-loss sold to flatten the position.' },
  take_profit: { label: 'took profit', tip: 'Take-profit cashed out — sold the position into the book at your target price.' },
  settlement_reconciled: { label: 'settled', tip: 'Booked from on-chain settlement after a missed/mis-marked fill.' },
  paper_removed: { label: 'removed', tip: 'Legacy paper position retired.' },
};

function PositionsTable({ title, rows }: { title: string; rows: Crypto15mPosition[] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-[0.16em] text-rom-muted">{title}</h3>
      <div className="overflow-hidden rounded-xl border border-rom-border">
        <table className="rom-table">
          <thead>
            <tr>
              <th>Asset</th>
              <th>Side</th>
              <th>Status</th>
              <th>Contracts</th>
              <th>Entry</th>
              <th>Cost</th>
              <th>P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => <PositionRow key={p.id} p={p} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PositionRow({ p }: { p: Crypto15mPosition }) {
  const entryC = p.avgEntryCents ?? p.entryLimitCents;
  const reason = p.exitReason ? C15_SKIP_LABELS[p.exitReason] : undefined;
  return (
    <tr>
      <td><TickerLink ticker={p.ticker} env={p.network} label={p.asset} /></td>
      <td>
        <span className={cls(
          'rounded-md px-1.5 py-0.5 text-[11px] font-semibold uppercase',
          p.side === 'up' ? 'bg-rom-win/10 text-rom-win' : 'bg-rom-loss/10 text-rom-lossText',
        )}>
          {p.side || p.direction}
        </span>
      </td>
      <td className="text-xs text-rom-muted">
        {p.settling ? (
          <span className="text-rom-warn" title="Window closed — waiting on Polymarket's on-chain settlement to index (usually under ~2 min).">
            resolving…
          </span>
        ) : reason ? (
          <span
            className={p.status === 'canceled' || p.status === 'error' ? 'text-rom-dim' : undefined}
            title={reason.tip}
          >
            {reason.label}
          </span>
        ) : p.status === 'error' ? (
          <span className="text-rom-lossText" title={p.error || 'Order error'}>error</span>
        ) : (
          <>{p.status}</>
        )}
      </td>
      <td className="font-mono text-xs">{p.filledContracts}/{p.targetContracts}</td>
      <td className="font-mono text-xs">{entryC ? `${Math.round(entryC)}¢` : '—'}</td>
      <td className="font-mono text-xs text-rom-muted">{fmtUsd(p.costUsd)}</td>
      <td className={cls(
        'font-mono text-xs',
        p.pnlUsd === null ? 'text-rom-dim' : p.pnlUsd >= 0 ? 'text-rom-win' : 'text-rom-lossText',
      )}>
        {p.pnlUsd === null ? '—' : fmtUsd(p.pnlUsd, { sign: true })}
      </td>
    </tr>
  );
}
