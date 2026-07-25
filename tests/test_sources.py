"""Aggregation of available items: local files + user-listed remote URLs."""

from nwupdater.apps.sources import aggregate, read_url_list, remote_items


def test_aggregate_local_and_remote(tmp_path):
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "game.nwa").write_bytes(b"x" * 10)
    (apps / "notes.txt").write_text("ignored")
    (apps / "_urls.txt").write_text(
        "# comment\nhttps://example.com/apps/demo.nwa\n\nhttps://example.org/x/other.nwa\n"
    )
    items = aggregate(apps, [".nwa"])
    names = [i.name for i in items]
    assert "game.nwa" in names and "demo.nwa" in names and "other.nwa" in names
    assert "notes.txt" not in names  # extension filter
    local = [i for i in items if i.origin == "local"]
    assert local and local[0].size == 10


def test_url_list_parsing(tmp_path):
    f = tmp_path / "_urls.txt"
    f.write_text("# header\n\nhttps://a.example/one.nwa\nhttps://b.example/two.nwa\n")
    assert read_url_list(f) == ["https://a.example/one.nwa", "https://b.example/two.nwa"]
    assert [i.name for i in remote_items(read_url_list(f), [".nwa"])] == ["one.nwa", "two.nwa"]


def test_user_apps_dir_env_override(tmp_path, monkeypatch):
    from nwupdater.apps.sources import user_apps_dir

    monkeypatch.setenv("NWUPDATER_APPS_DIR", str(tmp_path / "custom"))
    assert user_apps_dir() == tmp_path / "custom"


def test_app_entries_from_user_dir(tmp_path):
    from nwupdater.apps.sources import app_entries
    from nwupdater.formats.nwa import build_nwa

    d = tmp_path / "apps"
    d.mkdir()
    (d / "MyGame.nwa").write_bytes(build_nwa("MyGame", api_level=0, code=b"\x00" * 64))
    (d / "_urls.txt").write_text("https://host.example/pub/cool.nwa\n# comment\n")
    by_name = {e.name: e for e in app_entries(d)}
    # local .nwa: name comes from the parsed header, real bytes are addressable via local_path
    assert "MyGame" in by_name
    assert by_name["MyGame"].local_path.endswith("MyGame.nwa")
    assert by_name["MyGame"].url == "" and by_name["MyGame"].api_level == 0
    # remote url: added as a downloadable entry, host surfaced as the source
    assert by_name["cool.nwa"].url == "https://host.example/pub/cool.nwa"
    assert by_name["cool.nwa"].source == "host.example"


def test_app_entries_empty_when_dir_absent(tmp_path):
    from nwupdater.apps.sources import app_entries

    assert app_entries(tmp_path / "does-not-exist") == []
