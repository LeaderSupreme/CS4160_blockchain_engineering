# Lab 3

## Possible upgrades

- Dynamic difficulty - Ruben
- Merkle tree for `txs_hash` - Ruben
- Transaction fees / Coinbase
- Persistent chain?
- Dependency tracking in mempool for order of mining - Ruben
- Multi threaded mining, each thread can get his own nonce range - Ruben
- More intelligent way to keep track of forks (tree?) - Daniel
- Handle orphan nodes better - Daniel
- Enable sharing the mempool, so if you submit one transaction to a node, all others also get it - Faizel
- Periodically syncing chains between nodes - Faizel

## Run tests

To run all tests:

```bash
uv run pytest assignment_3/tests -v
```

## Run the project

```bash
uv run python -m assignment_3/client
```
