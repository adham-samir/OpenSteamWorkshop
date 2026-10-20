"""SteamCMD binary management and Workshop download wrapper.

Downloads Valve's official client on first use (linux: steamcmd_linux.tar.gz
under our own data dir) and drives it via subprocess, parsing its output for
progress. Downloads are validated by checking the files on disk, NOT the exit
code — steamcmd sometimes exits 0 after a failed item download.
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Callable

from .net import NetError, http

STEAMCMD_URL_LINUX = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
STEAMCMD_URL_WIN = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "OpenSteamWorkshop"


class SteamCMDError(RuntimeError):
    pass


class SteamCMD:
    def __init__(self, install_dir: Path | str | None = None):
        self.install_dir = Path(install_dir) if install_dir else DEFAULT_DATA_DIR / "steamcmd"
        if platform.system() == "Windows":
            self._binary = self.install_dir / "steamcmd.exe"
            self._url = STEAMCMD_URL_WIN
            self._archive = "zip"
        else:
            self._binary = self.install_dir / "steamcmd.sh"
            self._url = STEAMCMD_URL_LINUX
            self._archive = "tar.gz"

    # ------------------------------------------------------------- install

    @property
    def installed(self) -> bool:
        return self._binary.is_file()

    def ensure_installed(self, log: Callable[[str], None] | None = None) -> Path:
        if self.installed:
            return self._binary
        self.install_dir.mkdir(parents=True, exist_ok=True)
        if log:
            log(f"Downloading SteamCMD from {self._url} ...")
        data = http.request(self._url)
        archive = self.install_dir / f"steamcmd.{self._archive}"
        archive.write_bytes(data)
        if log:
            log("Extracting ...")
        if self._archive == "tar.gz":
            with tarfile.open(archive) as tar:
                # 32-bit binaries shipped; keep permissions
                tar.extractall(self.install_dir, filter="data") if sys.version_info >= (3, 12) \
                    else tar.extractall(self.install_dir)
        else:  # zip
            import zipfile

            with zipfile.ZipFile(archive) as z:
                z.extractall(self.install_dir)
        archive.unlink(missing_ok=True)
        self._binary.chmod(0o755)
        self.verify_works(log)
        return self._binary

    LIB_HINT_URL = "https://github.com/ValveSoftware/steam-for-linux/wiki/lib32gcc-s1"

    def verify_works(self, log: Callable[[str], None] | None = None) -> None:
        """Run a harmless command to surface missing 32-bit libs early."""
        lines: list[str] = []
        try:
            self._run(["+quit"], on_line=lines.append)
        except FileNotFoundError as e:
            raise SteamCMDError(f"cannot run steamcmd: {e}") from e
        joined = "\n".join(lines)
        if re.search(
            r"error while loading shared libraries|cannot execute|Version mismatch|startupdlls",
            joined,
            re.I,
        ):
            raise SteamCMDError(
                "SteamCMD failed to start, almost always due to missing 32-bit runtime"
                " libraries. On Debian/Ubuntu install lib32gcc-s1:\n"
                "    sudo apt install lib32gcc-s1\n"
                "See: " + self.LIB_HINT_URL
            )

    # ---------------------------------------------------------------- core

    def _run(
        self,
        args: list[str],
        on_line: Callable[[str], None] | None = None,
        stdin_lines: list[str] | None = None,
        timeout: float = 600.0,
    ) -> list[str]:
        cmd = [str(self._binary), *args]
        if sys.platform != "win32":
            import os

            env = {**os.environ, "TERM": "xterm"}
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if stdin_lines is not None else subprocess.DEVNULL,
                text=True,
                bufsize=1,
                cwd=str(self.install_dir),
                env=env,
            )
        else:  # pragma: no cover
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if stdin_lines is not None else subprocess.DEVNULL,
                text=True,
                bufsize=1,
                cwd=str(self.install_dir),
            )

        lines: list[str] = []
        assert proc.stdout is not None
        deadline = time.monotonic() + timeout
        stdin_iter = iter(stdin_lines or [])
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            line = line.rstrip("\r\n")
            lines.append(line)
            if on_line:
                try:
                    on_line(line)
                except Exception:  # never let a UI callback kill the reader
                    pass
            if line.endswith("code:") or "Steam Guard" in line or "two-factor" in line.lower():
                # interactive auth requested; feed next stdin line
                try:
                    to_send = next(stdin_iter) + "\n"
                    proc.stdin.write(to_send)
                    proc.stdin.flush()
                except StopIteration:
                    pass
            if time.monotonic() > deadline:
                proc.kill()
                raise SteamCMDError("steamcmd timed out")
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        proc.wait(timeout=30)
        return lines

    # ----------------------------------------------------------- downloads

    def download_item(
        self,
        appid: int,
        fileid: int,
        content_root: Path,
        login: str = "anonymous",
        password: str = "",
        retries: int = 3,
        on_line: Callable[[str], None] | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> Path:
        """Download workshop item; return destination directory (verified)."""
        content_root = Path(content_root)
        app_dir = content_root / "steamapps" / "workshop" / "content" / str(appid)
        item_dir = app_dir / str(fileid)

        args = ["+force_install_dir", str(content_root)]
        if login and login != "anonymous":
            if password:
                args += ["+login", login, password]
            else:
                args += ["+login", login]
        else:
            args += ["+login", "anonymous"]
        args += ["+workshop_download_item", str(appid), str(fileid), "+quit"]

        last_err = ""
        last_lines: list[str] = []
        for attempt in range(1, retries + 1):
            buf: list[str] = []

            def _pump(line: str, buf=buf):
                buf.append(line)
                if on_line:
                    on_line(line)
                m = re.search(r"[Pp]rogress: (\d+(?:\.\d+)?)", line)
                if m and on_progress:
                    on_progress(min(100.0, float(m.group(1))))
                em = re.search(r"ERROR! (.+)", line)
                if em:
                    buf.append("ERR:" + em.group(1))

            stdin_feed: list[str] = []
            self._run(args, on_line=_pump, timeout=1800.0)
            last_lines = buf
            err_lines = [x for x in buf if x.startswith("ERR:")]
            last_err = err_lines[-1][4:] if err_lines else ""

            if self.item_downloaded(appid, fileid, content_root):
                return item_dir
            # steamcmd sometimes silently no-ops the first attempt; retry
            time.sleep(1.5 * attempt)

        raise SteamCMDError(
            _friendly_failure(appid, fileid, last_err, last_lines)
        )

    def item_downloaded(self, appid: int, fileid: int, content_root: Path) -> bool:
        item_dir = Path(content_root) / "steamapps" / "workshop" / "content" / str(appid) / str(fileid)
        if not item_dir.is_dir():
            return False
        try:
            next(item_dir.iterdir())
        except StopIteration:
            return False
        return True

    # -------------------------------------------------------------- login

    def check_login(self, username: str, password: str, guard: str = "") -> bool:
        """Verify credentials can log in (for the GUI settings dialog)."""
        stdin_lines = [password]
        if guard:
            stdin_lines.append(guard)
        lines = self._run(
            ["+login", username, "+quit"],
            stdin_lines=stdin_lines,
            timeout=120,
        )
        joined = "\n".join(lines)
        return "Logged in OK" in joined or "Waiting for user info...OK" in joined


def _friendly_failure(appid: int, fileid: int, last_err: str, lines: list[str]) -> str:
    joined = "\n".join(lines[-40:])
    if "Missing manifest" in joined or "No subscription" in joined or "Failed" in joined and "download item" in joined.lower():
        return (
            f"This account does not own app {appid}, so SteamCMD refuses to"
            " download workshop item"
            f" {fileid}.\nAnonymous downloads only work for free/eligible"
            " apps. Log in with a Steam account that owns the game"
            " (Settings → Steam account)."
        )
    if last_err:
        return f"SteamCMD failed for item {fileid}: {last_err}"
    return f"SteamCMD could not verify download of item {fileid}. Last output:\n" + joined[-500:]
