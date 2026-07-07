import os
import shutil
import sys

# core_pipeline.py (and the modules it imports) rely on bare top-level
# imports (e.g. "from lenses.x import Y", "from airtable_client import Z"),
# matching how it's actually invoked in production: `python engine/core_pipeline.py`
# from the project root, which puts the script's own directory (engine/) on
# sys.path. Mirror that here rather than importing via the "engine.*" dotted
# path used by the other test modules.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

import pytest

from core_pipeline import CorePipelineRouter

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "mock_fixtures")

STANDARD_TRADE_KEYS = {
    "Trade ID", "Account ID", "Asset", "Direction", "Exec Timestamps",
    "Gross PnL", "Exchange Fees", "Funding Fees Paid",
}


class FakeAirtableClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def push_trades(self, trades, is_crypto=False, table=None, dry_run=False):
        self.calls.append({"trades": trades, "is_crypto": is_crypto})
        if self.fail:
            return [{"status": "error", "batch_index": 0, "error": "simulated failure"}]
        return [{"status": "success", "batch_index": 0, "response": {"records": [{"id": "recFAKE"}]}}]


def _stage(tmp_path, filenames):
    staging = tmp_path / "raw_staging"
    archive = tmp_path / "processed_archive"
    staging.mkdir()
    archive.mkdir()
    for name in filenames:
        shutil.copy(os.path.join(FIXTURES_DIR, name), staging / name)
    return f"{staging}{os.sep}", f"{archive}{os.sep}"


def test_atas_replay_file_transmits_and_archives_chart_with_its_tape_sidefile(tmp_path):
    staging, archive = _stage(tmp_path, ["RISK_Chart.csv", "RISK_Tape.csv"])
    client = FakeAirtableClient()
    router = CorePipelineRouter(airtable_client=client)

    router.process_staging_directory(staging_path=staging, archive_path=archive)

    assert not os.path.exists(os.path.join(staging, "RISK_Chart.csv"))
    assert not os.path.exists(os.path.join(staging, "RISK_Tape.csv"))
    assert os.path.exists(os.path.join(archive, "RISK_Chart.csv"))
    assert os.path.exists(os.path.join(archive, "RISK_Tape.csv"))

    assert len(client.calls) == 1
    assert client.calls[0]["is_crypto"] is False
    trades = client.calls[0]["trades"]
    assert len(trades) == 4
    for trade in trades:
        assert set(trade.keys()) == STANDARD_TRADE_KEYS


def test_mexc_file_routes_as_crypto_with_fee_fields_intact(tmp_path):
    staging, archive = _stage(tmp_path, ["MEXC_SAMPLE.csv"])
    client = FakeAirtableClient()
    router = CorePipelineRouter(airtable_client=client)

    router.process_staging_directory(staging_path=staging, archive_path=archive)

    assert os.path.exists(os.path.join(archive, "MEXC_SAMPLE.csv"))
    assert client.calls[0]["is_crypto"] is True
    trade = client.calls[0]["trades"][0]
    assert trade["Exchange Fees"] == pytest.approx(0.7)
    assert trade["Funding Fees Paid"] == pytest.approx(0.15)


def test_failed_transmission_leaves_files_in_staging_per_post_transfer_rule(tmp_path):
    staging, archive = _stage(tmp_path, ["RISK_Chart.csv", "RISK_Tape.csv"])
    client = FakeAirtableClient(fail=True)
    router = CorePipelineRouter(airtable_client=client)

    router.process_staging_directory(staging_path=staging, archive_path=archive)

    assert os.path.exists(os.path.join(staging, "RISK_Chart.csv"))
    assert os.path.exists(os.path.join(staging, "RISK_Tape.csv"))
    assert os.listdir(archive) == []


def test_unrecognized_file_format_is_left_untouched(tmp_path):
    staging = tmp_path / "raw_staging"
    archive = tmp_path / "processed_archive"
    staging.mkdir()
    archive.mkdir()
    junk = staging / "not_a_broker_file.csv"
    junk.write_text("foo,bar\n1,2\n")

    client = FakeAirtableClient()
    router = CorePipelineRouter(airtable_client=client)
    router.process_staging_directory(staging_path=f"{staging}{os.sep}", archive_path=f"{archive}{os.sep}")

    assert junk.exists()
    assert client.calls == []


def test_account_id_is_delivered_as_a_linked_record_array_end_to_end(tmp_path):
    staging, archive = _stage(tmp_path, ["RISK_Chart.csv", "RISK_Tape.csv"])
    from airtable_client import build_airtable_payload

    captured = {}

    class CapturingClient(FakeAirtableClient):
        def push_trades(self, trades, is_crypto=False, table=None, dry_run=False):
            captured["payload"] = build_airtable_payload(trades, is_crypto)
            return super().push_trades(trades, is_crypto, table, dry_run)

    router = CorePipelineRouter(airtable_client=CapturingClient())
    router.process_staging_directory(staging_path=staging, archive_path=archive)

    assert captured["payload"], "expected at least one record to have been pushed"
    for record in captured["payload"]:
        assert record["fields"]["Account ID"] == ["ATAS_REPLAY_BACKTEST"]
        assert "Exchange Fees" not in record["fields"]  # non-crypto lens: fees stripped, no leak


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
