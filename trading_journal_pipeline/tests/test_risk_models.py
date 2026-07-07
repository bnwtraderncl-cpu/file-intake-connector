import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest

from engine.risk_models import (
    calculate_atr,
    compute_stop_levels,
    compute_trade_pnl,
    detect_aggressive_buy_cluster,
    load_tape_fixture,
    rank_risk_models,
    run_full_risk_pipeline,
    select_winning_model,
    simulate_static_stop_model,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "mock_fixtures")
RISK_CHART_PATH = os.path.join(FIXTURES_DIR, "RISK_Chart.csv")
RISK_TAPE_PATH = os.path.join(FIXTURES_DIR, "RISK_Tape.csv")


def _make_candles(rows):
    df = pd.DataFrame(rows)
    df["Datetime"] = pd.to_datetime(df["Datetime"])
    return df


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

def test_atr_no_lookahead_truncating_future_rows_leaves_history_unchanged():
    df = load_chart_like_fixture()
    cutoff = 20

    full_atr = calculate_atr(df.copy())
    truncated_atr = calculate_atr(df.iloc[:cutoff].copy())

    pd.testing.assert_series_equal(
        full_atr.iloc[:cutoff].reset_index(drop=True),
        truncated_atr.reset_index(drop=True),
        check_names=False,
    )


def load_chart_like_fixture():
    from engine.vwap_vectors import load_chart_fixture
    return load_chart_fixture(RISK_CHART_PATH)


# ---------------------------------------------------------------------------
# Stop level math
# ---------------------------------------------------------------------------

def test_compute_stop_levels_matches_spec_formulas():
    levels = compute_stop_levels(vector_high=100.0, vector_low=90.0, atr_at_signal=2.0)
    assert levels["model_1_atr"] == pytest.approx(100.0 + 1.5 * 2.0)
    assert levels["model_2A"] == pytest.approx(100.0)          # 0% of range
    assert levels["model_2B"] == pytest.approx(100.0 + 0.25 * 10.0)
    assert levels["model_2C"] == pytest.approx(100.0 + 0.50 * 10.0)


# ---------------------------------------------------------------------------
# Static stop-loss simulation
# ---------------------------------------------------------------------------

def test_static_model_stops_out_when_high_breaches_stop():
    df = _make_candles([
        {"Datetime": "2026-01-01 09:30", "Open": 100, "High": 100.1, "Low": 99.9, "Close": 100},
        {"Datetime": "2026-01-01 09:35", "Open": 100, "High": 103.0, "Low": 99.5, "Close": 102},
    ])
    result = simulate_static_stop_model(df, entry_index=0, entry_price=100.0, stop_level=102.0,
                                         profit_target=90.0, model_name="test")
    assert result["outcome"] == "stop_out"
    assert result["exit_price"] == 102.0
    assert result["mae"] == pytest.approx(3.0)


def test_static_model_hits_profit_target_when_low_breaches_target():
    df = _make_candles([
        {"Datetime": "2026-01-01 09:30", "Open": 100, "High": 100.1, "Low": 99.9, "Close": 100},
        {"Datetime": "2026-01-01 09:35", "Open": 100, "High": 100.5, "Low": 95.0, "Close": 96},
    ])
    result = simulate_static_stop_model(df, entry_index=0, entry_price=100.0, stop_level=110.0,
                                         profit_target=96.0, model_name="test")
    assert result["outcome"] == "profit_target"
    assert result["exit_price"] == 96.0
    assert result["mfe"] == pytest.approx(5.0)


def test_static_model_same_bar_conservatively_assumes_stop_hits_first():
    df = _make_candles([
        {"Datetime": "2026-01-01 09:30", "Open": 100, "High": 100.1, "Low": 99.9, "Close": 100},
        {"Datetime": "2026-01-01 09:35", "Open": 100, "High": 110.0, "Low": 90.0, "Close": 95},
    ])
    result = simulate_static_stop_model(df, entry_index=0, entry_price=100.0, stop_level=105.0,
                                         profit_target=95.0, model_name="test")
    assert result["outcome"] == "stop_out"


def test_static_model_stays_open_if_nothing_triggers():
    df = _make_candles([
        {"Datetime": "2026-01-01 09:30", "Open": 100, "High": 100.1, "Low": 99.9, "Close": 100},
        {"Datetime": "2026-01-01 09:35", "Open": 100, "High": 100.2, "Low": 99.8, "Close": 100},
    ])
    result = simulate_static_stop_model(df, entry_index=0, entry_price=100.0, stop_level=110.0,
                                         profit_target=90.0, model_name="test")
    assert result["outcome"] == "open"
    assert result["exit_price"] is None


# ---------------------------------------------------------------------------
# Tape cluster detection
# ---------------------------------------------------------------------------

def test_tape_fixture_requires_tape_suffix():
    with pytest.raises(ValueError):
        load_tape_fixture("bad_name.csv")


def test_cluster_detected_once_cumulative_buy_volume_crosses_threshold():
    tape_window = pd.DataFrame([
        {"Timestamp": pd.Timestamp("2026-01-01 09:30:10"), "Price": 107.90, "Size": 300, "Side": "Buy"},
        {"Timestamp": pd.Timestamp("2026-01-01 09:30:20"), "Price": 107.60, "Size": 500, "Side": "Sell"},
        {"Timestamp": pd.Timestamp("2026-01-01 09:30:30"), "Price": 107.95, "Size": 250, "Side": "Buy"},
    ])
    trigger = detect_aggressive_buy_cluster(tape_window, vector_high=108.0)
    assert trigger is not None
    assert trigger["Price"] == 107.95


def test_cluster_ignored_when_below_volume_threshold():
    tape_window = pd.DataFrame([
        {"Timestamp": pd.Timestamp("2026-01-01 09:30:10"), "Price": 107.95, "Size": 100, "Side": "Buy"},
    ])
    assert detect_aggressive_buy_cluster(tape_window, vector_high=108.0) is None


def test_cluster_ignored_when_price_outside_tolerance_of_vector_high():
    tape_window = pd.DataFrame([
        {"Timestamp": pd.Timestamp("2026-01-01 09:30:10"), "Price": 105.00, "Size": 1000, "Side": "Buy"},
    ])
    assert detect_aggressive_buy_cluster(tape_window, vector_high=108.0) is None


# ---------------------------------------------------------------------------
# Full concurrent pipeline (RISK_Chart.csv / RISK_Tape.csv whipsaw scenario)
# ---------------------------------------------------------------------------

def test_concurrent_models_diverge_on_the_whipsaw_signal():
    out = run_full_risk_pipeline(RISK_CHART_PATH, RISK_TAPE_PATH)
    results = out["results"]

    losing_trade = results[(results["signal_index"] == 14) & (results["entry_variant"] == "aggressive")]
    by_model = losing_trade.set_index("model")

    # Tightest static stop (2A) exits one bar earlier, for less damage, than the
    # looser static stops (1/2B/2C), which all ride it out to the same later bar.
    assert by_model.at["model_2A", "outcome"] == "stop_out"
    assert by_model.at["model_2A", "mae"] == pytest.approx(3.55)
    for wide_model in ("model_1_atr", "model_2B", "model_2C"):
        assert by_model.at[wide_model, "outcome"] == "stop_out"
        assert by_model.at[wide_model, "mae"] == pytest.approx(8.50)

    # The tape model preempts the hard stop entirely via the aggressive-buy
    # cluster, exiting earlier and for even less damage than model_2A.
    assert by_model.at["model_3_tape", "outcome"] == "tape_exit"
    assert by_model.at["model_3_tape", "mae"] < by_model.at["model_2A", "mae"]


def test_summary_reports_equal_win_rate_but_differentiated_mae():
    out = run_full_risk_pipeline(RISK_CHART_PATH, RISK_TAPE_PATH)
    summary = out["summary"].set_index("model")

    # All 5 model-variants share the same win/loss record (3 of 4 trades)...
    assert summary["win_rate"].apply(lambda v: v == pytest.approx(0.75)).all()

    # ...but the tape-based dynamic stop achieves the best (lowest) average MAE,
    # and the tightest static variant beats the looser ones - the whole point
    # of comparing risk models with an identical win rate.
    assert summary.at["model_3_tape", "avg_mae"] < summary.at["model_2A", "avg_mae"]
    assert summary.at["model_2A", "avg_mae"] < summary.at["model_1_atr", "avg_mae"]


# ---------------------------------------------------------------------------
# Net Expectancy ranking / winning model selection
# ---------------------------------------------------------------------------

def test_compute_trade_pnl_is_entry_minus_exit_for_a_short():
    df = pd.DataFrame([
        {"entry_price": 100.0, "exit_price": 90.0},   # price fell -> short profit
        {"entry_price": 100.0, "exit_price": 105.0},  # price rose -> short loss
    ])
    out = compute_trade_pnl(df)
    assert out["pnl"].tolist() == pytest.approx([10.0, -5.0])


def test_rank_risk_models_orders_by_net_expectancy_then_mae():
    out = run_full_risk_pipeline(RISK_CHART_PATH, RISK_TAPE_PATH)
    ranked = rank_risk_models(out["results"])

    assert list(ranked["model"]) == ["model_3_tape", "model_2A", "model_1_atr", "model_2B", "model_2C"]
    assert ranked["net_expectancy"].is_monotonic_decreasing


def test_select_winning_model_picks_highest_net_expectancy():
    out = run_full_risk_pipeline(RISK_CHART_PATH, RISK_TAPE_PATH)
    assert select_winning_model(out["results"]) == "model_3_tape"


def test_select_winning_model_raises_when_nothing_resolved():
    unresolved = pd.DataFrame([
        {"model": "model_1_atr", "entry_price": 100.0, "exit_price": None, "outcome": "open", "mae": 0.0, "mfe": 0.0},
    ])
    with pytest.raises(ValueError):
        select_winning_model(unresolved)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
