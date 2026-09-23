import { useEffect, useState } from 'react';
import { AlertTriangle, Minus, Square, Copy as Restore, X } from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { cls } from '../utils/format';

export function TitleBar() {
  const { account, backend, config, refresh } = useApp();
  const toast = useToast();
  const [maxed, setMaxed] = useState(false);
  const [stopping, setStopping] = useState(false);

  useEffect(() => {
    let mounted = true;
    void window.rom.window.isMaximized().then((m) => {
      if (mounted) setMaxed(m);
    });
    const off = window.rom.window.onMaximizeChange((m) => setMaxed(m));
    return () => {
      mounted = false;
      off();
    };
  }, []);

  const dot =
    backend.status === 'running' ? 'bg-rom-win' :
    backend.status === 'starting' ? 'bg-rom-warn' :
    backend.status === 'crashed' || backend.status === 'restarting' ? 'bg-rom-loss' :
    'bg-rom-dim';

  const emergencyStop = async (): Promise<void> => {
    if (stopping) return;
    setStopping(true);
    try {
      const result = await window.rom.trading.emergencyStop();
      if (result.ok) toast.info(result.message || 'Main strategy paused.');
      else toast.error(result.message || 'Emergency stop could not be completed.');
      await refresh.state();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Emergency stop could not be completed.');
    } finally {
      setStopping(false);
    }
  };

  return (
    <div className="titlebar-drag relative z-30 flex h-9 select-none items-center justify-between border-b border-rom-border bg-rom-void/95 px-3 backdrop-blur">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-medium tracking-wide text-white/90">
            ROM PolyBot
          </span>
        </div>
        <div className="hidden items-center gap-2 text-[11px] text-rom-muted lg:flex">
          <span className={cls('h-2 w-2 rounded-full', dot, backend.status === 'running' && 'shadow-[0_0_8px_currentColor]')} />
          <span className="capitalize">Engine {backend.status}</span>
          {backend.authOk ? (
            <span className="rom-pill border-rom-win/40 bg-rom-win/10 text-rom-win">
              API connected
            </span>
          ) : (
            <span className="rom-pill border-rom-warn/40 bg-rom-warn/10 text-rom-warn">
              API not connected
            </span>
          )}
          {backend.authOk && account?.cashUsd === 0 && (
            <span className="rom-pill border-rom-warn/40 bg-rom-warn/10 text-rom-warn">
              No buying power
            </span>
          )}
        </div>
      </div>

      <div className="titlebar-no-drag flex items-center">
        {config?.enableTrading && (
          <button
            onClick={() => void emergencyStop()}
            disabled={stopping}
            title="Pause the main strategy and cancel its pending orders"
            className="mr-2 inline-flex h-7 items-center gap-1.5 rounded-md border border-rom-loss/60 bg-rom-loss/15 px-2 text-[10px] font-semibold text-rom-lossText hover:bg-rom-loss/25 disabled:opacity-60"
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            {stopping ? 'Stopping…' : 'Emergency stop'}
          </button>
        )}
        <button
          onClick={() => window.rom.window.minimize()}
          aria-label="Minimize"
          className="grid h-9 w-11 place-items-center text-rom-muted hover:bg-white/5 hover:text-white"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => window.rom.window.maximize()}
          aria-label={maxed ? 'Restore' : 'Maximize'}
          className="grid h-9 w-11 place-items-center text-rom-muted hover:bg-white/5 hover:text-white"
        >
          {maxed ? <Restore className="h-3 w-3" /> : <Square className="h-3 w-3" />}
        </button>
        <button
          onClick={() => window.rom.window.close()}
          aria-label="Close"
          className="grid h-9 w-11 place-items-center text-rom-muted hover:bg-rom-loss hover:text-white"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
