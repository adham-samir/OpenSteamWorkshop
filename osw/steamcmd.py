"""Official SteamCMD installer and supervised, serialized Workshop downloads."""

from __future__ import annotations

import codecs
import os
import platform
import queue
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .net import http
from .storage import file_lock

STEAMCMD_URL_LINUX = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
STEAMCMD_URL_WIN = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "OpenSteamWorkshop"
AuthHandler = Callable[[str, str, threading.Event], str | None]


class SteamCMDError(RuntimeError):
    def __init__(self, message: str, kind: str = "unknown"):
        super().__init__(message)
        self.kind = kind


class DownloadCancelled(SteamCMDError):
    def __init__(self, message: str = "Download cancelled"):
        super().__init__(message, "cancelled")


def failure_kind(output: str) -> str:
    text = output.lower()
    if any(
        s in text
        for s in ("no subscription", "access denied", "does not own", "insufficient privilege")
    ):
        return "access"
    if any(
        s in text
        for s in (
            "invalid password",
            "invalid login",
            "account logon denied",
            "two-factor code mismatch",
        )
    ):
        return "authentication"
    if any(s in text for s in ("timeout", "timed out")):
        return "timeout"
    if any(
        s in text for s in ("no connection", "connection failed", "service unavailable", "network")
    ):
        return "network"
    if any(s in text for s in ("file not found", "item not found", "deleted", "private item")):
        return "unavailable"
    if any(s in text for s in ("shared libraries", "cannot execute", "exec format", "startupdlls")):
        return "runtime"
    return "unknown"


class SteamCMD:
    def __init__(self, install_dir: Path | str | None = None):
        self.install_dir = Path(install_dir or DEFAULT_DATA_DIR / "steamcmd").expanduser().resolve()
        windows = platform.system() == "Windows"
        self._binary = self.install_dir / ("steamcmd.exe" if windows else "steamcmd.sh")
        self._url = STEAMCMD_URL_WIN if windows else STEAMCMD_URL_LINUX
        self._archive = "zip" if windows else "tar.gz"
        self._mutex = threading.RLock()
        self._workspace_depth = threading.local()

    @contextmanager
    def workspace(self, cancel: threading.Event | None = None):
        while not self._mutex.acquire(timeout=0.1):
            self._check_cancel(cancel)
        try:
            if getattr(self._workspace_depth, "held", False):
                yield
            else:
                with file_lock(self.install_dir / ".osw.lock", cancel):
                    self._workspace_depth.held = True
                    try:
                        yield
                    finally:
                        self._workspace_depth.held = False
        finally:
            self._mutex.release()

    @staticmethod
    def _check_cancel(cancel):
        if cancel is not None and cancel.is_set():
            raise DownloadCancelled()

    @property
    def installed(self) -> bool:
        return self._binary.is_file()

    def ensure_installed(self, log=None, cancel: threading.Event | None = None) -> Path:
        with self.workspace(cancel):
            self._check_cancel(cancel)
            if self.installed:
                return self._binary
            if platform.system() not in ("Linux", "Windows"):
                raise SteamCMDError(
                    "This release supports SteamCMD on Linux and Windows", "runtime"
                )
            if log:
                log("Downloading Valve's official SteamCMD…")
            data = http.request(self._url, cancel=cancel)
            archive = self.install_dir / f"steamcmd.{self._archive}"
            archive.write_bytes(data)
            try:
                if self._archive == "tar.gz":
                    with tarfile.open(archive) as tar:
                        if hasattr(tarfile, "data_filter"):
                            tar.extractall(self.install_dir, filter="data")
                        else:  # Python 3.10 without the extraction-filter backport
                            for member in tar.getmembers():
                                target = (self.install_dir / member.name).resolve()
                                if not target.is_relative_to(self.install_dir) or not (
                                    member.isfile() or member.isdir()
                                ):
                                    raise SteamCMDError("Unsafe SteamCMD archive entry", "runtime")
                            tar.extractall(self.install_dir)
                else:  # pragma: no cover
                    import zipfile

                    with zipfile.ZipFile(archive) as zipped:
                        zipped.extractall(self.install_dir)
                self._binary.chmod(0o755)
                self.verify_works(log, cancel)
            finally:
                archive.unlink(missing_ok=True)
            return self._binary

    def verify_works(self, log=None, cancel=None):
        try:
            self._run(["+quit"], on_line=log, cancel=cancel, timeout=600)
        except OSError as exc:
            raise SteamCMDError(
                f"Cannot run SteamCMD: {exc}. On Debian/Ubuntu, install lib32gcc-s1.", "runtime"
            ) from exc

    def _run(
        self,
        args: list[str],
        on_line=None,
        stdin_lines=None,
        timeout: float | None = 600.0,
        *,
        inactivity_timeout: float | None = None,
        cancel: threading.Event | None = None,
        on_auth: AuthHandler | None = None,
        password: str = "",
    ) -> list[str]:
        """Read chunks, not lines; supervise total and output-inactivity deadlines."""
        with self.workspace(cancel):
            self._check_cancel(cancel)
            cmd = [str(self._binary), *args]
            master = slave = None
            proc = None
            stopped = threading.Event()
            chunks: queue.Queue = queue.Queue()
            replies: queue.Queue = queue.Queue()
            secrets = [password] if password else []
            feed = iter(stdin_lines or [])
            lines: list[str] = []
            pending = ""
            auth_pending = False
            auth_thread = None
            decoder = codecs.getincrementaldecoder("utf-8")("replace")

            def redact(text):
                text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
                for secret in secrets:
                    text = text.replace(secret, "[redacted]")
                return text

            def publish(text):
                text = redact(text).strip()
                if text:
                    lines.append(text)
                    if len(lines) > 2000:
                        del lines[:1000]
                    if on_line:
                        try:
                            on_line(text)
                        except Exception:
                            pass

            def answer(kind, prompt):
                try:
                    value = on_auth(kind, redact(prompt), stopped) if on_auth else None
                    replies.put((kind, value))
                except Exception as exc:
                    replies.put((kind, exc))

            try:
                if os.name != "nt":
                    import pty
                    import termios

                    master, slave = pty.openpty()
                    attrs = termios.tcgetattr(slave)
                    attrs[3] &= ~termios.ECHO
                    termios.tcsetattr(slave, termios.TCSANOW, attrs)
                    proc = subprocess.Popen(
                        cmd,
                        stdin=slave,
                        stdout=slave,
                        stderr=slave,
                        cwd=self.install_dir,
                        start_new_session=True,
                        env={**os.environ, "TERM": "dumb"},
                    )
                    os.close(slave)
                    slave = None
                    read_fd = master

                    def write_input(value):
                        os.write(master, (value + "\n").encode())
                else:  # pragma: no cover
                    proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        cwd=self.install_dir,
                    )
                    read_fd = proc.stdout.fileno()

                    def write_input(value):
                        proc.stdin.write((value + "\n").encode())
                        proc.stdin.flush()

                def read_output():
                    try:
                        while not stopped.is_set():
                            data = os.read(read_fd, 4096)
                            if not data:
                                break
                            chunks.put(data)
                    except OSError:
                        pass  # PTYs report EIO at EOF
                    finally:
                        chunks.put(None)

                reader = threading.Thread(target=read_output, daemon=True, name="osw-output")
                reader.start()
                started = last_output = time.monotonic()
                deadline = started + timeout if timeout is not None else None
                while True:
                    self._check_cancel(cancel)
                    now = time.monotonic()
                    if deadline is not None and now >= deadline:
                        raise SteamCMDError("SteamCMD timed out", "timeout")
                    if (
                        inactivity_timeout is not None
                        and not auth_pending
                        and now - last_output >= inactivity_timeout
                    ):
                        seconds = int(inactivity_timeout)
                        raise SteamCMDError(
                            f"SteamCMD stopped responding (no output for {seconds} seconds)",
                            "timeout",
                        )
                    if auth_pending:
                        try:
                            kind, value = replies.get_nowait()
                        except queue.Empty:
                            pass
                        else:
                            auth_pending = False
                            if isinstance(value, Exception):
                                raise SteamCMDError(
                                    "Authentication input failed", "authentication"
                                ) from value
                            if value is None:
                                raise SteamCMDError("Authentication cancelled", "authentication")
                            if kind != "approval":
                                if any(c in value for c in ("\r", "\n", "\0")):
                                    raise SteamCMDError(
                                        "Invalid authentication input", "authentication"
                                    )
                                secrets.append(value)
                                write_input(value)
                                last_output = time.monotonic()
                    try:
                        chunk = chunks.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if chunk is None:
                        break
                    last_output = time.monotonic()
                    pending += decoder.decode(chunk)
                    # Detect prompts before splitting: Steam Guard prompts may end with a newline.
                    tail = pending[-1500:]
                    kind = None
                    if re.search(r"(?:password|pass phrase)[^\r\n:]*:\s*$", tail, re.I):
                        kind = "password"
                    elif re.search(
                        r"(?:guard|authenticator|two.factor|email|enter)[^\r\n]*code[^\r\n]*[:>]\s*$",
                        tail,
                        re.I,
                    ):
                        kind = "guard"
                    elif re.search(
                        r"(?:confirm.*(?:mobile|steam app)|waiting for.*confirmation|approve.*sign.in)",
                        tail,
                        re.I,
                    ):
                        kind = "approval"
                    if kind and not auth_pending:
                        publish(pending)
                        pending = ""
                        supplied = password if kind == "password" else ""
                        password = ""  # rejected passwords must be requested again
                        if not supplied and kind != "approval":
                            supplied = next(feed, "")
                        if supplied:
                            if any(c in supplied for c in ("\r", "\n", "\0")):
                                raise SteamCMDError(
                                    "Invalid authentication input", "authentication"
                                )
                            secrets.append(supplied)
                            write_input(supplied)
                            last_output = time.monotonic()
                        elif on_auth:
                            auth_pending = True
                            auth_thread = threading.Thread(
                                target=answer, args=(kind, tail), daemon=True, name="osw-auth"
                            )
                            auth_thread.start()
                        else:
                            raise SteamCMDError(
                                "Steam requires account authentication; use an interactive login",
                                "authentication",
                            )
                    else:
                        parts = re.split(r"[\r\n]", pending)
                        pending = parts.pop()
                        for part in parts:
                            publish(part)
                        # Bound an unterminated output line, retaining enough text for prompt detection.
                        if len(pending) > 8192:
                            publish(pending[:-1500])
                            pending = pending[-1500:]
                publish(pending + decoder.decode(b"", final=True))
                remaining = (
                    max(0.01, deadline - time.monotonic())
                    if deadline is not None
                    else inactivity_timeout or 30.0
                )
                try:
                    returncode = proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired as exc:
                    raise SteamCMDError("SteamCMD timed out", "timeout") from exc
                if returncode:
                    output = "\n".join(lines[-20:])
                    raise SteamCMDError(
                        f"SteamCMD exited with status {returncode}:\n{output}",
                        failure_kind(output) if failure_kind(output) != "unknown" else "runtime",
                    )
                return lines
            finally:
                stopped.set()
                if auth_thread is not None:
                    auth_thread.join(timeout=0.2)
                if proc is not None:
                    if os.name != "nt":
                        try:
                            os.killpg(proc.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    elif proc.poll() is None:  # pragma: no cover
                        proc.terminate()
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    if os.name != "nt":
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    for stream in (proc.stdin, proc.stdout):
                        if stream:
                            stream.close()
                for descriptor in (slave, master):
                    if descriptor is not None:
                        os.close(descriptor)

    def download_item(
        self,
        appid: int,
        fileid: int,
        content_root: Path,
        login="anonymous",
        password="",
        retries=3,
        on_line=None,
        on_progress=None,
        *,
        cancel=None,
        on_auth=None,
        on_attempt=None,
    ) -> Path:
        if appid <= 0 or fileid <= 0:
            raise ValueError("App and Workshop IDs must be positive integers")
        root = Path(content_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        login = login or "anonymous"
        if any(c in login for c in ("\r", "\n", "\0")) or login.startswith("+"):
            raise ValueError("Invalid Steam username")
        args = [
            "+force_install_dir",
            str(root),
            "+login",
            login,
            "+workshop_download_item",
            str(appid),
            str(fileid),
            "+quit",
        ]
        with self.workspace(cancel):
            for attempt in range(1, max(1, retries) + 1):
                self._check_cancel(cancel)
                if on_attempt:
                    on_attempt(attempt)

                def pump(line):
                    if on_line:
                        on_line(line)
                    match = re.search(r"progress:\s*(\d+(?:\.\d+)?)", line, re.I)
                    if match and on_progress:
                        on_progress(min(100.0, float(match.group(1))))

                try:
                    # A normal Workshop download already verifies its depot metadata. Full
                    # validation is substantially slower, so reserve it for recovery attempts.
                    attempt_args = list(args)
                    if attempt > 1:
                        attempt_args.insert(-1, "validate")
                    lines = self._run(
                        attempt_args,
                        on_line=pump,
                        timeout=7200,
                        inactivity_timeout=300,
                        cancel=cancel,
                        on_auth=on_auth,
                        password=password,
                    )
                    joined = "\n".join(lines)
                    errors = re.search(
                        r"ERROR!|failed to download|download item .*failed", joined, re.I
                    )
                    # The command's item-specific success is mandatory; old files are insufficient.
                    success = re.search(
                        rf"Success\.\s*(?:Downloaded item|Item)\s+{fileid}\b", joined, re.I
                    )
                    if success and not errors:
                        paths = []
                        reported = re.search(
                            rf'Downloaded item\s+{fileid}\s+to\s+["\'](.+?)["\']', joined, re.I
                        )
                        if reported:
                            paths.append(Path(reported.group(1)))
                        paths += [
                            root / "steamapps/workshop/content" / str(appid) / str(fileid),
                            self.install_dir
                            / "steamapps/workshop/content"
                            / str(appid)
                            / str(fileid),
                        ]
                        for path in paths:
                            if (
                                path.name == str(fileid)
                                and path.parent.name == str(appid)
                                and self._has_files(path)
                            ):
                                self._check_cancel(cancel)
                                expected = (
                                    root / "steamapps/workshop/content" / str(appid) / str(fileid)
                                )
                                return self._publish_download(path.resolve(), expected, cancel)
                    kind = failure_kind(joined)
                    raise SteamCMDError(_friendly_failure(appid, fileid, "", lines), kind)
                except SteamCMDError as exc:
                    if exc.kind not in ("timeout", "network", "unknown") or attempt >= max(
                        1, retries
                    ):
                        raise
                    if on_line:
                        on_line(
                            f"Retrying item {fileid} after {exc.kind} failure ({attempt}/{retries})"
                        )
                    if (cancel or threading.Event()).wait(1.5 * attempt):
                        raise DownloadCancelled() from exc
        raise AssertionError("unreachable")

    def _publish_download(self, actual: Path, expected: Path, cancel=None) -> Path:
        """SteamCMD sometimes ignores force_install_dir for Workshop content."""
        if actual == expected.resolve():
            return actual
        expected.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".osw-{expected.name}-", dir=expected.parent
        ) as folder:
            staging = Path(folder) / "content"
            previous = Path(folder) / "previous"

            def copy_file(source, destination):
                self._check_cancel(cancel)
                with open(source, "rb") as incoming, open(destination, "wb") as outgoing:
                    while chunk := incoming.read(1024 * 1024):
                        self._check_cancel(cancel)
                        outgoing.write(chunk)
                shutil.copystat(source, destination)
                return destination

            shutil.copytree(actual, staging, copy_function=copy_file)
            self._check_cancel(cancel)
            had_previous = expected.exists() or expected.is_symlink()
            if had_previous:
                os.replace(expected, previous)
            try:
                os.replace(staging, expected)
            except OSError:
                if had_previous:
                    os.replace(previous, expected)
                raise
        return expected.resolve()

    @staticmethod
    def _has_files(path: Path) -> bool:
        return path.is_dir() and any(p.is_file() for p in path.rglob("*"))

    def item_downloaded(self, appid, fileid, content_root):
        return self._has_files(
            Path(content_root) / "steamapps/workshop/content" / str(appid) / str(fileid)
        )

    def check_login(self, username, password="", guard="", on_auth=None, cancel=None):
        self.ensure_installed(cancel=cancel)
        lines = self._run(
            ["+login", username, "+quit"],
            password=password,
            stdin_lines=[guard] if guard else [],
            on_auth=on_auth,
            cancel=cancel,
            timeout=120,
        )
        return bool(re.search(r"Logged in OK|Waiting for user info.*OK", "\n".join(lines), re.I))


def _friendly_failure(appid, fileid, last_err, lines):
    joined = "\n".join(lines[-20:])
    kind = failure_kind(joined)
    if kind == "access":
        return (
            f"Steam denied access to Workshop item {fileid} for app {appid}. "
            "Anonymous access is controlled by this game's publisher. "
            "You can retry with a Steam account that has access.\n" + joined[-1500:]
        )
    return f"SteamCMD could not verify item {fileid} ({kind}).\n" + (last_err or joined[-2000:])
