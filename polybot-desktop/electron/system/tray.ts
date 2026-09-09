import { app, Menu, Tray, nativeImage } from 'electron';
import { join } from 'node:path';
import { existsSync } from 'node:fs';
import { pythonBackend } from './python-backend';

let tray: Tray | null = null;

function backendStatusLine(): string {
  const status = pythonBackend.info().status;
  if (status === 'running') return 'backend running';
  if (status === 'starting' || status === 'restarting') return 'backend starting…';
  if (status === 'crashed') {
    const { gaveUp, retrying } = pythonBackend.recoveryState();
    if (retrying || gaveUp) return 'backend crashed — retrying';
    return 'backend crashed';
  }
  return 'backend stopped';
}

interface TrayHandlers {
  openWindow: () => void;
  toggleTrading: () => void;
  isTrading: () => boolean;
  quit: () => void;
}

function iconPath(): string {
  const candidates = [
    app.isPackaged
      ? join(process.resourcesPath, 'app.asar.unpacked', 'resources', 'rom.ico')
      : join(process.cwd(), 'resources', 'rom.ico'),
    app.isPackaged
      ? join(process.resourcesPath, 'rom.ico')
      : join(process.cwd(), 'resources', 'rom.ico'),

    join(__dirname, '..', 'resources', 'rom.ico'),
    join(__dirname, '..', 'resources', 'rom.png'),
    join(process.cwd(), 'resources', 'rom.png'),
  ];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  return candidates[candidates.length - 1];
}

export function installTray(handlers: TrayHandlers): Tray {
  if (tray && !tray.isDestroyed()) return tray;
  const img = nativeImage.createFromPath(iconPath());
  tray = new Tray(img.isEmpty() ? nativeImage.createEmpty() : img);
  tray.setToolTip('ROM PolyBot');
  tray.on('click', () => handlers.openWindow());
  tray.on('double-click', () => handlers.openWindow());
  rebuild(handlers);
  return tray;
}

export function rebuild(handlers: TrayHandlers): void {
  if (!tray) return;
  const trading = handlers.isTrading();
  const statusLine = backendStatusLine();

  const status = pythonBackend.info().status;
  tray.setToolTip(
    status === 'running'
      ? 'ROM PolyBot'
      : `ROM PolyBot — ${statusLine.toUpperCase()}`,
  );
  const menu = Menu.buildFromTemplate([
    { label: 'Open ROM PolyBot', click: () => handlers.openWindow() },
    { type: 'separator' },

    { label: `Status: ${statusLine}`, enabled: false },
    { type: 'separator' },
    {
      label: trading ? 'Pause Trading' : 'Resume Trading',
      click: () => handlers.toggleTrading(),
    },
    { type: 'separator' },
    { label: 'Quit', click: () => handlers.quit() },
  ]);
  tray.setContextMenu(menu);
}

export function destroyTray(): void {
  if (tray && !tray.isDestroyed()) tray.destroy();
  tray = null;
}
