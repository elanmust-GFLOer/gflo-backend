# GFLO Backend (`gflo-backend`)

**Ez a repó fut élesben.** Railway service: `web-gflo-sov-f4a65.up.railway.app`
Deploy forrás: `gflo-backend` / `master` ág · Start: `Procfile` → `web: python flask_api.py`

Jelölések: ✅ ÉLŐ · ⚠️ RÉSZLEGES/NEM FUT · ❌ HIÁNYZIK/TÖRÖTT

---

## Fájlok

| Fájl | Állapot | Megjegyzés |
|---|---|---|
| `flask_api.py` | ✅ ÉLŐ | A ténylegesen futó Flask API. **v2.1**: a PIECore-hívások a valóban deployolt kontraktus ABI-jához igazítva (`getXP`/`getTier`/`identities`) — nem a nem létező `getIdentity()`-hez. |
| `gflo_faucet.py` | ❌ **HIÁNYZIK** | A `flask_api.py` importálja (`from gflo_faucet import faucet_bp`), de a fájl **nincs ebben a repóban**. A faucet-végpontok emiatt jelenleg nem léteznek. **TODO: fel kell tölteni.** |
| `gflo_scheduler.py` | ⚠️ NEM FUT | XP-reward automatizáló (a `GasFeeLoop.stake()` → `rewardXP()` hiányzó láncszem). A `Procfile` **nem indítja el** — csak egy fájl a repóban, nem egy futó folyamat. A `schedule` csomag sincs a `requirements.txt`-ben, tehát jelenleg futtatva is hibázna. |
| `api.py` | ❌ TÖRÖTT, nem használt | `from ai.gflo_ai_core import GFLOAICore`-t importál, de nincs `ai/` mappa ebben a repóban. Semmi nem hívja, biztonságosan törölhető. |
| `app.py`, `app_test.py` | — | Egyszeri RPC-kapcsolat diagnosztikai szkriptek, nem részei az élő API-nak. |
| `requirements.txt` | ⚠️ HIÁNYOS | Hiányzik: `eth-account` (a `gflo_faucet.py`-hoz kell) és `schedule` (a `gflo_scheduler.py`-hoz kell, ha valaha elindítod). |
| `Procfile` | ✅ | `web: python flask_api.py` — ez az EGYETLEN dolog, amit a Railway ténylegesen elindít. |

---

## Kontraktus-címek

| Név | Cím | Állapot |
|---|---|---|
| PIECore | `0x9CF55d0b9D61Dc28EF3cb10765CF4b861Cd0991e` | ✅ Bytecode-szinten, 14/14 function selectorral megerősítve (forrás: `gflo-pie/contracts/PIECore.sol`) |
| GasFeeLoop | `0xd2C926F67080D6315b5dbBc7D621d729Cfe8A9C7` | ✅ Bytecode-szinten megerősítve |
| ~~GFLOIgnition~~ | ~~`0x414DEDcf9264614Fd087BDa58bE27a0B698CcC54`~~ | ❌ **Nem létezik önálló szerződésként.** Ez a cím a PIECore egy redundáns/árva duplikátuma — bytecode-for-bytecode azonos vele. A burn/tier-upgrade logika a PIECore-ban van (`upgradeToReformer()`, `upgradeToPraxis()`). |

---

## Railway env vars

| Változó | Állapot |
|---|---|
| `GROQ_API_KEY` | ✅ beállítva |
| `SEPOLIA_RPC_URL` | ✅ beállítva |
| `FAUCET_CLAIM_AMOUNT` | ✅ beállítva (1000) |
| `FAUCET_COOLDOWN_HOURS` | ✅ beállítva (24) |
| `FAUCET_PRIVATE_KEY` | ❌ még hiányzik — dedikált faucet-wallet szükséges hozzá |
| `SCHEDULER_PRIVATE_KEY` | — csak akkor kell, ha valaha elindítod a `gflo_scheduler.py`-t |

---

## Ismert, nyitott pontok (prioritás szerint)

1. **`gflo_faucet.py` feltöltése** — enélkül a faucet nem működik, bár az app nem omlik össze (try/except véd).
2. **`FAUCET_PRIVATE_KEY` beállítása** — dedikált teszt-wallet szükséges, NEM a deployer wallet.
3. **`gflo_scheduler.py` soha nincs elindítva** — a `GasFeeLoop.stake()` jelenleg nem ad automatikusan XP-t valós stake-elésre; ez a rendszer egyik ismert, még megoldatlan hiányossága.
4. **`api.py` törölhető** — törött import, nem használja semmi.
