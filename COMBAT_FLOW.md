# Combat Flow Cheat Sheet

This document summarizes what happens once an attack is declared during the unified **Action** phase. The flow mirrors the state transitions in `fabgame/engine.py` (see `CombatStep`), which currently walk through six ordered steps: **Layer → Attack → Defend → Reaction → Damage → Resolution**. The engine resets to *idle* after Resolution; there is no separate “Close step” implemented yet.

---

## 1. Layer
After an attack is declared, the game records the combat state and enters the **Layer** step:

- `combat_step` is set to `LAYER` and priority sits with the attacker (`combat_priority`).
- The engine only allows players to **pass** in the current build, but the step exists to host instant-speed effects in the future.
- Each `PASS` toggles priority and updates `combat_passes`; after two passes in succession the layer closes, a `layer_end` event is logged, and the sequence advances to the Attack step.

---

## 2. Attack
Once the Layer step closes, the attack becomes live:

1. **Pay costs** with floating resources first, then new pitch (`_consume_resources`).
2. **Move the card** (hand/arsenal) to the graveyard; weapons stay equipped.
3. **Apply modifiers** via `apply_on_declare_attack_modifiers`, updating `pending_attack`, `last_attack_card`, `last_pitch_sum`, and Go Again flags.
4. **Prep combat state** by resetting reaction trackers and flagging that the defender may now block (`combat_step = ATTACK`, `awaiting_defense = True`).

A `declare_attack` event is emitted showing card name, final attack, cost, pitch used, and source.

---

## 3. Defend
The defending player can now declare non-reaction blocks:

- Legal actions: `DEFEND` (choose up to `DEFEND_MAX` non-reaction defense cards) or `PASS` to block nothing.
- Chosen cards move from hand to grave and their defense totals accumulate in `reaction_block`.
- The engine records the block (`block_play` or `block_pass`) and transitions to the Reaction step with priority on the defender.

---

## 4. Reaction
Priority alternates until both players pass consecutively. Logic lives entirely in the Action phase, but `combat_step` is set to `REACTION`:

- **Defender priority**: may play defense reactions from hand/arsenal (`DEFEND`) or pass. Arsenal reactions are logged in `reaction_arsenal_cards` and add to `reaction_block`. A defender pass bumps `combat_passes` to 1 and hands priority to the attacker.
- **Attacker priority**: may play attack reactions (`PLAY_ATTACK_REACTION`) from hand/arsenal. Each reaction spends resources, moves to grave, and adds its bonus to `pending_attack`. Reactions reset `combat_passes` to 0 before returning priority to the defender.
- Passing simply flips `reaction_actor`; if the attacker passes while `combat_passes` is 0, priority returns to the defender. When the attacker passes with `combat_passes == 1`, the flow proceeds to Damage.

Relevant events: `defense_react_play`, `attack_react`, `reaction_pass`.

---

## 5. Damage
Triggered when the attacker passes with no further reactions:

1. Compute `damage = max(0, pending_attack - reaction_block)` and store it in `pending_damage`.
2. Apply damage to the defending hero, if any, and flip `combat_step` to `DAMAGE` then `RESOLUTION`.
3. No further actions are offered; once bookkeeping completes, the engine returns to the Resolution step.

If the attack dealt damage, it is considered to have hit.

---

## 6. Resolution
The combat chain link resolves and the game returns to the Action phase:

1. A `defense_resolve` event logs total block, damage dealt, remaining life, and any arsenal reactions.
2. Go Again (if flagged) restores one action point.
3. Combat state resets (`pending_attack`, `reaction_block`, `reaction_actor`, `combat_step`, etc.) so the attacker can continue their turn or pass.

After this reset the system is back in idle Action play; there is no explicit Close step in the current implementation.

---

## Key State Fields

| Field                    | Description                                                |
|--------------------------|------------------------------------------------------------|
| `combat_step`            | Current combat phase (`LAYER`, `ATTACK`, `REACTION`, …).    |
| `combat_priority`        | Which player has priority during the Layer step (toggled on each pass). |
| `combat_passes`          | Counts consecutive passes on the Layer and Reaction steps. |
| `pending_attack`         | Attack value currently resolving.                         |
| `reaction_block`         | Combined block (regular block + defense reactions).       |
| `reaction_actor`         | Whose turn it is during the reaction sub-loop.            |
| `reaction_arsenal_cards` | Defense reactions played from arsenal (for logging).     |
| `last_attack_had_go_again` | Tracks whether Go Again should restore an action point. |

---

## Where to Look in Code

- Combat state & sequencing: `fabgame/engine.py` (`CombatStep`, `_apply_action_impl`, `enumerate_legal_actions`).
- Player prompts and bot logic: `fabgame/agents.py` (block step + reaction options).
- Logging: `fabgame/pretty.py` events (`layer_pass`, `layer_end`, `declare_attack`, `block_play`, `attack_react`, `defense_resolve`, etc.).

Keep this reference handy when adjusting combat timing or introducing new reaction behaviours.
