import { spawnSync } from 'node:child_process';

const commands = [
  ['npm', ['run', 'typecheck']],
  ['npm', ['run', 'check:ui']],
  ['npm', ['run', 'check:e2e-drift']],
  ['npm', ['run', 'py:test', '--', '-q']],
  ['npm', ['run', 'check:capacity']],
  ['npm', ['run', 'build']],
];

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
