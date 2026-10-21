"""GUI facade over :mod:`osw.installed`.

The scan/lookup core lives in ``osw.installed`` so the CLI can share it; these
names are re-exported here because the Library workspace imports them.
"""

from ..installed import (
    InstalledIndex,
    InstalledItem,
    InstalledMetadata,
    content_dir,
    delete_installed_item,
    fetch_installed_metadata,
    scan_delivered_folder,
    scan_installed,
)

__all__ = [
    "InstalledIndex",
    "InstalledItem",
    "InstalledMetadata",
    "content_dir",
    "delete_installed_item",
    "fetch_installed_metadata",
    "scan_delivered_folder",
    "scan_installed",
]
