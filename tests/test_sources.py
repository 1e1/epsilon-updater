"""Aggregation of available items: local files + user-listed remote URLs + on-disk cache."""

from nwupdater.apps.sources import RemoteCache, aggregate, read_url_list, remote_items


def test_aggregate_local_and_remote(tmp_path):
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "game.nwa").write_bytes(b"x" * 10)
    (apps / "notes.txt").write_text("ignored")
    (apps / "_urls.txt").write_text(
        "# comment\nhttps://example.com/apps/demo.nwa\n\nhttps://example.org/x/other.nwa\n")
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


def test_cache_fetches_once(tmp_path):
    calls = []

    def fetch(u):
        calls.append(u)
        return b"DATA:" + u.encode()

    cache = RemoteCache(tmp_path / "cache")
    a = cache.get("https://example.com/x.nwa", fetch)
    b = cache.get("https://example.com/x.nwa", fetch)
    assert a == b == b"DATA:https://example.com/x.nwa"
    assert calls == ["https://example.com/x.nwa"]  # fetched once, then served from cache
