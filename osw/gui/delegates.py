"""Delegates: Workshop cards, game results, and clickable download rows."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .item_models import (
    FavoriteRole,
    GameRole,
    JobState,
    MetaRole,
    RatingRole,
    SnapshotRole,
    TagListRole,
    ThumbRole,
    _state_label,
    actions_for,
)

ACCENT = "#46B4E6"
CARD_W, CARD_H = 192, 258
GAME_W, GAME_H = 300, 64
GAP = 6
BUTTON_PAD_X = 11
BUTTON_H = 25
BUTTON_GAP = 6


def _card_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _fill_round(painter: QPainter, rect: QRectF, color: str, radius: float) -> None:
    painter.fillPath(_card_path(rect, radius), QColor(color))


class ItemCardDelegate(QStyledItemDelegate):
    """Workshop card: cover art, two-line title, mono meta, rating, tag chips."""

    def sizeHint(self, option, index):
        return QSize(CARD_W, CARD_H)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        _fill_round(painter, rect, "#171C22", 9.0)
        if selected:
            painter.setPen(QColor(ACCENT))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(_card_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), 9.0))

        body = rect.adjusted(10, 0, -10, -9)
        thumb_h = 118.0
        thumb = QRectF(rect.x(), rect.y(), rect.width(), thumb_h)
        img = index.data(ThumbRole)

        painter.save()
        painter.setClipPath(_card_path(thumb.adjusted(1, 1, -1, -1), 8.2))
        if img is not None and not img.isNull():
            scaled = img.scaled(
                int(thumb.width()), int(thumb.height()),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawImage(
                QRectF(
                    thumb.center().x() - scaled.width() / 2,
                    thumb.center().y() - scaled.height() / 2,
                    scaled.width(), scaled.height(),
                ),
                scaled,
            )
        else:
            painter.fillRect(thumb, QColor("#141A20"))

        # template frame so card geometry never depends on art
        painter.setPen(QColor("#232B34"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(thumb.adjusted(1, 1, -2, -2), 8.2, 8.2)
        painter.restore()

        title_rect = QRectF(body.x(), thumb.bottom() + 8, body.width(), 30)
        painter.setPen(QColor("#F3F6F8"))
        painter.drawText(title_rect, Qt.TextFlag.TextWordWrap, index.data() or "", )

        meta_y = title_rect.bottom() + 4
        font = QFont()
        font.setPointSizeF(8.2)
        painter.setFont(font)
        rating = index.data(RatingRole)
        meta = index.data(MetaRole) or ""
        painter.setPen(QColor("#98A3AF"))
        if rating:
            painter.drawText(
                QRectF(body.x(), meta_y, body.width() - 42, 14), Qt.AlignmentFlag.AlignLeft, meta
            )
            painter.setPen(QColor("#4EC98A"))
            painter.drawText(
                QRectF(body.right() - 42, meta_y, 42, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"★ {rating}",
            )
        else:
            painter.drawText(QRectF(body.x(), meta_y, body.width(), 14), Qt.AlignmentFlag.AlignLeft, meta)

        tags = index.data(TagListRole) or []
        if tags:
            font.setPointSizeF(8.0)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            cursor = body.x()
            for label in tags[:2]:
                w = metrics.horizontalAdvance(label) + 10
                if cursor + w > body.right() + 0.5:
                    break
                chip = QRectF(cursor, body.bottom() - 18, w, 15)
                painter.fillPath(_card_path(chip, 4.0), QColor("#232B34"))
                painter.setPen(QColor("#98A3AF"))
                painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, label)
                cursor += w + GAP
        painter.restore()

    def helpEvent(self, *args) -> bool:  # detail level comes from the inspector, not tooltips
        return False


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
            _fill_round(painter, rect.adjusted(2, 1, -2, -1), "#1F2630", 8.0)
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
        font = QFont()
        font.setPointSizeF(9.8)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#F3F6F8"))
        painter.drawText(
            QRectF(text_x, rect.y() + 10, text_right - text_x, 20),
            Qt.TextFlag.TextSingleLine,
            QFontMetrics(font).elidedText(index.data() or "", Qt.TextElideMode.ElideRight, int(text_right - text_x)),
        )
        font.setPointSizeF(8.4)
        painter.setFont(font)
        painter.setPen(QColor("#98A3AF"))
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
        JobState.QUEUED: "#98A3AF",
        JobState.RUNNING: ACCENT,
        JobState.WAITING_FOR_AUTH: "#E8B84D",
        JobState.DONE: "#4EC98A",
        JobState.FAILED: "#E5605C",
        JobState.CANCELLED: "#98A3AF",
        JobState.INTERRUPTED: "#E8B84D",
    }

    def sizeHint(self, option, index):
        return QSize(option.rect.width() or 700, 62)

    @staticmethod
    def _chip_color(snap) -> str:
        return JobRowDelegate.STATE_COLORS.get(snap.state, "#98A3AF")

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        snap = index.data(SnapshotRole)
        if snap is None:
            return
        painter.save()
        rect = QRectF(option.rect)

        live_job = snap.state is JobState.RUNNING
        if live_job:
            painter.fillRect(rect, QColor("rgba(70, 180, 230, 16)"))
        # state dot
        dot = QColor(self._chip_color(snap))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot)
        painter.drawEllipse(QRectF(rect.x() + 12, rect.y() + 13, 7, 7))

        # job cell
        font = QFont()
        font.setPointSizeF(9.6)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#F3F6F8"))
        job_x = rect.x() + 28
        title_w = 230
        title_font = QFontMetrics(font)
        painter.drawText(
            QRect(job_x, rect.y() + 9, title_w, 18), Qt.TextFlag.TextSingleLine,
            title_font.elidedText(snap.title, Qt.TextElideMode.ElideRight, title_w),
        )
        font.setPointSizeF(8.3)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor("#7C8794"))
        painter.drawText(
            QRect(job_x, rect.y() + 29, title_w + 70, 14), Qt.TextFlag.TextSingleLine,
            f"{snap.app_name or '—'} · {snap.fileid}",
        )

        # status chip + progress bar
        chip_x = job_x + title_w + 80
        chip_rect = QRectF(chip_x, rect.y() + 10, 140, 20)
        label = _state_label(snap.state, snap.progress, snap.output_path)
        font.setPointSizeF(8.4)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(dot)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(chip_rect, 5, 5)
        painter.drawText(chip_rect.adjusted(9, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, label)

        if live_job or (snap.state is JobState.QUEUED and False):
            bar_rect = QRectF(chip_x, rect.y() + 36, 140, 5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillPath(_card_path(bar_rect, 2.0), QColor("#1F2630"))
            fill = max(1, int(bar_rect.width() * max(0.02, min(1.0, snap.progress / 100))))
            painter.fillPath(_card_path(QRectF(bar_rect.x(), bar_rect.y(), fill, 5), 2.0), dot)

        # actions
        acts = actions_for(snap)
        if acts:
            font.setPointSizeF(8.6)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            cur_x = rect.right() - 8
            for label in reversed(acts):
                w = metrics.horizontalAdvance(label) + BUTTON_PAD_X * 2
                btn = QRectF(
                    cur_x - w, rect.y() + (rect.height() - BUTTON_H) / 2, w, BUTTON_H
                )
                fg = "#F3F6F8"
                if label == "Cancel":
                    fg = "#E5605C"
                if label in ("Retry", "Resume", "Retry with account"):
                    fg = ACCENT
                painter.fillPath(_card_path(btn, 6.0), QColor("#1F2630"))
                painter.setPen(QColor(fg))
                painter.drawText(btn, Qt.AlignmentFlag.AlignCenter, label)
                cur_x -= w + BUTTON_GAP
        painter.restore()

    def action_rects(self, rect: QRect, index: QModelIndex):
        """(label, QRect) pairs in left-to-right paint order — used for clicks and tests."""
        snap = index.data(SnapshotRole)
        if snap is None:
            return []
        acts = actions_for(snap)
        if not acts:
            return []
        font = QFont()
        font.setPointSizeF(8.6)
        metrics = QFontMetrics(font)
        rects = []
        cur_x = rect.right() - 8
        for label in reversed(acts):
            w = metrics.horizontalAdvance(label) + BUTTON_PAD_X * 2
            rects.append(
                (label, QRect(cur_x - w, rect.y() + (rect.height() - BUTTON_H) // 2, w, BUTTON_H))
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
