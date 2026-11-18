"""Shared contract-address configuration for the GFLO backend.

Fail-closed rule: an address is usable only if it is explicitly configured,
well-formed, and NOT one of the retired Sepolia v3 contracts. There are no
hard-coded defaults, so a missing Railway variable disables the feature
instead of silently falling back to a deprecated contract.

Retired v3 contracts (see gflo-pie/docs/DECISION-001-v3-retirement.md):
  PIECore v3   - public gainXP(): anyone can mint unlimited XP
  GFLOIgnition - always reverts against PIECore v3
  GasFeeLoop   - stake-multiplied XP, rejected as plutocratic
  GFLOToken    - MockGFLOToken with open faucet() mint, no burn
"""

import logging
import os

from web3 import Web3

logger = logging.getLogger("gflo_config")

DEPRECATED_V3_ADDRESSES = frozenset(a.lower() for a in (
    "0x9CF55d0b9D61Dc28EF3cb10765CF4b861Cd0991e",  # PIECore v3
    "0x414DEDcf9264614Fd087BDa58bE27a0B698CcC54",  # GFLOIgnition (v3)
    "0xd2C926F67080D6315b5dbBc7D621d729Cfe8A9C7",  # GasFeeLoop
    "0x563b2e3b499818a2f84c472efb3169a2667807fe",  # GFLOToken / MockGFLOToken
))


def is_deprecated(address: str) -> bool:
    return bool(address) and address.strip().lower() in DEPRECATED_V3_ADDRESSES


def canonical_address(env_name: str):
    """Return the checksummed address from env_name, or None if unusable."""
    raw = (os.getenv(env_name) or "").strip()
    if not raw:
        return None
    if is_deprecated(raw):
        logger.error("%s points at a retired v3 contract (%s); refusing to use it.", env_name, raw)
        return None
    if not Web3.is_address(raw):
        logger.error("%s is not a valid address; ignoring it.", env_name)
        return None
    return Web3.to_checksum_address(raw)
