from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..io.card_yaml import CARDS_DIR, YAML_AVAILABLE, load_card_from_yaml, pitch_to_color

try:  # pragma: no cover - optional dependency
    from ..io import card_yaml as _card_yaml_module
except Exception:  # pragma: no cover
    _card_yaml_module = None  # type: ignore


_BASE_TRIGGERS: Tuple[str, ...] = ("on_declare", "on_hit", "on_block", "on_graveyard")
_FALLBACK_DURATIONS: Tuple[str, ...] = ("", "this_turn", "this_chain_link", "this_combat_chain", "permanent")
_FALLBACK_KEYWORDS: Tuple[str, ...] = (
    "attack_action",
    "defense_reaction",
    "attack_reaction",
    "go_again",
    "instant",
    "reaction",
    "buff",
)


def _ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _normalize_token(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


@dataclass(frozen=True)
class RuleFeatureSpec:
    triggers: Tuple[str, ...]
    durations: Tuple[str, ...]
    keywords: Tuple[str, ...]


@dataclass(frozen=True)
class RuleFeatureData:
    trigger_flags: Tuple[int, ...]
    duration_flags: Tuple[int, ...]
    keyword_flags: Tuple[int, ...]


class YamlFeatureExtractor:
    """Extract rule-related features from card YAML metadata."""

    def __init__(self, cards_dir: str = CARDS_DIR) -> None:
        self.cards_dir = Path(cards_dir)
        self.spec = self._build_spec()
        self._cache: Dict[Tuple[str, int], RuleFeatureData] = {}

    def _build_spec(self) -> RuleFeatureSpec:
        triggers = list(dict.fromkeys(_normalize_token(t) for t in _BASE_TRIGGERS if t))
        durations = set(_normalize_token(item) for item in _FALLBACK_DURATIONS if item is not None)
        keywords = set(_normalize_token(item) for item in _FALLBACK_KEYWORDS if item is not None)

        yaml_module = getattr(_card_yaml_module, "yaml", None)
        if YAML_AVAILABLE and yaml_module:
            raw_paths = list(self.cards_dir.glob("*.yaml"))
            for path in raw_paths:
                try:
                    with path.open("r", encoding="utf-8") as handle:
                        data = yaml_module.safe_load(handle) or {}
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                rules = data.get("rules")
                if isinstance(rules, dict):
                    durations.update(_normalize_token(rules.get("duration")))
                    for kw in _ensure_list(rules.get("keywords")):
                        keywords.add(_normalize_token(kw))
                    for effect in _ensure_list(rules.get("effects")):
                        if not isinstance(effect, dict):
                            continue
                        when = _normalize_token(effect.get("when"))
                        if when:
                            triggers.append(when)
                        durations.add(_normalize_token(effect.get("duration")))
                        for kw in _ensure_list(effect.get("keywords")):
                            keywords.add(_normalize_token(kw))
        triggers = [token for token in triggers if token]
        durations = {token for token in durations if token}
        keywords = {token for token in keywords if token}
        return RuleFeatureSpec(
            triggers=tuple(sorted(dict.fromkeys(triggers))),
            durations=tuple(sorted(durations)),
            keywords=tuple(sorted(keywords)),
        )

    def _zero(self) -> RuleFeatureData:
        return RuleFeatureData(
            trigger_flags=tuple(0 for _ in self.spec.triggers),
            duration_flags=tuple(0 for _ in self.spec.durations),
            keyword_flags=tuple(0 for _ in self.spec.keywords),
        )

    def _features_from_yaml(self, data: Optional[Dict[str, Any]]) -> RuleFeatureData:
        if not data:
            return self._zero()
        rules = data.get("rules")
        if not isinstance(rules, dict):
            return self._zero()

        trig = [0 for _ in self.spec.triggers]
        durations = [0 for _ in self.spec.durations]
        keywords = [0 for _ in self.spec.keywords]

        def mark_trigger(token: str) -> None:
            token_norm = _normalize_token(token)
            if not token_norm:
                return
            try:
                idx = self.spec.triggers.index(token_norm)
            except ValueError:
                return
            trig[idx] = 1

        def mark_duration(token: str) -> None:
            token_norm = _normalize_token(token)
            if not token_norm:
                return
            try:
                idx = self.spec.durations.index(token_norm)
            except ValueError:
                return
            durations[idx] = 1

        def mark_keyword(token: str) -> None:
            token_norm = _normalize_token(token)
            if not token_norm:
                return
            try:
                idx = self.spec.keywords.index(token_norm)
            except ValueError:
                return
            keywords[idx] = 1

        mark_duration(rules.get("duration"))
        for kw in _ensure_list(rules.get("keywords")):
            mark_keyword(kw)

        effects = rules.get("effects")
        if isinstance(effects, list):
            for effect in effects:
                if not isinstance(effect, dict):
                    continue
                mark_trigger(effect.get("when"))
                mark_duration(effect.get("duration"))
                for kw in _ensure_list(effect.get("keywords")):
                    mark_keyword(kw)

        return RuleFeatureData(
            trigger_flags=tuple(trig),
            duration_flags=tuple(durations),
            keyword_flags=tuple(keywords),
        )

    def features_for_card(self, card_name: str, pitch: int) -> RuleFeatureData:
        key = (card_name.lower(), int(pitch))
        if key in self._cache:
            return self._cache[key]
        if YAML_AVAILABLE:
            color = pitch_to_color(pitch)
            data = load_card_from_yaml(card_name, color)
        else:
            data = None
        features = self._features_from_yaml(data)
        self._cache[key] = features
        return features


DEFAULT_YAML_EXTRACTOR = YamlFeatureExtractor()


__all__ = [
    "DEFAULT_YAML_EXTRACTOR",
    "RuleFeatureData",
    "RuleFeatureSpec",
    "YamlFeatureExtractor",
]
