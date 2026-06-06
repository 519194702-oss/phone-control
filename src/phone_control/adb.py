"""Small ADB wrapper used by the desktop phone-control application."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterable


class AdbError(RuntimeError):
    """Raised when an ADB command fails or produces unusable output."""


@dataclass(frozen=True)
class AndroidDevice:
    """A connected Android device reported by ``adb devices``."""

    serial: str
    state: str
    description: str = ""

    @property
    def is_ready(self) -> bool:
        return self.state == "device"


class AdbClient:
    """Execute ADB commands for one optional Android device serial."""

    def __init__(self, adb_path: str | None = None, serial: str | None = None, timeout: float = 10.0) -> None:
        self.adb_path = adb_path or shutil.which("adb") or "adb"
        self.serial = serial
        self.timeout = timeout

    def with_serial(self, serial: str | None) -> "AdbClient":
        return AdbClient(self.adb_path, serial, self.timeout)

    def _base_command(self) -> list[str]:
        command = [self.adb_path]
        if self.serial:
            command.extend(["-s", self.serial])
        return command

    def run(self, args: Iterable[str], *, timeout: float | None = None, binary: bool = False) -> bytes | str:
        command = self._base_command() + list(args)
        try:
            completed = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout if timeout is None else timeout,
            )
        except FileNotFoundError as exc:
            raise AdbError("adb executable was not found. Install Android platform-tools and add adb to PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"ADB command timed out: {' '.join(command)}") from exc

        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()
            raise AdbError(stderr or f"ADB command failed: {' '.join(command)}")

        if binary:
            return completed.stdout
        return completed.stdout.decode("utf-8", errors="replace")

    def devices(self) -> list[AndroidDevice]:
        output = self.run(["devices", "-l"])
        assert isinstance(output, str)
        devices: list[AndroidDevice] = []
        for line in output.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=2)
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            description = parts[2] if len(parts) > 2 else ""
            devices.append(AndroidDevice(serial=serial, state=state, description=description))
        return devices

    def wait_for_device(self) -> None:
        self.run(["wait-for-device"], timeout=60)

    def screen_png(self) -> bytes:
        data = self.run(["exec-out", "screencap", "-p"], timeout=5, binary=True)
        assert isinstance(data, bytes)
        if not data.startswith(b"\x89PNG"):
            raise AdbError("device did not return a PNG screenshot")
        return data

    def screen_size(self) -> tuple[int, int]:
        output = self.run(["shell", "wm", "size"])
        assert isinstance(output, str)
        match = re.search(r"Physical size:\s*(\d+)x(\d+)", output)
        if not match:
            match = re.search(r"Override size:\s*(\d+)x(\d+)", output)
        if not match:
            raise AdbError(f"could not parse screen size from: {output.strip()}")
        return int(match.group(1)), int(match.group(2))

    def tap(self, x: int, y: int) -> None:
        self.run(["shell", "input", "tap", str(max(0, x)), str(max(0, y))], timeout=3)

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 250) -> None:
        duration = max(1, min(duration_ms, 5000))
        self.run(
            [
                "shell",
                "input",
                "swipe",
                str(max(0, start_x)),
                str(max(0, start_y)),
                str(max(0, end_x)),
                str(max(0, end_y)),
                str(duration),
            ],
            timeout=5,
        )

    def keyevent(self, key_code: int | str) -> None:
        self.run(["shell", "input", "keyevent", str(key_code)], timeout=3)

    def text(self, value: str) -> None:
        payload = encode_input_text(value)
        if payload:
            self.run(["shell", "input", "text", payload], timeout=5)


def encode_input_text(value: str) -> str:
    """Encode text for ``adb shell input text``.

    Android's input command treats ``%s`` as a space and has limited support for
    punctuation. Keeping this conservative makes keyboard forwarding reliable
    across stock Android builds without requiring an on-device helper APK.
    """

    replacements = {
        " ": "%s",
        "\n": "",
        "\r": "",
        "\t": "%s",
        "%": "\\%",
        "&": "\\&",
        "<": "\\<",
        ">": "\\>",
        "|": "\\|",
        ";": "\\;",
        "(": "\\(",
        ")": "\\)",
        "'": "\\'",
        '"': '\\"',
        "\\": "\\\\",
    }
    return "".join(replacements.get(char, char) for char in value).strip()
