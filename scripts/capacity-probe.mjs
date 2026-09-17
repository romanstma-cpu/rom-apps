import { ensureVenv, run, VENV_PY } from './python-utils.mjs';

ensureVenv();
run(VENV_PY, ['capacity_probe.py', ...process.argv.slice(2)]);
