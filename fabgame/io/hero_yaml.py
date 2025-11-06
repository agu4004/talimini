from __future__ import annotations

import os
from typing import Any, Dict, Optional

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

from .card_yaml import CARDS_DIR, YAML_AVAILABLE, slugify

HERO_DIR = os.environ.get("FAB_HERO_DIR", "data/heroes")


def _candidate_paths(name: str) -> list[str]:
    slug = slugify(name)
    return [
        os.path.join(HERO_DIR, f"{slug}.yaml"),
        os.path.join(CARDS_DIR, f"{slug}.yaml"),
        os.path.join(CARDS_DIR, f"hero_{slug}.yaml"),
    ]


def load_hero_from_yaml(name: str) -> Optional[Dict[str, Any]]:
    if not YAML_AVAILABLE or yaml is None:
        return None
    for path in _candidate_paths(name):
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Invalid hero YAML (expected mapping): {path}")
        return data
    return None


__all__ = ["load_hero_from_yaml", "HERO_DIR"]
