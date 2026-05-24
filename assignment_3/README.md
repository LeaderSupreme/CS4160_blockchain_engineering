# Lab 3

## Possible upgrades

- Dynamic difficulty
- Merkle tree for `txs_hash`
- Transaction fees / Coinbase
- Persistent chain?
- More intelligent way to keep track of forks (tree?)
- Dependency tracking in Mempool for order of mining
- Multi threaded mining, each thread can get his own nonce range
- enable sharing the mempool, so if you submit one transaction to a node, all others also get it

## Run tests

To run all tests:

```bash
uv run pytest assignment_3/tests -v
```
