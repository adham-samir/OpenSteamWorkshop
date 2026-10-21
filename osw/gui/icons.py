"""Monochrome SVG icon set (packaged under gui/icons) plus a colorizing loader."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

ASSETS = Path(__file__).resolve().parent / "icons"

# Fallback paths used when an SVG asset is missing (name -> path data, filled?).
PATHS = {
    "browse": ("M2 3.2 8 1l6 2.2L8 5.4zM2 12.8V3.2M14 12.8V3.2M2 12.8 8 14l6-1.2 0-9.6", False),
    "import": ("M7 2v6.6M7 2 4.4 4.7M7 2l2.6 2.7M2 11v3h10v-3M6.6 9.5h1", False),
    "transfer": ("M1.5 5h9M8 2.7 10.5 5 8 7.3M15 11H6m2.5-2.3L6 11l2.5 2.3M13.8 1.6l1 1-1 1M1.6 13.8l-1-1 1-1", False),
    "search": ("M7 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm3.2 7.2 3.3 3.3", False),
    "check": ("m2.8 8.2 3.4 3.4 6.9-7", False),
    "x": ("m3.5 3.5 9 9m0-9-9 9", False),
    "warn": ("M8 1.6 14.5 13.4H1.5zM8 6v3.2M8 11.2v.3", False),
    "spinner": ("M8 1.6a6.4 6.4 0 0 0-6.4 6.4", False),
    "play": ("M5 3.2v9.6L12.6 8z", True),
    "stop": ("M4 4h8v8H4z", True),
    "copy": ("M5.6 5.6h8.8v8.8H5.6zM11.2 5.6V1.6H1.6v9.6h4", False),
    "stack": ("M8 1.4 1.6 4.4 8 7.4l6.4-3zM1.6 8.4 8 11.4l6.4-3M1.6 11.4 8 14.4l6.4-3", False),
    "info": ("M8 14A6 6 0 1 0 8 2a6 6 0 0 0 0 12zM8 7v4M8 5v.3", False),
    "star": ("M8 1.8l1.9 4 4.3.5-3.2 3 .9 4.4L8 11.5l-3.9 2.2.9-4.4-3.2-3 4.3-.5z", True),
    "eye": ("M8 3.6c-3.9 0-6.2 2.8-7 4.4.8 1.6 3.1 4.4 7 4.4s6.2-2.8 7-4.4c-.8-1.6-3.1-4.4-7-4.4zM8 6.4A1.6 1.6 0 1 0 8 9.6 1.6 1.6 0 0 0 8 6.4z", False),
}

# Names rendered in accent color by default where the QSS tint cannot reach.
DEFAULT_COLORS = {
    "brand": theme.ACCENT,
}


def icon_svg(name: str, color: str | None = None) -> str:
    """SVG markup rendered in the given color (defaults to theme secondary)."""
    color = color or DEFAULT_COLORS.get(name, theme.TEXT2)
    path = ASSETS / f"{name}.svg"
    if path.is_file():
        markup = path.read_text(encoding="utf-8")
        return markup.replace("#ffffff", color).replace("{c}", color)
    try:
        data, filled = PATHS[name]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unknown icon: {name}") from exc
    stroke, fill = ("none", color) if filled else (color, "none")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        f'<path d="{data}" fill="{fill}" stroke="{stroke}" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


@lru_cache
def _pixmap(name: str, color: str, size: int, square: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(icon_svg(name, color).encode()))
    img = QImage(square, square, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF((square - size) / 2, (square - size) / 2, size, size)
    renderer.render(p, rect)
    p.end()
    return QPixmap.fromImage(img)


def icon(name: str, color: str | None = None, size: int = 16) -> QIcon:
    """QIcon for toolbars/buttons; crisp at DPR without extra work."""
    pm = _pixmap(name, color or theme.TEXT2, size, max(size + 4, 20))
    return QIcon(pm)


def paint(painter: QPainter, rect: QRectF, name: str, color: str | None = None) -> None:
    """Paint an icon path directly (delegates use this instead of QIcon)."""
    renderer = QSvgRenderer(QByteArray(icon_svg(name, color or theme.TEXT2).encode()))
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = min(rect.width(), rect.height())
    target = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
    renderer.render(painter, target)
    painter.restore()
