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
    tagline: 'Two sources at once — crypto whales + sports momentum.',
    description:
      'Runs both signal sources together, each restricted to where it tends to work: whale-following in CRYPTO / EXOTICS / ENTERTAINMENT and contrarian trade-cluster momentum in SPORTS (confidence ≥ 40, since momentum scores run low), with an 85¢ entry cap to skip near-decided favorites. Diversifies across two independent setups. Experimental — start with a small balance you can afford to lose.',
    riskLabel: 'experimental',
    config: merge({
      tradeWhales: true,
      tradeMomentum: true,
      contrarianOnly: true,
      allowedCategories: null,
      allowedWhaleCategories: ['crypto', 'exotics', 'entertainment'],
      allowedMomentumCategories: ['sports'],
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
    name: 'Crypto Whale',
    tagline: 'Whale-following, crypto markets only.',
    description:
      'Follows $2.5k+ taker orders in CRYPTO markets only, with momentum disabled. The entry cap is raised to 98¢ so it can follow the high-price favorites that crypto whales tend to back. Experimental — start with a small balance you can afford to lose.',
    riskLabel: 'experimental',
    badge: 'new',
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
