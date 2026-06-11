from __future__ import annotations

import os
import struct
import logging
from pathlib import Path
from typing import Iterator, Protocol

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .chain import Block

# 4-byte big-endian length prefix on every WAL record.
_LEN_STRUCT = struct.Struct(">I")
_WAL_FILENAME = "chain.wal"
_WAL_TMP = "chain.wal.tmp"

logger = logging.getLogger(__name__)

class BlockStorage(Protocol):
    """
    Minimal storage interface that Blockchain depends on.
    """

    def load(self) -> list[bytes]:
        """Return all stored blocks in ascending height order."""
        ...

    def append(self, block: bytes) -> None:
        """Durably store a newly confirmed block."""
        ...

    def replace_all(self, blocks: list[bytes]) -> None:
        """
        Replace the entire stored chain with `blocks` (for fork switches).

        `blocks` is in ascending height order.
        """
        ...


class InMemoryStorage(BlockStorage):
    """
    Volatile storage backed by a list. No I/O.
    """

    def __init__(self) -> None:
        self._blocks: list[bytes] = []

    def load(self) -> list[bytes]:
        return list(self._blocks)

    def append(self, block: bytes) -> None:
        self._blocks.append(block)

    def replace_all(self, blocks: list[bytes]) -> None:
        self._blocks = list(blocks)


class WALStorage(BlockStorage):
    """
    Crash-safe storage using a Write-Ahead Log.

    directory:
        Path to the directory where chain.wal will be created.
        Created if it does not exist.
    compact_every:
        Compact the WAL after this many appended records.
        Lower values keep file size small; higher values reduce fsync calls.
        Default is 50.
    """

    def __init__(self, directory: str | Path, compact_every: int = 50) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

        self._wal_path = self._dir / _WAL_FILENAME
        self._tmp_path = self._dir / _WAL_TMP
        self._compact_every = compact_every
        self._appends_since_compact = 0

    def load(self) -> list[bytes]:
        """
        Replay the WAL and return all blocks in height order.
        Stops at the first truncated record (partial writes at the tail are silently discarded).
        There could be blocks with duplicate heights, this should be handled by the consumer.
        """
        if not self._wal_path.exists():
            logger.info("Loading WAL storage, but path did not exist. Returning empty list.")
            return []

        return list(self._replay(self._wal_path))

    def append(self, block: bytes) -> None:
        """Append a single block record to the WAL."""
        with open(self._wal_path, "ab") as fh:
            fh.write(_LEN_STRUCT.pack(len(block)))
            fh.write(block)
            fh.flush()
            os.fsync(fh.fileno())

        self._appends_since_compact += 1
        if self._appends_since_compact >= self._compact_every:
            self._compact()

    def replace_all(self, blocks: list[bytes]) -> None:
        """
        Rewrite the WAL with only the given blocks.

        Used for fork switches. Atomic: we write to a temp file first,
        then rename over the live WAL.
        """
        self._write_wal(self._tmp_path, blocks)
        os.replace(self._tmp_path, self._wal_path)
        self._appends_since_compact = 0

    def _replay(self, path: Path) -> Iterator[bytes]:
        """
        Yield blocks by reading length-prefixed records from `path`.

        Stops cleanly on a truncated record rather than raising.
        """
        with open(path, "rb") as fh:
            while True:
                length_bytes = fh.read(_LEN_STRUCT.size)
                if len(length_bytes) < _LEN_STRUCT.size:
                    # EOF or truncated length field - stop here.
                    logger.debug(f"EOF or truncated length field, for path: {path}")
                    break

                (length,) = _LEN_STRUCT.unpack(length_bytes)
                data = fh.read(length)
                if len(data) < length:
                    # Truncated record body - discard and stop.
                    logger.debug(f"Truncated record body, for path: {path}")
                    break

                try:
                    yield data
                except Exception as e:
                    # Corrupted record - stop rather than skipping,
                    # so we don't silently lose a gap in the chain.
                    logger.debug(f"Corrupted Record, for path: {path}: {repr(e)}")
                    break

    def _write_wal(self, path: Path, blocks: list[bytes]) -> None:
        """Write all blocks to `path` as a fresh WAL (no prior content)."""
        with open(path, "wb") as fh:
            for block in blocks:
                fh.write(_LEN_STRUCT.pack(len(block)))
                fh.write(block)
            fh.flush()
            os.fsync(fh.fileno())

    def _compact(self) -> None:
        """
        Rewrite the WAL to contain only one record per height.

        Called automatically after `compact_every` appends. Also callable
        manually (e.g. on clean shutdown).
        """
        blocks = self.load()
        self._write_wal(self._tmp_path, blocks)
        os.replace(self._tmp_path, self._wal_path)
        self._appends_since_compact = 0

    def compact(self) -> None:
        """Public API for explicit compaction (e.g. on clean shutdown)."""
        self._compact()