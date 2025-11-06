from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pragma: no cover - dependency guard
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("fabgame.rl.encoding requires numpy to be installed") from exc

from ..engine import current_actor_index
from ..models import Card, CombatStep, GameState, Phase
from ..io import card_yaml as _card_yaml_module
from ..io.card_yaml import CARDS_DIR, YAML_AVAILABLE
from .yaml_features import DEFAULT_YAML_EXTRACTOR, RuleFeatureData


_FALLBACK_CARD_KEYWORDS: Tuple[str, ...] = (
    "attack_action",
    "attack_reaction",
    "defense_reaction",
    "reaction",
    "go_again",
    "combo",
    "dominate",
    "crush",
    "ninja",
    "guardian",
)


def _ensure_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _normalize_keyword(value: str) -> str:
    return str(value).strip().lower()


def _collect_card_keywords() -> Tuple[str, ...]:
    keywords = set(_normalize_keyword(item) for item in _FALLBACK_CARD_KEYWORDS)
    yaml_module = getattr(_card_yaml_module, "yaml", None)
    if YAML_AVAILABLE and yaml_module:
        for path in Path(CARDS_DIR).glob("*.yaml"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = yaml_module.safe_load(handle) or {}
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            for kw in _ensure_list(data.get("keywords")):
                keywords.add(_normalize_keyword(kw))
            rules = data.get("rules")
            if isinstance(rules, dict):
                for kw in _ensure_list(rules.get("keywords")):
                    keywords.add(_normalize_keyword(kw))
    keywords.discard("")
    return tuple(sorted(keywords))


def _collect_hero_vocab() -> Tuple[str, ...]:
    heroes = {"generic hero"}
    yaml_module = getattr(_card_yaml_module, "yaml", None)
    if YAML_AVAILABLE and yaml_module:
        hero_paths = list(Path(CARDS_DIR).glob("hero_*.yaml"))
        for path in hero_paths:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = yaml_module.safe_load(handle) or {}
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            name = data.get("name") or data.get("id")
            if isinstance(name, str) and name.strip():
                heroes.add(name.strip().lower())
    return tuple(sorted(heroes))


CARD_KEYWORD_VOCAB = _collect_card_keywords()
CARD_KEYWORD_INDEX = {token: idx for idx, token in enumerate(CARD_KEYWORD_VOCAB)}
RULE_TRIGGER_VOCAB = DEFAULT_YAML_EXTRACTOR.spec.triggers
RULE_DURATION_VOCAB = DEFAULT_YAML_EXTRACTOR.spec.durations
RULE_KEYWORD_VOCAB = DEFAULT_YAML_EXTRACTOR.spec.keywords
HERO_VOCAB = _collect_hero_vocab()
HERO_INDEX = {token: idx for idx, token in enumerate(HERO_VOCAB)}
PHASE_VOCAB = tuple(phase for phase in Phase)
PHASE_INDEX = {phase: idx for idx, phase in enumerate(PHASE_VOCAB)}
COMBAT_STEP_VOCAB = tuple(step for step in CombatStep)
COMBAT_STEP_INDEX = {step: idx for idx, step in enumerate(COMBAT_STEP_VOCAB)}


@dataclass(frozen=True)
class EncoderConfig:
    max_hand_size: int = 6
    max_arsenal_size: int = 2
    max_pitch_size: int = 8
    max_grave_size: int = 8
    keyword_vocab: Tuple[str, ...] = CARD_KEYWORD_VOCAB
    hero_vocab: Tuple[str, ...] = HERO_VOCAB
    rule_trigger_vocab: Tuple[str, ...] = RULE_TRIGGER_VOCAB
    rule_duration_vocab: Tuple[str, ...] = RULE_DURATION_VOCAB
    rule_keyword_vocab: Tuple[str, ...] = RULE_KEYWORD_VOCAB


def _card_feature_dim(config: EncoderConfig) -> int:
    base_numeric = 4  # attack, defense, cost, pitch
    flag_features = 4  # is_attack, is_defense, is_reaction, is_attack_reaction
    return (
        base_numeric
        + flag_features
        + len(config.keyword_vocab)
        + len(config.rule_trigger_vocab)
        + len(config.rule_duration_vocab)
        + len(config.rule_keyword_vocab)
    )


def _keyword_flags(card: Card, config: EncoderConfig) -> np.ndarray:
    flags = np.zeros(len(config.keyword_vocab), dtype=np.float32)
    for keyword in card.keywords:
        key = _normalize_keyword(keyword)
        if not key:
            continue
        try:
            idx = CARD_KEYWORD_INDEX[key]
        except KeyError:
            continue
        flags[idx] = 1.0
    return flags


def _rule_arrays(rule_data: RuleFeatureData, config: EncoderConfig) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    trigger = np.array(rule_data.trigger_flags, dtype=np.float32)
    duration = np.array(rule_data.duration_flags, dtype=np.float32)
    keywords = np.array(rule_data.keyword_flags, dtype=np.float32)
    trigger.resize((len(config.rule_trigger_vocab),), refcheck=False)
    duration.resize((len(config.rule_duration_vocab),), refcheck=False)
    keywords.resize((len(config.rule_keyword_vocab),), refcheck=False)
    return trigger, duration, keywords


def encode_card(card: Optional[Card], config: EncoderConfig = EncoderConfig()) -> np.ndarray:
    dim = _card_feature_dim(config)
    if card is None:
        return np.zeros(dim, dtype=np.float32)

    base = np.array(
        [float(card.attack), float(card.defense), float(card.cost), float(card.pitch)],
        dtype=np.float32,
    )
    flags = np.array(
        [
            1.0 if card.is_attack() else 0.0,
            1.0 if card.is_defense() else 0.0,
            1.0 if card.is_reaction() else 0.0,
            1.0 if card.is_attack_reaction() else 0.0,
        ],
        dtype=np.float32,
    )
    keyword_flags = _keyword_flags(card, config)
    rule_data = DEFAULT_YAML_EXTRACTOR.features_for_card(card.name, card.pitch)
    rule_trigger, rule_duration, rule_keyword = _rule_arrays(rule_data, config)
    return np.concatenate([base, flags, keyword_flags, rule_trigger, rule_duration, rule_keyword]).astype(np.float32)


def _pad_zone(cards: Sequence[Card], max_size: int, feature_dim: int, config: EncoderConfig) -> Tuple[np.ndarray, np.ndarray]:
    data = np.zeros((max_size, feature_dim), dtype=np.float32)
    mask = np.zeros((max_size,), dtype=np.float32)
    for idx, card in enumerate(cards[:max_size]):
        data[idx] = encode_card(card, config=config)
        mask[idx] = 1.0
    return data, mask


def _hero_vector(name: str, config: EncoderConfig) -> np.ndarray:
    vec = np.zeros(len(config.hero_vocab), dtype=np.float32)
    key = name.strip().lower()
    idx = HERO_INDEX.get(key)
    if idx is None:
        idx = HERO_INDEX.get("generic hero")
    if idx is not None:
        vec[idx] = 1.0
    return vec


def _phase_vector(phase: Phase) -> np.ndarray:
    vec = np.zeros(len(PHASE_VOCAB), dtype=np.float32)
    vec[PHASE_INDEX[phase]] = 1.0
    return vec


def _combat_step_vector(step: CombatStep) -> np.ndarray:
    vec = np.zeros(len(COMBAT_STEP_VOCAB), dtype=np.float32)
    vec[COMBAT_STEP_INDEX[step]] = 1.0
    return vec


def encode_observation(
    state: GameState,
    *,
    acting_player: Optional[int] = None,
    config: EncoderConfig = EncoderConfig(),
) -> Dict[str, np.ndarray]:
    actor = acting_player if acting_player is not None else current_actor_index(state)
    opponent = 1 - actor
    players = (state.players[actor], state.players[opponent])
    feature_dim = _card_feature_dim(config)

    hand = np.zeros((2, config.max_hand_size, feature_dim), dtype=np.float32)
    hand_mask = np.zeros((2, config.max_hand_size), dtype=np.float32)
    arsenal = np.zeros((2, config.max_arsenal_size, feature_dim), dtype=np.float32)
    arsenal_mask = np.zeros((2, config.max_arsenal_size), dtype=np.float32)
    pitched = np.zeros((2, config.max_pitch_size, feature_dim), dtype=np.float32)
    pitched_mask = np.zeros((2, config.max_pitch_size), dtype=np.float32)
    grave = np.zeros((2, config.max_grave_size, feature_dim), dtype=np.float32)
    grave_mask = np.zeros((2, config.max_grave_size), dtype=np.float32)

    for idx, player in enumerate(players):
        hand[idx], hand_mask[idx] = _pad_zone(player.hand, config.max_hand_size, feature_dim, config)
        arsenal[idx], arsenal_mask[idx] = _pad_zone(player.arsenal, config.max_arsenal_size, feature_dim, config)
        pitched[idx], pitched_mask[idx] = _pad_zone(player.pitched, config.max_pitch_size, feature_dim, config)
        grave[idx], grave_mask[idx] = _pad_zone(player.grave, config.max_grave_size, feature_dim, config)

    life = np.array([float(player.life) for player in players], dtype=np.float32)
    deck_size = np.array([float(len(player.deck)) for player in players], dtype=np.float32)
    grave_size = np.array([float(len(player.grave)) for player in players], dtype=np.float32)
    floating = np.array(
        [
            float(state.floating_resources[actor]),
            float(state.floating_resources[opponent]),
        ],
        dtype=np.float32,
    )
    hero = np.stack([_hero_vector(player.hero, config) for player in players], axis=0)
    phase_vec = _phase_vector(state.phase)
    combat_vec = _combat_step_vector(state.combat_step)
    last_attack = encode_card(state.last_attack_card, config=config)

    observation: Dict[str, np.ndarray] = {
        "life": life,
        "deck_size": deck_size,
        "grave_size": grave_size,
        "floating_resources": floating,
        "hand": hand,
        "hand_mask": hand_mask,
        "arsenal": arsenal,
        "arsenal_mask": arsenal_mask,
        "pitched": pitched,
        "pitched_mask": pitched_mask,
        "grave": grave,
        "grave_mask": grave_mask,
        "hero": hero,
        "phase": phase_vec,
        "combat_step": combat_vec,
        "pending_attack": np.array([float(state.pending_attack)], dtype=np.float32),
        "pending_damage": np.array([float(state.pending_damage)], dtype=np.float32),
        "action_points": np.array([float(state.action_points)], dtype=np.float32),
        "last_pitch_sum": np.array([float(state.last_pitch_sum)], dtype=np.float32),
        "last_attack_had_go_again": np.array([1.0 if state.last_attack_had_go_again else 0.0], dtype=np.float32),
        "awaiting_defense": np.array([1.0 if state.awaiting_defense else 0.0], dtype=np.float32),
        "awaiting_arsenal": np.array([1.0 if state.awaiting_arsenal else 0.0], dtype=np.float32),
        "turn_player": np.array([1.0 if state.turn == actor else 0.0], dtype=np.float32),
        "last_attack_card": last_attack,
    }
    return observation


__all__ = ["EncoderConfig", "encode_card", "encode_observation", "CARD_KEYWORD_VOCAB"]
