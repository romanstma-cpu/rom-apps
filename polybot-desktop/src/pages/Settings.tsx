import { useEffect, useRef, useState } from 'react';
import { RefreshCw, RotateCcw } from 'lucide-react';
import type { TraderConfig } from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Card, Page, Section, Switch } from '../components/common';

export function SettingsPage() {
  const { config, refresh, state, backend } = useApp();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const restartBackend = async (): Promise<void> => {
    toast.info('Restarting backend — every engine stops and restarts…');
    await window.rom.backend.restart();
    setTimeout(() => void refresh.backend(), 1000);
  };

  if (!config) return <Page title="Settings"><div className="text-rom-muted">Loading…</div></Page>;

  const update = async <K extends keyof TraderConfig>(key: K, value: TraderConfig[K]): Promise<void> => {
    try {
      await window.rom.config.update({ [key]: value } as Partial<TraderConfig>);
      await refresh.state();
    } catch (e: any) {
      toast.error(`${e?.message || e}`);
    }
  };

  return (
    <Page
      title="Settings"
      subtitle="App-level preferences: startup behavior, notifications, and data. Each trading engine has its own page and its own on/off switch — Main Engine (whales + momentum), Crypto, Copy Trading, and Scripts."
    >
      <Section
        title="Backend"
        description="The Python process every engine runs inside. Restarting it stops and restarts ALL of them — it is not scoped to any single engine, which is why it lives here rather than on an engine page."
      >
        <Card>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <button onClick={() => void restartBackend()} className="rom-btn-default">
              <RefreshCw className="h-4 w-4" /> Restart backend
            </button>
            <div className="text-[11px] text-rom-dim">
              Status:{' '}
              <span className={backend.status === 'running' ? 'text-rom-win' : 'text-rom-warn'}>
                {backend.status}
              </span>
              {backend.status === 'running'
                ? ' — open positions keep their management passes; a restart briefly interrupts them.'
                : ' — a restart usually clears a stuck backend.'}
            </div>
          </div>
        </Card>
      </Section>

      <Section title="App preferences">
        <Card>
          <div className="grid gap-2 md:grid-cols-2">
            <Switch
              label="Start with Windows"
              description="Launch ROM PolyBot at login (silent if Start Minimized is on)."
              checked={!!state?.startWithWindows}
              onChange={(v) => window.rom.state.setStartWithWindows(v).then(refresh.state)}
            />
            <Switch
              label="Start minimized to tray"
              description="If autostarted, hide to tray on launch. Open from the tray icon."
              checked={!!state?.startMinimized}
              onChange={(v) => window.rom.state.setStartMinimized(v).then(refresh.state)}
            />
          </div>
        </Card>
      </Section>

      <Section
        title="Discord webhooks (optional)"
        description="Drop your channel webhook URLs to mirror events to Discord."
      >
        <Card>
          <div className="grid gap-3 md:grid-cols-2">
            <UrlField label="Trade events" value={config.eventWebhookUrl}
              onChange={(v) => void update('eventWebhookUrl', v)} />
            <UrlField label="Stats" value={config.statsWebhookUrl}
              onChange={(v) => void update('statsWebhookUrl', v)} />
            <UrlField label="Whale alerts" value={config.whaleWebhookUrl}
              onChange={(v) => void update('whaleWebhookUrl', v)} />
            <UrlField label="Momentum alerts" value={config.momentumWebhookUrl}
              onChange={(v) => void update('momentumWebhookUrl', v)} />
          </div>
          <Switch
            label="Enable Discord webhooks"
            description="Master switch — turn off to mute all webhook posting without losing the URLs."
            checked={config.enableDiscord}
            onChange={(v) => void update('enableDiscord', v)}
          />
        </Card>
      </Section>

      <DangerZone busy={busy} setBusy={setBusy} />
    </Page>
  );
}

function DangerZone({
  busy, setBusy,
}: { busy: boolean; setBusy: (b: boolean) => void }) {
  const toast = useToast();

  const [showModal, setShowModal] = useState(false);
  const [phrase, setPhrase] = useState('');

  const openModal = (): void => {
    setPhrase('');
    setShowModal(true);
  };

  const cancel = (): void => {
    setShowModal(false);
    setPhrase('');
  };

  const confirm = async (): Promise<void> => {
    if (phrase.trim() !== 'RESET') {
      toast.error('Type RESET (uppercase) to confirm.');
      return;
    }
    setShowModal(false);
    setBusy(true);
    try {
      const r = await window.rom.app.factoryReset();
      if (r.ok) {
        const summary = (r.data as { deleted?: Record<string, number> })?.deleted || {};
        const detail = Object.entries(summary)
          .filter(([k, v]) => !k.startsWith('_') && (v as number) > 0)
          .map(([k, v]) => `${k}: ${v}`)
          .join(', ');
        toast.success(detail
          ? `Wiped — ${detail}`
          : (r.message || 'Local data cleared (nothing to delete)'));
      } else {
        toast.error(r.message || 'Reset failed');
      }
    } catch (e: any) {
      toast.error(`${e?.message || e}`);
    } finally {
      setBusy(false);
      setPhrase('');
    }
  };

  return (
    <>
      <Section title="Danger zone">
        <Card>
          <div className="space-y-3 rounded-xl border border-rose-500/40 bg-rose-500/5 p-4">
            <div>
              <div className="text-sm font-semibold text-rose-300">
                Full reset
              </div>
              <p className="text-xs text-rom-muted mt-1">
                Wipes all locally stored trading history, P&amp;L snapshots,
                bot runs, and signals. Your API credentials, profiles, and settings are
                preserved. Live Polymarket positions will be re-imported on the
                next reconcile cycle. Useful for clearing inconsistent state
                from old builds before live testing.
              </p>
            </div>
            <button
              onClick={openModal}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-lg border border-rose-500/60 bg-rose-500/15 px-4 py-2 text-sm font-semibold text-rose-200 hover:bg-rose-500/25 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RotateCcw className="h-4 w-4" />
              Full reset
            </button>
          </div>
        </Card>
      </Section>

      {showModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={cancel}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-rose-500/50 bg-rom-panel p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-rose-300">
              Confirm full reset
            </h3>
            <div className="mt-3 space-y-2 text-sm text-rom-muted">
              <p>This will permanently delete:</p>
              <ul className="ml-5 list-disc space-y-1">
                <li>all bot positions and trade history</li>
                <li>all bot runs (session P&amp;L)</li>
                <li>all P&amp;L snapshots</li>
                <li>all whale and momentum signals</li>
              </ul>
              <p className="pt-2">
                Your API credentials, profiles, and settings are <strong>kept</strong>.
                Live Polymarket positions will be re-imported on the next
                reconcile cycle.
              </p>
            </div>
            <label className="mt-4 block text-xs font-semibold uppercase tracking-wider text-rom-muted">
              Type <span className="text-rose-300">RESET</span> to confirm
            </label>
            <input
              autoFocus
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void confirm();
                if (e.key === 'Escape') cancel();
              }}
              className="mt-1 w-full rounded-lg border border-rose-500/40 bg-black/30 px-3 py-2 text-sm font-mono text-rose-100 placeholder-rom-muted/50 outline-none focus:border-rose-400"
              placeholder="RESET"
            />
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={cancel}
                className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-rom-muted hover:bg-white/10"
              >
                Cancel
              </button>
              <button
                onClick={() => void confirm()}
                disabled={phrase.trim() !== 'RESET'}
                className="rounded-lg border border-rose-500/60 bg-rose-500/20 px-4 py-2 text-sm font-semibold text-rose-100 hover:bg-rose-500/30 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Wipe everything
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function UrlField({
  label, value, onChange,
}: { label: string; value: string; onChange: (v: string) => void }) {
  const [text, setText] = useState(value);
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setText(value); }, [value]);
  return (
    <div>
      <label className="rom-label">{label} webhook</label>
      <input
        type="text"
        className="rom-input font-mono text-xs"
        value={text}
        placeholder="https://discord.com/api/webhooks/…"
        onFocus={() => { focused.current = true; }}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => { focused.current = false; if (text !== value) onChange(text); }}
      />
    </div>
  );
}
