"""
GFLO Backend - XP Reward Scheduler & Event Monitor
Handles automated XP distribution to stakers and event tracking
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from web3 import Web3
from web3.contract import Contract
from dotenv import load_dotenv
import schedule
import time
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

load_dotenv()

# ============================================
# LOGGING SETUP
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('gflo_scheduler')

# ============================================
# CONFIGURATION
# ============================================

RPC_URL = os.getenv("SEPOLIA_RPC_URL", "https://sepolia.drpc.org")
PRIVATE_KEY = os.getenv("SCHEDULER_PRIVATE_KEY", "")
REWARD_AMOUNT = int(os.getenv("DAILY_REWARD_AMOUNT", "100")) * 10**18  # Default 100 XP

PIECORE_ADDRESS = os.getenv("PIECORE_ADDRESS", "0x9CF55d0b9D61Dc28EF3cb10765CF4b861Cd0991e")
GASFEELOOP_ADDRESS = os.getenv("GASFEELOOP_ADDRESS", "0xd2C926F67080D6315b5dbBc7D621d729Cfe8A9C7")

# Log paths
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
EVENTS_LOG = LOG_DIR / "events.jsonl"
REWARDS_LOG = LOG_DIR / "rewards.json"
STATE_FILE = LOG_DIR / "scheduler_state.json"

# ============================================
# CONTRACT ABIs
# ============================================

GASFEELOOP_ABI = [
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "getStake",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "getUserInfo",
        "outputs": [
            {"name": "stakeAmount", "type": "uint256"},
            {"name": "multiplier", "type": "uint256"},
            {"name": "accumulatedXP", "type": "uint256"},
            {"name": "currentEpochXP", "type": "uint256"},
            {"name": "remainingEpochXP", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "user", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "rewardXP",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "users", "type": "address[]"},
            {"name": "amounts", "type": "uint256[]"}
        ],
        "name": "batchRewardXP",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

PIECORE_ABI = [
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "getIdentity",
        "outputs": [
            {"name": "xp", "type": "uint256"},
            {"name": "path", "type": "uint8"},
            {"name": "tier", "type": "uint8"},
            {"name": "nextThreshold", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

# ============================================
# DATA MODELS
# ============================================

@dataclass
class RewardRecord:
    timestamp: str
    user: str
    amount: int
    tx_hash: Optional[str] = None
    status: str = "pending"

@dataclass
class EventRecord:
    timestamp: str
    event_type: str
    user: str
    data: Dict

# ============================================
# SCHEDULER CLASS
# ============================================

class GFLOScheduler:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        self.account = None
        
        if PRIVATE_KEY:
            self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
            logger.info(f"✅ Scheduler account: {self.account.address}")
        else:
            logger.warning("⚠️ No PRIVATE_KEY - rewards disabled")
        
        # Initialize contracts
        self.gas_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(GASFEELOOP_ADDRESS),
            abi=GASFEELOOP_ABI
        )
        
        self.pie_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(PIECORE_ADDRESS),
            abi=PIECORE_ABI
        )
        
        self.rewards_log = self._load_rewards_log()
        logger.info(f"🚀 GFLO Scheduler initialized")
    
    # ============================================
    # UTILITY FUNCTIONS
    # ============================================
    
    def _load_rewards_log(self) -> Dict:
        """Load rewards log from file"""
        if REWARDS_LOG.exists():
            return json.loads(REWARDS_LOG.read_text())
        return {"rewards": [], "total_distributed": 0}
    
    def _save_rewards_log(self):
        """Save rewards log to file"""
        REWARDS_LOG.write_text(json.dumps(self.rewards_log, indent=2))
    
    def _log_event(self, event_type: str, user: str, data: Dict):
        """Log event to JSONL"""
        record = EventRecord(
            timestamp=datetime.utcnow().isoformat(),
            event_type=event_type,
            user=user,
            data=data
        )
        with open(EVENTS_LOG, 'a') as f:
            f.write(json.dumps(asdict(record)) + '\n')
        logger.info(f"📝 Event logged: {event_type} for {user}")
    
    def _save_state(self, state: Dict):
        """Save scheduler state"""
        STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    
    def _load_state(self) -> Dict:
        """Load scheduler state"""
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
        return {"last_reward_run": None, "stakers_count": 0}
    
    # ============================================
    # STAKER DETECTION
    # ============================================
    
    def get_stakers(self, from_block: int = None, to_block: int = None) -> List[str]:
        """
        Get list of active stakers by monitoring Staked events
        Note: This is a basic implementation. Enhance with event filters as needed.
        """
        try:
            if from_block is None:
                from_block = self.w3.eth.block_number - 100000  # Last ~100k blocks
            if to_block is None:
                to_block = self.w3.eth.block_number
            
            # Try to get Staked events from contract
            # This requires the contract to have event logs enabled
            logger.info(f"🔍 Scanning for stakers from block {from_block} to {to_block}")
            
            # Placeholder: In production, monitor event logs or maintain a database
            # For now, return empty list (must be populated externally)
            return []
        except Exception as e:
            logger.error(f"❌ Error getting stakers: {e}")
            return []
    
    # ============================================
    # REWARD DISTRIBUTION
    # ============================================
    
    def reward_staker(self, user_address: str, amount: int = REWARD_AMOUNT) -> Optional[str]:
        """
        Reward a single staker with XP
        """
        if not self.account:
            logger.warning("⚠️ Cannot reward: no account configured")
            return None
        
        try:
            user_addr = Web3.to_checksum_address(user_address)
            
            # Check if user has stake
            stake = self.gas_contract.functions.getStake(user_addr).call()
            if stake == 0:
                logger.warning(f"⏭️ Skipping {user_address}: no stake")
                return None
            
            # Get user info
            user_info = self.gas_contract.functions.getUserInfo(user_addr).call()
            remaining_xp = user_info[4]  # remainingEpochXP
            
            # Adjust reward if it exceeds remaining epoch cap
            actual_reward = min(amount, remaining_xp)
            
            if actual_reward == 0:
                logger.warning(f"⏭️ Skipping {user_address}: epoch XP cap reached")
                self._log_event("EPOCH_CAP_REACHED", user_address, {"remaining_xp": remaining_xp})
                return None
            
            # Build transaction
            tx = self.gas_contract.functions.rewardXP(user_addr, actual_reward).build_transaction({
                'from': self.account.address,
                'gas': 100000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.account.address)
            })
            
            # Sign and send
            signed_tx = self.w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # Wait for receipt
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt['status'] == 1:
                logger.info(f"✅ Rewarded {user_address}: {actual_reward / 1e18} XP (tx: {tx_hash.hex()})")
                
                # Log reward
                reward_record = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "user": user_address,
                    "amount": actual_reward,
                    "tx_hash": tx_hash.hex(),
                    "status": "success"
                }
                self.rewards_log["rewards"].append(reward_record)
                self.rewards_log["total_distributed"] += actual_reward
                self._save_rewards_log()
                
                self._log_event("REWARD_DISTRIBUTED", user_address, {
                    "amount": actual_reward,
                    "tx_hash": tx_hash.hex()
                })
                
                return tx_hash.hex()
            else:
                logger.error(f"❌ Transaction failed for {user_address}")
                self._log_event("REWARD_FAILED", user_address, {"tx_hash": tx_hash.hex()})
                return None
        
        except Exception as e:
            logger.error(f"❌ Error rewarding {user_address}: {e}")
            self._log_event("REWARD_ERROR", user_address, {"error": str(e)})
            return None
    
    def batch_reward_stakers(self, stakers: List[str], amounts: Optional[List[int]] = None) -> int:
        """
        Reward multiple stakers in one transaction
        """
        if not self.account:
            logger.warning("⚠️ Cannot batch reward: no account configured")
            return 0
        
        if not stakers:
            logger.info("ℹ️ No stakers to reward")
            return 0
        
        if amounts is None:
            amounts = [REWARD_AMOUNT] * len(stakers)
        
        try:
            addresses = [Web3.to_checksum_address(addr) for addr in stakers]
            
            # Build transaction
            tx = self.gas_contract.functions.batchRewardXP(addresses, amounts).build_transaction({
                'from': self.account.address,
                'gas': 500000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.account.address)
            })
            
            # Sign and send
            signed_tx = self.w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # Wait for receipt
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt['status'] == 1:
                total_amount = sum(amounts)
                logger.info(f"✅ Batch rewarded {len(stakers)} stakers: {total_amount / 1e18} XP (tx: {tx_hash.hex()})")
                
                # Log each reward
                for addr, amount in zip(stakers, amounts):
                    reward_record = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "user": addr,
                        "amount": amount,
                        "tx_hash": tx_hash.hex(),
                        "status": "success"
                    }
                    self.rewards_log["rewards"].append(reward_record)
                    self.rewards_log["total_distributed"] += amount
                
                self._save_rewards_log()
                
                self._log_event("BATCH_REWARD_DISTRIBUTED", self.account.address, {
                    "stakers_count": len(stakers),
                    "total_amount": total_amount,
                    "tx_hash": tx_hash.hex()
                })
                
                return len(stakers)
            else:
                logger.error(f"❌ Batch transaction failed")
                return 0
        
        except Exception as e:
            logger.error(f"❌ Error in batch reward: {e}")
            return 0
    
    # ============================================
    # SCHEDULED JOBS
    # ============================================
    
    def daily_reward_job(self):
        """
        Daily job: Reward active stakers
        Should be called once per day
        """
        logger.info("⏰ Running daily reward job...")
        
        state = self._load_state()
        
        # TODO: Integrate with your staker database/tracking system
        # For now, this is a placeholder
        
        logger.info("✅ Daily reward job completed")
        
        state["last_reward_run"] = datetime.utcnow().isoformat()
        self._save_state(state)
    
    def health_check_job(self):
        """
        Periodic health check: Verify blockchain connection and log status
        """
        try:
            if self.w3.is_connected():
                block = self.w3.eth.block_number
                logger.info(f"✅ Health check: Connected at block {block}")
                
                self._log_event("HEALTH_CHECK", "scheduler", {
                    "block_number": block,
                    "status": "healthy"
                })
            else:
                logger.error("❌ Health check: Not connected!")
                self._log_event("HEALTH_CHECK", "scheduler", {"status": "disconnected"})
        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
    
    # ============================================
    # SCHEDULER START
    # ============================================
    
    def start(self):
        """Start the scheduler with recurring jobs"""
        logger.info("🚀 Starting GFLO Scheduler...")
        
        # Schedule jobs
        schedule.every().day.at("00:00").do(self.daily_reward_job)
        schedule.every(5).minutes.do(self.health_check_job)
        
        logger.info("📅 Jobs scheduled")
        
        # Run scheduler loop
        while True:
            try:
                schedule.run_pending()
                time.sleep(60)
            except Exception as e:
                logger.error(f"❌ Scheduler error: {e}")
                time.sleep(60)

# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    scheduler = GFLOScheduler()
    scheduler.start()
