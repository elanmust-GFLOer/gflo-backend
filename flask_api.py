from flask import Flask, jsonify, request
from flask_cors import CORS
from web3 import Web3
from functools import wraps
import os, requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env"))

from gflo_config import canonical_address  # noqa: E402  (needs env loaded first)

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

# ── Canonical PIE v0.2 read path (fail-closed) ────────────────
# A visszavont Sepolia v3 szerződéseket (PIECore 0x9CF55d…, GasFeeLoop 0xd2C926…)
# a backend NEM olvassa: ott az XP bárki által önkiosztható, a GasFeeLoop pedig
# plutokratikus. Nincs alapértelmezett cím. Amíg a v0.2 nincs nyilvános hálózaton
# deployolva és a három env var be nincs állítva, minden XP/tier végpont 503-at ad,
# és a tier_required kapu MINDEN kérést elutasít.
#   PIE_CORE_ADDRESS        PIECoreIgnitionV01  getIdentity()
#   XP_REGISTRY_ADDRESS     TrustedXPSourceRegistryV02  totalXP()
#   EFFECTIVE_TIER_GATE_ADDRESS  EffectiveTierGateV01  effectiveTier()
PIE_CORE_ADDRESS = canonical_address("PIE_CORE_ADDRESS")
XP_REGISTRY_ADDRESS = canonical_address("XP_REGISTRY_ADDRESS")
EFFECTIVE_TIER_GATE_ADDRESS = canonical_address("EFFECTIVE_TIER_GATE_ADDRESS")

PIE_CORE_ABI = [{
    "inputs": [{"name": "account", "type": "address"}], "name": "getIdentity",
    "outputs": [{"components": [
        {"name": "exists", "type": "bool"}, {"name": "xp", "type": "uint64"},
        {"name": "selectedPath", "type": "uint8"}, {"name": "tier", "type": "uint8"}],
        "name": "", "type": "tuple"}],
    "stateMutability": "view", "type": "function"}]
XP_REGISTRY_ABI = [{
    "inputs": [{"name": "user", "type": "address"}], "name": "totalXP",
    "outputs": [{"name": "", "type": "uint64"}], "stateMutability": "view", "type": "function"}]
TIER_GATE_ABI = [{
    "inputs": [{"name": "wallet", "type": "address"}], "name": "effectiveTier",
    "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"}]

REPUTATION_ENABLED = all((PIE_CORE_ADDRESS, XP_REGISTRY_ADDRESS, EFFECTIVE_TIER_GATE_ADDRESS))
if REPUTATION_ENABLED:
    pie = w3.eth.contract(address=PIE_CORE_ADDRESS, abi=PIE_CORE_ABI)
    xp_registry = w3.eth.contract(address=XP_REGISTRY_ADDRESS, abi=XP_REGISTRY_ABI)
    tier_gate = w3.eth.contract(address=EFFECTIVE_TIER_GATE_ADDRESS, abi=TIER_GATE_ABI)
else:
    pie = xp_registry = tier_gate = None

PATH_NAMES = {0: 'None', 1: 'Sovereign', 2: 'Reformer', 3: 'Praxis'}
UNAVAILABLE = {
    'error': 'canonical_source_unavailable',
    'detail': 'No canonical PIE v0.2 deployment is configured. Legacy v3 XP is self-mintable '
              'and is not served as reputation.',
}


class ReputationUnavailable(Exception):
    pass


def compute_identity(addr):
    """Canonical identity: attested XP via the Registry, privilege via EffectiveTierGate."""
    if not REPUTATION_ENABLED:
        raise ReputationUnavailable()
    exists, _base_xp, selected_path, achieved_tier = pie.functions.getIdentity(addr).call()
    if not exists:
        return {'exists': False, 'xp': 0, 'path': 'None', 'achievedTier': 0, 'effectiveTier': 0}
    return {
        'exists': True,
        'xp': xp_registry.functions.totalXP(addr).call(),
        'path': PATH_NAMES.get(selected_path, 'Unknown'),
        'achievedTier': achieved_tier,   # historical only, never a privilege
        'effectiveTier': tier_gate.functions.effectiveTier(addr).call(),
    }


# ── TIER MIDDLEWARE (fail-closed) ─────────────────────────────
def tier_required(min_tier):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not REPUTATION_ENABLED:
                return jsonify(UNAVAILABLE), 503
            wallet = request.headers.get('X-Wallet-Address') or (request.get_json(silent=True) or {}).get('address', '')
            if not wallet:
                return jsonify({'error': 'Wallet address required'}), 401
            try:
                addr = Web3.to_checksum_address(wallet)
                user_tier = tier_gate.functions.effectiveTier(addr).call()
            except Exception:
                return jsonify({'error': 'Identity check failed'}), 503
            if user_tier < min_tier:
                return jsonify({'error': f'Tier {min_tier} required. Effective tier: {user_tier}.'}), 403
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
        'reputation': 'enabled' if REPUTATION_ENABLED else 'disabled',
        'contracts': {
            'PIECore': PIE_CORE_ADDRESS,
            'XPRegistry': XP_REGISTRY_ADDRESS,
            'EffectiveTierGate': EFFECTIVE_TIER_GATE_ADDRESS,
        },
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
    except Exception:
        return jsonify({'error': 'Invalid address'}), 400
    try:
        return jsonify({'address': addr, 'piecore': compute_identity(addr)})
    except ReputationUnavailable:
        return jsonify(UNAVAILABLE), 503
    except Exception:
        return jsonify({'error': 'Chain read failed'}), 503

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
    data = request.get_json(silent=True) or {}
    message = data.get('message', '')
    address = data.get('address', '')

    context = ""
    if address and REPUTATION_ENABLED:
        try:
            identity = compute_identity(Web3.to_checksum_address(address))
            context = (f"\nUser: XP={identity['xp']}, EffectiveTier={identity['effectiveTier']}, "
                       f"Path={identity['path']}")
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
    if not REPUTATION_ENABLED:
        return jsonify(UNAVAILABLE), 503
    addresses = (request.get_json(silent=True) or {}).get('addresses', [])
    if not isinstance(addresses, list) or not addresses or len(addresses) > 100:
        return jsonify({'error': 'Invalid count (max 100)'}), 400

    results = []
    for addr_str in addresses:
        try:
            addr = Web3.to_checksum_address(addr_str)
            results.append({'address': addr, **compute_identity(addr)})
        except Exception:
            results.append({'address': addr_str, 'error': 'Invalid'})
    return jsonify({'results': results, 'count': len(results)})

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    print("🚀 GFLO Flask API v3.0 — canonical PIE v0.2 read path, legacy v3 disabled")
    print(f"🔗 Blockchain: {'✅ connected' if w3.is_connected() else '❌ disconnected'}")
    print(f"🧬 Reputation: {'enabled' if REPUTATION_ENABLED else 'DISABLED (no canonical deployment configured)'}")
    app.run(host='0.0.0.0', port=5000, debug=False)
