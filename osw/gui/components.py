"""Reusable Transfer Desk components and model-backed views."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import (
    QAbstractListModel,
    QAbstractTableModel,
    QModelIndex,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListView,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..models import Game, ItemDetails, WorkshopItem, fmt_count, fmt_size, fmt_unix
from ..queue import ACTIVE, JobSnapshot, JobState
from .theme import (
    ACCENT,
    ACCENT_DIM,
    ACCENT_INK,
    AMBER,
    BG,
    BORDER,
    GREEN,
    MUTED,
    RAIL,
    RED,
    SURFACE,
    TEXT,
    icon,
    mono_font,
)

ITEM_ROLE = Qt.UserRole + 1
GAME_ROLE = Qt.UserRole + 2
THUMB_ROLE = Qt.UserRole + 3
JOB_ROLE = Qt.UserRole + 4
JOB_ID_ROLE = Qt.UserRole + 5
PROGRESS_ROLE = Qt.UserRole + 6
STATE_ROLE = Qt.UserRole + 7

STATE_LOOK = {
    JobState.QUEUED: ("Queued", "clock", MUTED),
    JobState.RUNNING: ("Running", "downloads", ACCENT),
    JobState.WAITING_FOR_AUTH: ("Waiting for login", "user", AMBER),
    JobState.DONE: ("Complete", "check", GREEN),
    JobState.FAILED: ("Failed", "alert", RED),
    JobState.CANCELLED: ("Cancelled", "cancel", MUTED),
    JobState.INTERRUPTED: ("Interrupted", "alert", AMBER),
}


def _hint(text: str) -> str:
    return f'<span style="color:{MUTED}">{escape(text)}</span>'


def fit_wrap(label: QLabel, width: int) -> None:
    """Pin a word-wrapped label to ``width`` and reserve its real text height.

    Qt's box layouts can collapse centred word-wrapped labels to a single line;
    this makes their minimum height match the wrapped text.
    """
    label.setFixedWidth(width)
    label.ensurePolished()
    label.setMinimumHeight(max(label.fontMetrics().lineSpacing(), label.heightForWidth(width)))


def _two_lines(text: str, metrics: QFontMetrics, width: int) -> list[str]:
    text = " ".join((text or "").split())
    if not text:
        return [""]
    if metrics.horizontalAdvance(text) <= width:
        return [text]
    words = text.split(" ")
    first = ""
    for index, word in enumerate(words):
        candidate = f"{first} {word}".strip()
        if metrics.horizontalAdvance(candidate) <= width:
            first = candidate
            continue
        rest = " ".join(words[index:])
        left = first or metrics.elidedText(word, Qt.ElideRight, width)
        return [left, metrics.elidedText(rest, Qt.ElideRight, width)]
    return [metrics.elidedText(first, Qt.ElideRight, width)]


def _paint_cover(painter: QPainter, pixmap: QPixmap, rect: QRectF, radius: float) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.save()
    painter.setClipPath(path)
    target = QSize(max(0, int(rect.width())), max(0, int(rect.height())))
    if target.width() <= 0 or target.height() <= 0:
        painter.restore()
        return
    scaled = pixmap.scaled(target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    source = QRectF(
        max(0, (scaled.width() - target.width()) / 2),
        max(0, (scaled.height() - target.height()) / 2),
        target.width(),
        target.height(),
    )
    painter.drawPixmap(rect, scaled, source)
    painter.restore()


# --------------------------------------------------------------------- games


class GameListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._games: list[Game] = []
        self._images: dict[int, QPixmap] = {}

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._games)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._games):
            return None
        game = self._games[index.row()]
        if role == Qt.DisplayRole:
            return game.name
        if role == GAME_ROLE:
            return game
        if role == Qt.DecorationRole:
            return self._images.get(game.appid)
        if role == Qt.ToolTipRole:
            return f"{game.name}\nApp ID {game.appid} · {game.type.title()}"
        if role == Qt.AccessibleTextRole:
            return f"{game.name}, app {game.appid}, {game.type}"
        return None

    def set_games(self, games: list[Game]) -> None:
        self.beginResetModel()
        self._games = list(games)
        self._images = {k: v for k, v in self._images.items() if any(g.appid == k for g in games)}
        self.endResetModel()

    def set_image(self, appid: int, pixmap: QPixmap) -> None:
        self._images[appid] = pixmap
        row = self.row_for_appid(appid)
        if row >= 0:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, [Qt.DecorationRole])

    def row_for_appid(self, appid: int) -> int:
        return next((n for n, game in enumerate(self._games) if game.appid == appid), -1)

    def game_at(self, row: int) -> Game | None:
        return self._games[row] if 0 <= row < len(self._games) else None

    def games(self) -> list[Game]:
        return list(self._games)


class GameDelegate(QStyledItemDelegate):
    HEIGHT = 68

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(300, self.HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect.adjusted(2, 2, -2, -2))
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        background = QColor("#19222B" if selected else ("#1B222A" if hover else SURFACE))
        painter.setBrush(background)
        painter.setPen(QPen(QColor(ACCENT if selected else BORDER), 1))
        painter.drawRoundedRect(rect, 8, 8)

        thumb = QRectF(rect.left() + 7, rect.top() + 7, 112, rect.height() - 14)
        painter.setBrush(QColor("#222B35"))
        painter.setPen(QPen(QColor("#2A3440"), 1))
        painter.drawRoundedRect(thumb, 5, 5)
        pixmap = index.data(Qt.DecorationRole)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            _paint_cover(painter, pixmap, thumb, 5)
        else:
            placeholder = icon("games", "#526273", 26).pixmap(26, 26)
            painter.drawPixmap(
                int(thumb.center().x() - 13), int(thumb.center().y() - 13), placeholder
            )

        game: Game = index.data(GAME_ROLE)
        title_font = QFont(option.font)
        title_font.setPointSizeF(max(9.0, option.font.pointSizeF() + 0.5))
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(TEXT))
        title_rect = QRectF(thumb.right() + 13, rect.top() + 14, rect.width() - 160, 20)
        metrics = QFontMetrics(title_font)
        painter.drawText(
            title_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            metrics.elidedText(game.name, Qt.ElideRight, int(title_rect.width())),
        )
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(max(8.0, option.font.pointSizeF() - 1.0))
        painter.setFont(sub_font)
        painter.setPen(QColor(MUTED))
        painter.drawText(
            QRectF(title_rect.left(), rect.top() + 34, rect.width() - 178, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"App {game.appid}  ·  {game.type.title()}",
        )
        chevron = icon("chevron-right", "#66717D", 15).pixmap(15, 15)
        painter.drawPixmap(int(rect.right() - 24), int(rect.center().y() - 7), chevron)
        painter.restore()


# ------------------------------------------------------------------ workshop

CARD_W = 248
CARD_H = 258
GRID_W = 256
GRID_H = 272


class WorkshopListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[WorkshopItem] = []
        self._thumbs: dict[int, QPixmap] = {}

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        if role == Qt.DisplayRole:
            return item.title or f"Item {item.publishedfileid}"
        if role == ITEM_ROLE:
            return item
        if role == THUMB_ROLE:
            return self._thumbs.get(item.publishedfileid)
        if role == Qt.ToolTipRole:
            bits = [item.title or f"Item {item.publishedfileid}"]
            if item.short_description:
                bits.append(item.short_description[:320])
            meta = []
            if item.file_size:
                meta.append(fmt_size(item.file_size))
            meta.append(f"{fmt_count(item.subscriptions)} subscribers")
            if item.star_rating:
                meta.append(f"★ {item.star_rating:.1f}/5")
            if item.time_updated:
                meta.append(f"updated {fmt_unix(item.time_updated)}")
            if meta:
                bits.append(" · ".join(meta))
            if item.tags:
                bits.append(", ".join(item.tags[:6]))
            bits.append(f"Workshop ID {item.publishedfileid}")
            return "\n".join(bits)
        if role == Qt.AccessibleTextRole:
            bits = [item.title or f"Item {item.publishedfileid}"]
            if item.file_size:
                bits.append(fmt_size(item.file_size))
            bits.append(f"{fmt_count(item.subscriptions)} subscribers")
            if item.star_rating:
                bits.append(f"rated {item.star_rating:.1f} out of 5")
            if item.tags:
                bits.append("tags " + ", ".join(item.tags[:4]))
            return ", ".join(bits)
        return None

    def set_items(self, items: list[WorkshopItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self._thumbs = {
            key: value for key, value in self._thumbs.items() if any(i.publishedfileid == key for i in items)
        }
        self.endResetModel()

    def set_thumb(self, fileid: int, pixmap: QPixmap) -> None:
        self._thumbs[fileid] = pixmap
        row = self.row_for_id(fileid)
        if row >= 0:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, [THUMB_ROLE])

    def items(self) -> list[WorkshopItem]:
        return list(self._items)

    def item_at(self, row: int) -> WorkshopItem | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def row_for_id(self, fileid: int) -> int:
        return next((n for n, item in enumerate(self._items) if item.publishedfileid == fileid), -1)

    def thumb_for_id(self, fileid: int) -> QPixmap | None:
        return self._thumbs.get(fileid)


class WorkshopCardDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(GRID_W, GRID_H)

    def paint(self, painter: QPainter, option, index) -> None:
        item: WorkshopItem = index.data(ITEM_ROLE)
        if item is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect.adjusted(2, 2, -2, -2))
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        background = QColor("#19222B" if selected else ("#1B222A" if hover else SURFACE))
        painter.setBrush(background)
        painter.setPen(QPen(QColor(ACCENT if selected else BORDER), 1))
        painter.drawRoundedRect(rect, 9, 9)

        thumb = QRectF(rect.left() + 8, rect.top() + 8, rect.width() - 16, 116)
        painter.setBrush(QColor("#222B35"))
        painter.setPen(QPen(QColor("#2A3440"), 1))
        painter.drawRoundedRect(thumb, 6, 6)
        pixmap = index.data(THUMB_ROLE)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            _paint_cover(painter, pixmap, thumb, 6)
        else:
            placeholder = icon("eye", "#526273", 36).pixmap(36, 36)
            painter.drawPixmap(
                int(thumb.center().x() - 18), int(thumb.center().y() - 18), placeholder
            )

        if item.tags:
            kind = item.tags[0].upper()[:14]
            kind_font = QFont(option.font)
            kind_font.setPixelSize(9)
            kind_font.setWeight(QFont.Medium)
            bridge = QFontMetrics(kind_font)
            chip_w = bridge.horizontalAdvance(kind) + 12
            chip_rect = QRectF(thumb.left() + 7, thumb.top() + 7, chip_w, 18)
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.setBrush(QColor("#151B22"))
            painter.drawRoundedRect(chip_rect, 4, 4)
            painter.setFont(kind_font)
            painter.setPen(QColor("#A9B4C0"))
            painter.drawText(chip_rect, Qt.AlignCenter, kind)

        if selected:
            check_rect = QRectF(thumb.right() - 25, thumb.top() + 7, 18, 18)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(ACCENT))
            painter.drawEllipse(check_rect)
            check = icon("check", ACCENT_INK, 12).pixmap(12, 12)
            painter.drawPixmap(
                int(check_rect.center().x() - 6), int(check_rect.center().y() - 6), check
            )

        title_font = QFont(option.font)
        title_font.setPixelSize(13)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(TEXT))
        metrics = QFontMetrics(title_font)
        lines = _two_lines(item.title or f"Item {item.publishedfileid}", metrics, int(rect.width() - 16))
        line_y = rect.top() + 132
        for line in lines[:2]:
            painter.drawText(
                QRectF(rect.left() + 8, line_y, rect.width() - 16, 17),
                Qt.AlignLeft | Qt.AlignVCenter,
                line,
            )
            line_y += 16

        meta_font = QFont(option.font)
        meta_font.setPixelSize(10)
        painter.setFont(meta_font)
        meta_metrics = QFontMetrics(meta_font)
        meta_y = rect.top() + 166
        segments: list[tuple[str, str]] = []
        if item.file_size:
            segments.append((fmt_size(item.file_size), MUTED))
        segments.append((f"{fmt_count(item.subscriptions)} subs", MUTED))
        if item.star_rating:
            segments.append((f"★ {item.star_rating:.1f}", AMBER))
        else:
            segments.append(("No rating", MUTED))
        x = rect.left() + 8
        for text, colour in segments:
            painter.setPen(QColor(colour))
            painter.drawText(QRectF(x, meta_y, 100, 16), Qt.AlignLeft | Qt.AlignVCenter, text)
            x += meta_metrics.horizontalAdvance(text) + 7
            if x > rect.right() - 30:
                break
        if item.time_updated:
            updated = fmt_unix(item.time_updated)
            painter.setPen(QColor("#66717D"))
            painter.drawText(
                QRectF(rect.left() + 8, rect.bottom() - 23, rect.width() - 16, 15),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"Updated {updated}",
            )
            painter.setPen(QColor(MUTED))
            painter.drawText(
                QRectF(rect.left() + 8, rect.bottom() - 23, rect.width() - 16, 15),
                Qt.AlignRight | Qt.AlignVCenter,
                "Inspect ›",
            )

        tag_font = QFont(option.font)
        tag_font.setPixelSize(9)
        painter.setFont(tag_font)
        tag_metrics = QFontMetrics(tag_font)
        tx = rect.left() + 8
        ty = rect.top() + 189
        for tag in item.tags[:3]:
            label = tag[:18]
            width = tag_metrics.horizontalAdvance(label) + 12
            if tx + width > rect.right() - 8:
                break
            chip = QRectF(tx, ty, width, 19)
            painter.setPen(QPen(QColor("#2A3440"), 1))
            painter.setBrush(QColor("#1A222B"))
            painter.drawRoundedRect(chip, 4, 4)
            painter.setPen(QColor("#A9B4C0"))
            painter.drawText(chip, Qt.AlignCenter, label)
            tx += width + 4
        painter.restore()


class WorkshopView(QListView):
    """Icon-mode card view with extended selection and accessible labelling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setGridSize(QSize(GRID_W, GRID_H))
        self.setSpacing(0)
        self.setWordWrap(False)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setAccessibleName("Workshop items")
        self.setContextMenuPolicy(Qt.CustomContextMenu)


# ------------------------------------------------------------------- imports


class ImportTableModel(QAbstractTableModel):
    HEADERS = ["Include", "Mod", "Game ID", "Source", "Size"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resolution = None
        self._included: set[int] = set()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or self.resolution is None:
            return 0
        return len(self.resolution.items)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def flags(self, index):
        base = super().flags(index)
        if index.isValid() and index.column() == 0:
            return base | Qt.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self.resolution is None:
            return None
        row, col = index.row(), index.column()
        if row >= len(self.resolution.items):
            return None
        item = self.resolution.items[row]
        required = item.publishedfileid in self.resolution.dependencies
        if role == Qt.CheckStateRole and col == 0:
            return Qt.Checked if item.publishedfileid in self._included else Qt.Unchecked
        if role == ITEM_ROLE:
            return item
        if role == Qt.DisplayRole:
            values = (
                "",
                item.title or f"Item {item.publishedfileid}",
                str(item.appid) if item.appid else "Unknown",
                "Required" if required else "Import",
                fmt_size(item.file_size) or "Unknown",
            )
            return values[col]
        if role == Qt.TextAlignmentRole and col in (0, 2, 4):
            return int(Qt.AlignCenter)
        if role == Qt.ForegroundRole and col == 3 and required:
            return QColor(AMBER)
        if role == Qt.ToolTipRole:
            bits = [item.title or f"Item {item.publishedfileid}", f"Workshop ID {item.publishedfileid}"]
            if required:
                bits.append("Pulled in as a required item")
            return "\n".join(bits)
        if role == Qt.AccessibleTextRole:
            return (
                f"{item.title or item.publishedfileid}, game {item.appid or 'unknown'}, "
                f"{'required item' if required else 'imported item'}"
            )
        return None

    def setData(self, index, value, role=Qt.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or index.column() != 0 or role != Qt.CheckStateRole:
            return False
        item = self.resolution.items[index.row()]
        if Qt.CheckState(value) == Qt.Checked:
            self._included.add(item.publishedfileid)
        else:
            self._included.discard(item.publishedfileid)
        self.dataChanged.emit(index, index, [Qt.CheckStateRole])
        return True

    def set_resolution(self, resolution) -> None:
        self.beginResetModel()
        self.resolution = resolution
        self._included = {item.publishedfileid for item in resolution.items} if resolution else set()
        self.endResetModel()

    def selected_items(self) -> list[WorkshopItem]:
        if self.resolution is None:
            return []
        return [item for item in self.resolution.items if item.publishedfileid in self._included]

    def set_all(self, checked: bool) -> None:
        if self.resolution is None:
            return
        self._included = {item.publishedfileid for item in self.resolution.items} if checked else set()
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0), [Qt.CheckStateRole]
            )

    def included_count(self) -> int:
        return len(self._included)


# ----------------------------------------------------------------- downloads


class DownloadTableModel(QAbstractTableModel):
    HEADERS = ["Mod", "Game", "State", "Progress", "Detail"]
    ALL = "all"
    ACTIVE = "active"
    ATTENTION = "attention"
    FINISHED = "finished"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all: list[JobSnapshot] = []
        self._visible: list[JobSnapshot] = []
        self._filter = self.ALL

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._visible)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    @staticmethod
    def matches(job: JobSnapshot, key: str) -> bool:
        if key == DownloadTableModel.ACTIVE:
            return job.state in ACTIVE
        if key == DownloadTableModel.ATTENTION:
            return job.state in (JobState.FAILED, JobState.INTERRUPTED)
        if key == DownloadTableModel.FINISHED:
            return job.state in (JobState.DONE, JobState.CANCELLED)
        return True

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._visible):
            return None
        job = self._visible[index.row()]
        col = index.column()
        label, icon_name, colour = STATE_LOOK.get(job.state, ("Unknown", "info", MUTED))
        if role == JOB_ROLE:
            return job
        if role == JOB_ID_ROLE:
            return job.id
        if role == STATE_ROLE:
            return job.state.value
        if role == PROGRESS_ROLE:
            return job.progress
        if role == Qt.DisplayRole:
            if col == 0:
                return job.title
            if col == 1:
                return job.app_name or f"App {job.appid}"
            if col == 2:
                return label
            if col == 3:
                return ""
            if col == 4:
                message = (job.message or "").splitlines()
                return message[0][:240] if message else ""
        if role == Qt.DecorationRole and col == 2:
            return icon(icon_name, colour, 15)
        if role == Qt.ForegroundRole and col == 2:
            return QColor(colour)
        if role == Qt.TextAlignmentRole and col == 3:
            return int(Qt.AlignCenter)
        if role == Qt.ToolTipRole:
            bits = [job.title, f"Workshop ID {job.fileid}", f"Destination {job.dest}"]
            if job.message:
                bits.append(job.message)
            if job.error_kind:
                bits.append(f"Error type: {job.error_kind}")
            return "\n".join(bits)
        if role == Qt.AccessibleTextRole:
            return (
                f"{job.title}, game {job.app_name or job.appid}, {label}, "
                f"{int(job.progress)} percent, {job.message or 'no detail'}"
            )
        return None

    def set_jobs(self, jobs: list[JobSnapshot]) -> None:
        self._all = list(jobs)
        self._rebuild(reset=True)

    def update_job(self, job: JobSnapshot) -> None:
        """Update one job without resetting the view during progress ticks."""
        found = False
        for index, existing in enumerate(self._all):
            if existing.id == job.id:
                self._all[index] = job
                found = True
                break
        if not found:
            self._all.append(job)
        row = self.row_for_id(job.id)
        if self.matches(job, self._filter):
            if row >= 0:
                self._visible[row] = job
                self.dataChanged.emit(
                    self.index(row, 0), self.index(row, self.columnCount() - 1)
                )
            else:
                self._rebuild(reset=True)
        elif row >= 0:
            self._rebuild(reset=True)

    def set_filter(self, key: str) -> None:
        if key == self._filter:
            return
        self._filter = key
        self._rebuild(reset=True)

    def _rebuild(self, *, reset: bool) -> None:
        visible = [job for job in self._all if self.matches(job, self._filter)]
        if reset:
            self.beginResetModel()
            self._visible = visible
            self.endResetModel()
        else:
            self._visible = visible
            if visible:
                self.dataChanged.emit(
                    self.index(0, 0), self.index(len(visible) - 1, self.columnCount() - 1)
                )

    def filter_key(self) -> str:
        return self._filter

    def counts(self) -> dict[str, int]:
        return {
            self.ALL: len(self._all),
            self.ACTIVE: sum(1 for j in self._all if j.state in ACTIVE),
            self.ATTENTION: sum(
                1 for j in self._all if j.state in (JobState.FAILED, JobState.INTERRUPTED)
            ),
            self.FINISHED: sum(
                1 for j in self._all if j.state in (JobState.DONE, JobState.CANCELLED)
            ),
            "failed": sum(1 for j in self._all if j.state is JobState.FAILED),
            "done": sum(1 for j in self._all if j.state is JobState.DONE),
            "queued": sum(1 for j in self._all if j.state is JobState.QUEUED),
            "interrupted": sum(1 for j in self._all if j.state is JobState.INTERRUPTED),
        }

    def job_at(self, row: int) -> JobSnapshot | None:
        return self._visible[row] if 0 <= row < len(self._visible) else None

    def row_for_id(self, job_id: str) -> int:
        return next((n for n, job in enumerate(self._visible) if job.id == job_id), -1)

    def jobs(self) -> list[JobSnapshot]:
        return list(self._all)


class ProgressDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index) -> None:
        if index.column() != 3:
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#1D3A4C"))
        job: JobSnapshot = index.data(JOB_ROLE)
        rect = QRectF(option.rect.adjusted(8, 0, -8, 0))
        bar = QRectF(rect.left(), rect.center().y() - 3, max(10.0, rect.width() - 48), 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#26313C"))
        painter.drawRoundedRect(bar, 3, 3)
        value = 0.0 if job is None else max(0.0, min(100.0, job.progress))
        if job is not None and job.state is JobState.RUNNING and value <= 0:
            fill = bar.adjusted(0, 0, -(bar.width() * 0.55), 0)
            colour = ACCENT
        else:
            fill = bar.adjusted(0, 0, -(bar.width() * (1 - value / 100)), 0)
            colour = GREEN if job is not None and job.state is JobState.DONE else ACCENT
        painter.setBrush(QColor(colour))
        painter.drawRoundedRect(fill, 3, 3)
        painter.setFont(option.font)
        painter.setPen(QColor(MUTED if job is None or job.state not in ACTIVE else TEXT))
        text = "—" if job is None or (job.state in ACTIVE and value <= 0) else f"{int(value)}%"
        painter.drawText(
            QRectF(bar.right() + 7, rect.top(), 42, rect.height()),
            Qt.AlignRight | Qt.AlignVCenter,
            text,
        )
        painter.restore()


# ------------------------------------------------------------------ surfaces


class StatePanel(QWidget):
    """A visible loading / empty / no-results / error / permission state."""

    ICONS = {
        "loading": ("clock", ACCENT),
        "empty": ("folder", MUTED),
        "no-results": ("search", MUTED),
        "error": ("alert", RED),
        "offline": ("alert", RED),
        "permission": ("shield", AMBER),
        "success": ("check", GREEN),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(8)
        layout.addStretch(1)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label)
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setProperty("role", "h2")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        self.body_label = QLabel()
        self.body_label.setAlignment(Qt.AlignCenter)
        self.body_label.setProperty("role", "muted")
        self.body_label.setWordWrap(True)
        self.body_label.setMaximumWidth(540)
        layout.addWidget(self.body_label, 0, Qt.AlignHCenter)
        self.actions = QWidget()
        self.action_layout = QHBoxLayout(self.actions)
        self.action_layout.setContentsMargins(0, 8, 0, 0)
        self.action_layout.setSpacing(8)
        self.action_layout.addStretch(1)
        layout.addWidget(self.actions, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        self.kind = "empty"

    def set_state(self, kind: str, title: str, body: str = "", actions=None) -> None:
        self.kind = kind
        icon_name, colour = self.ICONS.get(kind, ("info", MUTED))
        self.icon_label.setPixmap(icon(icon_name, colour, 34).pixmap(34, 34))
        self.title_label.setText(title)
        self.body_label.setText(body)
        self.body_label.setVisible(bool(body))
        fit_wrap(self.title_label, 540)
        fit_wrap(self.body_label, 540)
        while self.action_layout.count() > 1:
            item = self.action_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for label, role, callback in actions or []:
            button = QPushButton(label)
            if role:
                button.setProperty("role", role)
            button.clicked.connect(callback)
            self.action_layout.insertWidget(self.action_layout.count() - 1, button)
        self.setAccessibleName(f"{title}. {body}".strip())


class InlineNotice(QFrame):
    KINDS = {
        "info": ("info", ACCENT),
        "success": ("check", GREEN),
        "warning": ("alert", AMBER),
        "error": ("alert", RED),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setProperty("notice", "info")
        self._kind = "info"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 8, 7)
        layout.setSpacing(8)
        self.icon_label = QLabel()
        self.icon_label.setFixedWidth(16)
        layout.addWidget(self.icon_label, 0, Qt.AlignTop)
        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.text_label, 1)
        self.close_button = QToolButton()
        self.close_button.setIcon(icon("close", MUTED, 13))
        self.close_button.setProperty("role", "icon")
        self.close_button.setToolTip("Dismiss")
        self.close_button.setAccessibleName("Dismiss message")
        self.close_button.clicked.connect(self.dismiss)
        layout.addWidget(self.close_button, 0, Qt.AlignTop)
        self.action_button: QPushButton | None = None

    def show_message(
        self,
        kind: str,
        text: str,
        *,
        action_label: str | None = None,
        action=None,
    ) -> None:
        if self.action_button is not None:
            self.layout().removeWidget(self.action_button)
            self.action_button.deleteLater()
            self.action_button = None
        self._kind = kind
        self.setProperty("notice", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        icon_name, colour = self.KINDS.get(kind, ("info", ACCENT))
        self.icon_label.setPixmap(icon(icon_name, colour, 15).pixmap(15, 15))
        self.text_label.setText(text)
        self.setAccessibleName(text)
        if action_label and action is not None:
            self.action_button = QPushButton(action_label)
            self.action_button.setProperty("role", "link")
            self.action_button.clicked.connect(action)
            self.layout().insertWidget(self.layout().count() - 1, self.action_button)
        self.setVisible(True)

    def text(self) -> str:
        return self.text_label.text()

    def kind(self) -> str:
        return self._kind

    def dismiss(self) -> None:
        self.setVisible(False)
        self.text_label.clear()


class Sidebar(QWidget):
    navigate = Signal(str)

    ITEMS = (
        ("browse", "Browse", "games", "Ctrl+1"),
        ("imports", "Imports", "imports", "Ctrl+2"),
        ("downloads", "Downloads", "downloads", "Ctrl+3"),
    )
    LABELS = {key: label for key, label, _, _ in ITEMS} | {"settings": "Settings"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebarFrame")
        self._collapsed = False
        self._active = "browse"
        self.setFixedWidth(208)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 18, 12, 12)
        layout.setSpacing(6)
        self.setStyleSheet(f"QWidget#sidebarFrame {{ background:{RAIL}; border-right:1px solid {BORDER}; }}")

        self.brand_row = QWidget()
        brand_layout = QHBoxLayout(self.brand_row)
        brand_layout.setContentsMargins(6, 0, 4, 14)
        brand_layout.setSpacing(10)
        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(icon("downloads", ACCENT, 20).pixmap(20, 20))
        self.brand_icon.setFixedSize(30, 30)
        self.brand_icon.setAlignment(Qt.AlignCenter)
        self.brand_icon.setStyleSheet(
            f"border:1px solid {ACCENT}; border-radius:8px; background:transparent;"
        )
        brand_layout.addWidget(self.brand_icon)
        self.brand_text = QWidget()
        brand_text_layout = QVBoxLayout(self.brand_text)
        brand_text_layout.setContentsMargins(0, 0, 0, 0)
        brand_text_layout.setSpacing(0)
        self.brand_name = QLabel("OpenSteamWorkshop")
        self.brand_name.setObjectName("brandName")
        self.brand_sub = QLabel("TRANSFER DESK")
        self.brand_sub.setObjectName("brandSub")
        brand_text_layout.addWidget(self.brand_name)
        brand_text_layout.addWidget(self.brand_sub)
        brand_layout.addWidget(self.brand_text, 1)
        layout.addWidget(self.brand_row)

        self.caption = QLabel("WORKSPACES")
        self.caption.setObjectName("navCaption")
        layout.addWidget(self.caption)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for key, label, icon_name, shortcut in self.ITEMS:
            button = self._nav_button(key, label, icon_name, f"{label} ({shortcut})")
            self.buttons[key] = button
            self.group.addButton(button)
            layout.addWidget(button)

        layout.addStretch(1)
        rule = QFrame()
        rule.setObjectName("sidebarRule")
        rule.setFrameShape(QFrame.HLine)
        layout.addWidget(rule)
        self.settings_button = self._nav_button(
            "settings", "Settings", "settings", "Settings (Ctrl+4)"
        )
        self.group.addButton(self.settings_button)
        layout.addWidget(self.settings_button)
        self.version = QLabel("v0.1.0 · Linux")
        self.version.setObjectName("railVersion")
        layout.addWidget(self.version)
        self.set_active("browse")

    def _nav_button(self, key: str, label: str, icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton(label)
        button.setProperty("nav", True)
        button.setCheckable(True)
        button.setIcon(icon(icon_name, MUTED, 18))
        button.setIconSize(QSize(18, 18))
        button.setMinimumHeight(40)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tooltip)
        button.setAccessibleName(label)
        button.setAccessibleDescription(tooltip)
        button.clicked.connect(lambda checked=False, k=key: self.navigate.emit(k))
        return button

    def set_active(self, key: str) -> None:
        self._active = key
        for name, button in self.buttons.items():
            button.setChecked(name == key)
            icon_name = next(i[2] for i in self.ITEMS if i[0] == name)
            button.setIcon(icon(icon_name, ACCENT if name == key else MUTED, 18))
        self.settings_button.setChecked(key == "settings")
        self.settings_button.setIcon(icon("settings", ACCENT if key == "settings" else MUTED, 18))

    def active(self) -> str:
        return self._active

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.setFixedWidth(64 if collapsed else 208)
        self.brand_text.setVisible(not collapsed)
        self.caption.setVisible(not collapsed)
        self.version.setVisible(not collapsed)
        for button in [*self.buttons.values(), self.settings_button]:
            key = self._button_key(button)
            button.setText("" if collapsed else self.LABELS.get(key, ""))
            button.setProperty("collapsed", collapsed)
            button.setToolTip(button.accessibleDescription())
            button.setFixedWidth(40 if collapsed else 184)
            button.style().unpolish(button)
            button.style().polish(button)
        self.brand_row.setFixedHeight(46 if collapsed else 46)

    def _button_key(self, button: QPushButton) -> str:
        for key, candidate in {**self.buttons, "settings": self.settings_button}.items():
            if candidate is button:
                return key
        return ""


class StatusStrip(QFrame):
    """A compact, jobs-only status surface; activating it opens Downloads."""

    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusStrip")
        self.setFixedHeight(52)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Download status: idle")
        self.queued_count = 0
        self.failure_count = 0
        self.attention_count = 0
        self.completed_count = 0
        self.running_title = ""
        self.progress_value = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 20, 0)
        layout.setSpacing(14)
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(22, 22)
        self.status_icon.setAlignment(Qt.AlignCenter)
        self.status_icon.setStyleSheet(
            f"background:{ACCENT_DIM}; border-radius:11px; border:none;"
        )
        self.status_icon.setPixmap(icon("downloads", ACCENT, 13).pixmap(13, 13))
        self.status_icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.status_icon)
        self.title = QLabel("Downloads idle")
        self.title.setObjectName("statusTitle")
        self.title.setMinimumWidth(180)
        self.title.setMaximumWidth(420)
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.title)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(170)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.progress.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.progress)
        self.pct = QLabel("")
        self.pct.setObjectName("statusMeta")
        self.pct.setFixedWidth(34)
        self.pct.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.pct)
        self.queue_label = QLabel("")
        self.queue_label.setObjectName("statusQueue")
        self.queue_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.queue_label)
        self.failure_label = QLabel("")
        self.failure_label.setObjectName("statusFail")
        self.failure_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.failure_label)
        self.attention_label = QLabel("")
        self.attention_label.setObjectName("statusMeta")
        self.attention_label.setStyleSheet(f"color:{AMBER};")
        self.attention_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.attention_label)
        layout.addStretch(1)
        self.open_label = QLabel("Open Downloads  ›")
        self.open_label.setObjectName("statusOpen")
        self.open_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.open_label)

    def update_from_jobs(self, jobs: list[JobSnapshot]) -> None:
        running = next(
            (j for j in jobs if j.state in (JobState.RUNNING, JobState.WAITING_FOR_AUTH)), None
        )
        self.queued_count = sum(1 for j in jobs if j.state is JobState.QUEUED)
        self.failure_count = sum(1 for j in jobs if j.state is JobState.FAILED)
        self.attention_count = sum(1 for j in jobs if j.state is JobState.INTERRUPTED)
        self.completed_count = sum(1 for j in jobs if j.state is JobState.DONE)
        self.running_title = running.title if running else ""
        self.progress_value = int(running.progress) if running else 0

        if running is not None:
            if running.state is JobState.WAITING_FOR_AUTH:
                text = f"<b>Waiting for Steam login</b> · {escape(running.title)}"
            else:
                text = f"<b>Downloading</b> · {escape(running.title)}"
            self.title.setText(text)
            self.progress.setVisible(True)
            if self.progress_value <= 0:
                self.progress.setRange(0, 0)
                self.pct.setText("")
            else:
                self.progress.setRange(0, 100)
                self.progress.setValue(self.progress_value)
                self.pct.setText(f"{self.progress_value}%")
        else:
            self.progress.setVisible(False)
            self.pct.setText("")
            if self.failure_count or self.attention_count:
                self.title.setText("<b>Downloads need attention</b> · review and retry")
            elif self.queued_count:
                noun = "job" if self.queued_count == 1 else "jobs"
                self.title.setText(f"<b>{self.queued_count} queued</b> · one SteamCMD {noun} at a time")
            elif self.completed_count:
                self.title.setText("<b>All downloads complete</b> · open Downloads for logs and folders")
            else:
                self.title.setText("<b>Downloads idle</b> · ready when you are")

        self.queue_label.setText(
            f"● {self.queued_count} queued" if self.queued_count else ""
        )
        self.failure_label.setText(
            f"● {self.failure_count} failed" if self.failure_count else ""
        )
        self.attention_label.setText(
            f"● {self.attention_count} need attention" if self.attention_count else ""
        )
        self.pct.setVisible(bool(running and self.progress_value > 0))
        summary = (
            f"Download status: {self.running_title or 'idle'}, "
            f"{self.queued_count} queued, {self.failure_count} failed, "
            f"{self.attention_count} need attention, {self.completed_count} complete"
        )
        self.setAccessibleName(summary)
        self.setToolTip(summary)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.activated.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class BulkActionBar(QFrame):
    reviewRequested = Signal(list)
    downloadRequested = Signal(list)
    clearRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("panel", "raised")
        self.setMinimumHeight(48)
        self._items: list[WorkshopItem] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 8, 5)
        layout.setSpacing(8)
        self.label = QLabel("0 selected")
        self.label.setProperty("role", "h3")
        layout.addWidget(self.label)
        self.hint = QLabel("Review together before queueing")
        self.hint.setProperty("role", "muted")
        layout.addWidget(self.hint)
        layout.addStretch(1)
        self.review_button = QPushButton("Review in Imports")
        self.review_button.setProperty("role", "primary")
        self.review_button.clicked.connect(self._review)
        layout.addWidget(self.review_button)
        self.download_button = QPushButton("Download now")
        self.download_button.clicked.connect(self._download)
        layout.addWidget(self.download_button)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setProperty("role", "ghost")
        self.clear_button.clicked.connect(self.clearRequested)
        layout.addWidget(self.clear_button)
        self.setVisible(False)

    def set_items(self, items: list[WorkshopItem]) -> None:
        self._items = list(items)
        self.label.setText(f"{len(items)} selected")
        self.setVisible(len(items) > 1)
        self.review_button.setEnabled(bool(items))
        self.download_button.setEnabled(bool(items))
        self.setAccessibleName(f"{len(items)} Workshop items selected")

    def items(self) -> list[WorkshopItem]:
        return list(self._items)

    def _review(self) -> None:
        if self._items:
            self.reviewRequested.emit([i.publishedfileid for i in self._items])

    def _download(self) -> None:
        if self._items:
            self.downloadRequested.emit(self._items)


class SideInspector(QFrame):
    downloadRequested = Signal(object)
    importRequested = Signal(object, bool)
    openRequested = Signal(str)
    copyRequested = Signal(str)
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("panel", "true")
        self.item: WorkshopItem | None = None
        self.details: ItemDetails | None = None
        self._required = False
        self.setMinimumWidth(300)
        self.setMaximumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(13, 0, 7, 0)
        header_layout.setSpacing(6)
        caption = QLabel("INSPECTOR")
        caption.setProperty("role", "caption")
        header_layout.addWidget(caption)
        header_layout.addStretch(1)
        close = QToolButton()
        close.setIcon(icon("close", MUTED, 15))
        close.setProperty("role", "icon")
        close.setToolTip("Close inspector (Esc)")
        close.setAccessibleName("Close inspector")
        close.clicked.connect(self.closeRequested)
        header_layout.addWidget(close)
        header.setFixedHeight(40)
        layout.addWidget(header)
        rule = QFrame()
        rule.setProperty("rule", True)
        layout.addWidget(rule)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(14, 12, 14, 12)
        self.body_layout.setSpacing(8)
        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.title_label.setProperty("role", "h2")
        self.body_layout.addWidget(self.title_label)
        self.byline = QLabel()
        self.byline.setWordWrap(True)
        self.byline.setProperty("role", "muted")
        self.body_layout.addWidget(self.byline)
        self.id_label = QLabel()
        self.id_label.setFont(mono_font())
        self.id_label.setProperty("role", "muted")
        self.body_layout.addWidget(self.id_label)
        self.loading = QLabel("Loading details…")
        self.loading.setProperty("role", "accent")
        self.loading.setWordWrap(True)
        self.body_layout.addWidget(self.loading)
        self.stats = QLabel()
        self.stats.setTextFormat(Qt.RichText)
        self.stats.setWordWrap(True)
        self.body_layout.addWidget(self.stats)
        self.tags = QLabel()
        self.tags.setWordWrap(True)
        self.tags.setProperty("role", "accent")
        self.body_layout.addWidget(self.tags)
        self.about_caption = QLabel("ABOUT")
        self.about_caption.setProperty("role", "caption")
        self.body_layout.addWidget(self.about_caption)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.description.setStyleSheet("color:#C7D0D8; font-size:12px;")
        self.body_layout.addWidget(self.description)
        self.required_caption = QLabel("REQUIRED ITEMS")
        self.required_caption.setProperty("role", "caption")
        self.body_layout.addWidget(self.required_caption)
        self.required_box = QVBoxLayout()
        self.required_box.setSpacing(4)
        self.body_layout.addLayout(self.required_box)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setProperty("role", "bad")
        self.body_layout.addWidget(self.error_label)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(body)
        layout.addWidget(self.scroll, 1)
        rule2 = QFrame()
        rule2.setProperty("rule", True)
        layout.addWidget(rule2)

        self.actions = QWidget()
        action_layout = QVBoxLayout(self.actions)
        action_layout.setContentsMargins(11, 10, 11, 11)
        action_layout.setSpacing(7)
        self.download_button = QPushButton("Download mod")
        self.download_button.setProperty("role", "primary")
        self.download_button.setIcon(icon("downloads", ACCENT_INK, 15))
        self.download_button.clicked.connect(self._download)
        action_layout.addWidget(self.download_button)
        row = QHBoxLayout()
        row.setSpacing(7)
        self.import_button = QPushButton("Review import")
        self.import_button.clicked.connect(self._import)
        row.addWidget(self.import_button, 1)
        self.open_button = QPushButton("Open ↗")
        self.open_button.setProperty("role", "ghost")
        self.open_button.clicked.connect(self._open)
        row.addWidget(self.open_button)
        action_layout.addLayout(row)
        layout.addWidget(self.actions)
        self.setVisible(False)

    @property
    def fileid(self) -> int | None:
        return self.item.publishedfileid if self.item else None

    def show_item(self, item: WorkshopItem, *, loading: bool = True) -> None:
        self.item = item
        self.details = None
        self._required = bool(item.children)
        self.setVisible(True)
        self.title_label.setText(item.title or f"Item {item.publishedfileid}")
        self.byline.setText(
            f"by {escape(item.author)}" if item.author else "Workshop item"
        )
        self.id_label.setText(f"Workshop ID {item.publishedfileid}")
        size = fmt_size(item.file_size) or "Unknown"
        rating = f"★ {item.star_rating:.1f}" if item.star_rating else "No rating"
        self.stats.setText(
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td><span style="color:{MUTED};font-size:10px">SIZE</span><br>{escape(size)}</td>'
            f'<td><span style="color:{MUTED};font-size:10px">SUBSCRIBERS</span><br>'
            f"{fmt_count(item.subscriptions)}</td></tr><tr>"
            f'<td><span style="color:{MUTED};font-size:10px">RATING</span><br>'
            f'<span style="color:{AMBER}">{rating}</span></td>'
            f'<td><span style="color:{MUTED};font-size:10px">APP ID</span><br>'
            f"{item.appid or 'Unknown'}</td></tr></table>"
        )
        self.tags.setText(" · ".join(item.tags[:8]))
        self.tags.setVisible(bool(item.tags))
        self.description.setText(item.short_description or "Loading description…")
        self._fit_wrapped()
        self._clear_required()
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.loading.setVisible(loading)
        self._configure_actions()
        if loading:
            self.download_button.setEnabled(False)
            self.import_button.setEnabled(True)

    def show_details(self, details: ItemDetails) -> bool:
        if self.item is None or details.fileid != self.item.publishedfileid:
            return False
        self.details = details
        self.loading.setVisible(False)
        self._required = bool(details.required_items)
        self.title_label.setText(details.title or self.item.title)
        if details.author:
            self.byline.setText(f"by {escape(details.author)}")
        size = str(details.file_size or fmt_size(self.item.file_size) or "Unknown")
        ratings = f" ({fmt_count(details.num_ratings)})" if details.num_ratings else ""
        rating = (
            f"★ {self.item.star_rating:.1f}{ratings}" if self.item.star_rating else "No rating"
        )
        self.stats.setText(
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td><span style="color:{MUTED};font-size:10px">SIZE</span><br>{escape(size)}</td>'
            f'<td><span style="color:{MUTED};font-size:10px">RATING</span><br>'
            f'<span style="color:{AMBER}">{rating}</span></td></tr><tr>'
            f'<td><span style="color:{MUTED};font-size:10px">POSTED</span><br>'
            f"{escape(details.posted or 'Unknown')}</td>"
            f'<td><span style="color:{MUTED};font-size:10px">APP ID</span><br>'
            f"{details.appid or self.item.appid or 'Unknown'}</td></tr></table>"
        )
        tags = details.tags or self.item.tags
        self.tags.setText(" · ".join(tags[:8]))
        self.tags.setVisible(bool(tags))
        self.description.setText((details.description or "No description provided.")[:2400])
        self._fit_wrapped()
        self._clear_required()
        for fileid, title in details.required_items[:12]:
            label = QLabel(
                f'<span style="font-family:monospace;color:{MUTED}">{fileid}</span> '
                f"{escape(title or 'Required item')}"
            )
            label.setTextFormat(Qt.RichText)
            label.setWordWrap(True)
            self.required_box.addWidget(label)
        self.required_caption.setVisible(bool(details.required_items))
        if details.error:
            self.error_label.setText(details.error)
            self.error_label.setVisible(True)
        else:
            self.error_label.setVisible(False)
        self._configure_actions()
        usable = not details.error and bool(details.appid or self.item.appid)
        self.download_button.setEnabled(usable and details.file_type != 2)
        self.import_button.setEnabled(True)
        return True

    def show_error(self, message: str) -> None:
        self.loading.setVisible(False)
        self.error_label.setText(message)
        self.error_label.setVisible(True)
        self._fit_wrapped()
        if self.item is not None:
            self.download_button.setEnabled(False)
            self.import_button.setEnabled(True)
        self.setVisible(True)

    def _fit_wrapped(self) -> None:
        """Reserve real wrapped height for the inspector's text block."""
        if not hasattr(self, "description"):
            return
        width = max(160, self.scroll.viewport().width() - 28)
        for label in (
            self.title_label,
            self.byline,
            self.tags,
            self.description,
            self.error_label,
        ):
            if not label.wordWrap():
                continue
            label.setMinimumHeight(0)
            if label.text():
                label.setMinimumHeight(
                    max(label.fontMetrics().lineSpacing(), label.heightForWidth(width))
                )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_wrapped()

    def clear(self) -> None:
        self.item = None
        self.details = None
        self.setVisible(False)

    def _configure_actions(self) -> None:
        if self.item is None:
            return
        if self.item.file_type == 2 or (self.details and self.details.file_type == 2):
            self.download_button.setText("Review collection in Imports")
            self.download_button.setIcon(icon("imports", ACCENT_INK, 15))
        else:
            self.download_button.setText("Download mod")
            self.download_button.setIcon(icon("downloads", ACCENT_INK, 15))
        self.import_button.setText(
            "Review dependencies" if self._required else "Review import"
        )
        self.open_button.setToolTip("Open this Workshop page in your browser")
        self.setAccessibleName(
            f"Inspector: {self.title_label.text()}" if self.item else "Item inspector"
        )

    def _clear_required(self) -> None:
        while self.required_box.count():
            item = self.required_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.required_caption.setVisible(False)

    def _download(self) -> None:
        if self.item is not None:
            self.downloadRequested.emit(self.item)

    def _import(self) -> None:
        if self.item is not None:
            self.importRequested.emit(self.item, self._required)

    def _open(self) -> None:
        if self.item is not None:
            self.openRequested.emit(self.item.url)


def make_icon_button(
    name: str,
    tooltip: str,
    callback,
    *,
    parent=None,
    size: int = 32,
    color: str = MUTED,
    icon_size: int = 15,
) -> QToolButton:
    button = QToolButton(parent)
    button.setIcon(icon(name, color, icon_size))
    button.setIconSize(QSize(icon_size, icon_size))
    button.setProperty("role", "icon")
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setFixedSize(size, size)
    button.setCursor(Qt.PointingHandCursor)
    button.clicked.connect(callback)
    return button


def table_view(model) -> QTableView:
    view = QTableView()
    view.setModel(model)
    view.setSelectionBehavior(QAbstractItemView.SelectRows)
    view.setSelectionMode(QAbstractItemView.SingleSelection)
    view.setEditTriggers(QAbstractItemView.NoEditTriggers)
    view.setAlternatingRowColors(True)
    view.setShowGrid(False)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(36)
    view.horizontalHeader().setHighlightSections(False)
    view.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    view.horizontalHeader().setStretchLastSection(True)
    view.setWordWrap(False)
    return view


def configure_import_columns(view: QTableView) -> None:
    header = view.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.Fixed)
    header.setSectionResizeMode(1, QHeaderView.Stretch)
    header.setSectionResizeMode(2, QHeaderView.Fixed)
    header.setSectionResizeMode(3, QHeaderView.Fixed)
    header.setSectionResizeMode(4, QHeaderView.Fixed)
    view.setColumnWidth(0, 72)
    view.setColumnWidth(2, 84)
    view.setColumnWidth(3, 92)
    view.setColumnWidth(4, 92)


def configure_download_columns(view: QTableView) -> None:
    header = view.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.Stretch)
    header.setSectionResizeMode(1, QHeaderView.Fixed)
    header.setSectionResizeMode(2, QHeaderView.Fixed)
    header.setSectionResizeMode(3, QHeaderView.Fixed)
    header.setSectionResizeMode(4, QHeaderView.Stretch)
    view.setColumnWidth(1, 160)
    view.setColumnWidth(2, 150)
    view.setColumnWidth(3, 140)


def size_policy_expanding() -> QSizePolicy:
    return QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)


__all__ = [
    "ACCENT",
    "BG",
    "BORDER",
    "BulkActionBar",
    "CARD_H",
    "CARD_W",
    "DownloadTableModel",
    "GAME_ROLE",
    "GRID_H",
    "GRID_W",
    "GameDelegate",
    "GameListModel",
    "ImportTableModel",
    "InlineNotice",
    "ITEM_ROLE",
    "JOB_ROLE",
    "ProgressDelegate",
    "SideInspector",
    "Sidebar",
    "StatePanel",
    "StatusStrip",
    "WorkshopCardDelegate",
    "WorkshopListModel",
    "WorkshopView",
    "configure_download_columns",
    "configure_import_columns",
    "make_icon_button",
    "table_view",
]
