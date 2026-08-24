"""YAML config loading with per-category overrides."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATHS = ("config.yaml", "config.example.yaml")


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Config:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        candidates = [path] if path else [p for p in DEFAULT_PATHS]
        for cand in candidates:
            if cand and Path(cand).exists():
                with open(cand) as fh:
                    return cls(yaml.safe_load(fh) or {})
        raise FileNotFoundError(
            f"No config found (looked for {', '.join(candidates)})")

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def for_category(self, category: str) -> dict[str, Any]:
        """Config dict with this category's overrides merged in."""
        overrides = (self.data.get("category_overrides") or {}).get(category, {})
        return _deep_merge(self.data, overrides)

    @property
    def mode(self) -> str:
        return self.data.get("mode", "paper")

    @staticmethod
    def env(name: str, required: bool = False) -> str | None:
        val = os.environ.get(name)
        if required and not val:
            raise RuntimeError(f"Environment variable {name} is required")
        return val
