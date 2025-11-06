from __future__ import annotations

import argparse
import os
from typing import Optional

from fabgame import config
from fabgame.deck import DeckLoadResult, discover_deck_files, load_deck_from_json, prompt_pick_deck
from fabgame.launcher import DEFAULT_MODES, LauncherConfig, LauncherGUI, LauncherUI
from fabgame.ui import play_loop


MODES = dict(DEFAULT_MODES)


def select_deck(path: Optional[str]) -> Optional[DeckLoadResult]:
    if path and os.path.isfile(path):
        try:
            return load_deck_from_json(path)
        except Exception as exc:
            print(f"Failed to load deck from '{path}': {exc}. Falling back to selection menu.")
    return None


def prompt_mode_selection() -> str:
    print("\n=== MODE SELECTOR ===")
    for key, label in MODES.items():
        print(f"[{key}] {label}")
    keys = "/".join(MODES.keys())
    while True:
        choice = input(f"Choose mode [{keys}]: ").strip().lower()
        if choice in MODES:
            return choice
        print("  Invalid selection, please try again.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", default=None, choices=list(MODES.keys()), help="hh/hb/bh/bb")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--d0", type=str, default=None, help="Deck JSON for Player 0 (leave blank to pick interactively)")
    parser.add_argument("--d1", type=str, default=None, help="Deck JSON for Player 1 (leave blank to pick interactively)")
    parser.add_argument("--agent0", type=str, choices=["human", "bot", "ml"], default=None, help="Override agent for Player 0")
    parser.add_argument("--agent1", type=str, choices=["human", "bot", "ml"], default=None, help="Override agent for Player 1")
    parser.add_argument("--ml-policy", type=str, default=None, help="Path to a trained ML policy checkpoint")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors in the log output")
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Launch the interactive launcher UI for easier configuration",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the graphical launcher window (requires Tkinter)",
    )
    args = parser.parse_args()

    if args.interactive and args.gui:
        parser.error("Choose at most one of --interactive or --gui.")

    if args.interactive:
        initial = LauncherConfig(
            mode_key=args.mode or next(iter(MODES.keys())),
            seed=args.seed,
            deck0_path=args.d0,
            deck1_path=args.d1,
            use_color=not args.no_color,
            agent0=args.agent0 or "auto",
            agent1=args.agent1 or "auto",
            ml_policy_path=args.ml_policy,
        )
        launcher = LauncherUI(MODES)
        launcher.run(initial=initial)
        return

    if args.gui:
        initial = LauncherConfig(
            mode_key=args.mode or next(iter(MODES.keys())),
            seed=args.seed,
            deck0_path=args.d0,
            deck1_path=args.d1,
            use_color=not args.no_color,
            agent0=args.agent0 or "auto",
            agent1=args.agent1 or "auto",
            ml_policy_path=args.ml_policy,
        )
        try:
            launcher = LauncherGUI(MODES)
        except RuntimeError as exc:
            print(f"Unable to start GUI launcher: {exc}")
            return
        launcher.run(initial=initial)
        return

    if args.no_color:
        config.USE_COLOR = False

    mode_key = args.mode or prompt_mode_selection()

    deck0 = select_deck(args.d0)
    deck1 = select_deck(args.d1)

    if deck0 is None or deck1 is None:
        available = discover_deck_files(config.DEFAULT_DECK_DIR)
        print("\n=== DECK SELECTOR ===")
        if deck0 is None:
            deck0 = prompt_pick_deck("Player 0", available)
        if deck1 is None:
            deck1 = prompt_pick_deck("Player 1", available)

    play_mode = MODES[mode_key]
    play_loop(
        mode=play_mode,
        seed=args.seed,
        deck0=deck0,
        deck1=deck1,
        agent0=args.agent0,
        agent1=args.agent1,
        ml_policy_path=args.ml_policy,
    )


if __name__ == "__main__":
    main()
