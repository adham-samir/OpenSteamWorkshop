"""Restart-safe download queue shared by the Qt GUI and CLI.

SteamCMD still runs one process per workspace, but up to three worker slots can
run at the same time. Workers use separate managed SteamCMD installs and a
per-app lock, so two items from the same game never update one ``.acf`` at once.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .delivery import deliver_item
from .installed import read_acf_updates
from .models import WorkshopItem
from .steamcmd import DEFAULT_DATA_DIR, DownloadCancelled, SteamCMD
from .storage import atomic_json


class JobState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_AUTH = "waiting for login"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


ACTIVE = (JobState.QUEUED, JobState.RUNNING, JobState.WAITING_FOR_AUTH)


def _clamp_parallel(value) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(3, value))


@dataclass(frozen=True)
class JobSnapshot:
    id: str
    appid: int
    app_name: str
    fileid: int
    title: str
    dest: Path
    state: JobState
    progress: float
    message: str
    attempts: int
    output_path: str
    error_kind: str
    logs: tuple[str, ...]
    inflight: bool
    deliver_to: str = ""


class DownloadJob:
    def __init__(
        self, appid, app_name, fileid, title, dest, *, username="", password="", steamcmd_dir=None,
        deliver_to=None,
    ):
        if int(appid) <= 0 or int(fileid) <= 0:
            raise ValueError("App and Workshop IDs must be positive integers")
        self.id = uuid.uuid4().hex
        self.appid, self.app_name = int(appid), app_name
        self.fileid, self.title = int(fileid), title
        self.dest = Path(dest).expanduser().resolve()
        self.deliver_to = Path(deliver_to).expanduser().resolve() if deliver_to else None
        self.username, self._password = username, password
        self.steamcmd_dir = str(steamcmd_dir) if steamcmd_dir else ""
        self.state, self.progress = JobState.QUEUED, 0.0
        self.message, self.attempts = "", 0
        self.output_path, self.error_kind = "", ""
        self.logs: list[str] = []
        self.cancel_event = threading.Event()
        self._generation = 0
        self._inflight = False

    def snapshot(self):
        return JobSnapshot(
            self.id,
            self.appid,
            self.app_name,
            self.fileid,
            self.title,
            self.dest,
            self.state,
            self.progress,
            self.message,
            self.attempts,
            self.output_path,
            self.error_kind,
            tuple(self.logs),
            self._inflight,
            str(self.deliver_to) if self.deliver_to else "",
        )

    def record(self):
        # Deliberately exclude account identity, secrets, logs and authentication prompts.
        return {
            "id": self.id,
            "appid": self.appid,
            "app_name": self.app_name,
            "fileid": self.fileid,
            "title": self.title,
            "dest": str(self.dest),
            "deliver_to": str(self.deliver_to) if self.deliver_to else "",
            "state": self.state.value,
            "attempts": self.attempts,
            "output_path": self.output_path,
            "error_kind": self.error_kind,
            "steamcmd_dir": self.steamcmd_dir,
        }


@dataclass
class DownloadManager:
    content_root: Path | str
    steamcmd_dir: Path | str | None = None
    username: str = ""
    password: str = ""
    parallel: int = 1  # 1-3 simultaneous SteamCMD workspaces
    queue_path: Path | None = None
    on_job_update: object = None
    on_log: object = None
    on_auth: object = None
    jobs: list[DownloadJob] = field(default_factory=list, init=False)
    _queue: queue.Queue = field(default_factory=queue.Queue, init=False)
    _lock: object = field(default_factory=threading.RLock, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _threads: dict[int, threading.Thread] = field(default_factory=dict, init=False)
    _app_locks: dict[int, threading.Lock] = field(default_factory=dict, init=False)
    _clients: dict = field(default_factory=dict, init=False)
    _batch_depth: int = field(default=0, init=False)

    def __post_init__(self):
        self.content_root = Path(self.content_root).expanduser().resolve()
        self.parallel = _clamp_parallel(self.parallel)
        if self.queue_path:
            self.queue_path = Path(self.queue_path)
            self.restore()

    def log(self, message):
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                pass

    def _save(self):
        if self.queue_path and not self._batch_depth:
            atomic_json(self.queue_path, {"version": 1, "jobs": [j.record() for j in self.jobs]})

    def emit(self, job, *, persist=True):
        with self._lock:
            if persist:
                try:
                    self._save()
                except OSError as exc:
                    self.log(f"Could not save download queue: {exc}")
            snapshot = job.snapshot()
        if self.on_job_update:
            try:
                self.on_job_update(snapshot)
            except Exception:
                pass  # a closed frontend must not kill the worker

    def workspace_dir(self, slot: int, base=None) -> Path | None:
        """SteamCMD install directory for one worker slot.

        Slot 0 uses the configured (or default) directory so a serial queue
        keeps the existing install. Extra slots get a sibling workspace, which
        keeps SteamCMD's ``steamapps`` state and locks independent.
        """
        raw = base or self.steamcmd_dir
        if not raw:
            root = DEFAULT_DATA_DIR / "steamcmd"
        else:
            root = Path(raw).expanduser()
        root = root.resolve()
        if slot <= 0:
            return root
        return root.with_name(f"{root.name}-w{int(slot)}")

    def steamcmd(self, install_dir=None, cancel=None):
        key = str(install_dir or self.steamcmd_dir or "")
        with self._lock:
            client = self._clients.get(key)
            if client is None:
                client = self._clients[key] = SteamCMD(key or None)
        client.ensure_installed(log=self.log, cancel=cancel)
        return client

    def add(self, item: WorkshopItem, app_name="", deliver_to=None, *, reinstall=False):
        dest = Path(self.content_root).expanduser().resolve()
        deliver_to = Path(deliver_to).expanduser().resolve() if deliver_to else None
        with self._lock:
            for job in self.jobs:
                if (job.appid, job.fileid, job.dest, job.deliver_to) == (
                    item.appid,
                    item.publishedfileid,
                    dest,
                    deliver_to,
                ):
                    finished = job.state in (
                        JobState.FAILED,
                        JobState.CANCELLED,
                        JobState.INTERRUPTED,
                    )
                    if finished or (reinstall and job.state is JobState.DONE):
                        if reinstall:
                            job.output_path = ""
                        self.retry(job.id)
                    return job
            job = DownloadJob(
                item.appid,
                app_name,
                item.publishedfileid,
                item.title or f"Item {item.publishedfileid}",
                dest,
                username=self.username,
                password=self.password,
                steamcmd_dir=self.steamcmd_dir,
                deliver_to=deliver_to,
            )
            self.jobs.append(job)
            self._enqueue(job)
        return job

    def add_direct(self, appid, fileid, app_name="", title="", deliver_to=None):
        return self.add(
            WorkshopItem(publishedfileid=fileid, appid=appid, title=title),
            app_name,
            deliver_to=deliver_to,
        )

    def add_many(self, items, deliver_for=None, *, reinstall=False):
        """Persist a bulk enqueue once, rather than fsync the whole queue per mod."""
        with self._lock:
            self._batch_depth += 1
            try:
                jobs = [
                    self.add(
                        item,
                        deliver_to=(
                            deliver_for(item.appid) if deliver_for is not None else None
                        ),
                        reinstall=reinstall,
                    )
                    for item in items
                ]
            finally:
                self._batch_depth -= 1
                self._save()
                self.ensure_workers()
        return jobs

    def _enqueue(self, job):
        if self._stop.is_set():
            raise RuntimeError("Download manager is shutting down")
        job.state, job.progress, job.message, job.error_kind = JobState.QUEUED, 0.0, "Queued", ""
        job.cancel_event = threading.Event()
        job._generation += 1
        self._queue.put((job.id, job._generation))
        self.emit(job)
        self.ensure_workers()

    def get_job(self, job_or_id):
        key = job_or_id.id if hasattr(job_or_id, "id") else job_or_id
        with self._lock:
            return next((job for job in self.jobs if job.id == key), None)

    def retry(self, job_or_id, *, username=None, password=None):
        with self._lock:
            job = self.get_job(job_or_id)
            if job is None or job.state in ACTIVE or job._inflight:
                return False
            if username is not None:
                job.username = username
            if password is not None:
                job._password = password
            self._enqueue(job)
            return True

    def cancel(self, job_or_id):
        with self._lock:
            job = self.get_job(job_or_id)
            if job is not None and job.state in ACTIVE:
                job.cancel_event.set()
                job.state, job.message = JobState.CANCELLED, "Cancelled"
                self.emit(job)

    def ensure_workers(self):
        with self._lock:
            if self._batch_depth:
                return
            self.parallel = _clamp_parallel(self.parallel)
            for slot in range(self.parallel):
                thread = self._threads.get(slot)
                if thread is None or not thread.is_alive():
                    thread = threading.Thread(
                        target=self._worker,
                        args=(slot,),
                        daemon=True,
                        name=f"osw-download-{slot}",
                    )
                    self._threads[slot] = thread
                    thread.start()

    def _app_lock(self, appid: int) -> threading.Lock:
        with self._lock:
            return self._app_locks.setdefault(int(appid), threading.Lock())

    def _worker(self, slot: int = 0):
        while not self._stop.is_set():
            if slot >= self.parallel:
                return
            try:
                job_id, generation = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                with self._lock:
                    job = self.get_job(job_id)
                    valid = job and generation == job._generation and job.state is JobState.QUEUED
                if not valid:
                    continue
                lock = self._app_lock(job.appid)
                if not lock.acquire(blocking=False):
                    # Another slot owns this game's SteamCMD manifest. Put the
                    # job back so this worker can help with a different game,
                    # instead of blocking capacity behind a lock.
                    self._queue.put((job.id, generation))
                    if self._stop.wait(0.05):
                        return
                    continue
                try:
                    self._run_job(job, slot)
                finally:
                    lock.release()
            finally:
                self._queue.task_done()

    def _run_job(self, job, slot: int = 0):
        with self._lock:
            if job.state is not JobState.QUEUED:
                return
            job.state, job._inflight = JobState.RUNNING, True
            job.message = "Preparing SteamCMD / waiting for its workspace"
            self.emit(job)

        def update(*, persist=True, **values):
            with self._lock:
                if job.state not in (JobState.CANCELLED, JobState.INTERRUPTED):
                    for key, value in values.items():
                        setattr(job, key, value)
                    self.emit(job, persist=persist)

        def line(text):
            with self._lock:
                job.logs = (job.logs + [text])[-200:]
            if "ERROR!" in text or "Downloading item" in text or text.startswith("Retrying"):
                # Messages and logs are intentionally not restored, so avoid an fsync here.
                update(persist=False, message=text)

        last_progress_emit = 0.0

        def progress(value):
            """Keep the UI responsive without fsyncing or flooding it on every SteamCMD tick."""
            nonlocal last_progress_emit
            now = time.monotonic()
            with self._lock:
                changed_enough = abs(value - job.progress) >= 0.5
            if value < 100 and not changed_enough and now - last_progress_emit < 0.25:
                return
            last_progress_emit = now
            update(persist=False, progress=value)

        def auth(kind, prompt, cancel):
            update(state=JobState.WAITING_FOR_AUTH, message="Waiting for Steam authentication")
            try:
                return self.on_auth(job.snapshot(), kind, prompt, cancel) if self.on_auth else None
            finally:
                update(state=JobState.RUNNING, message="Authenticating")

        try:
            client = self.steamcmd(
                self.workspace_dir(slot, job.steamcmd_dir or self.steamcmd_dir),
                job.cancel_event,
            )
            path = client.download_item(
                job.appid,
                job.fileid,
                job.dest,
                login=job.username or "anonymous",
                password=job._password,
                on_line=line,
                on_progress=progress,
                on_attempt=lambda n: update(attempts=n),
                cancel=job.cancel_event,
                on_auth=auth,
            )
            if job.cancel_event.is_set():
                raise DownloadCancelled()
            if job.deliver_to is not None:
                # Delivery is part of the running job: no new job state, so
                # filters, status strip and queue control stay unaffected.
                update(
                    persist=False,
                    progress=100.0,
                    message=f"Delivering to {job.deliver_to}…",
                )
                # SteamCMD recorded the exact revision it just installed; keep
                # it in the marker so the update checker can compare it later.
                revision = read_acf_updates(job.dest, job.appid).get(job.fileid, 0)
                path = deliver_item(
                    path,
                    job.deliver_to,
                    job.appid,
                    job.fileid,
                    job.title,
                    updated=revision,
                )
            update(state=JobState.DONE, progress=100.0, output_path=str(path), message=str(path))
        except (DownloadCancelled, InterruptedError):
            with self._lock:
                if job.state is not JobState.INTERRUPTED:
                    job.state, job.message = JobState.CANCELLED, "Cancelled"
        except Exception as exc:
            update(
                state=JobState.FAILED,
                error_kind=getattr(
                    exc, "kind", "network" if hasattr(exc, "transient") else "unknown"
                ),
                message=str(exc) or type(exc).__name__,
            )
        finally:
            with self._lock:
                job._inflight = False
                self.emit(job)

    def restore(self):
        if not self.queue_path.is_file():
            return
        data = json.loads(self.queue_path.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or data.get("version") != 1
            or not isinstance(data.get("jobs"), list)
        ):
            raise ValueError("Unsupported queue file; the original file has been preserved")
        restored = []
        for row in data["jobs"]:
            job = DownloadJob(
                row["appid"],
                row.get("app_name", ""),
                row["fileid"],
                row["title"],
                row["dest"],
                steamcmd_dir=row.get("steamcmd_dir"),
                deliver_to=row.get("deliver_to") or None,
            )
            job.id = str(row["id"])
            job.state = JobState(row["state"])
            if job.state in ACTIVE:
                job.state = JobState.INTERRUPTED
                job.message = "Interrupted — choose Resume unfinished"
            job.attempts = int(row.get("attempts", 0))
            job.output_path = str(row.get("output_path", ""))
            job.error_kind = str(row.get("error_kind", ""))
            if job.state is JobState.FAILED:
                job.message = f"Previous download failed ({job.error_kind or 'unknown'}); retry to collect a fresh log"
            job.progress = 100.0 if job.state is JobState.DONE else 0.0
            restored.append(job)
        if len({j.id for j in restored}) != len(restored):
            raise ValueError("Queue contains duplicate job IDs")
        self.jobs = restored

    def resume_unfinished(self):
        for job in list(self.jobs):
            if job.state is JobState.INTERRUPTED:
                self.retry(job.id)  # anonymous after restart; never restore credentials

    def clear_finished(self):
        with self._lock:
            removed = [
                j.id
                for j in self.jobs
                if j.state in (JobState.DONE, JobState.FAILED, JobState.CANCELLED)
                and not j._inflight
            ]
            self.jobs[:] = [j for j in self.jobs if j.id not in removed]
            self._save()
            return removed

    def shutdown(self, timeout=3):
        self._stop.set()
        with self._lock:
            for job in self.jobs:
                if job.state in ACTIVE:
                    job.cancel_event.set()
                    job.state, job.message = (
                        JobState.INTERRUPTED,
                        "Interrupted — choose Resume unfinished",
                    )
                    self.emit(job)
        threads = list(self._threads.values())
        deadline = time.monotonic() + max(0.1, timeout)
        for thread in threads:
            if thread is threading.current_thread():
                continue
            thread.join(max(0.0, deadline - time.monotonic()))
