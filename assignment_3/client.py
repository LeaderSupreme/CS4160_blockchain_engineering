import logging
import asyncio
from pathlib import Path

from assignment_3.chain import Blockchain, make_genesis_block
from assignment_3.difficulty import FixedDifficultyPolicy
from assignment_3.mempool import Mempool
from assignment_3.peers import TrustedPeers

from .config import PERSONAL_KEY_FILE, DIFFICULTY
from assignment_3.blockchain_community import BlockchainCommunity
from assignment_3.registering_community import RegisteringCommunity
 
from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs
from ipv8_service import IPv8

class _UnsupportedCurveFilter(logging.Filter):
    """Suppress the stream of 'Curve X is not supported' errors from old peers."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "Curve" not in msg and "is not supported" not in msg
 
logging.getLogger(__name__).addFilter(_UnsupportedCurveFilter())
logging.basicConfig(level=logging.DEBUG)

async def main():
    key_path = Path(PERSONAL_KEY_FILE)

    blockchain = Blockchain(make_genesis_block(DIFFICULTY))
    mempool = Mempool(max_size=1000)
    trusted_peers = TrustedPeers()
    difficulty_policy = FixedDifficultyPolicy()
    
 
    builder = ConfigBuilder()
    builder.clear_keys()
    builder.clear_overlays()
    builder.add_key("my peer", "curve25519", str(key_path))
    builder.add_overlay(
        "Lab2Community",
        "my peer",
        [WalkerDefinition(Strategy.RandomWalk, 20, {"timeout": 5.0})],
        default_bootstrap_defs,
        {
            "chain": blockchain,
            "mempool": mempool,
            "trusted_peers": trusted_peers,
            "difficulty_policy": difficulty_policy
        },
        [],
        False,
    )
 
    ipv8 = IPv8(
        builder.finalize(),
        extra_communities={
            "BlockchainCommunity": BlockchainCommunity,
            "RegisteringCommunity": RegisteringCommunity
        },
    )
 
    # TODO mb choose 1 teammate to register, and the rest can just start blockchain community
    await ipv8.start()
    print("IPv8 started, waiting for server peer...\n")
 
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await ipv8.stop()
 
 
if __name__ == "__main__":
    asyncio.run(main())