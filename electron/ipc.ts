import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type {
  ActionResult,
  AppState,
  BotPosition,
  CredentialsInput,
  CredentialsState,
  PositionFilter,
  Profile,
  ProfileScope,
  SignalFilter,
  TraderConfig,
} from '../shared/types';
import { setStartWithWindows } from './system/autostart';
import { pythonBackend } from './system/python-backend';
import * as accounts from './system/accounts';
import * as store from './system/settings-store';
import { validateConfigPatch } from './system/config-validate';
import { findStrategy, listStrategies } from './system/strategies';

const ok = <T>(data?: T, message?: string): ActionResult<T> => ({
  ok: true,
  data,
  message,
});
const err = (message: string): ActionResult => ({ ok: false, message });

function broadcastState(state: AppState): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send('state:changed', state);
    }
  }
}

function genId(): string {
  return `p_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e6).toString(36)}`;
}

function scopeOfKey(key: string): ProfileScope {
  if (key.startsWith('crypto15m')) return 'crypto';
  if (key.startsWith('copy')) return 'copy';
  return 'main';
}

function normScope(s: unknown): ProfileScope {
  return s === 'crypto' || s === 'copy' ? s : 'main';
}

function activeKeyFor(scope: ProfileScope): keyof AppState {
  return scope === 'crypto'
    ? 'activeCryptoProfileId'
    : scope === 'copy'
      ? 'activeCopyProfileId'
      : 'activeProfileId';
}

function scopedApplyPatch(cfg: TraderConfig, scope: ProfileScope): Partial<TraderConfig> {
  const patch: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(cfg)) {
    if (scopeOfKey(k) === scope) patch[k] = v;
  }

  if (scope === 'main') {
    delete patch.enableTrading;
    delete patch.mainPaperTrading;
    delete patch.network;
  } else if (scope === 'crypto') {
    delete patch.crypto15mEnabled;
  } else {
    delete patch.copyEnabled;
  }
  return patch as Partial<TraderConfig>;
}

async function pushConfigToBackend(): Promise<void> {
  if (!pythonBackend.isRunning()) return;
  const state = store.get();
  try {
    await pythonBackend.request('setConfig', { config: state.config });
  } catch (e) {}
}

const RUN_ONCE_ACTIONS = new Set([
  'syncMarkets', 'pollOrders', 'resolveAll', 'reconcilePositions',
  'syncPositions', 'recomputePnl', 'reconcileFills', 'auditPnl',
  'recoverOrder',
]);

export function registerIpc(): void {
  ipcMain.handle('app:version', () => app.getVersion());
  ipcMain.handle('app:openExternal', async (_e, url: string) => {
    if (typeof url === 'string' && /^(https?|mailto):/i.test(url)) {
      await shell.openExternal(url);
    }
  });
  ipcMain.handle('app:showItemInFolder', async (_e, p: string) => {
    shell.showItemInFolder(p);
  });
  ipcMain.handle('app:getUserDataPath', () => app.getPath('userData'));

  ipcMain.handle('accounts:current', () => accounts.currentAccount());
  ipcMain.handle('accounts:list', () => accounts.listAccounts());
  ipcMain.handle('accounts:create', (_e, name: string) => accounts.createAccount(name));
  ipcMain.handle('accounts:launch', (_e, name: string) => accounts.launchAccount(name));

  ipcMain.handle('state:get', () => store.get());
  ipcMain.handle('state:setStartMinimized', (_e, v: boolean) => {
    const next = store.save({ ...store.get(), startMinimized: !!v });
    broadcastState(next);
    return ok();
  });
  ipcMain.handle('state:setStartWithWindows', (_e, v: boolean) => {
    setStartWithWindows(!!v);
    const next = store.save({ ...store.get(), startWithWindows: !!v });
    broadcastState(next);
    return ok();
  });
  ipcMain.handle('state:setEnableDiscordRpc', async () => {
    return ok();
  });
  ipcMain.handle('state:acceptDisclaimer', () => {
    const next = store.save({ ...store.get(), acceptedDisclaimer: true });
    broadcastState(next);
    return ok();
  });

  ipcMain.handle('state:resetOnboarding', () => {
    const next = store.save({ ...store.get(), acceptedDisclaimer: false });
    broadcastState(next);
    return ok();
  });

  ipcMain.handle('config:get', () => store.get().config);
  ipcMain.handle('config:update', async (_e, patch: Partial<TraderConfig>) => {
    const v = validateConfigPatch(patch);
    if (!v.ok) {
      throw new Error(`Invalid config patch: ${v.errors!.join('; ')}`);
    }
    const next = store.patchConfig(v.value! as Partial<TraderConfig>);
    broadcastState(next);
    await pushConfigToBackend();
    return next.config;
  });
  ipcMain.handle('config:replace', async (_e, cfg: TraderConfig) => {
    const v = validateConfigPatch(cfg);
    if (!v.ok) {
      throw new Error(`Invalid config: ${v.errors!.join('; ')}`);
    }
    const next = store.replaceConfig(v.value! as unknown as TraderConfig);
    broadcastState(next);
    await pushConfigToBackend();
    return next.config;
  });
  ipcMain.handle('config:reset', async () => {
    const next = store.resetConfig();
    broadcastState(next);
    await pushConfigToBackend();
    return next.config;
  });
  ipcMain.handle('config:listStrategies', () => listStrategies());
  ipcMain.handle('config:applyStrategy', async (_e, id: string) => {
    const s = findStrategy(id);

    if (!s || s.comingSoon) return store.get().config;

    const cur = store.get();

    const PRESERVE_PREFIXES = ['crypto15m', 'copy', 'script'];
    const PRESERVE_KEYS = new Set([
      'eventWebhookUrl', 'statsWebhookUrl', 'whaleWebhookUrl',
      'momentumWebhookUrl', 'enableDiscord', 'statsPushInterval',
      'statsChartWindowHours',
    ]);
    const preserved = Object.fromEntries(
      Object.entries(cur.config).filter(
        ([k]) => PRESERVE_PREFIXES.some((p) => k.startsWith(p)) || PRESERVE_KEYS.has(k),
      ),
    ) as Partial<TraderConfig>;
    const next = store.replaceConfig({
      ...s.config,
      ...preserved,
      network: cur.config.network,

      enableTrading: cur.config.enableTrading,
      mainPaperTrading: cur.config.mainPaperTrading,
      mainPaperBankrollUsd: cur.config.mainPaperBankrollUsd,
    });
    const stateNext = store.save({ ...store.get(), activeProfileId: id });
    broadcastState(stateNext);
    await pushConfigToBackend();
    return next.config;
  });

  ipcMain.handle('profiles:list', () => store.get().customProfiles);
  ipcMain.handle('profiles:save', (_e, name: string, description?: string, scope?: ProfileScope) => {
    if (!name?.trim()) return err('Profile name required');
    const sc = normScope(scope);
    const cur = store.get();
    const now = new Date().toISOString();
    const profile: Profile = {
      id: genId(),
      name: name.trim(),
      description: description?.trim() || undefined,
      scope: sc,
      createdAt: now,
      updatedAt: now,

      config: structuredClone(cur.config),
    };
    const next = store.save({
      ...cur,
      customProfiles: [...cur.customProfiles, profile],
      [activeKeyFor(sc)]: profile.id,
    });
    broadcastState(next);
    const label = sc === 'crypto' ? 'crypto' : sc === 'copy' ? 'copy-trading' : 'main-engine';
    return ok(profile, `Saved ${label} profile "${profile.name}"`);
  });
  ipcMain.handle('profiles:apply', async (_e, id: string) => {
    const cur = store.get();
    const p = cur.customProfiles.find((x) => x.id === id);
    if (!p) {
      const s = findStrategy(id);
      if (s?.comingSoon) return err(`"${s.name}" is coming soon`);
      if (s) {
        const next = store.patchConfig(scopedApplyPatch(s.config, 'main'));
        const stateNext = store.save({ ...store.get(), activeProfileId: id });
        broadcastState(stateNext);
        await pushConfigToBackend();
        return ok(next.config, `Applied "${s.name}"`);
      }
      return err('Profile not found');
    }

    const sc = normScope(p.scope);
    const next = store.patchConfig(scopedApplyPatch(p.config, sc));
    const stateNext = store.save({ ...store.get(), [activeKeyFor(sc)]: id });
    broadcastState(stateNext);
    await pushConfigToBackend();
    const label = sc === 'crypto' ? 'crypto' : sc === 'copy' ? 'copy-trading' : 'main-engine';
    return ok(next.config, `Applied ${label} profile "${p.name}"`);
  });
  ipcMain.handle('profiles:rename', (_e, id: string, name: string) => {
    if (!name?.trim()) return err('Name required');
    const cur = store.get();
    const idx = cur.customProfiles.findIndex((p) => p.id === id);
    if (idx < 0) return err('Profile not found');
    const updated = [...cur.customProfiles];
    updated[idx] = { ...updated[idx], name: name.trim(), updatedAt: new Date().toISOString() };
    const next = store.save({ ...cur, customProfiles: updated });
    broadcastState(next);
    return ok();
  });
  ipcMain.handle('profiles:delete', (_e, id: string) => {
    const cur = store.get();
    const next = store.save({
      ...cur,
      customProfiles: cur.customProfiles.filter((p) => p.id !== id),
      activeProfileId: cur.activeProfileId === id ? null : cur.activeProfileId,
      activeCryptoProfileId: cur.activeCryptoProfileId === id ? null : cur.activeCryptoProfileId,
      activeCopyProfileId: cur.activeCopyProfileId === id ? null : cur.activeCopyProfileId,
    });
    broadcastState(next);
    return ok();
  });
  ipcMain.handle('profiles:duplicate', (_e, id: string) => {
    const cur = store.get();
    const orig = cur.customProfiles.find((p) => p.id === id);
    if (!orig) return err('Profile not found');
    const dup: Profile = {
      ...orig,
      id: genId(),
      name: `${orig.name} (copy)`,
      config: structuredClone(orig.config),
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    const next = store.save({
      ...cur,
      customProfiles: [...cur.customProfiles, dup],
    });
    broadcastState(next);
    return ok(dup);
  });
  ipcMain.handle('profiles:export', (_e, id: string) => {
    const cur = store.get();
    const p = cur.customProfiles.find((x) => x.id === id);
    if (!p) return err('Profile not found');
    const json = JSON.stringify(
      { romTraderProfile: 1, profile: p },
      null,
      2,
    );
    return ok(json);
  });
  ipcMain.handle('profiles:import', (_e, json: string) => {
    try {
      const parsed = JSON.parse(json);

      const norm = store.mergeProfile(parsed?.profile);
      if (!norm) return err('Not a valid ROM PolyBot profile');
      const cur = store.get();
      const dup: Profile = {
        ...norm,
        id: genId(),
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      const next = store.save({ ...cur, customProfiles: [...cur.customProfiles, dup] });
      broadcastState(next);
      return ok(dup, `Imported "${dup.name}"`);
    } catch (e: any) {
      return err(`Invalid profile JSON: ${e?.message || e}`);
    }
  });

  const emptyCred = () => ({
    env: 'mainnet' as const, hasWalletKey: false, hasApiCreds: false,
    address: '', addressPreview: '',
  });
  const emptyAllCreds = () => ({
    current: 'mainnet' as const,
    mainnet: emptyCred(),
  });
  ipcMain.handle('credentials:status', async () => {
    if (!pythonBackend.isRunning()) {
      return emptyCred() satisfies CredentialsState;
    }
    const all = await pythonBackend.request('credentialStatus', {}) as any;
    if (all && all.current && all[all.current]) {
      return all[all.current] as CredentialsState;
    }
    return all as CredentialsState;
  });
  ipcMain.handle('credentials:statusAll', async () => {
    if (!pythonBackend.isRunning()) return emptyAllCreds();
    return await pythonBackend.request('credentialStatus', {});
  });
  ipcMain.handle('credentials:save', async (_e, input: CredentialsInput) => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      await pythonBackend.request('setCredentials', input);
      return ok();
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });
  ipcMain.handle('credentials:test', async (_e, env?: string) => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      const data = await pythonBackend.request('testCredentials', env ? { env } : {});
      return ok(data, 'Connected to Polymarket');
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });
  ipcMain.handle('credentials:clear', async (_e, env?: string) => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      await pythonBackend.request('clearCredentials', env ? { env } : {});
      return ok();
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });

  ipcMain.handle('backend:info', () => pythonBackend.info());
  ipcMain.handle('backend:start', async () => {
    await pythonBackend.start();
    return ok();
  });
  ipcMain.handle('backend:stop', async () => {
    await pythonBackend.stop();
    return ok();
  });
  ipcMain.handle('backend:restart', async () => {
    await pythonBackend.restart();
    return ok();
  });
  ipcMain.handle('backend:runOnce', async (_e, action: string, payload?: unknown) => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    if (typeof action !== 'string' || !RUN_ONCE_ACTIONS.has(action)) {
      return err('Unknown action');
    }
    // Only recoverOrder carries arguments, and the backend indexes them
    // directly. Build the request from validated fields rather than
    // forwarding the renderer's object, so nothing else can reach the
    // backend through this channel.
    const request: Record<string, unknown> = { action };
    if (action === 'recoverOrder') {
      const ids = (payload ?? {}) as Record<string, unknown>;
      const localOrderId = typeof ids.localOrderId === 'string' ? ids.localOrderId.trim() : '';
      const exchangeOrderId =
        typeof ids.exchangeOrderId === 'string' ? ids.exchangeOrderId.trim() : '';
      if (!localOrderId || !exchangeOrderId) {
        return err('Recovery needs both the local order ID and the exchange order ID');
      }
      if (localOrderId.length > 200 || exchangeOrderId.length > 200) {
        return err('Order IDs are too long');
      }
      request.localOrderId = localOrderId;
      request.exchangeOrderId = exchangeOrderId;
    }
    try {
      const data = await pythonBackend.request('runOnce', request);
      return ok(data, (data as any)?.summary || 'Done');
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });

  ipcMain.handle('trading:setEnabled', async (_e, enabled: boolean) => {
    const next = store.patchConfig({
      enableTrading: !!enabled,
      ...(enabled ? { mainPaperTrading: false } : {}),
    });
    broadcastState(next);
    await pushConfigToBackend();
    return ok();
  });
  ipcMain.handle('trading:setPaperEnabled', async (_e, enabled: boolean) => {
    const next = store.patchConfig({
      mainPaperTrading: !!enabled,
      ...(enabled ? { enableTrading: false } : {}),
    });
    broadcastState(next);
    await pushConfigToBackend();
    return ok();
  });
  ipcMain.handle('trading:cancelAllOpen', async () => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      const data = await pythonBackend.request('cancelAllOpen', {});
      return ok(data, `Canceled ${data.canceled} order(s)`);
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });
  ipcMain.handle('trading:flatten', async () => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      const data = await pythonBackend.request('flatten', {});
      return ok(data, `Flattened ${data.closed} order(s)`);
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });
  ipcMain.handle('trading:status', async () => {
    if (!pythonBackend.isRunning()) {
      return {
        main: [{ id: 'backend', label: 'Backend running', state: 'blocked', reason: 'backend not running' }],
        mainMode: 'paused', mainState: 'blocked', mainSummary: 'Engine offline.', mainLastCycleAt: null,
        mainFilterCounts: {}, mainCandidates: 0, mainPlaced: 0,
        mainPaper: { bankrollUsd: 1000, availableUsd: 1000, open: 0, resolved: 0, wins: 0, losses: 0, pnlUsd: 0 },
        c15: { enabled: false, live: false, authed: false, env: 'mainnet', blockReasons: {} },
      };
    }
    return await pythonBackend.request('tradingStatus', {});
  });

  ipcMain.handle('app:factoryReset', async () => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      const data = await pythonBackend.request('factoryReset', {}) as any;
      const total = Object.values(data?.deleted || {}).reduce(
        (a: number, b: any) => a + (Number(b) || 0), 0,
      );
      return ok(data, `Cleared ${total} row(s)`);
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });

  ipcMain.handle('app:clearHistory', async () => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      const data = await pythonBackend.request('clearHistory', {}) as any;
      const total = Object.values(data?.deleted || {}).reduce(
        (a: number, b: any) => a + (Number(b) || 0), 0,
      );
      return ok(data, `Cleared ${total} row(s) of history`);
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });

  ipcMain.handle('data:account', async () => {
    if (!pythonBackend.isRunning()) {
      return {
        cashUsd: 0, portfolioUsd: 0, totalUsd: 0,
        startBankrollUsd: store.get().config.startBankrollUsd,
        roiPct: 0, realizedPnlUsd: 0, unrealizedPnlUsd: 0,
        openCostUsd: 0, feesUsd: 0, wins: 0, losses: 0, winRate: 0,
        pendingCount: 0, openCount: 0, resolvedCount: 0, totalOpened: 0,
        byNetwork: {
          mainnet: { wins: 0, losses: 0, realizedPnl: 0 },
        },
      };
    }
    return await pythonBackend.request('account', {});
  });
  ipcMain.handle('data:pnlSeries', async (_e, sinceHours?: number) => {
    if (!pythonBackend.isRunning()) return [];
    return await pythonBackend.request('pnlSeries', { sinceHours });
  });
  ipcMain.handle('data:positions', async (_e, filter?: PositionFilter) => {
    if (!pythonBackend.isRunning()) return [];
    return await pythonBackend.request('positions', filter || {});
  });
  ipcMain.handle('data:signals', async (_e, filter?: SignalFilter) => {
    if (!pythonBackend.isRunning()) return [];
    return await pythonBackend.request('signals', filter || {});
  });
  ipcMain.handle('data:scannerStats', async () => {
    if (!pythonBackend.isRunning()) {
      return {
        whales: { total: 0, sent: 0, resolved: 0, winRate: 0 },
        momentum: { total: 0, sent: 0, resolved: 0, winRate: 0 },
        marketsTracked: 0,
        lastWhaleScanAt: null,
        lastMomentumScanAt: null,
        lastTradeScanAt: null,
      };
    }
    return await pythonBackend.request('scannerStats', {});
  });
  ipcMain.handle('data:botRuns', async (_e, env?: string | null, limit?: number) => {
    if (!pythonBackend.isRunning()) {
      return { runs: [], activeRunId: 0, activeRun: null };
    }
    const params: Record<string, unknown> = {};
    if (env) params.env = env;
    if (limit) params.limit = limit;
    return await pythonBackend.request('botRuns', params);
  });

  ipcMain.handle('crypto15m:snapshot', async () => {
    if (!pythonBackend.isRunning()) {
      return {
        fetchedAt: new Date().toISOString(),
        spotOk: false,
        spotSource: 'unavailable',
        constants: {
          timeDelayMin: 8, entryThreshold: 0.95, entryMax: 0.98,
          exitThreshold: 0.4, minDeltaPct: 0, entryDiff: 0.02, directionMode: 'favorite',
          entryStyle: 'maker', hoursStartUtc: 0, hoursEndUtc: 24,
        },
        assets: [],
      };
    }
    return await pythonBackend.request('crypto15m', {});
  });
  ipcMain.handle('crypto15m:status', async () => {
    if (!pythonBackend.isRunning()) {
      return {
        enabled: false, authed: false, trading: false,
        orderSize: 1, maxConcurrent: 7, env: 'mainnet',
        sizing: {
          mode: 'fixed', balancePct: 0.02, maxLossPct: 0, balanceUsd: 0,
          estPriceCents: 0, estContracts: 1, estCostUsd: 0, note: '',
        },
        stats: { openCount: 0, wins: 0, losses: 0, realizedPnlUsd: 0, total: 0 },
        open: [], recent: [],
      };
    }
    return await pythonBackend.request('crypto15mStatus', {});
  });
  ipcMain.handle('crypto15m:history', async (_e, opts?: { limit?: number }) => {
    if (!pythonBackend.isRunning()) return { rows: [] };
    return await pythonBackend.request('c15History', { limit: opts?.limit ?? 300 });
  });
  ipcMain.handle('crypto15m:backtest', async (_e, args?: { sinceDays?: number; config?: Record<string, unknown> }) => {
    if (!pythonBackend.isRunning()) return null;

    return await pythonBackend.request('c15Backtest', args || {}, 120_000);
  });
  ipcMain.handle('main:backtest', async (_e, args?: { sinceDays?: number; config?: Record<string, unknown> }) => {
    if (!pythonBackend.isRunning()) return null;
    return await pythonBackend.request('mainBacktest', args || {}, 120_000);
  });
  ipcMain.handle('trading:calibration', async () => {
    if (!pythonBackend.isRunning()) throw new Error('Start the engine to check calibration evidence.');
    return await pythonBackend.request('signalCalibration', {}, 30_000);
  });
  ipcMain.handle('trading:practicePerformance', async () => {
    if (!pythonBackend.isRunning()) throw new Error('Start the engine to rank practice performance.');
    return await pythonBackend.request('practicePerformance', {}, 30_000);
  });
  ipcMain.handle('trading:allocationPlan', async () => {
    if (!pythonBackend.isRunning()) throw new Error('Start the engine to calculate evidence allocation.');
    return await pythonBackend.request('strategyAllocation', {}, 30_000);
  });
  ipcMain.handle('backtest:collection', async () => {
    if (!pythonBackend.isRunning()) return null;
    return await pythonBackend.request('collectionStats', {});
  });
  ipcMain.handle('backtest:export', async () => {
    if (!pythonBackend.isRunning()) return null;
    const r = await pythonBackend.request('exportResearch', {}, 120_000) as { dir?: string } | null;
    if (r?.dir) shell.showItemInFolder(r.dir);
    return r;
  });

  ipcMain.handle('scripts:list', async () => {
    if (!pythonBackend.isRunning()) return { scripts: [] };
    return await pythonBackend.request('scriptsList', {});
  });
  ipcMain.handle('scripts:save', async (_e, s: Record<string, unknown>) => {
    return await pythonBackend.request('scriptSave', s || {});
  });
  ipcMain.handle('scripts:delete', async (_e, id: string) => {
    return await pythonBackend.request('scriptDelete', { id });
  });
  ipcMain.handle('scripts:setEnabled', async (_e, id: string, enabled: boolean) => {
    return await pythonBackend.request('scriptSetEnabled', { id, enabled });
  });
  ipcMain.handle('scripts:setAssets', async (_e, id: string, assets: string[] | null) => {
    return await pythonBackend.request('scriptSetAssets', { id, assets });
  });
  ipcMain.handle('scripts:exportFile', async (e, name: string, code: string) => {
    const win = BrowserWindow.fromWebContents(e.sender) ?? undefined;
    const safe = (name || 'strategy').replace(/[^\w.-]+/g, '-').slice(0, 60);
    const res = await dialog.showSaveDialog(win!, {
      title: 'Export strategy script',
      defaultPath: join(app.getPath('documents'), `${safe}.py`),
      filters: [{ name: 'Python script', extensions: ['py'] }],
    });
    if (res.canceled || !res.filePath) return err('canceled');
    writeFileSync(res.filePath, code, 'utf-8');
    shell.showItemInFolder(res.filePath);
    return ok(res.filePath);
  });
  ipcMain.handle('scripts:importFile', async (e) => {
    const win = BrowserWindow.fromWebContents(e.sender) ?? undefined;
    const res = await dialog.showOpenDialog(win!, {
      title: 'Import strategy script',
      properties: ['openFile'],
      filters: [{ name: 'Python script', extensions: ['py', 'txt'] }],
    });
    if (res.canceled || !res.filePaths?.[0]) return err('canceled');
    try {
      const code = readFileSync(res.filePaths[0], 'utf-8');

      if (code.length > 128 * 1024) return err('Script exceeds 128KB');
      return ok(code);
    } catch (e2: any) {
      return err(e2?.message || 'Could not read that file');
    }
  });
  ipcMain.handle('scripts:setDryRun', async (_e, id: string, dryRun: boolean) => {
    return await pythonBackend.request('scriptSetDryRun', { id, dryRun });
  });
  ipcMain.handle('scripts:shadowOrders', async (_e, id: string, limit?: number) => {
    return await pythonBackend.request('scriptShadowOrders', { id, limit });
  });
  ipcMain.handle('scripts:validate', async (_e, code: string) => {
    return await pythonBackend.request('scriptValidate', { code });
  });
  ipcMain.handle('scripts:backtest', async (_e, args?: Record<string, unknown>) => {
    if (!pythonBackend.isRunning()) return null;

    return await pythonBackend.request('scriptBacktest', args || {}, 120_000);
  });
  ipcMain.handle('scripts:contextPack', async () => {
    return await pythonBackend.request('scriptContextPack', {}, 60_000);
  });
  ipcMain.handle('scripts:docs', async () => {
    return await pythonBackend.request('scriptApiDocs', {}, 60_000);
  });

  ipcMain.handle('scripts:exportPack', async (e) => {
    if (!pythonBackend.isRunning()) return err('Engine not running');
    const r = (await pythonBackend.request('scriptContextPack', {})) as { text?: string } | null;
    if (!r?.text) return err('Context pack generation failed');
    const win = BrowserWindow.fromWebContents(e.sender) ?? undefined;
    const res = await dialog.showSaveDialog(win!, {
      title: 'Save AI context pack',
      defaultPath: join(app.getPath('documents'), 'rom-ai-context-pack.txt'),
      filters: [{ name: 'Text file', extensions: ['txt'] }],
    });
    if (res.canceled || !res.filePath) return err('canceled');
    writeFileSync(res.filePath, r.text, 'utf-8');
    shell.showItemInFolder(res.filePath);
    return ok(res.filePath);
  });

  ipcMain.handle('copy:status', async () => {
    if (!pythonBackend.isRunning()) {
      return {
        enabled: false, authed: false, trading: false,
        wallets: [], openCopies: 0, todayPnlUsd: 0, lossLimitHit: false,
        sizing: { mode: 'fixed', fixedUsd: 10, balancePct: 0.02 },
        maxConcurrent: 10, entryMaxCents: 95,
      };
    }
    return await pythonBackend.request('copyStatus', {});
  });

  ipcMain.handle(
    'polymarket:marketUrl',
    async (_e, args?: { eventTicker?: string; ticker?: string; env?: string }) => {
      if (!pythonBackend.isRunning()) return { url: '' };
      return await pythonBackend.request('polymarketUrl', args || {});
    },
  );

  ipcMain.handle('logs:tail', async (_e, _limit?: number) => {
    return logsBuffer.slice(-1 * (_limit || 500));
  });
  ipcMain.handle('logs:clear', () => {
    logsBuffer.length = 0;
    return ok();
  });
  ipcMain.handle('logs:openFolder', async () => {
    const p = join(app.getPath('userData'), 'logs');
    if (existsSync(p)) shell.openPath(p);
  });

  ipcMain.on('window:minimize', (e) => {
    BrowserWindow.fromWebContents(e.sender)?.minimize();
  });
  ipcMain.on('window:maximize', (e) => {
    const w = BrowserWindow.fromWebContents(e.sender);
    if (!w) return;
    if (w.isMaximized()) w.unmaximize();
    else w.maximize();
  });
  ipcMain.on('window:close', (e) => {
    BrowserWindow.fromWebContents(e.sender)?.close();
  });
  ipcMain.handle('window:isMaximized', (e) => {
    return BrowserWindow.fromWebContents(e.sender)?.isMaximized() ?? false;
  });
}

const MAX_LOGS = 5000;
export const logsBuffer: any[] = [];

export function appendLog(entry: any): void {
  logsBuffer.push(entry);
  if (logsBuffer.length > MAX_LOGS) logsBuffer.shift();
}

export { broadcastState };
