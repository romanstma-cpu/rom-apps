import { useEffect, useRef, useState } from 'react';
import { FlaskConical, Play } from 'lucide-react';
import {
  Area, AreaChart, Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { C15_PRESET_CORE } from '@shared/c15Presets';
import type { CollectionStats, Crypto15mBacktest, TraderConfig } from '@shared/types';
import { Card, Page, Switch } from '../components/common';
import { useApp } from '../state/AppStateProvider';
import { cls, fmtUsd } from '../utils/format';

type Engine = 'crypto15m' | 'main';

const C15_STRATS: { id: string; name: string; patch: Partial<TraderConfig> }[] = [
  { id: 'current', name: 'My current settings', patch: {} },
  {
    id: 'sniper', name: 'Settlement Sniper',
    patch: {
      ...C15_PRESET_CORE.sniper,

      crypto15mModelMinProb: 0.97, crypto15mTimeDelayMin: 5, crypto15mEntryMax: 0.97,
    },
  },
  {
    id: 'sniper-5m', name: '5m Sniper (BTC)',
    patch: { ...C15_PRESET_CORE['sniper-5m'] },
  },
  {
    id: 'paired', name: 'Paired + Tilt',
    patch: { ...C15_PRESET_CORE.paired },
  },
  {
    id: 'favorite', name: 'Deep Favorite',

    patch: { ...C15_PRESET_CORE.favorite, crypto15mTimeDelayMin: 6 },
  },
  {
    id: 'contrarian', name: 'Contrarian fade',

    patch: { ...C15_PRESET_CORE.contrarian, crypto15mTimeDelayMin: 8 },
  },
];

const WINDOWS = [7, 14, 30, 60];

export function BacktestPage() {
  const [engine, setEngine] = useState<Engine>('main');
  const [stratSel, setStratSel] = useState('current');
  const [mainSel, setMainSel] = useState('current');
  const [days, setDays] = useState(30);
  const [scenario, setScenario] = useState('base');
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Crypto15mBacktest | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const runGeneration = useRef(0);
  useEffect(() => {
    // An older asynchronous result must never be labelled as the new selection.
    runGeneration.current += 1;
    setRes(null); setErr(null); setBusy(false);
    return () => { runGeneration.current += 1; };
  }, [engine, stratSel, mainSel, days, scenario]);
  const { config, state } = useApp();
  const profiles = state?.customProfiles ?? [];
  const [coll, setColl] = useState<CollectionStats | null>(null);
  const [showData, setShowData] = useState(false);

  const loadCollection = async () => {
    try {
      setColl(await window.rom.trading.collection());
    } catch {}
  };
  useEffect(() => { void loadCollection(); }, []);

  const toggleC15Collection = async (on: boolean) => {
    await window.rom.config.update({ crypto15mRecordSignals: on });
    void loadCollection();
  };

  const toggleMainCollection = async (on: boolean) => {
    await window.rom.config.update({ mainRecordSignals: on });
    void loadCollection();
  };

  const [exporting, setExporting] = useState(false);
  const exportData = async () => {
    setExporting(true);
    try {
      await window.rom.trading.exportData();
    } finally {
      setExporting(false);
    }
  };

  const sliceProfile = (cfg: TraderConfig, kind: Engine): Partial<TraderConfig> => {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(cfg)) {
      const is15m = k.startsWith('crypto15m');
      if ((kind === 'crypto15m') === is15m) out[k] = v;
    }

    delete out.enableTrading;
    delete out.crypto15mEnabled;
    return out as Partial<TraderConfig>;
  };

  const resolvePatch = (): Partial<TraderConfig> => {
    const sel = engine === 'crypto15m' ? stratSel : mainSel;
    if (sel.startsWith('profile:')) {
      const prof = profiles.find((pr) => pr.id === sel.slice(8));
      return prof ? sliceProfile(prof.config, engine) : {};
    }
    if (engine === 'crypto15m' && sel.startsWith('preset:')) {
      return C15_STRATS.find((st) => st.id === sel.slice(7))?.patch ?? {};
    }
    return {};
  };

  const run = async () => {
    const generation = ++runGeneration.current;
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      const patch = resolvePatch();
      const r = engine === 'crypto15m'
        ? await window.rom.crypto15m.backtest({ sinceDays: days, config: patch })
        : await window.rom.crypto15m.backtestMain({ sinceDays: days, config: { ...patch, replayScenario: scenario } as Partial<TraderConfig> });
      if (generation !== runGeneration.current) return;
      setRes(r);
      if (!r) setErr('Engine not running — start the app backend first.');
    } catch (e: any) {
      if (generation !== runGeneration.current) return;
      setErr(e?.message || String(e));
    } finally {
      if (generation === runGeneration.current) setBusy(false);
    }
  };

  const isCryptoProfile = (scope?: string) => (scope ?? 'main') === 'crypto';
  const isMainProfile = (scope?: string) => (scope ?? 'main') === 'main';

  return (
    <Page
      title="Backtest"
      subtitle="Test your settings against recorded evidence. Main replay includes cash limits, displayed liquidity, execution delay and US fees. Simulated results are not verified returns."
    >
      <Card header={<div className="text-xs uppercase tracking-wider text-rom-muted">Setup</div>}>
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Engine">
            <Chips
              options={[['crypto15m', 'Crypto up/down'], ['main', 'Main engine (whales + momentum)']]}
              value={engine}
              onPick={(v) => setEngine(v as Engine)}
            />
          </Field>
          {engine === 'crypto15m' && (
            <Field label="Strategy / profile">
              <select
                value={stratSel}
                onChange={(e) => setStratSel(e.target.value)}
                className="rounded-md border border-rom-border bg-rom-surface2 px-2.5 py-1.5 text-xs text-white outline-none focus:border-rom-purple/60"
              >
                <option value="current">Current settings</option>
                <optgroup label="Presets">
                  {C15_STRATS.filter((st) => st.id !== 'current').map((st) => (
                    <option key={st.id} value={`preset:${st.id}`}>{st.name}</option>
                  ))}
                </optgroup>
                {profiles.some((pr) => isCryptoProfile(pr.scope)) && (
                  <optgroup label="My profiles">
                    {profiles.filter((pr) => isCryptoProfile(pr.scope)).map((pr) => (
                      <option key={pr.id} value={`profile:${pr.id}`}>{pr.name}</option>
                    ))}
                  </optgroup>
                )}
              </select>
            </Field>
          )}
          {engine === 'main' && (
            <Field label="Strategy / profile">
              <select
                value={mainSel}
                onChange={(e) => setMainSel(e.target.value)}
                className="rounded-md border border-rom-border bg-rom-surface2 px-2.5 py-1.5 text-xs text-white outline-none focus:border-rom-purple/60"
              >
                <option value="current">Current settings (Strategies-page gates)</option>
                {profiles.some((pr) => isMainProfile(pr.scope)) && (
                  <optgroup label="My profiles">
                    {profiles.filter((pr) => isMainProfile(pr.scope)).map((pr) => (
                      <option key={pr.id} value={`profile:${pr.id}`}>{pr.name}</option>
                    ))}
                  </optgroup>
                )}
              </select>
            </Field>
          )}
          {engine === 'main' && <Field label="Execution scenario">
            <select aria-label="Execution scenario" value={scenario} onChange={(e) => setScenario(e.target.value)} className="rounded-md border border-rom-border bg-rom-surface2 px-2.5 py-1.5 text-xs text-white outline-none focus:border-rom-purple/60">
              <option value="base">Base · 250 ms, full depth</option>
              <option value="delayed">Delayed · 1 second, half depth</option>
              <option value="stress">Stress · 2 seconds, quarter depth, +1¢</option>
            </select>
          </Field>}
          <Field label="Window">
            <Chips
              options={WINDOWS.map((d) => [String(d), `${d}d`] as [string, string])}
              value={String(days)}
              onPick={(v) => setDays(Number(v))}
            />
          </Field>
          <button
            onClick={() => void run()}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-md border border-rom-purple/40 bg-rom-purple/10 px-4 py-2 text-xs font-semibold text-rom-purple transition-colors hover:bg-rom-purple/20 disabled:opacity-50"
          >
            {busy ? <FlaskConical className="h-3.5 w-3.5 animate-pulse" /> : <Play className="h-3.5 w-3.5" />}
            {busy ? 'Replaying…' : 'Run backtest'}
          </button>
        </div>
        {err && <p className="mt-2 text-xs text-rom-loss">{err}</p>}
      </Card>

      <div className="mt-4">
        <Card header={<div className="text-xs uppercase tracking-wider text-rom-muted">Data collection</div>}>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg bg-rom-surface2/50 p-3">
              <Switch
                checked={config?.crypto15mRecordSignals ?? true}
                onChange={(v) => void toggleC15Collection(v)}
                label="Collect crypto up/down data"
                description="Records every watched window's ticks and outcome while the app is open — no trading, no orders, works with the crypto executor fully off. This is the dataset crypto backtests run on."
              />
              <p className="mt-1.5 text-[11px] text-rom-dim">
                {coll ? `${coll.c15.windows.toLocaleString()} windows · ${coll.c15.ticks.toLocaleString()} ticks` : '…'}
                {coll?.c15.lastAt ? ` · last ${coll.c15.lastAt.slice(5, 16)} UTC` : ''}
              </p>
            </div>
            <div className="rounded-lg bg-rom-surface2/50 p-3">
              <Switch
                checked={config?.mainRecordSignals ?? true}
                onChange={(v) => void toggleMainCollection(v)}
                label="Collect whale + momentum signals"
                description="Records whale prints and momentum clusters while the app is open — nothing is bought. Note: if trading is ON, scanning stays on regardless (the engine can't follow signals it never sees)."
              />
              <p className="mt-1.5 text-[11px] text-rom-dim">
                {coll ? `${coll.main.whales.toLocaleString()} whale signals · ${coll.main.alerts.toLocaleString()} momentum` : '…'}
                {coll?.main.lastAt ? ` · last ${coll.main.lastAt.slice(5, 16)} UTC` : ''}
              </p>
              {coll && coll.main.alerts > coll.main.alertsWindowed ? (
                <p className="mt-1 text-[11px] text-rom-dim">
                  {coll.main.alertsWindowed.toLocaleString()} measured from live trade
                  windows. Earlier momentum rows were scored from rolling 24-hour
                  totals and are calibrated separately.
                </p>
              ) : null}
            </div>
          </div>
          <button
            onClick={() => void exportData()}
            disabled={exporting}
            className="mr-2 mt-3 rounded-md border border-rom-border bg-rom-surface2 px-3 py-1.5 text-xs text-rom-dim transition-colors hover:text-white disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : 'Export CSV (all collected data)'}
          </button>
          <button
            onClick={() => setShowData((v) => !v)}
            className="mt-3 rounded-md border border-rom-border bg-rom-surface2 px-3 py-1.5 text-xs text-rom-dim transition-colors hover:text-white"
          >
            {showData ? 'Hide collected data' : 'View collected data'}
          </button>
          {showData && coll && (
            <div className="mt-3 grid gap-4 lg:grid-cols-2">
              <div>
                <div className="mb-1 text-[10px] uppercase tracking-wide text-rom-dim">Latest crypto windows</div>
                <table className="w-full text-[11px]">
                  <thead><tr className="text-left text-rom-dim">
                    <th className="py-0.5 pr-2 font-normal">Asset</th>
                    <th className="py-0.5 pr-2 font-normal">Closes</th>
                    <th className="py-0.5 pr-2 font-normal">Favorite</th>
                    <th className="py-0.5 font-normal">Result</th>
                  </tr></thead>
                  <tbody>
                    {coll.c15.recent.map((r) => (
                      <tr key={r.ticker} className="border-t border-rom-border/50">
                        <td className="py-1 pr-2 font-mono text-white">{r.asset}</td>
                        <td className="py-1 pr-2 text-rom-dim">{r.close_time?.slice(5, 16)}</td>
                        <td className="py-1 pr-2 text-rom-dim">
                          {r.favorite ?? '—'}{r.favorite_price != null ? ` @ ${Math.round(r.favorite_price * 100)}¢` : ''}
                        </td>
                        <td className="py-1">
                          {!r.resolved ? <span className="text-rom-dim">open</span>
                            : r.up_won ? <span className="text-rom-win">UP won</span>
                              : <span className="text-rom-loss">DOWN won</span>}
                        </td>
                      </tr>
                    ))}
                    {coll.c15.recent.length === 0 && (
                      <tr><td colSpan={4} className="py-2 text-rom-dim">Nothing yet — leave the app open with collection on.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div>
                <div className="mb-1 text-[10px] uppercase tracking-wide text-rom-dim">Latest whale signals</div>
                <table className="w-full text-[11px]">
                  <thead><tr className="text-left text-rom-dim">
                    <th className="py-0.5 pr-2 font-normal">Category</th>
                    <th className="py-0.5 pr-2 font-normal">Side</th>
                    <th className="py-0.5 pr-2 font-normal">Price</th>
                    <th className="py-0.5 pr-2 font-normal">Size</th>
                    <th className="py-0.5 font-normal">Result</th>
                  </tr></thead>
                  <tbody>
                    {coll.main.recent.map((r, i) => (
                      <tr key={`${r.ticker}-${i}`} className="border-t border-rom-border/50">
                        <td className="py-1 pr-2 text-white">{r.category}</td>
                        <td className="py-1 pr-2 font-mono text-rom-dim">{r.taker_side}</td>
                        <td className="py-1 pr-2 text-rom-dim">{Math.round((r.price ?? 0) * 100)}¢</td>
                        <td className="py-1 pr-2 text-rom-dim">${Math.round(r.dollar_value ?? 0).toLocaleString()}</td>
                        <td className="py-1">
                          {!r.resolved ? <span className="text-rom-dim">open</span>
                            : r.outcome_correct ? <span className="text-rom-win">won</span>
                              : <span className="text-rom-loss">lost</span>}
                        </td>
                      </tr>
                    ))}
                    {coll.main.recent.length === 0 && (
                      <tr><td colSpan={5} className="py-2 text-rom-dim">Nothing yet — signals record while the app is open.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Card>
      </div>

      {res && (res.windowsScanned === 0 || res.dataStatus === 'insufficient_data') && (
        <Card className="mt-4">
          <div className="py-4 text-center">
            <div className="text-sm font-semibold text-white">No collected data yet</div>
            {res.caveats?.length ? (
              <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-rom-dim">{res.caveats[0]}</p>
            ) : (
              <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-rom-dim">
                This backtest runs on history YOUR bot collects while it runs. Leave the app open
                (monitor mode is enough — no live trading needed) and it records every
                {engine === 'crypto15m'
                  ? ' crypto up/down window with its outcome (the interval selected on the Crypto tab is the one recorded).'
                  : ' whale and momentum signal it sees, with outcomes. Data starts accruing immediately.'}
                {' '}Check back after a few hours; the charts get sharper every day it runs.
              </p>
            )}
          </div>
        </Card>
      )}
      {res && res.windowsScanned > 0 && res.dataStatus !== 'insufficient_data' && (
        <>
          {engine === 'crypto15m' && (
            res.interval ? (
              <div className="mt-4">
                <span className="rounded bg-rom-surface2 px-1.5 py-0.5 font-mono text-[10px] text-rom-dim">
                  replayed {res.interval} windows
                </span>
              </div>
            ) : (
              <p className="mt-4 text-[10px] text-rom-warn/80">
                backend predates per-interval backtests — update/rebuild the app
              </p>
            )
          )}
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-6">
            <Stat label="Trades" value={`${res.n}`} sub={`${res.windowsScanned} ${engine === 'crypto15m' ? 'windows' : 'signals'} scanned`} />
            <Stat label="Win rate" value={res.n ? `${(res.winRate * 100).toFixed(1)}%` : '—'} />
            <Stat label="Realized / contract" value={res.n ? `${res.netEvCentsPerContract.toFixed(2)}¢` : '—'} />
            <Stat label="Total P&L" value={fmtUsd(res.totalPnlUsd, { sign: true })} tone={res.totalPnlUsd >= 0 ? 'good' : 'bad'} />
            <Stat label="Max drawdown" value={fmtUsd(res.maxDrawdownUsd)} tone="bad" />
            <Stat label={res.mode === 'portfolio' ? 'Closed events' : 'Days traded'} value={`${res.mode === 'portfolio' ? res.independentEvents : res.byDay.length}`} />
          </div>
          {res.mode === 'portfolio' && <Card className="mt-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Cash" value={fmtUsd(res.cashUsd ?? 0)} />
              <Stat label="Reserved for orders" value={fmtUsd(res.reservedUsd ?? 0)} />
              <Stat label="Open positions" value={String(res.openPositions ?? 0)} />
              <Stat label="Simulated fees" value={fmtUsd(res.feesUsd ?? 0)} />
            </div>
          </Card>}

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card header={<ChartHead title="Equity over time" hint={res.mode === 'portfolio' ? 'Portfolio P&L includes open positions at recorded exit depth after fees. Stale or missing depth is valued at zero. Cash reserved for orders is still cash.' : 'Cumulative realized P&L in trade order.'} />}>
              <div className="h-48">
                <ResponsiveContainer>
                  <AreaChart data={res.equity.map((e, i) => ({ i, at: e.at ? e.at.slice(5, 16) : String(i), value: e.value }))}>
                    <XAxis dataKey="at" tick={{ fontSize: 9 }} minTickGap={40} stroke="#555" />
                    <YAxis tick={{ fontSize: 9 }} width={40} stroke="#555" />
                    <Tooltip contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 11 }} labelStyle={{ color: '#FFFFFF' }} itemStyle={{ color: '#FFFFFF' }} formatter={(v: number) => fmtUsd(v, { sign: true })} />
                    <Area dataKey="value" stroke="#a78bfa" fill="#a78bfa22" strokeWidth={1.5} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <Card header={<ChartHead title="P&L by hour of day (UTC)" hint="The 'first 12 hours print, last 12 lose' check — green bars earn, red bars bleed. Thin bars (low n) are noise, not signal." />}>
              <div className="h-48">
                <ResponsiveContainer>
                  <BarChart data={res.byHourUtc}>
                    <XAxis dataKey="hour" tick={{ fontSize: 9 }} stroke="#555" />
                    <YAxis tick={{ fontSize: 9 }} width={40} stroke="#555" />
                    <Tooltip
                      contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 11 }} labelStyle={{ color: '#FFFFFF' }} itemStyle={{ color: '#FFFFFF' }}
                      formatter={(v: number, _n, item: any) => [`${fmtUsd(v, { sign: true })} (${item?.payload?.wins}/${item?.payload?.n})`, 'P&L']}
                    />
                    <Bar dataKey="pnlUsd">
                      {res.byHourUtc.map((b) => (
                        <Cell key={b.hour} fill={b.pnlUsd >= 0 ? '#34d399' : '#f87171'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          <div className="mt-4">
            <Card header={<ChartHead title="P&L by day" hint="The 'prints one day, sucks the next' check — consistency across days matters more than the total." />}>
              <div className="h-40">
                <ResponsiveContainer>
                  <BarChart data={res.byDay.map((d) => ({ ...d, label: d.day.slice(5) }))}>
                    <XAxis dataKey="label" tick={{ fontSize: 9 }} stroke="#555" />
                    <YAxis tick={{ fontSize: 9 }} width={40} stroke="#555" />
                    <Tooltip
                      contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 11 }} labelStyle={{ color: '#FFFFFF' }} itemStyle={{ color: '#FFFFFF' }}
                      formatter={(v: number, _n, item: any) => [`${fmtUsd(v, { sign: true })} (${item?.payload?.wins}/${item?.payload?.n})`, 'P&L']}
                    />
                    <Bar dataKey="pnlUsd">
                      {res.byDay.map((d) => (
                        <Cell key={d.day} fill={d.pnlUsd >= 0 ? '#34d399' : '#f87171'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          {Object.keys(res.byAsset).length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {Object.entries(res.byAsset).map(([a, st]) => (
                <span key={a} className="rounded bg-rom-surface2 px-1.5 py-0.5 font-mono text-[10px] text-rom-dim">
                  {a} {st.wins}/{st.n} <span className={st.pnlUsd >= 0 ? 'text-rom-win' : 'text-rom-loss'}>{fmtUsd(st.pnlUsd, { sign: true })}</span>
                </span>
              ))}
            </div>
          )}

          <ul className="mt-3 space-y-0.5">
            {res.caveats.map((c, i) => (
              <li key={i} className="text-[10px] leading-relaxed text-rom-warn/80">⚠ {c}</li>
            ))}
          </ul>
        </>
      )}
    </Page>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[10px] uppercase tracking-wide text-rom-dim">{label}</div>
      {children}
    </div>
  );
}

function Chips({ options, value, onPick }: {
  options: [string, string][]; value: string; onPick: (v: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map(([v, label]) => (
        <button
          key={v}
          onClick={() => onPick(v)}
          className={cls(
            'rounded-md border px-2.5 py-1 text-xs transition-colors',
            v === value
              ? 'border-rom-purple/60 bg-rom-purple/15 text-rom-purple'
              : 'border-rom-border bg-rom-surface2 text-rom-dim hover:text-white',
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'good' | 'bad' }) {
  return (
    <div className="rounded-lg bg-rom-surface2/60 p-2">
      <div className="text-[10px] uppercase tracking-wide text-rom-dim">{label}</div>
      <div className={cls('font-mono text-sm', tone === 'good' ? 'text-rom-win' : tone === 'bad' ? 'text-rom-loss' : 'text-white')}>{value}</div>
      {sub && <div className="text-[10px] text-rom-dim">{sub}</div>}
    </div>
  );
}

function ChartHead({ title, hint }: { title: string; hint: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider text-rom-muted">{title}</div>
      <div className="mt-0.5 text-[10px] normal-case tracking-normal text-rom-dim">{hint}</div>
    </div>
  );
}
