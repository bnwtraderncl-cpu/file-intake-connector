import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

import engine.airtable_client as airtable_client
from engine.airtable_client import AirtableClient, CRYPTO_ONLY_FIELDS, build_airtable_payload


class FakeResponse:
    def __init__(self, status_code, json_data=None, headers=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

DUMMY_CRYPTO_TRADE = {
    "Trade ID": "MEXC_12345",
    "Account ID": "MEXC_DUAL_01",
    "Asset": "BTCUSDT",
    "Direction": "Long",
    "Exec Timestamps": "2026-07-01T00:00:00",
    "Gross PnL": 120.50,
    "Exchange Fees": 1.25,
    "Funding Fees Paid": 0.75,
}

DUMMY_NON_CRYPTO_TRADE = {
    "Trade ID": "IBKR_98765",
    "Account ID": "IBKR_MAIN",
    "Asset": "AAPL",
    "Direction": "Long",
    "Exec Timestamps": "2026-07-01T00:00:00",
    "Gross PnL": 45.00,
}


def test_crypto_trade_includes_fee_fields():
    payload = build_airtable_payload([DUMMY_CRYPTO_TRADE], is_crypto=True)
    fields = payload[0]["fields"]
    for key in CRYPTO_ONLY_FIELDS:
        assert key in fields


def test_non_crypto_trade_excludes_fee_fields():
    payload = build_airtable_payload([DUMMY_NON_CRYPTO_TRADE], is_crypto=False)
    fields = payload[0]["fields"]
    for key in CRYPTO_ONLY_FIELDS:
        assert key not in fields


def test_crypto_fields_stripped_when_lens_flag_is_false():
    # Guards against non-Lens-D callers accidentally forwarding crypto fields.
    payload = build_airtable_payload([DUMMY_CRYPTO_TRADE], is_crypto=False)
    fields = payload[0]["fields"]
    for key in CRYPTO_ONLY_FIELDS:
        assert key not in fields


def test_dry_run_returns_payload_without_network_call():
    client = AirtableClient(pat="fake_pat", base_id="fake_base")
    result = client.push_trades([DUMMY_CRYPTO_TRADE], is_crypto=True, dry_run=True)
    assert result == build_airtable_payload([DUMMY_CRYPTO_TRADE], is_crypto=True)


def test_dry_run_payload_matches_airtable_records_schema():
    # {"records": [{"fields": {...}}]} is Airtable's exact bulk-create shape.
    result = AirtableClient(pat="fake_pat", base_id="fake_base").push_trades(
        [DUMMY_CRYPTO_TRADE, DUMMY_NON_CRYPTO_TRADE], is_crypto=True, dry_run=True
    )
    assert isinstance(result, list)
    for record in result:
        assert set(record.keys()) == {"fields"}
        assert isinstance(record["fields"], dict)


def test_401_raises_auth_error_and_stops_the_run(monkeypatch):
    client = AirtableClient(pat="bad_pat", base_id="fake_base")
    monkeypatch.setattr(client.session, "post", lambda *a, **kw: FakeResponse(401))

    results = client.push_trades([DUMMY_CRYPTO_TRADE], is_crypto=True)

    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert "401" in results[0]["error"] or "unauthorized" in results[0]["error"].lower()


def test_429_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(airtable_client.time, "sleep", lambda *_: None)
    client = AirtableClient(pat="fake_pat", base_id="fake_base")

    call_count = {"n": 0}

    def fake_post(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return FakeResponse(429, headers={"Retry-After": "0"})
        return FakeResponse(200, json_data={"records": [{"id": "rec123"}]})

    monkeypatch.setattr(client.session, "post", fake_post)

    results = client.push_trades([DUMMY_CRYPTO_TRADE], is_crypto=True)

    assert call_count["n"] == 3
    assert results[0]["status"] == "success"


def test_429_exhausts_retries_and_reports_error_without_raising(monkeypatch):
    monkeypatch.setattr(airtable_client.time, "sleep", lambda *_: None)
    client = AirtableClient(pat="fake_pat", base_id="fake_base")
    monkeypatch.setattr(client.session, "post", lambda *a, **kw: FakeResponse(429, headers={"Retry-After": "0"}))

    results = client.push_trades([DUMMY_CRYPTO_TRADE], is_crypto=True)

    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert "rate limit" in results[0]["error"].lower()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
