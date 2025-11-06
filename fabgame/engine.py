from __future__ import annotations

import itertools
import random
from typing import Any, Dict, List, Optional, Set, Tuple

from .action_enumeration import ActionEnumerator
from .action_execution import ActionExecutor, _check_term, _end_and_pass_turn
from .game_initialization import new_game
from .config import DEFEND_MAX, INTELLECT, MAX_PITCH_ENUM
from .models import Action, ActType, Card, CombatStep, Game, GameState, Phase, PlayerState, Weapon
from .rules.abilities import apply_on_declare_attack_modifiers


# Game initialization functions have been moved to game_initialization.py


def current_actor_index(gs: GameState) -> int:
    if gs.awaiting_arsenal:
        return gs.arsenal_player if gs.arsenal_player is not None else gs.turn
    if gs.combat_step == CombatStep.LAYER and gs.combat_priority is not None:
        return gs.combat_priority
    if gs.combat_step == CombatStep.ATTACK and gs.awaiting_defense:
        return 1 - gs.turn
    if gs.combat_step == CombatStep.REACTION:
        if gs.reaction_actor is not None:
            return gs.reaction_actor
        return 1 - gs.turn
    if gs.combat_step in (CombatStep.DAMAGE, CombatStep.RESOLUTION) and gs.combat_priority is not None:
        return gs.combat_priority
    if gs.awaiting_defense and gs.phase == Phase.ACTION:
        return 1 - gs.turn
    return gs.turn


# ActionEnumerator and ActionExecutor have been moved to separate modules



def enumerate_legal_actions(gs: GameState) -> List[Action]:
    return ActionEnumerator(gs).enumerate()


def _apply_action_impl(state: GameState, act: Action) -> Tuple[GameState, bool, dict]:
    return ActionExecutor(state, act).execute()

def apply_action(gs: GameState, act: Action) -> Tuple[GameState, bool, dict]:
    state = gs.copy()
    original_ap = gs.action_points
    try:
        return _apply_action_impl(state, act)
    except ValueError as exc:
        action_label = act.typ.name if isinstance(act.typ, ActType) else str(act.typ)
        reverted = gs.copy()
        reverted.action_points = original_ap
        return reverted, _check_term(reverted), {
            "type": "illegal_action",
            "action": action_label,
            "reason": str(exc),
            "phase": gs.phase.name,
            "combat_step": gs.combat_step.name,
            "awaiting_defense": gs.awaiting_defense,
            "refunded_action_points": original_ap,
        }


# Helper functions moved to action_execution.py


__all__ = [
    "new_game",
    "current_actor_index",
    "enumerate_legal_actions",
    "apply_action",
]
