import pytest
import tempfile
from pathlib import Path

from assignment_3.blockchain.storage import InMemoryStorage, WALStorage, _WAL_FILENAME, _LEN_STRUCT
from assignment_3.blockchain.chain import Block 

def make_block(height: int, prev_hash: bytes = b"0") -> Block:
    return Block(
        height=height,
        prev_hash=prev_hash,
        txs_hash=b"x" * 32,
        timestamp=1_000_000 + height,
        difficulty=10,
        nonce=0,
        block_hash=bytes([height % 256]) * 32,
        transactions=(),
    )

class TestInMemoryStorage:
    def test_append_and_load(self):
        s = InMemoryStorage()

        b1 = make_block(0)
        b2 = make_block(1)

        s.append(b1._encode())
        s.append(b2._encode())

        assert [Block._decode(b) for b in s.load()] == [b1, b2]

    def test_replace_all_overwrites(self):
        s = InMemoryStorage()

        b1 = make_block(0)
        b2 = make_block(1)

        s.append(b1._encode())
        s.replace_all([b2._encode()])

        assert [Block._decode(b) for b in s.load()] == [b2]

class TestWALStorageBasic:
    def test_append_and_load_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = WALStorage(tmp, compact_every=10)

            b1 = make_block(0)
            b2 = make_block(1)

            s.append(b1._encode())
            s.append(b2._encode())
            print(list(s._replay(Path(tmp, _WAL_FILENAME))))
            s_loaded = [Block._decode(b) for b in s.load()]
            assert [b.height for b in s_loaded] == [0, 1]

            s2 = WALStorage(tmp)
            s2_loaded = [Block._decode(b) for b in s2.load()]

            assert [b.height for b in s2_loaded] == [0, 1]

             
class TestWALReplaceAll:
    def test_replace_all_overwrites_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = WALStorage(tmp)

            old = [make_block(0), make_block(1)]
            new = [make_block(0), make_block(1), make_block(2)]

            for b in old:
                s.append(b._encode())

            s.replace_all([b._encode() for b in new])

            loaded = [Block._decode(b) for b in WALStorage(tmp).load()]
            assert [b.height for b in loaded] == [0, 1, 2]

class TestWALTruncation:
    def test_truncated_tail_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / _WAL_FILENAME

            b1 = make_block(0)
            b2 = make_block(1)

            # write valid block
            with open(path, "wb") as f:
                data = b1._encode()
                f.write(_LEN_STRUCT.pack(len(data)))
                f.write(data)

                # write partial corrupted second record
                data2 = b2._encode()
                f.write(_LEN_STRUCT.pack(len(data2)))
                f.write(data2[:10])  # truncate intentionally

            s = WALStorage(tmp)
            loaded = [Block._decode(b) for b in s.load()]
            assert [b.height for b in loaded] == [0]

class TestWALCorruption:
    def test_corrupted_record_stops_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chain.wal"

            b1 = make_block(0)

            with open(path, "wb") as f:
                data = b1._encode()
                f.write(_LEN_STRUCT.pack(len(data)))
                f.write(data)

                # inject garbage
                f.write(b"\x00\x00\x00\xff" + b"broken")

            s = WALStorage(tmp)
            loaded = s.load()

            assert len(loaded) == 1

class TestWALCompaction:
    def test_compact_rewrites_clean_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = WALStorage(tmp, compact_every=100)

            blocks = [make_block(i) for i in range(5)]

            for b in blocks:
                s.append(b._encode())

            # force compaction
            s.compact()

            s2 = WALStorage(tmp)
            loaded = [Block._decode(b) for b in s2.load()]
            assert [b.height for b in loaded] == list(range(5))