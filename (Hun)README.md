# GFLO Backend (`gflo-backend`)

**Ez a repó fut élesben.** Railway service: `web-gflo-sov-f4a65.up.railway.app`
Deploy forrás: `gflo-backend` / `master` ág · Start: `Procfile` → `web: python flask_api.py`

> A protokoll kanonikus forrása a [`gflo-pie`](https://github.com/elanmust-GFLOer/gflo-pie) repó
> (szerződések, döntések, tesztek). Ez a repó csak a futó HTTP API.

Jelölések: ✅ ÉLŐ · ⚠️ KIKAPCSOLVA / DRY-RUN

---

## Fail-closed szabály (v3.0)

A backend **nem olvassa** a visszavont Sepolia v3 szerződéseket. Ott az XP bárki által
önkiosztható (`gainXP()`), a GasFeeLoop pedig stake-alapú, tehát plutokratikus.
Nincs beégetett alapértelmezett cím. A `gflo_config.py` tiltólistája akkor is elutasítja a
régi címeket, ha valamelyik env var még rájuk mutat.

| Visszavont v3 cím | Mi volt |
|---|---|
| `0x9CF55d0b9D61Dc28EF3cb10765CF4b861Cd0991e` | PIECore v3 (önkiosztható XP) |
| `0x414DEDcf9264614Fd087BDa58bE27a0B698CcC54` | GFLOIgnition v3 |
| `0xd2C926F67080D6315b5dbBc7D621d729Cfe8A9C7` | GasFeeLoop (stake-szorzós XP) |
| `0x563b2e3b499818a2f84c472efb3169a2667807fe` | MockGFLOToken (nyitott `faucet()` mint) |

Amíg a kanonikus v0.2 nincs nyilvános hálózaton deployolva:
- `/api/identity/*` és `/api/batch/identities` → **503** `canonical_source_unavailable`
- `tier_required` kapu → minden kérést elutasít (503)
- a faucet **DRY-RUN** módban fut, tranzakciót nem küld
- `/api/status` → `"reputation": "disabled"`

## Fájlok

| Fájl | Állapot | Megjegyzés |
|---|---|---|
| `flask_api.py` | ✅ ÉLŐ | v3.0 API. Kanonikus olvasási út: `PIECoreIgnitionV01.getIdentity` → `TrustedXPSourceRegistryV02.totalXP` → `EffectiveTierGateV01.effectiveTier`. Jogosultság **csak** `effectiveTier` alapján; az `achievedTier` csak történeti adat. |
| `gflo_config.py` | ✅ | Címkezelés: nincs default, v3-tiltólista, hibás cím → kikapcsolt funkció. |
| `gflo_faucet.py` | ⚠️ DRY-RUN | Csak kanonikus `GFLO_TOKEN_ADDRESS`-szel és `FAUCET_PRIVATE_KEY`-jel küld. |
| `test_flask_api.py` | ✅ | Fail-closed tesztek, hálózat és kulcs nélkül: `pip install -r requirements.txt pytest && python -m pytest -q` |
| `app.py`, `app_test.py` | — | Egyszeri RPC-diagnosztika, nem része az élő API-nak. |

A `gflo_scheduler.py` (GasFeeLoop stake → XP) és a törött `api.py` törölve: a stake-alapú XP-t az
ADR-0001 elvetette.

## Railway env vars

| Változó | Szerep |
|---|---|
| `SEPOLIA_RPC_URL` | RPC végpont |
| `GROQ_API_KEY` | AI chat |
| `PIE_CORE_ADDRESS` | `PIECoreIgnitionV01` — **v0.2 deploy után** |
| `XP_REGISTRY_ADDRESS` | `TrustedXPSourceRegistryV02` — **v0.2 deploy után** |
| `EFFECTIVE_TIER_GATE_ADDRESS` | `EffectiveTierGateV01` — **v0.2 deploy után** |
| `GFLO_TOKEN_ADDRESS` | `GFLOFixedSupplyV01` — csak ha a faucet élesedik |
| `FAUCET_PRIVATE_KEY` | dedikált teszt-wallet, **nem** a deployer |
| `FAUCET_CLAIM_AMOUNT`, `FAUCET_COOLDOWN_HOURS` | faucet paraméterek |

A régi `PIECORE_ADDRESS` és `GASFEELOOP_ADDRESS` változót a kód már nem olvassa; a Railwayről törölhetők.
