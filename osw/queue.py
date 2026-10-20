"""Download queue shared by CLI and GUI.

Plain threads + callbacks (no Qt dependency), so everything works in the CLI
and the GUI wraps callbacks in Qt signals.
"""

from __future__ import annotations

import queue as queue_mod
import threading
import traceback
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Union

from .models import WorkshopItem
from .steamcmd import SteamCMDError, SteamCMD

PathLike = Union[Path, str]


class JobState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadJob:
    """One queued workshop download. dest = content root directory."""

    def __init__(self, appid: int, app_name: str, fileid: int, title: str, dest: PathLike):
        self.appid = appid
        self.app_name = app_name
        self.fileid = fileid
        self.title = title
        self.dest = Path(dest)
        self.state = JobState.QUEUED
        self.progress = 0.0
        self.message = ""
        self.attempts = 0


@dataclass
class DownloadManager:
    content_root: Path
    steamcmd_dir: Path | None = None
    username: str = ""
    password: str = ""
    parallel: int = 2

    jobs: list = field(default_factory=list, init=False)
    _queue: queue_mod.Queue = field(default_factory=queue_mod.Queue, init=False)
    _threads: list = field(default_factory=list, init=False)
    _steamcmd: SteamCMD | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    shutdown: bool = field(default=False, init=False)

    # callbacks (invoked from worker threads; UI must marshal to its own thread)
    on_job_update: object = None   # callable(job)
    on_log: object = None          # callable(str)

    # ------------------------------------------------------------- plumbing

    def log(self, msg: str) -> None:
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def emit(self, job: DownloadJob) -> None:
        if self.on_job_update:
            try:
                self.on_job_update(job)
            except Exception:
                pass

    def steamcmd(self) -> SteamCMD:
        if self._steamcmd is None:
            self._steamcmd = SteamCMD(self.steamcmd_dir or None)
            self._steamcmd.ensure_installed(
                log=lambda m: self.log("steamcmd: " + m)
            )
        return self._steamcmd

    # ------------------------------------------------------------- queueing

    def add(self, item: WorkshopItem, app_name: str = "") -> DownloadJob:
        job = DownloadJob(
            appid=item.appid,
            app_name=app_name,
            fileid=item.publishedfileid,
            title=item.title or f"item {item.publishedfileid}",
            dest=self.content_root,
        )
        with self._lock:
            for j in self.jobs:
                if j.appid == job.appid and j.fileid == job.fileid:
                    if j.state in (JobState.DONE, JobState.FAILED, JobState.CANCELLED):
                        j.state = JobState.QUEUED
                        j.progress = 0.0
                        j.message = ""
                        self.emit(j)
                    return j
            self.jobs.append(job)
        self._queue.put(job)
        self.log(f"Queued {job.title}")
        self.ensure_workers()
        self.emit(job)
        return job

    def add_direct(self, appid: int, fileid: int, app_name: str = "", title: str = "") -> DownloadJob:
        item = WorkshopItem(publishedfileid=fileid, appid=appid, title=title or f"item {fileid}")
        return self.add(item, app_name)

    def ensure_workers(self) -> None:
        self.shutdown = False
        with self._lock:
            alive = [t for t in self._threads if t.is_alive()]
            need = max(1, self.parallel) - len(alive)
            for i in range(need):
                t = threading.Thread(target=self._worker, daemon=True, name=f"osw-worker-{i}")
                t.start()
                self._threads.append(t)

    def cancel(self, job: DownloadJob) -> None:
        if job.state in (JobState.RUNNING, JobState.QUEUED):
            job.state = JobState.CANCELLED
            self.emit(job)

    # -------------------------------------------------------------- worker

    def _worker(self) -> None:
        while not self.shutdown:
            try:
                job = self._queue.get(timeout=0.5)
            except queue_mod.Empty:
                return
            if job.state is not JobState.QUEUED:
                continue
            self._run_job(job)

    def _run_job(self, job: DownloadJob) -> None:
        if job.state is not JobState.QUEUED:
            return
        job.state = JobState.RUNNING
        job.progress = 0.0
        job.message = "preparing steamcmd..."
        self.emit(job)
        try:
            sc = self.steamcmd()
        except (SteamCMDError, NetError) as e:
            job.state = JobState.FAILED
            job.message = str(e)
            self.emit(job)
            return

        def prog(p: float) -> None:
            job.progress = p
            self.emit(job)

        def line(l: str) -> None:
            if "Downloading item" in l:
                job.message = "downloading"
                self.emit(job)
            elif "ERROR!" in l:
                job.message = l.strip()
                self.emit(job)

        try:
            job.attempts += 1
            sc.download_item(
                appid=job.appid,
                fileid=job.fileid,
                content_root=self.content_root,
                login=self.username or "anonymous",
                password=self.password,
                on_line=line,
                on_progress=prog,
            )
            job.state = JobState.DONE
            job.progress = 100.0
            job.message = str(job.dest / "steamapps/workshop/content" / str(job.appid) / str(job.fileid))
            self.log(f"Downloaded {job.title} -> {job.message}")
        except (SteamCMDError, OSError) as e:
            job.state = JobState.FAILED
            job.message = str(e).strip() or "unknown failure"
            self.log(f"FAILED {job.title}: {job.message.splitlines()[0] if job.message else ''}")
        except Exception as e:  # pragma: no cover
            job.state = JobState.FAILED
            job.message = f"bug: {e}\n{traceback.format_exc(limit=2)}"
            self.log(f"FAILED {job.title}: {e}")
        self.emit(job)
