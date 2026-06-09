import asyncio
import logging

from assignment_3.payloads import RegisterBlockchain, RegisterResponse

from .config import BLOCKCHAIN_COMMUNITY_ID, GROUP_ID, REGISTRATION_COMMUNITY_ID_B, SERVER_PUBLIC_KEY_B
from ipv8.community import Community
from ipv8.lazy_community import lazy_wrapper
from ipv8.peer import Peer

class _UnsupportedCurveFilter(logging.Filter):
    """Suppress the stream of 'Curve X is not supported' errors from old peers."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "Curve" not in msg and "is not supported" not in msg
 
logging.getLogger("Lab2Community").addFilter(_UnsupportedCurveFilter())
logging.basicConfig(level=logging.DEBUG)

class RegisteringCommunity(Community):
    community_id = REGISTRATION_COMMUNITY_ID_B
 
    def __init__(self, settings):
        super().__init__(settings)
        self.server_peer = None
        self.submitted = False
        self.add_message_handler(RegisterResponse, self.on_response)
        self.register_task("status", self._log_status, interval=10.0, delay=10.0)
 
    def _log_status(self):
        peers = self.get_peers()
        print(f"[status] {len(peers)} peer(s) in community, server_peer={self.server_peer is not None}")
 
        if self.submitted or self.server_peer is not None:
            return
 
        for peer in peers:
            try:
                if peer.public_key.key_to_bin() == SERVER_PUBLIC_KEY_B:
                    print("Server peer found!")
                    self.server_peer = peer
                    asyncio.ensure_future(self.submit())
                    return
            except Exception:
                continue
 
    def peer_added(self, peer: Peer) -> None:
        print(f"peer_added() called for: {peer}")
        try:
            key = peer.public_key.key_to_bin()
        except Exception as e:
            print(f"  Could not read key: {e}")
            return
 
        print(f"  Key: {key.hex()[:20]}...")
        if key == SERVER_PUBLIC_KEY_B:
            print("  -> Server peer discovered!")
            self.server_peer = peer
            asyncio.ensure_future(self.submit())
        else:
            print(f"  -> Non-server peer, skipping.")
 
    def peer_removed(self, peer: Peer) -> None:
        try:
            key = peer.public_key.key_to_bin()
        except Exception:
            return
 
        if key == SERVER_PUBLIC_KEY_B:
            print("WARNING: Server peer disconnected.")
            self.server_peer = None
 
    async def submit(self):
        if self.submitted:
            return
        self.submitted = True
 
        self.ez_send(self.server_peer, RegisterBlockchain(GROUP_ID, BLOCKCHAIN_COMMUNITY_ID))
 
    @lazy_wrapper(RegisterResponse)
    async def on_response(self, peer: Peer, payload: RegisterResponse):
        expected_key = SERVER_PUBLIC_KEY_B
        try:
            sender_key = peer.public_key.key_to_bin()
        except Exception:
            print("WARNING: Could not read public key from response sender — ignoring.")
            return
 
        if sender_key != expected_key:
            print("WARNING: Ignoring response from non-server peer.")
            return
 
        print("\n==============================")
        print("SERVER RESPONSE")
        print("==============================")
        print(f"Success: {payload.success}")
        print(f"Message: {payload.message}")
        print("==============================\n")
 
        # asyncio.get_event_loop().stop() # probably need to find a cleaner way to stop the execution