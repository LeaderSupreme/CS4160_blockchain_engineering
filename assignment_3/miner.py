import time
import logging
import threading
import crypto

from typing import Callable

from chain import Blockchain, Block, Transaction
from difficulty import DifficultyPolicy
from mempool import Mempool

logger = logging.getLogger(__name__)

class Miner:
    """Mining class that is stateless with respect to the chain.
    It is thread safe, so we can run it as co-routine.
    When it mines a block, the callback is used"""

    def __init__(self, mempool: Mempool, difficulty_policy: DifficultyPolicy, on_block_mined: Callable[[Block], None]) -> None:
        self._mempool = mempool
        self._difficulty_policy = difficulty_policy
        self._on_block_mined = on_block_mined

        self.interrupt = threading.Event()  # Event to stop, for example we have a new tip
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._tip: Block
        self._tip_lock = threading.Lock()

    def start(self) -> None:
        """Start the mining process, or continue if already started"""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._mine_loop, name="miner", daemon=True)
        self._thread.start()
        logger.info("Miner started")

    def stop(self) -> None:
        """Completely stop the mining"""
        self._stop_event.set()
        self.interrupt.set()
        if self._thread:
            self._thread.join(timeout=5)

        logger.info("Miner stopped")

    def mine(self, tip: Block) -> None:
        """Starts mining from the provided tip. If we were mining for another block we interrupt it."""
        with self._tip_lock:
            self._tip = tip
        self.interrupt.set()
        logger.debug(f"Starting to mine at tip: {tip}")

    def _mine_loop(self) -> None:
        """Keep trying to mine a block, so long we are not interrupted by the interupt event"""
        while not self._stop_event.is_set():
            with self._tip_lock:
                tip = self._tip
                self._mine_one_block(tip)

    def _mine_one_block(self, tip: Block) -> None:
        """Attempt to mine a block"""
        self.interrupt.clear()
        difficulty = self._difficulty_policy.get_difficulty(tip)
        pending = self._mempool.get_pending()

        # Get all things needed to mine a new block with the pending transactions in the pool
        tx_hashes = [tx.tx_hash for tx in pending]
        txs_hash = crypto.compute_txs_hash(tx_hashes)
        timestamp = int(time.time())
        prev_hash = tip.block_hash
        logger.debug(f"Mining block height={tip.height} difficulty={difficulty} nr_txs={len(pending)}")

        nonce = 0
        check_interval = 10_000  # interval to check if the thread should be interrupted
        while not self._stop_event.is_set():
            found_nonce, block_hash = crypto.mine_block(prev_hash, txs_hash, timestamp, difficulty, nonce, check_interval)

            if found_nonce is not None and block_hash:
                block = Block(
                    height=tip.height + 1,
                    prev_hash=prev_hash,
                    txs_hash=txs_hash,
                    timestamp=timestamp,
                    difficulty=difficulty,
                    nonce=found_nonce,
                    block_hash=block_hash,
                    transactions=tuple(pending),
                )
                logger.info(f"Mined a block! on tip: {tip}, minded block: {block}")
                self._on_block_mined(block)
                return

            nonce += check_interval
            if self.interrupt.is_set():
                logger.debug("Mining interrupted")
                return
