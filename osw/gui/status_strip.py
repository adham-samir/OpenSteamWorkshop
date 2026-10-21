"""Persistent status strip: one live transfer, queued count, failures. Opens Downloads."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QWidget

from ..queue import JobState
from . import theme


class SpinnerLabel(QWidget):
    """Small quarter-arc spinner; animated only while a transfer runs."""

    def __init__(self, color: str = theme.ACCENT, size: int = 13):
        super().__init__()
        self._angle = 90.0
        self._color = color
        self._size = size
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_running(self, running: bool) -> None:
        if running and not self._timer.isActive():
            self._timer.start(66)
        elif not running:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._angle = (self._angle - 24) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        theme.draw_spinner(p, QRectF(0, 0, self.width(), self.height()), QColor(self._color), 2.0, self._angle)
        p.end()


class CountChip(QFrame):
    """'N queued' / 'N failed' chip; clicks routed to the Downloads page."""

    activated = Signal()

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self._count = 0
        self._visible_count = False
        self.setObjectName(f"{kind}Chip")
        cursor = Qt.CursorShape.PointingHandCursor
        self.setCursor(cursor)
        self.setToolTip("Open the Downloads workspace")
        self.value = QLabel("0", self)
        self.value.setObjectName("chipValue")
        self.label = QLabel("queued", self)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 2, 9, 2)
        lay.setSpacing(5)
        lay.addWidget(self.value)
        lay.addWidget(self.label)
        self.set_count(0, "")

    def set_count(self, count: int, label: str) -> None:
        self._count = count
        self.value.setText(str(count))
        self.label.setText(label)
        self.setVisible(count > 0)
        color = theme.WARN if self.kind == "warn" else theme.BAD
        self.value.setStyleSheet(f"color: {color}; font-weight: 600; background: transparent;")
        self.label.setStyleSheet(f"color: {color}; background: transparent;")
        bg = "rgba(232,184,77,26)" if self.kind == "warn" else "rgba(229,96,92,26)"
        self.setStyleSheet(
            f"CountChip {{ background: {bg}; border: none; border-radius: 6px; }}"
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.activated.emit()


class StatusStrip(QFrame):
    """Bottom, always visible: current transfer progress, queued count, failures."""

    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusStrip")
        self.setFixedHeight(38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Open the Downloads workspace — current transfer, queue, failures")

        self.spinner = SpinnerLabel()
        self.title = QLabel("")
        self.title.setObjectName("stripTitle")
        self.message = QLabel("")
        self.message.setObjectName("stripMessage")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(150)
        self.progress.setFixedHeight(5)
        self.queued_chip = CountChip("warn")
        self.failed_chip = CountChip("bad")
        self.hint = QLabel("")
        self.hint.setObjectName("stripHint")
        self.queued_count = 0
        self.failure_count = 0
        self.running_title = ""
        self.progress_value = 0
        self.setAccessibleName("Download status: idle")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 3, 14, 3)
        lay.setSpacing(10)
        lay.addWidget(self.spinner)
        lay.addWidget(self.title)
        lay.addWidget(self.message, 1)
        lay.addWidget(self.progress)
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setFixedHeight(18)
        sep.setStyleSheet(f"background: {theme.BORDER};")
        lay.addWidget(sep)
        lay.addWidget(self.queued_chip)
        lay.addWidget(sep)
        lay.addWidget(self.failed_chip)
        lay.addStretch(1)
        lay.addWidget(self.hint)

    def update_state(
        self,
        current: str,
        message: str,
        running: bool,
        progress: float,
        queued: int,
        failed: int,
        active: int | None = None,
    ) -> None:
        """Called by the controller after every JobSnapshot update."""
        active_count = (
            int(active) if active is not None else (1 if running else 0)
        )
        self.queued_count = queued
        self.failure_count = failed
        self.running_title = current
        self.progress_value = int(progress)
        self.spinner.set_running(running)
        if active_count > 1:
            self.title.setText(f"{active_count} downloads active")
            self.message.setText(f"{current} · {message}" if current else message)
        else:
            self.title.setText(current)
            self.message.setText(message)
        self.progress.setRange(0, 0 if running and progress <= 0 else 100)
        self.progress.setValue(int(progress))
        self.queued_chip.set_count(queued, "queued")
        self.failed_chip.set_count(failed, "failed")
        state = "downloading" if running else "idle"
        active_text = f" {active_count} active." if active_count > 1 else ""
        self.setAccessibleName(
            f"Download status: {state}.{active_text} {queued} queued, {failed} failed."
        )

    def update_from_jobs(self, jobs) -> None:
        """Compatibility feed used by automation and restored-state checks."""
        live = [
            j for j in jobs if j.state in (JobState.RUNNING, JobState.WAITING_FOR_AUTH)
        ]
        running = next(
            (j for j in live if j.state is JobState.RUNNING),
            live[0] if live else None,
        )
        queued = sum(1 for j in jobs if j.state is JobState.QUEUED)
        failed = sum(1 for j in jobs if j.state is JobState.FAILED)
        if running is not None:
            progress = float(running.progress or 0)
            message = f"{running.state.value} · {progress:.0f}%"
            self.update_state(
                running.title, message, True, progress, queued, failed, len(live)
            )
        else:
            self.update_state("", "No active downloads.", False, 0.0, queued, failed)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            return
        super().keyPressEvent(event)

    def set_narrow(self, narrow: bool) -> None:
        """At small widths the message and hint yield room to the live title."""
        self.message.setVisible(not narrow)
        self.hint.setVisible(not narrow)
        self.progress.setFixedWidth(150 if not narrow else 110)
        self.title.setMaximumWidth(240 if narrow else 330)

    def set_hint(self, text: str) -> None:
        self.hint.setText(text)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
