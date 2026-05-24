from inspect import getblock
import logging
from socket import TCP_TX_DELAY
import crypto

from assignment_3.chain import Block, Blockchain, Transaction
from assignment_3.difficulty import DifficultyPolicy
from assignment_3.mempool import Mempool
from assignment_3.miner import Miner
from assignment_3.payloads import AnnounceBlock, BlockResponse, BlockResponseInner, ChainHeightResponse, GetBlock, GetChainHeight, RequestBlock, SubmitTransaction, SubmitTransactionResponse
from assignment_3.peers import TrustedPeers

from .config import BLOCKCHAIN_COMMUNITY_ID

from ipv8.community import Community, lazy_wrapper
from ipv8.peer import Peer

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
            chain=self._chain,
            mempool=self._mempool,
            difficulty_policy=self._difficulty_policy
        )
        
        # Msg handlers
        self.add_message_handler(SubmitTransaction, self.on_submit_transaction)
        self.add_message_handler(GetChainHeight, self.on_get_chain_height)
        self.add_message_handler(GetBlock, self.on_get_block)

        self.add_message_handler(AnnounceBlock, self.on_announce_block)
        self.add_message_handler(RequestBlock, self.on_request_block)

        # Orphans
        # TODO Refactor, this logic belongs in chain.py under Blockhain
        # These are blocks that are correct, but unconnected for now.
        # for example, a peer is ahead 2 blocks, and announes a new block.
        # this block is correct, but we cant connect it to the chain yet.
        self._orphans: dict[int, Block] = {}  # dict [height -> block]

    
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

        elif payload.height == self._chain.height and not self._chain.contains(payload.block_hash):
            logger.info(f"Received block announcement from peer: {peer}, at same height: {payload.height}, but unkown hash. Possible fork.") 
            self.ez_send(peer, RequestBlock(payload.height))
            return
        
        else:
            logger.debug(f"Received block announcement from peer {peer}, with height {payload.height}, our height is: {self._chain.height}, ignoring announcmeent.")

    @lazy_wrapper(RequestBlock)
    def on_request_block(self, peer: Peer, payload: RequestBlock) -> None:
        """Handle request block request, SAME LOGIC AS ON_GET_BLOCK"""
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
            height=payload.height,transactions=()  # We dont have the transactions 
        )

        if self._chain.add_block(block):
            self.logger.debug(f"Internal block response. Added block from peer {peer} to chain")
            adtopted = self.adopt_orphans()
            logger.info(f"Interal block resopnse: was able to adopt {len(adtopted)} orphans after this addition")
            return
        
        #TODO probably should not be here
        if block.height > self._chain.height + 1:
            self._orphans[block.height] = block
            logger.info(f"Internal block response: from peer: {peer} was valid, but were unable to add to chain. incorrect height. "
                        f"our height: {self._chain.height}, block height: {block.height}. requesting previous block and added to orphans")
            self.ez_send(peer, RequestBlock(block.height-1))

    def adopt_orphans(self) -> list[Block]:
        """Try to adopt orphans from the current pool"""
        adopted = []
        while True:
            orphan = self._orphans.pop(self._chain.height + 1, None)
            if not orphan:
                break

            if not self._chain.add_block(orphan):
                break

            adopted.append(orphan)
        return adopted
                
            
