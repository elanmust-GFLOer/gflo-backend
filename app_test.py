from web3 import Web3

def main():
    # Közvetlen, publikus Sepolia RPC
    url = "https://ethereum-sepolia-rpc.publicnode.com"
    w3 = Web3(Web3.HTTPProvider(url))
    
    print(f"--- Csatlakozás kísérlet ide: {url} ---")
    if w3.is_connected():
        print(f"✅ SIKER!")
        print(f"Aktuális blokkszám: {w3.eth.block_number}")
    else:
        print("❌ Hálózati hiba: A Termux nem éri el ezt az URL-t.")

if __name__ == "__main__":
    main()
