"""Transfer Desk theme: palette tokens, QSS, and small shared painting helpers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication

BG = "#101317"
SURFACE = "#171C22"
RAISED = "#1F2630"
BORDER = "#2E3742"
TEXT = "#F3F6F8"
TEXT2 = "#98A3AF"
ACCENT = "#46B4E6"
ACCENT_STRONG = "#6BC9F2"
ACCENT_TEXT = "#07141C"
OK = "#4EC98A"
WARN = "#E8B84D"
BAD = "#E5605C"

# Short aliases used by components; keep one source of truth for the palette.
ACCENT_INK = ACCENT_TEXT
ACCENT_DIM = "#173646"
AMBER = WARN
GREEN = OK
RED = BAD
MUTED = TEXT2
RAIL = SURFACE

MONO_CSS = "'JetBrains Mono','Cascadia Code',Menlo,Consolas,monospace"

_ICONS = Path(__file__).resolve().parent / "icons"
CHECK_URL = (_ICONS / "check.svg").as_posix()


def apply_theme(_app=None) -> None:
    app = _app or QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(SHEET)


SHEET = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ background: {BG}; color: {TEXT}; font-size: 13px; }}
QLabel {{ background: transparent; }}
QToolTip {{
    background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER};
    padding: 4px 8px; font-size: 12px;
}}

/* ------------------------------------------------------------- text roles */
QLabel[role="h1"] {{ font-size: 23px; font-weight: 650; color: {TEXT}; }}
QLabel[role="h2"] {{ font-size: 16px; font-weight: 650; color: {TEXT}; }}
QLabel[role="h3"] {{ font-size: 13px; font-weight: 650; color: {TEXT}; }}
QLabel[role="muted"] {{ color: {TEXT2}; font-size: 12px; }}
QLabel[role="caption"] {{
    color: {TEXT2}; font-size: 10px; font-weight: 650; letter-spacing: 1px;
}}
QLabel[role="accent"] {{ color: {ACCENT}; }}
QLabel[role="good"] {{ color: {GREEN}; }}
QLabel[role="bad"] {{ color: {RED}; }}
QLabel[role="pageTitle"] {{ font-size: 15px; font-weight: 650; }}
QLabel[role="pageSub"] {{ color: {TEXT2}; font-size: 11px; }}

/* ---------------------------------------------------------------- surfaces */
QFrame[panel="true"] {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
}}
QFrame[panel="raised"] {{
    background: {RAISED}; border: 1px solid {BORDER}; border-radius: 9px;
}}
QFrame[rule="true"] {{ background: {BORDER}; border: none; max-height: 1px; }}
QFrame[notice] {{ border-radius: 7px; border: 1px solid {BORDER}; background: {SURFACE}; }}
QFrame[notice="info"] {{ background: #15242E; border-color: #244A5E; }}
QFrame[notice="success"] {{ background: #14271E; border-color: #27543B; }}
QFrame[notice="warning"] {{ background: #2A2416; border-color: #5A4821; }}
QFrame[notice="error"] {{ background: #2A1A1B; border-color: #5C2D2F; }}
QFrame#Card {{ background: transparent; }}

/* --------------------------------------------------------------- controls */
QPushButton {{
    background: {RAISED}; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 5px 13px; font-weight: 550; min-height: 22px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT2}; border-color: {BORDER}; background: {SURFACE}; }}
QPushButton[role="primary"] {{
    background: {ACCENT}; color: {ACCENT_TEXT}; border-color: {ACCENT};
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_STRONG}; border-color: {ACCENT_STRONG}; }}
QPushButton[role="primary"]:disabled {{ background: {RAISED}; color: {TEXT2}; }}
QPushButton[role="ghost"] {{ background: transparent; border-color: transparent; }}
QPushButton[role="ghost"]:hover {{ background: {RAISED}; border-color: {BORDER}; }}
QPushButton[role="danger"] {{ background: transparent; border-color: {BAD}; color: {BAD}; }}
QPushButton[role="danger"]:hover {{ background: #2A1A1B; }}
QPushButton[role="danger"]:disabled {{ color: {TEXT2}; border-color: {BORDER}; }}
QPushButton[role="link"] {{
    background: transparent; border-color: transparent; color: {ACCENT};
    padding: 2px 5px; min-height: 16px;
}}
QPushButton[role="link"]:hover {{ color: {ACCENT_STRONG}; text-decoration: underline; }}
QPushButton[role="link"]:disabled {{ color: {TEXT2}; }}
QPushButton[role="chip"] {{
    background: transparent; border: 1px solid {BORDER}; border-radius: 13px;
    padding: 3px 11px; color: {TEXT2}; min-height: 18px; font-size: 12px;
}}
QPushButton[role="chip"]:hover {{ color: {TEXT}; border-color: {TEXT2}; }}
QPushButton[role="chip"]:checked {{
    background: {ACCENT_DIM}; border-color: {ACCENT}; color: {TEXT};
}}
QPushButton[nav="true"] {{
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    text-align: left; padding: 6px 10px; color: {TEXT2}; font-weight: 550;
}}
QPushButton[nav="true"]:hover {{ background: {RAISED}; color: {TEXT}; }}
QPushButton[nav="true"]:checked {{
    background: {ACCENT_DIM}; border-color: #24556C; color: {TEXT};
}}
QPushButton[nav="true"]:checked:hover {{ background: {ACCENT_DIM}; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 7px; }}
QToolButton:hover {{ background: {RAISED}; border-color: {BORDER}; }}
QToolButton[role="icon"] {{ padding: 4px; }}

QLineEdit, QPlainTextEdit, QComboBox {{
    background: {RAISED}; border: 1px solid {BORDER}; border-radius: 7px; padding: 5px 9px;
    selection-background-color: {ACCENT}; selection-color: {ACCENT_TEXT};
}}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover {{ border-color: #3C4653; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {TEXT2}; margin: 0 8px 0 0;
}}
QComboBox QAbstractItemView {{
    background: {RAISED}; border: 1px solid {BORDER}; selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit[error="true"] {{ border-color: {BAD}; }}

QCheckBox {{ spacing: 8px; color: {TEXT}; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border: 1px solid {BORDER}; border-radius: 4px;
    background: {RAISED};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT}; image: url({CHECK_URL});
}}
QCheckBox:disabled {{ color: {TEXT2}; }}

/* ------------------------------------------------------------------ views */
QListView, QTableView {{ background: transparent; border: none; outline: none; }}
QListView::item {{ color: {TEXT}; }}
QListView::item:hover {{ background: transparent; }}
QListView::item:selected {{ background: transparent; }}
QTableView {{
    gridline-color: transparent;
    selection-background-color: #1B3543;
    selection-color: {TEXT};
    alternate-background-color: #1A2028;
}}
QTableView::item {{ padding: 0 8px; border-bottom: 1px solid #232B35; }}
QTableView::item:selected {{ background: #1B3543; }}
QTableView QTableCornerButton::section {{ background: {SURFACE}; border: none; }}
QTableView > QWidget {{ background: {SURFACE}; }}
QTableWidget {{ background: {SURFACE}; }}

QHeaderView::section {{
    background: {SURFACE}; color: {TEXT2}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px 10px; font-size: 11px; letter-spacing: 0.4px;
}}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 26px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT2}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 26px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{
    background: {RAISED}; border: none; border-radius: 2px; text-align: center;
    color: transparent; max-height: 5px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}

QStatusBar {{ background: transparent; border-top: 1px solid {BORDER}; color: {TEXT2}; font-size: 12px; }}
QStatusBar::item {{ border: none; }}

QMenu {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 5px 24px 5px 10px; border-radius: 5px; }}
QMenu::item:selected {{ background: {BORDER}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}

QInputDialog QLineEdit {{ min-width: 260px; }}
QMessageBox, QInputDialog QLabel {{ color: {TEXT}; }}
QDialogButtonBox QPushButton {{ min-width: 74px; }}

/* --------------------------------------------------------- named regions */
QWidget#sidebarFrame {{ background: {RAIL}; border-right: 1px solid {BORDER}; }}
QLabel#brandName {{ font-size: 12px; font-weight: 650; color: {TEXT}; }}
QLabel#brandSub {{ font-size: 9px; font-weight: 650; color: {TEXT2}; letter-spacing: 1.4px; }}
QLabel#navCaption {{ color: {TEXT2}; font-size: 9.5px; font-weight: 650; letter-spacing: 1.2px; }}
QFrame#sidebarRule {{ background: {BORDER}; border: none; max-height: 1px; }}
QLabel#railVersion {{ color: #66717D; font-size: 10px; }}
QFrame#statusStrip {{
    background: {SURFACE}; border-top: 1px solid {BORDER}; border-left: none;
    border-right: none; border-bottom: none;
}}
QFrame#statusStrip:hover {{ background: #1B222A; }}
QLabel#statusTitle {{ color: {TEXT}; font-size: 12px; }}
QLabel#statusMeta {{ color: {TEXT2}; font-size: 11px; }}
QLabel#statusQueue {{ color: {TEXT2}; font-size: 11px; }}
QLabel#statusFail {{ color: {RED}; font-size: 11px; }}
QLabel#statusOpen {{ color: {ACCENT}; font-size: 11px; font-weight: 600; }}
"""


def mono_font(size: int = 11, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFamily("monospace")
    font.setPointSize(size)
    font.setWeight(weight)
    return font


def vertical_progress_fill(rect: QRect) -> bool:  # pragma: no cover - helper hook
    return False


def draw_spinner(
    painter: QPainter, rect, color: QColor, thickness: float = 2.0, angle: float = 90
) -> None:
    """Quarter-arc spinner used by the status strip and inline loading states."""
    painter.save()
    pen = QPen(color, thickness)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    adj = QRectF(rect)
    m = thickness / 2 + 1
    adj.adjust(m, m, -m, -m)
    size = min(adj.width(), adj.height())
    sq = QRectF(
        adj.center().x() - size / 2, adj.center().y() - size / 2, size, size
    )
    painter.drawArc(sq, int(angle * 16), 90 * 16)
    painter.restore()


def status_chip_style() -> QSize:  # pragma: no cover - trivial geometry hint
    return QSize(3, 3)


def icon(*args, **kwargs):
    """Lazy proxy to :func:`osw.gui.icons.icon` (avoids a theme/icons cycle)."""
    from .icons import icon as _icon

    return _icon(*args, **kwargs)


def icon_svg(*args, **kwargs):
    from .icons import icon_svg as _icon_svg

    return _icon_svg(*args, **kwargs)


def paint(*args, **kwargs):
    from .icons import paint as _paint

    return _paint(*args, **kwargs)
