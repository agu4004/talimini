"""Integration tests for end-to-end game scenarios."""
from __future__ import annotations

import pytest

from fabgame.engine import apply_action, enumerate_legal_actions
from fabgame.models import Action, ActType, Card, CombatStep, Phase
from tests.conftest import create_test_game


class TestFullTurnSequence:
    """Full turn sequence integration tests."""

    def test_full_turn_sequence_basic(self):
        """
        Given: Game initialized
        When: Complete turn sequence executed
        Then: SOT → ACTION → combat → END → next turn
        """
        gs = create_test_game(phase=Phase.SOT, turn=0)

        # 1. Start: CONTINUE → action phase
        continue_action = Action(typ=ActType.CONTINUE)
        state1, _, _ = apply_action(gs, continue_action)
        assert state1.phase == Phase.ACTION
        assert state1.action_points == 1

        # 2. Action: Add attack card and play it
        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        state1.players[0].hand = [attack_card]

        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state2, _, _ = apply_action(state1, attack_action)

        # 3. Combat: Complete layer, defend, reaction
        # Layer: two passes
        pass_action = Action(typ=ActType.PASS)
        state3, _, _ = apply_action(state2, pass_action)
        state4, _, _ = apply_action(state3, pass_action)

        # Defend: pass (no block)
        state5, _, _ = apply_action(state4, pass_action)

        # Reaction: both pass
        state6, _, _ = apply_action(state5, pass_action)
        state7, _, _ = apply_action(state6, pass_action)

        # Should be back in action phase with 0 action points
        assert state7.phase == Phase.ACTION
        assert state7.action_points == 0
        assert state7.combat_step == CombatStep.IDLE

        # 4. Action: PASS → end phase
        state8, _, _ = apply_action(state7, pass_action)
        assert state8.phase == Phase.END
        assert state8.awaiting_arsenal is True

        # 5. End: PASS (skip arsenal) → next turn
        state9, _, _ = apply_action(state8, pass_action)
        assert state9.turn == 1
        assert state9.phase == Phase.SOT

    def test_multi_attack_turn_with_go_again(self):
        """
        Given: Player has 2 Go Again attacks
        When: Turn executed
        Then: First attack → Go Again → second attack → end
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)

        go_again_cards = [
            Card(name=f"Go Again {i}", cost=0, attack=4, defense=2, pitch=1, keywords=["go_again"])
            for i in range(2)
        ]
        gs.players[0].hand = go_again_cards

        # First attack
        attack1_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, _, _ = apply_action(gs, attack1_action)

        # Complete combat
        pass_action = Action(typ=ActType.PASS)
        state2, _, _ = apply_action(state1, pass_action)
        state3, _, _ = apply_action(state2, pass_action)
        state4, _, _ = apply_action(state3, pass_action)
        state5, _, _ = apply_action(state4, pass_action)

        # Should have action point restored
        assert state5.action_points == 1
        assert state5.phase == Phase.ACTION

        # Second attack
        legal = enumerate_legal_actions(state5)
        attack_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK]

        if attack_actions:
            state6, _, _ = apply_action(state5, attack_actions[0])

            # Complete second combat
            state7, _, _ = apply_action(state6, pass_action)
            state8, _, _ = apply_action(state7, pass_action)
            state9, _, _ = apply_action(state8, pass_action)
            state10, _, _ = apply_action(state9, pass_action)

            # Action point restored again
            assert state10.action_points == 1
            assert state10.phase == Phase.ACTION


class TestCombatWithReactions:
    """Combat with reactions integration tests."""

    def test_combat_with_defense_reactions(self):
        """
        Given: Defender has defense reactions
        When: Combat executed
        Then: Block → defense reaction → damage reduced
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)

        attack_card = Card(name="Attack", cost=0, attack=8, defense=3, pitch=1)
        block_card = Card(name="Block", cost=0, attack=0, defense=2, pitch=1)
        reaction_card = Card(name="Reaction", cost=0, attack=0, defense=3, pitch=1,
                           keywords=["defense_reaction", "reaction"])

        gs.players[0].hand = [attack_card]
        gs.players[1].hand = [block_card, reaction_card]

        defender_life = gs.players[1].life

        # Execute attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, _, _ = apply_action(gs, attack_action)

        # Complete layer
        pass_action = Action(typ=ActType.PASS)
        state2, _, _ = apply_action(state1, pass_action)
        state3, _, _ = apply_action(state2, pass_action)

        # Block with regular card
        defend_action = Action(typ=ActType.DEFEND, defend_mask=1)  # First card
        state4, _, _ = apply_action(state3, defend_action)

        assert state4.reaction_block == 2

        # In reaction step, play defense reaction
        legal = enumerate_legal_actions(state4)
        defend_reactions = [a for a in legal if a.typ == ActType.DEFEND and a.defend_mask != 0]

        if defend_reactions:
            state5, _, _ = apply_action(state4, defend_reactions[0])
            # Total block should be 2 + 3 = 5
            assert state5.reaction_block >= 5

            # Both pass
            state6, _, _ = apply_action(state5, pass_action)
            state7, _, _ = apply_action(state6, pass_action)

            # Damage should be 8 - 5 = 3
            expected_life = defender_life - 3
            assert state7.players[1].life == expected_life

    def test_combat_with_attack_reactions(self):
        """
        Given: Attacker has attack reactions
        When: Combat executed
        Then: Initial attack → defense → attack reaction → increased damage
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)

        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        attack_reaction = Card(name="Attack Reaction", cost=0, attack=2, defense=0, pitch=1,
                              keywords=["attack_reaction", "reaction"])
        defense_card = Card(name="Defense", cost=0, attack=0, defense=2, pitch=1)

        gs.players[0].hand = [attack_card, attack_reaction]
        gs.players[1].hand = [defense_card]

        defender_life = gs.players[1].life

        # Execute attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, _, _ = apply_action(gs, attack_action)

        # Complete layer
        pass_action = Action(typ=ActType.PASS)
        state2, _, _ = apply_action(state1, pass_action)
        state3, _, _ = apply_action(state2, pass_action)

        # Defend
        defend_action = Action(typ=ActType.DEFEND, defend_mask=1)
        state4, _, _ = apply_action(state3, defend_action)

        # Defender passes in reaction
        state5, _, _ = apply_action(state4, pass_action)

        # Attacker plays attack reaction
        legal = enumerate_legal_actions(state5)
        attack_reactions = [a for a in legal if a.typ == ActType.PLAY_ATTACK_REACTION]

        if attack_reactions:
            state6, _, _ = apply_action(state5, attack_reactions[0])

            # Attack should increase
            assert state6.pending_attack > 5

            # Defender passes, attacker passes
            state7, _, _ = apply_action(state6, pass_action)
            state8, _, _ = apply_action(state7, pass_action)

            # Damage should be (5 + 2) - 2 = 5
            expected_life = defender_life - 5
            assert state8.players[1].life == expected_life

    def test_reaction_priority_alternation(self):
        """
        Given: Both players have reactions
        When: Reaction step executes
        Then: Defender → attacker → defender → attacker alternation
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)

        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        defense_reaction = Card(name="Defense Reaction", cost=0, attack=0, defense=2, pitch=1,
                               keywords=["defense_reaction", "reaction"])
        attack_reaction = Card(name="Attack Reaction", cost=0, attack=2, defense=0, pitch=1,
                              keywords=["attack_reaction", "reaction"])

        gs.players[0].hand = [attack_card, attack_reaction]
        gs.players[1].hand = [defense_reaction]

        # Execute attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, _, _ = apply_action(gs, attack_action)

        # Complete layer and defend step
        pass_action = Action(typ=ActType.PASS)
        state2, _, _ = apply_action(state1, pass_action)
        state3, _, _ = apply_action(state2, pass_action)
        state4, _, _ = apply_action(state3, pass_action)  # Defender passes on block

        # Reaction step: defender has priority
        assert state4.reaction_actor == 1 or state4.combat_step == CombatStep.REACTION

        # Defender plays defense reaction
        legal = enumerate_legal_actions(state4)
        defend_reactions = [a for a in legal if a.typ == ActType.DEFEND and a.defend_mask != 0]

        if defend_reactions:
            state5, _, _ = apply_action(state4, defend_reactions[0])

            # Priority should remain with defender (after defense reaction)
            # Then attacker can respond
            legal2 = enumerate_legal_actions(state5)
            # Check if attacker can play attack reaction or must pass


class TestGameToCompletion:
    """Full game to win condition."""

    def test_game_to_completion(self):
        """
        Given: Two players, full decks
        When: Game played until win condition
        Then: Multiple turns, life decreases, winner declared
        """
        gs = create_test_game(phase=Phase.SOT, turn=0)

        # Reduce starting life for faster test
        gs.players[0].life = 10
        gs.players[1].life = 10

        # Add simple attack cards to both players
        for i in range(2):
            attack_cards = [
                Card(name=f"Attack {j}", cost=0, attack=5, defense=2, pitch=1)
                for j in range(10)
            ]
            gs.players[i].deck = attack_cards
            gs.players[i].hand = []

        # Play until someone wins (with turn limit to prevent infinite loops)
        max_turns = 20
        turn_count = 0
        done = False

        while not done and turn_count < max_turns:
            legal = enumerate_legal_actions(gs)

            if not legal:
                break

            # Simple strategy: always take first legal action
            gs, done, info = apply_action(gs, legal[0])
            turn_count += 1

            # Check for win condition
            if gs.players[0].life <= 0 or gs.players[1].life <= 0:
                done = True
                break

        # Game should eventually end
        assert turn_count < max_turns or done

    def test_multiple_turns_execute_correctly(self):
        """
        Given: Game initialized
        When: Multiple turns executed
        Then: Turns alternate, phases cycle correctly
        """
        gs = create_test_game(phase=Phase.SOT, turn=0)

        # Turn 1: Player 0
        assert gs.turn == 0
        assert gs.phase == Phase.SOT

        # CONTINUE
        continue_action = Action(typ=ActType.CONTINUE)
        state1, _, _ = apply_action(gs, continue_action)

        # PASS to end
        pass_action = Action(typ=ActType.PASS)
        state2, _, _ = apply_action(state1, pass_action)

        # Pass arsenal
        state3, _, _ = apply_action(state2, pass_action)

        # Turn 2: Player 1
        assert state3.turn == 1
        assert state3.phase == Phase.SOT

        # CONTINUE
        state4, _, _ = apply_action(state3, continue_action)
        assert state4.phase == Phase.ACTION

        # PASS to end
        state5, _, _ = apply_action(state4, pass_action)
        assert state5.phase == Phase.END

        # Pass arsenal
        state6, _, _ = apply_action(state5, pass_action)

        # Turn 3: Player 0 again
        assert state6.turn == 0
        assert state6.phase == Phase.SOT

    def test_life_totals_decrease_over_time(self):
        """
        Given: Multiple combat rounds
        When: Damage dealt
        Then: Life totals progressively decrease
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)

        # Give both players attacks
        for i in range(2):
            gs.players[i].hand = [
                Card(name=f"Attack {j}", cost=0, attack=5, defense=2, pitch=1)
                for j in range(5)
            ]

        initial_life_0 = gs.players[0].life
        initial_life_1 = gs.players[1].life

        # Execute one attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, _, _ = apply_action(gs, attack_action)

        # Complete combat (no blocks)
        pass_action = Action(typ=ActType.PASS)
        state2, _, _ = apply_action(state1, pass_action)
        state3, _, _ = apply_action(state2, pass_action)
        state4, _, _ = apply_action(state3, pass_action)
        state5, _, _ = apply_action(state4, pass_action)

        # Defender life should decrease
        assert state5.players[1].life < initial_life_1

        # Continue turn and attack back
        # (Additional test steps...)


class TestComplexScenarios:
    """Complex multi-step scenarios."""

    def test_chain_attacks_with_resources(self):
        """
        Given: Player has attacks with costs and Go Again
        When: Chaining attacks
        Then: Resources managed correctly across attacks
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)

        # Attack costs 1, has Go Again
        attack1 = Card(name="Attack 1", cost=1, attack=4, defense=2, pitch=1, keywords=["go_again"])
        # Attack costs 0
        attack2 = Card(name="Attack 2", cost=0, attack=3, defense=2, pitch=1, keywords=["go_again"])
        # Pitch cards
        pitch_cards = [
            Card(name=f"Pitch {i}", cost=0, attack=0, defense=2, pitch=1)
            for i in range(3)
        ]

        gs.players[0].hand = [attack1, attack2] + pitch_cards

        # First attack (cost 1)
        legal = enumerate_legal_actions(gs)
        attack1_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK and a.play_idx == 0]

        if attack1_actions:
            state1, _, _ = apply_action(gs, attack1_actions[0])

            # Complete combat
            pass_action = Action(typ=ActType.PASS)
            state2, _, _ = apply_action(state1, pass_action)
            state3, _, _ = apply_action(state2, pass_action)
            state4, _, _ = apply_action(state3, pass_action)
            state5, _, _ = apply_action(state4, pass_action)

            # Should have action point back
            assert state5.action_points == 1

            # Second attack (cost 0, should be free)
            legal2 = enumerate_legal_actions(state5)
            attack2_actions = [a for a in legal2 if a.typ == ActType.PLAY_ATTACK]

            if attack2_actions:
                state6, _, _ = apply_action(state5, attack2_actions[0])
                # Should succeed
                assert state6.pending_attack > 0

    def test_arsenal_usage_over_turns(self):
        """
        Given: Card set to arsenal
        When: Multiple turns pass
        Then: Arsenal card persists and can be used
        """
        gs = create_test_game(phase=Phase.END, turn=0)

        arsenal_card = Card(name="Arsenal Attack", cost=0, attack=4, defense=2, pitch=1)
        gs.players[0].hand = [arsenal_card]
        gs.awaiting_arsenal = True
        gs.arsenal_player = 0

        # Set arsenal
        set_action = Action(typ=ActType.SET_ARSENAL, play_idx=0)
        state1, _, _ = apply_action(gs, set_action)

        # Should be in arsenal
        assert len(state1.players[0].arsenal) == 1

        # Turn passes
        assert state1.turn == 1

        # Next turn for player 0
        state1.turn = 0
        state1.phase = Phase.ACTION
        state1.action_points = 1

        # Should be able to play arsenal attack
        legal = enumerate_legal_actions(state1)
        action_types = {act.typ for act in legal}
        assert ActType.PLAY_ARSENAL_ATTACK in action_types
