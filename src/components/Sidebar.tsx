import { useEffect, useState } from 'react';
import {
  Activity, BarChart3, Bitcoin, BookOpen, Briefcase, Code2, Copy, FlaskConical, Folder,
  Info, LayoutDashboard, ListChecks, Orbit, Settings, Share2, Sparkles, SquareTerminal, Users, Wallet,
} from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { useStrategyActivity } from '../state/StrategyActivity';
import { cls, fmtUsd } from '../utils/format';
import { ROMSprite } from './ROMSprite';
import { FlexStatsCard } from './FlexStatsCard';
import { BossWidget } from './BossFight';
import type { PageId } from '../App';

const NAV: { id: PageId; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
  { id: 'analytics', label: 'Detailed analytics', icon: BarChart3 },
  { id: 'evidence', label: 'Evidence', icon: ListChecks },
  { id: 'main', label: 'Strategy', icon: Sparkles },
  { id: 'positions', label: 'Positions', icon: Briefcase },
  { id: 'signals', label: 'Signals', icon: Activity },
  { id: 'crypto15m', label: 'Crypto', icon: Bitcoin },
  { id: 'terminal', label: 'Terminal', icon: SquareTerminal },
  { id: 'copy', label: 'Copy Trading', icon: Copy },
  { id: 'scripts', label: 'Scripts', icon: Code2 },
  { id: 'backtest', label: 'Backtest', icon: FlaskConical },
  { id: 'history', label: 'History', icon: BarChart3 },
  { id: 'profiles', label: 'Profiles', icon: Folder },
  { id: 'accounts', label: 'Accounts', icon: Users },
  { id: 'settings', label: 'Settings', icon: Settings },
  { id: 'api', label: 'API', icon: Wallet },
  { id: 'logs', label: 'Logs', icon: ListChecks },
  { id: 'guide', label: 'Guide', icon: BookOpen },
  { id: 'about', label: 'About', icon: Info },
];

interface SidebarProps {
  page: PageId;
  setPage: (p: PageId) => void;
}

export function Sidebar({ page, setPage }: SidebarProps) {
  const { config, account, backend } = useApp();
  const activity = useStrategyActivity();
  const [acct, setAcct] = useState('Default');
    const [showStats, setShowStats] = useState(false);
    const [advanced, setAdvanced] = useState(false);
    const [rail, setRail] = useState(false);
    useEffect(() => {
      const mq = window.matchMedia('(max-width: 768px)');
      const on = () => setRail(mq.matches);
      on();
      mq.addEventListener('change', on);
      return () => mq.removeEventListener('change', on);
    }, []);
    useEffect(() => {
      if (!['dashboard', 'main', 'positions', 'history', 'api'].includes(page)) setAdvanced(true);
    }, [page]);
    useEffect(() => { window.rom.accounts.current().then(setAcct).catch(() => {}); }, []);

  const groups = [
    { label: 'Workspace', ids: ['dashboard', 'main', 'positions', 'history', 'api'] },
    ...(advanced ? [{ label: 'Advanced tools', ids: ['evidence', 'analytics', 'signals', 'crypto15m', 'scripts', 'backtest', 'copy', 'terminal', 'profiles', 'accounts', 'settings', 'logs', 'guide', 'about'] }] : []),
  ];
  return rail ? (
    <aside aria-label="Main navigation" className="flex h-full w-14 shrink-0 flex-col items-center gap-1 border-r border-rom-border bg-rom-sidebar py-4">
      {NAV.slice(0, 9).map(({ id, label, icon: Icon }) => {
        const active = page === id;
        return (
          <button
            key={id}
            aria-label={label}
            title={label}
            aria-current={active ? 'page' : undefined}
            onClick={() => setPage(id)}
            className={cls(
              'grid h-10 w-10 place-items-center rounded-lg transition-colors',
              active ? 'bg-blue-500/15 text-blue-300' : 'text-rom-muted hover:bg-white/[0.06] hover:text-white',
            )}
          >
            <Icon className="h-5 w-5" />
          </button>
        );
      })}
    </aside>
  ) : (
    <aside className="sidebar-shell flex h-full w-56 shrink-0 flex-col border-r border-rom-border bg-rom-sidebar">
    <div className="flex items-center gap-3 border-b border-rom-border/70 px-5 py-5"><div className="rounded-xl border border-rom-purple/20 bg-rom-purple/[0.06] p-1"><ROMSprite size={38} /></div><div><div className="text-lg font-semibold tracking-[0.14em]">ROM</div><div className="font-mono text-[11px] uppercase tracking-[0.12em] text-rom-muted">Polybot / US</div></div></div>
    <nav aria-label="Main navigation" className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
      {groups.map(group => <div key={group.label} className="mb-4"><div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-rom-dim">{group.label}</div>
      {group.ids.map(id => { const item = NAV.find(n => n.id === id)!; const Icon = item.icon; const active = page === id; return <button key={id} aria-current={active ? 'page' : undefined} onClick={() => setPage(item.id)} className={cls('mb-0.5 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] transition-colors', active ? 'bg-blue-500/10 font-medium text-blue-300 shadow-[inset_2px_0_0_#6EA8FE]' : 'text-rom-muted hover:bg-white/[0.04] hover:text-white')}><Icon className="h-4 w-4 shrink-0" /><span>{item.label}</span></button>; })}</div>)}
      <button aria-expanded={advanced} onClick={() => setAdvanced(!advanced)} className="mt-3 flex w-full items-center justify-between rounded-lg border border-rom-border px-3 py-2 text-xs text-rom-muted hover:text-white">Advanced tools <span>{advanced ? '−' : '+'}</span></button>
      {advanced && <button onClick={() => setPage('visualizer')} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] text-rom-muted hover:bg-white/5 hover:text-white"><Orbit className="h-4 w-4" />Live Visualizer</button>}
    </nav>
    <div className="shrink-0 border-t border-rom-border p-3">{advanced && <BossWidget />}<div className="rounded-xl border border-rom-border bg-rom-void/45 p-3"><div className="mb-2 flex items-center justify-between"><span className="truncate text-[11px] text-rom-muted">{acct} account</span><button aria-label="Open shareable stats" title="Open shareable stats" onClick={() => setShowStats(true)} className="rounded-md p-1 text-rom-dim transition-colors hover:bg-white/5 hover:text-white"><Share2 className="h-3.5 w-3.5" /></button></div><div className="font-mono text-[11px] uppercase tracking-[0.15em] text-rom-dim">Account value</div><div className="mt-1 text-xl font-semibold tracking-tight tabular-nums" title={backend.authOk ? undefined : 'Connect your account on the API page'}>{backend.authOk ? fmtUsd(account?.totalUsd) : '—'}</div><div className="mt-2 flex items-center gap-2 border-t border-rom-border pt-2 text-[11px] text-rom-muted"><span className={cls('h-1.5 w-1.5 rounded-full', activity.label === 'Scanning' ? 'bg-rom-win shadow-[0_0_7px_#40C9A2]' : 'bg-rom-warn')} />Main strategy · {activity.label}</div></div></div>
    {showStats && <FlexStatsCard onClose={() => setShowStats(false)} />}
        </aside>
      );
    }
