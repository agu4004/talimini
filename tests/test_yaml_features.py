from fabgame.rl.yaml_features import DEFAULT_YAML_EXTRACTOR


def test_yaml_trigger_flags():
    extractor = DEFAULT_YAML_EXTRACTOR
    spec = extractor.spec

    assert "on_block" in spec.triggers
    assert "on_graveyard" in spec.triggers

    on_hit = extractor.features_for_card("Bittering Thorns", 2)
    hit_idx = spec.triggers.index("on_hit")
    assert on_hit.trigger_flags[hit_idx] == 1

    on_declare = extractor.features_for_card("Scar for a Scar", 1)
    declare_idx = spec.triggers.index("on_declare")
    assert on_declare.trigger_flags[declare_idx] == 1

    synthetic_block = extractor._features_from_yaml({"rules": {"effects": [{"when": "on_block"}]}})
    block_idx = spec.triggers.index("on_block")
    assert synthetic_block.trigger_flags[block_idx] == 1

    synthetic_grave = extractor._features_from_yaml({"rules": {"effects": [{"when": "on_graveyard"}]}})
    grave_idx = spec.triggers.index("on_graveyard")
    assert synthetic_grave.trigger_flags[grave_idx] == 1
