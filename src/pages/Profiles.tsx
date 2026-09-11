import { useRef, useState } from 'react';
import {
  Check, Copy, Download, FolderOpen, FolderPlus, Pencil, Trash2, Upload,
} from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Empty, NameDialog, Page } from '../components/common';
import { cls, fmtDateTime } from '../utils/format';
import type { Profile, ProfileScope } from '@shared/types';

const SCOPES: { scope: ProfileScope; title: string; subtitle: string }[] = [
  { scope: 'main', title: 'Main engine', subtitle: 'Whale / momentum / convergence scanner' },
  { scope: 'crypto', title: 'Crypto market', subtitle: '15-minute crypto up/down engine' },
  { scope: 'copy', title: 'Copy trading', subtitle: 'Follow-wallet copy engine' },
];

const scopeOf = (p: Profile): ProfileScope => p.scope ?? 'main';

export function ProfilesPage() {
  const { state, refresh } = useApp();
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [createScope, setCreateScope] = useState<ProfileScope | null>(null);
  const [renameTarget, setRenameTarget] = useState<Profile | null>(null);

  const profiles = state?.customProfiles ?? [];
  const activeFor = (scope: ProfileScope): string | null =>
    scope === 'crypto'
      ? state?.activeCryptoProfileId ?? null
      : scope === 'copy'
        ? state?.activeCopyProfileId ?? null
        : state?.activeProfileId ?? null;

  const create = async (name: string): Promise<void> => {
    const scope = createScope ?? 'main';
    setCreateScope(null);
    const r = await window.rom.profiles.save(name, undefined, scope);
    if (r.ok) {
      toast.success(r.message || 'Saved');
      await refresh.state();
    } else toast.error(r.message || 'Failed to save');
  };

  const rename = async (name: string): Promise<void> => {
    const target = renameTarget;
    setRenameTarget(null);
    if (!target || name === target.name) return;
    const r = await window.rom.profiles.rename(target.id, name);
    if (r.ok) {
      toast.success('Renamed');
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const remove = async (id: string, name: string): Promise<void> => {
    if (!window.confirm(`Delete profile "${name}"?`)) return;
    const r = await window.rom.profiles.delete(id);
    if (r.ok) {
      toast.success('Deleted');
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const duplicate = async (id: string): Promise<void> => {
    const r = await window.rom.profiles.duplicate(id);
    if (r.ok) {
      toast.success(`Duplicated`);
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const apply = async (id: string): Promise<void> => {
    const r = await window.rom.profiles.apply(id);
    if (r.ok) {
      toast.success(r.message || 'Applied');
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const exportProfile = async (id: string, name: string): Promise<void> => {
    const r = await window.rom.profiles.export(id);
    if (!r.ok || !r.data) {
      toast.error(r.message || 'Export failed');
      return;
    }
    const blob = new Blob([r.data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name.replace(/[^a-z0-9-_]+/gi, '_')}.romprofile.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const importClick = (): void => fileInputRef.current?.click();

  const importHandler = async (e: React.ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const r = await window.rom.profiles.import(text);
      if (r.ok) {
        toast.success(r.message || 'Imported');
        await refresh.state();
      } else toast.error(r.message || 'Import failed');
    } catch (err: any) {
      toast.error(err?.message || 'Read failed');
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <Page
      title="Profiles"
      subtitle="Save snapshots of each engine's config and switch between them. Profiles are per-engine — applying one only changes that engine."
      actions={
        <>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => void importHandler(e)}
          />
          <button onClick={importClick} className="rom-btn-default">
            <Upload className="h-4 w-4" /> Import
          </button>
        </>
      }
    >
      <div className="space-y-8">
        {SCOPES.map(({ scope, title, subtitle }) => {
          const list = profiles.filter((p) => scopeOf(p) === scope);
          const activeId = activeFor(scope);
          return (
            <section key={scope}>
              <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
                <div>
                  <h2 className="text-sm font-semibold text-white">{title}</h2>
                  <p className="text-xs text-rom-dim">{subtitle}</p>
                </div>
                <button
                  onClick={() => setCreateScope(scope)}
                  className="rom-btn-default ml-auto text-xs"
                >
                  <FolderPlus className="h-3.5 w-3.5" /> New from current settings
                </button>
              </div>

              {list.length === 0 ? (
                <Empty
                  title={`No ${title.toLowerCase()} profiles`}
                  description="Save the current settings for this engine as a profile to switch between setups."
                  action={
                    <button onClick={() => setCreateScope(scope)} className="rom-btn-primary">
                      <FolderPlus className="h-4 w-4" /> Save current as profile
                    </button>
                  }
                />
              ) : (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {list.map((p) => (
                    <ProfileCard
                      key={p.id}
                      p={p}
                      active={activeId === p.id}
                      onApply={() => apply(p.id)}
                      onRename={() => setRenameTarget(p)}
                      onDuplicate={() => duplicate(p.id)}
                      onExport={() => exportProfile(p.id, p.name)}
                      onDelete={() => remove(p.id, p.name)}
                    />
                  ))}
                </div>
              )}
            </section>
          );
        })}
      </div>

      <NameDialog
        open={createScope !== null}
        title={`New ${createScope ?? 'main'} profile from current settings`}
        label="Saves a snapshot of this engine's current config."
        placeholder="Profile name"
        confirmLabel="Save"
        onSubmit={(name) => void create(name)}
        onClose={() => setCreateScope(null)}
      />
      <NameDialog
        open={renameTarget !== null}
        title="Rename profile"
        initialValue={renameTarget?.name ?? ''}
        confirmLabel="Rename"
        onSubmit={(name) => void rename(name)}
        onClose={() => setRenameTarget(null)}
      />
    </Page>
  );
}

function miniStats(p: Profile): { label: string; value: string }[] {
  const c = p.config;
  switch (scopeOf(p)) {
    case 'crypto':
      return [
        { label: 'dir', value: c.crypto15mDirectionMode === 'contrarian' ? 'fade' : 'fav' },
        { label: 'fav≥', value: `${Math.round((c.crypto15mEntryThreshold ?? 0) * 100)}¢` },
        { label: 'size', value: `${c.crypto15mOrderSize ?? 0}` },
      ];
    case 'copy':
      return [
        { label: 'wallets', value: `${c.copyWallets?.length ?? 0}` },
        { label: 'sizing', value: c.copySizingMode ?? 'fixed' },
        { label: 'max', value: `${c.copyMaxConcurrent ?? 0}` },
      ];
    default:
      return [
        { label: 'env', value: c.network },
        { label: 'cap', value: `$${c.hardMaxPositionUsd}` },
        { label: 'open', value: `${c.maxOpenPositions}` },
      ];
  }
}

function ProfileCard({
  p, active, onApply, onRename, onDuplicate, onExport, onDelete,
}: {
  p: Profile;
  active: boolean;
  onApply: () => void;
  onRename: () => void;
  onDuplicate: () => void;
  onExport: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={cls(
        'rounded-xl border bg-rom-surface p-4 transition-colors',
        active
          ? 'border-rom-purple shadow-rom-soft'
          : 'border-rom-border hover:border-rom-borderHi',
      )}
    >
      <div className="flex items-start gap-3">
        <div className={cls(
          'grid h-10 w-10 place-items-center rounded-lg',
          active ? 'bg-rom-glow text-white' : 'bg-rom-surface2 text-rom-muted',
        )}>
          <FolderOpen className="h-4 w-4" />
        </div>
        <div className="flex-1">
          <div className="text-sm font-medium text-white">{p.name}</div>
          <div className="text-xs text-rom-muted">Updated {fmtDateTime(p.updatedAt)}</div>
          {p.description && <p className="mt-1 text-xs text-rom-dim">{p.description}</p>}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
        {miniStats(p).map((m) => <Mini key={m.label} label={m.label} value={m.value} />)}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {!active && (
          <button onClick={onApply} className="rom-btn-primary text-xs">Apply</button>
        )}
        {active && (
          <span className="rom-pill border-rom-purple/40 bg-rom-purple/10 text-rom-purple">
            <Check className="h-3 w-3" /> Active
          </span>
        )}
        <button onClick={onRename} className="rom-btn-ghost text-xs">
          <Pencil className="h-3.5 w-3.5" /> Rename
        </button>
        <button onClick={onDuplicate} className="rom-btn-ghost text-xs">
          <Copy className="h-3.5 w-3.5" /> Duplicate
        </button>
        <button onClick={onExport} className="rom-btn-ghost text-xs">
          <Download className="h-3.5 w-3.5" /> Export
        </button>
        <button onClick={onDelete} className="rom-btn-ghost text-xs text-rom-loss/80 hover:text-rom-loss">
          <Trash2 className="h-3.5 w-3.5" /> Delete
        </button>
      </div>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-rom-border bg-rom-surface2 px-2 py-1">
      <div className="text-[10px] uppercase tracking-wider text-rom-dim">{label}</div>
      <div className="font-mono text-[11px] text-white">{value}</div>
    </div>
  );
}
