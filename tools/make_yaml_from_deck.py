from __future__ import annotations

import argparse
import json
from json import dumps as json_dumps
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from fabgame.io.card_yaml import card_yaml_path, pitch_to_color, slugify


def _derive_color(entry: Dict) -> Optional[str]:
    color = entry.get("color")
    if isinstance(color, str) and color:
        return color.lower()
    pitch = entry.get("pitch")
    if pitch is not None:
        try:
            inferred = pitch_to_color(int(pitch))
            if inferred:
                return inferred.lower()
        except Exception:
            return None
    return None


def _card_fields(entry: Dict) -> Tuple[str, int, int, int, int, str, str, Iterable[str]]:
    name = str(entry.get("name", "Card"))
    cost = int(entry.get("cost", 0) or 0)
    attack = int(entry.get("attack", 0) or 0)
    defense = int(entry.get("defense", 0) or 0)
    pitch = int(entry.get("pitch", 1) or 1)
    klass = str(entry.get("class", "Unknown") or "Unknown")
    card_type = str(entry.get("type", "attack") or "attack")
    keywords = entry.get("keywords", [])
    if not isinstance(keywords, Iterable) or isinstance(keywords, (str, bytes)):
        keywords = []
    return name, cost, attack, defense, pitch, klass, card_type, keywords


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate YAML stubs from a deck JSON.")
    parser.add_argument("--deck", required=True, help="Path to deck JSON file.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing YAML files.")
    args = parser.parse_args()

    deck_path = Path(args.deck)
    if not deck_path.is_file():
        raise SystemExit(f"Deck file not found: {deck_path}")

    data = json.loads(deck_path.read_text(encoding="utf-8"))
    cards = data.get("cards", [])
    if not isinstance(cards, list):
        raise SystemExit("Deck JSON missing 'cards' list.")

    seen = set()
    for entry in cards:
        if not isinstance(entry, dict):
            continue
        color = _derive_color(entry)
        name, cost, attack, defense, pitch, klass, card_type, keywords = _card_fields(entry)
        if not color:
            print(f"Skip {name}: missing color and unable to infer from pitch.")
            continue
        slug = slugify(name)
        key = (slug, color)
        if key in seen:
            continue
        seen.add(key)
        yaml_path = Path(card_yaml_path(name, color))
        if yaml_path.exists() and not args.force:
            print(f"SKIP {yaml_path} (exists)")
            continue

        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        record_id = f"{slug}_{color}"
        lines = [
            f"id: {json_dumps(record_id)}",
            f"name: {json_dumps(name)}",
            f"color: {json_dumps(color)}",
            f"class: {json_dumps(klass)}",
            f"type: {json_dumps(card_type)}",
            f"cost: {cost}",
            f"attack: {attack}",
            f"defense: {defense}",
            f"pitch: {pitch}",
            f"text: {json_dumps(str(entry.get('text', '')))}",
            f"keywords: {json_dumps(list(keywords))}",
            "modifiers:",
            "  on_declare: []",
        ]
        yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote {yaml_path}")


if __name__ == "__main__":
    main()

