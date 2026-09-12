import { app } from 'electron';

export function setStartWithWindows(enabled: boolean): void {
  try {
    if (enabled && process.platform === 'win32') {
      app.setLoginItemSettings({
        openAtLogin: true,
        path: process.execPath,
        args: ['--autostart'],
      });
    } else {
      app.setLoginItemSettings({ openAtLogin: enabled });
    }
  } catch {}
}
