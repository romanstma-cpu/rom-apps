import { useEffect, useRef, useState } from 'react';
import { Copy, FolderPlus, Plus, Trash2, Wallet, X } from 'lucide-react';
import type { CopyStatus, TraderConfig } from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Card, NameDialog, NumberInput, Page, Section, Switch } from '../components/common';
import { cls, fmtUsd } from '../utils/format';

const POLL_MS = 8000;

let cachedStatus: CopyStatus | null = null;

const isAddr = (s: string): boolean => /^0x[0-9a-fA-F]{40}$/.test(s.trim());

function OriginalCopyTradingPage() {
  const { config, positions } = useApp();
  const toast = useToast();
  const [status, setStatus] = useState<CopyStatus | null>(cachedStatus);
  const [addr, setAddr] = useState('');
  const [busy, setBusy] = useState(false);
  const [saveProfileOpen, setSaveProfileOpen] = useState(false);
  const timer = useRef<number | null>(null);

  async function load() {
    try {
      const s = await window.rom.copy.status();
      cachedStatus = s;
      setStatus(s);
    } catch {}
  }

  useEffect(() => {
    void load();
    timer.current = window.setInterval(load, POLL_MS);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, []);

  const update = async (patch: Partial<TraderConfig>): Promise<void> => {
    setBusy(true);
    try {
      await window.rom.config.update(patch);
      void load();
    } finally {
      setBusy(false);
    }
  };

  const enabled = !!config?.copyEnabled;
  const authed = !!status?.authed;
  const trading = !!status?.trading;
  const mode: 'OFF' | 'WAITING' | 'LIVE' = !enabled ? 'OFF' : (trading ? 'LIVE' : 'WAITING');
  const wallets = config?.copyWallets ?? [];
  const sizingMode = config?.copySizingMode ?? 'fixed';
  const copyPositions = positions.filter((p) => p.signalSource === 'copy');
  const openCopies = copyPositions.filter(
    (p) => !p.resolved && (p.status === 'filled' || p.status === 'partial' || p.status === 'submitted'),
  );

  const toggleEnabled = async (next: boolean): Promise<void> => {
    if (next && !window.confirm(
      'Enable copy trading?\n\nIt will place REAL orders with your Polymarket balance '
      + 'whenever a followed wallet enters a position — and sell when they exit — as soon '
      + 'as your wallet is connected. This runs independently of the main bot. There is no '
      + 'paper mode.',
    )) return;
    await update({ copyEnabled: next });
  };

  const addWallet = async (): Promise<void> => {
    const a = addr.trim().toLowerCase();
    if (!isAddr(a)) {
      toast.error('Enter a valid 0x… wallet address (40 hex chars).');
      return;
    }
    if (wallets.map((w) => w.toLowerCase()).includes(a)) {
      toast.info('Already following that wallet.');
      return;
    }
    await update({ copyWallets: [...wallets, a] });
    setAddr('');
    toast.success('Wallet added.');
  };

  const removeWallet = async (w: string): Promise<void> => {
    await update({ copyWallets: wallets.filter((x) => x !== w) });
  };

  const saveProfile = async (name: string): Promise<void> => {
    setSaveProfileOpen(false);
    const r = await window.rom.profiles.save(name, undefined, 'copy');
    if (r.ok) toast.success(r.message || 'Saved copy-trading profile');
    else toast.error(r.message || 'Failed to save profile');
  };

  const walletStat = (w: string) =>
    status?.wallets.find((x) => x.address.toLowerCase() === w.toLowerCase());

  return (
    <Page
      title="Copy Trading"
      subtitle="Mirror other Polymarket US APIs — copy their entries and follow them out on exit."
      actions={
        <button onClick={() => setSaveProfileOpen(true)} className="rom-btn-default">
          <FolderPlus className="h-4 w-4" /> Save as profile
        </button>
      }
    >
      <div className="mb-4 rounded-xl border border-rom-border bg-rom-surface p-3">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <div className="min-w-[260px] flex-1">
            <Switch
              checked={enabled}
              disabled={busy}
              onChange={(v) => void toggleEnabled(v)}
              label="Enable copy trading"
              description={
                mode === 'LIVE'
                  ? 'LIVE — placing real orders that mirror your followed wallets.'
                  : mode === 'WAITING'
                    ? 'Enabled — will mirror trades once your wallet is connected.'
                    : 'Off — not following anyone.'
              }
            />
          </div>
          <ModePill mode={mode} />
          <div className="flex items-center gap-4 text-xs">
            <KV label="Following" value={`${wallets.length}`} />
            <KV label="Open copies" value={`${openCopies.length}`} />
            <KV
              label="Today P&L"
              value={fmtUsd(status?.todayPnlUsd ?? 0, { sign: true })}
              tone={(status?.todayPnlUsd ?? 0) >= 0 ? 'good' : 'bad'}
            />
          </div>
        </div>
        {enabled && !authed && (
          <div className="mt-3 rounded-lg border border-rom-warn/30 bg-rom-warn/5 px-3 py-2 text-xs text-rom-warn">
            Enabled, but no wallet is connected — connect on the Wallet page to start mirroring trades.
          </div>
        )}
        {status?.lossLimitHit && (
          <div className="mt-3 rounded-lg border border-rom-loss/30 bg-rom-loss/5 px-3 py-2 text-xs text-rom-lossText">
            Daily loss limit hit — no new copies today. Open positions are still managed.
          </div>
        )}
      </div>

      <Section title="Followed wallets" description="Paste any Polymarket US API address to mirror its trades.">
        <Card>
          <div className="flex gap-2">
            <input
              value={addr}
              onChange={(e) => setAddr(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void addWallet(); }}
              placeholder="0x… wallet address"
              spellCheck={false}
              className="flex-1 rounded-lg border border-rom-border bg-rom-surface2 px-3 py-2 font-mono text-xs text-white placeholder:text-rom-dim focus:border-rom-purple focus:outline-none"
            />
            <button onClick={() => void addWallet()} disabled={busy} className="rom-btn-primary shrink-0">
              <Plus className="h-4 w-4" /> Follow
            </button>
          </div>

          <div className="mt-3 space-y-2">
            {wallets.length === 0 ? (
              <div className="rounded-lg border border-dashed border-rom-border px-3 py-6 text-center text-xs text-rom-muted">
                Not following anyone yet. Add a wallet above to start mirroring its trades.
              </div>
            ) : wallets.map((w) => {
              const ws = walletStat(w);
              return (
                <div key={w} className="flex items-center gap-3 rounded-lg border border-rom-border bg-rom-surface2 px-3 py-2">
                  <Wallet className="h-4 w-4 shrink-0 text-rom-purple" />
                  <span className="font-mono text-xs text-white">{ws?.short ?? `${w.slice(0, 6)}…${w.slice(-4)}`}</span>
                  <span className="text-[11px] text-rom-muted">
                    {ws ? `${ws.positions} open · ${fmtUsd(ws.valueUsd)}` : 'fetching…'}
                  </span>
                  <button
                    onClick={() => void removeWallet(w)}
                    disabled={busy}
                    className="ml-auto rounded-md p-1 text-rom-muted hover:bg-rom-loss/10 hover:text-rom-lossText"
                    title="Stop following"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              );
            })}
          </div>
        </Card>
      </Section>

      <Section title="Sizing & risk" description="How big each copy is, and the guard rails around it.">
        <Card>
          <div className="grid gap-5 md:grid-cols-2">
            <div>
              <Label>Copy size</Label>
              <div className="mb-2 inline-flex rounded-md border border-rom-border bg-rom-surface2 p-0.5">
                {(['fixed', 'balance_pct'] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => void update({ copySizingMode: m })}
                    className={cls(
                      'rounded-[6px] px-3 py-1.5 text-xs font-medium transition-colors',
                      sizingMode === m ? 'bg-rom-purple/15 text-rom-purple' : 'text-rom-muted hover:text-white',
                    )}
                  >
                    {m === 'fixed' ? 'Fixed $' : '% of balance'}
                  </button>
                ))}
              </div>
              {sizingMode === 'fixed' ? (
                <Row label="Dollars per copy" hint="Each mirrored entry spends about this much">
                  <NumberInput value={config?.copyFixedUsd ?? 10} step={5} min={1} prefix="$"
                    onChange={(v) => void update({ copyFixedUsd: Math.max(1, v) })} />
                </Row>
              ) : (
                <Row label="% of balance per copy" hint="Each copy spends this share of your balance">
                  <NumberInput value={Math.round((config?.copyBalancePct ?? 0.02) * 100)} step={1} min={0} max={100} suffix="%"
                    onChange={(v) => void update({ copyBalancePct: Math.max(0, Math.min(100, v)) / 100 })} />
                </Row>
              )}
            </div>

            <div className="space-y-3">
              <Row label="Min trade to copy" hint="Skip their positions smaller than this (their cost)">
                <NumberInput value={config?.copyMinTradeUsd ?? 25} step={5} min={0} prefix="$"
                  onChange={(v) => void update({ copyMinTradeUsd: Math.max(0, v) })} />
              </Row>
              <Row label="Max open copies" hint="Most positions copied at once">
                <NumberInput value={config?.copyMaxConcurrent ?? 10} step={1} min={1} max={200}
                  onChange={(v) => void update({ copyMaxConcurrent: Math.max(1, v) })} />
              </Row>
              <Row label="Max entry price" hint="Never pay more than this per contract">
                <NumberInput value={config?.copyEntryMaxCents ?? 95} step={1} min={1} max={99} suffix="¢"
                  onChange={(v) => void update({ copyEntryMaxCents: Math.max(1, Math.min(99, v)) })} />
              </Row>
              <Row label="Max daily loss" hint="Stop new copies after losing this much today. 0 = off">
                <NumberInput value={Math.abs(config?.copyDailyLossLimit ?? 50)} step={5} min={0} prefix="$"
                  onChange={(v) => void update({ copyDailyLossLimit: -Math.abs(v) })} />
              </Row>
              <Row label="Lifetime loss limit" hint="Circuit-breaker: pause copying once TOTAL realized copy loss reaches this % of your starting bankroll (survives history wipes). Default 50%. Raise or set 0 (off) to resume a tripped engine.">
                <NumberInput value={Math.round((config?.copyLifetimeLossLimitPct ?? 0.5) * 100)} step={5} min={0} max={100} suffix="%"
                  onChange={(v) => void update({ copyLifetimeLossLimitPct: Math.max(0, Math.min(100, v)) / 100 })} />
              </Row>
              <Row label="Lifetime limit $" hint="Absolute-$ version of the lifetime breaker; when > 0 it overrides the %. 0 = use the %">
                <NumberInput value={config?.copyLifetimeLossLimitUsd ?? 0} step={10} min={0} prefix="$"
                  onChange={(v) => void update({ copyLifetimeLossLimitUsd: Math.max(0, v) })} />
              </Row>
              <Switch
                checked={config?.copyOnlyNewEntries ?? true}
                onChange={(v) => void update({ copyOnlyNewEntries: v })}
                label="Only copy new entries"
                description="Copy a position only when a followed wallet opens it after you start following — skips ones they already hold, so you don't buy in after a big run-up. Off = mirror everything they currently hold."
              />
              <Switch
                checked={config?.copyAllowReentries ?? false}
                onChange={(v) => void update({ copyAllowReentries: v })}
                label="Copy repeat buys"
                description="When a followed wallet adds to a position you already copied (at least 'Min trade to copy' worth), place another copy at your normal size. Off = one copy per market, no matter how many times they buy in."
              />
            </div>
          </div>
        </Card>
      </Section>

      <p className="text-xs text-rom-dim">
        Copied positions appear on the <span className="text-rom-muted">Positions</span> page tagged
        {' '}<span className="rounded bg-rom-purple/15 px-1 text-rom-purple">copy</span>, with live P&amp;L.
        The bot mirrors an <span className="text-rom-muted">entry</span> when a followed wallet opens a position you
        don&apos;t hold, and <span className="text-rom-muted">exits</span> yours once every followed wallet has closed it.
      </p>

      <NameDialog
        open={saveProfileOpen}
        title="Save copy-trading profile"
        label="Saves your current copy-trading settings (followed wallets, sizing, limits) as a profile — find it under Profiles → Copy trading."
        placeholder="Profile name"
        confirmLabel="Save"
        onSubmit={(name) => void saveProfile(name)}
        onClose={() => setSaveProfileOpen(false)}
      />
    </Page>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <div className="text-xs text-white">{label}</div>
        {hint && <div className="text-[11px] text-rom-dim">{hint}</div>}
      </div>
      <div className="w-32 shrink-0">{children}</div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="mb-2 text-xs font-medium text-white">{children}</div>;
}

function KV({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'bad' }) {
  return (
    <div className="flex flex-col items-end leading-tight">
      <span className="text-[11px] uppercase tracking-wider text-rom-muted">{label}</span>
      <span className={cls('font-mono text-sm',
        tone === 'good' ? 'text-rom-win' : tone === 'bad' ? 'text-rom-lossText' : 'text-white')}>
        {value}
      </span>
    </div>
  );
}

function ModePill({ mode }: { mode: 'OFF' | 'WAITING' | 'LIVE' }) {
  return (
    <span className={cls(
      'rounded-md border px-2 py-1 text-[11px] font-semibold uppercase tracking-wider',
      mode === 'LIVE' && 'border-rom-loss/40 bg-rom-loss/10 text-rom-lossText',
      mode === 'WAITING' && 'border-rom-warn/40 bg-rom-warn/10 text-rom-warn',
      mode === 'OFF' && 'border-rom-border bg-rom-surface2 text-rom-muted',
    )}>
      {mode}
    </span>
  );
}

export function CopyTradingPage(){ return <Page title="Copy Trading" subtitle="Polymarket US"><Card><p className="text-sm text-rom-muted">Polymarket US does not expose other traders’ wallet positions or wallet activity. Wallet copy trading is unavailable. Your other strategies and risk controls remain available.</p></Card></Page>; }
