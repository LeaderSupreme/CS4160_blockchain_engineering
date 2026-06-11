import time
import logging
import threading

from typing import Callable

from . import crypto
from .chain import Block 
from .difficulty import DifficultyPolicy
from .mempool import Mempool

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class Miner:
    """Mining class that is stateless with respect to the chain.
    It is thread safe, so we can run it as co-routine.
    When it mines a block, the callback is used"""

    def __init__(self, mempool: Mempool, difficulty_policy: DifficultyPolicy, on_block_mined: Callable[[Block], None], num_threads = 4) -> None:
        self._mempool = mempool
        self._difficulty_policy = difficulty_policy
        self._on_block_mined = on_block_mined

        self.interrupt = threading.Event()  # Event to stop, for example we have a new tip
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._tip: Block
        self._tip_lock = threading.Lock()

        self._num_threads = num_threads
        self._workers = []
        self._found_lock = threading.Lock()
        self._found = False

    def start(self, tip = None) -> None:
        """Start the mining process, or continue if already started"""
        logger.debug("Miner start called")
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._found = False
        self._workers = []
        self._tip = tip

        for i in range(self._num_threads):
            thread = threading.Thread(target=self._mine_loop, args=(i,), name=f"miner-{i}", daemon=True)
            thread.start()
            self._workers.append(thread)

        logger.info(f"{self._num_threads} Miner(s) started")

    def stop(self) -> None:
        """Completely stop the mining"""
        self._stop_event.set()
        self.interrupt.set()

        for thread in self._workers:
            thread.join(timeout=5)

        self._workers.clear()
        logger.info("Miner stopped")

    def mine(self, tip: Block) -> None:
        """Starts mining from the provided tip. If we were mining for another block we interrupt it."""
        assert tip is not None, "passed None to mine function"
        with self._tip_lock:
            self._tip = tip
        with self._found_lock:
            self._found = False
        self.interrupt.set()
        logger.info(f"Starting to mine at tip: {tip}")

    def _mine_loop(self, worker_id) -> None:
        """Keep trying to mine a block, so long we are not interrupted by the interupt event"""
        if self._tip is None:
            return

        while not self._stop_event.is_set():
            with self._tip_lock:
                tip = self._tip
            # interrupt is sticky (set on tip switch / found). Clear it before a fresh attempt,
            # else every round bails immediately on the leftover signal and never mines.
            self.interrupt.clear()
            self._mine_one_block(tip, worker_id)

    def _mine_one_block(self, tip: Block, worker_id: int) -> None:
        """Attempt to mine a block"""
        difficulty = self._difficulty_policy.get_difficulty(tip)
        pending = self._mempool.get_pending()

        # Get all things needed to mine a new block with the pending transactions in the pool
        tx_hashes = [tx.tx_hash for tx in pending]
        txs_hash = crypto.compute_txs_hash(tx_hashes)
        timestamp = int(time.time())
        prev_hash = tip.block_hash
        logger.debug(f"Thread {worker_id} Mining block height={tip.height} difficulty={difficulty} nr_txs={len(pending)}")

        # We interleave the search space for multi threaded mining.
        nonce = worker_id 
        check_interval = 10_000  # interval to check if the thread should be interrupted
        while not self._stop_event.is_set():
            found_nonce, block_hash = crypto.mine_block(prev_hash, txs_hash, timestamp, difficulty, nonce, check_interval, step=self._num_threads)

            if found_nonce is not None and block_hash is not None:
                with self._found_lock:
                    if self._found:
                        return
                    self._found = True
                    self.interrupt.set()

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

                logger.info(f"Thread {worker_id} Mined a block! on tip: {tip}, minded block: {block}")
                self._on_block_mined(block)
                return

            nonce += check_interval * self._num_threads 
            if self.interrupt.is_set():
                logger.debug("Mining interrupted")
                return
