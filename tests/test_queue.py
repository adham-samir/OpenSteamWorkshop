import json
import threading
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from osw.delivery import deliver_item, read_marker, sanitize_folder_name
from osw.models import WorkshopItem
from osw.net import NetError
from osw.queue import DownloadManager, JobState


def manager(tmp_path, monkeypatch, **kwargs):
    instance = DownloadManager(tmp_path / "mods", **kwargs)
    monkeypatch.setattr(instance, "ensure_workers", lambda: None)
    return instance


def test_retry_requeues_and_skips_old_generation(tmp_path, monkeypatch):
    mgr = manager(tmp_path, monkeypatch)
    job = mgr.add_direct(10, 20)
    old = mgr._queue.get_nowait()
    job.state = JobState.FAILED
    assert mgr.add_direct(10, 20) is job
    new = mgr._queue.get_nowait()
    assert old[0] == new[0] == job.id
    assert new[1] > old[1]
    assert job.state is JobState.QUEUED


def test_deduplication_uses_destination(tmp_path, monkeypatch):
    mgr = manager(tmp_path, monkeypatch)
    first = mgr.add_direct(10, 20)
    assert mgr.add_direct(10, 20) is first
    mgr.content_root = tmp_path / "other"
    second = mgr.add_direct(10, 20)
    assert second.id != first.id
    assert first.dest == tmp_path / "mods"


def test_install_failure_becomes_terminal(tmp_path, monkeypatch):
    mgr = manager(tmp_path, monkeypatch)
    job = mgr.add_direct(10, 20)

    def fail(*args):
        raise NetError("Installer offline", transient=True)

    monkeypatch.setattr(mgr, "steamcmd", fail)
    mgr._run_job(job)
    assert job.state is JobState.FAILED
    assert job.message == "Installer offline"
    assert not job._inflight


def test_cancel_is_terminal_and_returned_path_is_used(tmp_path, monkeypatch):
    mgr = manager(tmp_path, monkeypatch)
    job = mgr.add_direct(10, 20)

    class Client:
        def download_item(self, appid, fileid, destination, **kwargs):
            assert destination == job.dest
            mgr.cancel(job)
            return tmp_path / "actual"

    monkeypatch.setattr(mgr, "steamcmd", lambda *args: Client())
    mgr._run_job(job)
    assert job.state is JobState.CANCELLED
    assert job.output_path == ""
    assert mgr.retry(job.id)

    class Success:
        def download_item(self, *args, **kwargs):
            return tmp_path / "actual"

    monkeypatch.setattr(mgr, "steamcmd", lambda *args: Success())
    mgr._run_job(job)
    assert job.state is JobState.DONE
    assert job.output_path == str(tmp_path / "actual")


def test_snapshots_are_immutable_and_not_live_jobs(tmp_path, monkeypatch):
    updates = []
    mgr = manager(tmp_path, monkeypatch, on_job_update=updates.append)
    job = mgr.add_direct(10, 20)
    snapshot = updates[-1]
    job.message = "changed later"
    assert snapshot.message == "Queued"
    with pytest.raises(FrozenInstanceError):
        snapshot.message = "mutable"


def test_queue_restores_interrupted_without_credentials(tmp_path, monkeypatch):
    path = tmp_path / "queue.json"
    mgr = manager(
        tmp_path, monkeypatch, queue_path=path, username="user", password="never-store-me"
    )
    job = mgr.add_direct(10, 20)
    job.state = JobState.WAITING_FOR_AUTH
    job.logs.append("sensitive prompt")
    mgr.emit(job)
    contents = path.read_text()
    assert "never-store-me" not in contents and "sensitive prompt" not in contents
    assert "username" not in contents
    restored = manager(tmp_path, monkeypatch, queue_path=path)
    other = restored.jobs[0]
    assert other.id == job.id
    assert other.state is JobState.INTERRUPTED
    assert not other.username and not other._password
    assert restored._queue.empty()
    restored.resume_unfinished()
    assert other.state is JobState.QUEUED
    assert not restored._queue.empty()


def test_corrupt_queue_is_preserved(tmp_path):
    path = tmp_path / "queue.json"
    path.write_text('{"version":99,"jobs":[]}')
    with pytest.raises(ValueError):
        DownloadManager(tmp_path, queue_path=path)
    assert json.loads(path.read_text())["version"] == 99


def test_parallel_clamping_and_workspace_dirs(tmp_path):
    assert DownloadManager(tmp_path, parallel=0).parallel == 1
    assert DownloadManager(tmp_path, parallel=9).parallel == 3
    assert DownloadManager(tmp_path, parallel="junk").parallel == 1

    base = tmp_path / "steamcmd"
    mgr = DownloadManager(tmp_path, parallel=3, steamcmd_dir=base)
    assert mgr.workspace_dir(0) == base.resolve()
    assert mgr.workspace_dir(1) == (tmp_path / "steamcmd-w1").resolve()
    assert mgr.workspace_dir(2) == (tmp_path / "steamcmd-w2").resolve()


def test_different_appids_download_concurrently(tmp_path, monkeypatch):
    mgr = DownloadManager(tmp_path, parallel=2)
    started: dict[int, float] = {}
    started_lock = threading.Lock()
    two_started = threading.Event()
    release = threading.Event()

    class Client:
        def download_item(self, appid, fileid, dest, **kwargs):
            with started_lock:
                started[fileid] = time.monotonic()
                if len(started) >= 2:
                    two_started.set()
            release.wait(5)
            return tmp_path / str(fileid)

    monkeypatch.setattr(mgr, "steamcmd", lambda *args: Client())
    try:
        a = mgr.add_direct(10, 20)
        b = mgr.add_direct(11, 21)
        assert two_started.wait(3), f"only started {started}"
        release.set()
        deadline = time.monotonic() + 3
        while (
            a.state is not JobState.DONE or b.state is not JobState.DONE
        ) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert a.state is b.state is JobState.DONE
    finally:
        release.set()
        mgr.shutdown()


def test_same_appid_serializes_even_with_spare_workers(tmp_path, monkeypatch):
    mgr = DownloadManager(tmp_path, parallel=2)
    first_started = threading.Event()
    release = threading.Event()
    started: list[int] = []
    started_lock = threading.Lock()

    class Client:
        def download_item(self, appid, fileid, dest, **kwargs):
            with started_lock:
                started.append(fileid)
            first_started.set()
            release.wait(3)
            return tmp_path / str(fileid)

    monkeypatch.setattr(mgr, "steamcmd", lambda *args: Client())
    try:
        a = mgr.add_direct(10, 20)
        assert first_started.wait(2)
        b = mgr.add_direct(10, 21)
        time.sleep(0.25)
        assert started == [20], "the same app's manifest must not be written twice at once"
        release.set()
        deadline = time.monotonic() + 3
        while (
            a.state is not JobState.DONE or b.state is not JobState.DONE
        ) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started == [20, 21]
        assert a.state is b.state is JobState.DONE
    finally:
        release.set()
        mgr.shutdown()


def test_worker_survives_idle_and_restarts_after_parallel_change(tmp_path, monkeypatch):
    mgr = DownloadManager(tmp_path, parallel=2)

    class Client:
        def download_item(self, appid, fileid, dest, **kwargs):
            return tmp_path / str(fileid)

    monkeypatch.setattr(mgr, "steamcmd", lambda *args: Client())
    try:
        a = mgr.add_direct(10, 20)
        deadline = time.monotonic() + 2
        while a.state is not JobState.DONE and time.monotonic() < deadline:
            time.sleep(0.01)
        assert a.state is JobState.DONE

        time.sleep(0.15)
        mgr.parallel = 1
        mgr.ensure_workers()
        c = mgr.add_direct(12, 22)
        deadline = time.monotonic() + 2
        while c.state is not JobState.DONE and time.monotonic() < deadline:
            time.sleep(0.01)
        assert c.state is JobState.DONE
    finally:
        mgr.shutdown()


def test_shutdown_interrupts_active_and_pending_jobs(tmp_path, monkeypatch):
    mgr = manager(tmp_path, monkeypatch)
    job = mgr.add_direct(10, 20)
    mgr.shutdown()
    assert job.state is JobState.INTERRUPTED
    assert job.cancel_event.is_set()


def test_closed_frontend_callbacks_do_not_kill_jobs(tmp_path, monkeypatch):
    def closed(*args):
        raise RuntimeError("Qt object deleted")

    mgr = manager(tmp_path, monkeypatch, on_job_update=closed, on_log=closed)

    class Client:
        def download_item(self, *args, **kwargs):
            return tmp_path / "actual"

    monkeypatch.setattr(mgr, "steamcmd", lambda *a: Client())
    job = mgr.add_direct(10, 20)
    mgr._run_job(job)
    mgr.log("Closed frontend")
    assert job.state is JobState.DONE


def test_progress_updates_do_not_rewrite_saved_queue(tmp_path, monkeypatch):
    from unittest.mock import Mock

    mgr = manager(tmp_path, monkeypatch, queue_path=tmp_path / "queue.json")
    job = mgr.add_direct(10, 20)
    atomic = Mock()
    monkeypatch.setattr("osw.queue.atomic_json", atomic)

    class Client:
        def download_item(self, *args, **kwargs):
            kwargs["on_attempt"](1)
            for value in (0.1, 0.2, 1.0, 1.1, 50.0, 100.0):
                kwargs["on_progress"](value)
            return tmp_path / "actual"

    monkeypatch.setattr(mgr, "steamcmd", lambda *args: Client())
    mgr._run_job(job)
    # RUNNING, attempt, DONE, and the final inflight transition are durable. Progress is not.
    assert atomic.call_count == 4


def test_bulk_enqueue_saves_once_and_keeps_single_worker(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from osw.models import WorkshopItem

    mgr = manager(tmp_path, monkeypatch, queue_path=tmp_path / "queue.json")
    atomic = Mock()
    monkeypatch.setattr("osw.queue.atomic_json", atomic)
    jobs = mgr.add_many([WorkshopItem(20, appid=10), WorkshopItem(21, appid=10)])
    assert len(jobs) == 2
    assert atomic.call_count == 1


# ------------------------------------------------------------- per-game delivery


def _stage(client_dest, appid, fileid, files=None):
    staged = (
        Path(client_dest) / "steamapps" / "workshop" / "content" / str(appid) / str(fileid)
    )
    staged.mkdir(parents=True)
    for name, payload in (files or {"About.xml": b"<Mod/>"}).items():
        (staged / name).write_bytes(payload)
    return staged


def test_delivery_moves_staged_item_and_tags_it(tmp_path, monkeypatch):
    mgr = manager(tmp_path, monkeypatch)
    deliver_to = tmp_path / "RimWorld" / "Mods"
    job = mgr.add_direct(294100, 123, title="Wiremod", deliver_to=deliver_to)

    class Client:
        def download_item(self, appid, fileid, dest, **kwargs):
            return _stage(dest, appid, fileid)

    monkeypatch.setattr(mgr, "steamcmd", lambda *args: Client())
    mgr._run_job(job)

    final = deliver_to / "Wiremod"
    assert job.state is JobState.DONE
    assert final.is_dir() and (final / "About.xml").read_bytes() == b"<Mod/>"
    assert job.output_path == str(final)
    staged_item = Path(mgr.content_root) / "steamapps" / "workshop" / "content" / "294100" / "123"
    assert not staged_item.exists()
    marker = read_marker(final)
    assert (marker["appid"], marker["fileid"], marker["title"]) == (294100, 123, "Wiremod")
    assert job.snapshot().deliver_to == str(deliver_to.resolve())


def test_delivery_failure_fails_job_and_keeps_staged_files(tmp_path, monkeypatch):
    mgr = manager(tmp_path, monkeypatch)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a folder")
    job = mgr.add_direct(10, 20, title="Wiremod", deliver_to=blocker / "Mods")
    staged = {}

    class Client:
        def download_item(self, appid, fileid, dest, **kwargs):
            staged["path"] = _stage(dest, appid, fileid)
            return staged["path"]

    monkeypatch.setattr(mgr, "steamcmd", lambda *args: Client())
    mgr._run_job(job)

    assert job.state is JobState.FAILED
    assert job.error_kind == "delivery"
    assert staged["path"].is_dir()
    assert job.output_path == ""


def test_delivery_replaces_rename_and_collision(tmp_path):
    root = tmp_path / "Mods"

    def staged(name, payload=b"x"):
        path = tmp_path / f"stage-{name}"
        path.mkdir()
        (path / "payload.bin").write_bytes(payload)
        return path

    first = deliver_item(staged("one"), root, 10, 1, "Same title")
    assert first.name == "Same title"

    colliding = deliver_item(staged("two"), root, 10, 2, "Same title")
    assert colliding.name == "Same title (2)"

    renamed = deliver_item(staged("three", b"new"), root, 10, 1, "Better title")
    assert renamed.name == "Better title"
    assert (renamed / "payload.bin").read_bytes() == b"new"
    assert not first.exists()
    assert colliding.is_dir()

    # The first item moved away, so the original title is free again.
    replaced = deliver_item(staged("four", b"again"), root, 10, 2, "Same title")
    assert replaced.name == "Same title"
    assert not colliding.exists()
    assert (replaced / "payload.bin").read_bytes() == b"again"


def test_delivery_folder_names_are_sanitized(tmp_path):
    assert sanitize_folder_name("  Bad/Name: <x>?  ", 5) == "BadName x"
    assert sanitize_folder_name("", 5) == "5"
    assert sanitize_folder_name("x" * 200, 5) == "x" * 60


def test_deliver_to_round_trips_and_old_queue_files_load_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "queue.json"
    deliver_to = tmp_path / "Mods"
    mgr = manager(tmp_path, monkeypatch, queue_path=path)
    job = mgr.add_direct(10, 20, title="Wiremod", deliver_to=deliver_to)
    assert job.deliver_to == deliver_to.resolve()
    saved = json.loads(path.read_text())
    assert saved["jobs"][0]["deliver_to"] == str(deliver_to.resolve())

    reloaded = manager(tmp_path, monkeypatch, queue_path=path)
    assert reloaded.jobs[0].deliver_to == deliver_to.resolve()

    saved["jobs"][0].pop("deliver_to")
    path.write_text(json.dumps(saved))
    legacy = manager(tmp_path, monkeypatch, queue_path=path)
    assert legacy.jobs[0].deliver_to is None


def test_add_deduplicates_per_delivery_folder_and_bulk_resolves_overrides(tmp_path, monkeypatch):
    mgr = manager(tmp_path, monkeypatch)
    first = mgr.add_direct(10, 20, title="Wiremod", deliver_to=tmp_path / "A")
    second = mgr.add_direct(10, 20, title="Wiremod", deliver_to=tmp_path / "B")
    assert first is not second
    assert mgr.add_direct(10, 20, title="Wiremod", deliver_to=tmp_path / "A") is first

    jobs = mgr.add_many(
        [WorkshopItem(21, appid=10), WorkshopItem(22, appid=30)],
        deliver_for=lambda appid: tmp_path / "A" if appid == 10 else None,
    )
    assert jobs[0].deliver_to == (tmp_path / "A").resolve()
    assert jobs[1].deliver_to is None


def test_reinstall_reenqueues_a_completed_job(tmp_path, monkeypatch):
    mgr = manager(tmp_path, monkeypatch)
    job = mgr.add_direct(10, 20)
    mgr._queue.get_nowait()  # original enqueue
    job.state = JobState.DONE
    job.output_path = str(tmp_path / "mods" / "old")
    generation = job._generation

    assert mgr.add_direct(10, 20) is job  # plain add keeps the finished job
    assert job.state is JobState.DONE
    assert job._generation == generation

    item = WorkshopItem(20, appid=10)
    assert mgr.add(item, reinstall=True) is job
    assert job.state is JobState.QUEUED
    assert job.output_path == ""
    assert job._generation > generation
    assert mgr._queue.get_nowait()[1] == job._generation
