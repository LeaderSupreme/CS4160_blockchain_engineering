# `wal/` — Write-Ahead-Log chain storage

Runtime persistence for the blockchain. Each node stores its main chain here so it can
recover after a crash or restart instead of re-mining from genesis. Written and read by
`WALStorage` in [`../blockchain/storage.py`](../blockchain/storage.py).

## Layout

```
wal/
└─ <key-stem>/
   ├─ chain.wal        # the append-only Write-Ahead Log
   └─ chain.wal.tmp    # temp file used for atomic replace_all / compaction
```

`client.py` derives the directory from the `--key_path` file stem
(`assignment_3/wal/<stem>`), so several nodes on one machine never share — and clobber — a
WAL. Example: running with `key.pem`, `faizel.pem`, `mykey.pem`, `ruben.pem` gives
`wal/key/`, `wal/faizel/`, `wal/mykey/`, `wal/ruben/`.

## Format

`chain.wal` is a sequence of length-prefixed records, each a 4-byte big-endian length
followed by that many msgpack-encoded `Block` bytes. Every append is `flush`+`fsync`'d.
On boot the log is replayed; truncated or corrupt tail records are discarded cleanly. Fork
switches rewrite the log atomically (write `chain.wal.tmp`, then `os.replace`), and the log
auto-compacts to one record per height. Only the **main chain** is stored — side forks are
not.

## Notes

- `*.wal` and `*.tmp` are **git-ignored** (see the repo `.gitignore`) — these are local
  runtime state, not source. This `README.md` is tracked; the chain data is not.
- Wipe a node's stored chain with `uv run python -m assignment_3.client --start_fresh`,
  which deletes that node's `chain.wal` before booting.
