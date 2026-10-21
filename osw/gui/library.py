"""GUI facade over :mod:`osw.installed`.

The scan/lookup core lives in ``osw.installed`` so the CLI can share it; these
names are re-exported here because the Library workspace imports them.
"""

from ..installed import (
    UNAVAILABLE,
    UNKNOWN,
    UP_TO_DATE,
    UPDATE_AVAILABLE,
    InstalledIndex,
    InstalledItem,
    InstalledMetadata,
    UpdateInfo,
    check_updates,
    content_dir,
    delete_installed_item,
    fetch_installed_metadata,
    read_acf_updates,
    scan_delivered_folder,
    scan_installed,
)

__all__ = [
    "UP_TO_DATE",
    "UNAVAILABLE",
    "UNKNOWN",
    "UPDATE_AVAILABLE",
    "InstalledIndex",
    "InstalledItem",
    "InstalledMetadata",
    "UpdateInfo",
    "check_updates",
    "content_dir",
    "delete_installed_item",
    "fetch_installed_metadata",
    "read_acf_updates",
    "scan_delivered_folder",
    "scan_installed",
]
