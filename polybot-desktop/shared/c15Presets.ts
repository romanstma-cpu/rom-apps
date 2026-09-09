import type { TraderConfig } from './types';

export const C15_PRESET_CORE: Record<
  'sniper' | 'sniper-5m' | 'paired' | 'favorite' | 'contrarian',
  Partial<TraderConfig>
> = {
  sniper: {
    crypto15mInterval: '15m',
    crypto15mDirectionMode: 'model', crypto15mUseRules: false,
    crypto15mModelMinEdgeCents: 2, crypto15mModelFinalMinute: true,
  },
  'sniper-5m': {
    crypto15mInterval: '5m', crypto15mAssets: ['BTC'],
    crypto15mDirectionMode: 'favorite', crypto15mUseRules: false,
    crypto15mPairedMode: false, crypto15mTimeDelayMin: 2,
    crypto15mEntryThreshold: 0.90, crypto15mEntryMax: 0.99,
    crypto15mMinDeltaPct: 0.0005,
  },
  paired: {
    crypto15mInterval: '15m',
    crypto15mDirectionMode: 'model', crypto15mUseRules: false,
    crypto15mPairedMode: true, crypto15mPairedMaxCombinedCents: 100,
    crypto15mPairedTilt1Cents: 3, crypto15mPairedTilt2Cents: 6,
    crypto15mPairedTilt3Cents: 10,
    crypto15mTimeDelayMin: 15, crypto15mEntryMax: 0.97,
  },
  favorite: {
    crypto15mInterval: '15m',
    crypto15mDirectionMode: 'favorite', crypto15mUseRules: false,
    crypto15mEntryThreshold: 0.95, crypto15mEntryMax: 0.98,
  },
  contrarian: {
    crypto15mInterval: '15m',
    crypto15mDirectionMode: 'contrarian', crypto15mUseRules: false,
    crypto15mEntryThreshold: 0.90,
  },
};
