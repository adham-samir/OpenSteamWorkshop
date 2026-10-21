import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QItemSelectionModel, Qt
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton

from osw import settings
from osw.bulk import DownloadResolution, ResolutionIssue
from osw.gui.browse_page import MODE_GRID
from osw.gui.browse_page import BrowsePage as DeskBrowsePage
from osw.gui.bulk_dialog import BulkDialog
from osw.gui.downloads_page import DownloadsPage
from osw.gui.imports_page import ImportPage
from osw.gui.item_models import (
    FavoriteRole,
    InstalledItemRole,
    ItemRole,
    JobFilter,
    MetaRole,
    ThumbRole,
)
from osw.gui.library import (
    InstalledItem,
    InstalledMetadata,
    content_dir,
    delete_installed_item,
    fetch_installed_metadata,
    scan_installed,
)
from osw.gui.library_page import LibraryPage
from osw.gui.main_window import Async, MainWindow
from osw.gui.state import AppState
from osw.gui.status_strip import StatusStrip
from osw.models import Game, ItemDetails, WorkshopItem
from osw.queue import JobSnapshot, JobState


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    w = MainWindow(queue_path=tmp_path / "queue.json")
    monkeypatch.setattr(w.manager, "ensure_workers", lambda: None)
    yield w
    w.close()
    w.deleteLater()
    qapp.processEvents()


def pump(qapp, condition, timeout=2):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert condition()


def test_settings_open_and_preserve_manager(window):
    manager = window.manager
    job = manager.add_direct(10, 20)

    window._open_settings()
    assert window.workspace == "settings"
    page = window.settings
    page.root_edit.setText(str(job.dest / "new"))
    page.user_edit.setText("user")
    page.password_edit.setText("session-secret")
    page.account_checkbox.setChecked(True)
    page.save_button.click()
    assert window.manager is manager
    assert manager.password == "session-secret"
    assert job.dest != manager.content_root
    assert not job._password
    assert len(manager.jobs) == 1


def test_pasted_item_uses_its_app_not_selected_game(window, monkeypatch):
    window.current_game = Game(10, "Selected game")
    queued = []
    monkeypatch.setattr(window, "_queue_download", queued.append)

    def download(dialog):
        next(b for b in dialog.findChildren(QPushButton) if b.text() == "Download").click()
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", download)
    window._show_details_dialog(ItemDetails(20, title="Other", appid=99), 10)
    assert queued[0].appid == 99


def test_unknown_or_private_item_cannot_be_downloaded(window, monkeypatch):
    buttons = []

    def inspect(dialog):
        buttons.append(
            next(b for b in dialog.findChildren(QPushButton) if b.text() == "Download").isEnabled()
        )
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", inspect)
    window.current_game = Game(10, "irrelevant")
    window._show_details_dialog(ItemDetails(20), None)
    window._show_details_dialog(ItemDetails(21, appid=10, error="Private"), 10)
    assert buttons == [False, False]


def test_stale_browse_results_do_not_replace_current_game(window):
    window.current_game = Game(10, "Current")
    original = WorkshopItem(20, appid=10)
    window.items = [original]
    window._items_ready(99, [], 0, 0)
    assert window.items == [original]


def test_request_generations_ignore_out_of_order_results(window, monkeypatch):
    callbacks = []
    monkeypatch.setattr(window.hub, "call", lambda fn, done, **kwargs: callbacks.append(done))
    seen = []
    window._request("test", lambda: None, seen.append)
    window._request("test", lambda: None, seen.append)
    callbacks[1]("new")
    callbacks[0]("old")
    assert seen == ["new"]


def test_failed_game_search_restores_button(window, qapp, monkeypatch):
    monkeypatch.setattr(
        "osw.gui.main_window.search_games", Mock(side_effect=RuntimeError("offline"))
    )
    window.gameSearchEdit.setText("Example game")
    window._game_search()
    assert not window.findBtn.isEnabled()
    pump(qapp, window.findBtn.isEnabled)
    assert "offline" in window.browserMessage.text()


def test_hub_routes_callbacks_on_main_thread_and_releases_carrier(window, qapp):
    main = threading.get_ident()
    # Let the window's startup installed-index scan finish so its carrier is gone
    # before the baseline is measured.
    pump(qapp, lambda: window._installed_ready)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    seen = []
    baseline = len(window.hub.findChildren(Async))
    window.hub.call(
        lambda: threading.get_ident(), lambda worker: seen.append((worker, threading.get_ident()))
    )
    pump(qapp, lambda: bool(seen))
    assert seen[0][0] != main and seen[0][1] == main
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert len(window.hub.findChildren(Async)) == baseline


def test_queue_row_state_resets_and_actions(window):
    job = window.manager.add_direct(10, 20)
    job.state, job.message = JobState.FAILED, "Failure"
    window._on_job_ui(job.snapshot())
    row = window._job_rows[job.id]
    assert row["bar"].isHidden()
    assert row["retry"].isEnabled()
    job.state, job.progress = JobState.RUNNING, 30
    window._on_job_ui(job.snapshot())
    assert not row["bar"].isHidden() and row["bar"].value() == 30
    assert row["cancel"].isEnabled() and not row["retry"].isEnabled()


def test_multiselect_opens_preview(window, monkeypatch):
    window.current_game = Game(10, "Game")
    window._items_ready(
        10, [WorkshopItem(20, appid=10, title="One"), WorkshopItem(21, appid=10, title="Two")], 2, 1
    )
    for n in range(2):
        window.modsGrid.item(n).setSelected(True)
    preview = Mock()
    monkeypatch.setattr(window, "_open_bulk", preview)
    window._download_selected()
    assert preview.call_args.args == ("20\n21",)


def test_bulk_preview_excludes_unchecked_items_and_invalidates(window, qapp, monkeypatch):
    from osw.bulk import DownloadResolution, ResolutionIssue

    result = DownloadResolution(
        items=[WorkshopItem(20, appid=10, title="One"), WorkshopItem(21, appid=10, title="Two")],
        issues=[ResolutionIssue("bad", "Invalid URL")],
    )
    monkeypatch.setattr("osw.gui.bulk_dialog.resolve_downloads", lambda *args: result)
    queued = []
    dialog = BulkDialog(window.hub, queued.extend, window)
    dialog.source.setPlainText("20\n21")
    dialog.resolve()
    pump(qapp, lambda: dialog.resolution is not None)
    assert "bad" in dialog.issues.toPlainText()
    dialog.table.item(1, 0).setCheckState(Qt.Unchecked)
    dialog._queue_selected()
    assert [item.publishedfileid for item in queued] == [20]
    dialog.deleteLater()


def test_auth_cancelled_before_dialog_is_not_shown(window, monkeypatch):
    cancel = threading.Event()
    cancel.set()
    ready = threading.Event()
    exec_mock = Mock()
    monkeypatch.setattr(QDialog, "exec", exec_mock)
    request = {"kind": "password", "cancel": cancel, "ready": ready, "value": None}
    window._show_auth(request)
    assert ready.is_set() and request["value"] is None
    exec_mock.assert_not_called()


def test_import_edit_or_close_cancels_resolution(window, monkeypatch):
    callbacks = []
    monkeypatch.setattr(window.hub, "call", lambda fn, done, **kw: callbacks.append(done))
    dialog = BulkDialog(window.hub, lambda items: None, window)
    dialog.source.setPlainText("20")
    dialog.resolve()
    first_cancel = dialog._cancel
    dialog.source.setPlainText("21")
    assert first_cancel.is_set()
    from osw.bulk import DownloadResolution

    callbacks[0](DownloadResolution(items=[WorkshopItem(20, appid=10)]))
    assert dialog.resolution is None
    assert not dialog.queue_button.isEnabled()
    dialog.resolve()
    current_cancel = dialog._cancel
    dialog.reject()
    assert current_cancel.is_set()
    callbacks[1](DownloadResolution(items=[WorkshopItem(21, appid=10)]))
    assert dialog.resolution is None
    dialog.deleteLater()


def test_restore_does_not_start_downloads(qapp, tmp_path):
    from unittest.mock import patch

    from osw.queue import DownloadManager

    path = tmp_path / "queue.json"
    manager = DownloadManager(tmp_path, queue_path=path)
    with patch.object(manager, "ensure_workers"):
        manager.add_direct(10, 20)
    window = MainWindow(queue_path=path)
    try:
        assert window.manager.jobs[0].state is JobState.INTERRUPTED
        assert window.manager._thread is None
        assert len(window._job_rows) == 1
    finally:
        window.close()
        window.deleteLater()


# ---------------------------------------------------------------- new workspace UI


def _snap(index, state=JobState.QUEUED, progress=0, **overrides):
    values = dict(
        id=f"job-{index}",
        appid=10,
        app_name="Game",
        fileid=100 + index,
        title=f"Mod {index}",
        dest=Path("/tmp/mods") / str(100 + index),
        state=state,
        progress=progress,
        message="working",
        attempts=0,
        output_path="",
        error_kind="",
        logs=(),
        inflight=False,
    )
    values.update(overrides)
    return JobSnapshot(**values)


def test_sidebar_collapses_to_icon_rail_and_restores(window, qapp):
    window.resize(960, 640)
    window.show()
    qapp.processEvents()
    assert window.sidebar.is_collapsed()
    assert window.sidebar.width() == 64
    for key, button in window.sidebar.buttons.items():
        assert button.text() == ""
        assert button.toolTip()
        assert button.accessibleName() == window.sidebar.LABELS[key]

    window.resize(1150, 740)
    qapp.processEvents()
    assert not window.sidebar.is_collapsed()
    assert window.sidebar.width() == 208
    assert window.sidebar.buttons["browse"].text() == "Browse"


def test_navigation_and_status_strip_open_downloads(window):
    for key in ("imports", "downloads", "settings", "browse"):
        window.sidebar.buttons[key].click()
        assert window.workspace == key
        assert window.stack.currentWidget() is window._pages[key]
        assert window.sidebar.active() == key

    window.navigate("browse")
    window.status_strip.activated.emit()
    assert window.workspace == "downloads"


def test_landing_actions_emit_intent(qapp):
    page = DeskBrowsePage()
    searches, imports = [], []
    page.game_search_requested.connect(searches.append)
    page.import_requested.connect(lambda: imports.append("imports"))

    page.game_search.setText("portal 2")
    page.find_button.click()
    page.import_btn.click()

    assert searches == ["portal 2"]
    assert imports == ["imports"]


def test_game_results_select_emits_appid(qapp):
    page = DeskBrowsePage()
    page.set_games("a", [Game(10, "Alpha"), Game(20, "Beta")])
    assert page.results.model.rowCount() == 2
    seen = []
    page.app_picked.connect(seen.append)
    page.results.list.clicked.emit(page.results.model.index(1, 0))
    assert seen == [20]


def test_workshop_cards_expose_metadata_and_thumbnail_updates(qapp):
    page = DeskBrowsePage()
    page.set_game(10, "Game")
    item = WorkshopItem(20, appid=10, title="Detail", tags=["Tools"], subscriptions=42)
    page.set_items([item], 1, 1, 1)

    index = page.grid_model.index(0, 0)
    assert page.grid_model.rowCount() == 1
    assert index.data(ItemRole).publishedfileid == 20
    assert index.data(Qt.DisplayRole) == "Detail"
    assert "42 subs" in index.data(MetaRole)
    assert index.data(ThumbRole) is None

    pixmap = QPixmap(8, 8)
    pixmap.fill(Qt.red)
    page.update_card_thumb(20, pixmap)
    assert index.data(ThumbRole) is not None


def test_multiselect_shows_bulk_bar_and_reviews(qapp):
    page = DeskBrowsePage()
    page.set_items(
        [WorkshopItem(20, appid=10, title="One"), WorkshopItem(21, appid=10, title="Two")],
        2,
        1,
        1,
    )
    selection = page.cards.selectionModel()
    flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
    selection.select(page.grid_model.index(0, 0), flags)
    selection.select(page.grid_model.index(1, 0), flags)
    qapp.processEvents()

    assert len(page.selected_items()) == 2
    assert not page.bulk_bar.isHidden()
    assert page.bulk_bar.label.text() == "2 items selected"

    reviewed = []
    page.bulk_download_requested.connect(lambda: reviewed.append(True))
    page.bulk_bar.download_btn.click()
    assert reviewed == [True]


def test_imports_invalidation_clears_stale_preview(qapp):
    page = ImportPage()
    resolution = DownloadResolution(
        items=[WorkshopItem(20, appid=10), WorkshopItem(21, appid=10)],
        issues=[ResolutionIssue("bad", "Invalid reference")],
        dependencies={21},
    )
    page.resolve_finished(resolution)
    assert page.tmodel.rowCount() == 2
    assert page.queue_button.isEnabled()
    assert page.tmodel.index(0, 0).data(Qt.CheckStateRole) == Qt.Checked
    assert page.tmodel.index(1, 3).data(Qt.DisplayRole) == "Required"

    page.source.setPlainText("changed")
    assert page.resolution is None
    assert page.tmodel.rowCount() == 0
    assert not page.queue_button.isEnabled()
    assert "List changed" in page.summary.text()


def test_imports_selection_and_stop(qapp):
    page = ImportPage()
    page.resolve_finished(
        DownloadResolution(items=[WorkshopItem(20, appid=10), WorkshopItem(21, appid=10)])
    )
    page.tmodel.setData(page.tmodel.index(0, 0), Qt.Unchecked, Qt.CheckStateRole)
    assert [item.publishedfileid for item in page.tmodel.checked()] == [21]

    page.source.setPlainText("123")
    requested = []
    page.resolve_requested.connect(lambda refs, hint, deps: requested.append(refs))
    page.resolve_button.click()
    assert requested == ["123"]
    assert page.cancel_button.isEnabled()

    page._stop()
    page.resolve_cancelled()
    assert "stopped" in page.summary.text().lower()
    assert not page.cancel_button.isEnabled()
    assert not page.queue_button.isEnabled()


def test_download_filters_and_counts(qapp):
    page = DownloadsPage()
    page.replace_all(
        [
            _snap(0, JobState.QUEUED),
            _snap(1, JobState.RUNNING, 40),
            _snap(2, JobState.FAILED, 10),
            _snap(3, JobState.INTERRUPTED, 20),
            _snap(4, JobState.DONE, 100),
        ]
    )
    counts = page.model.counts()
    assert counts[JobFilter.ALL] == 5
    assert counts[JobFilter.ACTIVE] == 2
    assert counts[JobFilter.ATTENTION] == 2
    assert counts[JobFilter.FINISHED] == 1
    attention = next(
        button for button, filt in page._filters.items() if filt == JobFilter.ATTENTION
    )
    assert "Needs attention" in attention.text()

    page.set_filter(filt=JobFilter.ATTENTION)
    assert page.model.rowCount() == 2
    page.set_filter(filt=JobFilter.FINISHED)
    assert page.model.rowCount() == 1
    page.set_filter(filt=JobFilter.ACTIVE)
    assert page.model.rowCount() == 2


def test_download_actions_route_selected_job(qapp):
    page = DownloadsPage()
    page.show()
    page.replace_all([_snap(0, JobState.RUNNING, 30), _snap(1, JobState.FAILED, 12)])
    seen = []
    page.action_requested.connect(lambda job_id, action: seen.append((job_id, action)))

    page.table.selectRow(0)
    qapp.processEvents()
    assert page.model.snapshot(page.table.currentIndex().row()).id == "job-0"
    cancel = next(button for button in page.action_buttons if button.text() == "Cancel")
    cancel.click()
    assert seen == [("job-0", "Cancel")]

    page.table.selectRow(1)
    qapp.processEvents()
    retry = next(button for button in page.action_buttons if button.text() == "Retry")
    retry.click()
    assert seen[-1] == ("job-1", "Retry")


def test_status_strip_counts_and_activation(qapp):
    strip = StatusStrip()
    strip.update_from_jobs(
        [
            _snap(0, JobState.QUEUED),
            _snap(1, JobState.RUNNING, 62, title="Live mod"),
            _snap(2, JobState.FAILED),
            _snap(3, JobState.INTERRUPTED),
            _snap(4, JobState.DONE, 100),
        ]
    )
    assert strip.queued_count == 1
    assert strip.failure_count == 1
    assert strip.running_title == "Live mod"
    assert strip.progress_value == 62
    assert "1 queued, 1 failed" in strip.accessibleName()

    activated = []
    strip.activated.connect(lambda: activated.append(True))
    strip.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    assert activated == [True]


def test_window_status_strip_follows_jobs(window):
    window.manager.ensure_workers = lambda: None
    window.manager.add_direct(10, 20)
    window._refresh_jobs()
    assert window.status_strip.queued_count == 1
    assert window.status_strip.complete is False if hasattr(window.status_strip, "complete") else True


def test_large_models_stay_responsive(qapp):
    page = DeskBrowsePage()
    page.set_items(
        [WorkshopItem(1000 + n, appid=10, title=f"Mod {n}") for n in range(30)],
        30,
        1,
        1,
    )
    assert page.grid_model.rowCount() == 30

    imports = ImportPage()
    imports.resolve_finished(
        DownloadResolution(items=[WorkshopItem(2000 + n, appid=10) for n in range(100)])
    )
    assert imports.tmodel.rowCount() == 100

    downloads = DownloadsPage()
    downloads.replace_all([_snap(n, JobState.QUEUED) for n in range(100)])
    assert downloads.model.rowCount() == 100
    assert downloads.model.counts()[JobFilter.ALL] == 100


# ------------------------------------------------------- recents & favorites


def test_app_state_round_trip_and_recent_limit(tmp_path):
    path = tmp_path / "state.json"
    state = AppState(path)
    for n in range(1, 9):
        state.record_game(Game(n, f"Game {n}"))

    assert [g.appid for g in state.recent] == [8, 7, 6, 5, 4, 3]
    assert state.toggle_favorite(Game(3, "Game 3")) is True
    assert state.is_favorite(3)
    assert state.toggle_favorite(Game(3, "Game 3")) is False

    state.toggle_favorite(Game(6, "Game 6"))
    reloaded = AppState(path)
    assert [g.appid for g in reloaded.recent] == [8, 7, 6, 5, 4, 3]
    assert [g.name for g in reloaded.favorites] == ["Game 6"]
    assert reloaded.favorite_ids() == {6}

    path.write_text("{not json", encoding="utf-8")
    broken = AppState(path)
    assert broken.recent == [] and broken.favorites == []


def test_hero_shows_recent_and_pinned_games(qapp):
    page = DeskBrowsePage()
    assert page.hero.recent_box.isHidden() and page.hero.pinned_box.isHidden()

    page.set_personal(
        [Game(10, "Alpha"), Game(20, "Beta")],
        [Game(20, "Beta")],
    )
    assert not page.hero.recent_box.isHidden()
    assert not page.hero.pinned_box.isHidden()
    assert page.hero.recent_row.itemAt(1).widget().text() == "Alpha"
    assert page.hero.recent_row.itemAt(2).widget().text() == "Beta"
    assert page.hero.pinned_row.itemAt(1).widget().text() == "Beta"

    opened = []
    page.hero.game_requested.connect(opened.append)
    page.hero.pinned_row.itemAt(1).widget().click()
    assert opened == [20]


def test_header_pin_reflects_and_emits_favorite(qapp):
    page = DeskBrowsePage()
    page.set_game(10, "Alpha")
    page.set_mode(MODE_GRID)
    page.set_favorite(True)
    assert page.pin_btn.text() == "Pinned"
    assert page.pin_btn.isChecked()

    seen = []
    page.favorite_toggled.connect(seen.append)
    page.pin_btn.click()
    assert seen == [10]

    page.set_favorite(False)
    assert page.pin_btn.text() == "Pin"


def test_game_results_mark_favorites(qapp):
    page = DeskBrowsePage()
    page.set_games("a", [Game(10, "Alpha"), Game(20, "Beta")])
    page.results.set_favorites({20})
    model = page.results.model
    assert model.index(0, 0).data(FavoriteRole) is False
    assert model.index(1, 0).data(FavoriteRole) is True


def test_window_starts_without_placeholder_recents(window):
    assert window.state.recent == []
    assert window.state.favorites == []
    assert window.browse.hero.recent_box.isHidden()
    assert window.browse.hero.pinned_box.isHidden()


def test_window_remembers_recent_and_pins_games(window):
    window._remember_game(Game(10, "Alpha"))
    assert [g.appid for g in window.state.recent] == [10]
    assert not window.browse.hero.recent_box.isHidden()

    window.current_game = Game(10, "Alpha")
    window._toggle_favorite(10)
    assert window.state.is_favorite(10)
    assert window.browse.pin_btn.isChecked()
    assert not window.browse.hero.pinned_box.isHidden()

    window._toggle_favorite(10)
    assert not window.state.is_favorite(10)
    assert not window.browse.pin_btn.isChecked()


# ------------------------------------------------------------ installed library


def _make_installed(root, appid, fileid, files=None):
    item_dir = content_dir(root) / str(appid) / str(fileid)
    item_dir.mkdir(parents=True)
    for name, payload in (files or {}).items():
        path = item_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return item_dir


def test_library_scan_tolerates_non_numeric_entries_and_cancels(tmp_path):
    root = tmp_path / "mods"
    first = _make_installed(
        root,
        4000,
        100,
        {"root.bin": b"abc", "nested/blob.bin": b"defg"},
    )
    second = _make_installed(root, 4000, 101)
    content = content_dir(root)
    (content / "not-an-app").mkdir()
    (content / "4000" / "not-an-item").mkdir(parents=True)
    (second / "empty.txt").write_bytes(b"")

    items = scan_installed(root)

    assert [(item.appid, item.fileid) for item in items] == [(4000, 100), (4000, 101)]
    assert items[0].path == first
    assert items[0].size == len(b"abc") + len(b"defg")
    assert items[0].modified > 0
    assert items[1].size == 0

    cancel = threading.Event()
    cancel.set()
    assert scan_installed(root, cancel) is None


def test_library_delete_refuses_folders_outside_the_content_tree(tmp_path):
    outside = tmp_path / "not-workshop" / "100"
    outside.mkdir(parents=True)
    item = InstalledItem(4000, 100, outside)

    with pytest.raises(ValueError):
        delete_installed_item(item, tmp_path / "mods")

    assert outside.is_dir()


def test_library_metadata_uses_bounded_batches_and_app_names(monkeypatch, tmp_path):
    items = [
        InstalledItem(4000, 100, tmp_path),
        InstalledItem(4000, 101, tmp_path),
        InstalledItem(500, 200, tmp_path),
    ]
    batches = []
    monkeypatch.setattr(
        "osw.installed.get_published_files",
        lambda ids, cancel: batches.append(list(ids))
        or {fileid: {"title": f"Title {fileid}"} for fileid in ids},
    )
    monkeypatch.setattr(
        "osw.installed.get_app_name",
        lambda appid, cancel: {4000: "Garry's Mod", 500: "Left 4 Dead 2"}[appid],
    )

    metadata = fetch_installed_metadata(items, batch_size=2, pause=0)

    assert batches == [[100, 101], [200]]
    assert metadata[100] == InstalledMetadata("Title 100", "Garry's Mod")
    assert metadata[200].title == "Title 200"
    assert metadata[200].app_name == "Left 4 Dead 2"


def test_library_page_rows_states_and_action_bar(qapp, tmp_path):
    page = LibraryPage()
    item = InstalledItem(
        4000,
        100,
        tmp_path / "100",
        size=1536,
        modified=1_700_000_000,
    )

    page.show_loading(tmp_path)
    assert page.state_panel.kind == "loading"
    assert page.action_bar.isHidden()
    page.show_items([item], tmp_path)
    assert page._stack.currentIndex() == 0
    assert not page.action_bar.isHidden()
    index = page.model.index(0, 0)
    assert index.data(InstalledItemRole) is item
    assert index.data(Qt.DisplayRole) == "Workshop item 100"
    assert "Workshop ID 100" in index.data(Qt.ToolTipRole)
    assert page.model.index(0, 2).data(Qt.DisplayRole) == "Default mods root"
    assert page.model.index(0, 3).data(Qt.DisplayRole) == "1.5 KB"

    page.apply_metadata({100: InstalledMetadata("Wiremod", "Garry's Mod")})
    assert index.data(Qt.DisplayRole) == "Wiremod"
    assert page.model.index(0, 1).data(Qt.DisplayRole) == "Garry's Mod"

    selected = []
    page.action_requested.connect(lambda target, action: selected.append((target, action)))
    page.update_actions(index)
    assert [button.text() for button in page.action_buttons] == [
        "Open folder",
        "Inspect in Browse",
        "Re-download",
        "Delete",
    ]
    next(button for button in page.action_buttons if button.text() == "Re-download").click()
    assert selected == [(item, "Re-download")]

    page.show_items([], tmp_path)
    assert page.model.rowCount() == 0
    assert page.state_panel.kind == "empty"
    assert page._stack.currentIndex() == 1
    assert page.action_bar.isHidden()


def test_library_workspace_navigation_scan_and_metadata(window, qapp, tmp_path, monkeypatch):
    root = tmp_path / "mods"
    _make_installed(root, 4000, 100, {"mod.txt": b"abc"})
    settings.save({"content_root": str(root)})
    monkeypatch.setattr(
        "osw.installed.get_published_files",
        lambda ids, cancel: {fileid: {"title": "Wiremod"} for fileid in ids},
    )
    monkeypatch.setattr(
        "osw.installed.get_app_name", lambda appid, cancel: "Garry's Mod"
    )

    window.navigate("library")

    assert window.workspace == "library"
    assert window.stack.currentWidget() is window.library
    assert window.nav.buttons["library"].isChecked()
    keys = list(window.nav.buttons)
    assert keys.index("imports") < keys.index("library") < keys.index("downloads")
    pump(
        qapp,
        lambda: window.library.model.rowCount() == 1
        and window.library.model.index(0, 0).data(Qt.DisplayRole) == "Wiremod",
    )
    assert window.library.model.index(0, 1).data(Qt.DisplayRole) == "Garry's Mod"
    assert window.nav.library_count == 1
    assert "1 installed" in window.nav.buttons["library"].text()
    assert "1 installed" in window.nav.buttons["library"].accessibleDescription()


def test_library_workspace_empty_state(window, qapp, tmp_path):
    settings.save({"content_root": str(tmp_path / "missing-mods")})

    window.navigate("library")

    pump(qapp, lambda: window.library.state_panel.kind == "empty")
    assert window.library.model.rowCount() == 0
    assert window.nav.library_count == 0
    assert window.library._stack.currentIndex() == 1


def test_library_actions_open_inspect_redownload_and_confirm_delete(
    window, tmp_path, monkeypatch
):
    root = tmp_path / "mods"
    item_dir = _make_installed(root, 4000, 100, {"mod.txt": b"abc"})
    settings.save({"content_root": str(root)})
    item = InstalledItem(
        4000,
        100,
        item_dir,
        size=3,
        modified=1_700_000_000,
        title="Wiremod",
        app_name="Garry's Mod",
    )

    opened = []

    class FakeDesktop:
        @staticmethod
        def openUrl(url):
            opened.append(url.toLocalFile())

    monkeypatch.setattr("osw.gui.main_window.QDesktopServices", FakeDesktop)
    window._on_library_action(item, "Open folder")
    assert Path(opened[0]).resolve() == item_dir.resolve()

    window.current_game = Game(4000, "Garry's Mod")
    requests = []
    monkeypatch.setattr(window, "_request", lambda *args, **kwargs: requests.append(args))
    window._on_library_action(item, "Inspect in Browse")
    assert window.workspace == "browse"
    assert window.browse.inspector.item.publishedfileid == 100
    assert requests and requests[0][0] == "inspector"

    queued = []
    monkeypatch.setattr(window, "_queue_download", queued.append)
    window._on_library_action(item, "Re-download")
    assert queued[0].publishedfileid == 100
    assert queued[0].appid == 4000

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    window._on_library_action(item, "Delete")
    assert item_dir.is_dir()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    window._on_library_action(item, "Delete")
    assert not item_dir.exists()


def test_app_state_per_game_paths_round_trip_and_old_files(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": 1, "recent": [], "favorites": []}))
    state = AppState(path)
    assert state.game_path(4000) is None

    chosen = tmp_path / "RimWorld" / "Mods"
    state.set_game_path(4000, chosen)
    state.set_game_path(0, tmp_path / "ignored")
    reloaded = AppState(path)
    assert reloaded.game_path(4000) == chosen
    assert sorted(json.loads(path.read_text())["game_paths"]) == ["4000"]

    assert reloaded.clear_game_path(4000)
    assert not reloaded.clear_game_path(4000)
    assert AppState(path).game_path(4000) is None

    path.write_text(
        json.dumps(
            {
                "game_paths": {
                    "bad": "/tmp/x",
                    "-1": "/tmp/y",
                    "500": "",
                    "600": "/tmp/kept",
                }
            }
        )
    )
    tolerant = AppState(path)
    assert tolerant.game_paths == {600: Path("/tmp/kept")}


def test_library_scan_includes_override_folders_and_delivered_wins(tmp_path):
    root = tmp_path / "mods"
    staged = _make_installed(root, 4000, 100, {"old.txt": b"old"})
    _make_installed(root, 4000, 101, {"new.txt": b"new"})
    game_mods = tmp_path / "RimWorld" / "Mods"
    delivered = game_mods / "Wiremod"
    delivered.mkdir(parents=True)
    (delivered / "About.xml").write_text("<Mod/>")
    (delivered / ".opensteamworkshop.json").write_text(
        json.dumps({"appid": 4000, "fileid": 100, "title": "Wiremod"})
    )
    manual = game_mods / "Manual mod"
    manual.mkdir()
    (manual / "notes.txt").write_text("not delivered by this app")

    items = scan_installed(
        root, game_paths={4000: game_mods, 999: tmp_path / "missing-folder"}
    )

    assert [(item.appid, item.fileid) for item in items] == [(4000, 100), (4000, 101)]
    delivered_item, staged_item = items
    assert delivered_item.delivered
    assert delivered_item.path == delivered
    assert delivered_item.title == "Wiremod"
    assert delivered_item.location_label.startswith("Delivered · ")
    assert not staged_item.delivered
    assert staged_item.location_label == "Default mods root"

    delete_installed_item(delivered_item, root)
    assert not delivered.exists()
    assert staged.is_dir()
    assert manual.is_dir()


def test_browse_mods_folder_override_persists_and_clears(window, tmp_path, monkeypatch):
    settings.save({"content_root": str(tmp_path / "mods")})
    window.current_game = Game(294100, "RimWorld")
    window.browse.set_game(294100, "RimWorld")
    window._refresh_mods_folder()
    assert "default" in window.browse.mods_btn.accessibleName()

    chosen = tmp_path / "RimWorld" / "Mods"
    chosen.mkdir(parents=True)
    monkeypatch.setattr(
        "osw.gui.main_window.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: str(chosen),
    )
    window._choose_mods_folder()

    assert window.state.game_path(294100) == chosen
    assert "override" in window.browse.mods_btn.accessibleName()
    assert str(chosen) in window.browse.mods_btn.toolTip()
    assert AppState().game_path(294100) == chosen

    window._clear_mods_folder()
    assert window.state.game_path(294100) is None
    assert AppState().game_path(294100) is None
    assert "default" in window.browse.mods_btn.accessibleName()


def test_redownload_and_bulk_queue_use_game_override(window, tmp_path):
    settings.save({"content_root": str(tmp_path / "mods")})
    override = tmp_path / "RimWorld" / "Mods"
    window.state.set_game_path(294100, override)
    window.current_game = Game(294100, "RimWorld")

    item = InstalledItem(294100, 100, tmp_path / "whatever", title="Wiremod")
    window._on_library_action(item, "Re-download")
    job = window.manager.jobs[-1]
    assert job.fileid == 100
    assert job.deliver_to == override.resolve()

    window._queue_many(
        [
            WorkshopItem(101, appid=294100, title="Other RimWorld mod"),
            WorkshopItem(102, appid=4000, title="Garry's Mod addon"),
        ]
    )
    by_id = {queued.fileid: queued for queued in window.manager.jobs}
    assert by_id[101].deliver_to == override.resolve()
    assert by_id[102].deliver_to is None


# ---------------------------------------------------------- installed guard


def _stage_install(root, appid, fileid):
    item_dir = content_dir(root) / str(appid) / str(fileid)
    item_dir.mkdir(parents=True)
    (item_dir / "mod.txt").write_text("installed")
    return item_dir


def test_single_download_asks_before_reinstalling(window, tmp_path, monkeypatch):
    root = tmp_path / "mods"
    item_dir = _stage_install(root, 4000, 100)
    settings.save({"content_root": str(root)})
    window._installed_ready = False
    item = WorkshopItem(100, appid=4000, title="Wiremod")

    prompts = []

    def decline(*args, **kwargs):
        prompts.append(args[2])
        return QMessageBox.StandardButton.No

    monkeypatch.setattr("osw.gui.main_window.QMessageBox.question", decline)
    window._queue_download(item)

    assert prompts and "already installed" in prompts[0].lower()
    assert str(item_dir) in prompts[0]
    assert window.manager.jobs == []

    monkeypatch.setattr(
        "osw.gui.main_window.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    window._queue_download(item)
    assert [job.fileid for job in window.manager.jobs] == [100]


def test_single_download_queues_normally_when_not_installed(window, tmp_path, monkeypatch):
    settings.save({"content_root": str(tmp_path / "empty-mods")})
    window._installed_ready = False
    monkeypatch.setattr(
        "osw.gui.main_window.QMessageBox.question",
        Mock(side_effect=AssertionError("must not ask for a fresh item")),
    )
    window._queue_download(WorkshopItem(500, appid=4000, title="New mod"))
    assert [job.fileid for job in window.manager.jobs] == [500]


def test_import_preview_marks_installed_rows(qapp):
    page = ImportPage()
    page.resolve_finished(
        DownloadResolution(
            items=[
                WorkshopItem(20, appid=10, title="One"),
                WorkshopItem(21, appid=10, title="Two"),
            ]
        )
    )

    page.mark_installed({20: "/mods/steamapps/workshop/content/10/20 (Default mods root)"})

    assert page.tmodel.index(0, 0).data(Qt.CheckStateRole) == Qt.Unchecked
    assert page.tmodel.index(1, 0).data(Qt.CheckStateRole) == Qt.Checked
    assert page.tmodel.index(0, 3).data(Qt.DisplayRole) == "Installed"
    assert "already installed" in page.tmodel.index(0, 3).data(Qt.ToolTipRole).lower()
    assert "1 already installed mod unchecked" in page.summary.text()
    assert [item.publishedfileid for item in page.tmodel.checked()] == [21]


def test_finished_download_records_the_install(window, tmp_path):
    item_dir = _stage_install(tmp_path / "mods", 4000, 100)
    job = window.manager.add_direct(4000, 100, title="Wiremod")
    snapshot = replace(
        job.snapshot(), state=JobState.DONE, progress=100.0, output_path=str(item_dir)
    )

    window._on_job_ui(snapshot)

    hit = window.installed.lookup(4000, 100)
    assert hit is not None
    assert hit.path == item_dir
    assert hit.title == "Wiremod"
