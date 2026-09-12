/**
 * Config shape validation for the IPC boundary.
 *
 * The renderer can send arbitrary JS values through `config:update` /
 * `config:replace`. The Python backend validates deeply, but this layer
 * is the first line of defense: reject non-objects, NaN/Infinity numbers
 * (which would survive JSON serialization to Python and re-introduce the
 * NaN-gate class of bugs), wrong-typed values, and unknown keys before
 * they reach the store.
 *
 * Kept deliberately dependency-free and pure so it can be unit-tested
 * by a standalone script (e2e/evidence.test.mjs pattern).
 */

/** Keys the renderer is allowed to set, mapped to their expected type. */
type FieldType = 'boolean' | 'number' | 'string' | 'string-array' | 'string-enum' | 'rules' | 'nullable-number' | 'string-array-null';

const FIELD_TYPES: Readonly<Record<string, FieldType>> = {
  // identity / environment
  network: 'string-enum',
  // main strategy
  enableTrading: 'boolean', mainPaperTrading: 'boolean', mainPaperBankrollUsd: 'number',
  tradeWhales: 'boolean', tradeMomentum: 'boolean', tradeConvergence: 'boolean',
  minEdgePtsWhale: 'number', minEdgePtsMomentum: 'number',
  minConfidenceWhale: 'number', minConfidenceMomentum: 'number',
  minEntryPriceCents: 'number', maxEntryPriceCents: 'number', maxResolutionDays: 'number',
  allowedMomentumSignalTypes: 'string-array', allowedCategories: 'string-array-null',
  allowedWhaleCategories: 'string-array-null', allowedMomentumCategories: 'string-array-null',
  contrarianOnly: 'boolean',
  useRules: 'boolean', rules: 'rules',
  // sizing
  sizingMode: 'string-enum', baseSizeFraction: 'number', minSizeFraction: 'number', maxSizeFraction: 'number',
  minContracts: 'number', maxContracts: 'number', sizingBaseEdge: 'number', sizingMaxEdge: 'number',
  kellyFraction: 'number', hardMaxPositionUsd: 'number', minCashReserveFraction: 'number',
  evidenceAllocationEnabled: 'boolean',
  // orders
  orderStyle: 'string-enum', crossSpreadFallbackOffset: 'number', orderExpirationSec: 'nullable-number',
  // risk
  maxOpenPositions: 'number', maxPositionsPerEvent: 'number', maxDailyNewPositions: 'number',
  unlimitedDailyNewPositions: 'boolean', maxTotalExposureFraction: 'number',
  maxGroupExposureFraction: 'number', maxDrawdownFraction: 'number',
  requireEntryDepth: 'boolean', exitPriceLossBudgetCents: 'number',
  // intervals
  tradeScanInterval: 'number', positionPollInterval: 'number', balancePollInterval: 'number',
  resolutionCheckInterval: 'number', whaleScanInterval: 'number', momentumScanInterval: 'number',
  marketRefreshInterval: 'number', maxSignalAgeSec: 'number',
  // daily limits
  startBankrollUsd: 'number', stopLossOnDay: 'number', takeProfitOnDay: 'number', takeProfitPct: 'number',
  flattenOnDailyStop: 'boolean', lifetimeLossLimitPct: 'number', lifetimeLossLimitUsd: 'number',
  // trading hours
  tradingHoursEnabled: 'boolean', tradingHoursStart: 'string', tradingHoursEnd: 'string',
  tradingDays: 'string-array', tradingTimezoneOffsetMin: 'number',
  // whale thresholds
  minWhaleUsd: 'number', minWhaleConfidence: 'number', minWhaleEdge: 'number',
  minMomentumConfidence: 'number', minMomentumEdge: 'number', minEntryPriceFrac: 'number',
  // webhooks
  eventWebhookUrl: 'string', statsWebhookUrl: 'string', whaleWebhookUrl: 'string',
  momentumWebhookUrl: 'string', statsPushInterval: 'number', statsChartWindowHours: 'number',
  enableDiscord: 'boolean',
  // crypto15m
  crypto15mEnabled: 'boolean', crypto15mInterval: 'string-enum', crypto15mAssets: 'string-array-null',
  crypto15mArbDetect: 'boolean', crypto15mArbMinEdgeCents: 'number',
  crypto15mImbalanceDetect: 'boolean', crypto15mImbalanceLevels: 'number',
  crypto15mImbalanceGate: 'boolean', crypto15mImbalanceGateMin: 'number',
  crypto15mIndicatorDetect: 'boolean', crypto15mWsBook: 'boolean', crypto15mUseRules: 'boolean',
  crypto15mRules: 'rules',
  crypto15mSizingMode: 'string-enum', crypto15mOrderSize: 'number', crypto15mBalancePct: 'number',
  crypto15mMaxLossPct: 'number', crypto15mStreakSizing: 'boolean', crypto15mStreakLossPct: 'number',
  crypto15mStreakWinPct: 'number', crypto15mStreakMaxMult: 'number', crypto15mMaxConcurrent: 'number',
  crypto15mDailyLossLimit: 'number', crypto15mLifetimeLossLimitPct: 'number',
  crypto15mLifetimeLossLimitUsd: 'number', crypto15mTakeProfitTotal: 'number',
  crypto15mDirectionMode: 'string-enum',
  crypto15mModelMinProb: 'number', crypto15mModelMinEdgeCents: 'number', crypto15mModelFinalMinute: 'boolean',
  crypto15mModelAutopause: 'boolean', crypto15mModelMaxBookGapCents: 'number',
  crypto15mSpotWs: 'boolean', crypto15mRtdsWs: 'boolean',
  crypto15mPairedMode: 'boolean', crypto15mPairedMaxCombinedCents: 'number',
  crypto15mPairedTilt1Cents: 'number', crypto15mPairedTilt2Cents: 'number', crypto15mPairedTilt3Cents: 'number',
  crypto15mSellIntoStrength: 'boolean', crypto15mSellStrengthCents: 'number', crypto15mTimeDelayMin: 'number',
  crypto15mEntryThreshold: 'number', crypto15mEntryMax: 'number',
  crypto15mExitThreshold: 'number', crypto15mTakeProfit: 'number',
  crypto15mStopLossPct: 'number', crypto15mTakeProfitPct: 'number',
  crypto15mMinRsi: 'number', crypto15mMinMacdHist: 'number', crypto15mMinDeltaPct: 'number',
  crypto15mEntryDiff: 'number', crypto15mEntryStyle: 'string-enum',
  crypto15mTakerFak: 'boolean', crypto15mMakerCancelMin: 'number',
  crypto15mMakerEscalate: 'boolean', crypto15mMakerFillSec: 'number',
  crypto15mHoursStartUtc: 'number', crypto15mHoursEndUtc: 'number',
  crypto15mRecordSignals: 'boolean', mainRecordSignals: 'boolean',
  // copy trading
  copyEnabled: 'boolean', copyWallets: 'string-array', copySizingMode: 'string-enum',
  copyFixedUsd: 'number', copyBalancePct: 'number', copyMinTradeUsd: 'number',
  copyMaxConcurrent: 'number', copyEntryMaxCents: 'number',
  copyDailyLossLimit: 'number', copyLifetimeLossLimitPct: 'number', copyLifetimeLossLimitUsd: 'number',
  copyPollSec: 'number', copyFastPollSec: 'number', copyActivityWs: 'boolean',
  copyMirrorReductions: 'boolean', copyReduceThreshold: 'number',
  copyOnlyNewEntries: 'boolean', copyAllowReentries: 'boolean',
  // scripts
  scriptsLiveEnabled: 'boolean', scriptPollSec: 'number', scriptMaxEntryCents: 'number',
  scriptMaxContracts: 'number', scriptMaxOpen: 'number', scriptDailyLossUsd: 'number',
  scriptMaxEnabled: 'number', scriptMarketLimit: 'number', scriptMarketMinVolume: 'number',
  scriptMarketMaxSpreadCents: 'number',
};

/** Keys that legitimately hold empty-string arrays are allowed null. */
const NULLABLE_ARRAY_KEYS: ReadonlySet<string> = new Set([
  'allowedCategories', 'allowedWhaleCategories', 'allowedMomentumCategories',
  'crypto15mAssets',
]);

/** String-valued sets (enums). Unknown values are rejected, not coerced. */
const STRING_ENUMS: Readonly<Record<string, ReadonlySet<string>>> = {
  sizingMode: new Set(['percent', 'contracts', 'kelly']),
  crypto15mSizingMode: new Set(['fixed', 'balance_pct']),
  crypto15mDirectionMode: new Set(['favorite', 'contrarian', 'model']),
  crypto15mEntryStyle: new Set(['maker', 'taker']),
  copySizingMode: new Set(['fixed', 'balance_pct']),
  crypto15mInterval: new Set(['5m', '15m', 'hourly']),
  orderStyle: new Set(['limit_cross', 'limit_mid', 'market']),
  network: new Set(['mainnet', 'matic']),
};

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/**
 * Validate a Partial<TraderConfig> patch.
 * Returns {ok: true, value} with only known keys, or {ok: false, errors}.
 * Unknown keys are dropped (not fatal) so the backend keeps working when
 * new config keys land before this list is updated — but wrong-typed
 * known keys and NaN/Infinity ARE fatal.
 */
export function validateConfigPatch(patch: unknown): {
  ok: boolean;
  value?: Record<string, unknown>;
  errors?: string[];
} {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) {
    return { ok: false, errors: ['config patch must be a plain object'] };
  }
  const errors: string[] = [];
  const value: Record<string, unknown> = {};

  const fail = (key: string, why: string) => { errors.push(`${key}: ${why}`); };

  for (const [key, raw] of Object.entries(patch)) {
    const expected = FIELD_TYPES[key];
    if (!expected) {
      // Unknown key: drop silently (forward-compatible), don't fail the patch.
      continue;
    }

    switch (expected) {
      case 'boolean':
        if (typeof raw === 'boolean') value[key] = raw;
        else fail(key, `expected boolean, got ${typeof raw}`);
        break;
      case 'number':
        if (isFiniteNumber(raw)) value[key] = raw;
        else fail(key, `expected number, got ${raw === null ? 'null' : typeof raw}`);
        break;
      case 'nullable-number':
        if (raw === null || isFiniteNumber(raw)) value[key] = raw;
        else fail(key, `expected number or null, got ${typeof raw}`);
        break;
      case 'string':
        if (typeof raw === 'string') value[key] = raw;
        else fail(key, `expected string, got ${typeof raw}`);
        break;
      case 'string-enum': {
        const set = STRING_ENUMS[key];
        if (typeof raw === 'string' && set && set.has(raw)) value[key] = raw;
        else fail(key, `invalid enum value '${String(raw)}'`);
        break;
      }
      case 'string-array':
        if (Array.isArray(raw) && raw.every((x) => typeof x === 'string')) value[key] = raw;
        else fail(key, 'expected array of strings');
        break;
      case 'string-array-null':
        if (raw === null) { value[key] = null; break; }
        if (Array.isArray(raw) && raw.every((x) => typeof x === 'string')) value[key] = raw;
        else fail(key, 'expected array of strings or null');
        break;
      case 'rules':
        // Rules objects are validated deeply by the Python backend; require
        // array-of-objects shape here, deep content checked there.
        if (Array.isArray(raw) && raw.every((r) => r && typeof r === 'object' && !Array.isArray(r))) {
          value[key] = raw;
        } else {
          fail(key, 'expected array of rule objects');
        }
        break;
    }
  }

  if (errors.length > 0) return { ok: false, errors };
  return { ok: true, value };
}
