# Machine Learning Bot Roadmap (Extended)

## 1. Objective and Success Criteria

* Deliver a machine-learning driven agent that can plug into the existing `fabgame` engine and participate in bot-vs-bot matches.
* Match or exceed the current heuristic `bot_choose_action` win rate across a representative deck pool; stretch goal is to consistently outperform it by >55% in mirror matches.
* Provide reproducible training scripts, checkpoints, and evaluation harness so future iterations can iterate on the policy.
* **(NEW)** Support multiple ruleset versions (rút gọn → mở rộng go again → full reaction) and record `rules_version` in all replays and training data.
* **(NEW)** Target real-time inference ≤ 50 ms/move on CPU; if exceeded, fall back to heuristic bot.

## 2. Current Engine Facts to Leverage

* Game state surface: `fabgame.models.GameState` exposes per-player life, hand, deck, arsenal, pitched cards, floating resources, action points, and combat metadata; copy semantics already provided.
* Action space: `fabgame.engine.enumerate_legal_actions` yields the full, legal move set each decision step (attack, defend, pitch mask, arsenal usage, weapons, reactions). Output size is variable but bounded by combinatorics of hand size and `DEFEND_MAX`.
* Transition + RNG: `fabgame.engine.apply_action` returns the next state, terminal flag, and event payload while handling validation; `GameState.rng_seed` enables deterministic rollouts when combined with deck seeds.
* Existing opponents: `fabgame.agents.bot_choose_action` offers a deterministic baseline; `launcher.py` already supports `bot-vs-bot` wiring for evaluation loops.
* Card metadata: YAML definitions under `data/cards` contain attack/defense/cost/pitch/keyword fields and structured `abilities` suitable for feature extraction.
* **(NEW)** Future card data may include `source_text` and `rules:` blocks → must keep extractor pluggable.

## 3. Recommended Learning Strategy

* **Overall approach**: staged training pipeline: (1) supervised imitation of heuristic bot, (2) self-play RL (PPO/APPO + GAE) using dynamic action masks.
* **Imperfect information**: treat as partially observable; encode local observations and maintain recurrent hidden state (GRU/LSTM) for opponent behaviour and hidden deck composition.
* **Action selection**: condition the policy on the legal action list each step; either (a) embed legal actions and score them (pointer/attention) or (b) output logits for a fixed template + mask.
* **Reward shaping**:

  * primary: win (+1) / loss (-1) / draw (0)
  * small negative step cost to encourage faster wins
  * **(NEW)** on-hit reward: +r1 when an on-hit effect successfully resolves (damage > 0)
  * **(NEW)** good block reward: +r2 when blocked damage ≥ threshold
  * **(NEW)** overpitch penalty: -r3 when pitched resources significantly > card cost
  * optional intermediate reward for life differential or efficient resource usage.

## 4. Implementation Milestones

### Milestone A — Environment and Tooling

* Wrap the engine in a gym-like interface (`reset`, `step`, `legal_actions`, `info`) that clones states to avoid side effects and supports batch self-play.
* Build a fast simulation loop that can pit arbitrary agents against each other, track win/loss, turn count, and key combat metrics.
* Instrument logging (structured JSON + TensorBoard) for step rewards, episode lengths, and action distributions.
* **(NEW)** Add `rules_version` to the env and propagate it into every transition and replay row.
* **(NEW)** Add deterministic test episodes (fixed deck + fixed seed) to CI.

### Milestone B — Feature Engineering

* Define deterministic encodings for cards (one-hot on card id, numeric attack/defense/cost/pitch, keyword flags, ability buckets).
* Encode per-player observation vectors: life totals, action points, floating resources, pending attack, last attack metadata, counts of deck/grave/pitched piles.
* Implement hand/arsenal encoders using either fixed slots (padding/masking) or permutation-invariant pooling (set transformer, attention pooling).
* Expose opponent public information (revealed blocks, graveyard summaries) while omitting hidden hand data to respect game rules.
* **(NEW)** Build a YAML → feature extractor that reads `rules:` blocks (on_declare, on_hit, on_graveyard, duration, keywords) and emits standardized card features (has_crush, grants_go_again, is_reaction, is_instant, costs_additional, hits_draw_card). This module must be kept separate so Codex-generated YAML stays usable.
* **(NEW)** Embed hero / deck ID so the model can condition behaviour on hero archetype (Guardian vs Ninja vs Brute).

### Milestone C — Baseline Data and Supervised Warm Start

* Generate a large corpus of bot-vs-bot games using the heuristic agent; log `(observation, legal action set, taken action, outcome)` tuples.
* Train an imitation model (cross-entropy on chosen action) to bootstrap the policy head and stabilise subsequent RL.
* Evaluate imitation accuracy and gameplay parity; retain dataset tooling for future offline analysis.
* **(NEW)** Filter out low-quality episodes: drop games with too many PASS-only turns, or no damage over N turns, or stuck defense loops.
* **(NEW)** Version all datasets with: `engine_commit`, `rules_version`, `deck_pool_version` so future training can replicate exact conditions.

### Milestone D — Self-Play Reinforcement Learning

* Implement self-play curriculum: start with imitation-initialised policy against the heuristic bot, then gradually shift to mirror self-play.
* Use PPO/APPO with recurrent policy (GRU/LSTM) and value head conditioned on the same observation; include entropy regularisation and KL control to avoid collapse.
* Handle variable action sets using masked logits; ensure gradient flow only through legal moves.
* Periodically freeze snapshots for evaluation, maintain an Elo-style rating ladder, and perform best-of-N matches versus heuristic and previous checkpoints.
* **(NEW)** Multi-deck curriculum: start with 1 hero (Ira) → 2 heroes (Ira vs Bravo) → 3–5 heroes that exist in YAML; sample decks per episode so the policy generalizes.
* **(NEW)** Add adversarial opponents (always block, never block, high-aggro) to surface exploitability.

### Milestone E — Deployment and Integration

* Package the trained policy in a lightweight inference module (`fabgame/agents_ml.py`) exposing `ml_bot_choose_action(gs, policy)` compatible with existing launcher flows.
* Add CLI options / config toggles to select the ML bot for `bot-vs-bot` and `bot-vs-human` modes; support loading checkpoints from disk.
* Document runtime requirements (Python deps, GPU optional), provide model validation tests, and integrate into CI smoke tests with reduced deck sizes for quick verification.
* **(NEW)** Export model to ONNX / TorchScript to meet latency targets; add CPU-only inference path.
* **(NEW)** Add fallback-to-heuristic if inference time > threshold or model fails validation.

## 5. Evaluation Plan

* Automated regression suite: run fixed-seed matches (e.g., 500 games across varied deck pairs) and report win rate, average life remaining, and average turn count.
* Stress tests: evaluate policy robustness against extreme decks (high defense, high aggression) and adversarial heuristics (e.g., always block, never block) to detect exploitability.
* Human-in-the-loop: optional manual review of selected replays by domain expert to ensure the bot follows legal sequencing and sensible resource usage.
* **(NEW)** Cross-play matrix: evaluate latest policy vs {heuristic, last-best, 2–3 older snapshots} and store results as a table for trend tracking.
* **(NEW)** Per-ruleset evaluation: run the same suite on each `rules_version` that you support, to make sure expanding rules didn’t regress older policies.

## 6. Risks and Mitigations

* **State explosion / long episodes**: apply frame skipping on redundant PASS loops, clip episode length with soft penalties, and profile performance to keep rollouts tractable.
* **Action masking errors**: write unit tests comparing `enumerate_legal_actions` output with the mask fed to the policy to avoid illegal move sampling.
* **Hidden information modelling**: if recurrent policy is insufficient, explore opponent card belief modeling or sampling opponent hands from deck composition.
* **Compute footprint**: start with CPU-based rollouts and scale to GPU inference only if necessary; leverage deterministic seeds for reproducibility.
* **(NEW)** Ruleset churn: store `rules_version` in data; write upgrade scripts to migrate old replays to new format or to drop incompatible episodes.

## 7. Immediate Next Steps

* Stand up the gym-style environment wrapper and minimal simulation harness.
* Draft observation and action encoding specs and validate them against live game traces.
* Launch heuristic self-play data generation to unblock imitation training.
* **(NEW)** Implement YAML → feature extractor and add tests for 4 base triggers: `on_declare`, `on_hit`, `on_block`, `on_graveyard`.
* **(NEW)** Add CI checks for action-mask parity and fixed-seed matches.
