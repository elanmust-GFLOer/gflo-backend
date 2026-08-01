"""
GFLO Faucet — Sepolia testnet token distribution endpoint
=============================================================
Skeleton implementation for the GFLO Sovereign faucet.
Built to integrate into the existing Flask backend (gflo-clean).

Required environment variables:
    SEPOLIA_RPC_URL       - QuickNode (or other) Sepolia RPC endpoint
    FAUCET_PRIVATE_KEY    - private key of the funded faucet wallet
                             (NEVER commit this. Use Railway/Render secrets.)
    GFLO_TOKEN_ADDRESS    - defaults to the known deployed GFLOToken address
    FAUCET_CLAIM_AMOUNT   - GFLO tokens per claim (default: 100)
    FAUCET_COOLDOWN_HOURS - hours between claims per wallet (default: 24)

Assumptions (easy to change — flag if wrong):
    - One claim per wallet address per cooldown window
    - No captcha in this skeleton (add hCaptcha/Turnstile before going public)
    - Claims persisted to a local JSON file (swap for Redis/Postgres before scale)
    - web3.py v6+ (uses signed.raw_transaction, not rawTransaction)

Install:
    pip install web3 eth-account flask
"""

import os
import json
import time
import logging
from pathlib import Path
from threading import Lock

from flask import Blueprint, request, jsonify
from web3 import Web3
from eth_account import Account

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RPC_URL = os.environ.get("SEPOLIA_RPC_URL")
PRIVATE_KEY = os.environ.get("FAUCET_PRIVATE_KEY")
GFLO_TOKEN_ADDRESS = os.environ.get(
    "GFLO_TOKEN_ADDRESS", "0x563b2e3b499818a2f84c472efb3169a2667807fe"
)
CLAIM_AMOUNT = int(os.environ.get("FAUCET_CLAIM_AMOUNT", "100"))
COOLDOWN_HOURS = int(os.environ.get("FAUCET_COOLDOWN_HOURS", "24"))

CLAIMS_LOG_PATH = Path(__file__).parent / "faucet_claims.json"
EVENT_LOG_PATH = Path(__file__).parent / "faucet_events.jsonl"

ERC20_TRANSFER_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gflo_faucet")

faucet_bp = Blueprint("faucet", __name__)
_lock = Lock()

# ---------------------------------------------------------------------------
# Web3 setup
# ---------------------------------------------------------------------------

w3 = None
token_contract = None
faucet_account = None

if RPC_URL and PRIVATE_KEY:
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    faucet_account = Account.from_key(PRIVATE_KEY)
    token_contract = w3.eth.contract(
        address=Web3.to_checksum_address(GFLO_TOKEN_ADDRESS), abi=ERC20_TRANSFER_ABI
    )
else:
    logger.warning(
        "SEPOLIA_RPC_URL / FAUCET_PRIVATE_KEY missing — faucet running in DRY-RUN mode."
    )

# ---------------------------------------------------------------------------
# Persistence helpers (swap for Redis/Postgres before mainnet)
# ---------------------------------------------------------------------------

def _load_claims():
    if CLAIMS_LOG_PATH.exists():
        return json.loads(CLAIMS_LOG_PATH.read_text())
    return {}


def _save_claims(claims):
    CLAIMS_LOG_PATH.write_text(json.dumps(claims, indent=2))


def _log_event(event: dict):
    event["timestamp"] = time.time()
    with EVENT_LOG_PATH.open("a") as f:
        f.write(json.dumps(event) + "\n")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@faucet_bp.route("/api/faucet/claim", methods=["POST"])
def claim():
    data = request.get_json(silent=True) or {}
    wallet = data.get("wallet_address", "").strip()

    if not wallet or not Web3.is_address(wallet):
        return jsonify({"error": "invalid wallet_address"}), 400

    wallet = Web3.to_checksum_address(wallet)

    with _lock:
        claims = _load_claims()
        last_claim = claims.get(wallet)
        now = time.time()

        if last_claim and (now - last_claim) < COOLDOWN_HOURS * 3600:
            remaining = COOLDOWN_HOURS * 3600 - (now - last_claim)
            return jsonify({
                "error": "cooldown_active",
                "retry_after_seconds": int(remaining),
            }), 429

        if w3 is None:
            # Dry-run mode — no RPC/key configured yet, but flow is testable end-to-end
            _log_event({"wallet": wallet, "amount": CLAIM_AMOUNT, "status": "dry_run"})
            claims[wallet] = now
            _save_claims(claims)
            return jsonify({"status": "dry_run", "wallet": wallet, "amount": CLAIM_AMOUNT})

        try:
            decimals = token_contract.functions.decimals().call()
            amount_wei = CLAIM_AMOUNT * (10 ** decimals)

            nonce = w3.eth.get_transaction_count(faucet_account.address)
            tx = token_contract.functions.transfer(wallet, amount_wei).build_transaction({
                "from": faucet_account.address,
                "nonce": nonce,
                "gas": 100000,
                "gasPrice": w3.eth.gas_price,
            })
            signed = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

            claims[wallet] = now
            _save_claims(claims)
            _log_event({
                "wallet": wallet,
                "amount": CLAIM_AMOUNT,
                "tx_hash": tx_hash.hex(),
                "status": "sent",
            })

            return jsonify({
                "status": "sent",
                "wallet": wallet,
                "amount": CLAIM_AMOUNT,
                "tx_hash": tx_hash.hex(),
            })

        except Exception as e:
            logger.exception("Faucet claim failed")
            _log_event({"wallet": wallet, "status": "error", "error": str(e)})
            return jsonify({"error": "transaction_failed", "detail": str(e)}), 500


@faucet_bp.route("/api/faucet/status/<wallet_address>", methods=["GET"])
def status(wallet_address):
    if not Web3.is_address(wallet_address):
        return jsonify({"error": "invalid wallet_address"}), 400

    wallet = Web3.to_checksum_address(wallet_address)
    claims = _load_claims()
    last_claim = claims.get(wallet)

    if not last_claim:
        return jsonify({"eligible": True})

    now = time.time()
    elapsed = now - last_claim
    cooldown_seconds = COOLDOWN_HOURS * 3600

    if elapsed >= cooldown_seconds:
        return jsonify({"eligible": True})

    return jsonify({
        "eligible": False,
        "retry_after_seconds": int(cooldown_seconds - elapsed),
    })


# ---------------------------------------------------------------------------
# Integration — in your main Flask app (e.g. app.py in gflo-clean):
#
#   from backend.gflo_faucet import faucet_bp
#   app.register_blueprint(faucet_bp)
#
# Then on Railway, set env vars:
#   SEPOLIA_RPC_URL, FAUCET_PRIVATE_KEY, GFLO_TOKEN_ADDRESS (optional)
# ---------------------------------------------------------------------------
