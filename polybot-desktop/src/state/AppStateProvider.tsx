import {
  createContext, ReactNode, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import type {
  AccountSnapshot, AppState, BackendInfo, BotPosition, CredentialsState,
  CredentialsStatusAll,
  LogEntry, ScannerStats, SignalRow, StrategyPreset, TraderConfig,
} from '@shared/types';
import { useToast } from './ToastProvider';

interface AppStateApi {
  state: AppState | null;
  config: TraderConfig | null;
  backend: BackendInfo;
  account: AccountSnapshot | null;
  scannerStats: ScannerStats | null;
  positions: BotPosition[];
  signals: SignalRow[];
  logs: LogEntry[];
  credentials: CredentialsState | null;
  credentialsAll: CredentialsStatusAll | null;
  strategies: StrategyPreset[];
  appVersion: string;
  refresh: {
    state: () => Promise<void>;
    account: () => Promise<void>;
    positions: () => Promise<void>;
    signals: () => Promise<void>;
    scannerStats: () => Promise<void>;
    credentials: () => Promise<void>;
    backend: () => Promise<void>;
  };
}

const AppCtx = createContext<AppStateApi | null>(null);

export function useApp(): AppStateApi {
  const ctx = useContext(AppCtx);
  if (!ctx) throw new Error('useApp must be inside AppStateProvider');
  return ctx;
}

const DEFAULT_BACKEND: BackendInfo = {
  status: 'stopped',
  pid: null,
  startedAt: null,
  lastError: null,
  pythonOk: false,
  authOk: false,
};

function notify(title: string, body: string): void {
  try {
    // eslint-disable-next-line no-new
    new Notification(title, { body, silent: true });
  } catch {}
}

export function AppStateProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [state, setState] = useState<AppState | null>(null);
  const [backend, setBackend] = useState<BackendInfo>(DEFAULT_BACKEND);
  const [account, setAccount] = useState<AccountSnapshot | null>(null);
  const [scannerStats, setScannerStats] = useState<ScannerStats | null>(null);
  const [positions, setPositions] = useState<BotPosition[]>([]);
  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [credentials, setCredentials] = useState<CredentialsState | null>(null);
  const [credentialsAll, setCredentialsAll] = useState<CredentialsStatusAll | null>(null);
  const [strategies, setStrategies] = useState<StrategyPreset[]>([]);
  const [appVersion, setAppVersion] = useState('1.0.0');

  const positionsByIdRef = useRef<Map<number, BotPosition>>(new Map());
  const signalsByKeyRef = useRef<Map<string, SignalRow>>(new Map());

  const flushPositions = (): void => {
    const arr = Array.from(positionsByIdRef.current.values());

    const ts = (p: BotPosition): number => {
      for (const c of [p.lastUpdated, p.resolvedAt, p.createdAt]) {
        if (!c) continue;
        const t = new Date(c).getTime();
        if (Number.isFinite(t)) return t;
      }
      return 0;
    };
    arr.sort((a, b) => ts(b) - ts(a));
    setPositions(arr.slice(0, 500));
  };

  const flushSignals = (): void => {
    const arr = Array.from(signalsByKeyRef.current.values());
    arr.sort((a, b) => {
      const ta = new Date(a.createdAt).getTime();
      const tb = new Date(b.createdAt).getTime();
      return (Number.isFinite(tb) ? tb : 0) - (Number.isFinite(ta) ? ta : 0);
    });
    setSignals(arr.slice(0, 300));
  };

  const flushPosTimer = useRef<number | null>(null);
  const flushSigTimer = useRef<number | null>(null);
  const scheduleFlushPositions = (): void => {
    if (flushPosTimer.current != null) return;
    flushPosTimer.current = window.setTimeout(() => {
      flushPosTimer.current = null;
      flushPositions();
    }, 150);
  };
  const scheduleFlushSignals = (): void => {
    if (flushSigTimer.current != null) return;
    flushSigTimer.current = window.setTimeout(() => {
      flushSigTimer.current = null;
      flushSignals();
    }, 150);
  };

  const logBufRef = useRef<LogEntry[]>([]);
  const flushLogTimer = useRef<number | null>(null);
  const scheduleFlushLogs = (): void => {
    if (flushLogTimer.current != null) return;
    flushLogTimer.current = window.setTimeout(() => {
      flushLogTimer.current = null;
      const buf = logBufRef.current;
      if (!buf.length) return;
      logBufRef.current = [];
      setLogs((cur) => {
        const next = [...cur, ...buf];
        if (next.length > 1000) next.splice(0, next.length - 1000);
        return next;
      });
    }, 150);
  };

  const refreshState = async (): Promise<void> => {
    try {
      const s = await window.rom.state.get();
      setState(s);
    } catch {}
  };

  const refreshAccount = async (): Promise<void> => {
    try {
      const a = await window.rom.data.account();
      setAccount(a);
    } catch {}
  };

  const refreshPositions = async (): Promise<void> => {
    try {
      const rows = await window.rom.data.positions({ limit: 500 });
      const map = new Map<number, BotPosition>();
      for (const r of rows) map.set(r.id, r);
      positionsByIdRef.current = map;
      flushPositions();
    } catch {}
  };

  const refreshSignals = async (): Promise<void> => {
    try {
      const rows = await window.rom.data.signals({ limit: 300 });
      const map = new Map<string, SignalRow>();
      for (const r of rows) map.set(`${r.source}:${r.id}`, r);
      signalsByKeyRef.current = map;
      flushSignals();
    } catch {}
  };

  const refreshScannerStats = async (): Promise<void> => {
    try {
      const s = await window.rom.data.scannerStats();
      setScannerStats(s);
    } catch {}
  };

  const refreshCredentials = async (): Promise<void> => {
    try {
      const [c, all] = await Promise.all([
        window.rom.credentials.status(),
        window.rom.credentials.statusAll().catch(() => null),
      ]);
      setCredentials(c);
      setCredentialsAll(all);
    } catch {}
  };

  const refreshBackend = async (): Promise<void> => {
    try {
      const b = await window.rom.backend.info();
      setBackend(b);
    } catch {}
  };

  useEffect(() => {
    let mounted = true;
    const init = async () => {
      const [s, b, a, c, ss, pos, sig, ls, ver, strat] = await Promise.all([
        window.rom.state.get(),
        window.rom.backend.info(),
        window.rom.data.account(),
        window.rom.credentials.status().catch(() => null),
        window.rom.data.scannerStats(),
        window.rom.data.positions({ limit: 500 }),
        window.rom.data.signals({ limit: 300 }),
        window.rom.logs.tail(500),
        window.rom.app.version(),
        window.rom.config.listStrategies(),
      ]);
      if (!mounted) return;
      setState(s);
      setBackend(b);
      setAccount(a);
      setCredentials(c);

      void window.rom.credentials.statusAll().then(setCredentialsAll).catch(() => null);
      setScannerStats(ss);
      const pmap = new Map<number, BotPosition>();
      for (const r of pos) pmap.set(r.id, r);
      positionsByIdRef.current = pmap;
      flushPositions();
      const smap = new Map<string, SignalRow>();
      for (const r of sig) smap.set(`${r.source}:${r.id}`, r);
      signalsByKeyRef.current = smap;
      flushSignals();
      setLogs(ls);
      setAppVersion(ver);
      setStrategies(strat);
    };
    void init();

    const offState = window.rom.state.onChange((s) => setState(s));
    const offBackend = window.rom.backend.onInfo((b) => setBackend(b));
    const offAccount = window.rom.data.onAccount((a) => setAccount(a));
    const offPos = window.rom.data.onPosition((p) => {
      const prev = positionsByIdRef.current.get(p.id);
      if (prev && prev.status !== p.status) {
        const name = p.title || p.ticker;
        if (p.status === 'filled' && prev.status !== 'filled') {
          notify(`Filled: ${name}`, `${p.filledContracts} @ ${p.avgFillPriceCents ?? '?'}¢`);
        } else if (p.resolved && !prev.resolved && typeof p.pnlUsd === 'number') {
          const won = p.pnlUsd >= 0;
          notify(`${won ? 'Won' : 'Lost'} $${Math.abs(p.pnlUsd).toFixed(2)} — ${name}`, p.status ?? '');
        }
      }
      positionsByIdRef.current.set(p.id, p);
      scheduleFlushPositions();
    });
    const offSig = window.rom.data.onSignal((s) => {
      signalsByKeyRef.current.set(`${s.source}:${s.id}`, s);
      scheduleFlushSignals();
    });
    const offLog = window.rom.logs.onAppend((entry) => {
      logBufRef.current.push(entry);
      scheduleFlushLogs();
    });

    const offCreds = window.rom.credentials.onChanged(() => {
      void refreshCredentials();
    });

    const offAutoOff = window.rom.crypto15m.onAutoOff((d) => {
      const gained = typeof d?.gained === 'number' ? d.gained : 0;
      const target = typeof d?.target === 'number' ? d.target : 0;
      toast.success(
        `Crypto take-profit hit (+$${gained.toFixed(2)} ≥ $${target.toFixed(2)}) — crypto engine turned off.`,
      );
    });
    const offReset = window.rom.app.onDataReset(() => {
      positionsByIdRef.current = new Map();
      signalsByKeyRef.current = new Map();
      setPositions([]);
      setSignals([]);
      void Promise.all([
        refreshAccount(),
        refreshPositions(),
        refreshSignals(),
        refreshScannerStats(),
      ]);
    });

    const intervals: number[] = [];
    const guarded = (fn: () => Promise<void>): (() => void) => {
      let busy = false;
      return () => {
        if (busy) return;
        busy = true;
        void fn().finally(() => { busy = false; });
      };
    };
    intervals.push(window.setInterval(guarded(refreshCredentials), 6000));
    intervals.push(window.setInterval(guarded(refreshScannerStats), 8000));
    intervals.push(window.setInterval(guarded(refreshSignals), 12000));
    intervals.push(window.setInterval(guarded(refreshPositions), 12000));

    return () => {
      mounted = false;
      offState();
      offBackend();
      offAccount();
      offPos();
      offSig();
      offLog();
      offCreds();
      offAutoOff();
      offReset();
      if (flushPosTimer.current != null) window.clearTimeout(flushPosTimer.current);
      if (flushSigTimer.current != null) window.clearTimeout(flushSigTimer.current);
      if (flushLogTimer.current != null) window.clearTimeout(flushLogTimer.current);
      for (const i of intervals) window.clearInterval(i);
    };
  }, []);

  const config = state?.config ?? null;

  const api = useMemo<AppStateApi>(
    () => ({
      state,
      config,
      backend,
      account,
      scannerStats,
      positions,
      signals,
      logs,
      credentials,
      credentialsAll,
      strategies,
      appVersion,
      refresh: {
        state: refreshState,
        account: refreshAccount,
        positions: refreshPositions,
        signals: refreshSignals,
        scannerStats: refreshScannerStats,
        credentials: refreshCredentials,
        backend: refreshBackend,
      },
    }),
    [
      state, config, backend, account, scannerStats, positions, signals,
      logs, credentials, strategies, appVersion,
    ],
  );

  return <AppCtx.Provider value={api}>{children}</AppCtx.Provider>;
}
