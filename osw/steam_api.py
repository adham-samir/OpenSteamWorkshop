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
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

from .models import Game, ItemDetails, WorkshopItem
from .net import NetError, http, urljoin

STORE_SEARCH = "https://store.steampowered.com/api/storesearch/"
APPDETAILS = "https://store.steampowered.com/api/appdetails"
WORKSHOP_BROWSE = "https://steamcommunity.com/workshop/browse/"
FILE_DETAILS = "https://steamcommunity.com/sharedfiles/filedetails/"

SORTS = {
    "trend": "Most popular",
    "toprated": "Top rated",
    "mostrecent": "Most recent",
}

# ---------------------------------------------------------------- game search


def search_games(term: str) -> list[Game]:
    """Search the Steam store index for apps by name."""
    term = term.strip()
    if not term:
        return []
    data = http.json(urljoin(STORE_SEARCH, term=term, cc="us", l="en"))
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


def get_app_name(appid: int) -> str:
    try:
        data = http.json(urljoin(APPDETAILS, appids=appid, filters="basic"))
        node = data.get(str(appid), {})
        if node.get("success") and node.get("data"):
            return node["data"].get("name", "").strip()
    except (NetError, ValueError, KeyError):
        pass
    return f"App {appid}"


# ---------------------------------------------------------- workshop browsing


def _extract_ssr_blob(page: str) -> object:
    m = re.search(
        r'<script[^>]*type="application/json"[^>]*id="valve-ssr-data"[^>]*>(.*?)</script>',
        page,
        re.S,
    )
    if not m:
        raise NetError("Workshop page is missing its SSR payload (Valve redesigned the page)")
    return json.loads(m.group(1))


def _walk_results(node, out: list, depth: int = 0):
    """Recursively find dicts that carry a QueryFiles-like `results` list.

    Valve nests these either as normal JSON values or as *double-encoded*
    JSON strings (loaderData/renderContext), so strings that look like
    serialized JSON are unwrapped and walked as well.
    """
    if depth > 3 or len(out) > 1:
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
        if (
            isinstance(res, list)
            and res
            and isinstance(res[0], dict)
            and "publishedfileid" in res[0]
        ):
            out.append(node)
        for v in node.values():
            _walk_results(v, out, depth)
    elif isinstance(node, list):
        for v in node:
            _walk_results(v, out, depth)


def browse_workshop(
    appid: int,
    page: int = 1,
    per_page: int = 30,
    sort: str = "trend",
    search_text: str = "",
    section: str = "readytouseitems",
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
    page_html = http.text(url)
    blob = _extract_ssr_blob(page_html)

    holder: list = []
    _walk_results(blob, holder)
    if not holder:
        return [], 0, 0
    data = holder[0]
    items = [WorkshopItem.from_browse_dict(d, appid=appid) for d in data["results"]]
    return items, int(data.get("total_count") or 0), int(data.get("total_pages") or 0)


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


def get_item_details(fileid: int | str) -> ItemDetails:
    """Fetch the legacy details page and scrape the stable fields."""
    det = ItemDetails(fileid=int(fileid))
    url = urljoin(FILE_DETAILS, id=fileid, l="english")
    page = http.text(url)
    if "Steam Community :: Error" in page:
        det.error = "Steam could not load this item (deleted or private)"
        return det

    det.title = html_mod.unescape(_regex(page, r'<div class="workshopItemTitle">(.*?)</div>'))
    det.description = html_to_text(_regex(
        page, r'<div class="workshopItemDescription" id="highlightContent">(.*?)</div>'
    ))

    # creator block (link overlay may come before the content div)
    m_creators = re.search(r'<div class="creatorsBlock">(.*?)</div>\s*</div>', page, re.S)
    if m_creators:
        block = m_creators.group(1)
        m_name = re.search(
            r'class="friendBlockContent">\s*(.*?)\s*<br>', block, re.S)
        if m_name:
            det.author = html_mod.unescape(re.sub("<[^>]+>", "", m_name.group(1))).strip()
        m_url = re.search(r'class="friendBlockLinkOverlay" href="([^"]+)"', block)
        if m_url:
            det.author_url = m_url.group(1)

    # stats: left/right aligned columns pair up (File Size, Posted, ...)
    left = re.findall(r'<div class="detailsStatLeft">(.*?)</div>', page, re.S)
    right = re.findall(r'<div class="detailsStatRight">(.*?)</div>', page, re.S)
    for l, r in zip(left, right):
        l_txt = re.sub(r"\s+", " ", html_mod.unescape(re.sub("<[^>]+>", "", l))).strip().lower()
        r_txt = re.sub(r"\s+", " ", html_mod.unescape(re.sub("<[^>]+>", "", r))).strip()
        if "size" in l_txt:
            det.file_size = r_txt
        elif "posted" in l_txt or "updated" in l_txt:
            det.posted = det.posted or r_txt

    # tags (links back into browse with requiredtags[])
    det.tags = [
        html_mod.unescape(m.group(1))
        for m in re.finditer(r"requiredtags%5D=([^&\"]+)", page)
    ]

    # rating
    det.num_ratings = int(_regex(page, r'<div class="numRatings">([\d,\.]+) ratings?', "0").replace(",", "") or 0)

    # required dependencies: containers with a requiredItem div inside an <a id=..>
    req_block = _regex(page, r'id="RequiredItems">(.*?)</div>\s*</div>', "")
    if req_block:
        lg = _LinkGrabber()
        lg.feed(req_block)
        for href, name in lg.links:
            mm = re.search(r"[?&]id=(\d+)", href)
            if mm:
                det.required_items.append((int(mm.group(1)), name))

    # preview image
    m = re.search(r'onclick="ShowEnlargedImagePreview\(\s*\'([^\']+)\'', page)
    if m:
        det.preview_url = m.group(1)
    else:
        m = re.search(r'<img id="previewImageMain"[^>]*src="([^"]+)"', page)
        if m:
            det.preview_url = m.group(1)

    # appid breadcrumb (for orphan item pages)
    m = re.search(r"steamcommunity\.com/(?:apps?|linkmanagement)/(\d+)/", page)
    if m:
        det.appid = int(m.group(1))

    return det


# --------------------------------------------------------------------- utils


def resolve_ids(text: str) -> tuple[int | None, list[int]]:
    """Extract (appid, [fileids]) from any pasted workshop/store text."""
    appid = None
    fileids: list[int] = []
    m = re.search(r"steamcommunity\.com/app/(\d+)/", text)
    if m:
        appid = int(m.group(1))
    for m in re.finditer(r"sharedfiles/filedetails/\?id=(\d+)", text):
        fileids.append(int(m.group(1)))
    if not appid:
        m = re.search(r"store\.steampowered\.com/app/(\d+)", text)
        if m:
            appid = int(m.group(1))
    if not fileids:
        m = re.search(r"[?&]id=(\d+)", text)
        if m:
            fileids.append(int(m.group(1)))
    if not appid and not fileids and text.strip().isdigit():
        appid = int(text.strip())
    return appid, fileids
