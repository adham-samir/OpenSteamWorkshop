"""Steam Web backends: game search, workshop browsing, item details.

All endpoints verified live (Oct 2026):

* Game search:
    https://store.steampowered.com/api/storesearch/?term=...&cc=us&l=en
  Public JSON, no API key.

* Workshop browse (new server-side-rendered React page). The interesting
  payload is inside  <script type="application/json" id="valve-ssr-data">
  as a JSON blob whose loaderData[i] strings unwrap (after a second
  json.loads) into dicts; one of them contains a QueryFiles-like object:
      {eresult, current_page, total_pages, total_count, results: [...]}
  URL parameters honoured by SSR:
      appid, p (page), numperpage, browsesort (trend|toprated|mostrecent),
      section=readytouseitems, searchtext=...

* Item details page is the *legacy* server-rendered HTML with stable class
  names (workshopItemTitle, detailsStatLeft/Right, requiredItemsContainer,
  creatorsBlock ...).
"""

from __future__ import annotations

import html as html_mod
import json
import re
import threading
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

from .models import Game, ItemDetails, WorkshopItem
from .net import NetError, http, urljoin

STORE_SEARCH = "https://store.steampowered.com/api/storesearch/"
APPDETAILS = "https://store.steampowered.com/api/appdetails"
WORKSHOP_BROWSE = "https://steamcommunity.com/workshop/browse/"
FILE_DETAILS = "https://steamcommunity.com/sharedfiles/filedetails/"
PUBLISHED_DETAILS = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
COLLECTION_DETAILS = "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/"

SORTS = {
    "trend": "Most popular",
    "toprated": "Top rated",
    "mostrecent": "Most recent",
}

# ---------------------------------------------------------------- game search


def search_games(term: str, cancel=None) -> list[Game]:
    """Search the Steam store index for apps by name."""
    term = term.strip()
    if not term:
        return []
    data = http.json(urljoin(STORE_SEARCH, term=term, cc="us", l="en"), cancel=cancel)
    games = []
    for it in data.get("items", []):
        games.append(
            Game(
                appid=int(it.get("id", 0)),
                name=it.get("name", "").strip(),
                type=it.get("type", "game"),
                image=it.get("tiny_image", ""),
            )
        )
    return games


def get_app_name(appid: int, cancel=None) -> str:
    try:
        data = http.json(urljoin(APPDETAILS, appids=appid, filters="basic"), cancel=cancel)
        node = data.get(str(appid), {})
        if node.get("success") and node.get("data"):
            return node["data"].get("name", "").strip()
    except (NetError, ValueError, KeyError):
        pass
    return f"App {appid}"


# ---------------------------------------------------------- workshop browsing


class _SSRParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("id") == "valve-ssr-data"

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False


def _extract_ssr_blob(page: str, appid_hint: int = 0) -> object:
    parser = _SSRParser()
    parser.feed(page)
    if not parser.parts:
        # A 302 to the generic /workshop hub usually means the app has no
        # community workshop on this site (e.g. CS2 -> Paradox Mods).
        tilt = re.search(r"<title>Steam Community :: (.*?)</title>", page, re.S)
        title = tilt.group(1).strip() if tilt else ""
        if title.lower() in ("steam workshop", "steam community"):
            raise NetError(
                f"This game ({appid_hint}) has no Steam Workshop community hub."
                " Its mods may live on a publisher platform (e.g. Paradox Mods)"
                " instead."
            )
        raise NetError("Workshop page is missing its SSR payload (Valve redesigned the page)")
    try:
        return json.loads("".join(parser.parts))
    except ValueError as exc:
        raise NetError("Workshop page contains an invalid SSR payload; try again later") from exc


def _walk_results(node, out: list, depth: int = 0):
    """Recursively find dicts that carry a QueryFiles-like `results` list.

    Valve nests these either as normal JSON values or as *double-encoded*
    JSON strings (loaderData/renderContext), so strings that look like
    serialized JSON are unwrapped and walked as well.
    """
    if depth > 16 or out:
        return
    if isinstance(node, str):
        s = node.strip()
        if s[:1] in "{[":
            try:
                decoded = json.loads(s)
            except (ValueError, RecursionError):
                return
            if isinstance(decoded, (dict, list)):
                _walk_results(decoded, out, depth + 1)
        return
    if isinstance(node, dict):
        res = node.get("results")
        if isinstance(res, list) and (
            (res and isinstance(res[0], dict) and "publishedfileid" in res[0])
            or (not res and "total_count" in node)
        ):
            out.append(node)
        for v in node.values():
            _walk_results(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk_results(v, out, depth + 1)


def browse_workshop(
    appid: int,
    page: int = 1,
    per_page: int = 30,
    sort: str = "trend",
    search_text: str = "",
    section: str = "readytouseitems",
    cancel=None,
) -> tuple[list[WorkshopItem], int, int]:
    """Return (items, total_count, total_pages)."""
    if sort not in SORTS:
        sort = "trend"
    url = urljoin(
        WORKSHOP_BROWSE,
        appid=appid,
        p=page,
        numperpage=per_page,
        browsesort=sort,
        section=section,
        l="english",
    )
    if search_text:
        url = urljoin(url, searchtext=search_text)
    page_html = http.text(url, cancel=cancel)
    blob = _extract_ssr_blob(page_html, appid_hint=appid)

    holder: list = []
    _walk_results(blob, holder)
    if not holder:
        raise NetError(
            "Workshop response format changed: no item results were found in the SSR payload"
        )
    data = holder[0]
    items = [WorkshopItem.from_browse_dict(d, appid=appid) for d in data["results"]]
    total = int(data.get("total_count") or 0)
    return items, total, int(data.get("total_pages") or ((total + per_page - 1) // per_page))


# -------------------------------------------------------------- item details


class _TextGrabber(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "br":
            self.chunks.append("\n")
        elif tag in ("p", "div", "li"):
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.chunks.append(data)


def html_to_text(fragment: str) -> str:
    p = _TextGrabber()
    p.feed(fragment)
    text = "".join(p.chunks)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return html_mod.unescape(text).strip()


class _LinkGrabber(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "a":
            self._href = d.get("href", "")
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, html_mod.unescape("".join(self._buf)).strip()))
            self._href = None


def _regex(html: str, pattern: str, default: str = "") -> str:
    m = re.search(pattern, html, re.S)
    return m.group(1).strip() if m else default


def _legacy_item_details(fileid: int | str, cancel=None) -> ItemDetails:
    """Fetch the legacy details page and scrape the stable fields."""
    det = ItemDetails(fileid=int(fileid))
    url = urljoin(FILE_DETAILS, id=fileid, l="english")
    page = http.text(url, cancel=cancel)
    if "Steam Community :: Error" in page:
        det.error = "Steam could not load this item (deleted or private)"
        return det

    det.title = html_mod.unescape(_regex(page, r'<div class="workshopItemTitle">(.*?)</div>'))
    det.description = html_to_text(
        _regex(page, r'<div class="workshopItemDescription" id="highlightContent">(.*?)</div>')
    )

    # creator block (link overlay may come before the content div)
    m_creators = re.search(r'<div class="creatorsBlock">(.*?)</div>\s*</div>', page, re.S)
    if m_creators:
        block = m_creators.group(1)
        m_name = re.search(r'class="friendBlockContent">\s*(.*?)\s*<br>', block, re.S)
        if m_name:
            det.author = html_mod.unescape(re.sub("<[^>]+>", "", m_name.group(1))).strip()
        m_url = re.search(r'class="friendBlockLinkOverlay" href="([^"]+)"', block)
        if m_url:
            det.author_url = m_url.group(1)

    # stats: left/right aligned columns pair up (File Size, Posted, ...)
    left = re.findall(r'<div class="detailsStatLeft">(.*?)</div>', page, re.S)
    right = re.findall(r'<div class="detailsStatRight">(.*?)</div>', page, re.S)
    for label, value in zip(left, right):
        l_txt = re.sub(r"\s+", " ", html_mod.unescape(re.sub("<[^>]+>", "", label))).strip().lower()
        r_txt = re.sub(r"\s+", " ", html_mod.unescape(re.sub("<[^>]+>", "", value))).strip()
        if "size" in l_txt:
            det.file_size = r_txt
        elif "posted" in l_txt or "updated" in l_txt:
            det.posted = det.posted or r_txt

    # tags (links back into browse with requiredtags[])
    det.tags = [
        html_mod.unescape(m.group(1)) for m in re.finditer(r"requiredtags%5D=([^&\"]+)", page)
    ]

    # rating
    det.num_ratings = int(
        _regex(page, r'<div class="numRatings">([\d,\.]+) ratings?', "0").replace(",", "") or 0
    )

    # required dependencies: containers with a requiredItem div inside an <a id=..>
    lg = _RequiredLinks()
    lg.feed(page)
    det.required_items = lg.items

    # preview image
    m = re.search(r'onclick="ShowEnlargedImagePreview\(\s*\'([^\']+)\'', page)
    if m:
        det.preview_url = m.group(1)
    else:
        m = re.search(r'<img id="previewImageMain"[^>]*src="([^"]+)"', page)
        if m:
            det.preview_url = m.group(1)

    # appid breadcrumb (for orphan item pages)
    m = re.search(r"steamcommunity\.com/(?:apps?|linkmanagement)/(\d+)(?:/|[\"'?#])", page)
    if m:
        det.appid = int(m.group(1))

    return det


class _RequiredLinks(HTMLParser):
    """Read every link in the required-items container, including nested markup."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.link_id = None
        self.text = []
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "RequiredItems":
            self.depth = 1
        elif self.depth and tag not in ("img", "br", "hr", "input", "meta", "link"):
            self.depth += 1
        if self.depth and tag == "a":
            _, ids = resolve_ids(attrs.get("href", ""))
            self.link_id = ids[0] if ids else None
            self.text = []

    def handle_endtag(self, tag):
        if self.depth:
            if tag in ("img", "br", "hr", "input", "meta", "link"):
                return
            if tag == "a" and self.link_id:
                self.items.append((self.link_id, "".join(self.text).strip()))
                self.link_id = None
            self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.link_id:
            self.text.append(data)


def get_published_files(
    fileids: list[int], cancel: threading.Event | None = None
) -> dict[int, dict]:
    """Fetch public metadata in bounded batches; no API key or login required."""
    result = {}
    ids = list(dict.fromkeys(int(i) for i in fileids))
    for offset in range(0, len(ids), 100):
        batch = ids[offset : offset + 100]
        data = {
            "itemcount": len(batch),
            **{f"publishedfileids[{i}]": n for i, n in enumerate(batch)},
        }
        response = http.json(PUBLISHED_DETAILS, method="POST", data=data, cancel=cancel)
        body = response.get("response") if isinstance(response, dict) else None
        rows = body.get("publishedfiledetails") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise NetError("Steam returned invalid Workshop item metadata")
        for row in rows:
            if isinstance(row, dict) and str(row.get("publishedfileid", "")).isdigit():
                result[int(row["publishedfileid"])] = row
        # Public metadata omits file_type even for collections. Use the collection
        # API to identify empty-file candidates, rather than guessing from size.
        candidates = [
            int(row["publishedfileid"])
            for row in rows
            if isinstance(row, dict)
            and str(row.get("publishedfileid", "")).isdigit()
            and str(row.get("result")) == "1"
            and "file_type" not in row
            and "filetype" not in row
            and not row.get("filename")
            and str(row.get("file_size") or "0") == "0"
        ]
        if candidates:
            try:
                collections = _collection_rows(candidates, cancel)
            except NetError as exc:
                for fileid in candidates:
                    result[fileid]["_collection_error"] = str(exc)
            else:
                for fileid in candidates:
                    collection = collections.get(fileid, {})
                    if str(collection.get("result")) == "1":
                        result[fileid]["file_type"] = 2
                        result[fileid]["_collection_children"] = _child_ids(collection)
    return result


def _child_ids(row):
    return [
        int(child["publishedfileid"])
        for child in row.get("children", [])
        if isinstance(child, dict) and str(child.get("publishedfileid", "")).isdigit()
    ]


def _collection_rows(fileids, cancel=None):
    response = http.json(
        COLLECTION_DETAILS,
        method="POST",
        data={
            "collectioncount": len(fileids),
            **{f"publishedfileids[{i}]": n for i, n in enumerate(fileids)},
        },
        cancel=cancel,
    )
    body = response.get("response") if isinstance(response, dict) else None
    rows = body.get("collectiondetails") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise NetError("Steam returned invalid Workshop collection metadata")
    return {
        int(row["publishedfileid"]): row
        for row in rows
        if isinstance(row, dict) and str(row.get("publishedfileid", "")).isdigit()
    }


def get_collection_children(fileid: int, cancel=None) -> list[int]:
    row = _collection_rows([fileid], cancel).get(fileid, {})
    if str(row.get("result")) != "1":
        raise NetError(f"Collection {fileid} is private, deleted or unavailable")
    return _child_ids(row)


def get_item_details(fileid: int | str, cancel=None) -> ItemDetails:
    fileid = int(fileid)
    try:
        rows = get_published_files([fileid], cancel)
        row = rows.get(fileid, {})
    except NetError:
        return _legacy_item_details(fileid, cancel)
    if int(row.get("result", 0)) != 1:
        return ItemDetails(
            fileid, error="Steam could not load this item (deleted, private or unavailable)"
        )
    if row.get("_collection_error"):
        return ItemDetails(
            fileid,
            error=f"Could not determine whether this item is a collection: {row['_collection_error']}",
        )
    item = WorkshopItem.from_browse_dict(row)
    det = ItemDetails(
        fileid,
        title=item.title,
        description=str(row.get("description") or ""),
        appid=item.appid,
        file_size=str(item.file_size) if item.file_size else "",
        tags=item.tags,
        required_items=[(n, "") for n in item.children],
        preview_url=item.preview_url,
        file_type=item.file_type,
    )
    try:
        legacy = _legacy_item_details(fileid, cancel)
    except NetError:
        return det
    for name in ("author", "author_url", "posted", "rating_text", "num_ratings"):
        setattr(det, name, getattr(legacy, name))
    if legacy.required_items:
        det.required_items = legacy.required_items
    return det


# --------------------------------------------------------------------- utils


def resolve_ids(text: str) -> tuple[int | None, list[int]]:
    """Extract (appid, [fileids]) from any pasted workshop/store text."""
    appid, fileids = None, []
    if text.strip().isdigit():
        return int(text.strip()) or None, []
    for token in re.split(r"[\s,]+", text.strip()):
        parsed = urlparse(token)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if parsed.scheme not in ("http", "https") or host not in (
            "steamcommunity.com",
            "store.steampowered.com",
        ):
            continue
        match = re.match(r"/apps?/(\d+)(?:/|$)", parsed.path)
        if match:
            appid = int(match.group(1)) or None
        if host == "steamcommunity.com" and parsed.path.rstrip("/") in (
            "/sharedfiles/filedetails",
            "/workshop/filedetails",
        ):
            for value in parse_qs(parsed.query).get("id", []):
                if value.isdigit() and int(value) > 0:
                    fileids.append(int(value))
    return appid, list(dict.fromkeys(fileids))
