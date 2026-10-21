"""Interaction contracts for the game-focused desktop shell."""
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog

from osw.bulk import DownloadResolution
from osw.gui.browse_page import MODE_GRID, BrowsePage
from osw.gui.games_page import GamesPage
from osw.gui.imports_page import ImportPage
from osw.gui.item_models import InstalledItemRole
from osw.gui.library import UPDATE_AVAILABLE, DuplicateGroup, InstalledItem, UpdateInfo
from osw.gui.library_page import LibraryPage
from osw.gui.main_window import MainWindow
from osw.gui.settings_page import SettingsPage
from osw.gui.state import AppState
from osw.models import Game, ItemDetails, WorkshopItem


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    w = MainWindow(queue_path=tmp_path / "queue.json")
    monkeypatch.setattr(w.manager, "ensure_workers", lambda: None)
    monkeypatch.setattr(w.hub, "call", lambda *a, **kw: None)
    yield w
    w.close()
    w.deleteLater()


def select(page, row):
    index = page.grid_model.index(row)
    page.cards.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select)
    page.cards.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
    page._selection_timer.stop()
    page._emit_selection()


def test_games_start_and_global_import_preserve_draft(window):
    assert window.workspace == "games"
    assert window.games_page.recent.model().rowCount() == 0
    assert window.games_page.first_use.isVisibleTo(window.games_page)
    window.import_button.click()
    window.imports.source.setPlainText("100")
    window.navigate("games")
    window.import_button.click()
    assert window.workspace == "imports"
    assert window.imports.source.toPlainText() == "100"


def test_games_use_only_real_personal_history(qapp):
    page = GamesPage()
    page.set_personal([Game(10, "Alpha")], [Game(20, "Beta")])
    assert page.first_use.isHidden()
    assert page.recent.model().rowCount() == 1
    opened = []
    page.app_picked.connect(opened.append)
    page.recent.clicked.emit(page.recent.model().index(0))
    assert opened == [10]


def test_game_context_restores_query_page_selection_art_and_dismissal(window, qapp):
    window.games = [Game(10, "Alpha"), Game(20, "Beta")]
    window._select_app(10)
    window._items_ready(10, [WorkshopItem(100, appid=10, title="First")], 80, 4, page=3)
    window.browse.modSearchEdit.setText("maps")
    window.browse.sortCombo.blockSignals(True)
    window.browse.sortCombo.setCurrentIndex(1)
    window.browse.sortCombo.blockSignals(False)
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    window.browse.update_card_thumb(100, image)
    select(window.browse, 0)
    window.browse.dismiss_details()
    window._select_app(20)
    window._items_ready(20, [WorkshopItem(200, appid=20, title="Second")], 1, 1)
    window.browse.modSearchEdit.setText("textures")
    window._select_app(10)
    qapp.processEvents()
    assert window.current_game.appid == 10
    assert window.page == 3 and window.total_pages == 4
    assert window.browse.modSearchEdit.text() == "maps"
    assert window.browse.sortCombo.currentIndex() == 1
    assert [it.publishedfileid for it in window.browse.selected_items()] == [100]
    assert not window.browse.card_thumb(100).isNull()
    assert not window.browse._details_open
    window._select_app(20)
    assert window.browse.modSearchEdit.text() == "textures"


def test_game_search_does_not_destroy_background_browse_context(window):
    window.current_game = Game(10, "Alpha")
    window.browse.set_game_context(window.current_game)
    window.browse.set_mode(MODE_GRID)
    window.browse.modSearchEdit.setText("maps")
    window.navigate("games")
    window.on_games_found([Game(20, "Beta")])
    assert window.browse.mode == MODE_GRID
    assert window.current_game.appid == 10
    assert window.browse.modSearchEdit.text() == "maps"


def test_card_list_preserve_shared_selection_and_model(qapp):
    page = BrowsePage()
    page.set_items([WorkshopItem(n, appid=10, title=f"Mod {n}") for n in range(10)], 10, 1, 1)
    select(page, 2)
    select(page, 4)
    model = page.cards.model()
    page.set_presentation("list")
    assert page.cards.model() is model
    assert {it.publishedfileid for it in page.selected_items()} == {2, 4}
    assert page.cards.currentIndex().row() == 4
    page.set_presentation("cards")
    assert {it.publishedfileid for it in page.selected_items()} == {2, 4}


def test_presentation_optional_backwards_compatible_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"version": 1, "recent": []}')
    state = AppState(path)
    assert state.browse_presentation == "cards"
    state.set_browse_presentation("list")
    assert AppState(path).browse_presentation == "list"
    path.write_text('{"browse_presentation": {"bad": true}}')
    assert AppState(path).browse_presentation == "cards"


@pytest.mark.parametrize("width", [960, 1150, 1440])
def test_details_in_page_close_restores_selection_focus_and_scroll(window, qapp, width):
    window.resize(width, 900 if width == 1440 else 640)
    window.show()
    window.current_game = Game(10, "Alpha")
    window.browse.set_game_context(window.current_game)
    window.browse.set_mode(MODE_GRID)
    window.navigate("browse")
    window._items_ready(10, [WorkshopItem(n, appid=10, title=f"Mod {n}") for n in range(60)], 60, 1)
    qapp.processEvents()
    window.browse.cards.verticalScrollBar().setValue(80)
    scroll = window.browse.cards.verticalScrollBar().value()
    window.browse.cards.selectionModel().select(window.browse.grid_model.index(0), QItemSelectionModel.SelectionFlag.Select)
    window.browse._selection_timer.stop()
    window.browse._emit_selection()
    qapp.processEvents()
    assert window.browse._details_open
    assert window.browse.content.isHidden() == (width < 1280)
    window.browse.inspector.close_btn.click()
    qapp.processEvents()
    assert not window.browse._details_open
    assert not window.browse.content.isHidden()
    assert window.browse.cards.hasFocus()
    assert [item.publishedfileid for item in window.browse.selected_items()] == [0]
    assert window.browse.cards.verticalScrollBar().value() == scroll
    window._on_resize()
    assert not window.browse._details_open


def test_stale_inspector_response_after_close_is_ignored(window):
    callbacks = []
    window.hub.call = lambda fn, done, **kw: callbacks.append(done)
    window.current_game = Game(10, "Alpha")
    window.browse.set_mode(MODE_GRID)
    window.navigate("browse")
    window.browse.set_items([WorkshopItem(100, appid=10, title="Original")], 1, 1, 1)
    select(window.browse, 0)
    window.browse.dismiss_details()
    callbacks[-1](ItemDetails(100, appid=10, title="Stale title"))
    assert window.browse.inspector.title_label.text() == "Original"
    assert not window.browse._details_open


def test_collection_details_primary_action_reviews_import(window):
    inspector = window.browse.inspector
    inspector.set_place(WorkshopItem(100, appid=10))
    inspector.set_details(ItemDetails(100, appid=99, title="Collection", file_type=2), 10)
    window._open_bulk = Mock()
    inspector.download_btn.click()
    window._open_bulk.assert_called_once_with("100")
    assert inspector.item.appid == 99


def test_installed_proxy_scope_search_status_and_action_target(qapp, tmp_path):
    page = LibraryPage()
    a = InstalledItem(10, 100, tmp_path / "a", title="A map")
    b = InstalledItem(20, 200, tmp_path / "b", title="A map from Beta")
    page.show_items([a, b], tmp_path)
    page.apply_update_status({100: UpdateInfo(100, UPDATE_AVAILABLE)})
    page.set_game_context(Game(10, "Alpha"))
    assert page.visible_items() == [a]
    page.search.setText("map")
    page.update_filter.setCurrentIndex(page.update_filter.findData(UPDATE_AVAILABLE))
    assert page.proxy.rowCount() == 1
    targets = []
    page.action_requested.connect(lambda item, action: targets.append((item, action)))
    page.table.setCurrentIndex(page.proxy.index(0, 0))
    next(btn for btn in page.action_buttons if btn.text() == "Re-download").click()
    assert targets == [(a, "Re-download")]
    page.set_installed_scope(None)
    assert page.visible_items() == [a, b]
    page.table.setCurrentIndex(page.proxy.index(1, 0))
    assert page.table.currentIndex().data(InstalledItemRole) is b
    assert page.path_label.text() == str(b.path)


def test_installed_restores_each_game_scope_context(qapp, tmp_path):
    page = LibraryPage()
    page.show_items([InstalledItem(10, 100, tmp_path, title="Alpha")], tmp_path)
    page.set_game_context(Game(10, "Alpha"))
    page.search.setText("Alpha")
    page.set_game_context(Game(20, "Beta"))
    page.search.setText("Beta")
    page.set_game_context(Game(10, "Alpha"))
    assert page.search.text() == "Alpha"
    assert page.visible_items()[0].fileid == 100


def test_update_and_cleanup_review_only_displayed_scope(window, tmp_path, monkeypatch):
    a = InstalledItem(10, 100, tmp_path / "a", title="Alpha")
    b = InstalledItem(20, 200, tmp_path / "b", title="Beta")
    window.library.show_items([a, b], tmp_path)
    window.library.apply_update_status({fid: UpdateInfo(fid, UPDATE_AVAILABLE) for fid in (100, 200)})
    window.library.set_game_context(Game(10, "Alpha"))
    groups = [DuplicateGroup(it.appid, it.fileid, [it], it) for it in (a, b)]
    window._duplicate_groups = groups
    reviewed = []
    class Review:
        def __init__(self, entries, parent=None):
            reviewed.append(entries)
        def exec(self):
            return QDialog.DialogCode.Rejected
        def deleteLater(self):
            pass
    monkeypatch.setattr("osw.gui.main_window.UpdateAllDialog", Review)
    monkeypatch.setattr("osw.gui.main_window.CleanupDialog", Review)
    window._update_all()
    window._review_duplicates()
    assert [entry[0] for entry in reviewed[0]] == [a]
    assert reviewed[1] == [groups[0]]
    window.library.set_installed_scope(None)
    window._review_duplicates()
    assert reviewed[2] == groups


def test_import_replacing_same_source_invalidates_resolution(qapp):
    page = ImportPage()
    page.set_source("100", hint="10", dependencies=False, auto_resolve=False)
    page.resolve_finished(DownloadResolution(items=[WorkshopItem(100, appid=99)]))
    generation = page.generation
    page.set_source("100", hint="10", dependencies=False, auto_resolve=False)
    assert page.generation > generation
    assert page.resolution is None
    assert page.tmodel.rowCount() == 0
    assert not page.queue_button.isEnabled()


def test_settings_validation_and_feedback(qapp, tmp_path):
    page = SettingsPage()
    saved = []
    page.save_requested.connect(lambda *args: saved.append(args))
    page.root_edit.clear()
    page.save_btn.click()
    assert "folder" in page.saved_label.text()
    assert not saved
    page.root_edit.setText(str(tmp_path))
    page.account_check.setChecked(True)
    page.save_btn.click()
    assert "username" in page.saved_label.text()
    page.user_edit.setText("example")
    page.save_btn.click()
    assert saved and saved[0][1] == "example"
    page.confirm_saved()
    assert page.saved_label.text() == "Settings saved"


def test_idle_footer_hides_progress_and_concurrency_is_truthful(window):
    window.strip.update_state("", "No active downloads", False, 0, 0, 0)
    assert window.strip.progress.isHidden()
    assert window.strip.spinner.isHidden()
    window.downloads.set_concurrency(3)
    assert "3 games" in window.downloads.subheader.text()
    window.downloads.set_concurrency(1)
    assert "One download" in window.downloads.subheader.text()


def test_queued_only_footer_does_not_animate_an_unstarted_transfer(window):
    window.manager.add_direct(10, 20)
    window._refresh_jobs()
    assert window.strip.queued_count == 1
    assert window.strip.progress.isHidden()
    assert window.strip.spinner.isHidden()


def test_download_progress_preserves_focused_recovery_action(qapp, tmp_path):
    from dataclasses import replace

    from osw.gui.downloads_page import DownloadsPage
    from osw.queue import JobSnapshot, JobState

    page = DownloadsPage()
    failed = JobSnapshot("failed", 10, "Alpha", 100, "Failed mod", tmp_path,
                         JobState.FAILED, 0, "Access denied", 1, "", "", (), False)
    running = replace(failed, id="running", fileid=200, state=JobState.RUNNING)
    page.upsert(failed)
    page.upsert(running)
    page.resize(960, 640)
    page.show()
    page.table.setCurrentIndex(page.model.index(0, 0))
    qapp.processEvents()
    retry = next(button for button in page.action_buttons if button.text() == "Retry")
    retry.setFocus()
    page.upsert(replace(running, progress=51))
    qapp.processEvents()
    assert retry in page.action_buttons
    assert retry.hasFocus()
    target = []
    page.action_requested.connect(lambda jobid, action: target.append((jobid, action)))
    retry.click()
    assert target == [("failed", "Retry")]


def test_download_filter_membership_change_keeps_selected_job_identity(qapp, tmp_path):
    from dataclasses import replace

    from osw.gui.downloads_page import DownloadsPage
    from osw.gui.item_models import JobFilter
    from osw.queue import JobSnapshot, JobState

    page = DownloadsPage()
    first = JobSnapshot("first", 10, "Alpha", 100, "First", tmp_path,
                        JobState.RUNNING, 10, "", 1, "", "", (), False)
    second = replace(first, id="second", fileid=200, title="Second")
    page.upsert(first)
    page.upsert(second)
    page.set_filter(filt=JobFilter.ACTIVE)
    page.table.setCurrentIndex(page.model.index(1, 0))
    page.upsert(replace(first, state=JobState.DONE))
    assert page.model.job_id(page.table.currentIndex().row()) == "second"
    actions = []
    page.action_requested.connect(lambda jobid, action: actions.append((jobid, action)))
    next(button for button in page.action_buttons if button.text() == "Cancel").click()
    assert actions == [("second", "Cancel")]


def test_large_installed_metadata_batch_coalesces_scope_refresh(qapp, tmp_path):
    from osw.gui.library import InstalledMetadata

    page = LibraryPage()
    page.show_items([InstalledItem(10, n+1, tmp_path / str(n), title=f"Mod {n}")
                     for n in range(2000)])
    page.set_game_context(Game(10, "Alpha"))
    page.search.setText("Updated")
    assert page.proxy.rowCount() == 0
    page.apply_metadata({n+1: InstalledMetadata(f"Updated {n}", "Alpha") for n in range(100)})
    assert page._filter_timer.isActive()
    qapp.processEvents()
    assert not page._filter_timer.isActive()
    assert page.proxy.rowCount() == 100
    assert "100 installed items" in page.summary.text()
    assert page._stack.currentIndex() == 0


def test_switch_back_to_inflight_game_retries_restored_query(window):
    window.games = [Game(10, "Alpha"), Game(20, "Beta")]
    window._select_app(10)
    window.browse.modSearchEdit.setText("pending search")
    window._do_browse()
    window._select_app(20)
    previous = window._requests["browse"]
    window._select_app(10)
    assert window.current_game.appid == 10
    assert window.browse.workshop_search_text() == "pending search"
    assert window._requests["browse"] > previous
    assert window._browse_loading
    assert "Loading Workshop" in window.browse.grid_state.text()


def test_switch_back_to_inflight_name_lookup_retries_name(window):
    window._select_app(10)
    window._select_app(20)
    previous = window._requests["app"]
    window._select_app(10)
    assert window.current_game.appid == 10
    assert window._requests["app"] > previous
    assert "Loading game" in window.browse.grid_state.text()
