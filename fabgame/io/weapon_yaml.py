"""Weapon YAML loader module - loads weapon data from YAML files.

This module provides functions to load weapon configurations from YAML files,
creating a registry system to replace hard-coded weapon logic.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

from .card_yaml import YAML_AVAILABLE, slugify
from ..models import Weapon


WEAPONS_DIR = os.environ.get("FAB_WEAPONS_DIR", "data/weapons")


def _candidate_paths(name: str) -> List[str]:
    """Generate candidate file paths for a weapon name.

    Args:
        name: Weapon name to search for

    Returns:
        List of potential file paths to check
    """
    slug = slugify(name)
    return [
        os.path.join(WEAPONS_DIR, f"{slug}.yaml"),
        os.path.join(WEAPONS_DIR, f"weapon_{slug}.yaml"),
    ]


def load_weapon_from_yaml(name: str) -> Optional[Dict[str, Any]]:
    """Load weapon data from YAML file.

    Args:
        name: Weapon name to load

    Returns:
        Dictionary of weapon data, or None if not found or YAML unavailable
    """
    if not YAML_AVAILABLE or yaml is None:
        return None

    for path in _candidate_paths(name):
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Invalid weapon YAML (expected mapping): {path}")
        return data
    return None


def create_weapon_from_yaml(name: str) -> Optional[Weapon]:
    """Create a Weapon object from YAML data.

    Args:
        name: Weapon name to load and create

    Returns:
        Weapon object if found, None otherwise
    """
    weapon_data = load_weapon_from_yaml(name)
    if not weapon_data:
        return None

    weapon_name = weapon_data.get("name", name)
    base_attack = weapon_data.get("base_attack", 0)
    cost = weapon_data.get("cost", 0)
    once_per_turn = weapon_data.get("once_per_turn", False)
    keywords = weapon_data.get("keywords", [])

    if not isinstance(keywords, list):
        keywords = []

    return Weapon(
        name=weapon_name,
        base_attack=base_attack,
        cost=cost,
        once_per_turn=once_per_turn,
        keywords=keywords,
    )


def load_weapon_from_arena(arena: Optional[List[Any]]) -> Optional[Weapon]:
    """Load weapon from arena configuration list.

    Searches the arena list for weapon names and attempts to load them from YAML.

    Args:
        arena: List of equipment/weapon configurations

    Returns:
        Weapon object if found, None otherwise
    """
    if not arena:
        return None

    # Extract weapon names from arena configuration
    weapon_names: List[str] = []
    for entry in arena:
        if isinstance(entry, dict):
            name = entry.get("name")
            if name:
                weapon_names.append(str(name).strip())
        elif isinstance(entry, str):
            weapon_names.append(entry.strip())

    # Try to load each weapon name from YAML
    for weapon_name in weapon_names:
        weapon = create_weapon_from_yaml(weapon_name)
        if weapon:
            return weapon

    return None


__all__ = [
    "load_weapon_from_yaml",
    "create_weapon_from_yaml",
    "load_weapon_from_arena",
    "WEAPONS_DIR",
]
