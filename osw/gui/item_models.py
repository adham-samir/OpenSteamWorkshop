"""Model-backed data stores for the Transfer Desk GUI (no item widgets)."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel,
    QAbstractTableModel,
    QModelIndex,
    Qt,
)
from PySide6.QtGui import QImage, QPixmap

from ..models import WorkshopItem, fmt_count, fmt_size, fmt_unix
from ..queue import ACTIVE, JobSnapshot, JobState
from .library import InstalledItem

THUMB = 168  # rendered thumbnail box

GameRole = Qt.ItemDataRole.UserRole + 11
MetaRole = Qt.ItemDataRole.UserRole + 12
TagListRole = Qt.ItemDataRole.UserRole + 13
ThumbRole = Qt.ItemDataRole.UserRole + 14
ItemRole = Qt.ItemDataRole.UserRole + 15
RatingRole = Qt.ItemDataRole.UserRole + 16
SnapshotRole = Qt.ItemDataRole.UserRole + 17
FavoriteRole = Qt.ItemDataRole.UserRole + 18
InstalledItemRole = Qt.ItemDataRole.UserRole + 19


def _as_image(data) -> QImage:
    if isinstance(data, QImage):
        return data
    if isinstance(data, QPixmap):
        return data.toImage()
    img = QImage.fromData(data) if data else QImage()
    return img


# ------------------------------------------------------------------- games


class GameListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._games: list = []
        self._thumbs: dict[int, QImage] = {}
        self._favorites: set[int] = set()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._games)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._games)):
            return None
        game = self._games[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return game.name
        if role == GameRole:
            return game
        img = self._thumbs.get(game.appid)
        if role in (Qt.ItemDataRole.DecorationRole, ThumbRole):
            return img if (img and not img.isNull()) else None
        if role == FavoriteRole:
            return game.appid in self._favorites
        return None

    def set_favorites(self, appids) -> None:
        favorites = {int(appid) for appid in appids or ()}
        if favorites == self._favorites:
            return
        self._favorites = favorites
        if self._games:
            self.dataChanged.emit(
                self.index(0),
                self.index(len(self._games) - 1),
                [FavoriteRole],
            )

    def set_games(self, games: list) -> None:
        self.beginResetModel()
        self._games = list(games or [])
        self._thumbs = {g.appid: self._thumbs.get(g.appid, QImage()) for g in self._games}
        self.endResetModel()

    def update_thumb(self, appid: int, data) -> None:
        row = next((i for i, g in enumerate(self._games) if g.appid == appid), None)
        if row is None:
            return
        img = _as_image(data)
        if img.isNull():
            return
        self._thumbs[self._games[row].appid] = img
        self.dataChanged.emit(self.index(row), self.index(row), [ThumbRole, Qt.ItemDataRole.DecorationRole])

    def game(self, index: QModelIndex):
        return index.data(GameRole)


class ResultsViewDelegateState:  # pragma: no cover - placeholder for typing only
    pass


# ------------------------------------------------------------------- cards


class ItemCardModel(QAbstractListModel):
    """One row per Workshop card; thumbnails stream in by role update."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[WorkshopItem] = []
        self._thumbs: dict[int, QImage] = {}
        self._rendered: dict[int, QImage] = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return item.title or f"item {item.publishedfileid}"
        if role == ItemRole:
            return item
        if role == MetaRole:
            return _meta_line(item)
        if role == RatingRole:
            return f"{item.star_rating:.1f}" if item.star_rating else ""
        if role == TagListRole:
            return item.tags[:3]
        if role in (ThumbRole, Qt.ItemDataRole.DecorationRole):
            return self._rendered.get(item.publishedfileid)
        return None

    def set_items(self, items: list[WorkshopItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        keep = {it.publishedfileid for it in self._items}
        self._thumbs = {k: v for k, v in self._thumbs.items() if k in keep}
        self._rendered = {k: v for k, v in self._rendered.items() if k in keep}
        self.endResetModel()

    def update_thumb(self, fileid: int, data) -> None:
        row = next(
            (i for i, it in enumerate(self._items) if it.publishedfileid == fileid), None
        )
        if row is None:
            return
        img = _as_image(data)
        if img.isNull():
            return
        self._thumbs[fileid] = img
        self._rendered[fileid] = _render_cover(img)
        self.dataChanged.emit(self.index(row), self.index(row), [ThumbRole, Qt.ItemDataRole.DecorationRole])

    def item(self, index: QModelIndex) -> WorkshopItem | None:
        return index.data(ItemRole) if index.isValid() else None

    def item_at(self, row: int) -> WorkshopItem | None:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None


def _meta_line(item: WorkshopItem) -> str:
    bits = []
    size = fmt_size(item.file_size)
    if size:
        bits.append(size)
    subs = fmt_count(item.subscriptions)
    if subs:
        bits.append(f"{subs} subs")
    return " · ".join(bits)


def _render_cover(src: QImage) -> QImage:
    img = src.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                     Qt.TransformationMode.SmoothTransformation)
    return img


# ---------------------------------------------------------------- imports


class ImportPreviewModel(QAbstractTableModel):
    """Include checkbox, Mod, Game ID, Source, Size — one row per resolved item."""

    COLUMNS = ("Include", "Mod", "Game ID", "Source", "Size")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list = []  # list[(include: bool, WorkshopItem, str)]
        self._installed: dict[int, str] = {}  # fileid -> human location

    def reset(self) -> None:
        self.beginResetModel()
        self._rows = []
        self._installed = {}
        self.endResetModel()

    def set_resolution(self, result) -> None:
        self.beginResetModel()
        self._installed = {}
        self._rows = [
            [True, item, "Required" if item.publishedfileid in result.dependencies else "Import"]
            for item in result.items
        ]
        self.endResetModel()

    def mark_installed(self, locations: dict[int, str]) -> int:
        """Flag already-installed rows and uncheck them; returns how many matched.

        Re-checking a flagged row is an explicit reinstall request.
        """
        self._installed = dict(locations)
        matched = 0
        for row in self._rows:
            if row[1].publishedfileid in self._installed:
                row[0] = False
                matched += 1
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, self.columnCount() - 1),
            )
        return matched

    def _source_label(self, row) -> str:
        _include, item, source = row
        if item.publishedfileid in self._installed:
            return f"Installed · {source}" if source != "Import" else "Installed"
        return source

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        include, item, source = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            return Qt.CheckState.Checked if include else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ToolTipRole:
            location = self._installed.get(item.publishedfileid)
            if location:
                return f"Already installed at {location} — re-check to reinstall"
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == 1:
                return item.title or f"item {item.publishedfileid}"
            if col == 2:
                return str(item.appid or "")
            if col == 3:
                return self._source_label(self._rows[index.row()])
            if col == 4:
                return fmt_size(item.file_size) or "Unknown"
        if role == ItemRole:
            return item
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            if isinstance(value, Qt.CheckState):
                include = value == Qt.CheckState.Checked
            else:
                include = bool(value)
            self._rows[index.row()][0] = include
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            return True
        return False

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def checked(self) -> list[WorkshopItem]:
        return [row[1] for row in self._rows if row[0]]

    def checked_count(self) -> int:
        return sum(1 for row in self._rows if row[0])

    def row_count(self) -> int:
        return len(self._rows)


# --------------------------------------------------------------- downloads


class JobFilter:
    ALL = 0
    ACTIVE = 1
    ATTENTION = 2
    FINISHED = 3


FINISHED_STATES = (JobState.DONE, JobState.FAILED, JobState.CANCELLED)


def matches_filter(snapshot: JobSnapshot, filt: int) -> bool:
    if filt == JobFilter.ALL:
        return True
    if filt == JobFilter.ACTIVE:
        return snapshot.state in ACTIVE
    if filt == JobFilter.ATTENTION:
        return snapshot.state in (JobState.FAILED, JobState.INTERRUPTED, JobState.WAITING_FOR_AUTH)
    if filt == JobFilter.FINISHED:
        return snapshot.state in (JobState.DONE, JobState.CANCELLED)
    return False


class JobTableModel(QAbstractTableModel):
    """State of the queue; upsert whichever JobSnapshot the worker emitted."""

    COLUMNS = ("Job", "Size", "Status", "Message", "Actions")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._order: list[str] = []
        self._snapshots: dict[str, JobSnapshot] = {}
        self._filter = JobFilter.ALL
        self._filtered_order: list[str] = []

    # -- mutation ---------------------------------------------------------

    def upsert(self, snapshot: JobSnapshot) -> None:
        known = snapshot.id in self._snapshots
        self._snapshots[snapshot.id] = snapshot
        if not known:
            self._order.append(snapshot.id)
        self._refilter(emit=True)

    def remove(self, job_id: str) -> None:
        if job_id not in self._snapshots:
            return
        del self._snapshots[job_id]
        self._order = [j for j in self._order if j != job_id]
        self._refilter(emit=True)

    def clear(self) -> None:
        self.beginResetModel()
        self._order.clear()
        self._snapshots.clear()
        self._filtered_order = list(self._order)
        self.endResetModel()

    def replace_all(self, snapshots: list[JobSnapshot]) -> None:
        self.clear()
        for snap in snapshots:
            self.upsert(snap)

    def set_filter(self, filt: int) -> None:
        self._filter = filt
        self._refilter(emit=True)

    def _refilter(self, emit: bool) -> None:
        kept = [j for j in self._order if matches_filter(self._snapshots[j], self._filter)]
        self._filtered_order = kept
        if emit:
            self.layoutChanged.emit()

    # -- reads ------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._filtered_order)

    def columnCount(self, parent=QModelIndex()):
        return 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        snap = self._snapshots[self._filtered_order[index.row()]]
        if role == SnapshotRole:
            return snap
        col = index.column()
        if col == 0 and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return snap.title
        if col == 1 and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return _dest_line(snap)
        if col == 2:
            if role == Qt.ItemDataRole.DisplayRole:
                return _state_label(snap.state, snap.progress, snap.output_path)
        if col == 3 and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return _first_line(snap.message) or ("Ready" if snap.state is JobState.QUEUED else "")
        if col == 4 and role == Qt.ItemDataRole.UserRole:
            return actions_for(snap)
        return None

    def snapshot(self, row: int) -> JobSnapshot | None:
        if 0 <= row < len(self._filtered_order):
            return self._snapshots[self._filtered_order[row]]
        return None

    def snapshot_by_id(self, job_id: str) -> JobSnapshot | None:
        return self._snapshots.get(job_id)

    def job_id(self, row: int) -> str | None:
        if 0 <= row < len(self._filtered_order):
            return self._filtered_order[row]
        return None

    def counts(self) -> dict[int, int]:
        active = sum(1 for j in self._snapshots.values() if matches_filter(j, JobFilter.ACTIVE))
        attn = sum(1 for j in self._snapshots.values() if matches_filter(j, JobFilter.ATTENTION))
        finished = sum(1 for j in self._snapshots.values() if matches_filter(j, JobFilter.FINISHED))
        return {JobFilter.ALL: len(self._snapshots), JobFilter.ACTIVE: active,
                JobFilter.ATTENTION: attn, JobFilter.FINISHED: finished}


def _dest_line(snap: JobSnapshot) -> str:
    return getattr(snap, "size_line", "") or ""


def _state_label(state: JobState, progress: float, output_path: str) -> str:
    labels = {
        JobState.QUEUED: "Queued",
        JobState.RUNNING: ("Downloading" if progress > 0 else "Preparing"),
        JobState.WAITING_FOR_AUTH: "Waiting for login",
        JobState.DONE: "Done",
        JobState.FAILED: "Failed",
        JobState.CANCELLED: "Cancelled",
        JobState.INTERRUPTED: "Interrupted",
    }
    return labels.get(state, state.value)


def _first_line(text: str) -> str:
    if not text:
        return ""
    return text.splitlines()[0][:180]


def actions_for(snap: JobSnapshot) -> tuple[str, ...]:
    """Visible per-row actions, in order; the delegate paints and routes clicks."""
    from ..queue import ACTIVE

    if snap.state in ACTIVE:
        return ("Cancel", "Log")
    acts: list[str] = []
    if snap.state is JobState.DONE:
        if snap.output_path:
            acts.append("Open folder")
        acts.append("Log")
    elif snap.state is JobState.FAILED:
        acts.append("Retry")
        if snap.error_kind in ("access", "authentication"):
            acts.append("Retry with account")
        acts.append("Log")
    elif snap.state in (JobState.CANCELLED, JobState.INTERRUPTED):
        acts.append("Resume" if snap.state is JobState.INTERRUPTED else "Retry")
        acts.append("Log")
    return tuple(acts)


# ------------------------------------------------------------------ library


INSTALLED_ACTIONS = ("Open folder", "Inspect in Browse", "Re-download", "Delete")


class InstalledLibraryModel(QAbstractTableModel):
    """Model-backed installed-content table; metadata arrives by role update."""

    COLUMNS = ("Workshop item", "Game", "Location", "Size", "Modified")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[InstalledItem] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(self.COLUMNS)
        ):
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        if role == InstalledItemRole:
            return item
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return (
                item.title or f"Workshop item {item.fileid}",
                item.game_label,
                item.location_label,
                fmt_size(item.size) or "—",
                fmt_unix(item.modified) or "—",
            )[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            bits = [
                item.label,
                f"Workshop ID {item.fileid}",
                f"Game {item.game_label} (app {item.appid})",
                f"Location {item.location_label}",
                f"Installed size {fmt_size(item.size) or 'unknown'}",
            ]
            if item.modified:
                bits.append(f"Modified {fmt_unix(item.modified)}")
            bits.append(str(item.path))
            return "\n".join(bits)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return (
                f"{item.label}, Workshop ID {item.fileid}, "
                f"{item.game_label}, {item.location_label}, "
                f"{fmt_size(item.size) or 'unknown size'}, "
                f"modified {fmt_unix(item.modified) or 'unknown'}"
            )
        return None

    def set_items(self, items: list[InstalledItem]) -> None:
        self.beginResetModel()
        self._items = list(items or [])
        self.endResetModel()

    def item_at(self, row: int) -> InstalledItem | None:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def row_for_id(self, fileid: int) -> int:
        return next(
            (row for row, item in enumerate(self._items) if item.fileid == fileid),
            -1,
        )

    def remove(self, fileid: int) -> None:
        row = self.row_for_id(fileid)
        if row < 0:
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._items[row]
        self.endRemoveRows()

    def apply_metadata(self, metadata: dict) -> None:
        for row, item in enumerate(self._items):
            meta = metadata.get(item.fileid)
            if meta is None:
                continue
            title = getattr(meta, "title", "") or ""
            app_name = getattr(meta, "app_name", "") or ""
            changed = False
            if title and title != item.title:
                item.title = title
                changed = True
            if app_name and app_name != item.app_name:
                item.app_name = app_name
                changed = True
            if changed:
                self.dataChanged.emit(
                    self.index(row, 0),
                    self.index(row, self.columnCount() - 1),
                    [
                        Qt.ItemDataRole.DisplayRole,
                        Qt.ItemDataRole.ToolTipRole,
                        Qt.ItemDataRole.AccessibleTextRole,
                    ],
                )

    def items(self) -> list[InstalledItem]:
        return list(self._items)

    def total_size(self) -> int:
        return sum(item.size for item in self._items)
