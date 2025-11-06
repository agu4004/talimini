from __future__ import annotations

import json
import os
import random
import copy
from typing import Any, Dict, List, Optional, Tuple

from .config import DEFAULT_DECK_DIR
from .models import Card
from .io.card_yaml import (
    YAML_AVAILABLE,
    extract_abilities,
    load_card_from_yaml,
    normalize_abilities,
    pitch_to_color,
)

DeckLoadResult = Tuple[List[Card], Dict[str, Any]]
_yaml_hint_emitted = False


def _read_deck_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _emit_yaml_hint_once() -> None:
    global _yaml_hint_emitted
    if _yaml_hint_emitted:
        return
    _yaml_hint_emitted = True
    print("Install pyyaml to use YAML card library")


def hydrate_card_entry(entry: Dict[str, Any]) -> Card:
    name = str(entry.get("name", "Card"))
    color_value = entry.get("color")
    color = str(color_value).lower() if color_value else None

    pitch_value = entry.get("pitch")
    if not color and pitch_value is not None:
        try:
            color = pitch_to_color(int(pitch_value))
        except Exception:
            color = None

    yaml_data = load_card_from_yaml(name, color)
    if yaml_data is None and not YAML_AVAILABLE:
        _emit_yaml_hint_once()

    def _int_value(key: str, default: int) -> int:
        value = entry.get(key)
        if value is not None:
            return int(value)
        if yaml_data and yaml_data.get(key) is not None:
            return int(yaml_data.get(key, default))
        return default

    def _keywords_list() -> List[str]:
        kw = entry.get("keywords")
        if isinstance(kw, list):
            return [str(item) for item in kw]
        if yaml_data:
            ykw = yaml_data.get("keywords")
            if isinstance(ykw, list):
                return [str(item) for item in ykw]
        return []

    numeric_keys = ("cost", "attack", "defense", "pitch")
    missing = [
        key
        for key in numeric_keys
        if entry.get(key) is None and not (yaml_data and yaml_data.get(key) is not None)
    ]
    if missing:
        raise ValueError(
            f"Card '{name}' missing numeric stats ({', '.join(missing)}); cannot hydrate without YAML"
        )

    cost = _int_value("cost", 0)
    attack = _int_value("attack", 0)
    defense = _int_value("defense", 0)
    pitch = _int_value("pitch", 1)

    text_value = entry.get("text")
    if text_value is None and yaml_data:
        text_value = yaml_data.get("text")
    text = str(text_value or "")

    def _abilities_dict() -> Dict[str, List[Dict[str, Any]]]:
        abilities_entry = entry.get("abilities")
        if abilities_entry is not None:
            return normalize_abilities(abilities_entry)
        if yaml_data:
            return extract_abilities(yaml_data)
        return {}

    if yaml_data:
        name = yaml_data.get("name", name)

    return Card(
        name=name,
        cost=cost,
        attack=attack,
        defense=defense,
        pitch=pitch,
        keywords=_keywords_list(),
        text=text,
        abilities=_abilities_dict(),
    )


def load_deck_from_json(path: str) -> DeckLoadResult:
    data = _read_deck_json(path)
    deck: List[Card] = []
    for entry in data.get("cards", []):
        count = int(entry.get("count", 1))
        template = hydrate_card_entry(entry)
        for _ in range(count):
            deck.append(
                Card(
                    name=template.name,
                    cost=template.cost,
                    attack=template.attack,
                    defense=template.defense,
                    pitch=template.pitch,
                    keywords=list(template.keywords),
                    text=template.text,
                    abilities=copy.deepcopy(template.abilities),
                )
            )
    random.shuffle(deck)
    meta = {
        "name": data.get("name"),
        "format": data.get("format"),
        "hero": data.get("hero"),
        "arena": data.get("arena", []),
        "source_urls": data.get("source_urls", []),
    }
    return deck, meta


def get_hero_ability(path: str) -> Optional[str]:
    data = _read_deck_json(path)
    ability = data.get("hero_ability")
    if ability:
        return ability

    hero_entry = data.get("hero")
    if isinstance(hero_entry, dict):
        return hero_entry.get("ability")
    return None


def get_weapon_abilities(path: str) -> Dict[str, str]:
    data = _read_deck_json(path)
    abilities = data.get("weapon_abilities")
    if isinstance(abilities, dict):
        return abilities

    arena_entries = data.get("arena", [])
    results: Dict[str, str] = {}
    for item in arena_entries:
        if isinstance(item, dict):
            name = item.get("name")
            ability = item.get("ability")
            if name and ability:
                results[name] = ability
    return results


def get_card_abilities(path: str) -> Dict[str, str]:
    data = _read_deck_json(path)
    abilities = data.get("card_abilities")
    if isinstance(abilities, dict):
        return abilities

    cards = data.get("cards", [])
    results: Dict[str, str] = {}
    for entry in cards:
        if isinstance(entry, dict):
            name = entry.get("name")
            ability = entry.get("ability")
            if name and ability:
                results[name] = ability
    return results


def discover_deck_files(directory: str = DEFAULT_DECK_DIR) -> List[str]:
    if not os.path.isdir(directory):
        return []
    return [
        os.path.join(directory, filename)
        for filename in sorted(os.listdir(directory))
        if filename.lower().endswith(".json")
    ]


def prompt_pick_deck(player_label: str, discovered: List[str]) -> Optional[DeckLoadResult]:
    print(f"\nCh?n deck cho {player_label}:")
    print("[0] Random deck")
    for i, path in enumerate(discovered, start=1):
        print(f"[{i}] {os.path.basename(path)}")
    print("[C] Custom path.")
    selection = input("Your choice [0/1/2/./C]: ").strip().lower()

    if selection in ("", "0", "r"):
        return None
    if selection == "c":
        path = input("Nh?p du?ng d?n file JSON: ").strip()
        if os.path.isfile(path):
            try:
                return load_deck_from_json(path)
            except Exception as exc:
                print(f"   L?i d?c deck: {exc}. D�ng Random.")
                return None
        print("   Kh�ng th?y file. D�ng Random.")
        return None
    try:
        index = int(selection)
        if 1 <= index <= len(discovered):
            return load_deck_from_json(discovered[index - 1])
    except Exception:
        pass
    print("   L?a ch?n kh�ng h?p l?. D�ng Random.")
    return None


__all__ = [
    "DeckLoadResult",
    "load_deck_from_json",
    "hydrate_card_entry",
    "get_hero_ability",
    "get_weapon_abilities",
    "get_card_abilities",
    "discover_deck_files",
    "prompt_pick_deck",
]
