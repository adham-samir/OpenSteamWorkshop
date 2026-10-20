"""OpenSteamWorkshop — Qt GUI.

Layout:

+---------------------------------------------------------------+
| [game search .......] [Find game]          [⚙ Settings]       |
+--------------+------------------------------------------------+
|  game list   | [mod search.....] [sort combo]   ‹ page ›       |
|  (capsules)  +------------------------------------------------+
|              |        mod grid (thumbnail cards)              |
|              +------------------------------------------------+
|              |        download queue rows (progress bars)     |
+--------------+------------------------------------------------+

All network/steamcmd work happens in QThreadPool workers; results come back
through Qt signals (auto-queued), so the UI thread never blocks.
"""

from __future__ import annotations

import hashlib
import mimetypes
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QColor, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..models import Game, ItemDetails, WorkshopItem, fmt_count, fmt_size, fmt_unix
from ..queue import DownloadJob, DownloadManager, JobState
from ..settings import get, set_key
from ..steam_api import (
    SORTS,
    browse_workshop,
    get_app_name,
    get_item_details,
    resolve_ids,
    search_games,
)
from ..steamcmd import SteamCMDError

CACHE_DIR = Path.home() / ".cache" / "OpenSteamWorkshop" / "thumbs"
THUMB = 168
CARD_W, CARD_H = 184, 224


def fetch_bytes(url: str) -> bytes:
    from ..net import http

    return http.request(url)


# ----------------------------------------------------------------- plumbing


class Async(QObject):
    """Signal carrier; work is done by _Runner and results emitted here."""

    fin = Signal(bool, object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn


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
        self.carrier.fin.emit(ok, res)


class Hub(QObject):
    """Async dispatcher + signal board shared by all worker jobs."""

    thumbs = Signal(object, object)            # fileid, image bytes
    error = Signal(str)
    logMessage = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tp = QThreadPool.globalInstance()
        self.tp.setMaxThreadCount(14)

    def call(self, fn, on_ok=None):
        """Schedule fn(); later run on_ok(result) or emit error(msg)."""
        carrier = Async(fn, self)
        carrier.fin.connect(self._route(on_ok))
        self.tp.start(_Runner(fn, carrier))

    def _route(self, on_ok):
        def handler(ok: bool, res):
            if ok:
                if on_ok is not None:
                    try:
                        on_ok(res)
                    except Exception as e:  # bug inside a UI callback
                        self.error.emit(f"internal: {e}")
            else:
                msg = str(res)
                self.error.emit(msg)
        return handler


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
                data = fetch_bytes(self.url)
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            except Exception:
                return
        try:
            self.hub.thumbs.emit(self.fileid, data)
        except RuntimeError:
            pass  # UI already torn down; nothing to frame


# ---------------------------------------------------------------- main window


class MainWindow(QMainWindow):
    jobEvent = Signal(object)  # fired from worker threads, auto-queued

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenSteamWorkshop")
        self.resize(1150, 740)

        self.games: list[Game] = []
        self.current_game: Game | None = None
        self.items: list[WorkshopItem] = []
        self.page = 1
        self.total_pages = 1
        self._game_term = ""

        self.hub = Hub(self)
        self.hub.thumbs.connect(self.on_thumb)
        self.hub.error.connect(self.on_error)
        self.hub.logMessage.connect(self.statusBar().showMessage)

        self.manager = self._build_manager()
        self.manager.on_job_update = self.jobEvent.emit  # worker-thread emit
        self.manager.on_log = lambda m: self.hub.logMessage.emit(m)
        self.jobEvent.connect(self._on_job_ui)

        self._job_rows: dict[tuple[int, int], dict] = {}

        self._build_ui()
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)

    def _build_manager(self) -> DownloadManager:
        username = get("username")
        password = get("password") if get("remember_password") else ""
        return DownloadManager(
            content_root=Path(get("content_root")),
            steamcmd_dir=(Path(get("steamcmd_dir")) if get("steamcmd_dir") else None),
            username=username,
            password=password,
            parallel=max(1, int(get("parallel_downloads") or 2)),
        )

    # ------------------------------------------------------------- UI build

    def _build_ui(self):
        top = QWidget()
        v = QVBoxLayout(top)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # top bar
        bar = QHBoxLayout()
        self.gameSearchEdit = QLineEdit()
        self.gameSearchEdit.setPlaceholderText(
            "Search a game by name, or paste an appid / workshop / store URL")
        self.findBtn = QPushButton("Find game")
        self.findBtn.clicked.connect(self._game_search)
        self.gameSearchEdit.returnPressed.connect(self._game_search)
        menuBtn = QPushButton("⚙ Settings")
        menuBtn.clicked.connect(self._open_settings)
        bar.addWidget(self.gameSearchEdit, 1)
        bar.addWidget(self.findBtn)
        bar.addWidget(menuBtn)
        v.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        v.addWidget(split, 1)

        # left: game results
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.gameList = QListWidget()
        self.gameList.setWordWrap(True)
        self.gameList.itemClicked.connect(self.on_game_clicked)
        self.gameList.setFixedWidth(300)
        lv.addWidget(self.gameList, 1)
        split.addWidget(left)

        # right: mod browser
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(8, 0, 0, 0)
        cv.setSpacing(6)

        tools = QHBoxLayout()
        self.modSearchEdit = QLineEdit()
        self.modSearchEdit.setPlaceholderText("Search inside this game's workshop…")
        self.modSearchEdit.returnPressed.connect(self.refresh)
        modBtn = QPushButton("Mods")
        modBtn.clicked.connect(self.refresh)
        self.sortCombo = QComboBox()
        for key, label in SORTS.items():
            self.sortCombo.addItem(label, key)
        self.sortCombo.currentIndexChanged.connect(self.refresh)
        self.prevBtn = QPushButton("‹")
        self.nextBtn = QPushButton("›")
        self.prevBtn.clicked.connect(lambda: self._goto_page(-1))
        self.nextBtn.clicked.connect(lambda: self._goto_page(+1))
        self.pageLabel = QLabel("—")
        tools.addWidget(self.modSearchEdit, 1)
        self.modSearchBtn = modBtn
        tools.addWidget(self.modSearchBtn)
        tools.addWidget(self.sortCombo)
        tools.addWidget(self.prevBtn)
        tools.addWidget(self.pageLabel)
        tools.addWidget(self.nextBtn)
        cv.addLayout(tools)

        self.modsGrid = QListWidget()
        self.modsGrid.setObjectName("modsGrid")
        self.modsGrid.setViewMode(QListWidget.IconMode)
        self.modsGrid.setIconSize(QPixmap(THUMB, THUMB).size())
        self.modsGrid.setGridSize(QPixmap(CARD_W, CARD_H).size())
        self.modsGrid.setUniformItemSizes(True)
        self.modsGrid.setSpacing(6)
        self.modsGrid.setWordWrap(True)
        self.modsGrid.setResizeMode(QListWidget.Adjust)
        self.modsGrid.setMovement(QListWidget.Static)
        self.modsGrid.doubleClicked.connect(self._show_details)
        self.modsGrid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.modsGrid.customContextMenuRequested.connect(self._grid_menu)
        cv.addWidget(self.modsGrid, 1)

        # queue panel
        cap = QLabel("Downloads")
        cap.setStyleSheet("color:#9aa0a6; font-weight:600;")
        cv.addWidget(cap)
        self.queueScroll = QScrollArea()
        self.queueScroll.setWidgetResizable(True)
        self.queueScroll.setMinimumHeight(140)
        self.queueScroll.setMaximumHeight(200)
        self.queueInner = QWidget()
        self.queueLay = QVBoxLayout(self.queueInner)
        self.queueLay.setContentsMargins(2, 2, 2, 2)
        self.queueLay.setSpacing(4)
        self.queueLay.addStretch(1)
        self.queueScroll.setWidget(self.queueInner)
        cv.addWidget(self.queueScroll)

        split.addWidget(center)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)

        self.setCentralWidget(top)
        self.statusBar().showMessage("Ready — SteamCMD will be downloaded on first use.")

        self._set_browser_enabled(False)

        self.setStyleSheet("""
        QListWidget { background: #1f2024; border: 1px solid #34363c;
                      border-radius: 6px; font-size: 12px; }
        #modsGrid { border: 1px solid #34363c; }
        QLabel#page { color:#c9ccd1; }
        QPushButton { padding: 5px 14px; }
        QLineEdit { padding: 5px 8px; }
        """)

    def _set_browser_enabled(self, on: bool) -> None:
        for w in (
            self.modSearchEdit,
            self.modSearchBtn,
            self.sortCombo,
            self.prevBtn,
            self.nextBtn,
        ):
            w.setEnabled(on)
        self.pageLabel.setText("—")

    def _focus_search(self):
        self.gameSearchEdit.setFocus()
        self.gameSearchEdit.selectAll()

    # ------------------------------------------------------------ callbacks

    def on_error(self, msg: str) -> None:
        m = msg.strip()
        if "Workshop page is missing" in m or "redesign" in m:
            QMessageBox.warning(self, "Steam page changed", m)
        else:
            self.statusBar().showMessage(f"Error: {m}", 8000)

    # ----------------------------------------------------------- game search

    def _game_search(self) -> None:
        text = self.gameSearchEdit.text().strip()
        if not text:
            return
        self._game_term = text
        appid, fileids = resolve_ids(text)
        if fileids:
            self._open_from_url(appid, fileids)
            return
        if appid:
            self._select_app(appid)
            return
        self.findBtn.setEnabled(False)
        self.statusBar().showMessage(f"Searching store for {text!r}…")
        self.hub.call(lambda: search_games(text), self.on_games_found)

    def on_games_found(self, games) -> None:
        self.findBtn.setEnabled(True)
        self.games = games or []
        self.gameList.clear()
        term = self._game_term
        if not self.games:
            self.statusBar().showMessage(
                f'No store results for "{term}" — try pasting the appid directly', 8000)
            return
        self.statusBar().showMessage(
            f"{len(self.games)} result(s) — click a game to browse its workshop", 8000)
        for g in self.games:
            it = QListWidgetItem(g.name)
            it.setData(Qt.UserRole, g.appid)
            it.setSizeHint(QPixmap(280, 92).size())
            ph = QPixmap(280, 92)
            ph.fill(QColor(0x2a, 0x2c, 0x30))
            it.setIcon(ph)
            self.gameList.addItem(it)
            if g.image:
                self.hub.call(lambda url=g.image: fetch_bytes(url),
                              lambda data, item=it: self._set_game_icon(item, data))

    def _set_game_icon(self, item: QListWidgetItem, data: bytes) -> None:
        img = QImage.fromData(data)
        if img.isNull():
            return
        pm = QPixmap.fromImage(img).scaled(280, 92,
                                           Qt.KeepAspectRatioByExpanding,
                                           Qt.SmoothTransformation)
        item.setIcon(pm)

    def on_game_clicked(self, item: QListWidgetItem) -> None:
        appid = item.data(Qt.UserRole)
        if appid:
            self._select_app(appid)

    def _select_app(self, appid: int) -> None:
        self.findBtn.setEnabled(True)

        def work():
            return get_app_name(appid)

        self.hub.call(work, lambda name: self._after_name(appid, name))

    def _after_name(self, appid: int, name: str) -> None:
        self.current_game = Game(appid=appid, name=name)
        self.gameSearchEdit.setText(name)
        self.setWindowTitle(f"OpenSteamWorkshop — {name}")
        self.modSearchEdit.clear()
        self.page = 1
        self._set_browser_enabled(True)
        self.refresh()

    def _open_from_url(self, appid_guess, fileids) -> None:
        if not fileids:
            if appid_guess:
                self._select_app(appid_guess)
            return
        fid = fileids[0]
        self.statusBar().showMessage("Loading item details…")
        self.hub.call(lambda: get_item_details(fid),
                      lambda det: self._show_details_dialog(det, appid_guess))

    # ---------------------------------------------------------------- browse

    def refresh(self) -> None:
        if not self.current_game:
            return
        self._do_browse()

    def _goto_page(self, delta: int) -> None:
        if not self.current_game:
            return
        self.page = max(1, self.page + delta)
        self._do_browse()

    def _do_browse(self) -> None:
        appid = self.current_game.appid
        sort = self.sortCombo.currentData() or "trend"
        text = self.modSearchEdit.text().strip()
        self.statusBar().showMessage("Loading workshop items…")
        self.hub.call(
            lambda: browse_workshop(
                appid, page=self.page, per_page=30, sort=sort, search_text=text),
            lambda res: self._items_ready(appid, *res),
        )

    def _items_ready(self, appid: int, items: list, total: int, pages: int) -> None:
        self.items = items
        self.total_pages = pages or 1
        self.modsGrid.clear()
        self.pageLabel.setText(f"{self.page} / {self.total_pages}")
        if not items:
            self.statusBar().showMessage(
                "No workshop content — this app may not publish ordinary mods here", 8000)
            return
        for it in items:
            card = QListWidgetItem(it.title or f"item {it.publishedfileid}")
            card.setData(Qt.UserRole, it.publishedfileid)
            size = fmt_size(it.file_size)
            subs = fmt_count(it.subscriptions)
            extra = []
            if size:
                extra.append(size)
            extra.append(f"subs {subs}")
            if it.star_rating:
                extra.append(f"★ {it.star_rating:.0f}/5")
            card.setText(it.title or f"item {it.publishedfileid}")
            tip = f"<b>{it.title}</b><br>{it.short_description[:250]}"
            if it.tags:
                tip += "<br><small>" + ", ".join(it.tags[:6]) + "</small>"
            tip += f"<br><small>{' · '.join(extra)} · updated {fmt_unix(it.time_updated)}</small>"
            card.setToolTip(tip)
            ph = QPixmap(CARD_W, CARD_H)
            ph.fill(QColor(0x2b, 0x2d, 0x31))
            card.setIcon(ph)
            card.setSizeHint(QPixmap(CARD_W, CARD_H).size())
            self.modsGrid.addItem(card)
            if it.preview_url:
                self.hub.tp.start(ThumbJob(self.hub, it.preview_url, it.publishedfileid))
        self.statusBar().showMessage(
            f"{len(items)} items on page {self.page}/{self.total_pages} · {fmt_count(total)} total")

    def on_thumb(self, fileid: int, data) -> None:
        img = QImage.fromData(data)
        if img.isNull():
            return
        pm = QPixmap.fromImage(img)
        pm = pm.scaled(THUMB, THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        for row in range(self.modsGrid.count()):
            it = self.modsGrid.item(row)
            if it.data(Qt.UserRole) == fileid:
                it.setIcon(pm)
                break

    # ---------------------------------------------------------------- details

    def _show_details(self) -> None:
        it = self._grid_selection()
        if not it:
            return
        self.statusBar().showMessage("Loading details…")
        self.hub.call(lambda: get_item_details(it.publishedfileid),
                      self._details_ready)

    def _details_ready(self, det: ItemDetails) -> None:
        self._show_details_dialog(det, self.current_game.appid if self.current_game else None)

    def _show_details_dialog(self, det: ItemDetails, appid_guess: int | None) -> None:
        from html import escape

        d = QDialog(self)
        d.setWindowTitle(det.title or f"Item {det.fileid}")
        d.resize(680, 580)
        v = QVBoxLayout(d)

        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        h = f"<h2>{escape(det.title)}</h2>"
        if det.author:
            if det.author_url:
                h += f"<p>by <a href='{det.author_url}'>{escape(det.author)}</a></p>"
            else:
                h += f"<p>by {escape(det.author)}</p>"
        bits = []
        if det.appid or appid_guess:
            bits.append(f"app {det.appid or appid_guess}")
        if det.file_size:
            bits.append(f"size {det.file_size}")
        if det.posted:
            bits.append(f"posted {det.posted}")
        if det.fileid:
            bits.append(f"id {det.fileid}")
        if det.num_ratings:
            bits.append(f"{det.num_ratings} ratings")
        if bits:
            h += "<p><i>" + " · ".join(bits) + "</i></p>"
        if det.tags:
            h += "<p style='color:#7ec9ff;'>" + " · ".join(escape(t) for t in det.tags[:12]) + "</p>"
        h += "<hr>"
        h += "<p>" + escape(det.description or "— no description —")[:4000] + "</p>"
        if det.error:
            h += f"<p style='color:#e77'>{escape(det.error)}</p>"
        if det.required_items:
            h += "<h3>Required items</h3><ul style='margin-left:8px;'>"
            for rid, rtitle in det.required_items[:40]:
                h += (f"<li><a href='https://steamcommunity.com/sharedfiles/filedetails/?id={rid}'>"
                      f"{escape(rtitle or str(rid))}</a></li>")
            h += "</ul>"
        if det.fileid:
            url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={det.fileid}"
            h += f"<p><a href='{url}'>open in browser ↗</a></p>"
        text.setHtml(h)
        v.addWidget(text, 1)

        row = QHBoxLayout()
        appid = (self.current_game.appid if self.current_game else det.appid) or appid_guess
        dl = QPushButton("Download")
        if not appid:
            dl.setEnabled(False)
            dl.setToolTip("Unknown appid for this item")
        dl.clicked.connect(
            lambda: (self._queue_download(
                WorkshopItem(publishedfileid=det.fileid, appid=appid, title=det.title)),
                d.accept()))
        row.addWidget(dl)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(d.reject)
        row.addWidget(close)
        v.addLayout(row)
        d.exec()

    def _grid_selection(self) -> WorkshopItem | None:
        it = self.modsGrid.currentItem()
        if not it:
            return None
        fid = it.data(Qt.UserRole)
        return next((x for x in self.items if x.publishedfileid == fid), None)

    def _grid_menu(self, pos) -> None:
        it = self.modsGrid.itemAt(pos)
        if not it:
            return
        fid = it.data(Qt.UserRole)
        item = next((x for x in self.items if x.publishedfileid == fid), None)
        if not item:
            return
        menu = QMenu(self)
        menu.addAction("View details", lambda: (self.modsGrid.setCurrentItem(it),
                                                self._show_details()))
        menu.addAction("Download", lambda: self._queue_download(item))
        if item.children:
            menu.addAction(
                f"Download + {len(item.children)} required item(s)",
                lambda: (self._queue_download(item),
                         [self._queue_download(
                             WorkshopItem(publishedfileid=c, appid=item.appid,
                                          title=f"dep {c}"))
                          for c in item.children]),
            )
        menu.addAction("Copy workshop URL", lambda: self._copy(item.url))
        menu.exec(self.modsGrid.mapToGlobal(pos))

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Copied to clipboard", 3000)

    def _queue_download(self, item: WorkshopItem) -> None:
        self._ensure_manager_settings()
        self.manager.add(item, self.current_game.name if self.current_game else "")

    def _ensure_manager_settings(self) -> None:
        self.manager.content_root = Path(get("content_root"))
        if not self.manager.username and get("username"):
            self.manager.username = get("username")
            if get("remember_password"):
                self.manager.password = get("password")

    # ------------------------------------------------------------ queue panel

    def _on_job_ui(self, job: DownloadJob) -> None:
        key = (job.appid, job.fileid)
        row = self._job_rows.get(key)
        if row is None:
            row = self._make_job_row()
            self._job_rows[key] = row

        label: QLabel = row["label"]
        bar: QProgressBar = row["bar"]
        state = job.state
        label.setText(f"{job.title}  —  {state.value}")

        if state is JobState.FAILED:
            bar.hide()
            tip = job.message or "failed"
            label.setToolTip(tip[:400])
            label.setStyleSheet("color:#e28b8b;")
        elif state is JobState.DONE:
            bar.setValue(100)
            bar.setStyleSheet("QProgressBar::chunk { background: #6bbf59; }")
            label.setToolTip(job.message[:400])
        elif state is JobState.RUNNING:
            bar.setRange(0, 100 if job.progress > 0 else 0)
            if job.progress:
                bar.setValue(int(job.progress))
        elif state is JobState.QUEUED:
            bar.setRange(0, 0)  # busy bar
            label.setStyleSheet("")

    def _make_job_row(self) -> dict:
        holder = QWidget()
        h = QVBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        label = QLabel("queued")
        label.setStyleSheet("font-weight:600;")
        bar = QProgressBar()
        bar.setFixedHeight(12)
        bar.setTextVisible(False)
        h.addWidget(label)
        h.addWidget(bar)
        # insert above the trailing stretch so rows accumulate naturally
        self.queueLay.insertWidget(max(0, self.queueLay.count() - 1), holder)
        return {"widget": holder, "label": label, "bar": bar}

    # --------------------------------------------------------------- settings

    def _open_settings(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("Settings")
        form = QFormLayout(d)

        tmp = {
            "content_root": get("content_root"),
            "username": get("username"),
            "remember_password": bool(get("remember_password")),
            "password": get("password") if get("remember_password") else "",
            "parallel_downloads": get("parallel_downloads"),
        }

        root_edit = QLineEdit(str(tmp["content_root"]))
        pick = QPushButton("…")
        pick.clicked.connect(lambda: root_edit.setText(
            QFileDialog.getExistingDirectory(d, "Choose mods root folder") or root_edit.text()))
        rootrow = QHBoxLayout()
        rootrow.addWidget(root_edit, 1)
        rootrow.addWidget(pick)
        rootwrap = QWidget()
        rootwrap.setLayout(rootrow)
        form.addRow("Mods root folder", rootwrap)

        user_edit = QLineEdit(tmp["username"])
        user_edit.setPlaceholderText("(empty = anonymous downloads only)")
        form.addRow("Steam username", user_edit)

        remember = QCheckBox("Remember password (plain text in settings.json)")
        remember.setChecked(bool(tmp["remember_password"]))
        form.addRow(remember)

        pw_edit = QLineEdit(tmp["password"] or "")
        pw_edit.setEchoMode(QLineEdit.Password)
        pw_edit.setEnabled(remember.isChecked())
        remember.toggled.connect(pw_edit.setEnabled)
        form.addRow("Steam password", pw_edit)

        par = QComboBox()
        for i in (1, 2, 3, 4):
            par.addItem(f"{i} parallel download{'s' if i > 1 else ''}", i)
        par.setCurrentIndex(max(0, min(3, int(tmp["parallel_downloads"]) - 1)))
        form.addRow("SteamCMD jobs", par)

        note = QLabel(
            "Steam Guard: when logging in with a password, SteamCMD may ask for a"
            " code — respond in the terminal if using the CLI, or save an app password"
            " otherwise.")
        note.setWordWrap(True)
        form.addRow(note)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        form.addRow(bb)

        if d.exec() != QDialog.Accepted:
            return
        parallel = par.currentData() or 2
        set_key("content_root", root_edit.text().strip() or str(Path.home() / "SteamMods"))
        set_key("username", user_edit.text().strip())
        set_key("remember_password", remember.isChecked())
        set_key("password", pw_edit.text() if remember.isChecked() else "")
        set_key("parallel_downloads", parallel)
        self.manager = self._build_manager()
        self.manager.on_job_update = self.jobEvent.emit
        self.manager.on_log = lambda m: self.hub.logMessage.emit(m)
        self.statusBar().showMessage("Settings saved", 5000)


# --------------------------------------------------------------------- run


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("OpenSteamWorkshop")
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
