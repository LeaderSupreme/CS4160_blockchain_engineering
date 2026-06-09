import logging

from .config import BLOCKCHAIN_COMMUNITY_ID
from ipv8.community import Community
from ipv8.peer import Peer

class _UnsupportedCurveFilter(logging.Filter):
    """Suppress the stream of 'Curve X is not supported' errors from old peers."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "Curve" not in msg and "is not supported" not in msg
 
logging.getLogger("Lab2Community").addFilter(_UnsupportedCurveFilter())
logging.basicConfig(level=logging.DEBUG)

class BlockchainCommunity(Community):
    community_id = BLOCKCHAIN_COMMUNITY_ID
 
    def __init__(self, settings):
        super().__init__(settings)
 
    def peer_added(self, peer: Peer) -> None:
        print(f"peer_added() called for: {peer}")
        try:
            key = peer.public_key.key_to_bin()
        except Exception as e:
            print(f"  Could not read key: {e}")
            return
 
    def peer_removed(self, peer: Peer) -> None:
        try:
            key = peer.public_key.key_to_bin()
        except Exception:
            return
 