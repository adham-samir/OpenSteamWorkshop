"""Game selection, with real history and model-backed artwork surfaces."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .delegates import GameCardDelegate
from .item_models import GameListModel, GameRole


class GamesPage(QWidget):
    search_requested = Signal(str)
    app_picked = Signal(int)
    import_requested = Signal()

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(16)
        title = QLabel("Your next mod starts with a game")
        title.setProperty("role", "h1")
        outer.addWidget(title)
        self.subtitle = QLabel("Find a game to explore its Steam Workshop. No game installation needed.")
        self.subtitle.setWordWrap(True)
        self.subtitle.setProperty("role", "muted")
        outer.addWidget(self.subtitle)
        search = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search games by name, app ID, or Steam link")
        self.search.setAccessibleName("Search games")
        self.search.setMinimumHeight(24)
        search.addWidget(self.search, 1)
        self.find = QPushButton("Find game")
        self.find.setProperty("role", "primary")
        self.find.clicked.connect(self._search)
        self.search.returnPressed.connect(self._search)
        search.addWidget(self.find)
        outer.addLayout(search)
        self.stack = QStackedWidget()
        personal = QWidget()
        pv = QVBoxLayout(personal)
        pv.setContentsMargins(0, 8, 0, 0)
        pv.setSpacing(18)
        self.pinned_box, self.pinned = self._section("Pinned games")
        self.recent_box, self.recent = self._section("Recently opened")
        pv.addWidget(self.pinned_box)
        pv.addWidget(self.recent_box)
        self.first_use = QLabel(
            "Choose your game, inspect a mod, then download.\n"
            "Already have a Workshop link or collection? Import it directly."
        )
        self.first_use.setWordWrap(True)
        self.first_use.setProperty("role", "muted")
        pv.addWidget(self.first_use)
        pv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(personal)
        self.stack.addWidget(scroll)
        results = QWidget()
        rv = QVBoxLayout(results)
        rv.setContentsMargins(0, 0, 0, 0)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setProperty("role", "muted")
        rv.addWidget(self.message)
        self.results = self._view()
        rv.addWidget(self.results, 1)
        self.back = QPushButton("Back to your games")
        self.back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        rv.addWidget(self.back, 0, Qt.AlignmentFlag.AlignLeft)
        self.stack.addWidget(results)
        outer.addWidget(self.stack, 1)
        alternative = QHBoxLayout()
        alternative.addWidget(QLabel("Have a link or a collection?"))
        add = QPushButton("Import links")
        add.setProperty("role", "ghost")
        add.clicked.connect(self.import_requested.emit)
        alternative.addWidget(add)
        alternative.addStretch(1)
        outer.addLayout(alternative)
        self.set_personal([], [])

    def _view(self):
        view = QListView()
        view.setModel(GameListModel(view))
        view.setItemDelegate(GameCardDelegate(view))
        view.setFlow(QListView.Flow.LeftToRight)
        view.setWrapping(True)
        view.setResizeMode(QListView.ResizeMode.Adjust)
        view.setUniformItemSizes(True)
        view.setSpacing(6)
        view.setMovement(QListView.Movement.Static)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setAccessibleName("Choose a game")
        view.clicked.connect(self._picked)
        view.activated.connect(self._picked)
        return view

    def _section(self, text):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(text)
        label.setProperty("role", "h2")
        layout.addWidget(label)
        view = self._view()
        view.setFixedHeight(182)
        layout.addWidget(view)
        return box, view

    def _picked(self, index):
        game = index.data(GameRole)
        if game:
            self.app_picked.emit(game.appid)

    def _search(self):
        self.search_requested.emit(self.search.text().strip())

    def set_personal(self, recent, pinned):
        self.recent.model().set_games(recent)
        self.pinned.model().set_games(pinned)
        self.recent_box.setVisible(bool(recent))
        self.pinned_box.setVisible(bool(pinned))
        self.first_use.setVisible(not recent and not pinned)
        QTimer.singleShot(0, self._fit_sections)

    def _fit_sections(self):
        for view in (self.recent, self.pinned):
            columns = max(1, (self.width()-70)//244)
            rows = max(1, (view.model().rowCount()+columns-1)//columns)
            view.setFixedHeight(rows*176)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._fit_sections()

    def show_loading(self, term):
        self.stack.setCurrentIndex(1)
        self.message.setText(f'Searching Steam for “{term}”…')
        self.results.model().set_games([])
        self.find.setEnabled(False)

    def set_games(self, term, games):
        self.stack.setCurrentIndex(1)
        self.results.model().set_games(games)
        self.find.setEnabled(True)
        self.message.setText(
            f'{len(games)} games for “{term}” · choose a game to browse mods'
            if games else f'No games found for “{term}”. Try another name or paste an app ID.'
        )

    def update_thumb(self, appid, data):
        for view in (self.recent, self.pinned, self.results):
            view.model().update_thumb(appid, data)
