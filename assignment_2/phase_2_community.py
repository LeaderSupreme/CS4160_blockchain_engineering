from __future__ import annotations
import time
import asyncio
import logging

from dataclasses import dataclass, field
from typing import Dict, List, Optional, cast
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ipv8.peer import Peer
from ipv8.community import Community, CommunitySettings
from ipv8.keyvault.keys import PrivateKey
from ipv8.lazy_community import lazy_wrapper
from ipv8.peerdiscovery.network import PeerObserver 
from ipv8.messaging.payload_dataclass import DataClassPayload

logger = logging.getLogger("Lab2")
class ChallengeRequestPayload(DataClassPayload[3]):
    group_id: str

class ChallengeResponsePayload(DataClassPayload[4]):
    nonce: bytes
    round_number: int
    deadline: float

class SignatureBundlePayload(DataClassPayload[5]):
    group_id: str
    round_number: int
    sig1: bytes        # Same number signatures as submitted in part 1 
    sig2: bytes        # In the same order every round. 
    sig3: bytes        

class RoundResultPayload(DataClassPayload[6]):
    success: bool
    round_number: int
    rounds_completed: int
    message: str

class NonceBroadcastPayload(DataClassPayload[91]):
    """Peer sharing the nonce for the current round number"""
    group_id: str
    round_number: int
    nonce: bytes

class SignatureSharePayload(DataClassPayload[92]):
    """Peer responding with signed nonce for the round"""
    group_id: str
    round_number: int
    signature: bytes

class ReadyPayload(DataClassPayload[93]):
    """Ready msg, to share we are ready to start the challenges. Only share when the cache is full."""
    group_id: str

@dataclass
class RoundState:
    round_number: int
    nonce: Optional[bytes] = None
    deadline: Optional[float] = None
    nonce_future: Optional[asyncio.Future] = None
    sig_futures: Dict[int, asyncio.Future] = field(default_factory=dict)
    result_future: Optional[asyncio.Future] = None

@dataclass
class Lab2Settings(CommunitySettings):
    private_key: Optional[Ed25519PrivateKey] = None
    group_id: str = ""
    member_keys: List[bytes] = field(default_factory=list)
    my_index: int = 0

class Lab2Community(Community, PeerObserver):
    ROUND_TO_SUBMITTER: Dict[int, int] = {1: 0, 2: 1, 3: 2}

    def __init__(self, settings: Lab2Settings) -> None:
        self.community_id = settings.community_id
        super().__init__(settings)

        self._group_id = settings.group_id
        self._my_index = settings.my_index
        self._member_keys = settings.member_keys
        self._server_pk = settings.server_pk
        self._sk = None

        self._round_states: Dict[int, RoundState] = {}
        self._all_done = asyncio.Event()

        # Cache the peer objects of our server and the peers, so we don't need to search for them again
        self._server_peer: Optional[Peer] = None
        self._teammate_peers: Dict[int, Peer] = {}  # member index to Peer instance

        self._my_cache_ready: bool = False
        self._teammates_ready: set[int] = set()
        self._all_ready = asyncio.Event()

        self.add_message_handler(ChallengeResponsePayload, self._on_challenge_response)
        self.add_message_handler(RoundResultPayload, self._on_round_result)
        self.add_message_handler(NonceBroadcastPayload, self._on_nonce_broadcast)
        self.add_message_handler(SignatureSharePayload, self._on_signature_share)
        self.add_message_handler(ReadyPayload, self._on_ready)

        # Make sure we have a private key associated to the public key
        assert self.my_peer.key.has_secret_key()
        self._signing_key: PrivateKey = cast(PrivateKey, self.my_peer.key) 
        logger.info("Lab2Community ready | group=%s | my_index=%d", settings.group_id, settings.my_index)

    def on_peer_added(self, peer: Peer) -> None:
        print(f"Peer added to community: {peer}")
        try:
            key = peer.public_key.key_to_bin()
        except Exception as e:
            print(f"Could not read key as bin: {e}")
            return None

        if key == bytes.fromhex(self._server_pk):
            print(" SERVER PEER DISCOVERED")
            self._cache_server(peer)

        elif key in self._member_keys:
            print(" MEMBER KEY FOUND") 
            self._cache_teammate(peer, key)
        return None

    def on_peer_removed(self, peer: Peer) -> None:
        print(f"Peer left community: {peer}")
        return None
        
    async def run_all_rounds(self) -> None:
        loop = asyncio.get_event_loop()
        for rn in (1, 2, 3):
            state = RoundState(round_number=rn)
            state.nonce_future  = loop.create_future()
            state.result_future = loop.create_future()

            # We only need to collect signatures in the round we are submitter
            if self.ROUND_TO_SUBMITTER[rn] == self._my_index:
                for idx in self._teammate_indices():
                    state.sig_futures[idx] = loop.create_future()

            self._round_states[rn] = state

        logger.info("Waiting for all peers to be discovered")
        await self._discover_all_peers()

        logger.info("Broadcasting ready, waiting for teammates")
        await self._readiness_handshake()

        logger.info("All 3 members ready — starting rounds.")
        if self.ROUND_TO_SUBMITTER[1] == self._my_index:
            asyncio.create_task(self._run_round_as_submitter(1))

        await self._all_done.wait()
        logger.info("All 3 rounds completed.")


    async def _run_round_as_submitter(self, round_num: int) -> None:
        logger.info("[Round %d] Starting our submitter round.", round_num)
        state = self._round_states[round_num]

        if not state.nonce_future.done():  # type: ignore
            self.ez_send(self._server_peer, ChallengeRequestPayload(group_id=self._group_id)) # type: ignore

        try:
            nonce = await asyncio.wait_for(asyncio.shield(state.nonce_future), timeout=5.0) # type: ignore
        except asyncio.TimeoutError:
            logger.error("[Round %d] No ChallengeResponse within timeout.", round_num)
            return

        self._broadcast_nonce(round_num, nonce)
        my_sig = self.crypto.create_signature(self._signing_key, nonce)

        logger.info("[Round %d] Waiting for teammate signatures", round_num)
        try:
            teammate_sigs = await asyncio.wait_for(
                asyncio.gather(*[state.sig_futures[i] for i in self._teammate_indices()]),
                timeout= 1.0,  
            )
        except asyncio.TimeoutError:
            logger.error("[Round %d] Timed out waiting for teammate signatures.", round_num)
            return

        sigs: List[Optional[bytes]] = [None, None, None]
        sigs[self._my_index] = my_sig
        for i, idx in enumerate(self._teammate_indices()):
            sigs[idx] = teammate_sigs[i]

        self.ez_send(
            self._server_peer, # type: ignore
            SignatureBundlePayload(
                group_id=self._group_id,
                round_number=round_num,
                sig1=sigs[0],
                sig2=sigs[1],
                sig3=sigs[2],
            ),
        )
        logger.info("[Round %d] Bundle submitted.", round_num)

    @lazy_wrapper(ChallengeResponsePayload)
    def _on_challenge_response(self, peer: Peer, payload: ChallengeResponsePayload) -> None:
        rn = payload.round_number
        state = self._round_states.get(rn)
        logger.info("[Round %d] ChallengeResponse received. Deadline in %.2f s.", rn, payload.deadline - time.time())

        if state is None:
            logger.warning("[Round %d] No state for incoming ChallengeResponse, ignoring. ", rn, payload)
            return

        state.nonce    = payload.nonce
        state.deadline = payload.deadline
        if state.nonce_future and not state.nonce_future.done():
            state.nonce_future.set_result(payload.nonce)

    @lazy_wrapper(RoundResultPayload)
    def _on_round_result(self, peer: Peer, payload: RoundResultPayload) -> None:
        self._cache_server(peer)
        logger.info("[Round %d] RoundResult: success=%s completed=%d/3 msg='%s'",
                    payload.round_number, payload.success,
                    payload.rounds_completed, payload.message)
        state = self._round_states.get(payload.round_number)
        if state and state.result_future and not state.result_future.done():
            state.result_future.set_result(payload.success)
        if payload.rounds_completed == 3:
            self._all_done.set()

    @lazy_wrapper(ReadyPayload)
    def _on_ready(self, peer: Peer, payload: ReadyPayload) -> None:
        sender_key = peer.public_key.key_to_bin()
        if sender_key not in self._member_keys:
            logger.warning("ReadyPayload from unregistered peer, ignored.", payload)
            return
        
        if payload.group_id != self._group_id:
            logger.warning("ReadyPayload group id mismatch.", payload)
            return

        self._cache_teammate(peer, sender_key)
        sender_idx = self._member_keys.index(sender_key)
        if sender_idx == self._my_index:
            return

        self._teammates_ready.add(sender_idx)
        logger.info("Teammate %d is ready (%d/2).", sender_idx, len(self._teammates_ready))
        self._check_all_ready()

    @lazy_wrapper(NonceBroadcastPayload)
    def _on_nonce_broadcast(self, peer: Peer, payload: NonceBroadcastPayload) -> None:
        sender_key = peer.public_key.key_to_bin()
        if sender_key not in self._member_keys:
            logger.warning("NonceBroadcast from unregistered peer, ignored.", payload)
            return

        rn = payload.round_number
        sig = self.crypto.create_signature(self._signing_key, payload.nonce)
        self.ez_send(peer, SignatureSharePayload(
            group_id=self._group_id,
            round_number=rn,
            signature=sig,
        ))
        logger.info("[Round %d] NonceBroadcast received, and replied.", rn)

    @lazy_wrapper(SignatureSharePayload)
    def _on_signature_share(self, peer: Peer, payload: SignatureSharePayload) -> None:
        sender_key = peer.public_key.key_to_bin()
        if sender_key not in self._member_keys:
            logger.warning("SignatureShare from unregistered peer, ignored.", payload)
            return

        rn = payload.round_number
        sender_idx = self._member_keys.index(sender_key)
        logger.info("[Round %d] SignatureShare from member %d.", rn, sender_idx)
        state = self._round_states.get(rn)
        if state is None:
            logger.warning("[Round %d] SignatureShare for unknown round.", rn)
            return

        fut = state.sig_futures.get(sender_idx)
        if fut and not fut.done():
            fut.set_result(payload.signature)

    async def _discover_all_peers(self, timeout: float = 600.0) -> None:
        deadline = time.time() + timeout
        while not self._my_cache_ready:
            if time.time() > deadline:
                raise RuntimeError("Could not discover all peers within %.1f s" % timeout)

            # Search through all peers
            print(f"Amount of current known peers: {len(self.get_peers())}")
            for peer in self.get_peers():
                if self._server_peer is None:
                    if peer.public_key.key_to_bin() == self._server_pk:
                        self._cache_server(peer)
                        break

                if len(self._teammate_peers) < 2:
                    key = peer.public_key.key_to_bin()
                    if key in self._member_keys and key != self._member_keys[self._my_index]:
                        idx = self._member_keys.index(key)
                        if idx not in self._teammate_peers:
                            self._cache_teammate(peer, key)

            await asyncio.sleep(5)

    async def _readiness_handshake(self, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        while not self._all_ready.is_set():
            if time.time() > deadline:
                raise RuntimeError("Readiness handshake timed out after %.1f s" % timeout)

            self._broadcast_ready()
            try:
                await asyncio.wait_for(asyncio.shield(self._all_ready.wait()), timeout=0.2)
            except asyncio.TimeoutError:
                pass  

    def _broadcast_ready(self) -> None:
        payload = ReadyPayload(group_id=self._group_id)
        for peer in self._teammate_peers.values():
            self.ez_send(peer, payload)
        logger.debug("ReadyPayload broadcast to %d teammate(s).", len(self._teammate_peers))

    def _cache_server(self, peer: Peer) -> None:
        if self._server_peer is None:
            self._server_peer = peer
            logger.info("Server peer cached: %s", peer.mid.hex())
            self._check_my_cache_ready()

    def _cache_teammate(self, peer: Peer, raw_key: bytes) -> None:
        idx = self._member_keys.index(raw_key)
        if idx not in self._teammate_peers:
            self._teammate_peers[idx] = peer
            logger.info("Teammate %d cached: %s", idx, peer.mid.hex())
            self._check_my_cache_ready()

    def _check_my_cache_ready(self) -> None:
        if (not self._my_cache_ready and self._server_peer is not None and len(self._teammate_peers) == 2):
            self._my_cache_ready = True
            logger.info("Local peer cache full — announcing readiness to teammates.")
            self._check_all_ready()

    def _check_all_ready(self) -> None:
        if (self._my_cache_ready and len(self._teammates_ready) == 2 and not self._all_ready.is_set()):
            self._all_ready.set()
            logger.info("All 3 members ready.")

    def _teammate_indices(self) -> List[int]:
        return [i for i in (0, 1, 2) if i != self._my_index]

    def _broadcast_nonce(self, round_num: int, nonce: bytes) -> None:
        payload = NonceBroadcastPayload(
            group_id=self._group_id,
            round_number=round_num,
            nonce=nonce,
        )

        for peer in self._teammate_peers.values():
            self.ez_send(peer, payload)

        logger.debug("[Round %d] Broadcasted nonce to all peers")