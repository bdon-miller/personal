from datetime import date

from fiftyfm.state import State, load_state, run_key, save_state


def test_load_missing_returns_default(tmp_path):
    st = load_state(tmp_path / "state.json", default_cursor=date(1976, 1, 3))
    assert st.cursor == date(1976, 1, 3)
    assert st.wildcard_index == 0
    assert st.completed == {}


def test_roundtrip(tmp_path):
    path = tmp_path / "deep" / "state.json"
    st = State(cursor=date(1976, 1, 24), wildcard_index=2, completed={})
    st.completed[run_key("hot-100", date(1976, 1, 3))] = {
        "playlist_url": "https://open.spotify.com/playlist/x",
        "posted": True,
    }
    save_state(path, st)
    loaded = load_state(path, default_cursor=date(1976, 1, 3))
    assert loaded == st


def test_run_key():
    assert run_key("soul", date(1976, 2, 7)) == "soul@1976-02-07"


def test_last_posted_key_round_trips(tmp_path):
    path = tmp_path / "state.json"
    state = load_state(path, default_cursor=date(1976, 1, 3))
    assert state.last_posted_key is None
    state.last_posted_key = "hot-100@1976-01-03"
    save_state(path, state)
    assert load_state(path, default_cursor=date(1976, 1, 3)).last_posted_key == (
        "hot-100@1976-01-03"
    )


def test_last_posted_key_absent_in_legacy_state_file(tmp_path):
    # State files written before polls existed have no such key.
    path = tmp_path / "state.json"
    path.write_text('{"cursor": "1976-01-03", "wildcard_index": 0, "completed": {}}')
    assert load_state(path, default_cursor=date(1976, 1, 3)).last_posted_key is None


def test_save_state_leaves_no_shared_tmp_file_behind(tmp_path):
    # Two writers (the chart run and the poll run) must never share a temp
    # path, or interleaved writes can publish truncated/mixed JSON.
    path = tmp_path / "state.json"
    state = State(cursor=date(1976, 1, 3))
    save_state(path, state)
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []
    assert not (tmp_path / "state.tmp").exists()


def test_save_state_survives_a_stale_tmp_file_from_another_process(tmp_path):
    # A crashed or concurrent writer's stale bare state.tmp must not block
    # (or get clobbered incorrectly by) this process's own save.
    path = tmp_path / "state.json"
    (tmp_path / "state.tmp").write_text("garbage from another process")
    state = State(cursor=date(1976, 1, 3))
    save_state(path, state)
    assert load_state(path, default_cursor=date(1976, 1, 3)) == state
    # The stale file is untouched - it belongs to whatever process left it.
    assert (tmp_path / "state.tmp").read_text() == "garbage from another process"
