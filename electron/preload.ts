import { contextBridge, ipcRenderer } from 'electron';
import type {
  AccountSnapshot, ActionResult, AppState, BackendInfo, BotPosition, CredentialsInput,
  CredentialsState, ROMApi, LogEntry, PnlPoint, PositionFilter, Profile,
  ScannerStats, SignalFilter, SignalRow, StrategyPreset, TraderConfig,
} from '../shared/types';

const sub = <T>(channel: string, cb: (val: T) => void): (() => void) => {
  const handler = (_e: unknown, val: T) => cb(val);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
};

const api: ROMApi = {
  app: {
    version: () => ipcRenderer.invoke('app:version'),
    openExternal: (url) => ipcRenderer.invoke('app:openExternal', url),
    showItemInFolder: (p) => ipcRenderer.invoke('app:showItemInFolder', p),
    getUserDataPath: () => ipcRenderer.invoke('app:getUserDataPath'),
    factoryReset: () => ipcRenderer.invoke('app:factoryReset'),
    clearHistory: () => ipcRenderer.invoke('app:clearHistory'),
    onDataReset: (cb) => sub<unknown>('data:reset', cb),
  },
  accounts: {
    current: () => ipcRenderer.invoke('accounts:current'),
    list: () => ipcRenderer.invoke('accounts:list'),
    create: (name: string) => ipcRenderer.invoke('accounts:create', name),
    launch: (name: string) => ipcRenderer.invoke('accounts:launch', name),
  },
  state: {
    get: (): Promise<AppState> => ipcRenderer.invoke('state:get'),
    onChange: (cb) => sub<AppState>('state:changed', cb),
    setStartMinimized: (v) => ipcRenderer.invoke('state:setStartMinimized', v),
    setStartWithWindows: (v) => ipcRenderer.invoke('state:setStartWithWindows', v),
    setEnableDiscordRpc: (v) => ipcRenderer.invoke('state:setEnableDiscordRpc', v),
    acceptDisclaimer: () => ipcRenderer.invoke('state:acceptDisclaimer'),
    resetOnboarding: () => ipcRenderer.invoke('state:resetOnboarding'),
  },
  config: {
    get: (): Promise<TraderConfig> => ipcRenderer.invoke('config:get'),
    update: (patch) => ipcRenderer.invoke('config:update', patch),
    replace: (cfg) => ipcRenderer.invoke('config:replace', cfg),
    reset: () => ipcRenderer.invoke('config:reset'),
    listStrategies: (): Promise<StrategyPreset[]> =>
      ipcRenderer.invoke('config:listStrategies'),
    applyStrategy: (id) => ipcRenderer.invoke('config:applyStrategy', id),
  },
  profiles: {
    list: (): Promise<Profile[]> => ipcRenderer.invoke('profiles:list'),
    save: (name, description, scope) => ipcRenderer.invoke('profiles:save', name, description, scope),
    apply: (id) => ipcRenderer.invoke('profiles:apply', id),
    rename: (id, name) => ipcRenderer.invoke('profiles:rename', id, name),
    delete: (id) => ipcRenderer.invoke('profiles:delete', id),
    duplicate: (id) => ipcRenderer.invoke('profiles:duplicate', id),
    export: (id) => ipcRenderer.invoke('profiles:export', id),
    import: (json) => ipcRenderer.invoke('profiles:import', json),
  },
  credentials: {
    status: (): Promise<CredentialsState> => ipcRenderer.invoke('credentials:status'),
    statusAll: () => ipcRenderer.invoke('credentials:statusAll'),
    save: (input: CredentialsInput) => ipcRenderer.invoke('credentials:save', input),
    test: (env?: string) => ipcRenderer.invoke('credentials:test', env),
    clear: (env?: string) => ipcRenderer.invoke('credentials:clear', env),
    onChanged: (cb) => sub<unknown>('credentials:changed', cb),
  },
  backend: {
    info: (): Promise<BackendInfo> => ipcRenderer.invoke('backend:info'),
    start: () => ipcRenderer.invoke('backend:start'),
    stop: () => ipcRenderer.invoke('backend:stop'),
    restart: () => ipcRenderer.invoke('backend:restart'),
    onInfo: (cb) => sub<BackendInfo>('backend:info', cb),
    runOnce: (action: string, payload?: unknown) =>
      ipcRenderer.invoke('backend:runOnce', action, payload),
  },
  trading: {
    calibration: () => ipcRenderer.invoke('trading:calibration'),
    setEnabled: (v: boolean): Promise<ActionResult> =>
      ipcRenderer.invoke('trading:setEnabled', v),
    setPaperEnabled: (v: boolean): Promise<ActionResult> =>
      ipcRenderer.invoke('trading:setPaperEnabled', v),
    cancelAllOpen: () => ipcRenderer.invoke('trading:cancelAllOpen'),
    flatten: () => ipcRenderer.invoke('trading:flatten'),
    status: () => ipcRenderer.invoke('trading:status'),
    collection: () => ipcRenderer.invoke('backtest:collection'),
    exportData: () => ipcRenderer.invoke('backtest:export'),
  },
  data: {
    account: (): Promise<AccountSnapshot> => ipcRenderer.invoke('data:account'),
    pnlSeries: (sinceHours?: number): Promise<PnlPoint[]> =>
      ipcRenderer.invoke('data:pnlSeries', sinceHours),
    positions: (filter?: PositionFilter): Promise<BotPosition[]> =>
      ipcRenderer.invoke('data:positions', filter),
    signals: (filter?: SignalFilter): Promise<SignalRow[]> =>
      ipcRenderer.invoke('data:signals', filter),
    scannerStats: (): Promise<ScannerStats> => ipcRenderer.invoke('data:scannerStats'),
    botRuns: (env, limit) =>
      ipcRenderer.invoke('data:botRuns', env ?? null, limit),
    onAccount: (cb) => sub<AccountSnapshot>('data:account', cb),
    onPosition: (cb) => sub<BotPosition>('data:position', cb),
    onSignal: (cb) => sub<SignalRow>('data:signal', cb),
  },
  crypto15m: {
    snapshot: () => ipcRenderer.invoke('crypto15m:snapshot'),
    status: () => ipcRenderer.invoke('crypto15m:status'),
    history: (opts?: { limit?: number }) => ipcRenderer.invoke('crypto15m:history', opts),
    backtest: (args?: { sinceDays?: number; config?: Record<string, unknown> }) =>
      ipcRenderer.invoke('crypto15m:backtest', args),
    backtestMain: (args?: { sinceDays?: number; config?: Record<string, unknown> }) =>
      ipcRenderer.invoke('main:backtest', args),
    onAutoOff: (cb) => sub<{ reason: string; gained: number; target: number }>('crypto15m:autoOff', cb),
  },
  scripts: {
    list: () => ipcRenderer.invoke('scripts:list'),
    save: (s) => ipcRenderer.invoke('scripts:save', s),
    delete: (id: string) => ipcRenderer.invoke('scripts:delete', id),
    setEnabled: (id: string, enabled: boolean) => ipcRenderer.invoke('scripts:setEnabled', id, enabled),
    setAssets: (id: string, assets: string[] | null) => ipcRenderer.invoke('scripts:setAssets', id, assets),
    setDryRun: (id: string, dryRun: boolean) => ipcRenderer.invoke('scripts:setDryRun', id, dryRun),
    exportFile: (name: string, code: string) => ipcRenderer.invoke('scripts:exportFile', name, code),
    importFile: () => ipcRenderer.invoke('scripts:importFile'),
    shadowOrders: (id: string, limit?: number) => ipcRenderer.invoke('scripts:shadowOrders', id, limit),
    validate: (code: string) => ipcRenderer.invoke('scripts:validate', code),
    backtest: (args) => ipcRenderer.invoke('scripts:backtest', args),
    contextPack: () => ipcRenderer.invoke('scripts:contextPack'),
    docs: () => ipcRenderer.invoke('scripts:docs'),
    exportPack: () => ipcRenderer.invoke('scripts:exportPack'),
    onStatus: (cb) => sub<{ id: string; enabled: boolean; lastError?: string }>('scripts:status', cb),
    onLog: (cb) => sub<{ id: string; lines: string[] }>('scripts:log', cb),
  },
  copy: {
    status: () => ipcRenderer.invoke('copy:status'),
  },
  polymarket: {
    marketUrl: (args) => ipcRenderer.invoke('polymarket:marketUrl', args),
  },
  logs: {
    tail: (limit?: number): Promise<LogEntry[]> => ipcRenderer.invoke('logs:tail', limit),
    onAppend: (cb) => sub<LogEntry>('logs:append', cb),
    clear: () => ipcRenderer.invoke('logs:clear'),
    openFolder: () => ipcRenderer.invoke('logs:openFolder'),
  },
  window: {
    minimize: () => ipcRenderer.send('window:minimize'),
    maximize: () => ipcRenderer.send('window:maximize'),
    close: () => ipcRenderer.send('window:close'),
    isMaximized: () => ipcRenderer.invoke('window:isMaximized'),
    onMaximizeChange: (cb) => sub<boolean>('window:maximizeChange', cb),
  },
};

contextBridge.exposeInMainWorld('rom', api);
