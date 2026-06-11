# Lab 3

## Run tests

To run all tests:

```bash
uv run pytest assignment_3/test -v
```

## Run the project

```bash
uv run python -m assignment_3/client
```

## Content

```C
assignment_3/
├─ test/                                # test files
│  ├─ test_crypto.py
│  ├─ test_chain.py
│  ├─ test_dynamic_difficulty.py
│  ├─ test_mempool.py
│  ├─ test_storage.py
├─ assignment_3.md                      # description of the assignment
├─ config.py                            
├─ client.py                            # entry point to the program
├─ registering_community.py             # ipv8 community for registering to the server
├─ blockchain_community.py              # ipv8 community with the actual blockchain
├─ peers.py                             # helper for trusted peers
├─ payloads.py                          # all ipv8 payloads
├─ crypto.py                            # crypto helpers
├─ difficulty.py                        # protocol classes for difficultie. `FixedDifficulty` and `DynamicDifficulty`
├─ chain.py                             # main blockchain class contains: `Transaction`, `Block` and `Blockchain`
├─ mempool.py                           # contains the mempool logic
├─ miner.py                             # contains multi threaded mining logic
├─ storage.py                           # contains storage protocols: `InMemoryStorage` and `WALStorage`
```

### Notable features

- (miner.py) Multithreaded mining, we interleave the associated nonce sets (e.g. with 2 sets, one does the even and one the uneven nonces)
- (chain.py) Fork handling
- (difficulty.py) Protocols for difficulty. Including dynamic difficulty based on exponential moving average (EMA).
- (storage.py) Protocols for storage. Including Write Ahead Log (WAL) that saves to file to recover on a crash. We only save the current chain, and not any forks.
