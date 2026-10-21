import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from osw.steamcmd import DownloadCancelled, SteamCMD, SteamCMDError, failure_kind


@pytest.fixture
def client(tmp_path):
    instance = SteamCMD(tmp_path)
    # Use the current Python as an executable fake SteamCMD; never fetch Valve binaries.
    instance._binary = Path(sys.executable)
    return instance


@pytest.mark.skipif(os.name == "nt", reason="Linux process supervisor")
def test_silent_process_times_out_and_is_reaped(client):
    started = time.monotonic()
    with pytest.raises(SteamCMDError) as exc:
        client._run(["-c", "import time; time.sleep(20)"], timeout=0.15)
    assert exc.value.kind == "timeout"
    assert time.monotonic() - started < 2


@pytest.mark.skipif(os.name == "nt", reason="Linux process supervisor")
def test_silent_process_hits_inactivity_timeout_without_total_deadline(client):
    started = time.monotonic()
    with pytest.raises(SteamCMDError, match="stopped responding") as exc:
        client._run(
            ["-c", "import time; time.sleep(20)"],
            timeout=None,
            inactivity_timeout=0.15,
        )
    assert exc.value.kind == "timeout"
    assert time.monotonic() - started < 2


def test_cancel_silent_process(client):
    cancel = threading.Event()
    timer = threading.Timer(0.1, cancel.set)
    timer.start()
    try:
        with pytest.raises(DownloadCancelled):
            client._run(["-c", "import time; time.sleep(20)"], cancel=cancel)
    finally:
        timer.cancel()


def test_password_and_guard_prompts_without_newlines(client):
    code = (
        "import sys; print('Password:',end='',flush=True); pw=input(); "
        "print('Steam Guard code:',end='',flush=True); guard=input(); "
        "print('echo '+pw+' '+guard); print('Logged in OK')"
    )
    seen = []

    def auth(kind, prompt, cancel):
        seen.append(kind)
        return "CODE123"

    lines = client._run(["-c", code], password="SECRET_PASS", on_auth=auth, timeout=2)
    assert seen == ["guard"]
    assert "SECRET_PASS" not in "\n".join(lines)
    assert "CODE123" not in "\n".join(lines)
    assert "Logged in OK" in lines


def test_deadline_applies_while_auth_callback_waits(client):
    def slow(kind, prompt, cancel):
        cancel.wait(10)
        return None

    with pytest.raises(SteamCMDError) as exc:
        client._run(
            ["-c", "print('Password:', end='', flush=True); input()"], on_auth=slow, timeout=0.15
        )
    assert exc.value.kind == "timeout"


def test_cancelled_auth_and_nonzero_exit(client):
    with pytest.raises(SteamCMDError) as exc:
        client._run(
            ["-c", "print('Password:', end='', flush=True); input()"], on_auth=lambda *a: None
        )
    assert exc.value.kind == "authentication"
    with pytest.raises(SteamCMDError, match="status 7"):
        client._run(["-c", "raise SystemExit(7)"])


def test_mobile_approval_notifies_without_writing_a_code(client):
    prompts = []
    code = "import time; print('Confirm sign-in in your Steam mobile app', flush=True); time.sleep(.1); print('Logged in OK')"
    lines = client._run(
        ["-c", code], on_auth=lambda kind, prompt, cancel: prompts.append(kind) or "", timeout=2
    )
    assert prompts == ["approval"]
    assert "Logged in OK" in lines


@pytest.mark.skipif(os.name == "nt", reason="Linux process groups")
def test_timeout_terminates_descendant_processes(client):
    pids = []
    code = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); "
        "print(child.pid, flush=True); time.sleep(20)"
    )
    with pytest.raises(SteamCMDError):
        client._run(["-c", code], on_line=lambda line: pids.append(int(line)), timeout=0.2)
    assert pids
    # An orphan may briefly remain as a zombie until PID 1 reaps it; it must not be running.
    status = Path(f"/proc/{pids[0]}/stat")
    if status.exists():
        assert status.read_text().split()[2] == "Z"


def test_stale_files_do_not_make_failed_download_succeed(client, tmp_path, monkeypatch):
    root = tmp_path / "mods"
    path = root / "steamapps/workshop/content/10/20"
    path.mkdir(parents=True)
    (path / "old.txt").write_text("old")
    monkeypatch.setattr(
        client, "_run", Mock(return_value=["ERROR! Download item 20 failed (Access denied). "])
    )
    with pytest.raises(SteamCMDError) as exc:
        client.download_item(10, 20, root)
    assert exc.value.kind == "access"
    assert client._run.call_count == 1
    assert (path / "old.txt").read_text() == "old"


def test_current_success_and_verified_path_required(client, tmp_path, monkeypatch):
    path = tmp_path / "steamapps/workshop/content/10/20"
    path.mkdir(parents=True)
    (path / "mod.txt").write_text("new")
    run = Mock(return_value=[f'Success. Downloaded item 20 to "{path}" (3 bytes)'])
    monkeypatch.setattr(client, "_run", run)
    expected = tmp_path / "elsewhere/steamapps/workshop/content/10/20"
    assert client.download_item(10, 20, tmp_path / "elsewhere", password="hidden") == expected
    assert (expected / "mod.txt").read_text() == "new"
    assert (path / "mod.txt").read_text() == "new"
    assert "hidden" not in run.call_args.args[0]
    assert "validate" not in run.call_args.args[0]


def test_retry_adds_validation_after_fast_first_attempt(client, tmp_path, monkeypatch):
    run = Mock(side_effect=SteamCMDError("Network offline", "network"))
    monkeypatch.setattr(client, "_run", run)
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: self.is_set())
    with pytest.raises(SteamCMDError):
        client.download_item(10, 20, tmp_path, retries=2)
    assert "validate" not in run.call_args_list[0].args[0]
    assert "validate" in run.call_args_list[1].args[0]


def test_transient_retry_is_bounded(client, tmp_path, monkeypatch):
    run = Mock(side_effect=SteamCMDError("Network offline", "network"))
    monkeypatch.setattr(client, "_run", run)
    # Event.wait is the cancellable backoff, not time.sleep.
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: self.is_set())
    with pytest.raises(SteamCMDError):
        client.download_item(10, 20, tmp_path)
    assert run.call_count == 3


@pytest.mark.parametrize(
    "output,expected",
    [
        ("Missing manifest", "unknown"),
        ("Failed to download item (Timeout)", "timeout"),
        ("No subscription", "access"),
        ("Invalid password", "authentication"),
        ("error while loading shared libraries", "runtime"),
    ],
)
def test_failure_classification_does_not_guess_ownership(output, expected):
    assert failure_kind(output) == expected


def test_workspace_wait_is_cancellable(tmp_path):
    first, second = SteamCMD(tmp_path), SteamCMD(tmp_path)
    cancel = threading.Event()
    timer = threading.Timer(0.1, cancel.set)
    with first.workspace():
        timer.start()
        try:
            with pytest.raises(InterruptedError):
                with second.workspace(cancel):
                    pytest.fail("acquired an occupied workspace")
        finally:
            timer.cancel()


def test_publish_preserves_previous_download_on_copy_failure(client, tmp_path, monkeypatch):
    actual, expected = tmp_path / "actual", tmp_path / "destination"
    actual.mkdir()
    expected.mkdir()
    (actual / "new").write_text("new")
    (expected / "old").write_text("old")
    monkeypatch.setattr("osw.steamcmd.shutil.copytree", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        client._publish_download(actual, expected)
    assert (expected / "old").read_text() == "old"


def test_publish_replaces_destination_only_after_verified_copy(client, tmp_path):
    actual, expected = tmp_path / "actual", tmp_path / "destination"
    actual.mkdir()
    expected.mkdir()
    (actual / "new").write_text("new")
    (expected / "old").write_text("old")
    assert client._publish_download(actual, expected) == expected
    assert (expected / "new").read_text() == "new"
    assert not (expected / "old").exists()
