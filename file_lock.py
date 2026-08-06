"""Simple cross-process lock file for live log / shared state writes."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path


class LockTimeout(TimeoutError):
    pass


@contextmanager
def file_lock(target: Path, timeout: float = 8.0, poll: float = 0.05):
    """
    Exclusive lock via sibling `.lock` file.
    Prevents booth+tablet races on full CSV rewrites.
    """
    path = Path(target)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    fd = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
            break
        except FileExistsError:
            # Stale lock: if older than 60s, steal
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > 60:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.time() - start > timeout:
                raise LockTimeout(f"Could not lock {path} within {timeout}s")
            time.sleep(poll)
    try:
        yield
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
