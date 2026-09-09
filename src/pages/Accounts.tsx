import { useEffect, useState } from 'react';
import { Check, ExternalLink, FolderPlus, Users } from 'lucide-react';
import type { AccountInfo } from '@shared/types';
import { useToast } from '../state/ToastProvider';
import { Card, NameDialog, Page, Section } from '../components/common';
import { cls } from '../utils/format';

export function AccountsPage() {
  const toast = useToast();
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [current, setCurrent] = useState('Default');
  const [createOpen, setCreateOpen] = useState(false);

  const reload = async (): Promise<void> => {
    try {
      const [list, cur] = await Promise.all([
        window.rom.accounts.list(),
        window.rom.accounts.current(),
      ]);
      setAccounts(list);
      setCurrent(cur);
    } catch {}
  };

  useEffect(() => { void reload(); }, []);

  const launch = async (name: string): Promise<void> => {
    const r = await window.rom.accounts.launch(name);
    if (r.ok) toast.success(`Opening "${name}"…`);
    else toast.error(r.message || 'Could not open account');
  };

  const create = async (name: string): Promise<void> => {
    setCreateOpen(false);
    const r = await window.rom.accounts.create(name);
    if (!r.ok || !r.name) { toast.error(r.message || 'Could not create account'); return; }
    toast.success(`Created "${r.name}" — opening…`);
    await reload();
    await window.rom.accounts.launch(r.name);
  };

  return (
    <Page
      title="Accounts"
      subtitle="Run multiple Polymarket accounts side by side. Each account is completely separate — its own API credentials, balance, positions, and settings — and opens in its own window."
      actions={
        <button onClick={() => setCreateOpen(true)} className="rom-btn-primary">
          <FolderPlus className="h-4 w-4" /> New account
        </button>
      }
    >
      <Section title="Your accounts">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {accounts.map((a) => {
            const isCurrent = a.name === current;
            return (
              <Card key={a.name}>
                <div className="flex items-start gap-3">
                  <div className={cls(
                    'grid h-10 w-10 shrink-0 place-items-center rounded-lg',
                    isCurrent ? 'bg-rom-glow text-white' : 'bg-rom-surface2 text-rom-muted',
                  )}>
                    <Users className="h-4 w-4" />
                  </div>
                  <div className="flex-1">
                    <div className="text-sm font-medium text-white">{a.name}</div>
                    <div className="text-xs text-rom-muted">
                      {a.isDefault ? 'Your original account' : 'Separate API credentials & data'}
                    </div>
                  </div>
                </div>
                <div className="mt-3">
                  {isCurrent ? (
                    <span className="rom-pill border-rom-purple/40 bg-rom-purple/10 text-rom-purple">
                      <Check className="h-3 w-3" /> This window
                    </span>
                  ) : (
                    <button onClick={() => void launch(a.name)} className="rom-btn-default text-xs">
                      <ExternalLink className="h-3.5 w-3.5" /> Open
                    </button>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      </Section>

      <Section title="How it works">
        <Card>
          <ul className="list-disc space-y-1.5 pl-5 text-xs text-rom-muted">
            <li>Each account has its own API credentials, balance, open positions, history, and settings — nothing is shared.</li>
            <li>Opening an account launches it in a <span className="text-white">separate window</span>; both run at the same time. Opening one that&apos;s already open just brings it to the front.</li>
            <li>The account you&apos;re currently in is shown at the top-left of the sidebar.</li>
            <li>New accounts start fresh — connect that account&apos;s API credentials on its API page.</li>
          </ul>
        </Card>
      </Section>

      <NameDialog
        open={createOpen}
        title="New account"
        label="Creates a fresh, fully separate account profile (its own API credentials & data). It opens in a new window where you connect that account's API credentials."
        placeholder="e.g. Main, Alt, Sports…"
        confirmLabel="Create & open"
        onSubmit={(name) => void create(name)}
        onClose={() => setCreateOpen(false)}
      />
    </Page>
  );
}
