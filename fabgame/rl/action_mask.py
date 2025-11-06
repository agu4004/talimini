from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

try:  # pragma: no cover - dependency guard
    import numpy as np
except ImportError as exc:  # pragma: no cover - provide actionable message
    raise RuntimeError("fabgame.rl.action_mask requires numpy to be installed") from exc

from ..config import DEFEND_MAX, INTELLECT
from ..models import Action, ActType

_SENTINEL_PLAY_IDX = -9999


def _bit_mask_from_indices(indices: Iterable[int]) -> int:
    mask = 0
    for idx in indices:
        mask |= 1 << idx
    return mask


def _generate_pitch_masks(max_size: int) -> List[int]:
    masks = [0]
    for r in range(1, max_size + 1):
        for combo in itertools.combinations(range(max_size), r):
            masks.append(_bit_mask_from_indices(combo))
    return masks


def _generate_defend_masks(max_size: int, max_cards: int) -> List[int]:
    masks = [0]
    for r in range(1, min(max_cards, max_size) + 1):
        for combo in itertools.combinations(range(max_size), r):
            masks.append(_bit_mask_from_indices(combo))
    return masks


def _normalize_key(action: Action) -> Tuple[int, int, int, int]:
    play_idx = action.play_idx if action.play_idx is not None else _SENTINEL_PLAY_IDX
    return (int(action.typ), int(play_idx), int(action.pitch_mask or 0), int(action.defend_mask or 0))


@dataclass
class ActionVocabulary:
    """Deterministic mapping between engine actions and policy indices."""

    max_hand_size: int = INTELLECT
    max_arsenal_size: int = 1

    def __post_init__(self) -> None:
        self._index: Dict[Tuple[int, int, int, int], int] = {}
        self._actions: List[Action] = []
        self._build()

    def _add(self, action: Action) -> None:
        key = _normalize_key(action)
        if key in self._index:
            return
        self._index[key] = len(self._actions)
        self._actions.append(action)

    def _build(self) -> None:
        max_hand = self.max_hand_size
        max_arsenal = self.max_arsenal_size
        pitch_masks = _generate_pitch_masks(max_hand)
        defend_masks = _generate_defend_masks(max_hand, DEFEND_MAX)

        self._add(Action(ActType.CONTINUE))
        self._add(Action(ActType.PASS))

        for idx in range(max_hand):
            self._add(Action(ActType.SET_ARSENAL, play_idx=idx))

        for idx in range(max_hand):
            for mask in pitch_masks:
                if mask & (1 << idx):
                    continue
                self._add(Action(ActType.PLAY_ATTACK, play_idx=idx, pitch_mask=mask))

        for idx in range(max_arsenal):
            for mask in pitch_masks:
                self._add(Action(ActType.PLAY_ARSENAL_ATTACK, play_idx=idx, pitch_mask=mask))

        for mask in pitch_masks:
            self._add(Action(ActType.WEAPON_ATTACK, play_idx=None, pitch_mask=mask))

        for arsenal_idx in range(-max_arsenal, 0):
            for mask in pitch_masks:
                self._add(Action(ActType.PLAY_ATTACK_REACTION, play_idx=arsenal_idx, pitch_mask=mask))
        for idx in range(max_hand):
            for mask in pitch_masks:
                if mask & (1 << idx):
                    continue
                self._add(Action(ActType.PLAY_ATTACK_REACTION, play_idx=idx, pitch_mask=mask))

        for arsenal_idx in range(max_arsenal):
            for mask in defend_masks:
                self._add(Action(ActType.DEFEND, play_idx=arsenal_idx, defend_mask=mask))
        for mask in defend_masks:
            self._add(Action(ActType.DEFEND, defend_mask=mask))

    def __len__(self) -> int:
        return len(self._actions)

    @property
    def actions(self) -> List[Action]:
        return list(self._actions)

    def action_for_index(self, index: int) -> Action:
        return self._actions[index]

    def index_for(self, action: Action) -> int:
        key = _normalize_key(action)
        if key not in self._index:
            raise KeyError(
                f"Action {action} outside configured vocabulary (max_hand={self.max_hand_size}, max_arsenal={self.max_arsenal_size})"
            )
        return self._index[key]


ACTION_VOCAB = ActionVocabulary(max_hand_size=10, max_arsenal_size=4)


def legal_action_mask(actions: Iterable[Action], vocab: ActionVocabulary = ACTION_VOCAB) -> np.ndarray:
    mask = np.zeros(len(vocab), dtype=np.bool_)
    for action in actions:
        idx = vocab.index_for(action)
        mask[idx] = True
    return mask


def mask_for_state(state, vocab: ActionVocabulary = ACTION_VOCAB) -> np.ndarray:
    from ..engine import enumerate_legal_actions

    return legal_action_mask(enumerate_legal_actions(state), vocab=vocab)


__all__ = ["ActionVocabulary", "ACTION_VOCAB", "legal_action_mask", "mask_for_state"]
