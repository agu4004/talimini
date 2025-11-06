from __future__ import annotations

import io
import os
import queue
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import config
from .deck import DeckLoadResult, discover_deck_files, load_deck_from_json
from .ui import play_loop


DEFAULT_MODES: Dict[str, str] = {
    "hh": "human-vs-human",
    "hb": "human-vs-bot",
    "bh": "bot-vs-human",
    "bb": "bot-vs-bot",
    "mb": "ml-vs-bot",
    "bm": "bot-vs-ml",
    "mm": "ml-vs-ml",
    "hm": "human-vs-ml",
    "mh": "ml-vs-human",
}



@dataclass
class LauncherConfig:
    mode_key: str
    seed: int
    deck0_path: Optional[str]
    deck1_path: Optional[str]
    use_color: bool
    agent0: str = "auto"
    agent1: str = "auto"
    ml_policy_path: Optional[str] = None


class _QueueWriter(io.TextIOBase):
    """Redirects writes into a thread-safe queue for GUI consumption."""

    def __init__(self, output_queue: "queue.Queue[str]") -> None:
        super().__init__()
        self._queue = output_queue

    def write(self, data: str) -> int:  # type: ignore[override]
        if data:
            self._queue.put(data)
        return len(data)

    def writelines(self, lines: List[str]) -> None:  # type: ignore[override]
        for line in lines:
            self.write(line)

    def flush(self) -> None:  # type: ignore[override]
        # No-op: the queue flushes writes immediately.
        return


class _QueueReader(io.TextIOBase):
    """Provides blocking readline() backed by a queue for GUI input."""

    def __init__(self, input_queue: "queue.Queue[Optional[str]]", stop_event: threading.Event) -> None:
        super().__init__()
        self._queue = input_queue
        self._stop_event = stop_event

    def readable(self) -> bool:  # type: ignore[override]
        return True

    def readline(self, size: int = -1) -> str:  # type: ignore[override]
        while True:
            if self._stop_event.is_set():
                raise EOFError
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                raise EOFError
            return item

    def close(self) -> None:  # type: ignore[override]
        self._stop_event.set()
        super().close()

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return "utf-8"


@contextmanager
def _redirect_stdio(stdin: io.TextIOBase, stdout: io.TextIOBase) -> None:
    """Context manager to temporarily redirect stdin/stdout/stderr."""

    old_stdin = sys.stdin
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdin = stdin
    sys.stdout = stdout
    sys.stderr = stdout
    try:
        yield
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        sys.stderr = old_stderr


class LauncherUI:
    """Simple text-based front-end for configuring and launching a match."""

    def __init__(self, modes: Dict[str, str], deck_directory: Optional[str] = None) -> None:
        self.modes = modes
        self.deck_directory = deck_directory or config.DEFAULT_DECK_DIR
        self.deck_cache: List[str] = []
        self._refresh_decks()

    def run(self, initial: Optional[LauncherConfig] = None) -> None:
        config_state = initial or LauncherConfig(
            mode_key=self._default_mode_key(),
            seed=11,
            deck0_path=None,
            deck1_path=None,
            use_color=config.USE_COLOR,
        )

        while True:
            self._print_header()
            self._print_configuration(config_state)
            print("\nOptions:")
            print("  [1] Change game mode")
            print("  [2] Select deck for Player 0")
            print("  [3] Select deck for Player 1")
            print("  [4] Set random seed")
            print("  [5] Toggle ANSI color")
            print("  [6] Refresh deck list")
            print("  [7] Start match")
            print("  [Q] Quit")
            choice = input("Select option: ").strip().lower()

            if choice == "1":
                config_state.mode_key = self._pick_mode(config_state.mode_key)
            elif choice == "2":
                config_state.deck0_path = self._pick_deck("Player 0", config_state.deck0_path)
            elif choice == "3":
                config_state.deck1_path = self._pick_deck("Player 1", config_state.deck1_path)
            elif choice == "4":
                config_state.seed = self._prompt_seed(config_state.seed)
            elif choice == "5":
                config_state.use_color = not config_state.use_color
                print(f"ANSI color {'enabled' if config_state.use_color else 'disabled'}.")
            elif choice == "6":
                self._refresh_decks()
            elif choice == "7":
                if self._start_match(config_state):
                    if not self._prompt_play_again():
                        break
                else:
                    input("Press Enter to return to the menu...")
            elif choice in ("q", "quit", "exit"):
                break
            else:
                print("Unrecognized option.")

    def _default_mode_key(self) -> str:
        return next(iter(self.modes.keys()))

    def _print_header(self) -> None:
        os.system("cls" if os.name == "nt" else "clear")
        print("=" * 60)
        print(" FABGAME :: SIMPLE LAUNCHER ".center(60, "="))
        print("=" * 60)

    def _print_configuration(self, config_state: LauncherConfig) -> None:
        mode_label = self.modes.get(config_state.mode_key, config_state.mode_key)
        print("Current configuration:")
        print(f"  Mode        : {mode_label} ({config_state.mode_key})")
        print(f"  Seed        : {config_state.seed}")
        print(f"  Player 0 deck: {self._sig_for_path(config_state.deck0_path)}")
        print(f"  Player 1 deck: {self._sig_for_path(config_state.deck1_path)}")
        print(f"  ANSI color  : {'On' if config_state.use_color else 'Off'}")

    def _sig_for_path(self, path: Optional[str]) -> str:
        if path is None:
            return "Random (engine-generated)"
        return os.path.basename(path)

    def _pick_mode(self, current_key: str) -> str:
        print("\nAvailable modes:")
        for idx, (key, label) in enumerate(self.modes.items(), start=1):
            marker = "*" if key == current_key else " "
            print(f"  [{idx}] {label} ({key}) {marker}")
        selection = input("Choose mode (number): ").strip()
        if selection.isdigit():
            idx = int(selection) - 1
            if 0 <= idx < len(self.modes):
                chosen_key = list(self.modes.keys())[idx]
                print(f"Selected mode: {self.modes[chosen_key]} ({chosen_key})")
                return chosen_key
        print("Mode unchanged.")
        return current_key

    def _pick_deck(self, player_label: str, current_path: Optional[str]) -> Optional[str]:
        if not self.deck_cache:
            print("No deck files found. Using random deck.")
            return None
        print(f"\nDecks available for {player_label}:")
        print("  [0] Random deck (engine generated)")
        for idx, path in enumerate(self.deck_cache, start=1):
            marker = "*" if path == current_path else " "
            print(f"  [{idx}] {os.path.basename(path)} {marker}")
        choice = input("Select deck (number): ").strip()
        if not choice:
            print("Deck selection cancelled.")
            return current_path
        if choice == "0":
            print(f"{player_label} will use a random deck.")
            return None
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(self.deck_cache):
                selected_path = self.deck_cache[idx]
                print(f"{player_label} deck set to {os.path.basename(selected_path)}")
                return selected_path
        print("Invalid selection; keeping previous deck.")
        return current_path

    def _prompt_seed(self, current_seed: int) -> int:
        entry = input(f"Enter random seed [{current_seed}]: ").strip()
        if not entry:
            return current_seed
        try:
            return int(entry)
        except ValueError:
            print("Seed must be an integer. Keeping previous value.")
            return current_seed

    def _refresh_decks(self) -> None:
        self.deck_cache = discover_deck_files(self.deck_directory)
        if not self.deck_cache:
            print("No deck files detected. Random decks will be used by default.")

    def _load_deck(self, path: Optional[str]) -> Optional[DeckLoadResult]:
        if path is None:
            return None
        try:
            return load_deck_from_json(path)
        except Exception as exc:
            print(f"Failed to load deck '{path}': {exc}")
            return None

    def _start_match(self, config_state: LauncherConfig) -> bool:
        deck0 = self._load_deck(config_state.deck0_path)
        deck1 = self._load_deck(config_state.deck1_path)
        if config_state.deck0_path and deck0 is None:
            print("Player 0 deck could not be loaded. Fix the issue or choose another deck.")
            return False
        if config_state.deck1_path and deck1 is None:
            print("Player 1 deck could not be loaded. Fix the issue or choose another deck.")
            return False

        config.USE_COLOR = config_state.use_color
        print("\nLaunching match... (Ctrl+C to abort)\n")
        play_loop(
            mode=self.modes.get(config_state.mode_key, config_state.mode_key),
            seed=config_state.seed,
            deck0=deck0,
            deck1=deck1,
        )
        return True

    def _prompt_play_again(self) -> bool:
        choice = input("\nStart another match? [y/N]: ").strip().lower()
        return choice.startswith("y")


class LauncherGUI:
    """Tkinter-based launcher window that wraps the existing text UI."""

    RANDOM_LABEL = "Random (engine-generated)"

    def __init__(
        self,
        modes: Dict[str, str],
        deck_directory: Optional[str] = None,
        *,
        master: Optional[object] = None,
    ) -> None:
        try:
            import tkinter as tk  # type: ignore
            from tkinter import messagebox, ttk  # type: ignore
        except Exception as exc:
            raise RuntimeError("Tkinter is required for the graphical launcher.") from exc

        self._tk = tk
        self._ttk = ttk
        self._messagebox = messagebox

        self.modes = modes
        self.deck_directory = deck_directory or config.DEFAULT_DECK_DIR

        self.root = master or tk.Tk()
        self.root.title("FabGame Launcher")

        self.deck_cache: List[str] = []
        self._deck_label_to_path: Dict[str, str] = {}
        self._deck_path_to_label: Dict[str, str] = {}

        self.output_queue: "queue.Queue[str]" = queue.Queue()
        self.input_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stop_event = threading.Event()
        self._match_running = False
        self._match_thread: Optional[threading.Thread] = None

        self._mode_label_to_key: Dict[str, str] = {}

        self._build_ui()
        self._refresh_decks()
        self._poll_output()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction helpers
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        tk = self._tk
        ttk = self._ttk

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        for column in range(2):
            main.columnconfigure(column, weight=(1 if column == 1 else 0))
        main.rowconfigure(5, weight=1)

        # Mode selector
        ttk.Label(main, text="Game mode:").grid(row=0, column=0, sticky="w")
        mode_display_values = [self._format_mode_label(k, v) for k, v in self.modes.items()]
        self._mode_label_to_key = {self._format_mode_label(k, v): k for k, v in self.modes.items()}
        self.mode_var = tk.StringVar(value=mode_display_values[0] if mode_display_values else "")
        self.mode_combo = ttk.Combobox(
            main,
            textvariable=self.mode_var,
            state="readonly",
            values=mode_display_values,
        )
        self.mode_combo.grid(row=0, column=1, sticky="ew", pady=(0, 6))

        # Seed entry
        ttk.Label(main, text="Random seed:").grid(row=1, column=0, sticky="w")
        self.seed_var = tk.StringVar(value="11")
        self.seed_entry = ttk.Entry(main, textvariable=self.seed_var)
        self.seed_entry.grid(row=1, column=1, sticky="ew", pady=(0, 6))

        # ANSI color toggle
        self.use_color_var = tk.BooleanVar(value=config.USE_COLOR)
        self.color_check = ttk.Checkbutton(
            main,
            text="Use ANSI color output",
            variable=self.use_color_var,
        )
        self.color_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Deck selection
        decks_frame = ttk.LabelFrame(main, text="Deck selection")
        decks_frame.grid(row=3, column=0, columnspan=2, sticky="nsew")
        decks_frame.columnconfigure(1, weight=1)

        ttk.Label(decks_frame, text="Player 0 deck:").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=(2, 4))
        ttk.Label(decks_frame, text="Player 1 deck:").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(0, 2))
        self.deck0_var = tk.StringVar(value=self.RANDOM_LABEL)
        self.deck1_var = tk.StringVar(value=self.RANDOM_LABEL)
        self.deck0_combo = ttk.Combobox(decks_frame, textvariable=self.deck0_var, state="readonly")
        self.deck1_combo = ttk.Combobox(decks_frame, textvariable=self.deck1_var, state="readonly")
        self.deck0_combo.grid(row=0, column=1, sticky="ew", pady=(2, 4))
        self.deck1_combo.grid(row=1, column=1, sticky="ew", pady=(0, 6))

        refresh_button = ttk.Button(decks_frame, text="Refresh deck list", command=self._refresh_decks)
        refresh_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        # Control buttons
        control_frame = ttk.Frame(main)
        control_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        control_frame.columnconfigure(0, weight=1)
        control_frame.columnconfigure(1, weight=1)

        self.start_button = ttk.Button(control_frame, text="Start match", command=self._on_start_match)
        self.stop_button = ttk.Button(control_frame, text="Abort match", command=self._on_abort_match, state="disabled")
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        # Output log
        log_frame = ttk.LabelFrame(main, text="Match log")
        log_frame.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.output_text = tk.Text(
            log_frame,
            state="disabled",
            wrap="word",
            height=20,
            font=("TkFixedFont", 9),
        )
        self.output_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.output_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.output_text.configure(yscrollcommand=scrollbar.set)

        # Input entry
        input_frame = ttk.Frame(main)
        input_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        input_frame.columnconfigure(0, weight=1)
        self.input_var = tk.StringVar()
        self.input_entry = ttk.Entry(input_frame, textvariable=self.input_var, state="disabled")
        self.input_entry.grid(row=0, column=0, sticky="ew")
        self.input_entry.bind("<Return>", self._on_submit_input)
        self.send_button = ttk.Button(input_frame, text="Send", command=self._on_send_input, state="disabled")
        self.send_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def run(self, initial: Optional[LauncherConfig] = None) -> None:
        config_state = initial or LauncherConfig(
            mode_key=self._default_mode_key(),
            seed=11,
            deck0_path=None,
            deck1_path=None,
            use_color=config.USE_COLOR,
        )
        self._apply_initial_config(config_state)
        self.root.mainloop()

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def _format_mode_label(self, key: str, label: str) -> str:
        return f"{label} ({key})"

    def _default_mode_key(self) -> str:
        return next(iter(self.modes.keys()))

    def _apply_initial_config(self, config_state: LauncherConfig) -> None:
        mode_label = self._mode_label_for_key(config_state.mode_key)
        if mode_label:
            self.mode_var.set(mode_label)
        self.seed_var.set(str(config_state.seed))
        self.use_color_var.set(config_state.use_color)
        self._restore_deck_selection(self.deck0_var, config_state.deck0_path)
        self._restore_deck_selection(self.deck1_var, config_state.deck1_path)

    def _mode_label_for_key(self, key: str) -> Optional[str]:
        for label, mapped_key in self._mode_label_to_key.items():
            if mapped_key == key:
                return label
        return None

    def _restore_deck_selection(self, var: "object", path: Optional[str]) -> None:
        label = self.RANDOM_LABEL
        if path:
            normalized = os.path.normpath(os.path.abspath(path))
            label = self._deck_path_to_label.get(normalized, self.RANDOM_LABEL)
        var.set(label)

    # ------------------------------------------------------------------
    # Deck management
    # ------------------------------------------------------------------
    def _refresh_decks(self) -> None:
        self.deck_cache = discover_deck_files(self.deck_directory)

        label_to_path: Dict[str, str] = {}
        path_to_label: Dict[str, str] = {}
        for raw_path in self.deck_cache:
            absolute = os.path.normpath(os.path.abspath(raw_path))
            relative = os.path.relpath(absolute, self.deck_directory)
            label = relative.replace("\\", "/")
            label_to_path[label] = absolute
            path_to_label[absolute] = label

        self._deck_label_to_path = label_to_path
        self._deck_path_to_label = path_to_label

        options = [self.RANDOM_LABEL] + list(label_to_path.keys())
        self.deck0_combo.configure(values=options)
        self.deck1_combo.configure(values=options)
        if self.deck0_var.get() not in options:
            self.deck0_var.set(self.RANDOM_LABEL)
        if self.deck1_var.get() not in options:
            self.deck1_var.set(self.RANDOM_LABEL)

        if not self.deck_cache:
            self._append_output("No deck files detected. Random decks will be used by default.\n")

    def _selected_deck_path(self, selection: str) -> Optional[str]:
        if selection == self.RANDOM_LABEL or not selection:
            return None
        return self._deck_label_to_path.get(selection)

    def _load_deck_safely(self, path: Optional[str], label: str) -> Optional[DeckLoadResult]:
        if path is None:
            return None
        try:
            return load_deck_from_json(path)
        except Exception as exc:
            self._messagebox.showerror("Deck load failed", f"Failed to load deck for {label}:\n{exc}")
            raise RuntimeError("Deck load failed") from exc

    # ------------------------------------------------------------------
    # Match control
    # ------------------------------------------------------------------
    def _on_start_match(self) -> None:
        if self._match_running:
            return

        seed_text = self.seed_var.get().strip() or "11"
        try:
            seed = int(seed_text)
        except ValueError:
            self._messagebox.showerror("Invalid seed", "Seed must be an integer.")
            self.seed_entry.focus_set()
            return

        mode_label = self.mode_var.get()
        mode_key = self._mode_label_to_key.get(mode_label, self._default_mode_key())

        deck0_path = self._selected_deck_path(self.deck0_var.get())
        deck1_path = self._selected_deck_path(self.deck1_var.get())

        try:
            deck0 = self._load_deck_safely(deck0_path, "Player 0")
            deck1 = self._load_deck_safely(deck1_path, "Player 1")
        except RuntimeError:
            return

        # Prepare fresh queues for this run.
        self.output_queue = queue.Queue()
        self.input_queue = queue.Queue()
        self._stop_event = threading.Event()

        # Update UI state.
        self._match_running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.input_entry.configure(state="normal")
        self.send_button.configure(state="normal")
        self.input_entry.focus_set()
        self._append_output("\n=== Launching match... ===\n")

        config_state = LauncherConfig(
            mode_key=mode_key,
            seed=seed,
            deck0_path=deck0_path,
            deck1_path=deck1_path,
            use_color=self.use_color_var.get(),
        )

        self._match_thread = threading.Thread(
            target=self._run_match_thread,
            args=(config_state, deck0, deck1),
            daemon=True,
        )
        self._match_thread.start()

    def _on_abort_match(self) -> None:
        if not self._match_running:
            return
        self._append_output("\n[Abort requested]\n")
        self._stop_event.set()
        self.input_queue.put(None)

    def _run_match_thread(
        self,
        config_state: LauncherConfig,
        deck0: Optional[DeckLoadResult],
        deck1: Optional[DeckLoadResult],
    ) -> None:
        output_stream = _QueueWriter(self.output_queue)
        input_stream = _QueueReader(self.input_queue, self._stop_event)

        previous_use_color = config.USE_COLOR
        try:
            with _redirect_stdio(input_stream, output_stream):
                config.USE_COLOR = config_state.use_color
                try:
                    play_loop(
                        mode=self.modes.get(config_state.mode_key, config_state.mode_key),
                        seed=config_state.seed,
                        deck0=deck0,
                        deck1=deck1,
                        agent0=config_state.agent0,
                        agent1=config_state.agent1,
                        ml_policy_path=config_state.ml_policy_path,
                    )
                except EOFError:
                    print("\nMatch aborted by user.\n")
                except Exception as exc:
                    print(f"\nAn unexpected error occurred: {exc}\n")
        finally:
            config.USE_COLOR = previous_use_color
            self._stop_event.set()
            self.root.after(0, self._on_match_thread_complete)

    def _on_match_thread_complete(self) -> None:
        self._match_running = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.input_entry.configure(state="disabled")
        self.send_button.configure(state="disabled")
        self.input_var.set("")
        self._match_thread = None

    # ------------------------------------------------------------------
    # Output & input wiring
    # ------------------------------------------------------------------
    def _poll_output(self) -> None:
        try:
            while True:
                chunk = self.output_queue.get_nowait()
                self._append_output(chunk)
        except queue.Empty:
            pass
        finally:
            try:
                self.root.after(50, self._poll_output)
            except self._tk.TclError:
                return

    def _append_output(self, text: str) -> None:
        if not text:
            return
        self.output_text.configure(state="normal")
        self.output_text.insert("end", text)
        self.output_text.see("end")
        self.output_text.configure(state="disabled")

    def _on_submit_input(self, event: object) -> str:
        self._on_send_input()
        return "break"

    def _on_send_input(self) -> None:
        if not self._match_running:
            return
        text = self.input_var.get()
        self.input_var.set("")
        if text:
            self._append_output(f"> {text}\n")
        self.input_queue.put((text or "") + "\n")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        if self._match_running:
            self._on_abort_match()
            self.root.after(200, self._await_thread_before_close)
        else:
            self.root.destroy()

    def _await_thread_before_close(self) -> None:
        if self._match_thread and self._match_thread.is_alive():
            self.root.after(200, self._await_thread_before_close)
            return
        self.root.destroy()


def run_gui_launcher(initial: Optional[LauncherConfig] = None) -> None:
    launcher = LauncherGUI(DEFAULT_MODES)
    launcher.run(initial=initial)


if __name__ == "__main__":
    run_gui_launcher()
