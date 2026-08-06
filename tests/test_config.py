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


def test_chart_source_fields_default_to_billboard():
    cfg = load_config()
    hot = cfg.charts["hot-100"]
    assert hot.source == "billboard"
    assert hot.publisher == "Billboard"
    assert hot.strict_match is False


def test_chart_source_fields_parse_from_toml(tmp_path):
    toml = tmp_path / "charts.toml"
    toml.write_text(
        """
[schedule]
start_date = 1976-01-03
weeks_per_run = 3
slots = [["hot-100"]]

[[charts]]
id = "hot-100"
slug = "hot-100"
display_name = "Hot 100"
available_from = 1958-08-04

[[charts]]
id = "oricon-showa"
slug = "oricon-showa"
display_name = "Oricon Weekly Singles (Shōwa)"
available_from = 1976-01-12
available_until = 1989-01-02
source = "oricon"
publisher = "Oricon"
strict_match = true
""",
        encoding="utf-8",
    )
    cfg = load_config(toml)
    o = cfg.charts["oricon-showa"]
    assert o.source == "oricon"
    assert o.publisher == "Oricon"
    assert o.strict_match is True
    assert o.available_until == date(1989, 1, 2)
