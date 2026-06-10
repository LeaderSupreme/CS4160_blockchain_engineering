import logging
from dataclasses import dataclass

from .config import DEFAULT_DIFFICULTY
from .crypto import compute_txs_hash, hash_header, satisfies_pow, sha256

logger = logging.getLogger(__name__)

# --------------------------------------
# Transaction
# --------------------------------------
@dataclass(frozen=True)
class Transaction:
    sender_key: bytes
    data: bytes
    timestamp: int
    signature: bytes
    tx_hash: bytes

    def __repr__(self) -> str:
        return f"<Tx {self.tx_hash.hex()[:12]}...>"


# --------------------------------------
# Block
# --------------------------------------
@dataclass(frozen=True)
class Block:
    block_hash: bytes   # 32 bytes (sha-256 of header)

    # header (84 bytes)
    prev_hash: bytes    # 32 bytes
    txs_hash: bytes     # 32 bytes
    timestamp: int      # unix seconds (8 bytes)
    difficulty: int     # 4 bytes 
    nonce: int          # 8 bytes

    # content
    height: int
    transactions: tuple[Transaction, ...]

    def verify_pow(self) -> bool:
        """Checks if the hash of the header is correct, and satisfies the pow difficulty"""
        expected = hash_header(self.prev_hash, self.txs_hash, self.timestamp, self.difficulty, self.nonce)
        return expected == self.block_hash and satisfies_pow(self.block_hash, self.difficulty)

    def verify_txs_hash(self) -> bool:
        """Checks if the txs_hash is the correct hash of all corresponding transaction hashes"""
        return compute_txs_hash([tx.tx_hash for tx in self.transactions]) == self.txs_hash

    def is_valid(self) -> bool:
        """Check if this is a valid transaction. it is valid when:
            - self.block_hash is a correct hash of all 5 header fields
            - the block hash satisfies the pow difficulty
            - self.txs_hash is the correct hash of all transaction hashes in this block
        """
        return self.verify_pow() and self.verify_txs_hash()

    @property
    def tx_hashes(self) -> list[bytes]:
        """For convenience, make the transaction hashes easy retrievable"""
        return [tx.tx_hash for tx in self.transactions]

    def __repr__(self) -> str:
        return (
            f"<Block h={self.height} hash={self.block_hash.hex()[:8]}... "
            f"nr_txs={len(self.transactions)} difficulty={self.difficulty}, height: {self.height}>"
        )


def make_genesis_block(difficulty: int = DEFAULT_DIFFICULTY) -> Block:
    """The chain needs a genesis block. It needs to be identical on all nodes, so we hardcode it to make it easy.

    genesis block:
      prev_hash  = 32 zero bytes  (doesnt have a parent)
      txs_hash   = SHA256(b"")    (doesnt have any transactions)
      timestamp  = 0              (doesnt have normal timestamp)
      difficulty = DIFFICULTY
      nonce      = 0              (doesnt have a nonce, it doesnt need pow, as it won't be need to be mined)
      height     = 0              (it is the first block of the chain)
    """
    return Block(
        height=0,
        prev_hash=b"\x00" * 32,
        txs_hash=sha256(b""),
        timestamp=0,
        difficulty=difficulty,
        nonce=0,
        block_hash=hash_header(b"\x00" * 32, sha256(b""), 0, difficulty, 0),
        transactions=(),
    )


# --------------------------------------
# Blockchain
# --------------------------------------
class Blockchain:
    """
    The blockchain, the chain is a linear representation of the longest chain. 
    It is a simple dict with {height -> block}.

    If there are forks, we track them in another dict. {split_block_hash -> fork_chain}.
    If an fork would overtake the chain, they should be swapped.
    """

    def __init__(self, genesis: Block) -> None:
        self._chain: dict[int, Block] = {0: genesis}
        self._forks: dict[bytes, list[Block]] = {} 

    @property
    def height(self) -> int:
        """Get the height of the current chain"""
        return max(self._chain.keys())

    @property
    def tip(self) -> Block:
        """Get the current tip of the chain"""
        return self._chain[self.height]

    def get_block(self, height: int) -> Block | None:
        """Get the block on the specified height, None if it doesnt exist"""
        return self._chain.get(height, None)

    def contains(self, block_hash: bytes) -> bool:
        """Checks if the provided block hash is present in the current chain"""
        return any(b.block_hash == block_hash for b in self._chain.values())

    def add_block(self, block: Block) -> bool:
        """Add a block to the current chain. Returns true if the current block is accepted.
        Checks:
          - provided block is valid (pow, hashes)
          - provided block height is correct (current lenght + 1)
          - block.prev_hash is same as chain.tip.block_hash
        """
        if not block.is_valid():
            logger.warning("Rejected invalid block %s", block)
            return False

        expected_height = self.height + 1
        if block.height != expected_height:
            logger.debug(f"Block height mismatch: expected {expected_height} got {block.height}")
            return False

        if block.prev_hash != self.tip.block_hash:
            logger.debug(f"Block prev_hash mismatch, provided prev_hash was not hash of current tip. Height: {block.height}")
            return False

        self._chain[block.height] = block
        logger.info(f"Accepted block {block}")
        return True

    def try_fork_switch(self, incoming_chain: list[Block]) -> bool:
        """
        Longest-chain rule: if `incoming_chain` (ordered from its fork point
        up to its tip) is longer than our current chain, replace ours.

        `incoming_chain` must be a list of consecutive, validated blocks
        starting right after a common ancestor that exists in our chain.

        Returns True if we switched.
        """
        if not incoming_chain:
            return False

        fork_root_height = incoming_chain[0].height - 1  # height where fork split off
        common_ancestor = self.get_block(fork_root_height)
        if common_ancestor is None:
            logger.warning("Fork switch: common ancestor not found")
            return False

        # validate the whole fork chain
        prev = common_ancestor
        for block in incoming_chain:
            if block.prev_hash != prev.block_hash or not block.is_valid():
                logger.warning("Fork switch: invalid block in incoming chain")
                return False
            prev = block

        # check if the fork is longer than our current chain
        # if it isn't longer, we dont need to switch
        incoming_tip = incoming_chain[-1].height
        if incoming_tip <= self.height:
            return False 

        # the fork becomes the chain, and the chain becomes a fork
        old_height = self.height
        old_chain_part = [self._chain[height] for height in range(fork_root_height + 1, old_height + 1)]
        self._forks[common_ancestor.block_hash] = old_chain_part

        for block in incoming_chain:
            self._chain[block.height] = block

        logger.info(f"Switched to fork: new tip {self.tip} (chain was height {old_height}, now is {incoming_tip})")
        return True

    def __repr__(self) -> str:
        return f"<Blockchain height={self.height} tip={self.tip}>"