from __future__ import annotations

import random
from typing import Iterable, List, Optional

from .config import DEFEND_MAX, BOT_WEAPON_TYPE_BIAS, BOT_HIGH_PRIORITY_SCORE
from .engine import current_actor_index, enumerate_legal_actions
from .models import Action, ActType, Card, CombatStep, GameState, Phase, PlayerState
from .pretty import _b, _dim


def _render_cards(cards: Iterable[Card]) -> str:
    lines = []
    for index, card in enumerate(cards):
        tags = []
        if card.is_attack():
            tags.append(f"ATK:{card.attack}/C{card.cost}")
        if card.is_defense():
            tags.append(f"DEF:{card.defense}")
        tags.append(f"P{card.pitch}")
        lines.append(f"  [{index}] {card.name} ({', '.join(tags)})")
    return "\n".join(lines) if lines else "  (empty)"


def render_hand(player: PlayerState) -> str:
    return _render_cards(player.hand)


def render_arsenal(player: PlayerState) -> str:
    return _render_cards(player.arsenal)



def parse_indices(prompt: str, max_index: int) -> List[int]:
    selection = input(prompt).strip()
    if not selection:
        return []
    selection = selection.replace(",", " ")
    parsed: List[int] = []
    for token in selection.split():
        if token.isdigit():
            idx = int(token)
            if 0 <= idx <= max_index:
                parsed.append(idx)
    seen = set()
    unique_indices: List[int] = []
    for idx in parsed:
        if idx not in seen:
            seen.add(idx)
            unique_indices.append(idx)
    return unique_indices


def _mask_from_indices(indices: Iterable[int]) -> int:
    mask = 0
    for idx in indices:
        mask |= 1 << idx
    return mask


def _prompt_pitch_sequence(
    player: PlayerState,
    *,
    required: int,
    forbidden: Optional[Iterable[int]] = None,
) -> Optional[List[int]]:
    if required <= 0:
        return []
    forbidden_set = set(forbidden or [])
    available = [i for i in range(len(player.hand)) if i not in forbidden_set]
    if not available:
        print("  No cards available to pitch.")
        return None
    total_pitch = sum(player.hand[i].pitch for i in available)
    if total_pitch < required:
        print("  Not enough pitch available to pay the cost -> PASS.")
        return None
    remaining = required
    chosen: List[int] = []
    available_set = set(available)
    while remaining > 0:
        choice = input(f"  Pitch index (need {remaining} more): ").strip()
        if not choice:
            return None
        if not choice.isdigit():
            print("  Invalid input.")
            continue
        idx = int(choice)
        if idx not in available_set or idx in chosen:
            print("  Invalid index.")
            continue
        card = player.hand[idx]
        chosen.append(idx)
        available_set.remove(idx)
        remaining -= card.pitch
        if remaining > 0:
            print(f"  -> Pitched {card.name} (P{card.pitch}). Need {remaining} more.")
            if not available_set:
                print("  No more cards to pitch -> cannot pay the cost.")
                return None
            remaining_pitch = sum(player.hand[i].pitch for i in available_set)
            if remaining_pitch < remaining:
                print("  Remaining pitch insufficient to cover cost -> PASS.")
                return None
    return chosen


class HumanActionPrompter:
    def __init__(self, state: GameState) -> None:
        self.state = state
        self.actor = current_actor_index(state)
        self.player = state.players[self.actor]

    def prompt(self) -> Action:
        self._print_banner()
        if self.state.phase == Phase.SOT:
            return self._handle_start_of_turn()
        if self.state.awaiting_arsenal:
            return self._handle_arsenal_step()
        if self._is_block_window():
            return self._handle_block_window()
        if self._is_layer_step():
            return self._handle_layer_step()
        if self._is_idle_attacker_window():
            return self._handle_attacker_window()
        if self._is_reaction_step():
            return self._handle_reaction_window()
        return Action(ActType.PASS)

    def _print_banner(self) -> None:
        print(_dim("-" * 56))
        phase_label = {"sot": "SOT", "action": "ACTION", "end": "END"}.get(
            self.state.phase.value, self.state.phase.value.upper()
        )
        await_tag = " [awaiting DEF]" if self.state.awaiting_defense else ""
        step_tag = ""
        if self.state.combat_step != CombatStep.IDLE:
            step_tag = f" | Step: {self.state.combat_step.name.capitalize()}"
        print(
            f"{_b('Your move')}  | Actor: P{self.actor} | Turn: P{self.state.turn} | Phase: {phase_label}{await_tag}{step_tag}"
        )
        print(f"Life  P0: {self.state.players[0].life}   P1: {self.state.players[1].life}")
        print(_dim("-" * 56))

    def _handle_start_of_turn(self) -> Action:
        input("SOT -> press Enter to move into ACTION... ")
        return Action(ActType.CONTINUE)

    def _handle_arsenal_step(self) -> Action:
        player_index = self.state.arsenal_player if self.state.arsenal_player is not None else self.state.turn
        player = self.state.players[player_index]
        print("== END PHASE: Arsenal ==")
        print("Hand:")
        print(render_hand(player))
        print("Arsenal (current):")
        print(render_arsenal(player))
        if not player.hand:
            print("No cards available to set. Skipping.")
            return Action(ActType.PASS)
        choice = input("Select card index to set (blank to skip): ").strip()
        if not choice or not choice.isdigit():
            return Action(ActType.PASS)
        play_idx = int(choice)
        if not (0 <= play_idx < len(player.hand)):
            return Action(ActType.PASS)
        return Action(ActType.SET_ARSENAL, play_idx=play_idx)

    def _is_block_window(self) -> bool:
        return (
            self.state.phase == Phase.ACTION
            and self.state.combat_step == CombatStep.ATTACK
            and self.state.awaiting_defense
        )

    def _handle_block_window(self) -> Action:
        attacker_index = self.state.turn
        defender = self.player
        print(f"== BLOCK STEP (you are P{self.actor}) ==")
        if self.state.last_attack_card is not None:
            card = self.state.last_attack_card
            print(f"  Attack card : {card.name}")
            print(f"  Attack value: {self.state.pending_attack} | Cost: {card.cost}")
        else:
            weapon = self.state.players[attacker_index].weapon
            weapon_name = weapon.name if weapon else "Weapon"
            print(f"  Weapon attack: {weapon_name}")
            print(f"  Attack value : {self.state.pending_attack}")
        print(render_hand(defender))
        print(f"Choose up to {DEFEND_MAX} non-reaction cards to block (blank = pass).")
        idxs = parse_indices("  Block indices: ", len(defender.hand) - 1)
        if not idxs:
            return Action(ActType.PASS)
        idxs = [
            i
            for i in idxs
            if 0 <= i < len(defender.hand) and defender.hand[i].is_defense() and not defender.hand[i].is_reaction()
        ]
        if not idxs:
            return Action(ActType.PASS)
        if len(idxs) > DEFEND_MAX:
            idxs = idxs[:DEFEND_MAX]
        return Action(ActType.DEFEND, defend_mask=_mask_from_indices(idxs))

    def _is_layer_step(self) -> bool:
        return self.state.phase == Phase.ACTION and self.state.combat_step == CombatStep.LAYER

    def _handle_layer_step(self) -> Action:
        print("== LAYER STEP ==")
        input("Both players must pass priority to continue. Press Enter to pass... ")
        return Action(ActType.PASS)

    def _is_idle_attacker_window(self) -> bool:
        return (
            self.state.phase == Phase.ACTION
            and self.state.combat_step == CombatStep.IDLE
            and not self.state.awaiting_defense
        )

    def _handle_attacker_window(self) -> Action:
        player = self.player
        float_available = self.state.floating_resources[self.actor]
        print(f"Action points remaining: {self.state.action_points}")
        print(f"Floating resources: {float_available}")
        print("== YOUR HAND (attacker) ==")
        print(render_hand(player))
        if player.arsenal:
            print("== YOUR ARSENAL ==")
            print(render_arsenal(player))
        if self.state.action_points <= 0:
            input("No action points remaining. Press Enter to pass... ")
            return Action(ActType.PASS)
        weapon = player.weapon
        weapon_ready = bool(weapon and (not weapon.once_per_turn or not weapon.used_this_turn))
        if weapon:
            status = "ready" if weapon_ready else "used"
            print(f"Weapon: {weapon.name} | ATK:{weapon.base_attack} | Cost:{weapon.cost} | {status}")
        options = "[H]and attack"
        if player.arsenal:
            options += " / [R]arsenal"
        if weapon:
            options += " / [W]eapon"
        options += " / [P]ass"
        choice = input(f"Choose: {options} ? ").strip().lower()
        if choice.startswith("p"):
            return Action(ActType.PASS)
        if choice.startswith("w"):
            if not weapon_ready or weapon is None:
                print("  Weapon not available -> PASS.")
                return Action(ActType.PASS)
            if weapon.cost == 0:
                print("  Weapon cost=0 -> no pitch needed.")
                return Action(ActType.WEAPON_ATTACK, play_idx=None, pitch_mask=0)
            required = max(0, weapon.cost - float_available)
            if required == 0:
                print("  Floating covers the weapon cost. Pitching for extra resources is not allowed.")
                return Action(ActType.WEAPON_ATTACK, play_idx=None, pitch_mask=0)
            print("== SELECT PITCH FOR WEAPON ==")
            print(f"  Need at least {required} pitch (after using {float_available} floating).")
            chosen = _prompt_pitch_sequence(player, required=required)
            if chosen is None:
                return Action(ActType.PASS)
            return Action(ActType.WEAPON_ATTACK, play_idx=None, pitch_mask=_mask_from_indices(chosen))
        if choice.startswith("r") and player.arsenal:
            arsenal_idx_s = input("  Arsenal index to attack with: ").strip()
            if not arsenal_idx_s.isdigit():
                return Action(ActType.PASS)
            arsenal_idx = int(arsenal_idx_s)
            if not (0 <= arsenal_idx < len(player.arsenal)) or not player.arsenal[arsenal_idx].is_attack():
                return Action(ActType.PASS)
            cost = player.arsenal[arsenal_idx].cost
            if cost == 0:
                print("  Cost=0 -> no pitch needed.")
                return Action(ActType.PLAY_ARSENAL_ATTACK, play_idx=arsenal_idx, pitch_mask=0)
            required = max(0, cost - float_available)
            if required == 0:
                print("  Floating covers the cost. Pitching for extra resources is not allowed.")
                return Action(ActType.PLAY_ARSENAL_ATTACK, play_idx=arsenal_idx, pitch_mask=0)
            print("== SELECT PITCH ==")
            print(f"  Need at least {required} pitch (after using {float_available} floating).")
            chosen = _prompt_pitch_sequence(player, required=required)
            if chosen is None:
                return Action(ActType.PASS)
            return Action(ActType.PLAY_ARSENAL_ATTACK, play_idx=arsenal_idx, pitch_mask=_mask_from_indices(chosen))
        play_idx_s = input("  Hand index to attack with: ").strip()
        if not play_idx_s.isdigit():
            return Action(ActType.PASS)
        play_idx = int(play_idx_s)
        if not (0 <= play_idx < len(player.hand)) or not player.hand[play_idx].is_attack():
            return Action(ActType.PASS)
        cost = player.hand[play_idx].cost
        if cost == 0:
            print("  Cost=0 -> no pitch needed.")
            return Action(ActType.PLAY_ATTACK, play_idx=play_idx, pitch_mask=0)
        required = max(0, cost - float_available)
        if required == 0:
            print("  Floating covers the cost. Pitching for extra resources is not allowed.")
            return Action(ActType.PLAY_ATTACK, play_idx=play_idx, pitch_mask=0)
        print("== SELECT PITCH ==")
        print(f"  Need at least {required} pitch (after using {float_available} floating).")
        chosen = _prompt_pitch_sequence(player, required=required, forbidden=[play_idx])
        if chosen is None:
            return Action(ActType.PASS)
        return Action(ActType.PLAY_ATTACK, play_idx=play_idx, pitch_mask=_mask_from_indices(chosen))

    def _is_reaction_step(self) -> bool:
        return self.state.phase == Phase.ACTION and self.state.combat_step == CombatStep.REACTION

    def _handle_reaction_window(self) -> Action:
        attacker_index = self.state.turn
        print(f"== REACTION WINDOW (you are P{self.actor}) ==")
        if self.state.last_attack_card is not None:
            card = self.state.last_attack_card
            print(f"  Attack card : {card.name}")
            print(f"  Attack value: {self.state.pending_attack} (base {card.attack})")
        else:
            weapon = self.state.players[attacker_index].weapon
            weapon_name = weapon.name if weapon else "Weapon"
            weapon_cost = weapon.cost if weapon else 0
            print(f"  Weapon attack: {weapon_name} (Cost {weapon_cost})")
            print(f"  Attack value : {self.state.pending_attack}")
        print(f"  Current block total: {self.state.reaction_block}")

        if self.actor == 1 - attacker_index:
            return self._handle_defender_reaction()
        return self._handle_attacker_reaction()

    def _handle_defender_reaction(self) -> Action:
        player = self.player
        print(render_hand(player))
        print("Only reaction cards may be selected.")
        print(f"Choose up to {DEFEND_MAX} cards to block (blank = no block).")
        raw_idxs = parse_indices("  Defense reaction indices: ", len(player.hand) - 1)
        idxs = [
            i
            for i in raw_idxs
            if 0 <= i < len(player.hand) and player.hand[i].is_defense() and player.hand[i].is_reaction()
        ]
        if len(idxs) > DEFEND_MAX:
            idxs = idxs[:DEFEND_MAX]
        arsenal_reactions = [
            (i, card) for i, card in enumerate(player.arsenal) if card.is_defense() and card.is_reaction()
        ]
        arsenal_choice: Optional[int] = None
        if arsenal_reactions:
            print("Arsenal defense reactions:")
            for i, card in arsenal_reactions:
                print(f"  [{i}] {card.name} (DEF:{card.defense})")
            choice = input("  Arsenal defense reaction index (blank = none): ").strip()
            if choice.isdigit():
                idx = int(choice)
                valid = {value for value, _ in arsenal_reactions}
                if idx in valid:
                    arsenal_choice = idx
        if not idxs and arsenal_choice is None:
            return Action(ActType.PASS)
        return Action(ActType.DEFEND, play_idx=arsenal_choice, defend_mask=_mask_from_indices(idxs))

    def _handle_attacker_reaction(self) -> Action:
        if self.state.last_attack_card is None:
            print("Attack reactions require a card attack. Passing.")
            return Action(ActType.PASS)

        player = self.player
        float_available = self.state.floating_resources[self.actor]
        print(f"Floating resources available: {float_available}")
        print("== YOUR HAND ==")
        print(render_hand(player))
        if player.arsenal:
            print("== YOUR ARSENAL ==")
            print(render_arsenal(player))

        hand_reacts = [i for i, card in enumerate(player.hand) if card.is_attack_reaction()]
        arsenal_reacts = [i for i, card in enumerate(player.arsenal) if card.is_attack_reaction()]

        options = "[P]ass"
        if hand_reacts:
            options += " / [H]and reaction"
        if arsenal_reacts:
            options += " / [R]snal reaction"
        choice = input(f"Choose: {options}: ").strip().lower()
        if not choice or choice.startswith("p"):
            return Action(ActType.PASS)
        if choice.startswith("h") and hand_reacts:
            idx_s = input("  Hand index: ").strip()
            if not idx_s.isdigit():
                return Action(ActType.PASS)
            play_idx = int(idx_s)
            if play_idx not in hand_reacts:
                return Action(ActType.PASS)
            card = player.hand[play_idx]
            cost = card.cost
            if cost == 0 and float_available >= 0:
                print("  Cost=0 -> no pitch needed.")
                return Action(ActType.PLAY_ATTACK_REACTION, play_idx=play_idx, pitch_mask=0)
            required = max(0, cost - float_available)
            if required <= 0:
                print("  Floating covers the cost.")
                return Action(ActType.PLAY_ATTACK_REACTION, play_idx=play_idx, pitch_mask=0)
            print("== SELECT PITCH FOR ATTACK REACTION ==")
            chosen = _prompt_pitch_sequence(player, required=required, forbidden=[play_idx])
            if chosen is None:
                return Action(ActType.PASS)
            return Action(ActType.PLAY_ATTACK_REACTION, play_idx=play_idx, pitch_mask=_mask_from_indices(chosen))
        if choice.startswith("r") and arsenal_reacts:
            idx_s = input("  Arsenal index: ").strip()
            if not idx_s.isdigit():
                return Action(ActType.PASS)
            arsenal_idx = int(idx_s)
            if arsenal_idx not in arsenal_reacts:
                return Action(ActType.PASS)
            card = player.arsenal[arsenal_idx]
            cost = card.cost
            if cost == 0 and float_available >= 0:
                print("  Cost=0 -> no pitch needed.")
                return Action(ActType.PLAY_ATTACK_REACTION, play_idx=-(arsenal_idx + 1), pitch_mask=0)
            required = max(0, cost - float_available)
            if required <= 0:
                print("  Floating covers the cost.")
                return Action(ActType.PLAY_ATTACK_REACTION, play_idx=-(arsenal_idx + 1), pitch_mask=0)
            print("== SELECT PITCH FOR ATTACK REACTION ==")
            chosen = _prompt_pitch_sequence(player, required=required)
            if chosen is None:
                return Action(ActType.PASS)
            return Action(ActType.PLAY_ATTACK_REACTION, play_idx=-(arsenal_idx + 1), pitch_mask=_mask_from_indices(chosen))
        return Action(ActType.PASS)


def current_human_action(gs: GameState) -> Action:
    return HumanActionPrompter(gs).prompt()


def bot_choose_action(gs: GameState, rng: random.Random) -> Action:
    actions = enumerate_legal_actions(gs)

    def pick_pass() -> Action:
        for act in actions:
            if act.typ == ActType.PASS:
                return act
        return actions[0] if actions else Action(ActType.PASS)

    if gs.awaiting_arsenal:
        player_index = gs.arsenal_player if gs.arsenal_player is not None else gs.turn
        arsenal_player = gs.players[player_index]
        set_actions = [a for a in actions if a.typ == ActType.SET_ARSENAL and a.play_idx is not None]
        if set_actions:
            best = max(set_actions, key=lambda a: arsenal_player.hand[a.play_idx].attack)
            return best
        return pick_pass()

    if gs.phase == Phase.SOT:
        return actions[0] if actions else Action(ActType.PASS)

    if gs.phase == Phase.ACTION and gs.combat_step == CombatStep.ATTACK and gs.awaiting_defense:
        actor = current_actor_index(gs)
        defender = gs.players[actor]
        block_actions = [a for a in actions if a.typ == ActType.DEFEND]
        if not block_actions:
            return pick_pass()
        need = gs.pending_attack

        def block_total(action: Action) -> int:
            total = 0
            for i in range(len(defender.hand)):
                if (action.defend_mask >> i) & 1:
                    total += defender.hand[i].defense
            return total

        best: Optional[Action] = None
        best_over = float("inf")
        for action in block_actions:
            total = block_total(action)
            if total >= need:
                over = total - need
                if over < best_over:
                    best_over = over
                    best = action
        if best is not None:
            return best
        return max(block_actions, key=block_total)

    if gs.phase == Phase.ACTION and gs.combat_step in (CombatStep.IDLE, CombatStep.LAYER) and not gs.awaiting_defense:
        turn_player = gs.players[gs.turn]
        hand = turn_player.hand
        weapon = turn_player.weapon
        arsenal = turn_player.arsenal
        attack_candidates = [
            a for a in actions if a.typ in (ActType.PLAY_ATTACK, ActType.PLAY_ARSENAL_ATTACK, ActType.WEAPON_ATTACK)
        ]
        if attack_candidates:
            def score(action: Action):
                pitch_sum = sum(hand[i].pitch for i in range(len(hand)) if (action.pitch_mask >> i) & 1)
                if action.typ == ActType.PLAY_ATTACK and action.play_idx is not None:
                    card = hand[action.play_idx]
                    cost = card.cost
                    attack = card.attack
                    type_bias = 0
                elif action.typ == ActType.PLAY_ARSENAL_ATTACK and action.play_idx is not None:
                    card = arsenal[action.play_idx]
                    cost = card.cost
                    attack = card.attack
                    type_bias = 1
                else:
                    if weapon is None:
                        return (BOT_HIGH_PRIORITY_SCORE, BOT_HIGH_PRIORITY_SCORE, 0, 3)
                    cost = weapon.cost
                    attack = weapon.base_attack
                    type_bias = BOT_WEAPON_TYPE_BIAS
                overpitch = pitch_sum - cost
                return (cost, overpitch, -attack, type_bias)

            attack_candidates.sort(key=score)
            return attack_candidates[0]
        return pick_pass()

    if gs.phase == Phase.ACTION and gs.combat_step == CombatStep.REACTION:
        actor = current_actor_index(gs)
        if actor == gs.turn:
            attack_player = gs.players[gs.turn]
            hand = attack_player.hand
            arsenal = attack_player.arsenal
            attack_reacts = [a for a in actions if a.typ == ActType.PLAY_ATTACK_REACTION]
            if attack_reacts:
                def score(action: Action):
                    if action.play_idx is None:
                        return (1, 0, 0)
                    if action.play_idx >= 0:
                        card = hand[action.play_idx]
                    else:
                        card = arsenal[-action.play_idx - 1]
                    pitch_sum = sum(hand[i].pitch for i in range(len(hand)) if (action.pitch_mask >> i) & 1)
                    overpitch = pitch_sum - card.cost
                    return (-card.attack, overpitch, card.cost)

                attack_reacts.sort(key=score)
                return attack_reacts[0]
            return pick_pass()

        defend_actions = [a for a in actions if a.typ == ActType.DEFEND]
        if not defend_actions:
            return pick_pass()

        opponent = gs.players[1 - gs.turn]
        need = gs.pending_attack

        def block_total(action: Action) -> int:
            total = 0
            for i in range(len(opponent.hand)):
                if (action.defend_mask >> i) & 1:
                    total += opponent.hand[i].defense
            if action.play_idx is not None and 0 <= action.play_idx < len(opponent.arsenal):
                total += opponent.arsenal[action.play_idx].defense
            return total

        best_full: Optional[Action] = None
        best_over = float("inf")
        for action in defend_actions:
            block = block_total(action)
            if block >= need:
                over = block - need
                if over < best_over:
                    best_over = over
                    best_full = action
        if best_full is not None:
            return best_full
        return max(defend_actions, key=block_total)

    return pick_pass()


__all__ = [
    "render_hand",
    "current_human_action",
    "bot_choose_action",
    "HumanActionPrompter",
]
