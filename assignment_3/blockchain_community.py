import logging
import crypto

from assignment_3.chain import Blockchain, Transaction
from assignment_3.difficulty import DifficultyPolicy
from assignment_3.mempool import Mempool
from assignment_3.miner import Miner
from assignment_3.payloads import SubmitTransaction, SubmitTransactionResponse
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




 