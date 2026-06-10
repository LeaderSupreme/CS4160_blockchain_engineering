import os
import struct
import msgpack
from pathlib import Path
from typing import Iterator, Protocol
from .chain import Block, Transaction

# 4-byte big-endian length prefix on every WAL record.
_LEN_STRUCT = struct.Struct(">I")
_WAL_FILENAME = "chain.wal"
_WAL_TMP = "chain.wal.tmp"


def _dict_to_block(d: dict) -> Block:
    """Deserialise a plain dict back to a Block."""
    # msgpack returns bytes for bytes fields.
    def _b(v) -> bytes:
        return v if isinstance(v, (bytes, bytearray)) else bytes.fromhex(v)

    txs = tuple(
        Transaction(
            sender_key=_b(t["sender_key"]),
            data=_b(t["data"]),
            timestamp=t["timestamp"],
            signature=_b(t["signature"]),
            tx_hash=_b(t["tx_hash"]),
        )
        for t in d.get("transactions", [])
    )
    return Block(
        height=d["height"],
        prev_hash=_b(d["prev_hash"]),
        txs_hash=_b(d["txs_hash"]),
        timestamp=d["timestamp"],
        difficulty=d["difficulty"],
        nonce=d["nonce"],
        block_hash=_b(d["block_hash"]),
        transactions=txs,
    )


def _encode(block: Block) -> bytes:
    d = block.to_dict()
    return msgpack.packb(d, use_bin_type=True) # type: ignore

def _decode(data: bytes) -> Block:
    d =  msgpack.unpackb(data, raw=False)
    return _dict_to_block(d)


class BlockStorage(Protocol):
    """
    Minimal storage interface that Blockchain depends on.
    """

    def load(self) -> list[Block]:
        """Return all stored blocks in ascending height order."""
        ...

    def append(self, block: Block) -> None:
        """Durably store a newly confirmed block."""
        ...

    def replace_all(self, blocks: list[Block]) -> None:
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
        self._blocks: list[Block] = []

    def load(self) -> list[Block]:
        return list(self._blocks)

    def append(self, block: Block) -> None:
        self._blocks.append(block)

    def replace_all(self, blocks: list[Block]) -> None:
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

    def load(self) -> list[Block]:
        """
        Replay the WAL and return all blocks in height order.
        Stops at the first truncated record (partial writes at the tail are silently discarded).
        There could be blocks with duplicate heights, this should be handled by the consumer.
        """
        if not self._wal_path.exists():
            return []

        blocks = list(self._replay(self._wal_path))
        return sorted(blocks, key=lambda b: b.height)

    def append(self, block: Block) -> None:
        """Append a single block record to the WAL."""
        record = _encode(block)
        with open(self._wal_path, "ab") as fh:
            fh.write(_LEN_STRUCT.pack(len(record)))
            fh.write(record)
            fh.flush()
            os.fsync(fh.fileno())

        self._appends_since_compact += 1
        if self._appends_since_compact >= self._compact_every:
            self._compact()

    def replace_all(self, blocks: list[Block]) -> None:
        """
        Rewrite the WAL with only the given blocks.

        Used for fork switches. Atomic: we write to a temp file first,
        then rename over the live WAL.
        """
        self._write_wal(self._tmp_path, blocks)
        os.replace(self._tmp_path, self._wal_path)
        self._appends_since_compact = 0

    def _replay(self, path: Path) -> Iterator[Block]:
        """
        Yield blocks by reading length-prefixed records from `path`.

        Stops cleanly on a truncated record rather than raising.
        """
        with open(path, "rb") as fh:
            while True:
                length_bytes = fh.read(_LEN_STRUCT.size)
                if len(length_bytes) < _LEN_STRUCT.size:
                    # EOF or truncated length field — stop here.
                    break

                (length,) = _LEN_STRUCT.unpack(length_bytes)
                data = fh.read(length)
                if len(data) < length:
                    # Truncated record body — discard and stop.
                    break

                try:
                    yield _decode(data)
                except Exception:
                    # Corrupted record — stop rather than skipping,
                    # so we don't silently lose a gap in the chain.
                    break

    def _write_wal(self, path: Path, blocks: list[Block]) -> None:
        """Write all blocks to `path` as a fresh WAL (no prior content)."""
        with open(path, "wb") as fh:
            for block in blocks:
                record = _encode(block)
                fh.write(_LEN_STRUCT.pack(len(record)))
                fh.write(record)
            fh.flush()
            os.fsync(fh.fileno())

    def _compact(self) -> None:
        """
        Rewrite the WAL to contain only one record per height.

        Called automatically after `compact_every` appends. Also callable
        manually (e.g. on clean shutdown).
        """
        blocks = self.load()     # deduplicated and sorted by load()
        self._write_wal(self._tmp_path, blocks)
        os.replace(self._tmp_path, self._wal_path)
        self._appends_since_compact = 0

    def compact(self) -> None:
        """Public API for explicit compaction (e.g. on clean shutdown)."""
        self._compact()