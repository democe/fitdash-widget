"""Private, atomic state. Credentials are never stored here."""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


class Busy(Exception):
    pass


class Cache:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)

    def read(self, name, default=None):
        try:
            path = self.directory / name
            if path.stat().st_size > 2_000_000:
                return default
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else default
        except (OSError, ValueError):
            return default

    def write(self, name, data):
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".write-")
        try:
            with os.fdopen(fd, "w") as out:
                json.dump(data, out, ensure_ascii=False, allow_nan=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, self.directory / name)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def remove(self, name):
        (self.directory / name).unlink(missing_ok=True)

    @contextmanager
    def lock(self, name="operation"):
        with open(self.directory / (name + ".lock"), "a", opener=lambda p, f: os.open(p, f, 0o600)) as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Busy() from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def merge_history(self, metrics, day, retention=7):
        """Retain only normalized daily values; backfilled corrections replace old totals."""
        from datetime import timedelta

        history = self.read("history.json", {})
        cutoff = str(day - timedelta(days=retention - 1))
        history = {
            d: values
            for d, values in history.items()
            if isinstance(d, str) and cutoff <= d <= str(day) and isinstance(values, dict)
        }
        for metric in metrics:
            period = metric.get("period", "")
            if metric.get("status") == "available" and cutoff <= period <= str(day):
                history.setdefault(period, {})[metric["key"]] = metric
        self.write("history.json", history)

    def clear_health(self):
        for name in ("snapshot.json", "scheduler.json", "history.json"):
            self.remove(name)
