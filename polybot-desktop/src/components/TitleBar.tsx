import { useEffect, useState } from 'react';
import { Minus, Square, Copy as Restore, X } from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { cls } from '../utils/format';

export function TitleBar() {
  const { backend } = useApp();
  const [maxed, setMaxed] = useState(false);

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
        </div>
      </div>

      <div className="titlebar-no-drag flex items-center">
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
