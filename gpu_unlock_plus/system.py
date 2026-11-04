# SPDX-License-Identifier: GPL-2.0-only
"""Bounded, read-only Linux observations. No shell or privilege escalation."""

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import tempfile

SOURCE_ROOT = Path(__file__).resolve().parent.parent
BDF = re.compile(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-1][0-9a-f]\.[0-7]", re.I)
MAX_READ = 4 * 1024 * 1024


def bdf(value):
    value = value.lower()
    if not BDF.fullmatch(value):
        raise ValueError("Use a full PCI address, for example 0000:01:00.0 (not all).")
    return value


@dataclass
class Observation:
    value: str | None
    error: str | None = None


class System:
    def __init__(self, root=Path("/")):
        self.root = Path(root).resolve()

    def path(self, name):
        return self.root / name.lstrip("/")

    def read(self, name):
        try:
            with self.path(name).open("rb") as stream:
                # proc/sys handlers can reject large single reads with ENOMEM.
                chunks, size = [], 0
                while size <= MAX_READ:
                    block = stream.read(min(4096, MAX_READ + 1 - size))
                    if not block:
                        break
                    chunks.append(block)
                    size += len(block)
                data = b"".join(chunks)
            if len(data) > MAX_READ:
                return Observation(None, "too_large")
            return Observation(data.decode("utf-8", errors="replace").strip())
        except FileNotFoundError:
            return Observation(None, "missing")
        except PermissionError:
            return Observation(None, "permission_denied")
        except OSError:
            return Observation(None, "unreadable")

    def run(self, args):
        if self.root != Path("/"):
            return Observation(None, "not_run_for_fixture_root")
        try:
            # File-backed output bounds RAM even when a command is unexpectedly noisy.
            with tempfile.TemporaryFile() as output:
                result = subprocess.run(args, stdout=output, stderr=subprocess.DEVNULL,
                                        timeout=15, check=False)
                output.seek(0)
                data = output.read(MAX_READ + 1)
            if result.returncode:
                return Observation(None, "command_failed_or_permission_denied")
            if len(data) > MAX_READ:
                return Observation(None, "too_large")
            return Observation(data.decode("utf-8", errors="replace").strip())
        except FileNotFoundError:
            return Observation(None, "command_missing")
        except PermissionError:
            return Observation(None, "permission_denied")
        except subprocess.TimeoutExpired:
            return Observation(None, "timeout")
        except OSError:
            return Observation(None, "command_unavailable")
