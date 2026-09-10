export type Network = 'mainnet';

export type OrderStyle = 'limit_cross' | 'limit_mid' | 'market';

export type SignalSource = 'whale' | 'momentum' | 'convergence' | 'external' | 'copy';

export interface RuleCondition {
  field: string;
  op: '>=' | '<=' | '>' | '<';
  value: number;
}

export interface TraderConfig {
  network: Network;
  enableTrading: boolean;
  mainPaperTrading: boolean;
  mainPaperBankrollUsd: number;

  tradeWhales: boolean;
  tradeMomentum: boolean;
  tradeConvergence: boolean;

  minEdgePtsWhale: number;
  minEdgePtsMomentum: number;
  minConfidenceWhale: number;
  minConfidenceMomentum: number;
  minEntryPriceCents: number;
  maxEntryPriceCents: number;
  maxResolutionDays?: number;
  allowedMomentumSignalTypes: string[];
  allowedCategories: string[] | null;

  allowedWhaleCategories: string[] | null;
  allowedMomentumCategories: string[] | null;
  contrarianOnly: boolean;

  useRules?: boolean;
  rules?: RuleCondition[];

  sizingMode?: 'percent' | 'contracts' | 'kelly';
  baseSizeFraction: number;
  minSizeFraction: number;
  maxSizeFraction: number;
  minContracts?: number;
  maxContracts?: number;
  sizingBaseEdge: number;
  sizingMaxEdge: number;
  kellyFraction?: number;
  hardMaxPositionUsd: number;
  minCashReserveFraction: number;

  orderStyle: OrderStyle;
  crossSpreadFallbackOffset: number;
  orderExpirationSec: number | null;

  maxOpenPositions: number;
  maxPositionsPerEvent: number;
  maxDailyNewPositions: number;

  unlimitedDailyNewPositions: boolean;
  maxTotalExposureFraction: number;

  tradeScanInterval: number;
  positionPollInterval: number;
  balancePollInterval: number;
  resolutionCheckInterval: number;
  whaleScanInterval: number;
  momentumScanInterval: number;
  marketRefreshInterval: number;

  maxSignalAgeSec: number;

  startBankrollUsd: number;
  stopLossOnDay: number;
  takeProfitOnDay: number;
  takeProfitPct?: number;
  flattenOnDailyStop?: boolean;
  lifetimeLossLimitPct?: number;
  lifetimeLossLimitUsd?: number;

  tradingHoursEnabled: boolean;
  tradingHoursStart: string;
  tradingHoursEnd: string;
  tradingDays: string[];
  tradingTimezoneOffsetMin: number;

  minWhaleUsd: number;
  minWhaleConfidence: number;
  minWhaleEdge: number;
  minMomentumConfidence: number;
  minMomentumEdge: number;
  minEntryPriceFrac: number;

  eventWebhookUrl: string;
  statsWebhookUrl: string;
  whaleWebhookUrl: string;
  momentumWebhookUrl: string;
  statsPushInterval: number;
  statsChartWindowHours: number;
  enableDiscord: boolean;

  crypto15mEnabled?: boolean;
  crypto15mInterval?: '5m' | '15m' | 'hourly';
  crypto15mAssets?: string[] | null;
  crypto15mArbDetect?: boolean;
  crypto15mArbMinEdgeCents?: number;
  crypto15mImbalanceDetect?: boolean;
  crypto15mImbalanceLevels?: number;
  crypto15mImbalanceGate?: boolean;
  crypto15mImbalanceGateMin?: number;
  crypto15mIndicatorDetect?: boolean;
  crypto15mWsBook?: boolean;
  crypto15mUseRules?: boolean;
  crypto15mRules?: RuleCondition[];
  crypto15mSizingMode?: 'fixed' | 'balance_pct';
  crypto15mOrderSize?: number;
  crypto15mBalancePct?: number;
  crypto15mMaxLossPct?: number;
  crypto15mStreakSizing?: boolean;
  crypto15mStreakLossPct?: number;
  crypto15mStreakWinPct?: number;
  crypto15mStreakMaxMult?: number;
  crypto15mMaxConcurrent?: number;
  crypto15mDailyLossLimit?: number;
  crypto15mLifetimeLossLimitPct?: number;
  crypto15mLifetimeLossLimitUsd?: number;
  crypto15mTakeProfitTotal?: number;
  crypto15mDirectionMode?: 'favorite' | 'contrarian' | 'model';

  crypto15mModelMinProb?: number;
  crypto15mModelMinEdgeCents?: number;
  crypto15mModelFinalMinute?: boolean;
  crypto15mModelAutopause?: boolean;
  crypto15mModelMaxBookGapCents?: number;
  crypto15mSpotWs?: boolean;
  crypto15mRtdsWs?: boolean;

  crypto15mPairedMode?: boolean;
  crypto15mPairedMaxCombinedCents?: number;
  crypto15mPairedTilt1Cents?: number;
  crypto15mPairedTilt2Cents?: number;
  crypto15mPairedTilt3Cents?: number;
  crypto15mSellIntoStrength?: boolean;
  crypto15mSellStrengthCents?: number;
  crypto15mTimeDelayMin?: number;
  crypto15mEntryThreshold?: number;
  crypto15mEntryMax?: number;
  crypto15mExitThreshold?: number;
  crypto15mTakeProfit?: number;
  crypto15mStopLossPct?: number;
  crypto15mTakeProfitPct?: number;
  crypto15mMinRsi?: number;
  crypto15mMinMacdHist?: number;
  crypto15mMinDeltaPct?: number;
  crypto15mEntryDiff?: number;
  crypto15mEntryStyle?: 'maker' | 'taker';
  crypto15mTakerFak?: boolean;
  crypto15mMakerCancelMin?: number;
  crypto15mMakerEscalate?: boolean;
  crypto15mMakerFillSec?: number;
  crypto15mHoursStartUtc?: number;
  crypto15mHoursEndUtc?: number;
  crypto15mRecordSignals?: boolean;
  mainRecordSignals?: boolean;

  copyEnabled?: boolean;
  copyWallets?: string[];
  copySizingMode?: 'fixed' | 'balance_pct';
  copyFixedUsd?: number;
  copyBalancePct?: number;
  copyMinTradeUsd?: number;
  copyMaxConcurrent?: number;
  copyEntryMaxCents?: number;
  copyDailyLossLimit?: number;
  copyLifetimeLossLimitPct?: number;
  copyLifetimeLossLimitUsd?: number;
  copyPollSec?: number;
  copyFastPollSec?: number;
  copyActivityWs?: boolean;
  copyMirrorReductions?: boolean;
  copyReduceThreshold?: number;
  copyOnlyNewEntries?: boolean;
  copyAllowReentries?: boolean;

  scriptsLiveEnabled?: boolean;
  scriptPollSec?: number;
  scriptMaxEntryCents?: number;
  scriptMaxContracts?: number;
  scriptMaxOpen?: number;
  scriptDailyLossUsd?: number;
  scriptMaxEnabled?: number;
  scriptMarketLimit?: number;
  scriptMarketMinVolume?: number;
  scriptMarketMaxSpreadCents?: number;
}

export interface CopyWalletInfo {
  address: string;
  short: string;
  positions: number;
  valueUsd: number;
}

export interface CopyStatus {
  enabled: boolean;
  authed: boolean;
  trading: boolean;
  wallets: CopyWalletInfo[];
  openCopies: number;
  todayPnlUsd: number;
  lossLimitHit: boolean;
  sizing: { mode: 'fixed' | 'balance_pct'; fixedUsd: number; balancePct: number };
  maxConcurrent: number;
  entryMaxCents: number;
}

export interface CredentialsState {
  env?: Network;

  hasWalletKey: boolean;

  hasApiCreds: boolean;

  address: string;

  addressPreview: string;

  funder?: string;

  signatureType?: number;

  walletMode?: 'eoa' | 'deposit' | 'error';

  metaError?: string;

  keyStoredUnencrypted?: boolean;
}

export interface CredentialsStatusAll {
  current: Network;
  mainnet: CredentialsState;
}

export interface CredentialsInput {
  keyId?: string;
  secretKey?: string;
  privateKey?: string;

  apiCreds?: { apiKey: string; secret: string; passphrase: string };
  env?: Network;

  funder?: string;

  signatureType?: number;
}

export type ProfileScope = 'main' | 'crypto' | 'copy';

export interface Profile {
  id: string;
  name: string;
  description?: string;

  scope?: ProfileScope;
  createdAt: string;
  updatedAt: string;
  config: TraderConfig;
  builtin?: boolean;
}

export interface AppState {
  config: TraderConfig;

  activeProfileId: string | null;
  activeCryptoProfileId?: string | null;
  activeCopyProfileId?: string | null;
  customProfiles: Profile[];
  startMinimized: boolean;
  startWithWindows: boolean;
  enableDiscordRpc: boolean;
  acceptedDisclaimer: boolean;
  windowBounds: { x: number; y: number; width: number; height: number } | null;
  /** Set once the UTC-day-boundary migration has run. See RELEASE-2.8.md. */
  tradingDayMigrated?: boolean;
}

export type BackendStatus =
  | 'stopped'
  | 'starting'
  | 'running'
  | 'restarting'
  | 'crashed';

export interface BackendInfo {
  status: BackendStatus;
  pid: number | null;
  startedAt: string | null;
  lastError: string | null;
  pythonOk: boolean;
  authOk: boolean;
}

export interface AccountSnapshot {
  cashUsd: number;
  portfolioUsd: number;
  totalUsd: number;
  balanceSyncing?: boolean;
  tradingGeoblocked?: boolean;
  startBankrollUsd: number;

  bankrollSource?: 'user' | 'auto' | 'live';
  roiPct: number;

  realizedPnlUsd: number;

  todayPnlUsd?: number;

  alltimePnlUsd?: number;

  todayBaselineUsd?: number | null;
  alltimeBaselineUsd?: number | null;
  todayWins?: number;
  todayLosses?: number;
  unrealizedPnlUsd: number;
  openCostUsd: number;

  unredeemedWinningsUsd?: number;
  unredeemedWinningsCount?: number;

  unredeemedWinningsStale?: boolean;
  feesUsd: number;
  wins: number;
  losses: number;
  winRate: number;
  pendingCount: number;
  openCount: number;
  resolvedCount: number;
  totalOpened: number;
  byNetwork: { mainnet: AccountByEnv };

  sessionPnlUsd?: number;
  sessionRoiPct?: number;
  sessionBaselineUsd?: number;
  sessionStartedAt?: string;
  sessionRunId?: number;
}

export interface BotRun {
  id: number;
  network: Network;
  startedAt: string;
  endedAt: string | null;
  startCashUsd: number;
  startPortfolioUsd: number;
  startTotalUsd: number;
  endCashUsd: number | null;
  endPortfolioUsd: number | null;
  endTotalUsd: number | null;
  pnlUsd: number;
  tradesOpened: number;
  tradesWon: number;
  tradesLost: number;
  isActive: boolean;
}

export interface BotRunsResponse {
  runs: BotRun[];
  activeRunId: number;
  activeRun: BotRun | null;
}

export interface AccountByEnv {
  wins: number;
  losses: number;
  realizedPnl: number;
}

export interface PnlPoint {
  at: string;
  cashUsd: number;
  portfolioUsd: number;
  totalUsd: number;
  realizedPnlUsd: number;
  openPositions: number;
}

export interface BotPosition {
  id: number;
  signalSource: SignalSource;
  signalId: number;
  ticker: string;
  eventTicker: string;
  title: string;
  category: string;
  direction: 'yes' | 'no';
  action: 'buy' | 'sell';
  targetContracts: number;
  limitPriceCents: number;
  filledContracts: number;
  avgFillPriceCents: number | null;
  costUsd: number;
  feesUsd: number;
  clientOrderId: string;
  orderId: string | null;
  status:
    | 'submitted'
    | 'partial'
    | 'filled'
    | 'canceled'
    | 'expired'
    | 'gone'
    | 'error'
    | 'dry_run';
  confidence: number;
  edgePts: number;
  signalPriceCents: number;
  resolved: boolean;
  outcomeCorrect: number | null;
  settlementUsd: number | null;
  pnlUsd: number | null;

  markPriceCents: number | null;

  livePnlUsd: number | null;
  balanceBeforeUsd: number | null;
  network: Network;
  createdAt: string;
  lastUpdated: string;
  resolvedAt: string | null;
  error: string | null;
}

export interface SignalRow {
  id: number;
  source: SignalSource;
  ticker: string;
  eventTicker: string;
  title: string;
  category: string;
  direction: 'yes' | 'no';
  priceCents: number;
  confidence: number;
  edgePts: number;
  signalType?: string;
  dollarValue?: number;
  createdAt: string;
  resolved: boolean;
  outcomeCorrect: number | null;
  pnlEstimate: number | null;

  traded: boolean;
}

export interface ScannerStats {
  whales: { total: number; sent: number; resolved: number; winRate: number };
  momentum: { total: number; sent: number; resolved: number; winRate: number };
  marketsTracked: number;
  lastWhaleScanAt: string | null;
  lastMomentumScanAt: string | null;
  lastTradeScanAt: string | null;
}

export interface LogEntry {
  ts: string;
  level: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL';
  source: 'main' | 'backend' | 'trader' | 'whale' | 'momentum' | 'discord';
  msg: string;
}

export interface ActionResult<T = void> {
  ok: boolean;
  message?: string;
  data?: T;
}

export interface StrategyPreset {
  id: string;
  name: string;
  tagline: string;
  description: string;
  riskLabel: 'safe' | 'balanced' | 'aggressive' | 'experimental';
  badge?: 'recommended' | 'new' | 'soon' | null;

  comingSoon?: boolean;
  config: TraderConfig;
}

export interface Crypto15mConstants {
  timeDelayMin: number;
  entryThreshold: number;
  exitThreshold: number;
  entryMax: number;
  minDeltaPct?: number;
  entryDiff: number;
  directionMode?: 'favorite' | 'contrarian';
  entryStyle?: 'maker' | 'taker';
  hoursStartUtc?: number;
  hoursEndUtc?: number;
}

export interface Crypto15mAsset {
  asset: string;
  series: string;
  enabled?: boolean;
  upAsk?: number | null;
  downAsk?: number | null;
  arbEdgeCents?: number | null;
  arbSignal?: boolean;
  bookImbalance?: number | null;
  spotUsd: number | null;
  open15mUsd: number | null;
  deltaUsd: number | null;
  deltaPct?: number | null;
  hasMarket: boolean;
  ticker: string | null;
  closeTime: string | null;
  minsLeft: number | null;
  upProb: number | null;
  downProb: number | null;
  favorite: 'up' | 'down' | null;
  favoritePrice: number | null;
  entryCost: number | null;
  yesBid?: number | null;
  yesAsk?: number | null;
  inWindow: boolean;
  signal: boolean;
  openMarketCount: number;
  error: string | null;
  hourUtc?: number | null;
  peersAgree?: number | null;
  marketBias?: number | null;

  macd?: number | null;
  macdSignal?: number | null;
  macdHist?: number | null;
  macdCross?: number | null;
  rsi?: number | null;
  wsBid?: number | null;
  wsAsk?: number | null;
  priceSource?: 'ws' | 'gamma';

  strikeUsd?: number | null;
  deltaSignedPct?: number | null;
  sigma1m?: number | null;
  modelProb?: number | null;
  edgeNetCents?: number | null;
  spotLive?: boolean;
}

export interface Crypto15mSnapshot {
  fetchedAt: string;
  spotOk: boolean;
  spotSource: string;
  hoursOk?: boolean;
  constants: Crypto15mConstants;
  assets: Crypto15mAsset[];
}

export type Crypto15mStatusName =
  | 'dry_run' | 'submitted' | 'filled' | 'exiting'
  | 'exited' | 'settled' | 'canceled' | 'error';

export interface Crypto15mPosition {
  id: number;
  asset: string;
  series: string;
  ticker: string;
  side: 'up' | 'down' | '';
  direction: 'yes' | 'no' | '';
  targetContracts: number;
  filledContracts: number;
  entryLimitCents: number;
  avgEntryCents: number | null;
  costUsd: number;
  status: Crypto15mStatusName | string;
  exitReason: string | null;
  exitLimitCents: number | null;
  proceedsUsd: number | null;
  confidence: number;
  entryDeltaUsd: number | null;
  outcomeCorrect: number | null;
  settlementUsd: number | null;
  pnlUsd: number | null;
  resolved: boolean;
  settling: boolean;
  closeTime: string;
  network: Network;
  createdAt: string;
  resolvedAt: string | null;
  error: string | null;
  strategy?: string;
  feesUsd?: number;
}

export interface Crypto15mStats {
  openCount: number;
  wins: number;
  losses: number;
  realizedPnlUsd: number;
  total: number;
}

export interface Crypto15mSizing {
  mode: 'fixed' | 'balance_pct';
  balancePct: number;
  maxLossPct: number;
  balanceUsd: number;
  estPriceCents: number;
  estContracts: number;
  estCostUsd: number;
  streakMult?: number;
  note: string;
}

export interface Crypto15mStatus {
  enabled: boolean;
  authed: boolean;
  trading: boolean;
  haltReason?: string;
  blockReasons?: Record<string, string>;
  byStrategy?: { strategy: string; n: number; wins: number; losses: number; pnl_usd: number; fees_usd: number }[];
  modelCalibration?: { ok: boolean; n: number; rate: number | null; lb: number | null };
  orderSize: number;
  maxConcurrent: number;
  sizing: Crypto15mSizing;
  env: Network;
  stats: Crypto15mStats;
  open: Crypto15mPosition[];
  recent: Crypto15mPosition[];
}

export interface TradingGate {
  id: string;
  label: string;
  state: 'ok' | 'blocked' | 'off';
  reason: string;
}

export interface TradingStatus {
  main: TradingGate[];
  mainMode: 'paused' | 'paper' | 'live';
  mainState: 'paused' | 'scanning' | 'waiting' | 'blocked';
  mainSummary: string;
  mainLastCycleAt: number | null;
  mainFilterCounts: Record<string, number>;
  mainCandidates: number;
  mainPlaced: number;
  mainPaper: {
    bankrollUsd: number;
    availableUsd: number;
    open: number;
    resolved: number;
    wins: number;
    losses: number;
    pnlUsd: number;
  };
  c15: {
    enabled: boolean;
    live: boolean;
    authed: boolean;
    env: string;
    blockReasons: Record<string, string>;
  };
}

export interface SignalCalibrationReport {
  status: 'collecting' | 'qualified' | 'not_qualified';
  reason: string;
  eventSamples: number;
  trainEvents: number;
  testEvents: number;
  qualifiedBuckets: number;
  asOf: number;
}

export interface Crypto15mBacktest {
  mode?: 'portfolio';
  dataStatus?: 'recorded' | 'insufficient_data';
  cashUsd?: number;
  reservedUsd?: number;
  feesUsd?: number;
  openPositions?: number;
  independentEvents?: number;
  n: number;
  wins: number;
  winRate: number;
  netEvCentsPerContract: number;
  totalPnlUsd: number;
  maxDrawdownUsd: number;
  contracts: number;
  windowsScanned: number;
  byAsset: Record<string, { n: number; wins: number; pnlUsd: number }>;
  equity: { at: string | null; value: number }[];
  byHourUtc: { hour: number; n: number; wins: number; pnlUsd: number }[];
  byDay: { day: string; n: number; wins: number; pnlUsd: number }[];
  trades: { ticker: string; asset: string; side: string; costCents: number; minsLeft: number | null; won: boolean; pnlUsd: number; at: string }[];
  caveats: string[];
  interval?: '5m' | '15m' | 'hourly';
}

export interface UserScriptStats {
  n: number;
  open: number;
  wins: number;
  losses: number;
  pnlUsd: number;
}

export interface ScriptAuditFinding {
  severity: 'critical' | 'warning' | 'info';

  category: string;
  line: number;
  message: string;
}

export interface ScriptAudit {
  ok: boolean;
  parsed: boolean;
  critical: number;
  warning: number;
  info: number;
  categories: string[];
  findings: ScriptAuditFinding[];
  summary: string;
}

export interface UserScriptStatus {
  state: 'off' | 'blocked' | 'error' | 'starting' | 'running';

  detail: string;
  ticks: number;
  intents: number;
  orders: number;
  lastTickAt: string | null;
  lastIntentAt: string | null;
  lastOrderAt: string | null;
}

export interface UserScript {
  id: string;
  name: string;
  description: string;
  code: string;
  enabled: boolean;

  dryRun: boolean;

  assets: string[] | null;

  audit: ScriptAudit;

  status: UserScriptStatus;
  notes: string;
  lastError: string | null;
  lastErrorAt: string | null;
  createdAt: string;
  updatedAt: string;
  stats: UserScriptStats | null;

  shadowStats: UserScriptStats | null;
}

export interface ScriptShadowOrder {
  id: number;
  source: 'crypto' | 'signal';
  asset: string;
  ticker: string;
  side: string;
  contracts: number;
  entryCents: number;
  orderType: string;
  reason: string;
  refused: boolean;
  note: string;
  resolved: boolean;
  won: boolean | null;
  pnlUsd: number | null;
  at: string;
}

export interface ScriptValidation {
  ok: boolean;
  errors: string[];
  warnings: string[];

  audit: ScriptAudit;
  name: string;
  description: string;
  hasHeader: boolean;
  ctxFields: string[];
}

export interface ScriptApiDocs {
  contract: string;
  fields: { name: string; doc: string; backtestable: boolean }[];

  injected: string[];

  hookTimeoutSec: number;
  rails: {
    maxEntryCents: number; maxContracts: number; maxOpen: number;
    dailyLossUsd: number; defaultOrderSize: number;
  };
  examples: { name: string; code: string }[];
}

export interface ScriptBacktest extends Crypto15mBacktest {
  tStat?: number | null;
  scriptError?: string | null;
  scriptLogs?: string[];

  signalResult?: (Crypto15mBacktest & { tStat?: number | null; scriptError?: string | null }) | null;
}

export interface CollectionStats {
  c15: {
    windows: number; resolved: number; ticks: number;
    firstAt: string | null; lastAt: string | null;
    recent: { ticker: string; asset: string; favorite: string | null; favorite_price: number | null; up_won: number | null; resolved: number; close_time: string }[];
  };
  main: {
    whales: number; whalesResolved: number; alerts: number; alertsResolved: number;
    alertsWindowed: number;
    firstAt: string | null; lastAt: string | null;
    topCategories: { category: string; n: number }[];
    recent: { ticker: string; category: string; taker_side: string; price: number; dollar_value: number; outcome_correct: number | null; resolved: number; created_at: string }[];
  };
  collecting: { c15: boolean; main: boolean };
}

export interface AccountInfo {
  name: string;
  current: boolean;
  isDefault: boolean;
}

export interface ROMApi {
  app: {
    version: () => Promise<string>;
    openExternal: (url: string) => Promise<void>;
    showItemInFolder: (filePath: string) => Promise<void>;
    getUserDataPath: () => Promise<string>;
    factoryReset: () => Promise<ActionResult<{ deleted: Record<string, number> }>>;
    clearHistory: () => Promise<ActionResult<{ deleted: Record<string, number> }>>;
    onDataReset: (cb: (payload: unknown) => void) => () => void;
  };
  accounts: {
    current: () => Promise<string>;
    list: () => Promise<AccountInfo[]>;
    create: (name: string) => Promise<{ ok: boolean; name?: string; message?: string }>;
    launch: (name: string) => Promise<{ ok: boolean; message?: string }>;
  };
  state: {
    get: () => Promise<AppState>;
    onChange: (cb: (state: AppState) => void) => () => void;
    setStartMinimized: (v: boolean) => Promise<ActionResult>;
    setStartWithWindows: (v: boolean) => Promise<ActionResult>;
    setEnableDiscordRpc: (v: boolean) => Promise<ActionResult>;
    acceptDisclaimer: () => Promise<ActionResult>;

    resetOnboarding: () => Promise<ActionResult>;
  };
  config: {
    get: () => Promise<TraderConfig>;
    update: (patch: Partial<TraderConfig>) => Promise<TraderConfig>;
    replace: (config: TraderConfig) => Promise<TraderConfig>;
    reset: () => Promise<TraderConfig>;
    listStrategies: () => Promise<StrategyPreset[]>;
    applyStrategy: (id: string) => Promise<TraderConfig>;
  };
  profiles: {
    list: () => Promise<Profile[]>;
    save: (name: string, description?: string, scope?: ProfileScope) => Promise<ActionResult<Profile>>;
    apply: (id: string) => Promise<ActionResult<TraderConfig>>;
    rename: (id: string, name: string) => Promise<ActionResult>;
    delete: (id: string) => Promise<ActionResult>;
    duplicate: (id: string) => Promise<ActionResult<Profile>>;
    export: (id: string) => Promise<ActionResult<string>>;
    import: (json: string) => Promise<ActionResult<Profile>>;
  };
  credentials: {
    status: () => Promise<CredentialsState>;

    statusAll: () => Promise<CredentialsStatusAll>;
    save: (input: CredentialsInput) => Promise<ActionResult>;

    test: (env?: Network) => Promise<ActionResult<{
      env: Network;
      balanceUsd: number;
      ready?: boolean;
      approvalsOk?: boolean | null;
      issues?: string[];
      address?: string;
    }>>;
    clear: (env?: Network) => Promise<ActionResult>;

    onChanged: (cb: (payload: unknown) => void) => () => void;
  };
  backend: {
    info: () => Promise<BackendInfo>;
    start: () => Promise<ActionResult>;
    stop: () => Promise<ActionResult>;
    restart: () => Promise<ActionResult>;
    onInfo: (cb: (info: BackendInfo) => void) => () => void;
    runOnce: (
      action:
        | 'syncMarkets'
        | 'pollOrders'
        | 'resolveAll'
        | 'reconcilePositions'
        | 'syncPositions'
        | 'recomputePnl'
        | 'reconcileFills'
        | 'auditPnl'
    ) => Promise<ActionResult<{ summary: string }>>;
  };
  trading: {
    calibration: () => Promise<SignalCalibrationReport>;
    setEnabled: (enabled: boolean) => Promise<ActionResult>;
    setPaperEnabled: (enabled: boolean) => Promise<ActionResult>;
    cancelAllOpen: () => Promise<ActionResult<{ canceled: number }>>;
    flatten: () => Promise<ActionResult<{ closed: number }>>;
    status: () => Promise<TradingStatus>;
    collection: () => Promise<CollectionStats | null>;
    exportData: () => Promise<{ dir: string; files: string[] } | null>;
  };
  data: {
    account: () => Promise<AccountSnapshot>;
    pnlSeries: (sinceHours?: number) => Promise<PnlPoint[]>;
    positions: (filter?: PositionFilter) => Promise<BotPosition[]>;
    signals: (filter?: SignalFilter) => Promise<SignalRow[]>;
    scannerStats: () => Promise<ScannerStats>;
    botRuns: (env?: Network | null, limit?: number) => Promise<BotRunsResponse>;
    onAccount: (cb: (snap: AccountSnapshot) => void) => () => void;
    onPosition: (cb: (pos: BotPosition) => void) => () => void;
    onSignal: (cb: (sig: SignalRow) => void) => () => void;
  };
  crypto15m: {
    snapshot: () => Promise<Crypto15mSnapshot>;
    status: () => Promise<Crypto15mStatus>;
    history: (opts?: { limit?: number }) => Promise<{ rows: Crypto15mPosition[] }>;
    backtest: (args?: { sinceDays?: number; config?: Record<string, unknown> }) => Promise<Crypto15mBacktest | null>;
    backtestMain: (args?: { sinceDays?: number; config?: Record<string, unknown> }) => Promise<Crypto15mBacktest | null>;

    onAutoOff: (cb: (d: { reason: string; gained: number; target: number }) => void) => () => void;
  };
  scripts: {
    list: () => Promise<{ scripts: UserScript[] }>;
    save: (s: { id?: string; name?: string; description?: string; code: string; notes?: string }) =>
      Promise<{ script: UserScript; errors: string[]; warnings: string[];
                audit: ScriptAudit; disarmed?: boolean }>;
    delete: (id: string) => Promise<{ ok: boolean }>;
    setEnabled: (id: string, enabled: boolean) => Promise<{ script: UserScript }>;

    setAssets: (id: string, assets: string[] | null) => Promise<{ script: UserScript }>;

    setDryRun: (id: string, dryRun: boolean) => Promise<{ script: UserScript }>;

    shadowOrders: (id: string, limit?: number) => Promise<{ orders: ScriptShadowOrder[] }>;

    exportFile: (name: string, code: string) => Promise<ActionResult<string>>;

    importFile: () => Promise<ActionResult<string>>;
    validate: (code: string) => Promise<ScriptValidation>;
    backtest: (args: { id?: string; code?: string; sinceDays?: number; assets?: string[] | null; config?: Record<string, unknown> }) =>
      Promise<ScriptBacktest | null>;
    contextPack: () => Promise<{ text: string }>;

    docs: () => Promise<ScriptApiDocs>;

    exportPack: () => Promise<ActionResult<string>>;

    onStatus: (cb: (d: { id: string; enabled: boolean; lastError?: string }) => void) => () => void;

    onLog: (cb: (d: { id: string; lines: string[] }) => void) => () => void;
  };
  copy: {
    status: () => Promise<CopyStatus>;
  };
  polymarket: {
    marketUrl: (args: { eventTicker?: string; ticker?: string; env?: string }) =>
      Promise<{ url: string }>;
  };
  logs: {
    tail: (limit?: number) => Promise<LogEntry[]>;
    onAppend: (cb: (entry: LogEntry) => void) => () => void;
    clear: () => Promise<ActionResult>;
    openFolder: () => Promise<void>;
  };
  window: {
    minimize: () => void;
    maximize: () => void;
    close: () => void;
    isMaximized: () => Promise<boolean>;
    onMaximizeChange: (cb: (max: boolean) => void) => () => void;
  };
}

export interface PositionFilter {
  status?: BotPosition['status'][];
  resolved?: boolean | null;
  signalSource?: SignalSource | null;
  limit?: number;
}

export interface SignalFilter {
  source?: SignalSource | null;
  minConfidence?: number;
  minEdge?: number;
  resolved?: boolean | null;
  limit?: number;
}

declare global {
  interface Window {
    rom: ROMApi;
  }
}
