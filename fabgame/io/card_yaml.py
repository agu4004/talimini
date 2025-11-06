from __future__ import annotations

import os
import re
import copy
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore
except Exception:  # pragma: no cover - PyYAML not installed
    yaml = None  # type: ignore


CARDS_DIR = os.environ.get("FAB_CARDS_DIR", "data/cards")
YAML_AVAILABLE = yaml is not None

_slug_re = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _slug_re.sub("_", name.strip().lower()).strip("_")


def pitch_to_color(pitch: int) -> Optional[str]:
    return {1: "red", 2: "yellow", 3: "blue"}.get(pitch)


def card_yaml_path(name: str, color: str) -> str:
    slug = slugify(name)
    return os.path.join(CARDS_DIR, f"{slug}_{color.lower()}.yaml")


def _coerce_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Expected integer-like value, received {value!r}")


def _ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _normalize_rules(data: Dict[str, Any]) -> None:
    rules = data.get("rules")
    if rules is None:
        return
    if not isinstance(rules, dict):
        raise TypeError("rules section must be a mapping if present")
    effects = rules.get("effects")
    if effects is None:
        return
    if not isinstance(effects, list):
        raise TypeError("rules.effects must be a list if present")
    normalized: List[Dict[str, Any]] = []
    for entry in effects:
        if isinstance(entry, dict):
            normalized.append(entry)
        else:
            raise TypeError("rules.effects entries must be mappings")
    rules["effects"] = normalized


def _apply_schema_defaults(data: Dict[str, Any], *, color: Optional[str]) -> Dict[str, Any]:
    result = dict(data)
    if "name" not in result and "id" in result:
        result["name"] = str(result["id"])

    if not result.get("name"):
        raise ValueError("Card YAML must define a name")

    if not result.get("type"):
        raise ValueError("Card YAML must define a type")

    for key, default in (("cost", 0), ("attack", 0), ("defense", 0), ("pitch", 0)):
        result[key] = _coerce_int(result.get(key), default)

    if "color" not in result or result.get("color") in (None, ""):
        inferred = color or pitch_to_color(result.get("pitch", 0))
        if inferred:
            result["color"] = inferred

    keywords = result.get("keywords")
    result["keywords"] = [str(item) for item in _ensure_list(keywords)]

    text_value = result.get("text") or ""
    result["text"] = str(text_value)

    engine_hints = result.get("engine_hints")
    if engine_hints is not None and not isinstance(engine_hints, dict):
        raise TypeError("engine_hints section must be a mapping if present")

    _normalize_rules(result)
    return result


def load_card_from_yaml(name: str, color: Optional[str]) -> Optional[Dict[str, Any]]:
    if not YAML_AVAILABLE:
        return None
    if not color:
        return None
    path = card_yaml_path(name, color)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Card YAML at {path} must be a mapping")
    try:
        data = _apply_schema_defaults(data, color=color)
    except Exception as exc:
        raise ValueError(f"Card YAML normalization failed at {path}: {exc}") from exc
    if "abilities" in data:
        data["abilities"] = normalize_abilities(data["abilities"])
    return data


def normalize_abilities(raw: Any) -> Dict[str, List[Dict[str, Any]]]:
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise TypeError("abilities section must be a mapping")
    normalized: Dict[str, List[Dict[str, Any]]] = {}
    for key, value in raw.items():
        trigger = str(key)
        if value is None:
            normalized[trigger] = []
            continue
        if not isinstance(value, list):
            raise TypeError(f"abilities[{trigger!r}] must be a list")
        rules: List[Dict[str, Any]] = []
        for entry in value:
            if isinstance(entry, dict):
                rules.append(copy.deepcopy(entry))
            else:
                raise TypeError(f"abilities[{trigger!r}] entries must be mappings")
        normalized[trigger] = rules
    return normalized


def extract_abilities(data: Optional[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    if not data:
        return {}
    raw = data.get("abilities")
    return normalize_abilities(raw) if raw else {}


__all__ = [
    "CARDS_DIR",
    "YAML_AVAILABLE",
    "slugify",
    "pitch_to_color",
    "card_yaml_path",
    "load_card_from_yaml",
    "normalize_abilities",
    "extract_abilities",
]
