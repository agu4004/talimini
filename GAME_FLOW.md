# Game Flow Overview

This project runs a streamlined Flesh and Blood loop with a fixed set of phases and state transitions. The notes below reflect the current engine (see `fabgame/engine.py`) after the latest blocking updates.

## Turn Phases

1. **Start Phase**
   - Triggered when `_end_and_pass_turn` finishes the previous turn.
   - Active player draws up to intellect, floating/resources reset, and the player advances by selecting `CONTINUE`, which grants 1 action point and transitions into the Action phase.

2. **Action Phase**
   - Combines card plays, blocking, and reactions into a single priority loop.
   - **Attacking player actions**
     - Play an attack from hand (`PLAY_ATTACK`).
     - Attack from arsenal (`PLAY_ARSENAL_ATTACK`).
     - Swing the equipped weapon (`WEAPON_ATTACK`).
     - `PASS` if no combat is pending (moves toward the End phase).
   - **Attack declaration sequence**
     1. Pay costs (floating resources + pitch); move attacker card to graveyard (weapons stay equipped).
     2. Record attack state via `apply_on_declare_attack_modifiers` (`pending_attack`, `last_attack_card`, `last_pitch_sum`, Go Again flags).
     3. Defender immediately chooses non-reaction block cards (up to `DEFEND_MAX`). Cards move to graveyard and their defense sums into `reaction_block`. Passing keeps the block total at 0.
     4. Priority alternates while the phase remains Action:
        - Defender can play defense reactions (`DEFEND`) or pass.
        - Attacker can play attack reactions (`PLAY_ATTACK_REACTION`) or pass.
        - Passing is tracked with `combat_passes`: a defender pass sets the counter to 1, and an immediate attacker pass with the counter already at 1 moves the flow forward. If the attacker passes first, priority simply returns to the defender with no damage being dealt.
     5. When both players pass consecutively, the engine walks through a lightweight **Damage → Resolution** sequence (damage = `pending_attack - reaction_block`, Go Again restored if applicable). Combat state resets and the attacking player retains priority in the same Action phase, spending remaining action points as desired.

3. **End Phase**
   - Triggered when the attacker chooses `PASS` with no pending combat and `_begin_arsenal_step` succeeds.
   - Current player may set a card to an empty arsenal slot (`SET_ARSENAL`) or skip.
   - `_end_and_pass_turn` then bottom-decks pitched cards, draws up to intellect, clears floating resources/reaction data, flips the turn, and returns to the Start phase.

## State Highlights

- `GameState` tracks reaction metadata (`reaction_actor`, `reaction_block`, `reaction_arsenal_cards`) so blocking and reactions accumulate before damage is applied. `combat_passes` is reused to count passes on both the Layer and Reaction sub-steps.
- Floating resources persist throughout the Action phase; `_consume_resources` reconciles floating plus newly pitched cards per attack.
- Cards loaded via `hydrate_card_entry` carry both display text and the raw `abilities` mapping from YAML for future data-driven logic.

## Action Types (ActType)

| Enum                   | Description                                                                |
| ---------------------- | -------------------------------------------------------------------------- |
| `CONTINUE`             | Advance from Start into Action.                                            |
| `PLAY_ATTACK`          | Attack from hand.                                                          |
| `PLAY_ARSENAL_ATTACK`  | Attack from arsenal.                                                       |
| `WEAPON_ATTACK`        | Swing the equipped weapon.                                                 |
| `PLAY_ATTACK_REACTION` | Play an attack reaction during the Action-phase reaction sub-step.         |
| `DEFEND`               | Declare blocks (non-reaction or reaction) depending on the current context.|
| `PASS`                 | Pass priority (ends block/reaction exchanges or ends the turn).            |
| `SET_ARSENAL`          | Set a card to arsenal during the End phase prompt.                         |

## Where to Look in Code

- Phase control & turn transitions: `fabgame/engine.py` (`enumerate_legal_actions`, `_apply_action_impl`, `_end_and_pass_turn`).
- Blocking + reaction flow: Action-phase branch and reaction logic in `_apply_action_impl`.
- Card hydration (`text`, `abilities` payloads): `fabgame/deck.py`, `fabgame/io/card_yaml.py`.
- Models with new metadata fields: `fabgame/models.py`.
- CLI loop / prompts: `fabgame/ui.py`, `fabgame/agents.py`.

Use this document as a starting point when adapting the engine or wiring the YAML-driven `abilities` data into runtime behaviour.
