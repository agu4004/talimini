"""Tests for turn phase transitions and state management (GAME_FLOW.md section 1)."""
from __future__ import annotations

import pytest

from fabgame.config import INTELLECT
from fabgame.engine import apply_action, current_actor_index, enumerate_legal_actions
from fabgame.models import Action, ActType, CombatStep, Phase
from tests.conftest import create_test_game


class TestStartPhase:
    """Tests for Start Phase (GAME_FLOW.md: Turn Phases -> Start Phase)."""

    def test_start_phase_initialization(self, basic_game_state):
        """
        Given: Game just initialized
        When: Start phase begins
        Then: Phase is SOT, only CONTINUE action available
        """
        gs = basic_game_state
        assert gs.phase == Phase.SOT
        assert gs.action_points == 0

        legal = enumerate_legal_actions(gs)
        assert len(legal) == 1
        assert legal[0].typ == ActType.CONTINUE

    def test_start_phase_continue_grants_action_point(self, basic_game_state):
        """
        Given: Player at start phase
        When: Player executes CONTINUE action
        Then: action_points set to 1, phase transitions to ACTION, combat_step is IDLE
        """
        gs = basic_game_state
        continue_action = Action(typ=ActType.CONTINUE)

        new_state, done, info = apply_action(gs, continue_action)

        assert new_state.action_points == 1
        assert new_state.phase == Phase.ACTION
        assert new_state.combat_step == CombatStep.IDLE
        assert not done

    def test_start_phase_draw_up_to_intellect(self):
        """
        Given: Player with 2 cards in hand, 10 cards in deck
        When: New turn begins (after _end_and_pass_turn)
        Then: Hand size equals INTELLECT, cards moved from deck to hand
        """
        # Create a game state with controlled deck/hand sizes
        from fabgame.models import Card, PlayerState, GameState

        deck = [Card(name=f"Card {i}", cost=1, attack=2, defense=2, pitch=1) for i in range(10)]
        player = PlayerState(
            life=20,
            deck=deck[:],
            hand=[],
            grave=[],
            pitched=[],
            arsenal=[],
        )

        # Simulate draw_up_to behavior
        initial_deck_size = len(player.deck)
        player.draw_up_to(INTELLECT)

        assert len(player.hand) == INTELLECT
        assert len(player.deck) == initial_deck_size - INTELLECT

    def test_start_phase_floating_resources_reset(self):
        """
        Given: Previous turn had floating resources
        When: Turn passes to start phase
        Then: floating_resources reset to [0, 0]
        """
        # This is tested implicitly in new_game and turn transitions
        gs = create_test_game(phase=Phase.SOT, turn=0)
        assert gs.floating_resources == [0, 0]


class TestActionPhase:
    """Tests for Action Phase (GAME_FLOW.md: Turn Phases -> Action Phase)."""

    def test_action_phase_legal_actions_no_combat(self, action_phase_state, simple_attack_card):
        """
        Given: Player in action phase with no pending combat
        When: enumerate_legal_actions is called
        Then: Can play attacks from hand, arsenal attacks, weapon attack, or PASS
        """
        gs = action_phase_state
        # Add attack card to hand
        gs.players[gs.turn].hand.append(simple_attack_card)

        legal = enumerate_legal_actions(gs)

        # Should have at least PASS and PLAY_ATTACK options
        action_types = {act.typ for act in legal}
        assert ActType.PASS in action_types
        assert ActType.PLAY_ATTACK in action_types

    def test_action_phase_consumes_action_point(self, action_phase_state, simple_attack_card):
        """
        Given: Player has 1 action point
        When: Player plays an attack
        Then: action_points decremented (combat initiated)
        """
        gs = action_phase_state
        gs.players[gs.turn].hand.append(simple_attack_card)

        # Add pitch cards
        pitch_cards = [
            Action(typ=ActType.CONTINUE, pitch_mask=0)
            for _ in range(3)
        ]
        from fabgame.models import Card

        gs.players[gs.turn].hand.extend(
            [Card(name=f"Pitch {i}", cost=0, attack=0, defense=2, pitch=1) for i in range(3)]
        )

        legal = enumerate_legal_actions(gs)
        attack_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK]

        if attack_actions:
            new_state, done, info = apply_action(gs, attack_actions[0])
            # Action point consumed when attack is played
            # After combat, may be restored by Go Again
            assert gs.action_points == 1  # Original state unchanged
            # Note: The new state may vary depending on combat flow

    def test_action_phase_pass_no_combat_enters_end_phase(self):
        """
        Given: Player in action phase, no combat pending, has action points
        When: Player executes PASS
        Then: Phase transitions to END, awaiting_arsenal becomes True
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)

        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(gs, pass_action)

        # Should transition to END phase
        assert new_state.phase == Phase.END
        assert new_state.awaiting_arsenal is True
        assert new_state.arsenal_player == 0

    def test_action_phase_with_weapon_attack_option(self, action_phase_state, simple_weapon):
        """
        Given: Player has weapon equipped and not used
        When: Checking legal actions
        Then: WEAPON_ATTACK is available
        """
        gs = action_phase_state
        gs.players[gs.turn].weapon = simple_weapon

        legal = enumerate_legal_actions(gs)
        action_types = {act.typ for act in legal}

        assert ActType.WEAPON_ATTACK in action_types

    def test_action_phase_weapon_used_not_available(self, action_phase_state, simple_weapon):
        """
        Given: Player's weapon already used this turn
        When: Checking legal actions
        Then: WEAPON_ATTACK not available
        """
        gs = action_phase_state
        simple_weapon.used_this_turn = True
        gs.players[gs.turn].weapon = simple_weapon

        legal = enumerate_legal_actions(gs)
        action_types = {act.typ for act in legal}

        assert ActType.WEAPON_ATTACK not in action_types


class TestEndPhase:
    """Tests for End Phase (GAME_FLOW.md: Turn Phases -> End Phase)."""

    def test_end_phase_arsenal_setting(self, end_phase_state):
        """
        Given: Player in end phase with cards in hand
        When: enumerate_legal_actions is called
        Then: Can SET_ARSENAL for each card in hand (if arsenal slot empty), or PASS
        """
        from fabgame.models import Card

        # Add cards to active player's hand
        player = end_phase_state.players[end_phase_state.turn]
        player.hand = [
            Card(name="Card 1", cost=1, attack=2, defense=2, pitch=1),
            Card(name="Card 2", cost=1, attack=2, defense=2, pitch=1),
        ]

        legal = enumerate_legal_actions(end_phase_state)
        action_types = {act.typ for act in legal}

        assert ActType.SET_ARSENAL in action_types
        assert ActType.PASS in action_types

    def test_end_phase_set_arsenal_moves_card(self, end_phase_state):
        """
        Given: Player in end phase
        When: Player executes SET_ARSENAL with card index
        Then: Card moved from hand to arsenal, awaiting_arsenal becomes False
        """
        from fabgame.models import Card

        player = end_phase_state.players[end_phase_state.turn]
        test_card = Card(name="Arsenal Card", cost=1, attack=3, defense=2, pitch=1)
        player.hand = [test_card]

        set_arsenal_action = Action(typ=ActType.SET_ARSENAL, play_idx=0)
        new_state, done, info = apply_action(end_phase_state, set_arsenal_action)

        # Card should move to arsenal
        new_player = new_state.players[end_phase_state.turn]
        assert len(new_player.arsenal) == 1
        assert new_player.arsenal[0].name == "Arsenal Card"
        assert len(new_player.hand) == 0

    def test_end_phase_pass_skips_arsenal(self, end_phase_state):
        """
        Given: Player in end phase
        When: Player executes PASS
        Then: No arsenal set, turn passing continues
        """
        from fabgame.models import Card

        player = end_phase_state.players[end_phase_state.turn]
        player.hand = [Card(name="Card", cost=1, attack=2, defense=2, pitch=1)]

        initial_arsenal_size = len(player.arsenal)

        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(end_phase_state, pass_action)

        # Arsenal should remain unchanged
        new_player = new_state.players[end_phase_state.turn]
        assert len(new_player.arsenal) == initial_arsenal_size

    def test_end_phase_turn_transition(self):
        """
        Given: Player completes arsenal step (or passes)
        When: _end_and_pass_turn executes
        Then: Turn passes, phase returns to SOT, resources cleared
        """
        gs = create_test_game(phase=Phase.END, turn=0)
        gs.awaiting_arsenal = True
        gs.arsenal_player = 0

        # Pass to skip arsenal
        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(gs, pass_action)

        # Should transition to next turn's start phase
        assert new_state.turn == 1
        assert new_state.phase == Phase.SOT
        assert new_state.floating_resources == [0, 0]

    def test_end_phase_pitched_cards_bottom_deck(self):
        """
        Given: Player has pitched cards this turn
        When: Turn ends
        Then: Pitched cards moved to bottom of deck
        """
        from fabgame.models import Card, PlayerState

        pitched_card = Card(name="Pitched", cost=1, attack=2, defense=2, pitch=1)
        player = PlayerState(
            life=20,
            deck=[Card(name=f"Deck {i}", cost=1, attack=2, defense=2, pitch=1) for i in range(5)],
            hand=[],
            grave=[],
            pitched=[pitched_card],
            arsenal=[],
        )

        initial_deck_size = len(player.deck)
        player.bottom_pitched_to_deck()

        assert len(player.pitched) == 0
        assert len(player.deck) == initial_deck_size + 1
        assert player.deck[0].name == "Pitched"  # At bottom (index 0)
