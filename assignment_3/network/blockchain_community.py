import asyncio
import logging

from ..blockchain import crypto
from ..blockchain.chain import Block, Blockchain, Transaction
from ..blockchain.difficulty import DifficultyPolicy
from ..blockchain.mempool import Mempool
from ..blockchain.miner import Miner
from .payloads import AnnounceBlock, BlockResponse, BlockResponseInner, ChainHeightResponse, GetBlock, GetChainHeight, RequestBlock, SubmitTransaction, SubmitTransactionResponse
from .peers import TrustedPeers
from ..config import BLOCKCHAIN_COMMUNITY_ID

from ipv8.community import Community, lazy_wrapper
from ipv8.peer import Peer

class _UnsupportedCurveFilter(logging.Filter):
    """Suppress the stream of 'Curve X is not supported' errors from old peers."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "Curve" not in msg and "is not supported" not in msg
 
logging.getLogger("RegisteringCommunity").addFilter(_UnsupportedCurveFilter())
logger = logging.getLogger(__name__)

class BlockchainCommunity(Community):
    """The community that actually runs our blockchain"""
    community_id = BLOCKCHAIN_COMMUNITY_ID
 
    def __init__(self, settings):
        super().__init__(settings)
        
        # Inject all dependencies via the settings
        self._chain: Blockchain = settings.chain
        self._mempool: Mempool = settings.mempool
        self._trusted_peers: TrustedPeers = settings.trusted_peers
        self._difficulty_policy: DifficultyPolicy = settings.difficulty_policy

        # Thead safe miner, which can run in the background
        self._miner = Miner(
            mempool=self._mempool,
            difficulty_policy=self._difficulty_policy,
            on_block_mined=self._on_block_mined_thread_safe
        )
        
        # Msg handlers
        self.add_message_handler(SubmitTransaction, self.on_submit_transaction)
        self.add_message_handler(GetChainHeight, self.on_get_chain_height)
        self.add_message_handler(GetBlock, self.on_get_block)

        self.add_message_handler(AnnounceBlock, self.on_announce_block)
        self.add_message_handler(RequestBlock, self.on_request_block)
        self.add_message_handler(BlockResponseInner, self.on_block_response_internal)

    def started(self) -> None:
        # TODO start miner
        # TODO should we schedule task to sync with peers? or do we trust we dont go out of sync?
        pass
 

    def peer_added(self, peer: Peer) -> None:
        if self._trusted_peers.is_server(peer):
            logger.info("Found the server")
        elif self._trusted_peers.is_teammate(peer):
            logger.info(f"Found a teammate, mid: {peer.mid}")
        else:
            logger.debug(f"Peer joined the community, neiter server not teammate. mid: {peer.mid}")

 
    def peer_removed(self, peer: Peer) -> None:
        if self._trusted_peers.is_server(peer):
            logger.warning("Server left the community")
        elif self._trusted_peers.is_teammate(peer):
            logger.warning(f"Teammate left the community, mid: {peer.mid}")
        else:
            logger.debug(f"Peer left the community. Was neither server nor teammate. mid: {peer.mid}")


    # --------------------------------------
    # Server communication
    # --------------------------------------
    @lazy_wrapper(SubmitTransaction)
    def on_submit_transaction(self, peer: Peer, payload: SubmitTransaction) -> None:
        """A peer submits a transaction to the mempool
        We need to:
            - Verify the signature
            - Add the transaction to the mempool
            - Respond
        """
        logger.debug(f"Peer: {peer}, submitted transaction: {payload}")

        # Verify the signature
        sender_key = self.crypto.key_from_public_bin(payload.sender_key)
        timestamp_bytes = payload.timestamp.to_bytes(8, "big")
        transaction_data = payload.sender_key + payload.data + timestamp_bytes
        transaction_hash = crypto.hash_transaction(payload.sender_key, payload.data, payload.timestamp, payload.signature)
        if not self.crypto.is_valid_signature(sender_key, transaction_data, payload.signature):
            self.logger.warning(f"Submittransaction from peer: {peer}, had invalid signature")
            self.ez_send(
                peer, 
                SubmitTransactionResponse(
                    success=False,
                    tx_hash=transaction_hash,  # TODO should this use actual transaction hash, or dummy hash like max value?
                    message="invalid signature"
                )
            )
            return
        
        # Add the transaction to the mempool
        tx = Transaction(
            sender_key=payload.sender_key,
            data=payload.data,
            timestamp=payload.timestamp,
            signature=payload.signature,
            tx_hash=transaction_hash
        )

        if not self._mempool.add(tx):
            self.logger.warning(f"Failed to add tx: {tx} to the mempool: {self._mempool}")
            self.ez_send(
                peer,
                SubmitTransactionResponse(
                    success=False,  # TODO if we want it to be idempotent split duplicate case from low priority. duplicate can be success=true mb.
                    tx_hash=transaction_hash, 
                    message="Failed to add to mempool. Either tx_hash already in mempool, or pool is full and prioity is too low."
                )
            )
            return

        self.ez_send(
            peer, 
            SubmitTransactionResponse(
                success=True,
                tx_hash=transaction_hash, 
                message="Added transcaction to pool"
            )
        )
        self.logger.debug(f"Submittransaction from peer: {peer}, was successfully added")


    @lazy_wrapper(GetChainHeight)
    def on_get_chain_height(self, peer: Peer, payload: GetChainHeight) -> None:
        """Handle a request for the current chain height"""
        current_tip = self._chain.tip
        self.logger.debug(f"Handeling get chain height request from peer: {peer}. Current tip: {current_tip}")
        self.ez_send(
            peer,
            ChainHeightResponse(
                request_id=payload.request_id,
                height=current_tip.height,
                tip_hash=current_tip.block_hash
            )
        )


    @lazy_wrapper(GetBlock)
    def on_get_block(self, peer: Peer, payload: GetBlock) -> None:
        """Handle a request for a block on a specific height"""
        block = self._chain.get_block(payload.height)
        if not block:
            self.logger.warning(f"Couldnt find a block a requested height: {payload.height}")
            return  # TODO no way to send failure right? mb other peers will have this height already
        
        tx_hashes = b"".join([transaction.tx_hash for transaction in block.transactions])
        self.ez_send(
            peer,
            BlockResponse(
                height=block.height,
                prev_hash=block.prev_hash,
                txs_hash=block.txs_hash,
                timestamp=block.timestamp,
                difficulty=block.difficulty,
                nonce=block.nonce,
                block_hash=block.block_hash,
                tx_hashes=tx_hashes
            )
        )
        self.logger.debug(f"Successfully returned requested block at height: {payload.height} to peer: {peer}")

        
    
    # --------------------------------------
    # Internal communication
    # --------------------------------------
    @lazy_wrapper(AnnounceBlock)
    def on_announce_block(self, peer: Peer, payload: AnnounceBlock) -> None:
        """Handle a block announcement. If we dont have this block yet, we will request more info for it"""
        if payload.height > self._chain.height:
            logger.info(f"Received block announcement from peer: {peer}, with height: {payload.height}, this is bigger then our own height: {self._chain.height}")
            self.ez_send(peer, RequestBlock(payload.height))
            return

        #TODO if this, or lower height, probably should be in forks (should we store it? we still assume longest chain is valid)
        elif payload.height == self._chain.height and not self._chain.contains(payload.block_hash):
            logger.info(f"Received block announcement from peer: {peer}, at same height: {payload.height}, but unkown hash. Possible fork.") 
            self.ez_send(peer, RequestBlock(payload.height))
            return
        
        else:
            logger.debug(f"Received block announcement from peer {peer}, with height {payload.height}, our height is: {self._chain.height}, ignoring announcmeent.")

    @lazy_wrapper(RequestBlock)
    def on_request_block(self, peer: Peer, payload: RequestBlock) -> None:
        """Handle an internal block request from a teammate. Same lookup as on_get_block, but we
        reply with BlockResponseInner so the requester's on_block_response_internal handler fires."""
        block = self._chain.get_block(payload.height)
        if not block:
            self.logger.warning(f"Couldnt find a block a requested height: {payload.height}")
            return  # TODO no way to send failure right? mb other peers will have this height already

        tx_hashes = b"".join([transaction.tx_hash for transaction in block.transactions])
        self.ez_send(
            peer,
            BlockResponseInner(
                height=block.height,
                prev_hash=block.prev_hash,
                txs_hash=block.txs_hash,
                timestamp=block.timestamp,
                difficulty=block.difficulty,
                nonce=block.nonce,
                block_hash=block.block_hash,
                tx_hashes=tx_hashes
            )
        )
        self.logger.debug(f"Successfully returned requested block at height: {payload.height} to peer: {peer}")

    @lazy_wrapper(BlockResponseInner)
    def on_block_response_internal(self, peer: Peer, payload: BlockResponseInner) -> None:
        """Handle Block reponse inner. We verify the block, and possible add it to our chain."""

        # Deserialze the tx hashes
        if len(payload.tx_hashes) % 32 != 0:
            logger.warning(f"Inernal Block response: Can't decode tx hashes. Nr bytes not divisible by 32, len: {len(payload.tx_hashes)}")
            return
        tx_hashes = [payload.tx_hashes[i:i+32] for i in range(0, len(payload.tx_hashes), 32)]

        txs_hash_check = crypto.compute_txs_hash(tx_hashes)
        if txs_hash_check != payload.txs_hash:
            logger.warning("Internal Block Response: txs_hash mismatch, rejecting block")
            return

        header_hash_check = crypto.hash_header(payload.prev_hash, payload.txs_hash, payload.timestamp, payload.difficulty, payload.nonce)
        if header_hash_check != payload.block_hash:
            logger.warning("Internal Block Response: blockhash didnt match header hash, rejecting block")
            return
        
        #TODO is it a problem we don't have the transactions?
        block = Block(
            block_hash=payload.block_hash,
            prev_hash=payload.prev_hash,
            txs_hash=payload.txs_hash,
            timestamp=payload.timestamp,
            difficulty=payload.difficulty,
            nonce=payload.nonce,
            height=payload.height,
            transactions=(),
        )

        result = self._chain.add_block(block)

        if result.is_orphan:
            # Parent unknown: the chain has parked this block. Ask for the previous height so we
            # can backfill towards a block we already have. (height-based backfill for now.)
            logger.info(f"Internal block response from peer {peer}: parked orphan at height {block.height}, "
                        f"requesting parent at height {block.height - 1}")
            self.ez_send(peer, RequestBlock(block.height - 1))
            return

        if result.added:
            self.logger.debug(f"Internal block response from peer {peer}: added block (extended_tip={result.extended_tip})")
            self._reconcile_after_chain_update(result)

    def _reconcile_after_chain_update(self, result) -> None:
        """After a block was added, keep the mempool and miner consistent with the new best chain."""
        if not result.extended_tip:
            return  # block landed on a side branch; main chain unchanged

        # Transactions that left the main chain in a reorg go back to the mempool...
        for block in result.reverted:
            for tx in block.transactions:
                self._mempool.add(tx)
        # ...and transactions now confirmed on the main chain are removed.
        for block in result.applied:
            self._mempool.remove_included(block.tx_hashes)

        # Mine from the new tip.
        self._miner.mine(self._chain.tip)


    def _announce_block(self, block: Block) -> None:
        """Broadcast the block to all known peers"""
        payload = AnnounceBlock(block.height, block.block_hash)
        for peer in self.get_peers():
            self.ez_send(peer, payload)
                
            
    # --------------------------------------
    # Mining
    # --------------------------------------
    def _on_block_mined_thread_safe(self, block: Block) -> None:
        """Called from the mining thread, when a block is mined. schedule the result in the event loop to make it thread safe."""
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(self._on_block_mined, block)
    
    def _on_block_mined(self, block: Block) -> None:
        """Callback method that handles the actual logic of a mined block"""
        result = self._chain.add_block(block)
        if not result.added:
            # Could be that during mining we already got this tip from a peer, or the tip moved on.
            self.logger.warning(f"Mined block was rejected from the chain. block: {block}")
            self._miner.mine(self._chain.tip)  # start mining a new block, from the current tip
            return

        # The block was successfully added.
        # - reconcile the mempool against the (possibly reorged) main chain
        # - announce the block to all peers
        # - keep mining from the current tip
        logger.info(f"Block added to chain: {block}")
        self._reconcile_after_chain_update(result)
        self._announce_block(block)
        self._miner.mine(self._chain.tip)