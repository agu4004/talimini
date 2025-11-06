"""Action execution module - applies actions to game state.

This module contains the ActionExecutor class which takes a game state and an action,
validates it, and returns a new game state with the action applied.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .config import DEFEND_MAX, INTELLECT
from .models import Action, ActType, CombatStep, GameState, Phase, PlayerState
from .rules.abilities import apply_on_declare_attack_modifiers


def _begin_arsenal_step(state: GameState) -> bool:
    """Begin the arsenal setting phase if conditions are met.

    Args:
        state: Current game state

    Returns:
        True if arsenal phase was started, False otherwise
    """
    player = state.players[state.turn]
    if state.awaiting_arsenal:
        return True
    if player.arsenal or not player.hand:
        return False
    state.awaiting_arsenal = True
    state.arsenal_player = state.turn
    state.phase = Phase.END
    state.floating_resources[state.turn] = 0
    return True


def _clear_arsenal_step(state: GameState) -> None:
    """Clear the arsenal phase and return to action phase.

    Args:
        state: Current game state
    """
    state.awaiting_arsenal = False
    state.arsenal_player = None
    state.phase = Phase.ACTION


def _consume_resources(state: GameState, player: PlayerState, pitch_indices: List[int], cost: int) -> int:
    """Consume resources by pitching cards and using floating resources.

    Args:
        state: Current game state
        player: Player consuming resources
        pitch_indices: Indices of cards to pitch from hand
        cost: Total cost to pay

    Returns:
        Total pitch value of cards pitched

    Raises:
        ValueError: If pitch indices are invalid or insufficient resources
    """
    float_pool = state.floating_resources[state.turn]
    spend_from_float = min(float_pool, cost)
    remaining_cost = cost - spend_from_float
    float_pool -= spend_from_float

    indices_sorted = sorted(pitch_indices, reverse=True)
    pitch_sum = 0
    for idx in indices_sorted:
        if not (0 <= idx < len(player.hand)):
            raise ValueError("Pitch index out of range")
        pitch_sum += player.hand[idx].pitch
    if remaining_cost > 0 and pitch_sum < remaining_cost:
        raise ValueError("Pitch insufficient for cost")

    for idx in indices_sorted:
        player.pitched.append(player.hand.pop(idx))

    leftover = pitch_sum - remaining_cost
    float_pool += leftover
    state.floating_resources[state.turn] = float_pool
    return pitch_sum


def _end_and_pass_turn(state: GameState) -> GameState:
    """End the current player's turn and pass to the opponent.

    Args:
        state: Current game state

    Returns:
        Updated game state with turn passed
    """
    current = state.turn
    turn_player = state.players[current]
    turn_player.bottom_pitched_to_deck()
    turn_player.draw_up_to(INTELLECT)
    turn_player.attacks_this_turn = 0
    if turn_player.weapon:
        turn_player.weapon.used_this_turn = False
    state.floating_resources[current] = 0
    state.awaiting_defense = False
    state.awaiting_arsenal = False
    state.arsenal_player = None
    state.pending_attack = 0
    state.last_attack_card = None
    state.last_pitch_sum = 0
    state.action_points = 0
    state.last_attack_had_go_again = False
    state.phase = Phase.SOT
    state.turn = 1 - current
    state.floating_resources[state.turn] = 0
    state.reaction_actor = None
    state.reaction_block = 0
    state.reaction_arsenal_cards = []
    state.combat_step = CombatStep.IDLE
    state.combat_priority = None
    state.combat_passes = 0
    return state


def _check_term(state: GameState) -> bool:
    """Check if the game has terminated (any player at 0 or less life).

    Args:
        state: Current game state

    Returns:
        True if game is terminated, False otherwise
    """
    return any(player.life <= 0 for player in state.players)


class ActionExecutor:
    """Applies a single action to the current game state while tracking events.

    This class validates an action against the current game state, applies it,
    and returns the resulting state along with event information for logging/display.

    Attributes:
        state: The current game state
        action: The action to execute
        turn_player: The player whose turn it is
        defending_player: The defending player
    """

    def __init__(self, state: GameState, action: Action) -> None:
        """Initialize the action executor.

        Args:
            state: Current game state
            action: Action to execute
        """
        self.state = state
        self.action = action
        self.turn_player = state.players[state.turn]
        self.defending_player = state.players[1 - state.turn]

    def execute(self) -> Tuple[GameState, bool, dict]:
        """Execute the action and return the resulting state.

        Returns:
            Tuple of (new_state, is_terminal, event_dict)

        Raises:
            ValueError: If the action is invalid for the current state
        """
        if self.state.awaiting_arsenal:
            return self._handle_awaiting_arsenal()
        if self.state.phase == Phase.SOT:
            return self._handle_start_of_turn()
        if self.state.combat_step == CombatStep.LAYER:
            return self._handle_layer_step()
        if self.state.phase == Phase.ACTION:
            return self._handle_action_phase()
        return self._result({})

    def _result(self, events: Dict[str, Any]) -> Tuple[GameState, bool, Dict[str, Any]]:
        """Helper to package results consistently.

        Args:
            events: Event dictionary describing what happened

        Returns:
            Tuple of (state, is_terminal, events)
        """
        return self.state, _check_term(self.state), events

    def _handle_awaiting_arsenal(self) -> Tuple[GameState, bool, dict]:
        """Handle action during arsenal setting phase.

        Returns:
            Result tuple with updated state

        Raises:
            ValueError: If action is invalid for arsenal phase
        """
        player_index = self.state.arsenal_player if self.state.arsenal_player is not None else self.state.turn
        arsenal_player = self.state.players[player_index]
        act = self.action

        if act.typ == ActType.SET_ARSENAL and act.play_idx is not None:
            if not (0 <= act.play_idx < len(arsenal_player.hand)):
                raise ValueError("Arsenal set index out of range")
            card = arsenal_player.hand.pop(act.play_idx)
            arsenal_player.arsenal.append(card)
            events = {"type": "set_arsenal", "player": player_index, "card": card.name}
            _clear_arsenal_step(self.state)
            self.state = _end_and_pass_turn(self.state)
            return self._result(events)

        if act.typ == ActType.PASS:
            events = {"type": "skip_arsenal", "player": player_index}
            _clear_arsenal_step(self.state)
            self.state = _end_and_pass_turn(self.state)
            return self._result(events)

        raise ValueError("Invalid action while awaiting arsenal")

    def _handle_start_of_turn(self) -> Tuple[GameState, bool, dict]:
        """Handle start of turn phase.

        Returns:
            Result tuple with updated state

        Raises:
            ValueError: If action is not CONTINUE
        """
        if self.action.typ != ActType.CONTINUE:
            raise ValueError("Only CONTINUE is valid in SOT")
        self.state.phase = Phase.ACTION
        self.state.action_points = 1
        return self._result({"type": "sot_to_action"})

    def _handle_layer_step(self) -> Tuple[GameState, bool, dict]:
        """Handle layer priority passing step.

        Returns:
            Result tuple with updated state

        Raises:
            ValueError: If action is not PASS
        """
        if self.action.typ != ActType.PASS:
            raise ValueError("Only PASS is allowed during the layer step")
        actor = self.state.combat_priority if self.state.combat_priority is not None else self.state.turn
        self.state.combat_passes += 1
        self.state.combat_priority = 1 - actor
        if self.state.combat_passes >= 2:
            self.state.combat_step = CombatStep.ATTACK
            self.state.combat_priority = None
            self.state.combat_passes = 0
            self.state.awaiting_defense = True
            events = {"type": "layer_end"}
        else:
            events = {"type": "layer_pass", "player": actor}
        return self._result(events)

    def _handle_action_phase(self) -> Tuple[GameState, bool, dict]:
        """Handle action phase - dispatch to specific handler.

        Returns:
            Result tuple from specific handler
        """
        if self.state.combat_step == CombatStep.REACTION:
            return self._handle_reaction_step()
        if self.state.awaiting_defense and self.state.combat_step == CombatStep.ATTACK:
            return self._handle_defense_step()
        return self._handle_attacker_step()

    def _handle_reaction_step(self) -> Tuple[GameState, bool, dict]:
        """Handle reaction window - dispatch to attacker or defender.

        Returns:
            Result tuple from specific reaction handler
        """
        actor = self.state.reaction_actor if self.state.reaction_actor is not None else 1 - self.state.turn
        if actor == 1 - self.state.turn:
            return self._handle_defender_reaction(actor)
        return self._handle_attacker_reaction(actor)

    def _handle_defender_reaction(self, actor: int) -> Tuple[GameState, bool, dict]:
        """Handle defender playing defense reactions.

        Args:
            actor: Player index of the defender

        Returns:
            Result tuple with updated state

        Raises:
            ValueError: If action or cards are invalid
        """
        act = self.action
        defending_player = self.defending_player

        if act.typ == ActType.PASS:
            self.state.combat_passes = 1
            self.state.reaction_actor = self.state.turn
            return self._result({"type": "reaction_pass", "player": actor})

        if act.typ != ActType.DEFEND:
            raise ValueError("Only DEFEND is valid for defense reactions")

        defend_indices = [i for i in range(len(defending_player.hand)) if (act.defend_mask >> i) & 1]
        if len(defend_indices) > DEFEND_MAX:
            raise ValueError(f"At most {DEFEND_MAX} cards to defend")

        for idx in defend_indices:
            card = defending_player.hand[idx]
            if not card.is_defense() or not card.is_reaction():
                raise ValueError("Only reaction defense cards may be used")

        if act.play_idx is not None:
            if not (0 <= act.play_idx < len(defending_player.arsenal)):
                raise ValueError("Arsenal index out of range")
            arsenal_card = defending_player.arsenal[act.play_idx]
            if not arsenal_card.is_defense():
                raise ValueError("Arsenal card cannot defend")
            if not arsenal_card.is_reaction():
                raise ValueError("Arsenal card must be a reaction")
        else:
            arsenal_card = None

        played_cards: List[str] = []
        added_block = 0
        for idx in sorted(defend_indices, reverse=True):
            defend_card = defending_player.hand.pop(idx)
            added_block += defend_card.defense
            played_cards.append(defend_card.name)
            defending_player.grave.append(defend_card)

        played_cards.reverse()

        if arsenal_card is not None:
            defending_player.arsenal.pop(act.play_idx)
            added_block += arsenal_card.defense
            played_cards.append(arsenal_card.name)
            defending_player.grave.append(arsenal_card)
            self.state.reaction_arsenal_cards.append(arsenal_card.name)

        self.state.reaction_block += added_block
        self.state.combat_passes = 0
        self.state.reaction_actor = self.state.turn

        events = {
            "type": "defense_react",
            "player": actor,
            "blocked": added_block,
            "cards": played_cards,
        }
        return self._result(events)

    def _handle_attacker_reaction(self, actor: int) -> Tuple[GameState, bool, dict]:
        """Handle attacker playing attack reactions.

        Args:
            actor: Player index of the attacker

        Returns:
            Result tuple with updated state

        Raises:
            ValueError: If action or cards are invalid
        """
        act = self.action
        if act.typ == ActType.PASS:
            return self._handle_attacker_reaction_pass(actor)
        if act.typ != ActType.PLAY_ATTACK_REACTION:
            raise ValueError("Only attack reactions or PASS allowed for attacker")
        if self.state.last_attack_card is None:
            raise ValueError("No attack card to target with attack reaction")

        pitch_indices = [i for i in range(len(self.turn_player.hand)) if (act.pitch_mask >> i) & 1]
        if act.play_idx is None:
            raise ValueError("Attack reaction card missing index")

        source = "hand"
        if act.play_idx >= 0:
            if not (0 <= act.play_idx < len(self.turn_player.hand)):
                raise ValueError("Attack reaction index out of range")
            reaction_idx = act.play_idx
            reaction_card = self.turn_player.hand[reaction_idx]
            if not reaction_card.is_attack_reaction():
                raise ValueError("Card is not an attack reaction")
            offset = sum(1 for i in pitch_indices if i < reaction_idx)
            pitch_sum = _consume_resources(self.state, self.turn_player, pitch_indices, reaction_card.cost)
            card = self.turn_player.hand.pop(reaction_idx - offset)
        else:
            arsenal_idx = -act.play_idx - 1
            if not (0 <= arsenal_idx < len(self.turn_player.arsenal)):
                raise ValueError("Attack reaction arsenal index out of range")
            reaction_card = self.turn_player.arsenal[arsenal_idx]
            if not reaction_card.is_attack_reaction():
                raise ValueError("Card is not an attack reaction")
            pitch_sum = _consume_resources(self.state, self.turn_player, pitch_indices, reaction_card.cost)
            card = self.turn_player.arsenal.pop(arsenal_idx)
            source = "arsenal"

        self.turn_player.grave.append(card)
        self.state.pending_attack += card.attack
        self.state.reaction_actor = 1 - self.state.turn
        self.state.combat_passes = 0

        events = {
            "type": "attack_react",
            "player": actor,
            "card": card.name,
            "bonus": card.attack,
            "source": source,
            "pitch_sum": pitch_sum,
        }
        return self._result(events)

    def _handle_attacker_reaction_pass(self, actor: int) -> Tuple[GameState, bool, dict]:
        """Handle attacker passing in reaction window.

        Args:
            actor: Player index of the attacker

        Returns:
            Result tuple - may resolve combat if both passed
        """
        if self.state.combat_passes == 1:
            return self._resolve_combat_chain()
        self.state.combat_passes = 0
        self.state.reaction_actor = 1 - self.state.turn
        return self._result({"type": "reaction_pass", "player": actor})

    def _resolve_combat_chain(self) -> Tuple[GameState, bool, dict]:
        """Resolve combat by applying damage and go-again.

        Returns:
            Result tuple with combat resolution event
        """
        blocked = self.state.reaction_block
        damage = max(0, self.state.pending_attack - blocked)
        self.state.pending_damage = damage
        self.state.combat_step = CombatStep.DAMAGE
        if damage > 0:
            self.defending_player.life -= damage
        self.state.combat_step = CombatStep.RESOLUTION

        go_again_triggered = False
        if self.state.last_attack_had_go_again:
            self.state.action_points += 1
            go_again_triggered = True
            self.state.last_attack_had_go_again = False

        arsenal_cards = None
        if self.state.reaction_arsenal_cards:
            arsenal_cards = ", ".join(self.state.reaction_arsenal_cards)

        event = {
            "type": "defense_resolve",
            "blocked": blocked,
            "damage": damage,
            "def_life_after": self.defending_player.life,
        }
        if arsenal_cards:
            event["arsenal_defense"] = arsenal_cards
        if go_again_triggered:
            event["go_again"] = True

        self._cleanup_after_resolution()
        return self._result(event)

    def _cleanup_after_resolution(self) -> None:
        """Clean up combat state after resolution."""
        self.state.pending_attack = 0
        self.state.pending_damage = 0
        self.state.reaction_block = 0
        self.state.combat_block_total = 0
        self.state.reaction_actor = None
        self.state.combat_passes = 0
        self.state.combat_priority = None
        self.state.combat_step = CombatStep.IDLE
        self.state.reaction_arsenal_cards = []
        self.state.awaiting_defense = False

    def _handle_defense_step(self) -> Tuple[GameState, bool, dict]:
        """Handle defender blocking with non-reaction defense cards.

        Returns:
            Result tuple with updated state

        Raises:
            ValueError: If action or cards are invalid
        """
        act = self.action
        defender_index = 1 - self.state.turn
        if act.typ == ActType.DEFEND:
            defend_indices = [i for i in range(len(self.defending_player.hand)) if (act.defend_mask >> i) & 1]
            if not defend_indices:
                raise ValueError("No cards selected to defend")
            if len(defend_indices) > DEFEND_MAX:
                raise ValueError(f"At most {DEFEND_MAX} cards to defend")
            block_cards: List[str] = []
            total_block = 0
            for idx in sorted(defend_indices, reverse=True):
                card = self.defending_player.hand[idx]
                if not card.is_defense() or card.is_reaction():
                    raise ValueError("Only non-reaction defense cards allowed during block step")
                total_block += card.defense
                block_cards.append(card.name)
                self.defending_player.grave.append(self.defending_player.hand.pop(idx))

            block_cards.reverse()
            self.state.reaction_block = total_block
            self.state.reaction_actor = 1 - self.state.turn
            self.state.awaiting_defense = False
            self.state.combat_step = CombatStep.REACTION
            self.state.combat_priority = None
            self.state.combat_passes = 0
            self.state.reaction_arsenal_cards = []
            self.state.combat_block_total = total_block
            self.state.pending_damage = 0

            events = {
                "type": "block_play",
                "player": defender_index,
                "blocked": total_block,
                "cards": block_cards,
            }
            return self._result(events)

        if act.typ == ActType.PASS:
            self.state.reaction_block = 0
            self.state.reaction_actor = 1 - self.state.turn
            self.state.awaiting_defense = False
            self.state.combat_step = CombatStep.REACTION
            self.state.combat_priority = None
            self.state.combat_passes = 0
            self.state.reaction_arsenal_cards = []
            self.state.combat_block_total = 0
            self.state.pending_damage = 0
            return self._result({"type": "block_pass", "player": defender_index})

        raise ValueError("Awaiting blockers")

    def _handle_attacker_step(self) -> Tuple[GameState, bool, dict]:
        """Handle attacker's main action phase.

        Returns:
            Result tuple with updated state

        Raises:
            ValueError: If action is invalid
        """
        act = self.action
        if act.typ == ActType.PASS:
            if _begin_arsenal_step(self.state):
                return self._result({"type": "end_phase_prompt"})
            self.state = _end_and_pass_turn(self.state)
            return self._result({"type": "pass_action"})
        if act.typ == ActType.WEAPON_ATTACK:
            return self._handle_weapon_attack()
        if act.typ == ActType.PLAY_ATTACK and act.play_idx is not None:
            return self._handle_play_attack()
        if act.typ == ActType.PLAY_ARSENAL_ATTACK and act.play_idx is not None:
            return self._handle_play_arsenal_attack()
        raise ValueError("Invalid action during attacker step")

    def _handle_weapon_attack(self) -> Tuple[GameState, bool, dict]:
        """Handle weapon attack action.

        Returns:
            Result tuple with attack declared event

        Raises:
            ValueError: If weapon attack is invalid
        """
        weapon = self.turn_player.weapon
        if weapon is None:
            raise ValueError("No weapon equipped")
        if weapon.once_per_turn and weapon.used_this_turn:
            raise ValueError("Weapon already used this turn")
        if self.state.action_points <= 0:
            raise ValueError("No action points remaining")
        pitch_indices = [i for i in range(len(self.turn_player.hand)) if (self.action.pitch_mask >> i) & 1]
        pitch_sum = _consume_resources(self.state, self.turn_player, pitch_indices, weapon.cost)
        weapon.used_this_turn = True
        self.state.action_points -= 1
        self.state.last_pitch_sum = pitch_sum
        mod_attack = apply_on_declare_attack_modifiers(
            self.state, weapon.base_attack, source_card=None, is_weapon=True
        )
        self.state.pending_attack = mod_attack
        self.state.last_attack_card = None
        self.state.last_attack_had_go_again = weapon.has_go_again()
        self._reset_combat_flow()
        events = {
            "type": "declare_attack",
            "card": weapon.name,
            "attack": mod_attack,
            "cost": weapon.cost,
            "pitch_sum": pitch_sum,
            "source": "weapon",
        }
        self.turn_player.attacks_this_turn += 1
        return self._result(events)

    def _handle_play_attack(self) -> Tuple[GameState, bool, dict]:
        """Handle attack from hand.

        Returns:
            Result tuple with attack declared event

        Raises:
            ValueError: If attack is invalid
        """
        act = self.action
        if not (0 <= act.play_idx < len(self.turn_player.hand)):
            raise ValueError("play_idx out of range")
        attack_card = self.turn_player.hand[act.play_idx]
        if not attack_card.is_attack():
            raise ValueError("Selected card is not an attack")
        if self.state.action_points <= 0:
            raise ValueError("No action points remaining")
        pitch_indices = [i for i in range(len(self.turn_player.hand)) if (act.pitch_mask >> i) & 1]
        offset = sum(1 for i in pitch_indices if i < act.play_idx)
        pitch_sum = _consume_resources(self.state, self.turn_player, pitch_indices, attack_card.cost)
        adjusted_idx = act.play_idx - offset
        if not (0 <= adjusted_idx < len(self.turn_player.hand)):
            raise ValueError("Adjusted play_idx out of range after resource consumption")
        card = self.turn_player.hand.pop(adjusted_idx)
        self.turn_player.grave.append(card)
        self.state.action_points -= 1
        self.state.last_pitch_sum = pitch_sum
        mod_attack = apply_on_declare_attack_modifiers(
            self.state, card.attack, source_card=card, is_weapon=False
        )
        self.state.pending_attack = mod_attack
        self.state.last_attack_card = card
        self.state.last_attack_had_go_again = card.has_keyword("go_again")
        self._reset_combat_flow()
        events = {
            "type": "declare_attack",
            "card": card.name,
            "attack": mod_attack,
            "cost": attack_card.cost,
            "pitch_sum": pitch_sum,
            "source": "hand",
        }
        self.turn_player.attacks_this_turn += 1
        return self._result(events)

    def _handle_play_arsenal_attack(self) -> Tuple[GameState, bool, dict]:
        """Handle attack from arsenal.

        Returns:
            Result tuple with attack declared event

        Raises:
            ValueError: If attack is invalid
        """
        act = self.action
        if not (0 <= act.play_idx < len(self.turn_player.arsenal)):
            raise ValueError("Arsenal index out of range")
        attack_card = self.turn_player.arsenal[act.play_idx]
        if not attack_card.is_attack():
            raise ValueError("Arsenal card is not an attack")
        if self.state.action_points <= 0:
            raise ValueError("No action points remaining")
        pitch_indices = [i for i in range(len(self.turn_player.hand)) if (act.pitch_mask >> i) & 1]
        pitch_sum = _consume_resources(self.state, self.turn_player, pitch_indices, attack_card.cost)
        card = self.turn_player.arsenal.pop(act.play_idx)
        self.turn_player.grave.append(card)
        self.state.action_points -= 1
        self.state.last_pitch_sum = pitch_sum
        mod_attack = apply_on_declare_attack_modifiers(
            self.state, card.attack, source_card=card, is_weapon=False
        )
        self.state.pending_attack = mod_attack
        self.state.last_attack_card = card
        self.state.last_attack_had_go_again = card.has_keyword("go_again")
        self._reset_combat_flow()
        events = {
            "type": "declare_attack",
            "card": card.name,
            "attack": mod_attack,
            "cost": attack_card.cost,
            "pitch_sum": pitch_sum,
            "source": "arsenal",
        }
        self.turn_player.attacks_this_turn += 1
        return self._result(events)

    def _reset_combat_flow(self) -> None:
        """Reset combat state to start of layer phase."""
        self.state.awaiting_defense = False
        self.state.combat_step = CombatStep.LAYER
        self.state.combat_priority = self.state.turn
        self.state.combat_passes = 0
        self.state.reaction_actor = 1 - self.state.turn
        self.state.reaction_block = 0
        self.state.reaction_arsenal_cards = []
        self.state.combat_block_total = 0
        self.state.pending_damage = 0
