"""Data models shared across CLI and GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def fmt_size(n: int | str | None) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    units = [(1 << 40, "TB"), (1 << 30, "GB"), (1 << 20, "MB"), (1 << 10, "KB")]
    for div, suffix in units:
        if n >= div:
            return f"{n / div:.1f} {suffix}"
    return f"{n} B"


def fmt_unix(ts: int | str | None) -> str:
    try:
        ts = int(ts or 0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def fmt_count(n: int) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


@dataclass
class Game:
    appid: int
    name: str
    type: str = "game"
    image: str = ""  # small capsule url


@dataclass
class WorkshopItem:
    publishedfileid: int
    appid: int = 0
    title: str = ""
    short_description: str = ""
    preview_url: str = ""
    creator: str = ""  # steamid64
    author: str = ""  # resolved personaname (detail page)
    author_url: str = ""
    file_size: int = 0
    tags: list[str] = field(default_factory=list)
    children: list[int] = field(default_factory=list)
    time_created: int = 0
    time_updated: int = 0
    subscriptions: int = 0
    favorited: int = 0
    views: int = 0
    num_comments: int = 0
    star_rating: float = 0.0  # 0..5
    total_votes: int = 0
    file_type: int = 0

    @property
    def url(self) -> str:
        return f"https://steamcommunity.com/sharedfiles/filedetails/?id={self.publishedfileid}"

    @classmethod
    def from_browse_dict(cls, d: dict, appid: int = 0) -> "WorkshopItem":
        def _int(v) -> int:
            if v in (None, ""):
                return 0
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        nbytes = _int(d.get("file_size"))
        if not nbytes:
            nbytes = _int(d.get("file_size", "0"))
        tags = [
            (t.get("display_name") or t.get("tag", "")) if isinstance(t, dict) else str(t)
            for t in (d.get("tags") or [])
        ]
        children = [
            c.get("publishedfileid") if isinstance(c, dict) else c
            for c in (d.get("children") or [])
        ]
        try:
            rating = float(d.get("star_rating") or 0)
        except (TypeError, ValueError):
            rating = 0.0
        return cls(
            publishedfileid=_int(d.get("publishedfileid")),
            appid=_int(d.get("consumer_appid") or d.get("consumer_app_id")) or appid,
            title=(d.get("title") or "").strip(),
            short_description=(d.get("short_description") or "").strip(),
            preview_url=d.get("preview_url") or "",
            creator=str(d.get("creator") or ""),
            file_size=nbytes,
            tags=[t for t in tags if t],
            children=[_int(c) for c in children if _int(c) > 0],
            time_created=_int(d.get("time_created")),
            time_updated=_int(d.get("time_updated")),
            subscriptions=_int(d.get("lifetime_subscriptions")) or _int(d.get("subscriptions")),
            favorited=_int(d.get("lifetime_favorited")) or _int(d.get("favorited")),
            views=_int(d.get("views")),
            num_comments=_int(d.get("num_comments_public")),
            star_rating=rating,
            total_votes=_int(d.get("total_votes")),
            file_type=_int(d.get("file_type", d.get("filetype"))),
        )


@dataclass
class ItemDetails:
    fileid: int
    title: str = ""
    description: str = ""
    author: str = ""
    author_url: str = ""
    appid: int = 0
    file_size: str = ""
    posted: str = ""
    rating_text: str = ""
    num_ratings: int = 0
    tags: list[str] = field(default_factory=list)
    required_items: list[tuple[int, str]] = field(default_factory=list)  # (fileid, title)
    preview_url: str = ""
    error: str = ""
    file_type: int = 0
