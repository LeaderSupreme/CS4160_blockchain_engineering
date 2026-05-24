import logging
import asyncio
from pathlib import Path

from .config import PERSONAL_KEY_FILE
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
 
    builder = ConfigBuilder()
    builder.clear_keys()
    builder.clear_overlays()
    builder.add_key("my peer", "curve25519", str(key_path))
    builder.add_overlay(
        "Lab2Community",
        "my peer",
        [WalkerDefinition(Strategy.RandomWalk, 20, {"timeout": 5.0})],
        default_bootstrap_defs,
        {},
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
 
    await ipv8.start()
    print("IPv8 started, waiting for server peer...\n")
 
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await ipv8.stop()
 
 
if __name__ == "__main__":
    asyncio.run(main())