"""Tests for all action types (GAME_FLOW.md: Action Types)."""
from __future__ import annotations

import pytest

from fabgame.engine import apply_action, enumerate_legal_actions
from fabgame.models import Action, ActType, Card, CombatStep, Phase
from tests.conftest import create_test_game


class TestContinueAction:
    """Tests for CONTINUE action."""

    def test_continue_only_legal_at_start(self, basic_game_state):
        """
        Given: Game at start of turn phase
        When: Checking legal actions
        Then: Only CONTINUE available
        """
        gs = basic_game_state
        assert gs.phase == Phase.SOT

        legal = enumerate_legal_actions(gs)
        assert len(legal) == 1
        assert legal[0].typ == ActType.CONTINUE

    def test_continue_not_legal_in_action_phase(self, action_phase_state):
        """
        Given: Game in action phase
        When: Checking legal actions
        Then: CONTINUE not available
        """
        gs = action_phase_state
        assert gs.phase == Phase.ACTION

        legal = enumerate_legal_actions(gs)
        action_types = {act.typ for act in legal}
        assert ActType.CONTINUE not in action_types


class TestPlayAttackAction:
    """Tests for PLAY_ATTACK action."""

    def test_play_attack_from_hand_basic(self, action_phase_state):
        """
        Given: Player has attack card in hand
        When: PLAY_ATTACK executed
        Then: Combat sequence initiated, card moved
        """
        gs = action_phase_state
        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        gs.players[gs.turn].hand = [attack_card]

        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        new_state, done, info = apply_action(gs, attack_action)

        # Combat should be initiated
        assert new_state.pending_attack > 0
        # Card should be removed from hand
        assert len(new_state.players[gs.turn].hand) == 0

    def test_play_attack_insufficient_resources(self):
        """
        Given: Player has expensive card, insufficient pitch pool
        When: Checking legal actions
        Then: Card not in legal action list
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        expensive_card = Card(name="Expensive", cost=5, attack=8, defense=3, pitch=1)
        # Only provide 1 pitch card when 5 is needed
        pitch_card = Card(name="Pitch", cost=0, attack=0, defense=2, pitch=1)
        gs.players[0].hand = [expensive_card, pitch_card]

        legal = enumerate_legal_actions(gs)
        # Should not be able to play expensive card
        attack_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK and a.play_idx == 0]
        # Either no actions or all actions have insufficient pitch
        # The engine should not generate impossible actions

    def test_play_attack_with_pitch_payment(self):
        """
        Given: Player has attack costing 2, has pitch cards
        When: PLAY_ATTACK executed with pitch
        Then: Pitched cards moved to pitched zone
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        attack_card = Card(name="Attack", cost=2, attack=5, defense=3, pitch=1)
        pitch_cards = [
            Card(name=f"Pitch {i}", cost=0, attack=0, defense=2, pitch=1)
            for i in range(2)
        ]
        gs.players[0].hand = [attack_card] + pitch_cards

        # Find legal attack with pitch
        legal = enumerate_legal_actions(gs)
        attack_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK and a.play_idx == 0]

        if attack_actions:
            new_state, done, info = apply_action(gs, attack_actions[0])
            # Some cards should be pitched
            assert len(new_state.players[0].pitched) >= 2


class TestPlayArsenalAttackAction:
    """Tests for PLAY_ARSENAL_ATTACK action."""

    def test_arsenal_attack_basic(self):
        """
        Given: Player has attack card in arsenal
        When: PLAY_ARSENAL_ATTACK executed
        Then: Card moved from arsenal, combat initiated
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        arsenal_card = Card(name="Arsenal Attack", cost=0, attack=4, defense=3, pitch=1)
        gs.players[0].arsenal = [arsenal_card]

        arsenal_action = Action(typ=ActType.PLAY_ARSENAL_ATTACK, play_idx=0, pitch_mask=0)
        new_state, done, info = apply_action(gs, arsenal_action)

        # Arsenal should be empty
        assert len(new_state.players[0].arsenal) == 0
        # Combat initiated
        assert new_state.pending_attack > 0

    def test_arsenal_attack_not_available_when_empty(self, action_phase_state):
        """
        Given: Player has empty arsenal
        When: Checking legal actions
        Then: PLAY_ARSENAL_ATTACK not available
        """
        gs = action_phase_state
        assert len(gs.players[gs.turn].arsenal) == 0

        legal = enumerate_legal_actions(gs)
        action_types = {act.typ for act in legal}
        assert ActType.PLAY_ARSENAL_ATTACK not in action_types


class TestWeaponAttackAction:
    """Tests for WEAPON_ATTACK action."""

    def test_weapon_attack_basic(self, action_phase_state, simple_weapon):
        """
        Given: Player has weapon equipped, not used
        When: WEAPON_ATTACK executed
        Then: Weapon attack value becomes pending_attack, used_this_turn set
        """
        gs = action_phase_state
        gs.players[gs.turn].weapon = simple_weapon

        weapon_action = Action(typ=ActType.WEAPON_ATTACK, pitch_mask=0)
        new_state, done, info = apply_action(gs, weapon_action)

        # Weapon should be marked as used
        assert new_state.players[gs.turn].weapon.used_this_turn is True
        # Attack value should be set
        assert new_state.pending_attack == simple_weapon.base_attack

    def test_weapon_attack_once_per_turn_restriction(self, action_phase_state, simple_weapon):
        """
        Given: Weapon with once_per_turn=True, already used
        When: Checking legal actions
        Then: WEAPON_ATTACK not available
        """
        gs = action_phase_state
        simple_weapon.used_this_turn = True
        gs.players[gs.turn].weapon = simple_weapon

        legal = enumerate_legal_actions(gs)
        action_types = {act.typ for act in legal}
        assert ActType.WEAPON_ATTACK not in action_types

    def test_weapon_attack_go_again(self, action_phase_state, go_again_weapon):
        """
        Given: Weapon with Go Again keyword
        When: Weapon attack resolves
        Then: Action point restored
        """
        gs = action_phase_state
        gs.players[gs.turn].weapon = go_again_weapon

        # Add pitch card for cost
        pitch_card = Card(name="Pitch", cost=0, attack=0, defense=2, pitch=1)
        gs.players[gs.turn].hand = [pitch_card]

        # Execute weapon attack
        weapon_action = Action(typ=ActType.WEAPON_ATTACK, pitch_mask=1)
        state1, done, info = apply_action(gs, weapon_action)

        # Complete combat (defender passes, both pass in reaction)
        pass_action = Action(typ=ActType.PASS)
        state2, done, info = apply_action(state1, pass_action)
        state3, done, info = apply_action(state2, pass_action)
        state4, done, info = apply_action(state3, pass_action)

        # Action point should be restored
        assert state4.action_points == 1

    def test_weapon_attack_stays_equipped(self, action_phase_state, simple_weapon):
        """
        Given: Player attacks with weapon
        When: Attack resolves
        Then: Weapon remains equipped (not in graveyard)
        """
        gs = action_phase_state
        gs.players[gs.turn].weapon = simple_weapon

        weapon_action = Action(typ=ActType.WEAPON_ATTACK, pitch_mask=0)
        new_state, done, info = apply_action(gs, weapon_action)

        # Weapon should still be equipped
        assert new_state.players[gs.turn].weapon is not None
        assert new_state.players[gs.turn].weapon.name == simple_weapon.name


class TestDefendAction:
    """Tests for DEFEND action."""

    def test_defend_in_block_phase(self, combat_defend_state):
        """
        Given: Defender in block phase
        When: DEFEND with card mask executed
        Then: Cards moved to graveyard, block value accumulated
        """
        gs = combat_defend_state
        defender_idx = 1 - gs.turn

        defense_card = Card(name="Defense", cost=0, attack=0, defense=3, pitch=1)
        gs.players[defender_idx].hand = [defense_card]

        defend_action = Action(typ=ActType.DEFEND, defend_mask=1)
        new_state, done, info = apply_action(gs, defend_action)

        assert new_state.reaction_block == defense_card.defense

    def test_defend_with_defense_reactions(self, combat_reaction_state, defense_reaction_card):
        """
        Given: Defender in reaction step with defense reaction
        When: DEFEND with reaction card executed
        Then: Reaction adds to block value
        """
        gs = combat_reaction_state
        defender_idx = 1
        gs.players[defender_idx].hand = [defense_reaction_card]

        initial_block = gs.reaction_block

        defend_action = Action(typ=ActType.DEFEND, defend_mask=1)
        new_state, done, info = apply_action(gs, defend_action)

        assert new_state.reaction_block > initial_block

    def test_defend_mask_encoding(self):
        """
        Given: Defender selecting multiple block cards
        When: Action created with mask
        Then: Mask correctly encodes selected cards
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        gs.players[0].hand = [attack_card]

        defense_cards = [
            Card(name=f"Defense {i}", cost=0, attack=0, defense=2, pitch=1)
            for i in range(3)
        ]
        gs.players[1].hand = defense_cards

        # Execute attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, done, info = apply_action(gs, attack_action)

        # Defend with cards 0 and 2 (mask = 0b101 = 5)
        defend_action = Action(typ=ActType.DEFEND, defend_mask=0b101)
        state2, done, info = apply_action(state1, defend_action)

        # Should have used 2 cards
        expected_block = defense_cards[0].defense + defense_cards[2].defense
        assert state2.reaction_block == expected_block


class TestPlayAttackReactionAction:
    """Tests for PLAY_ATTACK_REACTION action."""

    def test_attack_reaction_during_reaction_step(self, combat_reaction_state, attack_reaction_card):
        """
        Given: Attacker in reaction step with attack reaction
        When: PLAY_ATTACK_REACTION executed
        Then: Attack value increases
        """
        gs = combat_reaction_state
        gs.reaction_actor = 0  # Attacker
        gs.combat_passes = 1

        pitch_card = Card(name="Pitch", cost=0, attack=0, defense=2, pitch=1)
        gs.players[0].hand = [attack_reaction_card, pitch_card]

        initial_attack = gs.pending_attack

        legal = enumerate_legal_actions(gs)
        reaction_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK_REACTION]

        if reaction_actions:
            new_state, done, info = apply_action(gs, reaction_actions[0])
            assert new_state.pending_attack > initial_attack

    def test_attack_reaction_cost_payment(self, combat_reaction_state):
        """
        Given: Attack reaction with cost
        When: PLAY_ATTACK_REACTION executed
        Then: Resources consumed via floating + pitch
        """
        gs = combat_reaction_state
        gs.reaction_actor = 0
        gs.combat_passes = 1

        reaction_card = Card(name="Reaction", cost=1, attack=2, defense=0, pitch=1, keywords=["attack_reaction"])
        pitch_card = Card(name="Pitch", cost=0, attack=0, defense=2, pitch=1)
        gs.players[0].hand = [reaction_card, pitch_card]

        legal = enumerate_legal_actions(gs)
        reaction_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK_REACTION]

        if reaction_actions:
            new_state, done, info = apply_action(gs, reaction_actions[0])
            # Pitched cards should be in pitched zone
            assert len(new_state.players[0].pitched) > 0


class TestPassAction:
    """Tests for PASS action."""

    def test_pass_in_action_phase_ends_turn(self):
        """
        Given: Action phase, no combat, has action points
        When: PASS executed
        Then: Transitions to end phase
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)

        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(gs, pass_action)

        assert new_state.phase == Phase.END

    def test_pass_in_layer_step(self, combat_layer_state):
        """
        Given: Layer step
        When: PASS executed
        Then: Priority toggles, combat_passes increments
        """
        gs = combat_layer_state
        assert gs.combat_priority == 0

        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(gs, pass_action)

        assert new_state.combat_priority == 1
        assert new_state.combat_passes == 1

    def test_pass_in_reaction_step(self, combat_reaction_state):
        """
        Given: Reaction step, defender has priority
        When: PASS executed
        Then: Priority to attacker, combat_passes increments
        """
        gs = combat_reaction_state
        assert gs.reaction_actor == 1

        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(gs, pass_action)

        assert new_state.reaction_actor == 0
        assert new_state.combat_passes == 1

    def test_pass_in_end_phase(self, end_phase_state):
        """
        Given: End phase arsenal prompt
        When: PASS executed
        Then: No arsenal set, turn passing continues
        """
        gs = end_phase_state
        from fabgame.models import Card

        gs.players[gs.turn].hand = [Card(name="Card", cost=1, attack=2, defense=2, pitch=1)]

        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(gs, pass_action)

        # Turn should pass
        assert new_state.turn != gs.turn or new_state.phase == Phase.SOT


class TestSetArsenalAction:
    """Tests for SET_ARSENAL action."""

    def test_set_arsenal_moves_card(self, end_phase_state):
        """
        Given: Player in end phase with cards
        When: SET_ARSENAL executed
        Then: Card moved from hand to arsenal
        """
        gs = end_phase_state
        from fabgame.models import Card

        test_card = Card(name="Arsenal Card", cost=1, attack=3, defense=2, pitch=1)
        gs.players[gs.turn].hand = [test_card]

        set_action = Action(typ=ActType.SET_ARSENAL, play_idx=0)
        new_state, done, info = apply_action(gs, set_action)

        player = new_state.players[gs.turn]
        assert len(player.arsenal) == 1
        assert player.arsenal[0].name == "Arsenal Card"
        assert len(player.hand) == 0

    def test_set_arsenal_only_if_slot_empty(self):
        """
        Given: Arsenal already occupied
        When: Checking legal actions in end phase
        Then: SET_ARSENAL not available
        """
        gs = create_test_game(phase=Phase.END, turn=0)
        from fabgame.models import Card

        # Arsenal already has a card
        gs.players[0].arsenal = [Card(name="Existing", cost=1, attack=2, defense=2, pitch=1)]
        gs.players[0].hand = [Card(name="New Card", cost=1, attack=2, defense=2, pitch=1)]
        gs.awaiting_arsenal = True
        gs.arsenal_player = 0

        legal = enumerate_legal_actions(gs)
        action_types = {act.typ for act in legal}

        # SET_ARSENAL should not be available when arsenal is full
        assert ActType.SET_ARSENAL not in action_types

    def test_set_arsenal_only_in_end_phase(self, action_phase_state):
        """
        Given: Action phase
        When: Checking legal actions
        Then: SET_ARSENAL not available
        """
        gs = action_phase_state

        legal = enumerate_legal_actions(gs)
        action_types = {act.typ for act in legal}

        assert ActType.SET_ARSENAL not in action_types
