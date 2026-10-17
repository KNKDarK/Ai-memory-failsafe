"""Runtime resource detection and adaptive request throttling."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Condition


def _read_int(path: str) -> int | None:
    try:
        value = open(path).read().strip()
    except (OSError, ValueError):
        return None
    if value == "max":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _memory_bytes() -> tuple[int | None, int | None]:
    total = available = None
    try:
        values = {}
        with open("/proc/meminfo") as memory_file:
            for line in memory_file:
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0]) * 1024
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
    except (OSError, ValueError):
        pass

    limit = _read_int("/sys/fs/cgroup/memory.max")
    usage = _read_int("/sys/fs/cgroup/memory.current")
    if limit is not None and (total is None or limit < total):
        total = limit
        available = max(0, limit - usage) if usage is not None else available
    return total, available


def _cpu_count() -> int:
    quota = None
    try:
        quota_text, period_text = open("/sys/fs/cgroup/cpu.max").read().split()
        if quota_text != "max":
            quota = max(1, int(int(quota_text) / int(period_text)))
    except (OSError, ValueError):
        pass
    return max(1, min(os.cpu_count() or 1, quota or os.cpu_count() or 1))


@dataclass(frozen=True)
class ResourceSnapshot:
    cpu_count: int
    cpu_load_1m: float | None
    memory_total_bytes: int | None
    memory_available_bytes: int | None
    gpu_available: bool
    gpu_name: str | None
    gpu_memory_total_bytes: int | None
    gpu_memory_free_bytes: int | None
    recommended_concurrency: int

    def as_dict(self) -> dict:
        return {
            "cpu": {
                "count": self.cpu_count,
                "load_1m": self.cpu_load_1m,
            },
            "memory": {
                "total_bytes": self.memory_total_bytes,
                "available_bytes": self.memory_available_bytes,
            },
            "gpu": {
                "available": self.gpu_available,
                "name": self.gpu_name,
                "memory_total_bytes": self.gpu_memory_total_bytes,
                "memory_free_bytes": self.gpu_memory_free_bytes,
            },
            "recommended_concurrency": self.recommended_concurrency,
        }


def _gpu_info() -> tuple[bool, str | None, int | None, int | None]:
    if shutil.which("nvidia-smi") is None:
        return False, None, None, None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1,
            check=True,
        )
        name, total, free = result.stdout.splitlines()[0].split(", ")
        return True, name, int(float(total) * 1024 * 1024), int(float(free) * 1024 * 1024)
    except (OSError, IndexError, ValueError, subprocess.SubprocessError):
        return False, None, None, None


def detect_resources() -> ResourceSnapshot:
    cpu_count = _cpu_count()
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = None
    memory_total, memory_available = _memory_bytes()
    gpu_available, gpu_name, gpu_total, gpu_free = _gpu_info()

    concurrency = min(4, cpu_count)
    if load is not None and load >= cpu_count:
        concurrency = 1
    elif load is not None and load >= cpu_count * 0.75:
        concurrency = max(1, concurrency // 2)
    if memory_available is not None:
        if memory_available < 512 * 1024 * 1024:
            concurrency = 1
        elif memory_available < 2 * 1024 * 1024 * 1024:
            concurrency = min(concurrency, 2)
    if gpu_available and gpu_free is not None and gpu_free < 1024 * 1024 * 1024:
        concurrency = 1

    return ResourceSnapshot(
        cpu_count=cpu_count,
        cpu_load_1m=load,
        memory_total_bytes=memory_total,
        memory_available_bytes=memory_available,
        gpu_available=gpu_available,
        gpu_name=gpu_name,
        gpu_memory_total_bytes=gpu_total,
        gpu_memory_free_bytes=gpu_free,
        recommended_concurrency=max(1, concurrency),
    )


class AdaptiveConcurrency:
    """Limit active model calls using a fresh resource snapshot per waiter."""

    def __init__(self) -> None:
        self._condition = Condition()
        self._active = 0

    @contextmanager
    def slot(self) -> Iterator[None]:
        with self._condition:
            while self._active >= detect_resources().recommended_concurrency:
                self._condition.wait(timeout=1.0)
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()
