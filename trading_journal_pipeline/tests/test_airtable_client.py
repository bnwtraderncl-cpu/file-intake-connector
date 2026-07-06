import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.airtable_client import AirtableClient, CRYPTO_ONLY_FIELDS, build_airtable_payload

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


if __name__ == "__main__":
    test_crypto_trade_includes_fee_fields()
    test_non_crypto_trade_excludes_fee_fields()
    test_crypto_fields_stripped_when_lens_flag_is_false()
    test_dry_run_returns_payload_without_network_call()
    print("All airtable_client dry-run verification tests passed.")
