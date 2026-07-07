import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from engine.lenses.lens_a_atas_replay import STANDARD_COLUMNS, AtasReplayLens
from engine.risk_models import rank_risk_models, run_concurrent_risk_simulation, load_tape_fixture
from engine.vwap_vectors import run_vwap_vector_analysis

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "mock_fixtures")
RISK_CHART_PATH = os.path.join(FIXTURES_DIR, "RISK_Chart.csv")
RISK_TAPE_PATH = os.path.join(FIXTURES_DIR, "RISK_Tape.csv")
MEXC_SAMPLE_PATH = os.path.join(FIXTURES_DIR, "MEXC_SAMPLE.csv")


def test_identifies_chart_files_only():
    lens = AtasReplayLens()
    assert lens.identify_file_signature(RISK_CHART_PATH) is True
    assert lens.identify_file_signature(RISK_TAPE_PATH) is False
    assert lens.identify_file_signature(MEXC_SAMPLE_PATH) is False


def test_normalize_to_schema_returns_only_the_clean_standard_columns():
    lens = AtasReplayLens()
    df = lens.normalize_to_schema(RISK_CHART_PATH)

    assert list(df.columns) == list(STANDARD_COLUMNS)
    # No leaked internal simulation columns (model, mae, mfe, stop_level, outcome, ...).
    leaked = {"model", "mae", "mfe", "stop_level", "outcome", "profit_target", "signal_index", "entry_variant"}
    assert leaked.isdisjoint(set(df.columns))


def test_every_row_reports_the_short_direction_and_derived_asset():
    lens = AtasReplayLens()
    df = lens.normalize_to_schema(RISK_CHART_PATH)

    assert (df["Direction"] == "Short").all()
    assert (df["Asset"] == "RISK").all()
    assert (df["Account ID"] == "ATAS_REPLAY_BACKTEST").all()


def test_reported_trades_use_the_actual_winning_model_by_net_expectancy():
    vwap_result = run_vwap_vector_analysis(RISK_CHART_PATH)
    tape_df = load_tape_fixture(RISK_TAPE_PATH)
    risk_results = run_concurrent_risk_simulation(vwap_result["candles"], vwap_result["reversion_entries"], tape_df)
    ranked = rank_risk_models(risk_results)
    expected_winner_pnls = sorted(
        (risk_results["entry_price"] - risk_results["exit_price"])[risk_results["model"] == ranked.iloc[0]["model"]]
    )

    lens = AtasReplayLens()
    df = lens.normalize_to_schema(RISK_CHART_PATH)

    assert sorted(df["Gross PnL"]) == pytest.approx(expected_winner_pnls)


def test_no_flagged_entries_returns_empty_standard_frame(tmp_path):
    import pandas as pd

    flat_rows = []
    t0 = pd.Timestamp("2026-09-01 09:30:00")
    for i in range(20):
        o, c = (100.00, 100.05) if i % 2 == 0 else (100.05, 100.00)
        flat_rows.append({
            "Datetime": t0 + pd.Timedelta(minutes=5 * i),
            "Open": o, "High": max(o, c) + 0.02, "Low": min(o, c) - 0.02, "Close": c, "Volume": 1000,
        })
    flat_path = tmp_path / "FLAT_Chart.csv"
    pd.DataFrame(flat_rows).to_csv(flat_path, index=False)

    lens = AtasReplayLens()
    df = lens.normalize_to_schema(str(flat_path))
    assert df.empty
    assert list(df.columns) == list(STANDARD_COLUMNS)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
