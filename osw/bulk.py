"""Resolve URL/ID lists, collections and required items before any download starts."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

from .models import WorkshopItem
from .net import NetError
from .steam_api import get_collection_children, get_item_details, get_published_files, resolve_ids


@dataclass(frozen=True)
class ResolutionIssue:
    reference: str
    message: str


@dataclass
class DownloadResolution:
    items: list[WorkshopItem] = field(default_factory=list)
    issues: list[ResolutionIssue] = field(default_factory=list)
    duplicates: int = 0
    collections: int = 0
    dependencies: set[int] = field(default_factory=set)


def resolve_downloads(references, appid_hint=None, include_dependencies=False, cancel=None):
    result = DownloadResolution()
    if isinstance(references, str):
        references = [references]
    pending = deque()
    for reference in references:
        for token in re.split(r"[\s,]+", reference.strip()):
            if not token:
                continue
            _, fileids = resolve_ids(token)
            if token.isdigit() and int(token) > 0:
                fileids = [int(token)]  # bare numbers here are Workshop IDs, unlike game search
            if not fileids:
                result.issues.append(
                    ResolutionIssue(
                        token, "Expected a Workshop item/collection URL or positive item ID"
                    )
                )
            pending.extend((n, str(token), False) for n in fileids)
    visited = set()
    metadata = {}
    while pending:
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Import cancelled")
        # Prefetch metadata for the current frontier, preserving traversal order.
        missing = list(
            dict.fromkeys(n for n, _, _ in pending if n not in metadata and n not in visited)
        )[:100]
        if missing:
            try:
                metadata.update(get_published_files(missing, cancel))
            except NetError as exc:
                for n in missing:
                    metadata[n] = {"error": str(exc)}
        fileid, reference, is_dependency = pending.popleft()
        if is_dependency:
            result.dependencies.add(fileid)
        if fileid in visited:
            result.duplicates += 1
            continue
        visited.add(fileid)
        if len(visited) > 10000:
            result.issues.append(
                ResolutionIssue(reference, "Import exceeds 10,000 unique items; split the list")
            )
            break
        row = metadata.get(fileid, {})
        if row.get("_collection_error"):
            result.issues.append(
                ResolutionIssue(reference, f"Collection lookup failed: {row['_collection_error']}")
            )
            continue
        if str(row.get("result", 0)) != "1":
            result.issues.append(
                ResolutionIssue(
                    reference,
                    row.get("error") or f"Item {fileid} is private, deleted or unavailable",
                )
            )
            continue
        try:
            item = WorkshopItem.from_browse_dict(row, appid=int(appid_hint or 0))
        except (TypeError, ValueError, AttributeError) as exc:
            result.issues.append(ResolutionIssue(reference, f"Malformed Workshop metadata: {exc}"))
            continue
        if item.file_type == 2:  # EWorkshopFileTypeCollection
            try:
                children = row.get("_collection_children")
                if children is None:
                    children = get_collection_children(fileid, cancel)
                result.collections += 1
                pending.extend((n, f"Collection {fileid}: {n}", is_dependency) for n in children)
            except NetError as exc:
                result.issues.append(ResolutionIssue(reference, str(exc)))
            continue
        if not item.appid:
            result.issues.append(
                ResolutionIssue(reference, f"Unknown game for item {fileid}; supply an app ID hint")
            )
            continue
        result.items.append(item)
        if include_dependencies:
            children = item.children
            if "children" not in row:
                try:
                    children = [n for n, _ in get_item_details(fileid, cancel).required_items]
                except NetError as exc:
                    result.issues.append(
                        ResolutionIssue(reference, f"Could not resolve required items: {exc}")
                    )
            pending.extend((n, f"Required by {fileid}: {n}", True) for n in children)
    return result
