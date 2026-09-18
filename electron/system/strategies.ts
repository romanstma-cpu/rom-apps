import type { StrategyPreset, TraderConfig } from '../../shared/types';
import { DEFAULT_CONFIG } from './settings-store';

const merge = (over: Partial<TraderConfig>): TraderConfig => ({
  ...DEFAULT_CONFIG,
  ...over,
});

export const BUILTIN_STRATEGIES: StrategyPreset[] = [
  {
    id: 'rom-edge',
    name: 'Edge Stack',
    tagline: 'Both signal sources, selected by current evidence.',
    description:
      'Runs Large Trade and contrarian Momentum signals across available categories. Live entries still require a category, side and price group that passed chronological holdout testing after fees; Practice continues collecting unqualified candidates. The 85¢ entry cap avoids near-decided favorites. Experimental — start with Practice and a small balance.',
    riskLabel: 'experimental',
    badge: 'recommended',
    config: merge({
      tradeWhales: true,
      tradeMomentum: true,
      contrarianOnly: true,
      allowedCategories: null,
      allowedWhaleCategories: null,
      allowedMomentumCategories: null,
      allowedMomentumSignalTypes: ['trade_cluster'],
      minConfidenceWhale: 55.0,
      minEdgePtsWhale: 5.0,
      minConfidenceMomentum: 40.0,
      minEntryPriceCents: 15,
      maxEntryPriceCents: 85,
    }),
  },
  {
    id: 'rom-crypto-whale',
    name: 'Crypto Large Trades',
    tagline: 'Research-only large-order signals in crypto markets.',
    description:
      'Reacts to $2.5k+ public taker orders in CRYPTO markets only, with momentum disabled. Earlier historical performance did not hold on the larger sample, so this preset is retained for research and Practice rather than presented as a current edge.',
    riskLabel: 'experimental',
    config: merge({
      tradeWhales: true,
      tradeMomentum: false,
      allowedCategories: ['crypto'],
      minConfidenceWhale: 55.0,
      minEdgePtsWhale: 5.0,
      minEntryPriceCents: 15,
      maxEntryPriceCents: 98,
    }),
  },

  {
    id: 'rom-aggressive',
    name: 'ROM Aggressive',
    tagline: 'More signals, larger sizing, higher variance.',
    description:
      'Loosens edge gates to 3pts and confidence to 50%. Sizing scales 4-10% of bankroll, $100 cap, higher max-open count. High variance — use only with a bankroll you can stand to drop 30% on a bad day.',
    riskLabel: 'aggressive',
    config: merge({
      minEdgePtsWhale: 3.0,
      minEdgePtsMomentum: 3.0,
      minConfidenceWhale: 50.0,
      minConfidenceMomentum: 50.0,
      baseSizeFraction: 0.06,
      minSizeFraction: 0.04,
      maxSizeFraction: 0.1,
      hardMaxPositionUsd: 100.0,
      maxOpenPositions: 40,
      maxDailyNewPositions: 80,
      maxTotalExposureFraction: 0.85,
      stopLossOnDay: -100.0,
    }),
  },
];

export function listStrategies(): StrategyPreset[] {
  return BUILTIN_STRATEGIES;
}

export function findStrategy(id: string): StrategyPreset | undefined {
  return BUILTIN_STRATEGIES.find((s) => s.id === id);
}
