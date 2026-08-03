from datetime import date

from fiftyfm.cli import main
from fiftyfm.state import load_state


def test_set_cursor_snaps_to_saturday(tmp_path, monkeypatch, capsys):
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FIFTYFM_STATE_PATH", str(state_path))
    assert main(["set-cursor", "1981-03-19"]) == 0  # a Thursday
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    assert st.cursor == date(1981, 3, 21)
    assert "1981-03-21" in capsys.readouterr().out


def test_status_prints_cursor(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FIFTYFM_STATE_PATH", str(tmp_path / "state.json"))
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "1976-01-03" in out  # default cursor from packaged config


def test_run_requires_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FIFTYFM_STATE_PATH", str(tmp_path / "state.json"))
    for var in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET",
                "SPOTIFY_REFRESH_TOKEN", "DISCORD_WEBHOOK_URL"):
        monkeypatch.delenv(var, raising=False)
    assert main(["run"]) == 2
    assert "missing" in capsys.readouterr().err.lower()
