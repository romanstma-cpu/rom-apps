import { useState } from 'react';
import { AlertOctagon, ExternalLink } from 'lucide-react';
import type { BlockedIntent } from '@shared/types';
import { useToast } from '../state/ToastProvider';

const STATE_MEANING: Record<BlockedIntent['state'], string> = {
  sending: 'The order was journalled and then the process stopped before the exchange answered. It may or may not exist on the exchange.',
  unknown: 'The request failed in a way that does not prove the order was rejected — a timeout, a dropped connection, or an unexpected response.',
  cancel_pending: 'A cancel was sent but the follow-up read has not yet shown the order as canceled or matched.',
  accounting_pending: 'The exchange reported a fill this app cannot account for exactly — a missing average price, a missing commission, or a fractional quantity.',
};

function fmtAge(createdAt: number): string {
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - createdAt));
  if (secs < 90) return `${secs}s ago`;
  if (secs < 5400) return `${Math.round(secs / 60)}m ago`;
  if (secs < 172800) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

/**
 * The operator's way out of a halted journal.
 *
 * A blocking intent stops submissions from every engine — main, crypto15m,
 * copy trader — with no timeout and no automatic forget path, because the
 * alternative is double-submitting real money into the same market. Until
 * this panel existed the documented escape hatch was reachable only by
 * writing JSON-RPC to the backend's stdin with the app shut down.
 */
export function OrderRecovery({ intents }: { intents: BlockedIntent[] }) {
  const toast = useToast();
  const [ids, setIds] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  if (!intents.length) return null;

  const recover = async (intent: BlockedIntent) => {
    const exchangeOrderId = (ids[intent.localId] || '').trim();
    if (!exchangeOrderId) return;
    setBusy(intent.localId);
    try {
      const r = await window.rom.backend.runOnce('recoverOrder', {
        localOrderId: intent.localId,
        exchangeOrderId,
      });
      if (r.ok) {
        toast.push(r.data?.summary || 'Order linked and reconciled', 'success');
        setIds((prev) => ({ ...prev, [intent.localId]: '' }));
      } else {
        // The adapter refuses a mismatch on market, side, size or price, so a
        // failure here usually means the wrong order id — worth saying rather
        // than reducing to "failed".
        toast.push(r.message || 'Recovery refused — the order did not match this intent', 'error');
      }
    } catch (e) {
      toast.push(String((e as Error)?.message || e), 'error');
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      aria-labelledby="order-recovery-heading"
      className="mb-4 rounded-xl border border-rom-loss/40 bg-rom-loss/[0.07] p-4"
    >
      <div className="flex items-start gap-3">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-rom-loss/10 text-rom-loss">
          <AlertOctagon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 id="order-recovery-heading" className="text-sm font-semibold text-rom-loss">
            Trading is halted — {intents.length} order{intents.length > 1 ? 's' : ''} need
            {intents.length > 1 ? '' : 's'} recovery
          </h2>
          <p className="mt-1 text-xs leading-relaxed text-rom-muted">
            Every engine has stopped submitting orders. The journal holds an intent whose
            outcome it cannot prove, and it will not guess: the alternative is buying the
            same market twice. Find the matching order on Polymarket US and paste its
            order ID below to link them.
          </p>
          <p className="mt-2 text-xs leading-relaxed text-rom-muted">
            <span className="font-semibold text-rom-text">Do not guess an ID.</span> The
            app rejects an order whose market, side, size or price disagree with the
            intent — but a coincidentally matching wrong order would be accepted, and
            your account would then be reconciled against someone else&apos;s fill.
          </p>

          <ul className="mt-4 space-y-3">
            {intents.map((intent) => (
              <li
                key={intent.localId}
                className="rounded-lg border border-rom-border bg-rom-surface2 p-3"
              >
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="font-mono text-xs text-white">{intent.ticker}</span>
                  <span className="text-xs uppercase tracking-wide text-rom-muted">
                    {intent.action} {intent.side}
                  </span>
                  <span className="text-xs tabular-nums text-rom-muted">
                    {intent.quantity} @ {Math.round(intent.limitPrice * 100)}c
                  </span>
                  <span className="text-[10px] uppercase tracking-wide text-rom-dim">
                    {intent.state.replace('_', ' ')} · {fmtAge(intent.createdAt)}
                  </span>
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-rom-muted">
                  {STATE_MEANING[intent.state]}
                </p>
                {intent.error && (
                  <p className="mt-1 font-mono text-[10px] leading-relaxed text-rom-dim">
                    {intent.error}
                  </p>
                )}
                <div className="mt-1.5 text-[10px] text-rom-dim">
                  Local ID <span className="font-mono text-rom-muted">{intent.localId}</span>
                  {intent.orderId && (
                    <>
                      {' · '}exchange ID{' '}
                      <span className="font-mono text-rom-muted">{intent.orderId}</span>
                    </>
                  )}
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <label className="sr-only" htmlFor={`recover-${intent.localId}`}>
                    Exchange order ID for {intent.ticker} {intent.action} {intent.side}
                  </label>
                  <input
                    id={`recover-${intent.localId}`}
                    value={ids[intent.localId] || ''}
                    onChange={(e) =>
                      setIds((prev) => ({ ...prev, [intent.localId]: e.target.value }))
                    }
                    placeholder="Paste the exchange order ID"
                    spellCheck={false}
                    autoComplete="off"
                    className="min-w-0 flex-1 rounded-lg border border-rom-border bg-rom-bg px-3 py-2 font-mono text-xs text-white placeholder:text-rom-dim focus:border-rom-glow focus:outline-none"
                  />
                  <button
                    type="button"
                    className="rom-btn-default"
                    disabled={!((ids[intent.localId] || '').trim()) || busy === intent.localId}
                    onClick={() => void recover(intent)}
                  >
                    {busy === intent.localId ? 'Linking…' : 'Link and reconcile'}
                  </button>
                </div>
              </li>
            ))}
          </ul>

          <p className="mt-3 text-xs text-rom-muted">
            Full procedure, including how to find the order and what to do when no
            matching order exists, is in <span className="font-mono">docs/RECOVERY-RUNBOOK.md</span>.
          </p>
          <button
            type="button"
            className="rom-btn-ghost mt-2"
            onClick={() => void window.rom.app.openExternal('https://polymarket.us/portfolio')}
          >
            Open Polymarket US portfolio
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </section>
  );
}
