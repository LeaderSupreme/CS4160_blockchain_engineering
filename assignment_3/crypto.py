import hashlib
import struct

from dataclasses import dataclass

# --------------------------------------
# Header functions
# --------------------------------------
# --------------------------------------
# Block header layout (84 bytes total)
# --------------------------------------
# Offset  Size  Field
#   0     32    prev_hash
#  32     32    txs_hash
#  64      8    timestamp  (unix seconds)
#  72      4    difficulty (nr leading zeros)
#  76      8    nonce      
# --------------------------------------

HEADER_STRUCT = struct.Struct(">32s32sQIQ") 
assert HEADER_STRUCT.size == 84
def serialize_header(prev_hash: bytes, txs_hash: bytes, timestamp: int, difficulty: int, nonce: int) -> bytes:
    """Serialize a block header into 84-byte"""
    return HEADER_STRUCT.pack(prev_hash, txs_hash, timestamp, difficulty, nonce)


def deserialize_header(raw: bytes) -> tuple[bytes, bytes, int, int, int]:
    """Deserialize 84 bytes header to ordered ruple, returns (prev_hash, txs_hash, timestamp, difficulty, nonce)"""
    return HEADER_STRUCT.unpack(raw)


def hash_header(prev_hash: bytes, txs_hash: bytes, timestamp: int, difficulty: int, nonce: int) -> bytes:
    """Returns sha-256 of the packed header."""
    return sha256(serialize_header(prev_hash, txs_hash, timestamp, difficulty, nonce))

def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()

# --------------------------------------
# Transaction functions
# --------------------------------------
# --------------------------------------
# Transaction layout (84 bytes total)
# --------------------------------------
# Field
# - sender_key (32 bytes)
# - data       (arbitrary data)
# - timestamp  (unix seconds, 8 bytes)
# - signature  (sign combination of all 3 fields above)
# --------------------------------------
def hash_transaction(sender_key: bytes, data: bytes, timestamp: int, signature: bytes) -> bytes:
    """Hash a transaction, converts int timestamp to 8 byte binary representation"""
    timestamp_bytes = timestamp.to_bytes(8, "big")
    return sha256(sender_key + data + timestamp_bytes + signature)


def compute_txs_hash(tx_hashes: list[bytes]) -> bytes:
    """Computes txs_hash (hash over transaction hashes) -> SHA256(tx_hash_1 || ... || tx_hash_n) 
    Note that an empty block uses SHA256(b""), and is not just 32 0 bytes.
    """
    return sha256(b"".join(tx_hashes))



# --------------------------------------
# Proof of Work
# --------------------------------------
# We precompute LEADING_ZEROS_BIT_TABLE, because it will probably be called a bunch
LEADING_ZEROS_BIT_TABLE = [8 - i.bit_length() for i in range(256)]
def count_leading_zero_bits(data: bytes) -> int:
    """Get the nr of leading zero bits in the byte string"""
    count = 0
    for byte in data:
        if byte == 0:
            count += 8
        else:
            return count + LEADING_ZEROS_BIT_TABLE[byte]

    return count

def satisfies_pow(block_hash: bytes, difficulty: int) -> bool:
    """Check if block_hash has at least `difficulty` leading zero bits, returns true if this is the case"""
    return count_leading_zero_bits(block_hash) >= difficulty

def mine_block(prev_hash: bytes, txs_hash: bytes, timestamp: int, difficulty: int, start_nonce: int = 0) -> tuple[int, bytes]:
    """Search for a nonce that satisfies the PoW requirement, returns (nonce, block_hash)"""
    nonce = start_nonce
    while True:
        candidate = serialize_header(prev_hash, txs_hash, timestamp, difficulty, nonce)
        block_hash = sha256(candidate)

        if count_leading_zero_bits(block_hash) >= difficulty:
            return nonce, block_hash

        nonce += 1