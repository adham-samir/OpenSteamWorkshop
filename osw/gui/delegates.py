"""Delegates: Workshop cards, game results, and clickable download rows."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from . import icons, theme
from .item_models import (
    FavoriteRole,
    GameRole,
    JobState,
    MetaRole,
    SnapshotRole,
    ThumbRole,
    _state_label,
    actions_for,
)

ACCENT = theme.ACCENT
CARD_W, CARD_H = 244, 238
GAME_W, GAME_H = 300, 64
GAP = 6
BUTTON_PAD_X = 11
BUTTON_H = 30
BUTTON_GAP = 6


def _card_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _fill_round(painter: QPainter, rect: QRectF, color: str, radius: float) -> None:
    painter.fillPath(_card_path(rect, radius), QColor(color))


def _art(painter, rect, image, label="No preview"):
    painter.save()
    painter.setClipPath(_card_path(rect, 8))
    painter.fillRect(rect, QColor(theme.RAISED))
    if image is not None and not image.isNull():
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        ratio = max(rect.width()/image.width(), rect.height()/image.height())
        sw, sh = rect.width()/ratio, rect.height()/ratio
        source = QRectF((image.width()-sw)/2, (image.height()-sh)/2, sw, sh)
        painter.drawImage(rect, image, source)
    else:
        icons.paint(painter, QRectF(rect.center().x()-12, rect.center().y()-24, 24, 24),
                    "browse", theme.TEXT2)
        painter.setPen(QColor(theme.TEXT2))
        painter.drawText(rect.adjusted(4, 26, -4, -4), Qt.AlignmentFlag.AlignCenter, label)
    painter.restore()


def _text(painter, rect, text, *, size=10, bold=False, color=None):
    font = QFont(QApplication.font())
    font.setPointSizeF(size)
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    painter.setFont(font)
    painter.setPen(QColor(color or theme.TEXT))
    painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
                     QFontMetrics(font).elidedText(str(text), Qt.TextElideMode.ElideRight,
                                                  max(0, int(rect.width()))))


class ItemCardDelegate(QStyledItemDelegate):
    """Landscape artwork with a readable title and concise metadata."""
    def sizeHint(self, option, index):
        view = self.parent()
        width = view.viewport().width() if view else CARD_W
        columns = max(1, (width - 12) // (CARD_W + 16))
        cell = max(210, (width - 16 * (columns + 1)) // columns)
        return QSize(cell, int(cell * .56) + 102)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(1, 1, -1, -1)
        _fill_round(painter, r, theme.SURFACE, 10)
        image_rect = QRectF(r.x(), r.y(), r.width(), r.width() * .56)
        _art(painter, image_rect, index.data(ThumbRole))
        body = QRectF(r.x()+12, image_rect.bottom()+10, r.width()-24, 22)
        # Two deliberate lines, with the second elided for long titles.
        title = index.data() or "Untitled Workshop item"
        font = QFont(QApplication.font())
        font.setPointSizeF(10.5)
        font.setWeight(QFont.Weight.DemiBold)
        fm = QFontMetrics(font)
        words = title.split()
        line = ""
        while words and fm.horizontalAdvance((line + " " + words[0]).strip()) <= body.width():
            line = (line + " " + words.pop(0)).strip()
        if not line and words:
            line = words.pop(0)
        _text(painter, body, line, size=10.5, bold=True)
        _text(painter, body.translated(0, 21), " ".join(words), size=10.5, bold=True)
        _text(painter, QRectF(body.x(), r.bottom()-31, body.width(), 20),
              index.data(MetaRole) or "Workshop content", size=9, color=theme.TEXT2)
        if option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(theme.ACCENT))
            painter.drawRoundedRect(r, 10, 10)
        painter.restore()


class ItemListDelegate(QStyledItemDelegate):
    """The same item model and selection, presented as compact rows."""
    def sizeHint(self, option, index):
        return QSize(220, 82)

    def paint(self, painter, option, index):
        painter.save()
        r = QRectF(option.rect).adjusted(1, 2, -1, -2)
        selected = option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus)
        _fill_round(painter, r, theme.ACCENT_DIM if selected else theme.SURFACE, 8)
        _art(painter, QRectF(r.x()+8, r.y()+8, 98, r.height()-16), index.data(ThumbRole), "Preview")
        _text(painter, QRectF(r.x()+120, r.y()+12, r.width()-134, 26), index.data() or "", bold=True)
        _text(painter, QRectF(r.x()+120, r.y()+40, r.width()-134, 22),
              index.data(MetaRole) or "", size=9, color=theme.TEXT2)
        if selected:
            painter.setPen(QColor(theme.ACCENT))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(r, 8, 8)
        painter.restore()


class GameCardDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(232, 164)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(1, 1, -1, -1)
        _fill_round(painter, r, theme.SURFACE, 9)
        _art(painter, QRectF(r.x(), r.y(), r.width(), 115), index.data(ThumbRole), "Game artwork")
        _text(painter, QRectF(r.x()+12, r.y()+122, r.width()-24, 28), index.data() or "", bold=True)
        if option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus):
            painter.setPen(QColor(theme.ACCENT))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(r, 9, 9)
        painter.restore()


class GameResultDelegate(QStyledItemDelegate):
    """Focused game-results row: capsule image left, name + app id right."""

    def sizeHint(self, option, index):
        return QSize(GAME_W, GAME_H + 10)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        rect = QRectF(option.rect)
        state = option.state & (
            QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected
        )
        if state:
            _fill_round(painter, rect.adjusted(2, 1, -2, -1), theme.RAISED, 8.0)
        img = index.data(ThumbRole)
        cap = QRectF(rect.x() + 6, rect.y() + 5, 128, GAME_H - 10)
        scaled = None
        if img is not None and not img.isNull():
            scaled = img.scaled(
                int(cap.width()), int(cap.height()),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        if scaled is not None:
            painter.save()
            painter.setClipRect(cap)
            painter.drawImage(
                QRectF(
                    cap.center().x() - scaled.width() / 2,
                    cap.center().y() - scaled.height() / 2,
                    scaled.width(), scaled.height(),
                ),
                scaled,
            )
            painter.restore()
        else:
            painter.fillRect(cap.adjusted(0.5, 0.5, -0.5, -0.5), QColor("#1B222A"))

        text_x = cap.right() + 12
        favorite = bool(index.data(FavoriteRole))
        text_right = rect.right() - (28 if favorite else 0)
        font = QFont(QApplication.font())
        font.setPointSizeF(9.8)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(
            QRectF(text_x, rect.y() + 10, text_right - text_x, 20),
            Qt.TextFlag.TextSingleLine,
            QFontMetrics(font).elidedText(index.data() or "", Qt.TextElideMode.ElideRight, int(text_right - text_x)),
        )
        font.setPointSizeF(8.4)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT2))
        game = index.data(GameRole)
        painter.drawText(
            QRectF(text_x, rect.y() + 31, text_right - text_x, 14),
            Qt.TextFlag.TextSingleLine,
            f"app {game.appid}" if game else "",
        )
        if favorite:
            painter.setPen(QColor("#E8B84D"))
            painter.drawText(
                QRectF(rect.right() - 26, rect.y() + 20, 18, 18),
                Qt.AlignmentFlag.AlignCenter,
                "★",
            )
        painter.restore()


class JobRowDelegate(QStyledItemDelegate):
    """Downloads row: state dot, title/id, status chip + bar, actions as buttons."""

    def __init__(self, on_action, parent=None):
        super().__init__(parent)
        self._on_action = on_action

    STATE_COLORS = {
        JobState.QUEUED: theme.TEXT2,
        JobState.RUNNING: ACCENT,
        JobState.WAITING_FOR_AUTH: "#E8B84D",
        JobState.DONE: "#4EC98A",
        JobState.FAILED: "#E5605C",
        JobState.CANCELLED: theme.TEXT2,
        JobState.INTERRUPTED: "#E8B84D",
    }

    def sizeHint(self, option, index):
        return QSize(option.rect.width() or 700, 62)

    @staticmethod
    def _chip_color(snap) -> str:
        return JobRowDelegate.STATE_COLORS.get(snap.state, theme.TEXT2)

    def paint(self, painter, option, index):
        snap = index.data(SnapshotRole)
        if snap is None:
            return
        painter.save()
        r = QRectF(option.rect)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(r, QColor(theme.ACCENT_DIM))
        color = self._chip_color(snap)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(r.x()+10, r.y()+16, 7, 7))
        _text(painter, QRectF(r.x()+28, r.y()+6, r.width()-210, 25), snap.title, bold=True)
        label = _state_label(snap.state, snap.progress, snap.output_path)
        _text(painter, QRectF(r.right()-170, r.y()+6, 160, 25), label, size=9, color=color)
        _text(painter, QRectF(r.x()+28, r.y()+31, r.width()-210, 21),
              f"{snap.app_name or f'App {snap.appid}'} · {snap.fileid}", size=9, color=theme.TEXT2)
        if snap.state is JobState.RUNNING:
            bar = QRectF(r.right()-170, r.y()+38, 150, 4)
            painter.fillRect(bar, QColor(theme.RAISED))
            painter.fillRect(QRectF(bar.x(), bar.y(), bar.width()*max(0.02, min(1, snap.progress/100)), 4), QColor(theme.ACCENT))
        rects = self.action_rects(option.rect, index)
        right = rects[0][1].left()-10 if rects else r.right()-10
        _text(painter, QRectF(r.x()+28, r.y()+59, max(0, right-r.x()-28), 24),
              snap.message or "", size=9, color=theme.TEXT2)
        for label, rect in rects:
            _fill_round(painter, QRectF(rect), theme.RAISED, 5)
            _text(painter, QRectF(rect).adjusted(8, 0, -5, 0), label, size=8.6,
                  color=theme.BAD if label == "Cancel" else theme.TEXT)
        painter.restore()

    def action_rects(self, rect: QRect, index: QModelIndex):
        """(label, QRect) pairs in left-to-right paint order — used for clicks and tests."""
        snap = index.data(SnapshotRole)
        if snap is None:
            return []
        acts = actions_for(snap)
        if not acts:
            return []
        font = QFont(QApplication.font())
        font.setPointSizeF(8.6)
        metrics = QFontMetrics(font)
        rects = []
        cur_x = rect.right() - 8
        for label in reversed(acts):
            w = metrics.horizontalAdvance(label) + BUTTON_PAD_X * 2
            rects.append(
                (label, QRect(cur_x - w, rect.bottom() - BUTTON_H - 6, w, BUTTON_H))
            )
            cur_x -= w + BUTTON_GAP
        rects.reverse()
        return rects

    def editorEvent(self, event, model, option, index):
        if event.type() not in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonPress):
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        snap = index.data(SnapshotRole)
        if snap is None:
            return False
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        for label, r in self.action_rects(option.rect, index):
            if r.contains(pos):
                self._on_action(snap.id, label)
                return True
        return True  # row absorbs mouse presses; only buttons act
