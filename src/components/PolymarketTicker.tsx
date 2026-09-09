import { ExternalLink } from 'lucide-react';
import { cls } from '../utils/format';
import { openPolymarketMarket } from '../utils/polymarket';

export function TickerLink({
  ticker,
  eventTicker,
  env,
  label,
  className,
}: {
  ticker: string;
  eventTicker?: string;
  env?: string;
  label?: string;
  className?: string;
}) {
  if (!ticker) return <span className="text-rom-dim">{label ?? '—'}</span>;
  return (
    <button
      type="button"
      onClick={() => void openPolymarketMarket({ ticker, eventTicker, env })}
      title="Open this market on Polymarket"
      className={cls(
        'group inline-flex items-center gap-1 font-mono text-xs text-rom-purple',
        'transition-colors hover:text-rom-pink hover:underline',
        className,
      )}
    >
      {label ?? ticker}
      <ExternalLink className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-70" />
    </button>
  );
}
