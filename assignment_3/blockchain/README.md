# `blockchain/` — core chain logic

Pure blockchain primitives with **no networking**. Everything here is unit-tested in
[`../test/`](../test/) and consumed by [`../network/blockchain_community.py`](../network/blockchain_community.py).

| Module | Contents |
|---|---|
| `crypto.py` | header (de)serialization, SHA-256 hashing, PoW search |
| `chain.py` | `Transaction`, `Block`, `Blockchain` (the fork tree), `AddResult` |
| `difficulty.py` | `DifficultyPolicy` protocol + `Fixed` / `Dynamic` implementations |
| `mempool.py` | `Mempool` — pending transactions with priority eviction |
| `miner.py` | `Miner` — thread-safe, multi-threaded nonce search |
| `storage.py` | `BlockStorage` protocol + `InMemoryStorage` / `WALStorage` |

## `crypto.py`

Wire-level formats and the PoW primitive — the part that must match the server byte-for-byte.

- **Header (84 bytes)**, packed big-endian as `>32s32sQIQ`:
  `prev_hash(32) | txs_hash(32) | timestamp(u64) | difficulty(u32) | nonce(u64)`.
  `block_hash = SHA256(header)`.
- `tx_hash = SHA256(sender_key || data || timestamp_8be || signature)`.
- `txs_hash = SHA256(tx_hash_1 || … || tx_hash_n)`; an **empty** block uses
  `SHA256(b"")`, *not* 32 zero bytes.
- `count_leading_zero_bits` uses a precomputed table; `satisfies_pow` checks the hash has
  ≥ `difficulty` leading zero bits.
- `mine_block(...)` iterates nonces over `[start, start+count)` with a `step` (so threads
  can interleave) and returns `(nonce, block_hash)` or `(None, None)`.

## `chain.py`

- `Transaction` / `Block` — frozen dataclasses with msgpack (de)serialization for storage.
  A `Block` validates itself: `verify_header` (hash + PoW), `verify_txs_hash` (body
  commitment). Header-only blocks (synced from peers, bodies not yet fetched) pass on the
  header alone — see the `has_body` property.
- `make_genesis_block(...)` — deterministic, hardcoded genesis so all three nodes agree on
  block 0. `lru_cache`d.
- `Blockchain` — a **block tree**, not a list:
  - all connected blocks live in `_blocks` (keyed by hash); the main chain is materialized
    in `_chain` (height → block) for O(1) height lookups.
  - `add_block` validates, then extends / reorgs / parks-as-orphan, returning an
    `AddResult` so the caller can reconcile mempool and miner.
  - **Best-tip rule** (`_chain_score`): taller wins; on a height tie the **smaller block
    hash** wins. Deterministic across nodes → forks converge.
  - **Orphans**: blocks whose parent is unknown are parked (bounded pool to prevent a
    memory-exhaustion DoS) and adopted recursively when the parent connects.

## `difficulty.py`

`DifficultyPolicy` protocol with `get_difficulty(tip) -> int`.

- `FixedDifficultyPolicy` — constant difficulty (used in production).
- `DynamicDifficultyPolicy` — adjusts via an **EMA** of observed block times toward
  `TARGET_BLOCK_TIME_S`, clamped per step (`MAX_ADJUSTMENT`) and overall
  (`MIN/MAX_DIFFICULTY`). Also clamps incoming block timestamps. Stateful — one instance
  per chain.

> Production uses Fixed: difficulty is in *bits*, but work is exponential in bits, so a few
> fast blocks can push it to an unmineable value and freeze the tip.

## `mempool.py`

`Mempool` — ordered dict of pending transactions, capped at `max_size`. A pluggable
`key_fn` defines priority (default FIFO by timestamp; fee or fee/byte also work). When
full, the lowest-priority transaction is evicted only if the newcomer outranks it.

## `miner.py`

`Miner` — runs `num_threads` (default 4) daemon worker threads, all mining the **same
tip** over interleaved nonce ranges (`nonce = worker_id`, `step = num_threads`).

- First worker to find a block claims it (`_found`), emits it via `on_block_mined`, and
  clears `_resume` so all workers pause — no busy-spin, no duplicate blocks.
- `mine(tip)` bumps a generation counter and resumes workers on the new tip; always called
  after a block lands (self-mined or synced) so the pause never deadlocks.
- Mines even with an empty mempool, since the chain must keep growing to bury the test
  transaction under ≥3 confirmations.

## `storage.py`

`BlockStorage` protocol: `load()`, `append(block)`, `replace_all(blocks)`.

- `InMemoryStorage` — volatile list, no I/O (used in tests).
- `WALStorage` — crash-safe **Write-Ahead Log**:
  - each record is a 4-byte big-endian length prefix + block bytes, `flush`+`fsync`'d.
  - `load()` replays the log and stops cleanly at the first truncated/corrupt record
    (partial tail writes are discarded, not fatal).
  - `replace_all` (fork switch) writes a temp file then atomically `os.replace`s it.
  - auto-compacts to one record per height every `compact_every` (default 50) appends.
  - only the **main chain** is stored — side forks are not persisted.
