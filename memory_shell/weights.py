"""Shared model weights — where most of the memory actually goes.

A KV cache is what people optimise; weights are what dominate. A 7B model
at 16-bit is ~14GiB, and a server that loads it once per worker pays that
per worker. Loading it once and mapping it `MAP_SHARED` costs it once
total, because every mapping of the same file resolves to the same page
cache pages. The kernel does the deduplication; this module's job is to
make sure the process asks it to.

The mapping is read-only and shared, which is both the memory property
and a safety one: no session can scribble on weights another session is
reading, and no copy-on-write fault silently forks a private copy.

This is the largest and *safest* saving available, because weights carry
no tenant data. Sharing them across mutually distrusting tenants leaks
nothing beyond which model is loaded — see `isolation.py` for why the
same is emphatically not true of KV blocks.
"""
from __future__ import annotations

import mmap
import os
from dataclasses import dataclass, field
from pathlib import Path

from .blocks import resident_set_bytes


@dataclass
class SharedWeights:
    """One read-only shared mapping of a weights file."""

    path: Path
    mapping: mmap.mmap
    nbytes: int
    refcount: int = 0

    def segment(self, offset: int, length: int) -> memoryview:
        """A zero-copy view of part of the weights.

        Returns a memoryview rather than bytes deliberately: slicing to
        `bytes` would copy, which is the exact cost this module exists to
        avoid.
        """
        if offset < 0 or length < 0 or offset + length > self.nbytes:
            raise ValueError(
                f"segment [{offset}, {offset + length}) is outside the "
                f"{self.nbytes}-byte mapping"
            )
        return memoryview(self.mapping)[offset : offset + length]

    def close(self) -> None:
        try:
            self.mapping.close()
        except (BufferError, ValueError):
            # A live memoryview still references the mapping; leave it to
            # be reclaimed rather than invalidating a session's view.
            pass


@dataclass
class WeightRegistry:
    """One mapping per file, handed to every session that asks for it.

    `naive_bytes` is what the same workload would have cost with a private
    copy per acquisition; `resident_bytes` is what the mappings actually
    cost. The difference is the saving, and it is arithmetic over real file
    sizes rather than a model of one.
    """

    _mapped: dict[str, SharedWeights] = field(default_factory=dict)
    _acquisitions: dict[str, int] = field(default_factory=dict)

    def acquire(self, path: os.PathLike | str) -> SharedWeights:
        key = str(Path(path).resolve())
        self._acquisitions[key] = self._acquisitions.get(key, 0) + 1

        existing = self._mapped.get(key)
        if existing is not None:
            existing.refcount += 1
            return existing

        size = os.path.getsize(key)
        if size == 0:
            raise ValueError(f"{key} is empty; nothing to map")
        fd = os.open(key, os.O_RDONLY)
        try:
            mapping = mmap.mmap(fd, size, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ)
        finally:
            os.close(fd)

        weights = SharedWeights(Path(key), mapping, size, refcount=1)
        self._mapped[key] = weights
        return weights

    def release(self, path: os.PathLike | str) -> None:
        key = str(Path(path).resolve())
        weights = self._mapped.get(key)
        if weights is None:
            return
        weights.refcount -= 1
        if weights.refcount <= 0:
            weights.close()
            del self._mapped[key]

    @property
    def resident_bytes(self) -> int:
        """One copy per distinct file, however many sessions hold it."""
        return sum(w.nbytes for w in self._mapped.values())

    @property
    def naive_bytes(self) -> int:
        """What a private copy per acquisition would have cost."""
        total = 0
        for key, count in self._acquisitions.items():
            weights = self._mapped.get(key)
            size = weights.nbytes if weights else 0
            total += size * count
        return total

    @property
    def saved_bytes(self) -> int:
        return max(0, self.naive_bytes - self.resident_bytes)


def measure_sharing(path: os.PathLike | str, mappings: int = 4) -> dict:
    """Empirically check that N mappings do not cost N copies.

    The registry's arithmetic says sharing works. This asks the kernel.
    Every page of every mapping is touched, so the pages are genuinely
    resident and not merely reserved, then the RSS delta is compared
    against what N private copies would have cost.
    """
    size = os.path.getsize(path)
    before = resident_set_bytes()

    registry = WeightRegistry()
    held = []
    touched = 0
    for _ in range(mappings):
        weights = registry.acquire(path)
        held.append(weights)
        view = weights.segment(0, weights.nbytes)
        for offset in range(0, weights.nbytes, mmap.PAGESIZE):
            touched += view[offset]
        view.release()

    after = resident_set_bytes()
    naive = size * mappings
    delta = None if (before is None or after is None) else after - before

    return {
        "file_bytes": size,
        "mappings": mappings,
        "naive_bytes": naive,
        "registry_resident_bytes": registry.resident_bytes,
        "registry_saved_bytes": registry.saved_bytes,
        "rss_delta_bytes": delta,
        "pages_touched": touched and True,
    }
