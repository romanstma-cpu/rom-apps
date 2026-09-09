import { app } from 'electron';
import { copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import type { AppState, Profile, TraderConfig } from '../../shared/types';

const userDataDir = (): string => app.getPath('userData');

const settingsFile = (): string => join(userDataDir(), 'settings.json');

function vaultSettingsFile(): string | null {
  try {
    const base = process.env.LOCALAPPDATA
      ? join(process.env.LOCALAPPDATA, 'ROM PolyBot Vault')
      : join(app.getPath('home'), '.rom-polybot-vault');
    const ud = userDataDir();
    const tag = basename(dirname(ud)).toLowerCase() === 'accounts'
      ? basename(ud)
      : 'default';
    const dir = join(base, tag);
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    return join(dir, 'settings.json');
  } catch {
    return null;
  }
}

/**
 * Minutes from UTC for this machine's local zone (ET in summer => -240).
 * `Date#getTimezoneOffset` reports the inverse, hence the negation.
 */
export function hostOffsetMin(): number {
  return -new Date().getTimezoneOffset();
}

export const DEFAULT_CONFIG: TraderConfig = {
  network: 'mainnet',
  enableTrading: false,
  mainPaperTrading: false,
  mainPaperBankrollUsd: 1000,

  tradeWhales: true,
  tradeMomentum: true,
  tradeConvergence: false,

  minEdgePtsWhale: 5.0,
  minEdgePtsMomentum: 5.0,
  minConfidenceWhale: 55.0,
  minConfidenceMomentum: 55.0,
  minEntryPriceCents: 15,
  maxEntryPriceCents: 85,
  maxResolutionDays: 0,
  allowedMomentumSignalTypes: ['trade_cluster'],
  allowedCategories: null,
  allowedWhaleCategories: null,
  allowedMomentumCategories: null,
  contrarianOnly: true,

  useRules: false,
  rules: [],

  baseSizeFraction: 0.03,
  minSizeFraction: 0.02,
  maxSizeFraction: 0.06,
  sizingBaseEdge: 5.0,
  sizingMaxEdge: 20.0,
  kellyFraction: 0.25,
  hardMaxPositionUsd: 50.0,
  minCashReserveFraction: 0.05,

  orderStyle: 'limit_cross',
  crossSpreadFallbackOffset: 2,
  orderExpirationSec: 300,

  maxOpenPositions: 25,
  maxPositionsPerEvent: 1,
  maxDailyNewPositions: 40,
  unlimitedDailyNewPositions: false,
  maxTotalExposureFraction: 0.75,

  tradeScanInterval: 20,
  positionPollInterval: 30,
  balancePollInterval: 60,
  resolutionCheckInterval: 300,
  whaleScanInterval: 120,
  momentumScanInterval: 90,
  marketRefreshInterval: 300,

  maxSignalAgeSec: 120,

  startBankrollUsd: 0.0,
  stopLossOnDay: -50.0,
  takeProfitOnDay: 0.0,
  flattenOnDailyStop: false,

  tradingHoursEnabled: false,
  tradingHoursStart: '00:00',
  tradingHoursEnd: '23:59',
  tradingDays: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'],
  tradingTimezoneOffsetMin: hostOffsetMin(),

  minWhaleUsd: 2500.0,
  minWhaleConfidence: 30.0,
  minWhaleEdge: 2.0,
  minMomentumConfidence: 0.0,
  minMomentumEdge: 5.0,
  minEntryPriceFrac: 0.5,

  eventWebhookUrl: '',
  statsWebhookUrl: '',
  whaleWebhookUrl: '',
  momentumWebhookUrl: '',
  statsPushInterval: 1800,
  statsChartWindowHours: 168,
  enableDiscord: true,

  crypto15mEnabled: false,
  crypto15mSizingMode: 'fixed',
  crypto15mOrderSize: 5,
  crypto15mBalancePct: 0.02,
  crypto15mMaxLossPct: 0,
  crypto15mStreakSizing: false,
  crypto15mStreakLossPct: 20,
  crypto15mStreakWinPct: 0,
  crypto15mStreakMaxMult: 4,
  crypto15mMaxConcurrent: 7,
  crypto15mTakeProfitTotal: 0,
  crypto15mDirectionMode: 'favorite',
  crypto15mModelMinProb: 0.97,
  crypto15mModelMinEdgeCents: 2.0,
  crypto15mModelFinalMinute: true,
  crypto15mModelAutopause: true,
  crypto15mModelMaxBookGapCents: 25,
  crypto15mSpotWs: true,
  crypto15mRtdsWs: true,
  crypto15mPairedMode: false,
  crypto15mPairedMaxCombinedCents: 99,
  crypto15mPairedTilt1Cents: 3,
  crypto15mPairedTilt2Cents: 6,
  crypto15mPairedTilt3Cents: 10,
  crypto15mSellIntoStrength: false,
  crypto15mSellStrengthCents: 80,
  crypto15mTimeDelayMin: 8,
  crypto15mEntryThreshold: 0.95,
  crypto15mEntryMax: 0.98,
  crypto15mExitThreshold: 0.4,
  crypto15mTakeProfit: 0,
  crypto15mStopLossPct: 0,
  crypto15mMinRsi: 0,
  crypto15mMinMacdHist: 0,
  crypto15mMinDeltaPct: 0,
  crypto15mEntryDiff: 0.02,
  crypto15mEntryStyle: 'taker',
  crypto15mTakerFak: true,
  crypto15mMakerCancelMin: 1,
  crypto15mMakerEscalate: true,
  crypto15mHoursStartUtc: 0,
  crypto15mHoursEndUtc: 24,
  crypto15mRecordSignals: true,
  mainRecordSignals: true,
  crypto15mArbDetect: true,
  crypto15mArbMinEdgeCents: 1,
  crypto15mImbalanceDetect: true,
  crypto15mImbalanceLevels: 3,
  crypto15mImbalanceGate: false,
  crypto15mImbalanceGateMin: 0.2,
  crypto15mIndicatorDetect: true,
  crypto15mWsBook: true,
  crypto15mUseRules: false,
  crypto15mRules: [],

  copyEnabled: false,
  copyWallets: [],
  copySizingMode: 'fixed',
  copyFixedUsd: 10,
  copyBalancePct: 0.02,
  copyMinTradeUsd: 25,
  copyMaxConcurrent: 10,
  copyEntryMaxCents: 95,
  copyDailyLossLimit: -50,
  copyPollSec: 10,
  copyFastPollSec: 5,
  copyActivityWs: true,
  copyMirrorReductions: true,
  copyReduceThreshold: 0.25,

  scriptsLiveEnabled: false,
  scriptPollSec: 5,
  scriptMaxEntryCents: 97,
  scriptMaxContracts: 20,
  scriptMaxOpen: 2,
  scriptDailyLossUsd: 25,
  scriptMaxEnabled: 10,

  scriptMarketLimit: 150,
  scriptMarketMinVolume: 5000,

  scriptMarketMaxSpreadCents: 2,
};

export const DEFAULT_STATE: AppState = {
  config: { ...DEFAULT_CONFIG },
  activeProfileId: null,
  activeCryptoProfileId: null,
  activeCopyProfileId: null,
  customProfiles: [],
  startMinimized: false,
  startWithWindows: false,
  enableDiscordRpc: true,
  acceptedDisclaimer: false,
  windowBounds: null,
  tradingDayMigrated: true,
};

let cached: AppState | null = null;

let vaultMirrorAllowed = false;

function ensureDir(): void {
  const d = userDataDir();
  if (!existsSync(d)) mkdirSync(d, { recursive: true });
}

function mergeConfig(loaded: Partial<TraderConfig> | undefined): TraderConfig {
  return { ...DEFAULT_CONFIG, ...(loaded || {}) };
}

export function mergeProfile(loaded: any): Profile | null {
  if (!loaded || typeof loaded !== 'object') return null;
  if (!loaded.id || !loaded.name || !loaded.config) return null;
  const scope = loaded.scope === 'crypto' || loaded.scope === 'copy' ? loaded.scope : 'main';
  return {
    id: String(loaded.id),
    name: String(loaded.name),
    description: loaded.description ? String(loaded.description) : undefined,
    scope,
    createdAt: loaded.createdAt || new Date().toISOString(),
    updatedAt: loaded.updatedAt || new Date().toISOString(),
    builtin: !!loaded.builtin,
    config: mergeConfig(loaded.config),
  };
}

/**
 * Before 2.8 the daily stop-loss and new-position caps always rolled over at
 * UTC midnight while the trading-hours gate used this offset, so a US user's
 * limits reset mid-session. Adopt the host zone for installs that still carry
 * the old `0` default and never configured trading hours - an explicit choice
 * of UTC (or any saved offset) is left alone.
 */
function migrateTradingDay(loaded: any, config: TraderConfig): TraderConfig {
  if (loaded?.tradingDayMigrated) return config;
  if (config.tradingHoursEnabled) return config;
  if (Number(loaded?.config?.tradingTimezoneOffsetMin ?? 0) !== 0) return config;
  const off = hostOffsetMin();
  if (off === 0) return config;
  console.error(
    `trading-day boundary migrated from UTC to host offset ${off}min ` +
    `(daily limits now reset at your local midnight)`,
  );
  return { ...config, tradingTimezoneOffsetMin: off };
}

function mergeState(loaded: any): AppState {
  if (!loaded || typeof loaded !== 'object') return { ...DEFAULT_STATE };
  const profiles: Profile[] = Array.isArray(loaded.customProfiles)
    ? loaded.customProfiles.map(mergeProfile).filter((p: Profile | null): p is Profile => p !== null)
    : [];
  return {
    config: migrateTradingDay(loaded, mergeConfig(loaded.config)),
    activeProfileId: loaded.activeProfileId || null,
    activeCryptoProfileId: loaded.activeCryptoProfileId || null,
    activeCopyProfileId: loaded.activeCopyProfileId || null,
    customProfiles: profiles,
    startMinimized: !!loaded.startMinimized,
    startWithWindows: !!loaded.startWithWindows,
    enableDiscordRpc:
      typeof loaded.enableDiscordRpc === 'boolean' ? loaded.enableDiscordRpc : true,
    acceptedDisclaimer: !!loaded.acceptedDisclaimer,
    windowBounds: loaded.windowBounds || null,
    tradingDayMigrated: true,
  };
}

function readStateFile(path: string): AppState {
  const parsed = JSON.parse(readFileSync(path, 'utf-8'));
  if (!parsed || typeof parsed !== 'object') throw new Error('not a settings object');
  return mergeState(parsed);
}

export function load(): AppState {
  if (cached) return cached;
  ensureDir();
  const f = settingsFile();
  if (!existsSync(f)) {
    for (const candidate of [`${f}.bak`, vaultSettingsFile()]) {
      if (!candidate || !existsSync(candidate)) continue;
      try {
        cached = readStateFile(candidate);
        vaultMirrorAllowed = true;
        console.error(`settings.json missing — restored from ${candidate}`);
        save(cached);
        return cached;
      } catch (e) {
        console.error(`settings restore from ${candidate} failed:`, e);
      }
    }
    cached = { ...DEFAULT_STATE };
    save(cached);
    return cached;
  }
  try {
    cached = readStateFile(f);
    vaultMirrorAllowed = true;
  } catch (e) {
    console.error('settings parse failed:', e);

    try {
      const bad = `${f}.corrupt-${Date.now()}`;
      copyFileSync(f, bad);
      console.error(`backed up corrupt settings to ${bad}`);
    } catch (be) {
      console.error('could not back up corrupt settings:', be);
    }

    for (const candidate of [`${f}.bak`, vaultSettingsFile()]) {
      if (!candidate || !existsSync(candidate)) continue;
      try {
        cached = readStateFile(candidate);
        vaultMirrorAllowed = true;
        console.error(`recovered settings from ${candidate}`);
        return cached;
      } catch (re) {
        console.error(`settings recovery from ${candidate} failed:`, re);
      }
    }

    cached = { ...DEFAULT_STATE };
  }
  return cached;
}

export function save(state: AppState): AppState {
  ensureDir();
  cached = state;
  const f = settingsFile();
  const tmp = `${f}.tmp`;
  writeFileSync(tmp, JSON.stringify(state, null, 2), 'utf-8');

  try {
    if (existsSync(f)) {
      JSON.parse(readFileSync(f, 'utf-8'));
      copyFileSync(f, `${f}.bak`);
    }
  } catch {}
  renameSync(tmp, f);

  try {
    const vf = vaultSettingsFile();
    if (vf && vaultMirrorAllowed) {
      const vtmp = `${vf}.tmp`;
      copyFileSync(f, vtmp);
      renameSync(vtmp, vf);
    }
  } catch {}
  return state;
}

export function get(): AppState {
  return cached ?? load();
}

export function patchConfig(patch: Partial<TraderConfig>): AppState {
  const cur = get();

  vaultMirrorAllowed = true;
  const next: AppState = { ...cur, config: { ...cur.config, ...patch } };
  return save(next);
}

export function replaceConfig(config: TraderConfig): AppState {
  const cur = get();
  vaultMirrorAllowed = true;
  const next: AppState = { ...cur, config: mergeConfig(config) };
  return save(next);
}

export function resetConfig(): AppState {
  const cur = get();
  vaultMirrorAllowed = true;
  const next: AppState = {
    ...cur, config: { ...DEFAULT_CONFIG },
    activeProfileId: null, activeCryptoProfileId: null, activeCopyProfileId: null,
  };
  return save(next);
}
