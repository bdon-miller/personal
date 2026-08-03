from datetime import date
from fiftyfm.config import load_config


def test_load_packaged_config():
    cfg = load_config()
    assert cfg.start_date == date(1976, 1, 3)
    assert cfg.weeks_per_run == 3
    assert cfg.slots[0] == ["hot-100"]
    assert cfg.slots[1] == ["mainstream-rock", "soul"]
    assert cfg.slots[2] == ["rap", "soul", "country"]
    hot = cfg.charts["hot-100"]
    assert hot.slug == "hot-100"
    assert hot.display_name == "Hot 100"
    assert hot.available_from == date(1958, 8, 4)
    assert hot.available_until is None
    disco = cfg.charts["disco"]
    assert disco.available_from == date(1976, 8, 28)
    assert disco.available_until == date(2020, 3, 28)
    assert list(cfg.charts) == [
        "hot-100", "soul", "country", "easy-listening", "disco",
        "mainstream-rock", "latin", "modern-rock", "rap", "pop",
        "adult-top-40", "hot-rock", "dance-electronic", "global-200",
    ]
