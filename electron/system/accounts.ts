import { app } from 'electron';
import { existsSync, mkdirSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { spawn } from 'node:child_process';

let DEFAULT_USERDATA = '';
let CURRENT_ACCOUNT = '';

export function sanitizeAccountName(s: string): string {
  return (s || '')
    .replace(/[^a-zA-Z0-9 _-]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 40);
}

function parseAccountArg(argv: string[]): string {
  for (const a of argv) {
    const m = /^--account=(.*)$/.exec(a);
    if (m) return sanitizeAccountName(m[1]);
  }
  const i = argv.indexOf('--account');
  if (i >= 0 && argv[i + 1]) return sanitizeAccountName(argv[i + 1]);
  return '';
}

export function applyAccountFromArgv(): void {
  DEFAULT_USERDATA = app.getPath('userData');
  CURRENT_ACCOUNT = parseAccountArg(process.argv);
  if (CURRENT_ACCOUNT) {
    const dir = join(DEFAULT_USERDATA, 'accounts', CURRENT_ACCOUNT);
    mkdirSync(dir, { recursive: true });
    app.setPath('userData', dir);
  }
}

export function currentAccount(): string {
  return CURRENT_ACCOUNT || 'Default';
}

function accountsRoot(): string {
  return join(DEFAULT_USERDATA, 'accounts');
}

export interface AccountEntry {
  name: string;
  current: boolean;
  isDefault: boolean;
}

export function listAccounts(): AccountEntry[] {
  const out: AccountEntry[] = [
    { name: 'Default', current: CURRENT_ACCOUNT === '', isDefault: true },
  ];
  try {
    const root = accountsRoot();
    if (existsSync(root)) {
      for (const d of readdirSync(root, { withFileTypes: true })) {
        if (d.isDirectory()) {
          out.push({ name: d.name, current: d.name === CURRENT_ACCOUNT, isDefault: false });
        }
      }
    }
  } catch {}
  return out;
}

export function createAccount(name: string): { ok: boolean; name?: string; message?: string } {
  const n = sanitizeAccountName(name);
  if (!n) return { ok: false, message: 'Enter a name (letters, numbers, spaces, - or _).' };
  if (n.toLowerCase() === 'default') return { ok: false, message: '"Default" is reserved.' };
  const dir = join(accountsRoot(), n);
  if (existsSync(dir)) return { ok: false, message: `An account named "${n}" already exists.` };
  try {
    mkdirSync(dir, { recursive: true });
  } catch (e: any) {
    return { ok: false, message: String(e?.message || e) };
  }
  return { ok: true, name: n };
}

export function launchAccount(name: string): { ok: boolean; message?: string } {
  const n = name && name.toLowerCase() !== 'default' ? sanitizeAccountName(name) : '';
  const flagArgs = n ? ['--account', n] : [];
  try {
    if (app.isPackaged) {
      spawn(process.execPath, flagArgs, { detached: true, stdio: 'ignore' }).unref();
    } else {
      spawn(process.execPath, [app.getAppPath(), ...flagArgs], {
        detached: true, stdio: 'ignore',
      }).unref();
    }
    return { ok: true };
  } catch (e: any) {
    return { ok: false, message: String(e?.message || e) };
  }
}
