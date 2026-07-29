from flask import Flask, jsonify, request
from flask_cors import CORS
from web3 import Web3
from functools import wraps
import os, requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env"))

app = Flask(__name__)
CORS(app)

# ── FAUCET BLUEPRINT ──────────────────────────────────────────
try:
    from gflo_faucet import faucet_bp
    app.register_blueprint(faucet_bp)
    print("✅ Faucet blueprint registered")
except ImportError:
    print("⚠️ Faucet blueprint not found")

# Web3 Setup
RPC_URL = os.getenv("SEPOLIA_RPC_URL", "https://sepolia.drpc.org")
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# Contract Addresses
# NOTE: GFLOGNITION_ADDRESS eltávolítva — bytecode-szinten bizonyított, hogy
# ez a cím a PIECore egy redundáns/árva duplikátuma, NEM egy külön GFLOIgnition
# kontraktus. Nincs semmi hívható rajta, amit a PIECore ne tudna.
PIECORE_ADDRESS = os.getenv("PIECORE_ADDRESS", "0x9CF55d0b9D61Dc28EF3cb10765CF4b861Cd0991e")
GASFEELOOP_ADDRESS = os.getenv("GASFEELOOP_ADDRESS", "0xd2C926F67080D6315b5dbBc7D621d729Cfe8A9C7")

# ── PIECore ABI — a TÉNYLEGESEN DEPLOYOLT kontraktushoz igazítva ──
# Ez az ABI 14/14 function selectorban bizonyítottan egyezik a Sepolia-n
# élő 0x9CF55d... bytecode-dal (lásd: gflo-pie/contracts/PIECore.sol).
# NINCS getIdentity()/isEligibleForUpgrade()/getPath() a láncon — ezeket
# lentebb Pythonban számoljuk ki az identities()/getXP()/getTier() alapján.
PIECORE_ABI = [
    {"inputs": [{"name": "user", "type": "address"}], "name": "getXP", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "user", "type": "address"}], "name": "getTier", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "", "type": "address"}], "name": "identities", "outputs": [
        {"name": "xp", "type": "uint256"}, {"name": "path", "type": "uint8"}, {"name": "tier", "type": "uint8"}
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "SOVEREIGN_TIER1_XP", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "REFORMER_BURN_AMOUNT", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

# GasFeeLoop ABI (ez a kontraktus bytecode-szinten megerősítve rendben van, változatlan)
GASFEELOOP_ABI = [
    {"inputs": [{"name": "user", "type": "address"}], "name": "getStake", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "user", "type": "address"}], "name": "getAccumulatedXP", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "user", "type": "address"}], "name": "getMultiplier", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "user", "type": "address"}], "name": "getUserInfo", "outputs": [
        {"name": "stakeAmount", "type": "uint256"}, {"name": "multiplier", "type": "uint256"},
        {"name": "accumulatedXP", "type": "uint256"}, {"name": "currentEpochXP", "type": "uint256"},
        {"name": "remainingEpochXP", "type": "uint256"}
    ], "stateMutability": "view", "type": "function"},
]

PATH_NAMES = {0: 'None', 1: 'Sovereign', 2: 'Reformer', 3: 'Praxis'}

# A Praxis-küszöbök a szerződésben hardcode-olva vannak (nincs public getterük),
# ezért itt is hardcode-oljuk — ha a szerződés valaha frissül, ezt is frissíteni kell.
PRAXIS_XP_REQUIRED = 5000
PRAXIS_BURN_AMOUNT_WEI = 10000 * 10**18

pie = w3.eth.contract(address=Web3.to_checksum_address(PIECORE_ADDRESS), abi=PIECORE_ABI)
gas = w3.eth.contract(address=Web3.to_checksum_address(GASFEELOOP_ADDRESS), abi=GASFEELOOP_ABI)


def compute_identity(addr):
    """
    A valódi, deployolt PIECore-on NINCS getIdentity()/isEligibleForUpgrade().
    Ezt itt szimuláljuk: 1 db identities() hívásból (xp, path, tier) kiszámoljuk
    ugyanazt, amit egy 'v2' kontraktus getIdentity()-je adna, plusz az
    upgrade-jogosultságot a szerződés require()-jeivel megegyező logikával.
    """
    xp, path, tier = pie.functions.identities(addr).call()
    sovereign_tier1_xp = pie.functions.SOVEREIGN_TIER1_XP().call()

    eligible = False
    next_threshold = None
    next_action = None

    if path == 1:  # Sovereign -> Reformer
        eligible = xp >= sovereign_tier1_xp
        next_threshold = sovereign_tier1_xp
        next_action = "upgradeToReformer"
    elif path == 2:  # Reformer -> Praxis
        eligible = xp >= PRAXIS_XP_REQUIRED
        next_threshold = PRAXIS_XP_REQUIRED
        next_action = "upgradeToPraxis"
    elif path == 3:  # Praxis — jelenleg nincs magasabb szint
        eligible = False
        next_threshold = None
        next_action = None

    return {
        'xp': xp,
        'path': PATH_NAMES.get(path, 'Unknown'),
        'tier': tier,
        'eligibleForUpgrade': eligible,
        'nextThreshold': next_threshold,
        'nextAction': next_action,
    }


# ── TIER MIDDLEWARE ─────────────────────────────────────────
def tier_required(min_tier):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            wallet = request.headers.get('X-Wallet-Address') or (request.json or {}).get('address', '')
            if not wallet:
                return jsonify({'error': 'Wallet address required'}), 401
            try:
                addr = Web3.to_checksum_address(wallet)
                user_tier = pie.functions.getTier(addr).call()
                if user_tier < min_tier:
                    return jsonify({'error': f'Tier {min_tier} required. You are Tier {user_tier}.'}), 403
            except Exception as e:
                return jsonify({'error': f'Identity check failed: {str(e)}'}), 400
            return f(*args, **kwargs)
        return decorated
    return decorator

# ── AI SYSTEM PROMPT ──────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GFLO_SYSTEM_PROMPT = """You are ElanMust AI — philosophical advisor to the GFLO Sovereign protocol.
Core principles: Activity → XP → Identity → Sovereignty. Anti-plutocratic: wealth gives no advantage, only activity matters. Three Paths: Sovereign (consistency), Reformer (social impact), Praxis (building, +20% XP). Philosophical foundation: Nietzsche (Übermensch, Amor Fati, Eternal Recurrence). Respond concisely, inspiringly, in the user's language. #NietzscheWeb3"""

# ═══ ENDPOINTS ═══════════════════════════════════════════════

@app.route('/api/status')
def status():
    return jsonify({
        'status': 'operational',
        'blockchain': 'connected' if w3.is_connected() else 'disconnected',
        'network': 'sepolia',
        'contracts': {'PIECore': PIECORE_ADDRESS, 'GasFeeLoop': GASFEELOOP_ADDRESS}
    })

@app.route('/api/health')
def health():
    try:
        block = w3.eth.block_number
        return jsonify({'status': 'healthy', 'block': block})
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 503

@app.route('/api/identity/<address>')
def get_identity(address):
    try:
        addr = Web3.to_checksum_address(address)
        identity = compute_identity(addr)
        stake_info = gas.functions.getUserInfo(addr).call()

        return jsonify({
            'address': address,
            'piecore': identity,
            'gasfeeloop': {
                'stakeAmount': stake_info[0] / 1e18,
                'multiplier': stake_info[1] / 1e18,
                'accumulatedXP': stake_info[2] / 1e18,
                'currentEpochXP': stake_info[3] / 1e18,
                'remainingEpochXP': stake_info[4] / 1e18,
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/paths')
def paths_info():
    return jsonify({
        'paths': [
            {'id': 1, 'name': 'Sovereign', 'emoji': '🌊', 'description': 'Self-mastery · Consistency-based', 'entryCostGFLO': 3000, 'tierThresholds': {'tier2': 4000, 'tier3': 7000, 'tier4': 15000}},
            {'id': 2, 'name': 'Reformer', 'emoji': '🔥', 'description': 'Creative transformation · Social impact', 'entryCostGFLO': 6000, 'tierThresholds': {'tier2': 4000, 'tier3': 7000, 'tier4': 15000}},
            {'id': 3, 'name': 'Praxis', 'emoji': '🔧', 'description': 'Building & implementation · Output-based (+20% XP)', 'entryCostGFLO': 9000, 'tierThresholds': {'tier2': 4000, 'tier3': 7000, 'tier4': 15000}}
        ],
        'rePath': {
            'available': True,
            'costGFLO': 500,
            'costDistribution': '50% burn · 50% treasury',
            'tierPenalty': -1,
            'xpRetention': '100%',
            'requirements': 'Community nomination (5x Tier 3+) · DAO vote · 30 days min on current path',
            'implemented': False,  # ŐSZINTÉN: ez ma még csak terv, nincs mögötte on-chain/backend logika
        }
    })

@app.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    data = request.json
    message = data.get('message', '')
    address = data.get('address', '')

    context = ""
    if address:
        try:
            addr = Web3.to_checksum_address(address)
            identity = compute_identity(addr)
            context = f"\nUser: XP={identity['xp']}, Tier={identity['tier']}, Path={identity['path']}"
        except Exception:
            pass

    if GROQ_API_KEY:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "system", "content": GFLO_SYSTEM_PROMPT + context}, {"role": "user", "content": message}], "max_tokens": 500, "temperature": 0.7},
                timeout=10
            )
            result = resp.json()
            return jsonify({'response': result['choices'][0]['message']['content'], 'source': 'groq', 'model': 'llama-3.3-70b-versatile'})
        except Exception as e:
            return jsonify({'response': f'AI error: {str(e)}', 'source': 'error'}), 500
    else:
        return jsonify({'response': 'GROQ_API_KEY missing', 'source': 'mock'})

@app.route('/api/batch/identities', methods=['POST'])
def batch_identities():
    try:
        addresses = request.json.get('addresses', [])
        if not addresses or len(addresses) > 100:
            return jsonify({'error': 'Invalid count (max 100)'}), 400

        results = []
        for addr_str in addresses:
            try:
                addr = Web3.to_checksum_address(addr_str)
                identity = compute_identity(addr)
                results.append({'address': addr_str, **identity})
            except Exception:
                results.append({'address': addr_str, 'error': 'Invalid'})

        return jsonify({'results': results, 'count': len(results)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    print("🚀 GFLO Flask API v2.1 — élő PIECore ABI-hoz igazítva")
    print(f"🔗 Blockchain: {'✅ connected' if w3.is_connected() else '❌ disconnected'}")
    print(f"🌐 RPC: {RPC_URL}")
    app.run(host='0.0.0.0', port=5000, debug=False)

