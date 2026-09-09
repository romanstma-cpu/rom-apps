import { useApp } from '../state/AppStateProvider';
import { useStrategyActivity } from '../state/StrategyActivity';
export function WorkspaceStatus() {
  const { config, backend } = useApp();
  const {label} = useStrategyActivity();
  const count = [config?.enableTrading, config?.crypto15mEnabled, config?.copyEnabled, config?.scriptsLiveEnabled].filter(Boolean).length;
  const practicing = !!config?.mainPaperTrading && !config?.enableTrading;
  const connection = backend.status === 'running'
    ? (backend.authOk ? 'Connected' : 'Account not connected')
    : (backend.status === 'starting' || backend.status === 'restarting' ? 'Starting engine…' : 'Engine offline');
  return <header className="flex shrink-0 items-center justify-between gap-4 border-b border-rom-border px-8 py-3 text-xs text-rom-muted">
    <span className="flex flex-wrap items-center gap-2"><span className={`h-1.5 w-1.5 rounded-full ${label === 'Scanning' ? 'bg-rom-win' : 'bg-rom-dim'}`} />Main: {label} · {count ? `${count} live engine${count > 1 ? 's' : ''} enabled` : practicing ? 'Practice selected' : 'Live engines disabled'}</span>
    <span>Polymarket US · {connection}</span>
  </header>;
}
