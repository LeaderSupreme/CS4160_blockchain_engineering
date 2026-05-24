from dataclasses import dataclass
from ipv8.messaging.payload_dataclass import DataClassPayload

from config import (
    MSG_BLOCK_RESPONSE_INNER, MSG_REGISTER_BLOCKCHAIN, MSG_REGISTER_RESPONSE, MSG_REQUEST_BLOCK, 
    MSG_SUBMIT_TX, MSG_SUBMIT_TX_RESPONSE, MSG_GET_CHAIN_HEIGHT,
    MSG_CHAIN_HEIGHT_RESPONSE, MSG_GET_BLOCK, MSG_BLOCK_RESPONSE, MSG_ANNOUNCE_BLOCK
)

# --------------------------------------
# Registration
# --------------------------------------
@dataclass
class RegisterBlockchain(DataClassPayload[MSG_REGISTER_BLOCKCHAIN]):
    group_id: str
    community_id: bytes

@dataclass
class RegisterResponse(DataClassPayload[MSG_REGISTER_RESPONSE]):
    success: bool
    message: str


# --------------------------------------
# Blockchain
# --------------------------------------
@dataclass
class SubmitTransaction(DataClassPayload[MSG_SUBMIT_TX]):
    """Submit transaction to mempool"""
    sender_key: bytes
    data: bytes
    timestamp: int
    signature: bytes


@dataclass
class SubmitTransactionResponse(DataClassPayload[MSG_SUBMIT_TX_RESPONSE]):
    """Confirmation of transaction submittion"""
    success: bool
    tx_hash: bytes
    message: str


@dataclass
class GetChainHeight(DataClassPayload[MSG_GET_CHAIN_HEIGHT]):
    """Request current chain height"""
    request_id: int


@dataclass
class ChainHeightResponse(DataClassPayload[MSG_CHAIN_HEIGHT_RESPONSE]):
    """Response with current chain height, and hash of current tip"""
    request_id: int
    height: int
    tip_hash: bytes


@dataclass
class GetBlock(DataClassPayload[MSG_GET_BLOCK]):
    """Request for a block on a given height"""
    height: int


@dataclass
class BlockResponse(DataClassPayload[MSG_BLOCK_RESPONSE]):
    """Respond with requested block on the height provided in the request"""
    height: int
    prev_hash: bytes
    txs_hash: bytes
    timestamp: int
    difficulty: int
    nonce: int
    block_hash: bytes
    tx_hashes: bytes    # flat concatenated 32 byte hashes

# --------------------------------------
# Inner Communication
# --------------------------------------
@dataclass
class AnnounceBlock(DataClassPayload[MSG_ANNOUNCE_BLOCK]):
    """Announce you just mined or received a block at this height, include the block hash"""
    height: int
    block_hash: bytes

@dataclass
class RequestBlock(DataClassPayload[MSG_REQUEST_BLOCK]):
    """Request a block on a specific height from peers"""
    height: int

@dataclass
class BlockResponseInner(DataClassPayload[MSG_BLOCK_RESPONSE_INNER]):
    """Repondss with requested block"""
    height: int
    prev_hash: bytes
    txs_hash: bytes
    timestamp: int
    difficulty: int
    nonce: int
    block_hash: bytes
    tx_hashes: bytes    # flat concatenated 32 byte hashes