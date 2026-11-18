"""Fail-closed tests for the live API: retired v3 contracts must never be read.

Run: pip install -r requirements.txt pytest && python -m pytest -q
No RPC, keys or network needed; chain reads are stubbed.
"""
import importlib
import sys
from unittest import mock

import pytest

V3_PIECORE = "0x9CF55d0b9D61Dc28EF3cb10765CF4b861Cd0991e"
V3_GASFEELOOP = "0xd2C926F67080D6315b5dbBc7D621d729Cfe8A9C7"
V3_TOKEN = "0x563b2e3b499818a2f84c472efb3169a2667807fe"
CORE = "0x" + "11" * 20
REGISTRY = "0x" + "22" * 20
GATE = "0x" + "33" * 20
ALICE = "0x" + "aa" * 20
ENV_KEYS = ("PIE_CORE_ADDRESS", "XP_REGISTRY_ADDRESS", "EFFECTIVE_TIER_GATE_ADDRESS",
            "PIECORE_ADDRESS", "GASFEELOOP_ADDRESS", "GFLO_TOKEN_ADDRESS",
            "FAUCET_PRIVATE_KEY", "SEPOLIA_RPC_URL", "GROQ_API_KEY")


def load_api(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("HOME", str(tmp_path))  # ignore any developer ~/.env
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for name in ("flask_api", "gflo_faucet", "gflo_config"):
        sys.modules.pop(name, None)
    api = importlib.import_module("flask_api")
    api.app.testing = True
    return api


def stub(value):
    return mock.Mock(**{"call.return_value": value})


def test_unconfigured_api_disables_reputation(monkeypatch, tmp_path):
    api = load_api(monkeypatch, tmp_path)
    client = api.app.test_client()
    with mock.patch.object(api.w3, "is_connected", return_value=False):
        body = client.get("/api/status").get_json()
    assert body["reputation"] == "disabled"
    assert V3_PIECORE not in str(body) and V3_GASFEELOOP not in str(body)
    r = client.get(f"/api/identity/{ALICE}")
    assert r.status_code == 503 and r.get_json()["error"] == "canonical_source_unavailable"
    assert client.post("/api/batch/identities", json={"addresses": [ALICE]}).status_code == 503


def test_legacy_v3_env_vars_are_refused(monkeypatch, tmp_path):
    # Railway may still carry the old variables; even pointed at new names they are refused.
    api = load_api(monkeypatch, tmp_path, PIECORE_ADDRESS=V3_PIECORE, GASFEELOOP_ADDRESS=V3_GASFEELOOP,
                   PIE_CORE_ADDRESS=V3_PIECORE, XP_REGISTRY_ADDRESS=REGISTRY, EFFECTIVE_TIER_GATE_ADDRESS=GATE)
    assert api.PIE_CORE_ADDRESS is None and api.REPUTATION_ENABLED is False
    assert api.app.test_client().get(f"/api/identity/{ALICE}").status_code == 503


def test_lowercase_v3_address_is_refused(monkeypatch, tmp_path):
    api = load_api(monkeypatch, tmp_path, PIE_CORE_ADDRESS=V3_PIECORE.lower(),
                   XP_REGISTRY_ADDRESS=REGISTRY, EFFECTIVE_TIER_GATE_ADDRESS=GATE)
    assert api.REPUTATION_ENABLED is False


def configured(monkeypatch, tmp_path):
    api = load_api(monkeypatch, tmp_path, PIE_CORE_ADDRESS=CORE, XP_REGISTRY_ADDRESS=REGISTRY,
                   EFFECTIVE_TIER_GATE_ADDRESS=GATE)
    assert api.REPUTATION_ENABLED
    api.pie = mock.Mock(functions=mock.Mock(getIdentity=lambda a: stub((True, 25, 3, 2))))
    api.xp_registry = mock.Mock(functions=mock.Mock(totalXP=lambda a: stub(125)))
    api.tier_gate = mock.Mock(functions=mock.Mock(effectiveTier=lambda a: stub(1)))
    return api


def test_canonical_identity_reports_effective_tier(monkeypatch, tmp_path):
    api = configured(monkeypatch, tmp_path)
    body = api.app.test_client().get(f"/api/identity/{ALICE}").get_json()["piecore"]
    assert body == {"exists": True, "xp": 125, "path": "Praxis", "achievedTier": 2, "effectiveTier": 1}


def test_tier_gate_uses_effective_not_achieved_tier(monkeypatch, tmp_path):
    api = configured(monkeypatch, tmp_path)

    @api.app.route("/_t2")
    @api.tier_required(2)
    def _t2():
        return "ok"

    client = api.app.test_client()
    assert client.get("/_t2").status_code == 401
    # achievedTier is 2 but effectiveTier is 1: must be denied.
    assert client.get("/_t2", headers={"X-Wallet-Address": ALICE}).status_code == 403


def test_tier_gate_fails_closed_on_chain_error(monkeypatch, tmp_path):
    api = configured(monkeypatch, tmp_path)
    boom = mock.Mock(**{"call.side_effect": RuntimeError("rpc down")})
    api.tier_gate = mock.Mock(functions=mock.Mock(effectiveTier=lambda a: boom))

    @api.app.route("/_t0")
    @api.tier_required(0)
    def _t0():
        return "ok"

    assert api.app.test_client().get("/_t0", headers={"X-Wallet-Address": ALICE}).status_code == 503


def test_faucet_never_sends_from_retired_token(monkeypatch, tmp_path):
    api = load_api(monkeypatch, tmp_path, GFLO_TOKEN_ADDRESS=V3_TOKEN,
                   FAUCET_PRIVATE_KEY="0x" + "01" * 32, SEPOLIA_RPC_URL="http://127.0.0.1:1")
    faucet = sys.modules["gflo_faucet"]
    assert faucet.GFLO_TOKEN_ADDRESS is None and faucet.w3 is None
    monkeypatch.setattr(faucet, "CLAIMS_LOG_PATH", tmp_path / "claims.json")
    monkeypatch.setattr(faucet, "EVENT_LOG_PATH", tmp_path / "events.jsonl")
    r = api.app.test_client().post("/api/faucet/claim", json={"wallet_address": ALICE})
    assert r.get_json()["status"] == "dry_run"
