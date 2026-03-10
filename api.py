from flask import Flask, jsonify
from flask_cors import CORS
from ai.gflo_ai_core import GFLOAICore

app = Flask(__name__)
CORS(app) 
ai_core = GFLOAICore()

@app.route('/stats')
def get_stats():
    return jsonify({
        "status": "AI Core Active",
        "xp_fraud": "Clean",
        "network": "Sepolia L2"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
