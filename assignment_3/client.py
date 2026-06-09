from ipv8.keyvault.crypto import ECCrypto
from typing import List
import asyncio
from pathlib import Path

from assignment_3.blockchain_community import BlockchainCommunity
from assignment_3.registering_community import RegisteringCommunity
from .config import PERSONAL_KEY_FILE
 
from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs
from ipv8.lazy_community import lazy_wrapper
from ipv8_service import IPv8

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
        -1,
    )
 
    ipv8 = IPv8(
        builder.finalize(),
        extra_communities={"BlockchainCommunity": BlockchainCommunity,
                           "RegisteringCommunity": RegisteringCommunity},
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