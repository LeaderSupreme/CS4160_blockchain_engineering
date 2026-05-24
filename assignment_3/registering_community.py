import asyncio
import logging

from assignment_2.temp import is_server
from assignment_3.payloads import RegisterBlockchain, RegisterResponse
from assignment_3.peers import TrustedPeers

from .config import BLOCKCHAIN_COMMUNITY_ID, GROUP_ID, REGISTRATION_COMMUNITY_ID_B, SERVER_PUBLIC_KEY_B
from ipv8.community import Community
from ipv8.lazy_community import lazy_wrapper
from ipv8.peer import Peer

logger = logging.getLogger(__name__)

class RegisteringCommunity(Community):
    """Community, only used for registring our community to the server
    Everytime we register, the server will immediatly try to test our blockchain, if some of our nodes are not 
    ready etc, it will retry 3 times, and times out after 5 minutes.
    To try again, we need to register again.
    """
    community_id = REGISTRATION_COMMUNITY_ID_B
 
    def __init__(self, settings):
        super().__init__(settings)
        self._trusted_peers = TrustedPeers()
        self.server_peer = None
        self.submitted = False

        self.add_message_handler(RegisterResponse, self.on_response)
        self.register_task("status", self._log_status, interval=10.0, delay=10.0)
 
    def _log_status(self):
        peers = self.get_peers()
        logger.debug(f"[registering status] {len(peers)} peer(s) in community, server_peer={self.server_peer is not None}")
 
        if self.submitted or self.server_peer is not None:
            return
 
        for peer in peers:
            try:
                if self._trusted_peers.is_server(peer):
                    logger.info("Server peer found!")
                    self.server_peer = peer
                    asyncio.ensure_future(self.submit())
                    return
            except Exception:
                continue
 
    def peer_added(self, peer: Peer) -> None:
        logger.debug(f"peer_added() called for: {peer}")
 
        if self._trusted_peers.is_server(peer):
            logger.info("Server peer discovered!")
            self.server_peer = peer
            asyncio.ensure_future(self.submit())
        else:
            logger.debug(f"Found peer that was not server, mid: {peer.mid}")
 
    def peer_removed(self, peer: Peer) -> None:
        if self._trusted_peers.is_server(peer):
            logger.warning("WARNING: Server peer disconnected.")
            self.server_peer = None
 
    async def submit(self):
        """Submit method, to actually send registration to the server"""
        if self.submitted:
            return

        assert self.server_peer, "Server peer was none when registering"
        self.ez_send(self.server_peer, RegisterBlockchain(GROUP_ID, BLOCKCHAIN_COMMUNITY_ID))
        self.submitted = True
 
    @lazy_wrapper(RegisterResponse)
    async def on_response(self, peer: Peer, payload: RegisterResponse):
        """Handle registration response from the server"""
        if not self._trusted_peers.is_server(peer):
            logger.debug(f"Ignoring registration response from non-server peer. payload: {payload}")
            return
 
        print("\n==============================")
        print("SERVER RESPONSE")
        print("==============================")
        print(f"Success: {payload.success}")
        print(f"Message: {payload.message}")
        print("==============================\n")
        self.logger.info(f"Registration reponse from server. Success: {payload.success}, msg: {payload.success}")
 
        # asyncio.get_event_loop().stop() # probably need to find a cleaner way to stop the execution