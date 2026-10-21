import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from osw import cli, settings
from osw.net import Http, NetError, RateLimited
from osw.queue import DownloadManager, JobState


def test_connections_are_thread_local_and_closed_on_host_switch(monkeypatch):
    connections = []

    def factory(*args, **kwargs):
        obj = Mock()
        connections.append(obj)
        return obj

    monkeypatch.setattr("osw.net.httpc.HTTPSConnection", factory)
    http = Http()
    main = http._connection("one.example")
    with ThreadPoolExecutor(max_workers=1) as pool:
        other = pool.submit(http._connection, "one.example").result()
    assert main is not other
    assert http._connection("one.example") is main
    http._connection("two.example")
    main.close.assert_called_once()


def test_connection_errors_are_retried_and_rate_limits_are_typed(monkeypatch):
    http = Http()
    once = Mock(side_effect=[NetError("connection error", transient=True), b"ok"])
    monkeypatch.setattr(http, "_once", once)
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: self.is_set())
    assert http.request("https://example.test") == b"ok"
    assert once.call_count == 2
    once.side_effect = NetError("HTTP 429", status=429, transient=True)
    once.reset_mock()
    with pytest.raises(RateLimited):
        http.request("https://example.test")
    assert once.call_count == 5


def test_post_encoding_and_cancellation(monkeypatch):
    http = Http()
    once = Mock(return_value=b"{}")
    monkeypatch.setattr(http, "_once", once)
    assert http.json("https://example.test", method="POST", data={"publishedfileids[0]": 123}) == {}
    assert once.call_args.kwargs["body"] == b"publishedfileids%5B0%5D=123"
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        http.request("https://example.test", cancel=cancel)


def test_redirect_limit_and_downgrade_rejection(monkeypatch):
    http = Http()
    response = Mock(status=302)
    response.read.return_value = b""
    response.getheader.side_effect = lambda name: "/loop" if name == "Location" else None
    connection = Mock()
    connection.getresponse.return_value = response
    monkeypatch.setattr(http, "_connection", lambda *args: connection)
    with pytest.raises(NetError, match="too many redirects"):
        http.request("https://example.test")
    response.getheader.side_effect = lambda name: (
        "http://example.test/plain" if name == "Location" else None
    )
    with pytest.raises(NetError, match="HTTPS"):
        http.request("https://example.test")


def test_settings_migrate_passwords_and_validate_types(tmp_path):
    settings.CONFIG_FILE.parent.mkdir()
    settings.CONFIG_FILE.write_text(
        json.dumps(
            {
                "username": "user",
                "password": "old-secret",
                "remember_password": True,
                "parallel_downloads": 4,
                "content_root": 123,
            }
        )
    )
    loaded = settings.load()
    assert "password" not in loaded and "remember_password" not in loaded
    assert loaded["parallel_downloads"] == 3  # clamped to the supported range
    assert isinstance(loaded["content_root"], str)
    settings.save({"content_root": str(tmp_path / "mods"), "password": "new-secret"})
    data = json.loads(settings.CONFIG_FILE.read_text())
    assert "password" not in data and data["username"] == "user"
    if os.name != "nt":  # POSIX permission bits are not meaningful on Windows
        assert settings.CONFIG_FILE.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("stored", ["null", "[]", '"string"', "{broken"])
def test_settings_recover_from_invalid_json_shapes(stored):
    settings.CONFIG_FILE.parent.mkdir()
    settings.CONFIG_FILE.write_text(stored)
    assert settings.load()["parallel_downloads"] == 3


def test_fresh_settings_default_to_three_parallel_downloads():
    assert settings.load()["parallel_downloads"] == 3
    args = cli.build_parser().parse_args(["download", "10", "20"])
    assert cli._build_manager(args).parallel == 3


def test_cli_anonymous_precedence_and_default(monkeypatch):
    monkeypatch.setenv("OSW_PASS", "secret")
    for arguments, expected in [
        (["download", "10", "20"], ""),
        (["download", "10", "20", "--username", "user", "--anonymous"], ""),
        (["download", "10", "20", "--username", "user"], "user"),
    ]:
        args = cli.build_parser().parse_args(arguments)
        manager = cli._build_manager(args)
        assert manager.username == expected
        assert manager.password == ("secret" if expected else "")


def test_cli_parallel_flag_and_settings(monkeypatch):
    args = cli.build_parser().parse_args(["download", "10", "20", "--parallel", "2"])
    assert cli._build_manager(args).parallel == 2

    assert cli.main(["settings", "--parallel", "2"]) == 0
    assert settings.get("parallel_downloads") == 2
    default_args = cli.build_parser().parse_args(["download", "10", "20"])
    assert cli._build_manager(default_args).parallel == 2

    assert cli.main(["settings", "--parallel", "9"]) == 0
    assert settings.get("parallel_downloads") == 3


def test_cli_duplicate_downloads_finish(tmp_path, monkeypatch, capsys):
    manager = DownloadManager(tmp_path)

    class Client:
        def download_item(self, *args, **kwargs):
            return tmp_path / "actual"

    monkeypatch.setattr(manager, "steamcmd", lambda *a: Client())
    monkeypatch.setattr(cli, "_build_manager", lambda args: manager)
    assert cli.main(["download", "10", "20", "20"]) == 0
    assert len(manager.jobs) == 1
    assert manager.jobs[0].state is JobState.DONE
    assert "done" in capsys.readouterr().out


def test_cli_batch_partial_failure_returns_error(tmp_path, monkeypatch):
    from osw.bulk import DownloadResolution, ResolutionIssue
    from osw.models import WorkshopItem

    source = tmp_path / "mods.txt"
    source.write_text("20\nbad")
    resolution = DownloadResolution(
        items=[WorkshopItem(20, appid=10)], issues=[ResolutionIssue("bad", "invalid")]
    )
    resolver = Mock(return_value=resolution)
    monkeypatch.setattr(cli, "resolve_downloads", resolver)
    manager = DownloadManager(tmp_path)

    class Client:
        def download_item(self, *args, **kwargs):
            return tmp_path / "actual"

    monkeypatch.setattr(manager, "steamcmd", lambda *a: Client())
    monkeypatch.setattr(cli, "_build_manager", lambda args: manager)
    assert cli.main(["batch", "--input", str(source), "--with-dependencies"]) == 1
    assert resolver.call_args.args == (["20\nbad"], None, True)


def test_cli_interrupt_stops_manager(tmp_path, monkeypatch):
    manager = DownloadManager(tmp_path)
    monkeypatch.setattr(manager, "ensure_workers", lambda: None)
    monkeypatch.setattr(cli, "_build_manager", lambda args: manager)
    monkeypatch.setattr(cli.time, "sleep", Mock(side_effect=KeyboardInterrupt))
    assert cli.main(["download", "10", "20"]) == 130
    assert manager.jobs[0].state is JobState.INTERRUPTED


def test_cli_batch_requires_input_and_catches_network_errors(monkeypatch):
    assert cli.main(["batch"]) == 1
    monkeypatch.setattr(cli, "search_games", Mock(side_effect=NetError("offline")))
    assert cli.main(["search", "game"]) == 1


def test_cli_skips_installed_items_unless_reinstall(tmp_path, monkeypatch, capsys):
    root = tmp_path / "mods"
    item_dir = root / "steamapps" / "workshop" / "content" / "10" / "20"
    item_dir.mkdir(parents=True)
    (item_dir / "mod.txt").write_text("installed")

    monkeypatch.setattr(
        cli,
        "_build_manager",
        Mock(side_effect=AssertionError("a skipped download must not build the manager")),
    )
    assert cli.main(["download", "10", "20", "--out", str(root)]) == 0
    output = capsys.readouterr().out
    assert "already installed" in output
    assert str(item_dir) in output
    assert "--reinstall" in output


def test_cli_reinstall_flag_queues_installed_items(tmp_path, monkeypatch):
    root = tmp_path / "mods"
    item_dir = root / "steamapps" / "workshop" / "content" / "10" / "20"
    item_dir.mkdir(parents=True)
    (item_dir / "mod.txt").write_text("installed")

    class FakeManager:
        def __init__(self):
            self.items = []

        def add_many(self, items):
            self.items.extend(items)
            return []

        def shutdown(self):
            pass

    manager = FakeManager()
    monkeypatch.setattr(cli, "_build_manager", lambda args: manager)

    assert cli.main(["download", "10", "20", "--out", str(root), "--reinstall"]) == 0
    assert [item.publishedfileid for item in manager.items] == [20]

    from osw.bulk import DownloadResolution
    from osw.models import WorkshopItem

    monkeypatch.setattr(
        cli,
        "resolve_downloads",
        lambda references, hint, dependencies: DownloadResolution(
            items=[WorkshopItem(20, appid=10)]
        ),
    )
    assert cli.main(["batch", "20", "--appid", "10", "--out", str(root), "--reinstall"]) == 0
    assert [item.publishedfileid for item in manager.items] == [20, 20]
