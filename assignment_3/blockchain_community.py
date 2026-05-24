import logging

from assignment_3.chain import Blockchain
from assignment_3.difficulty import DifficultyPolicy
from assignment_3.mempool import Mempool
from assignment_3.miner import Miner
from assignment_3.peers import TrustedPeers

from .config import BLOCKCHAIN_COMMUNITY_ID

from ipv8.community import Community
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
 