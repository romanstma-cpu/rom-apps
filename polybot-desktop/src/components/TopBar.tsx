import { useApp } from '../state/AppStateProvider';
import { ShareButton } from './common';
import { BossWidget } from './BossFight';
import { cls, fmtPct, fmtUsd } from '../utils/format';

const ENGINES: { key: 'main' | 'crypto' | 'copy' | 'scripts'; label: string }[] = [
  { key: 'main', label: 'Main' },
  { key: 'crypto', label: 'Crypto' },
  { key: 'copy', label: 'Copy' },
  { key: 'scripts', label: 'Scripts' },
];

export function TopBar() {
  const { config, account, backend } = useApp();

  const live: Record<string, boolean> = {
    main: !!config?.enableTrading,
    crypto: !!config?.crypto15mEnabled,
    copy: !!config?.copyEnabled && !!(config?.copyWallets || []).length,
    scripts: !!config?.scriptsLiveEnabled,
  };
  const liveCount = ENGINES.filter((e) => live[e.key]).length;
  const practicing = !!config?.mainPaperTrading && !config?.enableTrading;

  return (
    <header className="z-20 flex items-center gap-4 border-b border-rom-border bg-rom-void/70 px-8 py-3 backdrop-blur">
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-sm font-medium text-white">
            {liveCount === 0 && practicing
              ? 'Practice mode selected'
              : liveCount === 0
              ? 'All engines paused'
              : `${liveCount} engine${liveCount === 1 ? '' : 's'} live`}
          </h1>
          <span
            className={cls(
              'text-xs',
              backend.status === 'running' ? 'text-rom-muted' : 'text-rom-warn',
            )}
          >
            {backend.status === 'running' ? 'Backend online' : `Backend ${backend.status}`}
          </span>
        </div>

        <div className="hidden items-center gap-1.5 xl:flex">
          {ENGINES.map((e) => (
            <span
              key={e.key}
              title={`${e.label} engine ${live[e.key] ? 'live' : 'off'} — switch it on its own page`}
              className={cls(
                'rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide',
                live[e.key]
                  ? 'bg-rom-win/15 text-rom-win'
                  : 'bg-rom-surface2 text-rom-dim',
              )}
            >
              {e.label}
            </span>
          ))}
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <BossWidget />
        <div className="hidden items-center gap-5 px-3 md:flex">
          <Stat label="Balance" value={fmtUsd(account?.totalUsd ?? 0)} />
          <Stat
            label="Session P&L"
            value={fmtUsd(account?.sessionPnlUsd ?? 0, { sign: true })}
            color={
              (account?.sessionPnlUsd ?? 0) >= 0 ? 'text-rom-win' : 'text-rom-loss'
            }
          />
          <Stat
            label="ROI"
            value={fmtPct(account?.sessionRoiPct ?? account?.roiPct ?? 0)}
            color={
              (account?.sessionRoiPct ?? account?.roiPct ?? 0) >= 0
                ? 'text-rom-win' : 'text-rom-loss'
            }
          />
          <ShareButton
            size="xs"
            text={
              `ROM PolyBot: ${fmtUsd(account?.totalUsd ?? 0)} balance · `
              + `${fmtUsd(account?.sessionPnlUsd ?? 0, { sign: true })} this session · `
              + `${fmtPct(account?.sessionRoiPct ?? account?.roiPct ?? 0)} ROI. `
              + `ROM Polybot · Polymarket US`
            }
          />
        </div>
      </div>
    </header>
  );
}

function Stat({
  label, value, color,
}: { label: string; value: string; color?: string }) {
  return (
    <div className="flex flex-col items-end leading-tight">
      <span className="text-[10px] uppercase tracking-wider text-rom-muted">
        {label}
      </span>
      <span className={cls('font-mono text-sm', color || 'text-white')}>
        {value}
      </span>
    </div>
  );
}
