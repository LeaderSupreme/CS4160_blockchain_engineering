import time
import pytest

from ..chain import Block, Blockchain, Transaction, make_genesis_block
from ..crypto import compute_txs_hash, hash_transaction, mine_block, sha256

def make_valid_block(chain: Blockchain, difficulty: int = 4) -> Block:
    """Helper method to make a valid (empty) block"""
    tip = chain.tip
    txs_hash = compute_txs_hash([])
    ts = int(time.time())
    nonce, block_hash = mine_block(tip.block_hash, txs_hash, ts, difficulty)

    return Block(
        height=tip.height + 1,
        prev_hash=tip.block_hash,
        txs_hash=txs_hash,
        timestamp=ts,
        difficulty=difficulty,
        nonce=nonce,
        block_hash=block_hash,
        transactions=(),
    )


# --------------------------------------
# Genesis (test invariants)
# --------------------------------------
def test_genesis_height_zero():
    genesis = make_genesis_block()
    assert genesis.height == 0

def test_genesis_prev_hash_zero():
    genesis = make_genesis_block()
    assert genesis.prev_hash == b"\x00" * 32

def test_genesis_txs_hash_empty():
    genesis = make_genesis_block()
    assert genesis.txs_hash == sha256(b"")

def test_genesis_deterministic():
    """Genesis block should always be the same"""
    genesis = make_genesis_block()
    genesis = make_genesis_block()
    assert genesis.block_hash == genesis.block_hash


# --------------------------------------
# Block validation
# --------------------------------------
def test_block_verify_pow_valid():
    chain = Blockchain(make_genesis_block())
    block = make_valid_block(chain)
    assert block.verify_pow()

def test_block_verify_pow_wrong_hash():
    """Make sure pow fails, with a bad block hash"""
    chain = Blockchain(make_genesis_block())
    block = make_valid_block(chain)
    bad_block = Block(
        height=block.height,
        prev_hash=block.prev_hash,
        txs_hash=block.txs_hash,
        timestamp=block.timestamp,
        difficulty=block.difficulty,
        nonce=block.nonce,
        block_hash=b"\xff" * 32,
        transactions=(),
    )
    assert not bad_block.verify_pow()

def test_block_verify_txs_hash_empty():
    """Check that an empty block has correct txs hash"""
    chain = Blockchain(make_genesis_block())
    block = make_valid_block(chain)
    assert block.verify_txs_hash()

def test_block_verify_txs_hash_with_tx():
    """Check if hashses are also correct, when transaction sare non empty"""
    tx_hash = hash_transaction(b"key", b"data", 1234, b"sig")
    txs_hash = compute_txs_hash([tx_hash])
    tip = make_genesis_block()
    ts = int(time.time())
    nonce, block_hash = mine_block(tip.block_hash, txs_hash, ts, 4)

    tx = Transaction(
        sender_key=b"key",
        data=b"data",
        timestamp=1000,
        signature=b"sig",
        tx_hash=tx_hash,
    )
    block = Block(
        height=1,
        prev_hash=tip.block_hash,
        txs_hash=txs_hash,
        timestamp=ts,
        difficulty=4,
        nonce=nonce,
        block_hash=block_hash,
        transactions=(tx,),
    )
    assert block.verify_txs_hash()


# --------------------------------------
# Blockchain
# --------------------------------------
def test_add_block_extends_chain():
    """Check if we can correctly add a valid block to the chain"""
    chain = Blockchain(make_genesis_block())
    block = make_valid_block(chain)
    assert chain.add_block(block)
    assert chain.height == 1
    assert chain.tip == block

def test_add_block_wrong_height_rejected():
    """Check that a block with the wrong height is rejected, and chain is not updated"""
    chain = Blockchain(make_genesis_block())
    tip = chain.tip
    block = make_valid_block(chain)
    bad_block = Block(
        height=2,
        prev_hash=block.prev_hash,
        txs_hash=block.txs_hash,
        timestamp=block.timestamp,
        difficulty=block.difficulty,
        nonce=block.nonce,
        block_hash=block.block_hash,
        transactions=(),
    )
    assert not chain.add_block(bad_block)
    assert chain.height == 0
    assert chain.tip == tip

def test_add_block_wrong_prev_hash_rejected():
    """Check block is rejected if prev_hash is wrong"""
    chain = Blockchain(make_genesis_block())
    tip = chain.tip
    txs_hash = sha256(b"")
    ts = int(time.time())
    bad_prev = b"\xaa" * 32  
    nonce, block_hash = mine_block(bad_prev, txs_hash, ts, 4)
    block = Block(
        height=1,
        prev_hash=bad_prev,
        txs_hash=txs_hash,
        timestamp=ts,
        difficulty=4,
        nonce=nonce,
        block_hash=block_hash,
        transactions=(),
    )
    assert not chain.add_block(block)

def test_chain_get_block():
    chain = Blockchain(make_genesis_block())
    assert chain.get_block(0) is not None
    assert chain.get_block(1) is None

def test_fork_switch_longer_chain_wins():
    """Test if switching forks goes as planned when fork is longer"""
    chain = Blockchain(make_genesis_block())
    b1 = make_valid_block(chain)
    chain.add_block(b1)

    # build a competing fork, that split from genesis
    genesis = chain.get_block(0)
    assert genesis
    fork_chain = Blockchain(genesis)
    f1 = make_valid_block(fork_chain)
    fork_chain.add_block(f1)
    f2 = make_valid_block(fork_chain)
    fork_chain.add_block(f2)

    # forked chain is height 2, orignal 1. they should switch
    switched = chain.try_fork_switch([f1, f2])
    assert switched
    assert chain.height == 2
    assert chain._forks[genesis.block_hash]
    assert len(chain._forks[genesis.block_hash]) == 1 

def test_fork_switch_shorter_chain_ignored():
    """Test that if fork is shorter than current chain, we dont swap"""
    chain = Blockchain(make_genesis_block())
    b1 = make_valid_block(chain)
    chain.add_block(b1)
    b2 = make_valid_block(chain)
    chain.add_block(b2)

    # forked chain with lenght 1
    genesis = chain.get_block(0)
    assert genesis
    fork_chain = Blockchain(genesis)
    f1 = make_valid_block(fork_chain)
    fork_chain.add_block(f1)

    switched = chain.try_fork_switch([f1])
    assert not switched
    assert chain.height == 2