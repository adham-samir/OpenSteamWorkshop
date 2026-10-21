"""Browse workspace: landing actions, game results, Workshop cards and inspector."""

from __future__ import annotations

from PySide6.QtCore import QItemSelection, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...models import Game, ItemDetails, WorkshopItem, fmt_count
from ...steam_api import SORTS
from ..components import (
    GAME_ROLE,
    ITEM_ROLE,
    BulkActionBar,
    GameDelegate,
    GameListModel,
    InlineNotice,
    SideInspector,
    StatePanel,
    WorkshopCardDelegate,
    WorkshopListModel,
    WorkshopView,
    fit_wrap,
    make_icon_button,
)
from ..theme import ACCENT, MUTED, icon


class BrowsePage(QWidget):
    searchGamesRequested = Signal(str)
    gameSelected = Signal(int)
    browseRequested = Signal(int, str, str)  # page, sort, search text
    detailsRequested = Signal(object)
    downloadRequested = Signal(object)
    downloadManyRequested = Signal(list)
    importsRequested = Signal(str, bool, object)  # references, dependencies, appid hint
    importLinksRequested = Signal()
    openRequested = Signal(str)
    copyRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_game: Game | None = None
        self.games: list[Game] = []
        self.items: list[WorkshopItem] = []
        self.page = 1
        self.total_pages = 1
        self._last_term = ""
        self._has_results = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        self.landing = self._build_landing()
        self.results = self._build_results()
        self.workshop = self._build_workshop()
        self.stack.addWidget(self.landing)
        self.stack.addWidget(self.results)
        self.stack.addWidget(self.workshop)

    # ------------------------------------------------------------- landing

    def _build_landing(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 30, 26, 22)
        layout.setSpacing(18)
        layout.addStretch(1)
        eyebrow = QLabel("TRANSFER DESK")
        eyebrow.setProperty("role", "caption")
        eyebrow.setStyleSheet(f"color:{ACCENT};")
        layout.addWidget(eyebrow, 0, Qt.AlignHCenter)
        title = QLabel("Get Workshop content into your mods folder.")
        title.setProperty("role", "h1")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)
        body = QLabel(
            "Find a game, browse its Workshop, and queue a mod — or bring a link, "
            "collection, or text list. SteamCMD does the download; no game install is needed."
        )
        body.setProperty("role", "muted")
        body.setAlignment(Qt.AlignCenter)
        body.setWordWrap(True)
        body.setMaximumWidth(620)
        fit_wrap(body, 620)
        layout.addWidget(body, 0, Qt.AlignHCenter)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        find_card = QFrame()
        find_card.setProperty("panel", True)
        find_layout = QVBoxLayout(find_card)
        find_layout.setContentsMargins(18, 16, 18, 16)
        find_layout.setSpacing(8)
        find_title = QLabel("Find a game")
        find_title.setProperty("role", "h2")
        find_layout.addWidget(find_title)
        find_body = QLabel("Search the public Steam store, then browse that game's Workshop.")
        find_body.setProperty("role", "muted")
        find_body.setWordWrap(True)
        find_layout.addWidget(find_body)
        search_row = QHBoxLayout()
        search_row.setSpacing(7)
        self.landing_search = QLineEdit()
        self.landing_search.setPlaceholderText("Game name, app ID, or Steam URL")
        self.landing_search.setAccessibleName("Game search")
        self.landing_search.returnPressed.connect(self._emit_game_search)
        search_row.addWidget(self.landing_search, 1)
        self.find_button = QPushButton("Find game")
        self.find_button.setProperty("role", "primary")
        self.find_button.setIcon(icon("search", "#071219", 15))
        self.find_button.clicked.connect(self._emit_game_search)
        search_row.addWidget(self.find_button)
        find_layout.addLayout(search_row)
        find_layout.addStretch(1)
        cards.addWidget(find_card, 1)

        import_card = QFrame()
        import_card.setProperty("panel", True)
        import_layout = QVBoxLayout(import_card)
        import_layout.setContentsMargins(18, 16, 18, 16)
        import_layout.setSpacing(8)
        import_title = QLabel("Import Workshop links")
        import_title.setProperty("role", "h2")
        import_layout.addWidget(import_title)
        import_body = QLabel(
            "Paste item or collection links, import a text file, and review every "
            "dependency before queueing."
        )
        import_body.setProperty("role", "muted")
        import_body.setWordWrap(True)
        import_layout.addWidget(import_body)
        self.import_button = QPushButton("Open Imports")
        self.import_button.setIcon(icon("imports", MUTED, 15))
        self.import_button.setAccessibleName("Import Workshop links")
        self.import_button.clicked.connect(lambda: self.importLinksRequested.emit())
        import_layout.addWidget(self.import_button, 0, Qt.AlignLeft)
        import_layout.addStretch(1)
        cards.addWidget(import_card, 1)
        layout.addLayout(cards, 0)
        self.message = InlineNotice()
        layout.addWidget(self.message)
        footnote = QLabel(
            "Anonymous downloads are the default. Some items require a Steam account; "
            "you can retry those from Downloads without losing your place."
        )
        footnote.setProperty("role", "muted")
        footnote.setAlignment(Qt.AlignCenter)
        footnote.setWordWrap(True)
        fit_wrap(footnote, 720)
        layout.addWidget(footnote, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        return page

    def _emit_game_search(self) -> None:
        text = self.landing_search.text().strip()
        if text:
            self.searchGamesRequested.emit(text)

    # ------------------------------------------------------------- results

    def _build_results(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(10)
        back = make_icon_button(
            "chevron-left", "Back to Browse start", self.show_landing, size=32
        )
        head.addWidget(back)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.results_title = QLabel("Game results")
        self.results_title.setProperty("role", "h2")
        titles.addWidget(self.results_title)
        self.results_sub = QLabel("Select a game to open its Workshop.")
        self.results_sub.setProperty("role", "muted")
        titles.addWidget(self.results_sub)
        head.addLayout(titles, 1)
        self.results_stack = QStackedWidget()
        layout.addLayout(head)
        self.game_model = GameListModel(self)
        self.game_list = QListView(self)
        self.game_list.setViewMode(QListView.ListMode)
        self.game_list.setSpacing(0)
        self.game_list.setUniformItemSizes(False)
        self.game_list.setItemDelegate(GameDelegate(self.game_list))
        self.game_list.setModel(self.game_model)
        self.game_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.game_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.game_list.setAccessibleName("Game search results")
        self.game_list.clicked.connect(self._game_clicked)
        self.game_list.activated.connect(self._game_clicked)
        self.game_state = StatePanel()
        self.results_stack.addWidget(self.game_list)
        self.results_stack.addWidget(self.game_state)
        layout.addWidget(self.results_stack, 1)
        return page

    def _game_clicked(self, index) -> None:
        game = index.data(GAME_ROLE)
        if game is not None:
            self.gameSelected.emit(game.appid)

    def show_search_loading(self, term: str) -> None:
        self._last_term = term
        self.stack.setCurrentWidget(self.results)
        self.results_title.setText(f'Game results for “{term}”')
        self.results_sub.setText("Searching the Steam store…")
        self.game_model.set_games([])
        self.game_state.set_state(
            "loading", "Searching Steam", f"Looking for games matching “{term}”."
        )
        self.results_stack.setCurrentWidget(self.game_state)

    def show_games(self, games: list[Game], term: str) -> None:
        self._last_term = term
        self._has_results = bool(games)
        self.games = list(games)
        self.stack.setCurrentWidget(self.results)
        self.results_title.setText(f'Game results for “{term}”')
        self.game_model.set_games(self.games)
        if not self.games:
            self.results_sub.setText("No matching games")
            self.game_state.set_state(
                "no-results",
                "No games found",
                f'Nothing in the Steam store matched “{term}”. Try another name, or '
                "paste an app ID or Workshop link.",
                [
                    ("Search again", "primary", self.focus_primary),
                    ("Import links instead", "", self.importLinksRequested.emit),
                ],
            )
            self.results_stack.setCurrentWidget(self.game_state)
            return
        self.results_sub.setText(
            f"{len(self.games)} result{'s' if len(self.games) != 1 else ''} · "
            "select a game to browse its Workshop"
        )
        self.results_stack.setCurrentWidget(self.game_list)
        self.game_list.setFocus()

    def show_search_error(self, message: str, term: str | None = None) -> None:
        self._last_term = term or self._last_term
        self.stack.setCurrentWidget(self.results)
        self.results_title.setText(
            f'Game results for “{self._last_term}”' if self._last_term else "Game search"
        )
        self.results_sub.setText("Search could not complete")
        self.game_state.set_state(
            "offline",
            "Could not search Steam",
            message,
            [
                ("Try again", "primary", self.focus_primary),
                ("Import links instead", "", self.importLinksRequested.emit),
            ],
        )
        self.results_stack.setCurrentWidget(self.game_state)
        self.message.show_message("error", message)

    def set_game_image(self, appid: int, pixmap: QPixmap) -> None:
        self.game_model.set_image(appid, pixmap)

    # ------------------------------------------------------------ workshop

    def _build_workshop(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 14, 24, 12)
        layout.setSpacing(9)

        context = QHBoxLayout()
        context.setSpacing(10)
        self.workshop_back = make_icon_button(
            "chevron-left", "Back to game results", self._back_from_workshop, size=32
        )
        context.addWidget(self.workshop_back)
        names = QVBoxLayout()
        names.setSpacing(1)
        self.game_title = QLabel()
        self.game_title.setProperty("role", "h2")
        names.addWidget(self.game_title)
        self.game_meta = QLabel()
        self.game_meta.setProperty("role", "muted")
        names.addWidget(self.game_meta)
        context.addLayout(names, 1)
        self.change_game = QPushButton("Change game")
        self.change_game.setProperty("role", "ghost")
        self.change_game.clicked.connect(self._back_from_workshop)
        context.addWidget(self.change_game)
        layout.addLayout(context)

        tools = QHBoxLayout()
        tools.setSpacing(7)
        self.mod_search = QLineEdit()
        self.mod_search.setPlaceholderText("Search this game's Workshop")
        self.mod_search.setAccessibleName("Workshop search")
        self.mod_search.setClearButtonEnabled(True)
        self.mod_search.returnPressed.connect(self._emit_browse)
        tools.addWidget(self.mod_search, 1)
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self._emit_browse)
        tools.addWidget(self.search_button)
        self.sort_combo = QComboBox()
        for key, label in SORTS.items():
            self.sort_combo.addItem(label, key)
        self.sort_combo.setAccessibleName("Workshop sort order")
        self.sort_combo.setMinimumWidth(132)
        self.sort_combo.currentIndexChanged.connect(self._emit_browse)
        tools.addWidget(self.sort_combo)
        self.prev_button = make_icon_button(
            "chevron-left", "Previous page", lambda: self._goto_page(-1), size=32
        )
        tools.addWidget(self.prev_button)
        self.page_label = QLabel("—")
        self.page_label.setProperty("role", "muted")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setMinimumWidth(54)
        tools.addWidget(self.page_label)
        self.next_button = make_icon_button(
            "chevron-right", "Next page", lambda: self._goto_page(1), size=32
        )
        tools.addWidget(self.next_button)
        layout.addLayout(tools)

        self.workshop_notice = InlineNotice()
        layout.addWidget(self.workshop_notice)
        self.bulk_bar = BulkActionBar()
        self.bulk_bar.reviewRequested.connect(self._review_ids)
        self.bulk_bar.downloadRequested.connect(self.downloadManyRequested)
        self.bulk_bar.clearRequested.connect(self.clear_selection)
        layout.addWidget(self.bulk_bar)

        self.workshop_model = WorkshopListModel(self)
        self.cards = WorkshopView()
        self.cards.setItemDelegate(WorkshopCardDelegate(self.cards))
        self.cards.setModel(self.workshop_model)
        self.cards.selectionModel().selectionChanged.connect(self._selection_changed)
        self.cards.doubleClicked.connect(self._open_inspector)
        self.cards.customContextMenuRequested.connect(self._context_menu)
        self.workshop_state = StatePanel()
        self.cards_stack = QStackedWidget()
        self.cards_stack.addWidget(self.cards)
        self.cards_stack.addWidget(self.workshop_state)

        self.inspector = SideInspector()
        self.inspector.downloadRequested.connect(self._inspector_download)
        self.inspector.importRequested.connect(
            lambda item, deps: self.importsRequested.emit(
                str(item.publishedfileid), deps, item.appid or self._appid()
            )
        )
        self.inspector.openRequested.connect(self.openRequested)
        self.inspector.copyRequested.connect(self.copyRequested)
        self.inspector.closeRequested.connect(self.clear_selection)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.cards_stack)
        self.splitter.addWidget(self.inspector)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([760, 340])
        layout.addWidget(self.splitter, 1)
        self.hint = QLabel(
            "Ctrl/Shift-click to select multiple mods · Enter opens the inspector · Esc clears selection"
        )
        self.hint.setProperty("role", "muted")
        layout.addWidget(self.hint)
        self._set_browse_enabled(False)
        return page

    def _appid(self) -> int | None:
        return self.current_game.appid if self.current_game else None

    def show_workshop(self, game: Game, *, loading: bool = True) -> None:
        self.current_game = game
        self.items = []
        self.workshop_model.set_items([])
        self.game_title.setText(game.name)
        self.game_meta.setText(
            f"App ID {game.appid} · Workshop items · anonymous access by default"
        )
        self.page_label.setText("—")
        self.cards_stack.setCurrentWidget(self.workshop_state)
        self.bulk_bar.set_items([])
        self.inspector.clear()
        self.workshop_notice.dismiss()
        self.stack.setCurrentWidget(self.workshop)
        self._set_browse_enabled(True)
        if loading:
            self.set_browse_loading()

    def set_browse_loading(self) -> None:
        self.workshop_notice.dismiss()
        self.workshop_state.set_state(
            "loading", "Loading Workshop items", "Reading the game's public Workshop catalogue."
        )
        self.cards_stack.setCurrentWidget(self.workshop_state)
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.page_label.setText("…")

    def show_items(
        self, items: list[WorkshopItem], total: int, pages: int, page: int
    ) -> None:
        self.items = list(items)
        self.page = page
        self.total_pages = max(1, pages)
        self.workshop_model.set_items(self.items)
        self.page_label.setText(f"{self.page} / {self.total_pages}")
        self.prev_button.setEnabled(self.page > 1)
        self.next_button.setEnabled(self.page < self.total_pages)
        if not self.items:
            self.workshop_state.set_state(
                "no-results",
                "No Workshop items match",
                "Try another search or sort order. Some games publish their mods "
                "on another platform.",
                [
                    ("Clear search", "primary", self._clear_search),
                    ("Change game", "", self._back_from_workshop),
                ],
            )
            self.cards_stack.setCurrentWidget(self.workshop_state)
            return
        self.cards_stack.setCurrentWidget(self.cards)
        appid = (
            self.current_game.appid
            if self.current_game is not None
            else (self.items[0].appid if self.items else "—")
        )
        self.game_meta.setText(
            f"App ID {appid} · {fmt_count(total)} items · "
            f"page {self.page} of {self.total_pages}"
        )
        self.workshop_notice.dismiss()

    def show_browse_error(self, message: str) -> None:
        self.workshop_notice.show_message("error", message)
        self.workshop_state.set_state(
            "error",
            "Could not load this Workshop",
            message,
            [
                ("Try again", "primary", self._emit_browse),
                ("Change game", "", self._back_from_workshop),
            ],
        )
        self.cards_stack.setCurrentWidget(self.workshop_state)
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)

    def set_thumb(self, fileid: int, pixmap: QPixmap) -> None:
        self.workshop_model.set_thumb(fileid, pixmap)

    def set_page(self, page: int, pages: int) -> None:
        self.page = page
        self.total_pages = max(1, pages)
        self.page_label.setText(f"{self.page} / {self.total_pages}")
        self.prev_button.setEnabled(self.page > 1)
        self.next_button.setEnabled(self.page < self.total_pages)

    def _set_browse_enabled(self, enabled: bool) -> None:
        for widget in (
            self.mod_search,
            self.search_button,
            self.sort_combo,
            self.prev_button,
            self.next_button,
        ):
            widget.setEnabled(enabled)

    def _emit_browse(self) -> None:
        if self.current_game is None:
            return
        sort = self.sort_combo.currentData() or "trend"
        self.browseRequested.emit(1, sort, self.mod_search.text().strip())

    def _goto_page(self, delta: int) -> None:
        target = max(1, min(self.total_pages, self.page + delta))
        if target == self.page:
            return
        sort = self.sort_combo.currentData() or "trend"
        self.browseRequested.emit(target, sort, self.mod_search.text().strip())

    def _clear_search(self) -> None:
        self.mod_search.clear()
        self._emit_browse()

    def _back_from_workshop(self) -> None:
        self.clear_selection()
        if self._has_results:
            self.stack.setCurrentWidget(self.results)
            self.game_list.setFocus()
        else:
            self.show_landing()

    # ----------------------------------------------------------- selection

    def selected_items(self) -> list[WorkshopItem]:
        rows = sorted({index.row() for index in self.cards.selectionModel().selectedIndexes()})
        return [item for row in rows if (item := self.workshop_model.item_at(row)) is not None]

    def _selection_changed(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        items = self.selected_items()
        if len(items) == 1:
            item = items[0]
            thumb = self.workshop_model.thumb_for_id(item.publishedfileid)
            self.inspector.show_item(item)
            if thumb is not None:
                # The inspector has no preview; keeping the thumbnail in the model is enough.
                pass
            self.inspector.setVisible(True)
            self.bulk_bar.set_items([])
            self.detailsRequested.emit(item)
        elif len(items) > 1:
            self.inspector.clear()
            self.bulk_bar.set_items(items)
        else:
            self.inspector.clear()
            self.bulk_bar.set_items([])

    def clear_selection(self) -> None:
        self.cards.clearSelection()
        self.inspector.clear()
        self.bulk_bar.set_items([])
        self.cards.setFocus()

    def _open_inspector(self, index) -> None:
        item = index.data(ITEM_ROLE)
        if item is None:
            return
        self.inspector.show_item(item)
        self.detailsRequested.emit(item)

    def _inspector_download(self, item: WorkshopItem) -> None:
        if item.file_type == 2:
            self.importsRequested.emit(
                str(item.publishedfileid), True, item.appid or self._appid()
            )
        else:
            self.downloadRequested.emit(item)

    def _review_ids(self, ids: list[int]) -> None:
        self.importsRequested.emit(
            "\n".join(str(n) for n in ids), False, self._appid()
        )

    def _context_menu(self, pos) -> None:
        index = self.cards.indexAt(pos)
        if not index.isValid():
            return
        self.cards.setCurrentIndex(index)
        item = index.data(ITEM_ROLE)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("Inspect", lambda: self._open_inspector(index))
        menu.addAction("Download", lambda: self._inspector_download(item))
        menu.addAction(
            "Review in Imports",
            lambda: self.importsRequested.emit(
                str(item.publishedfileid), bool(item.children), item.appid or self._appid()
            ),
        )
        menu.addSeparator()
        menu.addAction("Open in browser", lambda: self.openRequested.emit(item.url))
        menu.addAction(
            "Copy Workshop URL", lambda: self.copyRequested.emit(item.url)
        )
        menu.exec(self.cards.mapToGlobal(pos))

    def show_details(self, details: ItemDetails) -> bool:
        if self.inspector.fileid != details.fileid:
            return False
        return self.inspector.show_details(details)

    def show_details_error(self, fileid: int, message: str) -> None:
        if self.inspector.fileid == fileid:
            self.inspector.show_error(message)

    # ------------------------------------------------------------ lifecycle

    def show_landing(self) -> None:
        self.stack.setCurrentWidget(self.landing)
        self.clear_selection()
        self.landing_search.setFocus()

    def focus_primary(self) -> None:
        if self.stack.currentWidget() is self.workshop:
            if not self.mod_search.hasFocus():
                self.mod_search.setFocus()
                self.mod_search.selectAll()
        elif self.stack.currentWidget() is self.results:
            self.game_list.setFocus()
        else:
            self.landing_search.setFocus()
            self.landing_search.selectAll()

    def focus_workshop_search(self) -> None:
        if self.stack.currentWidget() is self.workshop:
            self.mod_search.setFocus()
            self.mod_search.selectAll()
            return
        self.focus_primary()

    def current_workspace_summary(self) -> str:
        if self.stack.currentWidget() is self.workshop and self.current_game:
            return f"{self.current_game.name} · Workshop"
        if self.stack.currentWidget() is self.results:
            return f"Game search · {self._last_term}"
        return "Find a game or import Workshop links"
