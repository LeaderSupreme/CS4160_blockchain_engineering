import logging
import asyncio
import argparse
from pathlib import Path

from .blockchain.chain import Blockchain, make_genesis_block
from .blockchain.difficulty import DynamicDifficultyPolicy, FixedDifficultyPolicy
from .blockchain.mempool import Mempool
from .blockchain.storage import WALStorage, InMemoryStorage
from .network.peers import TrustedPeers

from .config import PERSONAL_KEY_FILE, DEFAULT_DIFFICULTY
from .network.blockchain_community import BlockchainCommunity
from .network.registering_community import RegisteringCommunity
 
from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs
from ipv8_service import IPv8

class _UnsupportedCurveFilter(logging.Filter):
    """Suppress the stream of 'Curve X is not supported' errors from old peers."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "Curve" not in msg and "is not supported" not in msg
 
logging.getLogger("RegisteringCommunity").addFilter(_UnsupportedCurveFilter())
logging.basicConfig(level=logging.DEBUG)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key_path", required=False, help="path to the key file (default = PERSONAL_KEY_FILE)", default=PERSONAL_KEY_FILE)
    args = parser.parse_args()

    storage_path = Path("assignment_3")
    blockchain = Blockchain(make_genesis_block(DEFAULT_DIFFICULTY), storage=WALStorage(storage_path))
    mempool = Mempool(max_size=1000)
    trusted_peers = TrustedPeers()
    difficulty_policy = DynamicDifficultyPolicy(blockchain.get_block)
     
 
    builder = ConfigBuilder()
    builder.clear_keys()
    builder.clear_overlays()
    builder.add_key("my peer", "curve25519", str(args.key_path))
    builder.add_overlay(
        "RegisteringCommunity",
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