"""Stage registry, discovered from this package.

Stages are found by scanning for `stageN_*.py` modules exporting a `STAGE`,
then ordered by stage number. Discovery rather than a hand-maintained list:
stages are built independently, and a registry every author must edit is a
merge conflict waiting to happen and a stage silently missing from a run when
someone forgets.

A module that fails to import is reported as a broken stage rather than
vanishing from the run -- a validation harness that quietly skips a check is
the failure mode this whole thing exists to remove.
"""
from __future__ import annotations

import importlib
import pkgutil

BROKEN = {}


def _discover():
    found = {}
    for info in pkgutil.iter_modules(__path__):
        if not info.name.startswith('stage'):
            continue
        try:
            module = importlib.import_module(f'{__name__}.{info.name}')
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            BROKEN[info.name] = f'{type(exc).__name__}: {exc}'
            continue
        stage = getattr(module, 'STAGE', None)
        if stage is None:
            BROKEN[info.name] = 'module exports no STAGE'
            continue
        if stage.number in found:
            BROKEN[info.name] = f'duplicate stage number {stage.number}'
            continue
        found[stage.number] = stage
    return [found[n] for n in sorted(found)]


ALL_STAGES = _discover()
