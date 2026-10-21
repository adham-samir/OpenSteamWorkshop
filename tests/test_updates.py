"""Workshop revision tracking and update checks."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import Mock

from osw import installed
from osw.delivery import deliver_item, read_marker
from osw.gui.state import AppState
from osw.installed import (
    UNAVAILABLE,
    UNKNOWN,
    UP_TO_DATE,
    UPDATE_AVAILABLE,
    InstalledItem,
    check_updates,
    content_dir,
    read_acf_updates,
    scan_installed,
)

ACF = """\"AppWorkshop\"
{
\t\"appid\"\t\t\"4000\"
\t\"WorkshopItemsInstalled\"
\t{
\t\t\"100\"
\t\t{
\t\t\t\"size\"\t\t\"10\"
\t\t\t\"timeupdated\"\t\t\"1700000000\"
\t\t}
\t\t\"101\"
\t\t{
\t\t\t\"size\"\t\t\"20\"
\t\t\t\"timeupdated\"\t\t\"1700100000\"
\t\t}
\t}
}
"""


def _staged(root, appid, fileid):
    path = content_dir(root) / str(appid) / str(fileid)
    path.mkdir(parents=True)
    (path / "mod.txt").write_text("installed")
    return path


def _write_acf(root, appid, text=ACF):
    path = installed.acf_path(root, appid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_read_acf_updates_maps_exact_revisions(tmp_path):
    root = tmp_path / "mods"
    _write_acf(root, 4000)

    assert read_acf_updates(root, 4000) == {100: 1700000000, 101: 1700100000}
    assert read_acf_updates(root, 9999) == {}


def test_read_acf_updates_tolerates_missing_and_malformed(tmp_path):
    root = tmp_path / "mods"
    assert read_acf_updates(root, 4000) == {}

    _write_acf(root, 4000, "this is not keyvalues")
    assert read_acf_updates(root, 4000) == {}

    _write_acf(root, 4000, '"AppWorkshop" { "WorkshopItemsInstalled" { "bad" { } } }')
    assert read_acf_updates(root, 4000) == {}


def test_scan_uses_acf_and_marker_revisions(tmp_path):
    root = tmp_path / "mods"
    staged = _staged(root, 4000, 100)
    _write_acf(root, 4000)

    game_mods = tmp_path / "RimWorld" / "Mods"
    delivered = game_mods / "Delivered mod"
    delivered.mkdir(parents=True)
    marker = {"appid": 4000, "fileid": 200, "title": "Delivered mod", "delivered": "2024-01-02"}
    marker["updated"] = 1700200000
    (delivered / ".opensteamworkshop.json").write_text(json.dumps(marker))

    items = {item.fileid: item for item in scan_installed(root, game_paths={4000: game_mods})}
    assert items[100].path == staged
    assert items[100].updated == 1700000000
    assert items[100].updated_label == "2023-11-14"
    assert items[200].delivered is True
    assert items[200].updated == 1700200000


def test_legacy_marker_falls_back_to_delivery_day(tmp_path):
    game_mods = tmp_path / "Mods"
    delivered = game_mods / "Legacy"
    delivered.mkdir(parents=True)
    (delivered / ".opensteamworkshop.json").write_text(
        json.dumps({"appid": 1, "fileid": 2, "title": "Legacy", "delivered": "2024-01-02"})
    )

    items = scan_installed(tmp_path / "empty-root", game_paths={1: game_mods})
    hit = next(item for item in items if item.fileid == 2)
    assert hit.updated > 0
    assert hit.updated_label == "2024-01-02"


def test_check_updates_reports_every_state(monkeypatch, tmp_path):
    items = [
        InstalledItem(10, 1, tmp_path / "1", updated=1000, title="One"),
        InstalledItem(10, 2, tmp_path / "2", updated=2000, title="Two"),
        InstalledItem(10, 3, tmp_path / "3", updated=0, title="Three"),
        InstalledItem(10, 4, tmp_path / "4", updated=1000, title="Four"),
    ]
    rows = {
        1: {"result": 1, "time_updated": 2000, "title": "One"},
        2: {"result": 1, "time_updated": 2000},
        3: {"result": 1, "time_updated": 3000},
        4: {"result": 0},
    }
    monkeypatch.setattr(installed, "get_published_files", lambda ids, cancel=None: rows)

    statuses = check_updates(items)

    assert statuses[1].status == UPDATE_AVAILABLE
    assert statuses[1].installed_label == "1970-01-01"
    assert statuses[1].online_label == "1970-01-01"
    assert statuses[2].status == UP_TO_DATE
    assert statuses[3].status == UNKNOWN
    assert statuses[4].status == UNAVAILABLE
    assert statuses[1].available is True
    assert statuses[2].available is False


def test_check_updates_batches_metadata_requests(monkeypatch):
    calls = []

    def rows(ids, cancel=None):
        calls.append(list(ids))
        return {fileid: {"result": 1, "time_updated": 5} for fileid in ids}

    monkeypatch.setattr(installed, "get_published_files", rows)
    items = [InstalledItem(1, fileid, Path("x"), updated=1) for fileid in range(1, 152)]

    statuses = check_updates(items, pace=0)

    assert [len(call) for call in calls] == [100, 51]
    assert len(statuses) == 151


def test_cancelled_check_returns_nothing(monkeypatch):
    monkeypatch.setattr(
        installed, "get_published_files", Mock(side_effect=AssertionError("no requests"))
    )
    cancel = threading.Event()
    cancel.set()

    assert check_updates([InstalledItem(1, 1, Path("x"), updated=1)], cancel) == {}


def test_delivery_records_the_workshop_revision(tmp_path):
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "mod.txt").write_text("installed")

    final = deliver_item(staged, tmp_path / "Mods", 10, 20, "Mod", updated=1700000000)

    assert read_marker(final)["updated"] == 1700000000


def test_state_persists_update_check_time(tmp_path):
    path = tmp_path / "state.json"
    state = AppState(path)
    assert state.updates_check_due() is True

    state.mark_updates_checked(time.time())
    assert state.updates_check_due() is False

    reloaded = AppState(path)
    assert reloaded.last_update_check > 0
    assert reloaded.updates_check_due() is False


def test_cli_cleanup_reports_and_prunes_only_default_copies(
    tmp_path, monkeypatch, capsys
):
    import osw.cli as cli

    root = tmp_path / "mods"
    staged = _staged(root, 4000, 100)
    game_mods = tmp_path / "RimWorld" / "Mods"
    delivered = game_mods / "Wiremod"
    delivered.mkdir(parents=True)
    (delivered / ".opensteamworkshop.json").write_text(
        json.dumps({"appid": 4000, "fileid": 100, "title": "Wiremod"})
    )
    AppState().set_game_path(4000, game_mods)
    monkeypatch.setattr(
        cli,
        "_build_manager",
        Mock(side_effect=AssertionError("cleanup must not start SteamCMD")),
    )

    assert cli.main(["cleanup", "--out", str(root)]) == 0
    report = capsys.readouterr().out
    assert "Wiremod" in report
    assert "recommended to delete" in report
    assert "1 safe deletion" in report
    assert staged.is_dir() and delivered.is_dir()

    assert cli.main(["cleanup", "--out", str(root), "--prune"]) == 0
    pruned = capsys.readouterr().out
    assert "Deleted default copy of Wiremod" in pruned
    assert not staged.exists()
    assert delivered.is_dir()


def test_cli_cleanup_skips_ambiguous_delivered_copies(tmp_path, capsys):
    import osw.cli as cli

    root = tmp_path / "mods"
    first = tmp_path / "GameA" / "Mods" / "Wiremod"
    second = tmp_path / "GameB" / "Mods" / "Wiremod copy"
    for folder in (first, second):
        folder.mkdir(parents=True)
        (folder / ".opensteamworkshop.json").write_text(
            json.dumps({"appid": 4000, "fileid": 100, "title": "Wiremod"})
        )
    state = AppState()
    state.set_game_path(4000, first.parent)
    state.set_game_path(4001, second.parent)

    assert cli.main(["cleanup", "--out", str(root), "--prune"]) == 0
    output = capsys.readouterr().out
    assert "need a choice" in output
    assert "Skipped 1 items" in output
    assert first.is_dir() and second.is_dir()


def test_cli_updates_reports_and_applies(tmp_path, monkeypatch, capsys):
    import osw.cli as cli
    from osw.installed import UpdateInfo
    from osw.queue import JobState

    root = tmp_path / "mods"
    _staged(root, 10, 20)
    _write_acf(
        root,
        10,
        '"AppWorkshop" { "WorkshopItemsInstalled" { "20" { "timeupdated" "1000" } } }',
    )
    monkeypatch.setattr(
        cli,
        "check_updates",
        lambda items: {20: UpdateInfo(20, UPDATE_AVAILABLE, 1000, 2000, "Wiremod")},
    )

    monkeypatch.setattr(
        cli,
        "_build_manager",
        Mock(side_effect=AssertionError("a report must not start SteamCMD")),
    )
    assert cli.main(["updates", "--out", str(root)]) == 0
    output = capsys.readouterr().out
    assert "Update available" in output
    assert "installed 1970-01-01 · latest 1970-01-01" in output
    assert "1 update available" in output

    class Job:
        id = "job"
        fileid = 20
        title = "Wiremod"
        state = JobState.DONE
        message = "ok"
        error_kind = ""

    class Manager:
        def __init__(self):
            self.added = []

        def add(self, item, app_name="", deliver_to=None, reinstall=False):
            self.added.append((item, deliver_to, reinstall))
            return Job()

        def shutdown(self):
            pass

    manager = Manager()
    monkeypatch.setattr(cli, "_build_manager", lambda args: manager)
    assert cli.main(["updates", "--out", str(root), "--apply"]) == 0
    item, deliver_to, reinstall = manager.added[0]
    assert item.publishedfileid == 20
    assert deliver_to is None
    assert reinstall is True
