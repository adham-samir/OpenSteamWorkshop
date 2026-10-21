"""OpenSteamWorkshop — Transfer Desk shell.

MainWindow (QMainMenu) is the stable entry point: the shell/controller owning
the async Hub, the download manager, request generations, and navigation state.
Presentation lives in browse_page / imports_page / downloads_page /
settings_page plus the nav rail and status strip. Pages emit user-intent
signals; the controller performs the existing async work and feeds
renderable state back to the pages' models.

All network/steamcmd work happens in QThreadPool workers; results come back
through Qt signals (auto-queued), so the UI thread never blocks.
"""

from __future__ import annotations

import hashlib
import mimetypes
import threading
from pathlib import Path

from PySide6.QtCore import (
    QItemSelectionModel,
    QLockFile,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..models import Game, ItemDetails, WorkshopItem, fmt_count
from ..queue import ACTIVE, DownloadManager, JobSnapshot, JobState
from ..settings import CONFIG_DIR, get, save
from ..steam_api import (
    browse_workshop,
    get_app_name,
    get_item_details,
    resolve_ids,
    search_games,
)
from . import theme
from .browse_page import MODE_GRID, MODE_HERO, MODE_RESULTS, BrowsePage
from .downloads_page import DownloadsPage
from .imports_page import ImportPage
from .library import (
    InstalledIndex,
    content_dir,
    delete_installed_item,
    fetch_installed_metadata,
    scan_installed,
)
from .library_page import LibraryPage
from .nav_rail import NavRail
from .settings_page import SettingsPage
from .state import AppState
from .status_strip import StatusStrip

CACHE_DIR = Path.home() / ".cache" / "OpenSteamWorkshop" / "thumbs"
PAGE_KEYS = ("browse", "imports", "library", "downloads", "settings")


def fetch_bytes(url: str, cancel=None) -> bytes:
    from ..net import http

    return http.request(url, cancel=cancel)


# ----------------------------------------------------------------- plumbing


class Async(QObject):
    """Signal carrier; work is done by _Runner and results emitted here."""

    fin = Signal(bool, object)

    def __init__(self, fn, parent=None, on_ok=None, on_error=None, on_done=None):
        super().__init__(parent)
        self.fn = fn
        self.on_ok, self.on_error, self.on_done = on_ok, on_error, on_done
        self.fin.connect(self._complete, Qt.QueuedConnection)

    @Slot(bool, object)
    def _complete(self, ok, result):
        try:
            if ok:
                if self.on_ok:
                    self.on_ok(result)
            elif self.on_error:
                self.on_error(result)
        except Exception as exc:
            if self.parent():
                self.parent().error.emit(f"Internal error: {exc}")
        finally:
            if self.on_done:
                self.on_done()
            self.deleteLater()


class _Runner(QRunnable):
    def __init__(self, fn, carrier: Async):
        super().__init__()
        self.fn = fn
        self.carrier = carrier

    def run(self):
        try:
            ok, res = True, self.fn()
        except Exception as e:  # surfaced to the UI thread
            ok, res = False, e
        try:
            self.carrier.fin.emit(ok, res)
        except RuntimeError:
            pass  # window has closed


class Hub(QObject):
    """Async dispatcher + signal board shared by all worker jobs."""

    thumbs = Signal(object, object)  # fileid, image bytes
    error = Signal(str)
    logMessage = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tp = QThreadPool.globalInstance()
        self.tp.setMaxThreadCount(14)
        self.cancel = threading.Event()

    def call(self, fn, on_ok=None, *, on_error=None, on_done=None):
        """Schedule fn(); later run on_ok(result) or emit error(msg)."""
        carrier = Async(fn, self, on_ok, on_error or (lambda e: self.error.emit(str(e))), on_done)
        self.tp.start(_Runner(fn, carrier))


class ThumbJob(QRunnable):
    """Fetch one preview image (cache on disk), emit (fileid, bytes)."""

    def __init__(self, hub: Hub, url: str, fileid: int):
        super().__init__()
        self.hub, self.url, self.fileid = hub, url, fileid

    def run(self):
        kind = mimetypes.guess_type(self.url)[0] or "image/jpeg"
        ext = mimetypes.guess_extension(kind) or ".jpg"
        path = CACHE_DIR / (hashlib.sha1(self.url.encode()).hexdigest()[:20] + ext)
        data = None
        if path.is_file():
            try:
                data = path.read_bytes()
            except OSError:
                data = None
        if not data:
            try:
                data = fetch_bytes(self.url, self.hub.cancel)
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            except Exception:
                return
        try:
            self.hub.thumbs.emit(self.fileid, data)
        except RuntimeError:
            pass  # UI already torn down; nothing to frame


# ---------------------------------------------------------------- main window


class _BarCompat:
    """Minimal progress-bar stand-in for the legacy ``_job_rows`` API."""

    def __init__(self):
        self._hidden = True
        self._value = 0

    def isHidden(self):  # noqa: N802
        return self._hidden

    def value(self):
        return self._value

    def setValue(self, value):  # noqa: N802
        self._value = int(value)

    def set_progress(self, visible: bool, value: float) -> None:
        self._hidden = not visible
        self._value = int(value)


class _ActionCompat:
    """Minimal button stand-in for the legacy ``_job_rows`` API."""

    def __init__(self):
        self._enabled = False

    def isEnabled(self):  # noqa: N802
        return self._enabled

    def setEnabled(self, enabled):  # noqa: N802
        self._enabled = bool(enabled)


class _JobRowCompat:
    """Adapter preserving ``window._job_rows[job.id]['bar'|'retry'|'cancel']``."""

    def __init__(self):
        self._items = {
            "bar": _BarCompat(),
            "retry": _ActionCompat(),
            "cancel": _ActionCompat(),
        }

    def __getitem__(self, key):
        return self._items[key]

    def update(self, snapshot: JobSnapshot) -> None:
        active = snapshot.state in ACTIVE
        self._items["bar"].set_progress(active, snapshot.progress)
        self._items["cancel"].setEnabled(active)
        self._items["retry"].setEnabled(
            snapshot.state in (JobState.FAILED, JobState.INTERRUPTED)
        )


class _GridItemCompat:
    def __init__(self, view, index):
        self._view = view
        self._index = index

    def setSelected(self, selected: bool) -> None:  # noqa: N802
        model = self._view.selectionModel()
        if model is None or not self._index.isValid():
            return
        flag = (
            QItemSelectionModel.SelectionFlag.Select
            if selected
            else QItemSelectionModel.SelectionFlag.Deselect
        )
        model.select(self._index, flag | QItemSelectionModel.SelectionFlag.Rows)


class _GridCompat:
    """Legacy QListWidget-style access over the model-backed card view."""

    def __init__(self, view):
        self._view = view

    def item(self, row: int) -> _GridItemCompat:
        model = self._view.model()
        return _GridItemCompat(self._view, model.index(row, 0) if model else None)


class MainWindow(QMainWindow):
    """Transfer Desk shell/controller; run() creates it."""

    jobEvent = Signal(object)  # fired from worker threads, auto-queued
    authEvent = Signal(object)

    def __init__(self, queue_path=None):
        super().__init__()
        self.setWindowTitle("OpenSteamWorkshop")
        self.resize(1150, 740)
        self.setMinimumSize(960, 640)

        self.games: list[Game] = []
        self.current_game: Game | None = None
        self.items: list[WorkshopItem] = []
        self.page = 1
        self.total_pages = 1
        self._game_term = ""
        self._requests: dict = {}
        self._closing = False
        self._selection: list[WorkshopItem] = []
        self._queue_path = Path(queue_path) if queue_path else CONFIG_DIR / "queue.json"
        self._job_snapshots: dict[str, JobSnapshot] = {}
        self._job_rows: dict[str, _JobRowCompat] = {}
        self.state = AppState()
        self.installed = InstalledIndex()
        self._installed_ready = False
        self._installed_generation = 0
        self._library_scan_generation = 0
        self._library_scan_cancel = threading.Event()
        self._library_meta_cancel = threading.Event()
        self._library_content_dir: Path | None = None

        self.hub = Hub(self)
        self.hub.thumbs.connect(self.on_thumb)
        self.hub.error.connect(self.on_error)
        self.hub.logMessage.connect(self.statusBar().showMessage)

        self.manager = self._build_manager()
        self.manager.on_job_update = self.jobEvent.emit  # worker-thread emit
        self.manager.on_log = lambda m: self.hub.logMessage.emit(m)
        self.manager.on_auth = self._request_auth
        self.jobEvent.connect(self._on_job_ui)
        self.authEvent.connect(self._show_auth, Qt.QueuedConnection)

        self._build_ui()
        self._refresh_installed_index()
        for job in self.manager.jobs:
            self._on_job_ui(job.snapshot())
        self.update_strip()
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self.navigate("browse"))
        QShortcut(QKeySequence("Ctrl+2"), self, activated=lambda: self.navigate("imports"))
        QShortcut(QKeySequence("Ctrl+3"), self, activated=lambda: self.navigate("downloads"))
        QShortcut(QKeySequence("Ctrl+4"), self, activated=lambda: self.navigate("settings"))
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: self.navigate("library"))
        QShortcut(QKeySequence("/"), self, activated=self._focus_workshop_search)

    # compatibility names kept for tests and automation

    @property
    def gameSearchEdit(self):
        return self.browse.game_search

    @property
    def findBtn(self):
        return self.browse.find_button

    @property
    def browserMessage(self):
        return self.browse.browserMessage

    @property
    def modsGrid(self):
        return _GridCompat(self.browse.cards)

    # workspace aliases used by automation and accessibility tooling

    @property
    def workspace(self) -> str:
        for key, page in self._pages.items():
            if page is self.page_stack.currentWidget():
                return key
        return "browse"

    @property
    def sidebar(self):
        return self.nav

    @property
    def stack(self):
        return self.page_stack

    @property
    def status_strip(self):
        return self.strip

    @property
    def settings(self):
        return self.settings_page

    # --------------------------------------------------------------- build

    def _build_manager(self) -> DownloadManager:
        return DownloadManager(
            content_root=Path(get("content_root")),
            steamcmd_dir=(Path(get("steamcmd_dir")) if get("steamcmd_dir") else None),
            queue_path=self._queue_path,
            parallel=1,
        )

    def _request(self, key, fn, on_ok, on_done=None):
        """Bump generation; stale responses are dropped, never applied."""
        generation = self._requests.get(key, 0) + 1
        self._requests[key] = generation

        def current():
            return not self._closing and self._requests.get(key) == generation

        self.hub.call(
            fn,
            lambda result: on_ok(result) if current() else None,
            on_error=lambda exc: self.on_error(str(exc)) if current() else None,
            on_done=lambda: on_done() if current() and on_done else None,
        )

    def _build_ui(self):
        self.nav = NavRail()
        self.nav.navigate.connect(self.navigate)
        self.browse = BrowsePage()
        self.imports = ImportPage()
        self.library = LibraryPage()
        self.downloads = DownloadsPage()
        self.settings_page = SettingsPage()
        self._pages = {
            "browse": self.browse,
            "imports": self.imports,
            "library": self.library,
            "downloads": self.downloads,
            "settings": self.settings_page,
        }
        self.page_stack = QStackedWidget()
        for key in PAGE_KEYS:
            self.page_stack.addWidget(self._pages[key])
        self.page_stack.setCurrentWidget(self.browse)

        self.strip = StatusStrip()
        self.strip.activated.connect(lambda: self.navigate("downloads"))

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.nav)
        row.addWidget(self.page_stack, 1)
        work = QWidget()
        work.setLayout(row)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(work, 1)
        layout.addWidget(self.strip)
        holder = QWidget()
        holder.setLayout(layout)
        self.setCentralWidget(holder)

        self.statusBar().showMessage("Ready — SteamCMD will be downloaded on first use.")

        self._wire_browse()
        self._wire_imports()
        self._wire_library()
        self._wire_downloads()
        self._wire_settings()
        self._wire_inspector()
        self._refresh_personal()
        self._on_resize()

    # ---------------------------------------------------------- wiring

    def _wire_browse(self) -> None:
        browse = self.browse
        browse.game_search_requested.connect(self._game_search)
        browse.app_picked.connect(self._select_app)
        browse.change_game_requested.connect(self._change_game)
        browse.workshop_change_requested.connect(self.refresh)
        browse.sort_change_requested.connect(self.refresh)
        browse.page_requested.connect(self._goto_page)
        browse.import_requested.connect(self._open_bulk_without_prefill)
        browse.selection_changed.connect(self._on_selection_count)
        browse.selection_items_changed.connect(self._on_selection_items)
        browse.bulk_download_requested.connect(self._download_selected)
        browse.item_action_requested.connect(self._on_item_action)
        browse.favorite_toggled.connect(self._toggle_favorite)
        browse.results.pin_requested.connect(self._toggle_favorite)
        browse.mods_folder_change_requested.connect(self._choose_mods_folder)
        browse.mods_folder_clear_requested.connect(self._clear_mods_folder)
        browse.mods_folder_open_requested.connect(self._open_game_mods_folder)

    def _wire_imports(self) -> None:
        self.imports.resolve_requested.connect(self._resolve_import)
        self.imports.queue_requested.connect(self._queue_many)

    def _wire_library(self) -> None:
        self.library.refresh_requested.connect(self._scan_library)
        self.library.open_root_requested.connect(self._open_library_root)
        self.library.action_requested.connect(self._on_library_action)

    def _wire_downloads(self) -> None:
        self.downloads.action_requested.connect(self._on_job_action)
        self.downloads.page_action.connect(self._on_downloads_page_action)

    def _wire_settings(self) -> None:
        self.settings_page.save_requested.connect(self._save_settings)

    def _wire_inspector(self) -> None:
        inspector = self.browse.inspector
        inspector.download_clicked.connect(self._inspector_download)
        inspector.deps_clicked.connect(self._inspector_deps)
        inspector.copy_clicked.connect(lambda item: self._copy(item.url))
        inspector.browser_clicked.connect(
            lambda item: QDesktopServices.openUrl(QUrl(item.url))
        )

    # ---------------------------------------------------- navigation

    def navigate(self, key: str) -> None:
        if key not in self._pages:
            return
        if key != "library" and self.page_stack.currentWidget() is self.library:
            self._library_scan_cancel.set()
            self._library_meta_cancel.set()
        page = self._pages[key]
        self.page_stack.setCurrentWidget(page)
        self.nav.set_active(key)
        self.setWindowTitle("OpenSteamWorkshop — " + key.title())
        if key == "settings":
            self._load_settings()
        if key == "library":
            self._scan_library()
            self.statusBar().showMessage(
                "Library: installed Workshop content from your mods root and per-game folders."
            )
        if key == "browse" and not self.current_game:
            if self.games:
                self.browse.set_mode(MODE_RESULTS)
            else:
                self.browse.set_mode(MODE_HERO)
        if key == "browse":
            self.statusBar().showMessage(
                "Browse: search a game, or import Workshop links from any workspace."
            )

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._on_resize()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        # A window resized while hidden does not receive a resize event on show.
        QTimer.singleShot(0, self._on_resize)

    def _on_resize(self) -> None:
        compact = self.width() < 1120
        self.nav.set_compact(compact)
        self.strip.set_narrow(self.width() < 1080)
        show_inspector = (
            self.width() >= 1080
            and len(self._selection) == 1
            and self.page_stack.currentWidget() is self.browse
            and self.browse.mode == MODE_GRID
        )
        if not show_inspector:
            self.browse.set_inspector(False)
        elif self.browse.inspector.isHidden():
            self.browse.set_inspector(True)

    def _focus_search(self) -> None:
        if self.page_stack.currentWidget() is not self.browse:
            self.navigate("browse")
        self.browse.focus_game_search()

    def _focus_workshop_search(self) -> None:
        if self.page_stack.currentWidget() is self.browse:
            self.browse.focus_workshop_search()

    # ---------------------------------------------------------- callbacks

    def on_error(self, msg: str) -> None:
        m = msg.strip()
        if "Workshop page is missing" in m or "redesign" in m:
            QMessageBox.warning(self, "Steam page changed", m)
        else:
            self.statusBar().showMessage(f"Error: {m}", 8000)
        self.browse.set_grid_state(None)
        self.browse.browserMessage.setText(f"Error: {m} — try again, or import Workshop links directly.")

    # ----------------------------------------------------------- game search

    def _game_search(self, term: str = "") -> None:
        text = (term or self.browse.game_search.text()).strip()
        if not text:
            self.browse.focus_game_search()
            return
        self._game_term = text
        self._requests["games"] = self._requests.get("games", 0) + 1
        for key in ("app", "details"):
            self._requests[key] = self._requests.get(key, 0) + 1
        appid, fileids = resolve_ids(text)
        if fileids:
            self._open_from_url(appid, fileids)
            self.browse.find_button.setEnabled(True)
            return
        if appid:
            self._select_app(appid)
            return
        self.browse.find_button.setEnabled(False)
        self.statusBar().showMessage(f"Searching store for {text!r}…")
        self.browse.results.set_message(f"Searching store for “{text}”…")
        self._request(
            "games",
            lambda: search_games(text, self.hub.cancel),
            self.on_games_found,
            lambda: self.browse.find_button.setEnabled(True),
        )

    def on_games_found(self, games) -> None:
        self.browse.find_button.setEnabled(True)
        self.games = games or []
        old = self.current_game
        term = self._game_term
        self.browse.set_games(term, self.games)
        self.browse.results.set_favorites(self.state.favorite_ids())
        if not self.games:
            # keep browsing context; the results list doubles as confirmation
            self.current_game = old
            self.statusBar().showMessage(
                f'No store results for "{term}" — try pasting the appid directly', 8000
            )
            return
        if old is None and not self._selection:
            self.statusBar().showMessage(f"{len(self.games)} result(s) — click a game to browse", 8000)
        for g in self.games:
            if not g.image:
                continue
            generation = self._requests.get("games")
            self.hub.call(
                lambda url=g.image: fetch_bytes(url, self.hub.cancel),
                lambda data, appid=g.appid, gen=generation: self._set_game_icon(
                    appid, data, gen
                ),
                on_error=lambda _: None,
            )

    def _set_game_icon(self, appid: int, data: bytes, generation=None) -> None:
        if generation != self._requests.get("games"):
            return
        self.browse.update_game_thumb(appid, data)

    def _change_game(self) -> None:
        """'Change' → put the results panel / hero back in front."""
        self.browse.set_mode(MODE_RESULTS if self.games else MODE_HERO)
        self.browse.focus_game_search()

    def _select_app(self, appid: int) -> None:
        self.browse.find_button.setEnabled(True)
        for key in ("games", "browse", "details", "inspector"):
            self._requests[key] = self._requests.get(key, 0) + 1
        self.current_game = Game(appid, f"App {appid}")
        self.items = []
        self._selection = []
        self.browse.grid_model.set_items([])
        self.browse.set_browser_enabled(False)
        self.browse.set_game(appid, "")
        self.browse.set_mode(MODE_GRID)

        def work():
            return get_app_name(appid, self.hub.cancel)

        self._request("app", work, lambda name: self._after_name(appid, name))

    def _after_name(self, appid: int, name: str) -> None:
        if not self.current_game or self.current_game.appid != appid:
            return
        self.current_game = Game(appid=appid, name=name)
        self.browse.set_game(appid, name)
        self.browse.game_search.setText(name)
        self.browse.clear_workshop_search()
        self.setWindowTitle(f"OpenSteamWorkshop — {name}")
        self.page = 1
        self.browse.set_browser_enabled(True)
        self._remember_game(self.current_game)
        self.refresh()

    # ------------------------------------------------------- personal state

    def _remember_game(self, game: Game | None) -> None:
        self.state.record_game(game)
        self._refresh_personal()

    def _refresh_personal(self) -> None:
        self.browse.set_personal(self.state.recent_games(), self.state.favorite_games())
        self.browse.results.set_favorites(self.state.favorite_ids())
        if self.current_game is not None:
            self.browse.set_favorite(self.state.is_favorite(self.current_game.appid))
        self._refresh_mods_folder()

    # ---------------------------------------------------- per-game mods folder

    def _default_mods_root(self) -> Path:
        return Path(get("content_root")).expanduser()

    def _resolve_deliver_to(self, appid: int) -> Path | None:
        """Override folder for that game, or ``None`` for the default root."""
        path = self.state.game_path(int(appid)) if appid else None
        return path.expanduser().resolve() if path is not None else None

    def _refresh_mods_folder(self) -> None:
        override = (
            self.state.game_path(self.current_game.appid)
            if self.current_game is not None
            else None
        )
        self.browse.set_mods_folder(
            str(override) if override is not None else "",
            str(self._default_mods_root()),
        )

    def _choose_mods_folder(self) -> None:
        game = self.current_game
        if game is None:
            return
        start = self.state.game_path(game.appid) or self._default_mods_root()
        chosen = QFileDialog.getExistingDirectory(
            self, f"Choose mods folder for {game.name}", str(start)
        )
        if not chosen:
            return
        self.state.set_game_path(game.appid, chosen)
        self._refresh_mods_folder()
        self.statusBar().showMessage(
            f"{game.name}: new downloads install to {Path(chosen)}/<Item title>/", 8000
        )

    def _clear_mods_folder(self) -> None:
        game = self.current_game
        if game is None:
            return
        if self.state.clear_game_path(game.appid):
            self._refresh_mods_folder()
            self.statusBar().showMessage(
                f"{game.name}: using the default mods root again", 6000
            )

    def _open_game_mods_folder(self) -> None:
        game = self.current_game
        if game is None:
            return
        target = self.state.game_path(game.appid) or self._default_mods_root()
        if not target.exists():
            self.statusBar().showMessage(f"Folder not found: {target}", 6000)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _toggle_favorite(self, appid: int) -> None:
        game = None
        if self.current_game is not None and self.current_game.appid == appid:
            game = self.current_game
        if game is None:
            game = next((g for g in self.games if g.appid == appid), None)
        if game is None:
            game = next((g for g in self.state.recent if g.appid == appid), None)
        if game is None:
            game = next((g for g in self.state.favorites if g.appid == appid), None)
        if game is None:
            game = Game(appid, f"App {appid}")
        pinned = self.state.toggle_favorite(game)
        self._refresh_personal()
        verb = "Pinned" if pinned else "Unpinned"
        self.statusBar().showMessage(f"{verb} {game.name}", 4000)

    def _open_from_url(self, appid_guess, fileids) -> None:
        if not fileids:
            if appid_guess:
                self._select_app(appid_guess)
            return
        if len(fileids) > 1:
            self._open_bulk("\n".join(str(n) for n in fileids), appid_hint=appid_guess)
        else:
            fid = fileids[0]
            self.statusBar().showMessage("Loading item details…")
            self._request(
                "details",
                lambda: get_item_details(fid, self.hub.cancel),
                lambda det: self._show_details_dialog(det, appid_guess),
            )

    def _show_details_dialog(self, details: ItemDetails, fallback_appid=None) -> None:
        """Legacy item-details entry point; uses the item's own appid when known."""
        appid = details.appid or fallback_appid
        item = WorkshopItem(
            details.fileid,
            appid=appid or 0,
            title=details.title or f"Item {details.fileid}",
            short_description=details.description,
            author=details.author,
            author_url=details.author_url,
            tags=list(details.tags),
            file_type=details.file_type,
        )
        can_download = bool(appid) and not details.error

        dialog = QDialog(self)
        dialog.setWindowTitle(details.title or f"Workshop item {details.fileid}")
        layout = QVBoxLayout(dialog)
        title = QLabel(details.title or f"Workshop item {details.fileid}")
        title.setStyleSheet("font-size: 16px; font-weight: 650;")
        title.setWordWrap(True)
        layout.addWidget(title)

        meta = QLabel(
            f"Workshop ID {details.fileid}"
            + (f" · app {appid}" if appid else "")
            + (f" · by {details.author}" if details.author else "")
            + (f" · {details.file_size}" if details.file_size else "")
        )
        meta.setStyleSheet(f"color: {theme.TEXT2};")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        if details.description:
            body = QLabel(details.description[:1200])
            body.setWordWrap(True)
            layout.addWidget(body)
        if details.error:
            error = QLabel(details.error)
            error.setStyleSheet(f"color: {theme.BAD};")
            error.setWordWrap(True)
            layout.addWidget(error)
        if not can_download and not details.error:
            hint = QLabel("This item does not report a game ID, so it cannot be queued.")
            hint.setStyleSheet(f"color: {theme.WARN};")
            hint.setWordWrap(True)
            layout.addWidget(hint)

        buttons = QDialogButtonBox(dialog)
        download = buttons.addButton("Download", QDialogButtonBox.ButtonRole.AcceptRole)
        download.setEnabled(can_download)
        download.clicked.connect(lambda: self._queue_download(item))
        open_btn = buttons.addButton("Open in browser", QDialogButtonBox.ButtonRole.ActionRole)
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(item.url)))
        close = buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        close.clicked.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    # ---------------------------------------------------------------- browse

    def refresh(self) -> None:
        if not self.current_game:
            return
        self.page = 1
        self._do_browse()

    def _goto_page(self, delta: int) -> None:
        if not self.current_game:
            return
        self.page = max(1, min(self.total_pages, self.page + delta))
        self._do_browse()

    def _do_browse(self) -> None:
        appid = self.current_game.appid
        sort = self.browse.current_sort()
        text = self.browse.workshop_search_text()
        page = self.page
        self.browse.prevBtn.setEnabled(False)
        self.browse.nextBtn.setEnabled(False)
        self.browse.set_grid_state("Loading Workshop items…", "Fetching a page of mods.")
        self.statusBar().showMessage("Loading workshop items…")
        self._request(
            "browse",
            lambda: browse_workshop(
                appid, page=page, per_page=30, sort=sort, search_text=text, cancel=self.hub.cancel
            ),
            lambda res: self._items_ready(appid, *res, page=page),
            self._browse_finished,
        )

    def _browse_finished(self):
        self.browse.set_pager(self.page, self.total_pages)

    def _items_ready(self, appid: int, items: list, total: int, pages: int, page=None) -> None:
        if not self.current_game or appid != self.current_game.appid:
            return
        if page is not None:
            self.page = page
        self.items = items
        self.total_pages = pages or 1
        self.browse.set_items(items, total, self.page, self.total_pages)
        self.statusBar().showMessage(
            f"{len(items)} items on page {self.page}/{self.total_pages} · {fmt_count(total)} total"
        )
        for it in items:
            if it.preview_url:
                self.hub.tp.start(ThumbJob(self.hub, it.preview_url, it.publishedfileid))

    def on_thumb(self, fileid: int, data) -> None:
        self.browse.update_card_thumb(fileid, data)
        if self._selection and len(self._selection) == 1:
            single = self._selection[0]
            if single.publishedfileid == fileid:
                self.browse.inspector.set_cover(data)

    # ------------------------------------------------------------ selection

    def _on_selection_count(self, count: int) -> None:
        browse = self.browse
        self._selection = browse.selected_items()
        if count >= 2:
            browse.set_inspector(False)
        elif count == 1 and not self._closing:
            # single: show inspector (unless the window is too narrow)
            inspect = self.width() >= 1080
            browse.set_inspector(inspect)
        elif count == 0:
            browse.set_inspector(False)

    def _on_selection_items(self, items: list) -> None:
        if self._closing or len(items) != 1:
            return
        item = items[0]
        inspector = self.browse.inspector
        if self.browse.inspector.isHidden():
            return  # narrow window: bulk/single actions still work in the bulk bar
        highway = self.browse.card_thumb(item.publishedfileid)
        inspector.set_place(item)
        inspector.set_cover(highway)
        appid = item.appid or (self.current_game.appid if self.current_game else None)
        self._request(
            "inspector",
            lambda: get_item_details(item.publishedfileid, self.hub.cancel),
            lambda det: inspector.set_details(det, appid),
        )

    # ------------------------------------------------------------ item actions

    def _on_item_action(self, payload) -> None:
        item, action = payload
        if action == "download":
            self._queue_download(item)
        elif action == "preview":
            self._open_bulk(
                str(item.publishedfileid),
                dependencies=True,
                appid_hint=item.appid or (self.current_game.appid if self.current_game else None),
            )
        elif action == "copy":
            self._copy(item.url)
        elif action == "inspect":
            if self.browse.inspector.isHidden():
                self.browse.set_inspector(self.width() >= 1080)
            self.browse.cards.setCurrentIndex(self.browse.cards.indexAt(
                self.browse.cards.visualRect(self.browse.cards.currentIndex())
            ))

    def _inspector_download(self, item: WorkshopItem) -> None:
        if item.file_type == 2:
            self._open_bulk(str(item.publishedfileid))
        else:
            self._queue_download(item)

    def _inspector_deps(self, item: WorkshopItem) -> None:
        self._open_bulk(
            str(item.publishedfileid),
            dependencies=True,
            appid_hint=item.appid or (self.current_game.appid if self.current_game else None),
        )

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Copied to clipboard", 3000)

    def _queue_download(self, item: WorkshopItem) -> None:
        if item.file_type == 2:
            self._open_bulk(item.url)
            return
        self._ensure_manager_settings()
        hit = self._installed_for_queue().lookup(item.appid, item.publishedfileid)
        if hit is not None and not self._confirm_reinstall(hit):
            self.statusBar().showMessage(
                f"{item.title or item.publishedfileid}: already installed — skipped", 5000
            )
            return
        name = (
            self.current_game.name
            if self.current_game and self.current_game.appid == item.appid
            else ""
        )
        try:
            job = self.manager.add(
                item,
                name,
                deliver_to=self._resolve_deliver_to(item.appid),
                reinstall=hit is not None,
            )
            message = f"{job.title}: {job.state.value}"
            if job.deliver_to is not None:
                message += f" → {job.deliver_to}"
            self.statusBar().showMessage(message, 5000)
            self._on_job_ui(job.snapshot())
        except (ValueError, OSError) as exc:
            self.on_error(str(exc))

    def _confirm_reinstall(self, hit) -> bool:
        """Ask before re-downloading an item that is already on disk."""
        answer = QMessageBox.question(
            self,
            "Already installed",
            f"{hit.label} is already installed at:\n{hit.path}\n\n"
            "Download it again and overwrite the installed copy?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _installed_for_queue(self) -> InstalledIndex:
        """Return the installed index, syncing once if the async scan has not landed."""
        if not self._installed_ready:
            self._sync_installed_index()
        return self.installed

    def _sync_installed_index(self) -> None:
        self._installed_generation += 1
        root = Path(get("content_root"))
        paths = dict(self.state.game_paths)
        self.installed.content_root = root
        self.installed.game_paths = paths
        items = scan_installed(root, None, paths)
        if items is not None:
            self.installed.replace(items)
            self._installed_ready = True

    def _refresh_installed_index(self) -> None:
        """Rebuild the installed lookup off the UI thread."""
        self._installed_ready = False
        self._installed_generation += 1
        generation = self._installed_generation
        root = Path(get("content_root"))
        paths = dict(self.state.game_paths)
        self.installed.content_root = root
        self.installed.game_paths = paths

        def done(items):
            if self._closing or items is None or generation != self._installed_generation:
                return
            self.installed.replace(items)
            self._installed_ready = True

        self.hub.call(
            lambda: scan_installed(root, None, paths),
            done,
            on_error=lambda _exc: None,
        )

    def _ensure_manager_settings(self) -> None:
        self.manager.content_root = Path(get("content_root"))

    # ------------------------------------------------------------- bulk bar

    def _download_selected(self) -> None:
        selected = [item.publishedfileid for item in self.browse.selected_items()]
        if selected:
            self._open_bulk("\n".join(str(n) for n in selected))

    def _open_bulk_without_prefill(self) -> None:
        self._open_bulk()

    def _open_bulk(self, references="", *, dependencies=False, appid_hint=None):
        # Imports workspace instead of a blocking dialog; existing entry points prefill.
        self.navigate("imports")
        self.imports.set_source(
            references,
            hint=str(appid_hint if appid_hint is not None else (self.current_game.appid if self.current_game else "")),
            dependencies=dependencies,
            auto_resolve=bool(references.strip()),
        )

    def _resolve_import(self, references: str, hint: str, dependencies: bool) -> None:
        from ..bulk import resolve_downloads

        generation = self.imports.generation
        cancel = self.imports._cancel

        def done(result):
            if self._closing:
                return
            if self.imports.generation == generation:
                self.imports.resolve_finished(result)
                locations = {
                    fileid: item.summary
                    for fileid, item in self._installed_for_queue().locations().items()
                }
                if locations:
                    self.imports.mark_installed(locations)
            else:
                self.imports.resolve_cancelled()

        def failed(exc):
            if not self._closing and self.imports.generation == generation:
                self.imports.resolve_failed(str(exc))

        self.hub.call(
            lambda: resolve_downloads(
                references, int(hint) if hint else None, dependencies, cancel
            ),
            done,
            on_error=failed,
        )

    def _queue_many(self, items) -> None:
        self._ensure_manager_settings()
        try:
            jobs = self.manager.add_many(
                items, deliver_for=self._resolve_deliver_to, reinstall=True
            )
        except (ValueError, OSError) as exc:
            self.on_error(str(exc))
            self.imports.resolve_button.setEnabled(True)
            return
        self.imports.queue_accepted(len(jobs))
        self.statusBar().showMessage(f"{len(jobs)} mods added to the download queue", 5000)
        for job in jobs:
            self._on_job_ui(job.snapshot())
        self.navigate("downloads")

    # ------------------------------------------------------------ queue panel

    def _on_job_ui(self, job: JobSnapshot) -> None:
        if self._closing or self.manager.get_job(job.id) is None:
            return
        self._job_snapshots[job.id] = job
        self._job_rows.setdefault(job.id, _JobRowCompat()).update(job)
        self.downloads.upsert(job)
        if job.state is JobState.DONE and job.fileid:
            self.installed.record(
                job.appid,
                job.fileid,
                job.output_path or job.dest,
                title=job.title,
            )
        self.update_strip()

    def _refresh_jobs(self) -> None:
        """Re-read manager snapshots (used after direct/restored queue changes)."""
        live = {job.id for job in self.manager.jobs}
        for job_id in list(self._job_rows):
            if job_id not in live:
                self._job_rows.pop(job_id, None)
                self._job_snapshots.pop(job_id, None)
        for job in self.manager.jobs:
            self._job_rows.setdefault(job.id, _JobRowCompat()).update(job.snapshot())
        for job in self.manager.jobs:
            self._on_job_ui(job.snapshot())
        self.update_strip()

    def update_strip(self) -> None:
        """Status strip counts come only from JobSnapshot updates."""
        snapshots = [
            snap for snap in self._job_snapshots.values()
            if self.manager.get_job(snap.id) is not None
        ]
        queued = sum(1 for s in snapshots if s.state is JobState.QUEUED)
        failed = sum(1 for s in snapshots if s.state is JobState.FAILED)
        active = [s for s in snapshots if s.state in ACTIVE]
        running = [s for s in active if s.state is JobState.RUNNING]
        current = running[0] if running else (active[0] if active else None)
        if current is None:
            self.strip.update_state("", "No active downloads.", False, 0.0, queued, failed)
        else:
            progress_text = f"{current.progress:.0f}%" if current.progress > 0 else "starting…"
            self.strip.update_state(
                current.title,
                f"{current.state.value} · {progress_text}",
                True,
                current.progress,
                queued,
                failed,
            )
        self.nav.set_counts(queued, failed)
        self.downloads.update_counts()

    def _on_job_action(self, job_id: str, action: str) -> None:
        if action == "Cancel":
            self.manager.cancel(job_id)
        elif action == "Log":
            self._show_job_log(job_id)
        elif action == "Open folder":
            self._open_job_folder(job_id)
        elif action in ("Retry", "Resume"):
            self._retry_job(job_id)
        elif action == "Retry with account":
            self._retry_with_account(job_id)

    def _on_downloads_page_action(self, action: str) -> None:
        if action == "resume":
            self.manager.resume_unfinished()
        elif action == "retry":
            self._retry_failed()
        elif action == "clear":
            self._clear_finished()

    def _retry_job(self, job_id):
        self._ensure_manager_settings()
        self.manager.retry(job_id)

    def _retry_failed(self):
        for job in list(self.manager.jobs):
            if job.state is JobState.FAILED:
                self.manager.retry(job.id)

    def _clear_finished(self):
        for job_id in self.manager.clear_finished():
            self._job_snapshots.pop(job_id, None)
            self._job_rows.pop(job_id, None)
            self.downloads.remove(job_id)
        self.update_strip()
        self.statusBar().showMessage("Cleared finished downloads", 4000)

    def _show_job_log(self, job_id):
        job = self.manager.get_job(job_id)
        if not job:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Download log — {job.title}")
        dialog.resize(760, 440)
        layout = QVBoxLayout(dialog)
        log = QPlainTextEdit()
        log.setReadOnly(True)
        log.setPlainText("\n".join(job.snapshot().logs) or job.message)
        layout.addWidget(log)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
        dialog.deleteLater()

    def _open_job_folder(self, job_id):
        job = self.manager.get_job(job_id)
        if job and job.output_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(job.output_path))

    def _retry_with_account(self, job_id):
        username, accepted = QInputDialog.getText(
            self, "Retry with Steam account", "Steam username", text=get("username")
        )
        if accepted and username.strip():
            # Password/Guard will be requested only when SteamCMD needs them.
            self.manager.retry(job_id, username=username.strip(), password="")

    def _request_auth(self, job, kind, prompt, cancel):
        request = {
            "job": job,
            "kind": kind,
            "cancel": cancel,
            "ready": threading.Event(),
            "value": None,
        }
        self.authEvent.emit(request)
        while not request["ready"].wait(0.1):
            if cancel.is_set() or self._closing:
                return None
        return request["value"]

    @Slot(object)
    def _show_auth(self, request):
        try:
            if self._closing or request["cancel"].is_set():
                return
            if request["kind"] == "approval":
                self.statusBar().showMessage(
                    "Approve the sign-in request in your Steam mobile app."
                )
                request["value"] = ""
                return
            dialog = QInputDialog(self)
            dialog.setWindowTitle("Steam authentication")
            dialog.setLabelText(
                "Steam password" if request["kind"] == "password" else "Steam Guard code"
            )
            dialog.setTextEchoMode(QLineEdit.EchoMode.Password)
            timer = QTimer(dialog)
            timer.timeout.connect(lambda: dialog.reject() if request["cancel"].is_set() else None)
            timer.start(100)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                request["value"] = dialog.textValue()
            dialog.deleteLater()
        finally:
            request["ready"].set()

    # --------------------------------------------------------------- library

    def _scan_library(self) -> None:
        """Scan installed content off the UI thread; cancel any older scan."""
        self._library_scan_generation += 1
        generation = self._library_scan_generation
        self._library_scan_cancel.set()
        self._library_meta_cancel.set()
        scan_cancel = threading.Event()
        meta_cancel = threading.Event()
        self._library_scan_cancel = scan_cancel
        self._library_meta_cancel = meta_cancel

        root = Path(get("content_root"))
        path = content_dir(root)
        self._library_content_dir = path
        self.library.show_loading(path)
        game_paths = dict(self.state.game_paths)
        self.hub.call(
            lambda: scan_installed(root, scan_cancel, game_paths),
            lambda items: self._library_scanned(generation, path, items),
            on_error=lambda exc: self._library_scan_failed(generation, path, exc),
        )

    def _library_scanned(self, generation: int, path: Path, items) -> None:
        if self._closing or generation != self._library_scan_generation or items is None:
            return
        items = list(items)
        self.installed.replace(items)
        self._installed_ready = True
        self.library.show_items(items, path)
        self.nav.set_library_count(len(items))
        noun = "item" if len(items) == 1 else "items"
        self.statusBar().showMessage(
            f"Library: {len(items)} installed {noun}", 5000
        )
        if not items:
            return
        meta_cancel = self._library_meta_cancel
        self.hub.call(
            lambda: fetch_installed_metadata(items, meta_cancel),
            lambda metadata: self._library_metadata_ready(generation, meta_cancel, metadata),
            on_error=lambda _exc: None,
        )

    def _library_metadata_ready(self, generation: int, cancel: threading.Event, metadata) -> None:
        if (
            self._closing
            or cancel.is_set()
            or generation != self._library_scan_generation
            or not metadata
        ):
            return
        self.library.apply_metadata(metadata)

    def _library_scan_failed(self, generation: int, path: Path, exc) -> None:
        if self._closing or generation != self._library_scan_generation:
            return
        self.nav.set_library_count(0)
        self.library.show_error(str(exc), path)
        self.statusBar().showMessage(f"Could not scan the Library: {exc}", 8000)

    def _open_library_root(self) -> None:
        root = Path(get("content_root")).expanduser()
        path = self._library_content_dir or content_dir(root)
        target = path if path.exists() else root
        if not target.exists():
            self.statusBar().showMessage(f"Folder not found: {target}", 6000)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _on_library_action(self, item, action: str) -> None:
        if action == "Open folder":
            if not item.path.exists():
                self.statusBar().showMessage(f"Folder is missing: {item.path}", 6000)
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(item.path)))
        elif action == "Inspect in Browse":
            self._inspect_library_item(item)
        elif action == "Re-download":
            self._redownload_library_item(item)
        elif action == "Delete":
            self._delete_library_item(item)

    def _inspect_library_item(self, item) -> None:
        """Open Browse with the installed item's details in the inspector."""
        self.navigate("browse")
        if self.current_game is None or self.current_game.appid != item.appid:
            self._select_app(item.appid)
        elif self.browse.mode != MODE_GRID:
            self.browse.set_mode(MODE_GRID)
        work = WorkshopItem(
            item.fileid,
            appid=item.appid,
            title=item.title or f"Workshop item {item.fileid}",
            file_size=item.size,
        )
        self._selection = [work]
        inspector = self.browse.inspector
        inspector.set_place(work)
        inspector.set_cover(None)
        inspector.set_load_state(True)
        wide = self.width() >= 1080
        self.browse.set_inspector(wide)

        def show_details(details) -> None:
            if wide:
                inspector.set_details(details, item.appid)
            else:
                # The side inspector is reserved for wide layouts; keep the
                # action useful at 960 px with the existing details dialog.
                self._show_details_dialog(details, item.appid)

        self._request(
            "inspector",
            lambda: get_item_details(item.fileid, self.hub.cancel),
            show_details,
        )
        self.statusBar().showMessage(f"Inspecting {work.title} in Browse", 5000)

    def _redownload_library_item(self, item) -> None:
        self._ensure_manager_settings()
        dest = Path(get("content_root")).expanduser().resolve()
        deliver_to = self._resolve_deliver_to(item.appid)
        existing = next(
            (
                job
                for job in self.manager.jobs
                if (job.appid, job.fileid, job.dest, job.deliver_to)
                == (item.appid, item.fileid, dest, deliver_to)
            ),
            None,
        )
        if existing is not None:
            if existing.state not in ACTIVE:
                self.manager.retry(existing.id)
                self.statusBar().showMessage(f"Re-download queued: {item.label}", 5000)
            else:
                self.statusBar().showMessage(f"Already queued: {item.label}", 5000)
            return
        work = WorkshopItem(
            item.fileid,
            appid=item.appid,
            title=item.title or f"Workshop item {item.fileid}",
            file_size=item.size,
        )
        self._queue_download(work)

    def _delete_library_item(self, item) -> None:
        answer = QMessageBox.question(
            self,
            "Delete installed item",
            (
                f"Delete “{item.label}” from disk?\n\n"
                f"{item.path}\n\n"
                "This removes the installed files and cannot be undone."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_installed_item(item, get("content_root"))
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"Could not delete {item.label}: {exc}", 8000)
            return
        self.library.remove_item(item.fileid)
        self.installed.remove(item.appid, item.fileid)
        self.nav.set_library_count(self.library.model.rowCount())
        self.statusBar().showMessage(f"Deleted {item.label}", 5000)

    # --------------------------------------------------------------- settings

    def _open_settings(self) -> None:
        self.navigate("settings")

    def _load_settings(self) -> None:
        self.settings_page.load(
            content_root=str(get("content_root")),
            username=self.manager.username or get("username"),
            use_account=bool(self.manager.username),
            password=self.manager.password,
            steamcmd_dir=str(get("steamcmd_dir")),
        )

    def _save_settings(self, content_root, username, use_account, password, steamcmd_dir) -> None:
        try:
            save(
                {
                    "content_root": content_root,
                    "username": username,
                    "steamcmd_dir": steamcmd_dir,
                }
            )
        except OSError as exc:
            self.settings_page.show_error(f"Could not save settings: {exc}")
            return
        self.manager.content_root = Path(get("content_root"))
        self.manager.steamcmd_dir = get("steamcmd_dir") or None
        self.manager.username = username if use_account else ""
        self.manager.password = password if self.manager.username else ""
        self._refresh_mods_folder()
        self._refresh_installed_index()
        self.settings_page.confirm_saved()
        self.statusBar().showMessage("Settings saved", 5000)

    # ------------------------------------------------------------------ misc

    def closeEvent(self, event):  # noqa: N802
        self._closing = True
        self.hub.cancel.set()
        self._library_scan_cancel.set()
        self._library_meta_cancel.set()
        self.imports._stop()
        self.manager.shutdown()
        super().closeEvent(event)


# --------------------------------------------------------------------- run


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("OpenSteamWorkshop")
    app.setStyle("Fusion")
    theme.apply_theme()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(CONFIG_DIR / "gui.lock"))
    if not lock.tryLock(0):
        QMessageBox.warning(
            None,
            "OpenSteamWorkshop is running",
            "Another window already owns the saved download queue.",
        )
        return 1
    try:
        window = MainWindow()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        QMessageBox.critical(
            None,
            "Could not restore download queue",
            str(exc) + "\nThe queue file has been preserved.",
        )
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
