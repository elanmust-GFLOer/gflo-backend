import os
from web3 import Web3
from dotenv import load_dotenv

# Betöltjük a .env fájlt
load_dotenv()

def main():
    rpc_url = os.getenv("SEPOLIA_RPC_URL")
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if w3.is_connected():
        print("--- GFLO Rendszer Ellenőrzés ---")
        print(f"✅ Csatlakozva: {rpc_url}")
        print(f"Aktuális blokkszám: {w3.eth.block_number}")
    else:
        print("❌ Hiba: Nem sikerült csatlakozni! Ellenőrizd a .env fájlt.")

if __name__ == "__main__":
    main()
