"""Installed-content lookup shared by the GUI and CLI."""

import json

from osw.installed import (
    InstalledIndex,
    content_dir,
    scan_installed,
    scan_installed_all,
)


def _staged(root, appid, fileid, payload=b"abc"):
    item_dir = content_dir(root) / str(appid) / str(fileid)
    item_dir.mkdir(parents=True)
    (item_dir / "mod.txt").write_bytes(payload)
    return item_dir


def test_index_scan_lookup_record_and_remove(tmp_path):
    root = tmp_path / "mods"
    item_dir = _staged(root, 4000, 100)

    index = InstalledIndex()
    assert index.scan(root)
    hit = index.lookup(4000, 100)
    assert hit is not None and hit.path == item_dir and hit.size == len(b"abc")
    assert index.lookup(0, 100) is hit  # unknown app id falls back to the file id
    assert index.lookup(500, 100) is None  # a mismatched app id is not a hit
    assert 100 in index and len(index) == 1

    index.record(4000, 101, item_dir.parent / "101", title="Fresh install")
    recorded = index.lookup(4000, 101)
    assert recorded is not None and recorded.title == "Fresh install"
    assert recorded.delivered is False

    index.remove(4000, 101)
    assert index.lookup(4000, 101) is None
    assert index.lookup(4000, 100) is hit


def test_index_includes_delivered_override_markers(tmp_path):
    root = tmp_path / "mods"
    _staged(root, 4000, 100)
    game_mods = tmp_path / "RimWorld" / "Mods"
    delivered = game_mods / "Wiremod"
    delivered.mkdir(parents=True)
    (delivered / ".opensteamworkshop.json").write_text(
        json.dumps({"appid": 4000, "fileid": 100, "title": "Wiremod"})
    )

    index = InstalledIndex()
    assert index.scan(root, {4000: game_mods})
    hit = index.lookup(4000, 100)
    assert hit is not None
    assert hit.delivered is True
    assert hit.path == delivered
    assert hit.location_label.startswith("Delivered")


def test_scan_all_finds_redundant_default_copy(tmp_path):
    root = tmp_path / "mods"
    staged = _staged(root, 4000, 100)
    game_mods = tmp_path / "RimWorld" / "Mods"
    delivered = game_mods / "Wiremod"
    delivered.mkdir(parents=True)
    (delivered / "About.xml").write_text("<Mod/>")
    (delivered / ".opensteamworkshop.json").write_text(
        json.dumps({"appid": 4000, "fileid": 100, "title": "Wiremod"})
    )

    items, groups = scan_installed_all(root, game_paths={4000: game_mods})

    assert [(item.appid, item.fileid) for item in items] == [(4000, 100)]
    assert items[0].path == delivered  # delivered wins, as before
    assert len(groups) == 1
    group = groups[0]
    assert group.label == "Wiremod"
    assert [(copy.path, copy.delivered) for copy in group.copies] == [
        (staged, False),
        (delivered, True),
    ]
    assert group.redundant.path == staged
    assert group.requires_choice is False


def test_scan_all_requires_choice_between_two_delivered_copies(tmp_path):
    root = tmp_path / "mods"
    first = tmp_path / "GameA" / "Mods" / "Wiremod"
    second = tmp_path / "GameB" / "Mods" / "Wiremod copy"
    for folder in (first, second):
        folder.mkdir(parents=True)
        (folder / ".opensteamworkshop.json").write_text(
            json.dumps({"appid": 4000, "fileid": 100, "title": "Wiremod"})
        )

    items, groups = scan_installed_all(
        root, game_paths={4000: first.parent, 4001: second.parent}
    )

    assert len(items) == 1
    assert len(groups) == 1
    assert {copy.path for copy in groups[0].copies} == {first, second}
    assert groups[0].redundant is None
    assert groups[0].requires_choice is True


def test_index_exposes_duplicate_groups_and_clears_them(tmp_path):
    root = tmp_path / "mods"
    staged = _staged(root, 4000, 100)
    game_mods = tmp_path / "Mods"
    delivered = game_mods / "Wiremod"
    delivered.mkdir(parents=True)
    (delivered / ".opensteamworkshop.json").write_text(
        json.dumps({"appid": 4000, "fileid": 100, "title": "Wiremod"})
    )

    index = InstalledIndex()
    assert index.scan(root, {4000: game_mods})
    assert index.duplicate_count() == 1
    assert index.duplicates()[0].redundant.path == staged

    index.remove(4000, 100)
    assert index.duplicate_count() == 0


def test_cancelled_scan_leaves_index_untouched(tmp_path):
    import threading

    root = tmp_path / "mods"
    item_dir = _staged(root, 4000, 100)
    cancel = threading.Event()
    cancel.set()

    assert scan_installed(root, cancel) is None

    index = InstalledIndex()
    index.record(4000, 100, item_dir)
    assert index.scan(root, cancel=cancel) is False
    assert index.lookup(4000, 100).path == item_dir
