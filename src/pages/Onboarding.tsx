import { ROMSprite } from '../components/ROMSprite';
import { ArrowUpRight, Gift } from 'lucide-react';
import { POLYMARKET_REFERRAL_CODE, POLYMARKET_REFERRAL_URL } from '../utils/links';
import { useEffect, useRef } from 'react';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

function useFocusTrap(open: boolean, containerRef: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    if (!open || !containerRef.current) return;

    const el = containerRef.current;
    const prevFocus = document.activeElement as HTMLElement | null;

    // Focus first button in the modal on open
    const first = el.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();

    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // Let the caller handle close via onDone
        return;
      }
      if (e.key !== 'Tab') return;

      const nodes = el.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener('keydown', handler);

    // Disable scroll behind the modal
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handler);
      document.body.style.overflow = '';
      prevFocus?.focus();
    };
  }, [open, containerRef]);
}

export function OnboardingModal({onDone}:{onDone:()=>void}) {
  const containerRef = useRef<HTMLDivElement>(null);
  useFocusTrap(true, containerRef);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/70 p-6 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-label="Welcome to ROM Polybot"
    >
      <div
        ref={containerRef}
        className="my-auto w-full max-w-xl rounded-xl border border-rom-border bg-rom-surface p-8 shadow-2xl"
      >
        <ROMSprite size={56} />
        <div className="mb-3 mt-6 text-xs font-semibold uppercase tracking-[0.2em] text-rom-purple">
          Your trading workspace
        </div>
        <h2 className="text-3xl font-semibold tracking-tight">Welcome to ROM Polybot</h2>
        <p className="mt-4 leading-relaxed text-rom-muted">
          Connect your Polymarket US API Key ID and Secret Key to get started. Your
          dashboard, strategies, history and settings run locally.
        </p>

        <div className="mt-5 rounded-xl border border-blue-400/20 bg-gradient-to-br from-blue-500/10 to-rom-purple/5 p-4">
          <div className="flex items-start gap-3">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-blue-400/10 text-blue-300">
              <Gift className="h-5 w-5" />
            </div>
            <div>
              <p className="text-sm font-semibold">New to Polymarket US? Get $50 to trade.</p>
              <p className="mt-1 text-xs leading-relaxed text-rom-muted">
                Join with referral code{' '}
                <span className="font-semibold text-rom-text">
                  {POLYMARKET_REFERRAL_CODE}
                </span>{' '}
                and make a qualifying $10 deposit to unlock the current reward.
              </p>
            </div>
          </div>
          <button
            type="button"
            className="rom-btn-default mt-4 w-full"
            onClick={() => void window.rom.app.openExternal(POLYMARKET_REFERRAL_URL)}
          >
            Claim new-user offer
            <ArrowUpRight className="h-4 w-4" />
          </button>
          <p className="mt-3 text-[10px] leading-relaxed text-rom-dim">
            Eligibility and Polymarket terms apply. Offer may change or expire. ROM may
            also receive a referral reward.
          </p>
        </div>

        <p className="mt-4 text-sm text-rom-muted">
          Automated trading can lose money. Review your strategy and risk limits before
          enabling live trading. Some international market feeds and wallet-copy features
          are unavailable on the US exchange.
        </p>

        <button
          className="rom-btn-primary mt-6"
          onClick={async () => {
            await window.rom.state.acceptDisclaimer();
            onDone();
          }}
        >
          Continue to API Setup
        </button>
      </div>
    </div>
  );
}
