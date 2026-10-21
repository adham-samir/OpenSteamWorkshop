"""Browse workspace: first-run actions, focused game results, Workshop cards, inspector."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..models import ItemDetails, WorkshopItem, fmt_count, fmt_size
from ..steam_api import SORTS
from . import icons, theme
from .delegates import GameResultDelegate, ItemCardDelegate, ItemListDelegate
from .item_models import (
    FavoriteRole,
    GameListModel,
    GameRole,
    ItemCardModel,
    ItemRole,
    ThumbRole,
    _as_image,
)
from .status_strip import SpinnerLabel

MODE_HERO, MODE_RESULTS, MODE_GRID = "hero", "results", "grid"
GRID_SPACING = 8
ITEM_GRID_SPACING = GRID_SPACING


def _button(text: str, *, accent: bool = False, icon_name: str | None = None) -> QPushButton:
    if icon_name:
        btn = QPushButton(
            icons.icon(icon_name, theme.ACCENT_TEXT if accent else theme.TEXT2, 14), text
        )
    else:
        btn = QPushButton(text)
    if accent:
        btn.setProperty("accent", True)
    btn.setAccessibleName(text)
    return btn


# ------------------------------------------------------------------ hero


class HeroView(QFrame):
    """First run: two clear actions so a new user can start without docs."""

    find_requested = Signal()
    import_requested = Signal()
    game_requested = Signal(int)

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 0, 10, 0)
        v.addStretch(3)
        title = QLabel("Find a game or paste Workshop links")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet(f"font-size: 22px; font-weight: 650; color: {theme.TEXT};")
        v.addWidget(title)
        sub = QLabel(
            "Search the store by game name, or paste a Workshop link —\n"
            "no game installation needed; downloads land in your mods folder."
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        sub.setStyleSheet(f"color: {theme.TEXT2}; font-size: 13px;")
        v.addWidget(sub)
        v.addSpacing(18)
        row = QHBoxLayout()
        row.addStretch(1)
        find = _button("Find a game", accent=True, icon_name="search")
        find.setFixedHeight(34)
        find.clicked.connect(self.find_requested.emit)
        row.addWidget(find)
        add = _button("Import Workshop links", icon_name="import")
        add.setFixedHeight(34)
        add.clicked.connect(self.import_requested.emit)
        row.addWidget(add)
        row.addStretch(1)
        v.addLayout(row)

        self.recent_box, self.recent_row = self._personal_section("RECENT GAMES")
        v.addWidget(self.recent_box)
        v.addSpacing(10)
        self.pinned_box, self.pinned_row = self._personal_section("PINNED GAMES")
        v.addWidget(self.pinned_box)
        self.recent_box.hide()
        self.pinned_box.hide()
        v.addStretch(4)

    @staticmethod
    def _personal_section(title: str):
        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(5)
        caption = QLabel(title)
        caption.setStyleSheet(
            f"color: {theme.TEXT2}; font-size: 10.5px; font-weight: 650; letter-spacing: 1px;"
        )
        outer.addWidget(caption, 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        row.setSpacing(6)
        outer.addLayout(row)
        return box, row

    @staticmethod
    def _clear_row(row: QHBoxLayout) -> None:
        while row.count():
            item = row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def set_games(self, recent, favorites) -> None:
        self._fill_section(self.recent_box, self.recent_row, recent)
        self._fill_section(self.pinned_box, self.pinned_row, favorites)

    def _fill_section(self, box: QWidget, row: QHBoxLayout, games) -> None:
        self._clear_row(row)
        games = list(games or ())[:6]
        if not games:
            box.hide()
            return
        row.addStretch(1)
        for game in games:
            button = QPushButton()
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(28)
            button.setMaximumWidth(170)
            metrics = button.fontMetrics()
            button.setText(
                metrics.elidedText(game.name, Qt.TextElideMode.ElideRight, 140)
            )
            button.setToolTip(f"Open {game.name} — app {game.appid}")
            button.setAccessibleName(f"Open {game.name}")
            button.setStyleSheet(
                f"QPushButton {{ background: {theme.RAISED}; color: {theme.TEXT};"
                f" border: 1px solid {theme.BORDER}; border-radius: 6px;"
                f" padding: 4px 10px; }}"
                f"QPushButton:hover {{ border-color: {theme.ACCENT}; color: {theme.ACCENT}; }}"
            )
            button.clicked.connect(
                lambda _=False, appid=game.appid: self.game_requested.emit(appid)
            )
            row.addWidget(button)
        row.addStretch(1)
        box.show()


# -------------------------------------------------------------- results


class ResultsView(QWidget):
    """Focused results panel in place of a permanent game-list column."""

    app_picked = Signal(int)
    search_requested = Signal()
    pin_requested = Signal(int)

    def __init__(self):
        super().__init__()
        self.model = GameListModel(self)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        bar = QHBoxLayout()
        self.heading = QLabel("Search results")
        self.heading.setStyleSheet("font-size: 14px; font-weight: 600;")
        bar.addWidget(self.heading)
        self.term_hint = QLabel("")
        self.term_hint.setStyleSheet(f"color: {theme.TEXT2};")
        bar.addWidget(self.term_hint, 1)
        bar.addStretch(1)
        v.addLayout(bar)

        self.state = QLabel("Type a game name above to search the store.")
        self.state.setWordWrap(True)
        self.state.setStyleSheet(f"color: {theme.TEXT2};")
        v.addWidget(self.state)

        self.list = QListView()
        self.list.setModel(self.model)
        self.list.setItemDelegate(GameResultDelegate(self.list))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setUniformItemSizes(True)
        self.list.setAccessibleName("Game search results")
        self.list.activated.connect(self._picked)
        self.list.clicked.connect(self._picked)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.list, 1)

    def _menu(self, pos) -> None:
        index = self.list.indexAt(pos)
        game = index.data(GameRole) if index.isValid() else None
        if game is None:
            return
        favorite = bool(index.data(FavoriteRole))
        menu = QMenu(self)
        action = menu.addAction("Unpin from start" if favorite else "Pin to start")
        action.triggered.connect(lambda: self.pin_requested.emit(game.appid))
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def set_favorites(self, appids) -> None:
        self.model.set_favorites(appids)

    def _picked(self, index: QModelIndex) -> None:
        game = index.data(Qt.ItemDataRole.UserRole + 11)
        if game is not None:
            self.app_picked.emit(game.appid)

    def set_games(self, term: str, games) -> None:
        self.heading.setText('Results for "%s"' % term if term else "Results")
        self.model.set_games(games or [])
        if not games:
            self.set_message(
                f'No store results for "{term}" — try different spelling, or paste the app ID directly.'
            )
        else:
            self.set_message(f"{len(games)} result(s) — click a game to browse its Workshop.")

    def set_message(self, text: str) -> None:
        self.state.setText(text)


# ------------------------------------------------------------ inspector


class CoverFrame(QLabel):
    """Rounded aspect-fill cover; placeholder until art streams in."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(150)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pixmap: QPixmap | None = None

    def set_image(self, data) -> None:
        img = _as_image(data)
        if img.isNull():
            self.show_placeholder()
            return
        self._pixmap = QPixmap.fromImage(img)
        self.setText("")
        self.update()

    def show_placeholder(self) -> None:
        self._pixmap = None
        self.update()

    def setScaledContents(self, on: bool) -> None:  # not used; paint instead
        super().setScaledContents(False)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        r = QRectF(0, 0, self.width(), self.height())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._pixmap is None:
            p.fillRect(r, QColor("#131A21"))
            icons.paint(p, r, "eye", "#3C4652")
            p.end()
            return
        p.fillRect(r, QColor(theme.SURFACE))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scale = min(r.width()/self._pixmap.width(), r.height()/self._pixmap.height())
        width, height = self._pixmap.width()*scale, self._pixmap.height()*scale
        target = QRectF(r.center().x()-width/2, r.center().y()-height/2, width, height)
        p.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        p.end()


def _stat(text: str, value: str) -> tuple[QLabel, QLabel]:
    k = QLabel(text.upper())
    k.setStyleSheet(f"color: {theme.TEXT2}; font-size: 10px; letter-spacing: 0.6px;")
    v = QLabel(value)
    v.setStyleSheet("font-size: 12.5px; font-weight: 500;")
    return k, v


class InspectorPanel(QFrame):
    """Resizable side panel for a single Workshop item."""

    download_clicked = Signal(object)   # WorkshopItem currently shown
    deps_clicked = Signal(object)
    copy_clicked = Signal(object)
    browser_clicked = Signal(object)
    close_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("SidePanel")
        self.setMinimumWidth(280)
        self.item: WorkshopItem | None = None
        self._deps_item: WorkshopItem | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(14, 10, 12, 10)
        head_label = QLabel("Mod details")
        head_label.setStyleSheet(f"font-weight: 600; color: {theme.TEXT2};")
        head.addWidget(head_label)
        head.addStretch(1)
        self.close_btn = _button("Close", icon_name="x")
        self.close_btn.setAccessibleName("Close mod details")
        self.close_btn.clicked.connect(self.close_requested.emit)
        head.addWidget(self.close_btn)
        outer.addLayout(head)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.BORDER};")
        outer.addWidget(line)

        body = QScrollArea()
        body.setWidgetResizable(True)
        body.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(13, 12, 13, 13)
        self.body.setSpacing(10)
        body.setWidget(inner)
        outer.addWidget(body, 1)

        self.cover = CoverFrame()
        self.body.addWidget(self.cover)
        self.destination = QLabel("")
        self.destination.setWordWrap(True)
        self.destination.setProperty("role", "muted")
        self.body.addWidget(self.destination)
        self.installed_status = QLabel("")
        self.installed_status.setWordWrap(True)
        self.installed_status.setProperty("role", "muted")
        self.body.addWidget(self.installed_status)

        self.loading_row = QWidget()
        load_lay = QHBoxLayout(self.loading_row)
        load_lay.setContentsMargins(0, 2, 0, 2)
        self.loading_spinner = SpinnerLabel(theme.ACCENT, 12)
        load_lay.addWidget(self.loading_spinner)
        self.loading_text = QLabel("Loading details…")
        self.loading_text.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        load_lay.addWidget(self.loading_text)
        load_lay.addStretch(1)
        self.body.addWidget(self.loading_row)

        self.title_label = QLabel("")
        self.title_label.setWordWrap(True)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setStyleSheet("font-size: 15.5px; font-weight: 650;")
        self.body.addWidget(self.title_label)

        self.byline = QLabel("")
        self.byline.setWordWrap(True)
        self.byline.setTextFormat(Qt.TextFormat.PlainText)
        self.byline.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        self.body.addWidget(self.byline)

        stat_widget = QWidget()
        grid = QGridLayout(stat_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.stats: dict[str, QLabel] = {}
        for i, (key, caption) in enumerate(
            (
                ("size", "Size"),
                ("subs", "Subscribers"),
                ("rating", "Rating"),
                ("appid", "App ID"),
            )
        ):
            k, value = _stat(caption, "—")
            self.stats[key] = value
            box = QVBoxLayout()
            box.setSpacing(1)
            box.addWidget(k)
            box.addWidget(value)
            grid.addLayout(box, i // 2, i % 2)
        self.body.addWidget(stat_widget)

        self.notice = QFrame()
        self.notice.setObjectName("collectionNotice")
        nv = QVBoxLayout(self.notice)
        nv.setContentsMargins(10, 8, 10, 8)
        nv.setSpacing(5)
        self.notice_head = QLabel("")
        self.notice_head.setWordWrap(True)
        self.notice_head.setStyleSheet(f"font-weight: 600; color: {theme.WARN};")
        self.notice_body = QLabel("")
        self.notice_body.setWordWrap(True)
        self.notice_body.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        self.notice_btn = QPushButton("Preview required items…")
        self.notice_btn.setFlat(True)
        self.notice_btn.setStyleSheet(
            f"color: {theme.ACCENT}; border: none; padding: 2px 0; text-align: left;"
        )
        nv.addWidget(self.notice_head)
        nv.addWidget(self.notice_body)
        nv.addWidget(self.notice_btn)
        self.notice.setVisible(False)
        self.body.addWidget(self.notice)

        self.desc = QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setTextFormat(Qt.TextFormat.PlainText)
        self.desc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.desc.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12.5px;")
        self.body.addWidget(self.desc, 1)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {theme.BAD}; font-size: 12.5px;")
        self.error_label.setVisible(False)
        self.body.addWidget(self.error_label)

        id_row = QHBoxLayout()
        self.id_label = QLabel("")
        self.id_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 11px;")
        id_row.addWidget(self.id_label)
        id_row.addStretch(1)
        self.copy_btn = QPushButton("Copy link")
        self.copy_btn.setFlat(True)
        self.copy_btn.setStyleSheet(f"color: {theme.ACCENT}; border: none; padding: 2px 0;")
        id_row.addWidget(self.copy_btn)
        self.body.addLayout(id_row)

        actions_row = QVBoxLayout()
        actions_row.setSpacing(8)
        self.download_btn = _button("Download", accent=True, icon_name="download")
        self.download_btn.setFixedHeight(40)
        self.download_btn.setAccessibleName("Download this item")
        actions_row.addWidget(self.download_btn)
        sub_row = QHBoxLayout()
        self.deps_btn = _button("Preview dependencies")
        self.browser_btn = _button("In browser ↗")
        sub_row.addWidget(self.deps_btn, 1)
        sub_row.addWidget(self.browser_btn, 0)
        actions_row.addLayout(sub_row)
        actions_widget = QWidget()
        footer = QVBoxLayout(actions_widget)
        footer.setContentsMargins(13, 10, 13, 12)
        footer.addLayout(actions_row)
        outer.addWidget(actions_widget)

        self.download_btn.clicked.connect(self._maybe_download)
        self.deps_btn.clicked.connect(self._maybe_deps)
        self.notice_btn.clicked.connect(self._maybe_deps)
        self.copy_btn.clicked.connect(self._emit_copy)
        self.browser_btn.clicked.connect(self._emit_browser)
        self.set_load_state(True)

    # ------------------------------------------------------- public api

    def set_load_state(self, loading: bool) -> None:
        self.loading_row.setVisible(loading)
        self.title_label.setVisible(not loading)
        self.byline.setVisible(not loading)
        if loading:
            self.loading_spinner.set_running(True)
        else:
            self.loading_spinner.set_running(False)

    def set_cover(self, data) -> None:  # data: bytes | QImage | None
        if data:
            self.cover.set_image(data)
        else:
            self.cover.show_placeholder()

    def set_place(self, item: WorkshopItem) -> None:
        """Fill everything the card model already knows; details stream in later."""
        self.item = item
        self.installed_status.clear()
        self._deps_item = None
        self.title_label.setText(item.title or f"item {item.publishedfileid}")
        self.byline.setText("")
        self.stats["size"].setText(fmt_size(item.file_size) or "—")
        self.stats["subs"].setText(fmt_count(item.subscriptions) or "—")
        self.stats["rating"].setText(f"{item.star_rating:.1f} / 5" if item.star_rating else "—")
        self.stats["appid"].setText(str(item.appid or "—"))
        self.desc.setText("")
        self.error_label.setVisible(False)
        self.download_btn.setEnabled(item.appid > 0)
        self.download_btn.setText("Download")
        self.deps_btn.setText("Preview dependencies")
        self.deps_btn.setEnabled(item.appid > 0 and item.file_type == 2)
        self.browser_btn.setEnabled(item.appid > 0)
        self.notice.setVisible(False)
        self.id_label.setText(f"Item {item.publishedfileid}")
        self.set_load_state(False)

    def set_details(self, det: ItemDetails, appid_guess: int | None) -> None:
        appid = det.appid or appid_guess
        bits = []
        if det.author:
            bits.append(f"by {det.author}")
        if det.posted:
            bits.append(f"posted {det.posted}")
        self.byline.setText(" · ".join(bits))
        n_req = len(det.required_items)
        if det.file_type == 2 or n_req:
            self.notice.setVisible(True)
            self.notice_head.setText(
                "Part of a collection" if det.file_type == 2 else "Requires other items"
            )
            size_note = "Preview before downloading."
            self.notice_body.setText(
                f"Pulls in {n_req} required item(s). {size_note}" if n_req else size_note
            )
        else:
            self.notice.setVisible(False)
        self.desc.setText(det.description or "— no description —")
        self.error_label.setText(det.error or "")
        self.error_label.setVisible(bool(det.error))
        if det.num_ratings:
            self.stats["rating"].setText(det.rating_text or "—")
        if appid:
            self.stats["appid"].setText(str(appid))
        self.download_btn.setEnabled(bool(appid and not det.error))
        if not self.download_btn.isEnabled():
            self.download_btn.setToolTip("Unknown appid or the item is private")
        self.deps_btn.setVisible(det.file_type == 2 or bool(det.required_items))
        self.notice_btn.setVisible(det.file_type == 2 or bool(det.required_items))
        if det.file_type == 2:
            self.deps_btn.setText("Preview collection…")
            self.download_btn.setText("Preview collection…")
        else:
            self.download_btn.setText("Download")
        self._deps_item = WorkshopItem(publishedfileid=det.fileid, appid=appid or 0, title=det.title,
                                       file_type=det.file_type)
        # Ownership resolved by Steam is authoritative, including collections.
        self.item = self._deps_item
        if det.title:
            self.title_label.setText(det.title)

    def set_error(self, message: str) -> None:
        self.set_load_state(False)
        self.error_label.setText(message)
        self.error_label.setVisible(True)
        self.download_btn.setEnabled(False)

    # -------------------------------------------------------- internal

    def _maybe_download(self) -> None:
        if self.item is None:
            return
        self.download_clicked.emit(self.item)

    def _maybe_deps(self) -> None:
        target = self._deps_item or self.item
        if target is None:
            return
        self.deps_clicked.emit(target)

    def _emit_copy(self) -> None:
        if self.item is not None:
            self.copy_clicked.emit(self.item)

    def _emit_browser(self) -> None:
        if self.item is not None:
            self.browser_clicked.emit(self.item)


# ------------------------------------------------------------- bulk bar


class BulkBar(QFrame):
    """Shown while 2+ cards share a selection."""

    download_clicked = Signal(int)
    clear_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("BulkBar")
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(10)
        self.label = QLabel("0 selected")
        self.label.setStyleSheet("font-weight: 600;")
        h.addWidget(self.label)
        h.addStretch(1)
        self.download_btn = _button("Download selected…", icon_name="download")
        self.download_btn.setProperty("accent", True)
        self.clear_btn = _button("Clear selection")
        h.addWidget(self.download_btn)
        h.addWidget(self.clear_btn)
        self.hide()


# ------------------------------------------------------------------ page


class BrowsePage(QWidget):
    """Intents go out; the controller performs async work and feeds state in."""

    presentation_changed = Signal(str)
    details_closed = Signal()
    game_search_requested = Signal(str)
    app_picked = Signal(int)
    workshop_change_requested = Signal()
    sort_change_requested = Signal()
    page_requested = Signal(int)
    import_requested = Signal()
    change_game_requested = Signal()
    favorite_toggled = Signal(int)
    mods_folder_change_requested = Signal()
    mods_folder_clear_requested = Signal()
    mods_folder_open_requested = Signal()
    selection_changed = Signal(int)      # count
    item_action_requested = Signal(object)  # item or list[WorkshopItem] + kind below
    bulk_download_requested = Signal()
    selection_items_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self.current_game_target: tuple[int, str] | None = None
        self._closed = False
        self._mods_path = ""
        self._default_mods_root = ""
        self.presentation = "cards"
        self._wide_details = True
        self._details_open = False
        self._detail_scroll = 0

        self.hero = HeroView()
        self.results = ResultsView()
        self.results.app_picked.connect(self.app_picked.emit)
        self.results.search_requested.connect(
            lambda: self.game_search_requested.emit(self.game_search.text().strip())
        )

        # top search field, always visible
        self.game_search = QLineEdit()
        self.game_search.setPlaceholderText(
            "Search a game by name, or paste an appid / workshop / store URL"
        )
        self.game_search.setAccessibleName("Find games")
        self.game_search.returnPressed.connect(
            lambda: self.game_search_requested.emit(self.game_search.text().strip())
        )
        self.find_button = _button("Find a game", accent=True, icon_name="search")
        self.import_btn = _button("Import Workshop links", icon_name="import")

        # cards model + view
        self.grid_model = ItemCardModel(self)
        self.cards = QListView()
        self.cards.setModel(self.grid_model)
        self.cards.setItemDelegate(ItemCardDelegate(self.cards))
        self.cards.setViewMode(QListView.ViewMode.ListMode)
        self.cards.setFlow(QListView.Flow.LeftToRight)
        self.cards.setWrapping(True)
        self.cards.setResizeMode(QListView.ResizeMode.Adjust)
        self.cards.setUniformItemSizes(True)
        self.cards.setSpacing(GRID_SPACING)
        self.cards.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.cards.setMovement(QListView.Movement.Static)
        self.cards.setMouseTracking(False)
        self.cards.setAccessibleName("Workshop items")
        self.cards.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cards.setWordWrap(True)
        self.cards.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.cards.customContextMenuRequested.connect(self._open_menu)

        # grid page: toolbar, meta line, cards, bulk bar
        grid_widget = QWidget()
        gv = QVBoxLayout(grid_widget)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.setSpacing(8)

        tools = QHBoxLayout()
        self.modSearchEdit = QLineEdit()
        self.modSearchEdit.setPlaceholderText("Search inside this game's Workshop…")
        self.modSearchEdit.setAccessibleName("Workshop search")
        tools.addWidget(self.modSearchEdit, 1)
        self.sortCombo = QComboBox()
        for key, label in SORTS.items():
            self.sortCombo.addItem(label, key)
        self.sortCombo.setAccessibleName("Sort Workshop results")
        tools.addWidget(self.sortCombo)
        self.cards_btn = _button("Cards")
        self.list_btn = _button("List")
        for button, mode in ((self.cards_btn, "cards"), (self.list_btn, "list")):
            button.setCheckable(True)
            button.setAccessibleName(f"Show mods as {mode}")
            button.clicked.connect(lambda _=False, m=mode: self.set_presentation(m))
            tools.addWidget(button)
        self.cards_btn.setChecked(True)
        self.prevBtn = _button("‹")
        self.nextBtn = _button("›")
        self.pageLabel = QLabel("—")
        self.pageLabel.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        tools.addWidget(self.prevBtn)
        tools.addWidget(self.pageLabel)
        tools.addWidget(self.nextBtn)
        gv.addLayout(tools)

        self.browserMessage = QLabel("")
        self.browserMessage.setWordWrap(True)
        self.browserMessage.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        gv.addWidget(self.browserMessage)

        self.grid_state = QLabel("")
        self.grid_state.setWordWrap(True)
        self.grid_state.setTextFormat(Qt.TextFormat.RichText)
        self.grid_state.setStyleSheet(f"color: {theme.TEXT2}; font-size: 13px;")
        self.grid_state.hide()
        gv.addWidget(self.grid_state)

        self.cards_box = QScrollArea()
        self.cards_box.setWidgetResizable(True)
        self.cards_box.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_box.setWidget(self.cards)
        gv.addWidget(self.cards_box, 1)

        self.bulk_bar = BulkBar()
        gv.addWidget(self.bulk_bar)

        # content stack: hero | results | grid
        self.stack = QStackedWidget()
        self.stack.addWidget(self.hero)
        self.stack.addWidget(self.results)
        self.stack.addWidget(grid_widget)
        self._page_indices = {MODE_HERO: 0, MODE_RESULTS: 1, MODE_GRID: 2}

        header_top = QHBoxLayout()
        self.page_title = self._page_title()
        header_top.addWidget(self.page_title, 1)
        self.game_chip = QLabel("No game selected")
        self.game_chip.setObjectName("gameChip")
        self.game_chip.setStyleSheet(
            f"color: {theme.TEXT2}; font-size: 12.5px; padding: 2px 9px;"
            f"border: 1px solid {theme.BORDER}; border-radius: 7px;"
        )
        self.game_chip.hide()
        self.change_btn = _button("Change")
        self.change_btn.setFlat(True)
        self.change_btn.setStyleSheet(f"color: {theme.TEXT2}; border: none;")
        self.change_btn.hide()
        self.pin_btn = _button("Pin", icon_name="star")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setAccessibleName("Pin current game")
        self.pin_btn.setToolTip("Pin this game to the Browse start screen")
        self.pin_btn.clicked.connect(self._toggle_pin)
        header_top.addWidget(self.pin_btn)
        self.mods_btn = _button("Mods folder", icon_name="folder")
        self.mods_btn.setAccessibleName("Mods folder for the current game")
        self.mods_btn.setVisible(False)
        self.mods_btn.clicked.connect(self._show_mods_menu)
        header_top.addWidget(self.mods_btn)


        search_row = QHBoxLayout()
        search_row.setSpacing(7)
        search_icon = QLabel()
        search_icon.setPixmap(icons.icon("search", theme.TEXT2, 13).pixmap(13, 13))
        search_row.addWidget(search_icon)
        search_row.addWidget(self.game_search, 1)
        search_row.addWidget(self.find_button)
        search_row.addWidget(self.import_btn)

        header = QVBoxLayout()
        header.setSpacing(8)
        header.addLayout(header_top)
        self.search_holder = QWidget()
        self.search_holder.setLayout(search_row)
        header.addWidget(self.search_holder)

        left = QWidget()
        self.content = left
        self._left_layout = QVBoxLayout(left)
        self._left_layout.setContentsMargins(18, 14, 10, 10)
        self._left_layout.setSpacing(12)
        self._left_layout.addLayout(header)
        self._left_layout.addWidget(self.stack, 1)

        self.inspector = InspectorPanel()
        self.inspector.close_requested.connect(self.dismiss_details)
        QShortcut(QKeySequence("Escape"), self, activated=self.dismiss_details)
        self.inspector.hide()
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.inspector)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setChildrenCollapsible(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.splitter, 1)

        # wiring
        self.find_button.clicked.connect(
            lambda: self.game_search_requested.emit(self.game_search.text().strip())
        )
        self.import_btn.clicked.connect(self.import_requested.emit)
        self.change_btn.clicked.connect(self.change_game_requested.emit)
        self.hero.find_requested.connect(self.focus_game_search)
        self.hero.import_requested.connect(self.import_requested.emit)
        self.hero.game_requested.connect(self.app_picked.emit)
        self.modSearchEdit.returnPressed.connect(self.workshop_change_requested.emit)
        self.sortCombo.currentIndexChanged.connect(self.sort_change_requested.emit)
        self.prevBtn.clicked.connect(lambda: self.page_requested.emit(-1))
        self.nextBtn.clicked.connect(lambda: self.page_requested.emit(+1))
        self.bulk_bar.download_btn.clicked.connect(
            lambda: self.bulk_download_requested.emit()
        )
        self.bulk_bar.clear_btn.clicked.connect(self.cards.selectionModel().clearSelection)

        # selection batching
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.timeout.connect(self._emit_selection)
        self.cards.selectionModel().selectionChanged.connect(
            lambda *_: self._selection_timer.start(0)
        )
        self.cards.activated.connect(self._activate_card)
        self.cards.clicked.connect(self._reopen_details)
        self.set_mode(MODE_HERO)
        self.set_browser_enabled(False)

    @staticmethod
    def _page_title() -> QLabel:
        label = QLabel("Browse mods")
        label.setStyleSheet(f"font-size: 23px; font-weight: 650; color: {theme.TEXT};")
        return label

    # -------------------------------------------------------- internals

    def _emit_selection(self) -> None:
        items = self.selected_items()
        count = len(items)
        self.selection_changed.emit(count)
        self.selection_items_changed.emit(items)
        if count >= 2:
            self.bulk_bar.label.setText(f"{count} items selected")
            self.bulk_bar.show()
            self.inspector.hide()
        elif count == 1:
            self.bulk_bar.hide()
        else:
            self.bulk_bar.hide()

    def _reopen_details(self, index):
        # A dismissed item remains selected; clicking it again must reopen it.
        if not self._details_open and len(self.selected_items()) == 1:
            self.item_action_requested.emit((index.data(ItemRole), "inspect"))

    def _activate_card(self, index) -> None:
        item = index.data(ItemRole) if not isinstance(index, bool) else None
        if item is not None:
            self.item_action_requested.emit((item, "inspect"))

    def _open_menu(self, pos) -> None:
        index = self.cards.indexAt(pos)
        if not index.isValid():
            return
        item = index.data(ItemRole)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("Inspect", lambda: self._menu_action(item, "inspect"))
        menu.addAction("Download", lambda: self._menu_action(item, "download"))
        menu.addAction(
            "Preview with required items…", lambda: self._menu_action(item, "preview")
        )
        menu.addAction("Copy Workshop URL", lambda: self._menu_action(item, "copy"))
        menu.exec(self.cards.viewport().mapToGlobal(pos))

    def _menu_action(self, item, action: str) -> None:
        self.item_action_requested.emit((item, action))

    # ------------------------------------------------------ state feeds

    def selected_items(self) -> list:
        selection = self.cards.selectionModel()
        if selection is None:
            return []
        out = []
        for index in selection.selectedIndexes():
            item = index.data(ItemRole)
            if item is not None:
                out.append(item)
        return out

    @property
    def mode(self) -> str:
        index = self.stack.currentIndex()
        return next(
            (name for name, value in self._page_indices.items() if value == index),
            MODE_HERO,
        )

    def set_mode(self, mode: str) -> None:
        self.stack.setCurrentIndex(self._page_indices.get(mode, 0))
        self._update_header_buttons()
        self.search_holder.setVisible(mode != MODE_GRID)
        self.page_title.setText(self.current_game_target[1] if mode == MODE_GRID and self.current_game_target else "Games")
        if mode != MODE_GRID:
            self.content.show()
            self.inspector.hide()

    def set_personal(self, recent, favorites) -> None:
        self.hero.set_games(recent, favorites)

    def set_favorite(self, pinned: bool) -> None:
        self.pin_btn.setChecked(bool(pinned))
        self.pin_btn.setText("Pinned" if pinned else "Pin")
        self.pin_btn.setAccessibleName(
            "Unpin current game" if pinned else "Pin current game"
        )

    def set_mods_folder(self, path: str | None, default_root: str | None = None) -> None:
        """Show the selected game's effective mods folder (override or default)."""
        self._mods_path = str(path or "")
        if default_root is not None:
            self._default_mods_root = str(default_root or "")
        resolved = self._mods_path or self._default_mods_root
        override = "override" if self._mods_path else "default"
        self.mods_btn.setToolTip(
            f"Mods folder ({override}): {resolved}\n"
            "Downloaded items are moved there after download."
        )
        self.mods_btn.setAccessibleName(f"Mods folder ({override}): {resolved}")
        self._update_header_buttons()

    def _show_mods_menu(self) -> None:
        if self.current_game_target is None:
            return
        menu = QMenu(self)
        resolved = self._mods_path or self._default_mods_root
        current = menu.addAction(
            f"Current: {resolved}" if resolved else "Current: not configured"
        )
        current.setEnabled(False)
        menu.addSeparator()
        change = menu.addAction("Change…")
        clear = menu.addAction("Clear (use default)")
        clear.setEnabled(bool(self._mods_path))
        open_folder = menu.addAction("Open folder")
        open_folder.setEnabled(bool(resolved))
        chosen = menu.exec(self.mods_btn.mapToGlobal(self.mods_btn.rect().bottomLeft()))
        if chosen is change:
            self.mods_folder_change_requested.emit()
        elif chosen is clear:
            self.mods_folder_clear_requested.emit()
        elif chosen is open_folder:
            self.mods_folder_open_requested.emit()

    def _update_header_buttons(self) -> None:
        show = self.current_game_target is not None and self.mode != MODE_HERO
        self.change_btn.hide()
        self.pin_btn.setVisible(show)
        self.mods_btn.setVisible(show)

    def _toggle_pin(self) -> None:
        if self.current_game_target is not None:
            self.favorite_toggled.emit(self.current_game_target[0])

    def set_games(self, term: str, games) -> None:
        self.results.set_games(term, games)
        self.set_mode(MODE_RESULTS)

    def set_items(self, items: list, total: int, page: int, pages: int) -> None:
        self.grid_model.set_items(items)
        self.set_pager(page, pages)
        if not items:
            self.browserMessage.setText("No items match this search. Try another search or sort order.")
            self.set_grid_state(
                "No workshop content",
                "This app may not publish ordinary mods; try another sort order, or import links.",
            )
        else:
            self.browserMessage.setText(
                f"{fmt_count(total)} items · page {page} of {pages or 1} · "
                "click a card to inspect · Ctrl/Shift-click to multi-select"
            )
            self.set_grid_state(None)

    def set_grid_state(self, title: str | None, detail: str = "") -> None:
        if title is None:
            self.grid_state.hide()
            self.cards.setEnabled(True)
            return
        self.grid_state.setText(f"<b>{title}</b><br>{detail}" if detail else f"<b>{title}</b>")
        self.grid_state.show()
        self.cards.setEnabled(False)
        self.browserMessage.setText("")

    def set_pager(self, page: int, pages: int) -> None:
        self.pageLabel.setText(f"{page} / {pages or 1}")
        self.prevBtn.setEnabled(page > 1)
        self.nextBtn.setEnabled(page < max(1, pages or 1))

    def set_browser_enabled(self, on: bool) -> None:
        for widget in (self.modSearchEdit, self.sortCombo, self.prevBtn, self.nextBtn):
            widget.setEnabled(on)
        self.pageLabel.setText("—" if not on else self.pageLabel.text())

    def set_game(self, appid: int, name: str) -> None:
        self.current_game_target = (appid, name) if appid else None
        self.game_chip.setText(f"{name} · app {appid}" if appid else "No game selected")
        self.page_title.setText(name or (f"App {appid}" if appid else "Browse mods"))
        self.page_title.setToolTip(name)
        self.page_title.setMinimumWidth(0)
        self.page_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._update_header_buttons()

    def update_game_thumb(self, appid: int, data) -> None:
        self.results.model.update_thumb(appid, data)

    def update_card_thumb(self, fileid: int, data) -> None:
        self.grid_model.update_thumb(fileid, data)

    def current_sort(self) -> str:
        return self.sortCombo.currentData() or "trend"

    def workshop_search_text(self) -> str:
        return self.modSearchEdit.text().strip()

    def clear_workshop_search(self) -> None:
        self.modSearchEdit.clear()

    def card_thumb(self, fileid: int):
        """Cover bytes for the inspector while the item is selected."""
        row = next(
            (r for r in range(self.grid_model.rowCount())
             if self.grid_model.item_at(r) and self.grid_model.item_at(r).publishedfileid == fileid),
            None,
        )
        if row is None:
            return None
        return self.grid_model.index(row).data(ThumbRole)

    def set_presentation(self, presentation: str) -> None:
        presentation = "list" if presentation == "list" else "cards"
        if presentation == self.presentation:
            return
        self.presentation = presentation
        delegate = ItemListDelegate(self.cards) if presentation == "list" else ItemCardDelegate(self.cards)
        old = self.cards.itemDelegate()
        self.cards.setItemDelegate(delegate)
        old.deleteLater()
        self.cards.setFlow(QListView.Flow.TopToBottom if presentation == "list" else QListView.Flow.LeftToRight)
        self.cards.setWrapping(presentation == "cards")
        self.cards.setSpacing(2 if presentation == "list" else GRID_SPACING)
        self.cards_btn.setChecked(presentation == "cards")
        self.list_btn.setChecked(presentation == "list")
        self.cards.doItemsLayout()
        self.presentation_changed.emit(presentation)

    def set_game_context(self, game) -> None:
        self.set_game(game.appid, game.name) if game else self.set_game(0, "")

    def set_detail_layout(self, wide: bool) -> None:
        self._wide_details = wide
        self.content.setVisible(wide or not self._details_open)
        if self._details_open:
            self.inspector.show()
            if wide:
                self.splitter.setSizes([max(1, self.width()-350), 350])

    def set_inspector(self, visible: bool) -> None:
        if visible and not self._details_open:
            self._detail_scroll = self.cards.verticalScrollBar().value()
        self._details_open = visible
        self.inspector.setVisible(visible)
        self.content.setVisible(self._wide_details or not visible)
        if visible and self._wide_details:
            self.splitter.setSizes([max(1, self.width()-350), 350])

    def dismiss_details(self) -> None:
        if not self._details_open:
            return
        self.set_inspector(False)
        self.cards.setFocus()
        scroll = self._detail_scroll
        QTimer.singleShot(0, lambda: self.cards.verticalScrollBar().setValue(scroll))
        self.details_closed.emit()

    def capture_context(self) -> dict:
        return {
            "search": self.modSearchEdit.text(), "sort": self.sortCombo.currentIndex(),
            "selected": [item.publishedfileid for item in self.selected_items()],
            "current": self.cards.currentIndex().row(),
            "scroll": self._detail_scroll if self._details_open and not self._wide_details
                      else self.cards.verticalScrollBar().value(),
            "thumbs": {item.publishedfileid: self.card_thumb(item.publishedfileid)
                       for item in (self.grid_model.item_at(row) for row in range(self.grid_model.rowCount()))},
            "details": self._details_open,
        }

    def restore_context(self, context: dict) -> None:
        self.modSearchEdit.setText(context.get("search", ""))
        self.sortCombo.blockSignals(True)
        self.sortCombo.setCurrentIndex(context.get("sort", 0))
        self.sortCombo.blockSignals(False)
        for fileid, data in context.get("thumbs", {}).items():
            self.update_card_thumb(fileid, data)
        selected = set(context.get("selected", []))
        sm = self.cards.selectionModel()
        for row in range(self.grid_model.rowCount()):
            index = self.grid_model.index(row)
            if index.data(ItemRole).publishedfileid in selected:
                sm.select(index, QItemSelectionModel.SelectionFlag.Select)
        current = self.grid_model.index(context.get("current", -1))
        sm.setCurrentIndex(current, QItemSelectionModel.SelectionFlag.NoUpdate)
        self._selection_timer.stop()
        self._emit_selection()
        if not context.get("details", False):
            self.set_inspector(False)
        value = context.get("scroll", 0)
        self._detail_scroll = value
        QTimer.singleShot(0, lambda: self.cards.verticalScrollBar().setValue(value))

    def focus_game_search(self) -> None:
        self.game_search.setFocus()
        self.game_search.selectAll()

    def focus_workshop_search(self) -> None:
        self.modSearchEdit.setFocus()
