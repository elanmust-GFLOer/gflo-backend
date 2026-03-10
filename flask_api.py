from flask import Flask, jsonify, request
from flask_cors import CORS
from web3 import Web3
import random, os, requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env"))

app = Flask(__name__)
CORS(app)

w3 = Web3(Web3.HTTPProvider("https://sepolia.drpc.org"))
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

PIECORE_ADDRESS = "0x9CF55d0b9D61Dc28EF3cb10765CF4b861Cd0991e"
GASFEELOOP_ADDRESS = "0xd2C926F67080D6315b5dbBc7D621d729Cfe8A9C7"

PIECORE_ABI = [
    {"inputs":[{"name":"user","type":"address"}],"name":"getXP","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"user","type":"address"}],"name":"getTier","outputs":[{"name":"","type":"uint8"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"user","type":"address"}],"name":"identities","outputs":[{"name":"xp","type":"uint256"},{"name":"path","type":"uint8"},{"name":"tier","type":"uint8"}],"stateMutability":"view","type":"function"}
]

GASFEELOOP_ABI = [
    {"inputs":[{"name":"user","type":"address"}],"name":"getStake","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"user","type":"address"}],"name":"getAccumulatedXP","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"user","type":"address"}],"name":"getMultiplier","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
]

pie = w3.eth.contract(address=Web3.to_checksum_address(PIECORE_ADDRESS), abi=PIECORE_ABI)
gas = w3.eth.contract(address=Web3.to_checksum_address(GASFEELOOP_ADDRESS), abi=GASFEELOOP_ABI)
PATH_NAMES = {0: 'None', 1: 'Sovereign', 2: 'Reformer', 3: 'Praxis'}

GFLO_SYSTEM_PROMPT = """Te vagy az ElanMust AI – a GFLO Sovereign protokoll filozofikus tanácsadója.
A GFLO egy Web3 identitás protokoll, ahol:
- XP = tapasztalat = identitás (nem vásárolható, csak szerezhető)
- Három út: Sovereign (kezdő), Reformer (kreátor), Praxis (építő)
- Token burn = commitment bizonyítása
- Anti-plutokrata: a gazdagság nem ad előnyt, csak az aktivitás
- Filozofiai alap: Nietzsche (Übermensch, Amor Fati, Örök Visszatérés)
Válaszolj magyarul, tömören, inspirálóan. #NietzscheWeb3"""

@app.route('/api/status')
def status():
    return jsonify({
        'status': 'operational',
        'blockchain': 'connected' if w3.is_connected() else 'disconnected',
        'ai': 'groq' if GROQ_API_KEY else 'mock',
        'network': 'sepolia',
        'contracts': {
            'PIECore': PIECORE_ADDRESS,
            'GasFeeLoop': GASFEELOOP_ADDRESS
        }
    })

@app.route('/api/identity/<address>')
def get_identity(address):
    try:
        addr = Web3.to_checksum_address(address)
        xp = pie.functions.getXP(addr).call()
        tier = pie.functions.getTier(addr).call()
        identity = pie.functions.identities(addr).call()
        stake = gas.functions.getStake(addr).call()
        accumulated_xp = gas.functions.getAccumulatedXP(addr).call()
        multiplier = gas.functions.getMultiplier(addr).call()
        return jsonify({
            'address': address,
            'xp': xp / 1e18,
            'tier': tier,
            'path': PATH_NAMES.get(identity[1], 'Unknown'),
            'stake': stake / 1e18,
            'accumulated_xp': accumulated_xp / 1e18,
            'multiplier': multiplier / 1e18,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/paths')
def paths():
    return jsonify({'paths': [
        {'name': 'Sovereign', 'xp': 50000, 'emoji': '🌊'},
        {'name': 'Reformer', 'xp': 100000, 'emoji': '🔥'},
        {'name': 'Praxis', 'xp': 200000, 'emoji': '🔧'}
    ]})

@app.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    data = request.json
    message = data.get('message', '')
    address = data.get('address', '')

    context = ""
    if address:
        try:
            addr = Web3.to_checksum_address(address)
            xp = pie.functions.getXP(addr).call() / 1e18
            tier = pie.functions.getTier(addr).call()
            identity = pie.functions.identities(addr).call()
            path = PATH_NAMES.get(identity[1], 'None')
            context = f"\nA felhasználó adatai: XP={xp}, Tier={tier}, Path={path}"
        except:
            pass

    if GROQ_API_KEY:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": GFLO_SYSTEM_PROMPT + context},
                        {"role": "user", "content": message}
                    ],
                    "max_tokens": 300,
                    "temperature": 0.7
                },
                timeout=10
            )
            result = resp.json()
            ai_response = result['choices'][0]['message']['content']
            return jsonify({'response': ai_response, 'source': 'groq', 'model': 'llama-3.1-8b-instant'})
        except Exception as e:
            return jsonify({'response': f'AI hiba: {str(e)}', 'source': 'error'}), 500
    else:
        return jsonify({'response': 'GROQ_API_KEY hiányzik!', 'source': 'mock'})

if __name__ == '__main__':
    print("🚀 GFLO Flask API Starting...")
    print(f"🔗 Blockchain: {'connected' if w3.is_connected() else 'disconnected'}")
    print(f"🤖 AI: {'GROQ' if GROQ_API_KEY else 'mock'}")
    app.run(host='0.0.0.0', port=5000, debug=True)
