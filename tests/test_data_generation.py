from types import SimpleNamespace

from scripts.gen_selfplay_data import generate_dataset


def test_generate_dataset_single_game(tmp_path):
    args = SimpleNamespace(
        games=1,
        seed=7,
        deck_pool=None,
        rules_version="standard",
        max_pass_streak=12,
        max_no_damage=20,
        output=str(tmp_path / "unused.npz"),
    )
    dataset = generate_dataset(args)
    transition_count = dataset["chosen_action"].shape[0]
    assert transition_count > 0
    for key, value in dataset.items():
        if key.startswith("obs__"):
            assert value.shape[0] == transition_count
