"""Atomic JSON stores and cancellable cross-process workspace locks."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path


def atomic_json(path: Path, data: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def file_lock(path: Path, cancel: threading.Event | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        acquired = False
        try:
            while not acquired:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Cancelled while waiting for SteamCMD")
                try:
                    if os.name == "nt":  # pragma: no cover
                        import msvcrt

                        stream.seek(0)
                        if stream.read(1) == b"":
                            stream.write(b"0")
                            stream.flush()
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (BlockingIOError, PermissionError):
                    if (cancel or threading.Event()).wait(0.1):
                        raise InterruptedError("Cancelled while waiting for SteamCMD")
            yield
        finally:
            if acquired:
                if os.name == "nt":  # pragma: no cover
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)
