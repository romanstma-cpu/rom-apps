import { spawnSync } from 'node:child_process';

const commands = [
  ['npm', ['run', 'typecheck']],
  ['npm', ['run', 'check:e2e-drift']],
  ['npm', ['run', 'py:test', '--', '-q']],
  ['npm', ['run', 'check:capacity']],
  ['npm', ['run', 'build']],
];

// Electron's interactive visual audit requires a desktop session. GitHub's
// macOS runner can start Electron but never exposes its window to Playwright;
// the Mac workflow performs a packaged-app launch smoke test after this gate.
if (process.platform === 'win32' || process.env.ROM_RUN_UI_AUDIT === '1') {
  commands.splice(1, 0, ['npm', ['run', 'check:ui']]);
}

for (const [command, args] of commands) {
  console.log(`\n>> Release gate: ${command} ${args.join(' ')}`);
  const result = spawnSync(command, args, {
    cwd: process.cwd(),
    env: process.env,
    shell: process.platform === 'win32',
    stdio: 'inherit',
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

console.log('\n>> RELEASE GATE PASSED');
