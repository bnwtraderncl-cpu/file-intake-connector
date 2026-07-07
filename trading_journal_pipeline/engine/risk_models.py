import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd

try:
    from .vwap_vectors import run_vwap_vector_analysis
except ImportError:
    from vwap_vectors import run_vwap_vector_analysis

logger = logging.getLogger(__name__)

ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = 1.5
# Model 2 sub-variants: stop = Vector High + (pct * Vector Range)
VECTOR_RANGE_STOP_VARIANTS = {"model_2A": 0.00, "model_2B": 0.25, "model_2C": 0.50}

TAPE_PRICE_TOLERANCE = 0.10
TAPE_CLUSTER_VOLUME_THRESHOLD = 500

REQUIRED_TAPE_COLUMNS = ("Timestamp", "Price", "Size", "Side")


def calculate_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """Rolling ATR. True Range at bar t only uses High/Low[t] and Close[t-1],
    so ATR at any bar never depends on bars that come after it."""
    prev_close = df["Close"].shift(1)
    true_range = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return true_range.rolling(window=period, min_periods=period).mean()


def compute_stop_levels(vector_high: float, vector_low: float, atr_at_signal: float) -> Dict[str, float]:
    """Model 1 (ATR buffer) and Model 2A/2B/2C (vector range anchor) stop levels."""
    vector_range = vector_high - vector_low
    levels = {"model_1_atr": vector_high + ATR_STOP_MULTIPLIER * atr_at_signal}
    for name, pct in VECTOR_RANGE_STOP_VARIANTS.items():
        levels[name] = vector_high + pct * vector_range
    return levels


def load_tape_fixture(file_path: Union[str, Path]) -> pd.DataFrame:
    """Load individual transaction prints from a '*_Tape.csv' fixture file."""
    file_path = Path(file_path)
    if not file_path.name.endswith("_Tape.csv"):
        raise ValueError(f"Expected a '*_Tape.csv' fixture, got: {file_path.name}")

    df = pd.read_csv(file_path)
    missing = [col for col in REQUIRED_TAPE_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Tape fixture missing required columns: {missing}")

    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    return df.sort_values("Timestamp").reset_index(drop=True)


def detect_aggressive_buy_cluster(tape_window: pd.DataFrame, vector_high: float,
                                   price_tolerance: float = TAPE_PRICE_TOLERANCE,
                                   volume_threshold: float = TAPE_CLUSTER_VOLUME_THRESHOLD):
    """Scan a chronologically-ordered slice of tape prints for a counter-trend
    aggressive-buying cluster printing at/near the vector candle's High.

    Returns the print at which cumulative clustered volume first crosses the
    threshold, or None. Only ever looks at the prints handed to it - callers
    pass in prints for the bar/window currently being evaluated, so this never
    sees prints beyond the point being simulated.
    """
    at_high = tape_window[
        (tape_window["Side"] == "Buy") & (tape_window["Price"] >= vector_high - price_tolerance)
    ].sort_values("Timestamp")

    cumulative = 0.0
    for _, print_row in at_high.iterrows():
        cumulative += print_row["Size"]
        if cumulative >= volume_threshold:
            return print_row
    return None


def simulate_static_stop_model(candles_df: pd.DataFrame, entry_index: int, entry_price: float,
                                stop_level: float, profit_target: float, model_name: str) -> dict:
    """Bar-by-bar SHORT trade simulation against one fixed stop level and target.

    Conservative same-bar ordering: if a single bar's High would hit the stop
    AND its Low would hit the target, the stop is assumed to trigger first.
    """
    mae = 0.0
    mfe = 0.0
    outcome = "open"
    exit_price = None
    exit_timestamp = None

    for j in range(entry_index + 1, len(candles_df)):
        bar_high = candles_df.at[j, "High"]
        bar_low = candles_df.at[j, "Low"]
        mae = max(mae, bar_high - entry_price)
        mfe = max(mfe, entry_price - bar_low)

        if bar_high >= stop_level:
            outcome = "stop_out"
            exit_price = stop_level
            exit_timestamp = candles_df.at[j, "Datetime"]
            break
        if bar_low <= profit_target:
            outcome = "profit_target"
            exit_price = profit_target
            exit_timestamp = candles_df.at[j, "Datetime"]
            break

    return {
        "model": model_name, "entry_price": entry_price, "stop_level": stop_level,
        "profit_target": profit_target, "mae": mae, "mfe": mfe, "outcome": outcome,
        "exit_price": exit_price, "exit_timestamp": exit_timestamp,
    }


def simulate_tape_dynamic_stop_model(candles_df: pd.DataFrame, tape_df: Optional[pd.DataFrame],
                                      entry_index: int, entry_price: float, vector_high: float,
                                      hard_stop_level: float, profit_target: float,
                                      model_name: str = "model_3_tape") -> dict:
    """Model 3: streams tape prints bar-by-bar alongside the candles, exiting
    early the moment a counter-trend aggressive-buy cluster prints at/near the
    vector High - preempting the hard stop rather than waiting for it to be
    touched at the candle level. Falls back to the static hard stop / profit
    target when no such cluster occurs in a given bar's window.
    """
    mae = 0.0
    mfe = 0.0
    outcome = "open"
    exit_price = None
    exit_timestamp = None

    for j in range(entry_index + 1, len(candles_df)):
        bar_start = candles_df.at[j, "Datetime"]
        bar_end = (
            candles_df.at[j + 1, "Datetime"] if j + 1 < len(candles_df)
            else bar_start + (bar_start - candles_df.at[j - 1, "Datetime"])
        )
        bar_high = candles_df.at[j, "High"]
        bar_low = candles_df.at[j, "Low"]

        if tape_df is not None:
            tape_window = tape_df[(tape_df["Timestamp"] >= bar_start) & (tape_df["Timestamp"] < bar_end)]
            trigger = detect_aggressive_buy_cluster(tape_window, vector_high)
            if trigger is not None:
                outcome = "tape_exit"
                exit_price = float(trigger["Price"])
                exit_timestamp = trigger["Timestamp"]
                mae = max(mae, exit_price - entry_price)
                break

        mae = max(mae, bar_high - entry_price)
        mfe = max(mfe, entry_price - bar_low)

        if bar_high >= hard_stop_level:
            outcome = "stop_out"
            exit_price = hard_stop_level
            exit_timestamp = bar_start
            break
        if bar_low <= profit_target:
            outcome = "profit_target"
            exit_price = profit_target
            exit_timestamp = bar_start
            break

    return {
        "model": model_name, "entry_price": entry_price, "stop_level": hard_stop_level,
        "profit_target": profit_target, "mae": mae, "mfe": mfe, "outcome": outcome,
        "exit_price": exit_price, "exit_timestamp": exit_timestamp,
    }


def run_concurrent_risk_simulation(candles_df: pd.DataFrame, entries_df: pd.DataFrame,
                                    tape_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """For every flagged short entry (both Aggressive and Conservative variants),
    run all 3 stop-loss models concurrently and collect their outcomes."""
    candles_df = candles_df.copy()
    candles_df["ATR_14"] = calculate_atr(candles_df)
    timestamp_to_index = {ts: i for i, ts in enumerate(candles_df["Datetime"])}

    results: List[dict] = []

    for _, signal in entries_df.iterrows():
        signal_index = int(signal["signal_index"])
        vector_high = candles_df.at[signal_index, "High"]
        vector_low = candles_df.at[signal_index, "Low"]
        atr_at_signal = candles_df.at[signal_index, "ATR_14"]

        if pd.isna(atr_at_signal):
            logger.warning(
                "Skipping signal @ %s: fewer than %d bars of history for ATR_14",
                signal["signal_timestamp"], ATR_PERIOD,
            )
            continue

        stop_levels = compute_stop_levels(vector_high, vector_low, atr_at_signal)

        for variant in ("aggressive", "conservative"):
            entry_ts = signal[f"{variant}_entry_timestamp"]
            if pd.isna(entry_ts):
                continue

            entry_index = timestamp_to_index[entry_ts]
            entry_price = candles_df.at[entry_index, "Close"]
            profit_target = candles_df.at[entry_index, "vwap"]

            for model_name, stop_level in stop_levels.items():
                result = simulate_static_stop_model(
                    candles_df, entry_index, entry_price, stop_level, profit_target, model_name
                )
                result.update({"signal_index": signal_index, "entry_variant": variant, "entry_timestamp": entry_ts})
                results.append(result)

            tape_result = simulate_tape_dynamic_stop_model(
                candles_df, tape_df, entry_index, entry_price, vector_high,
                hard_stop_level=stop_levels["model_1_atr"], profit_target=profit_target,
            )
            tape_result.update({"signal_index": signal_index, "entry_variant": variant, "entry_timestamp": entry_ts})
            results.append(tape_result)

    return pd.DataFrame(results)


def summarize_risk_models(results_df: pd.DataFrame) -> pd.DataFrame:
    """Win rate and average MAE/MFE per risk model, across all simulated trades."""
    resolved = results_df[results_df["outcome"] != "open"]
    if resolved.empty:
        return pd.DataFrame(columns=["model", "trades", "wins", "win_rate", "avg_mae", "avg_mfe"])

    summary = resolved.groupby("model").agg(
        trades=("outcome", "count"),
        wins=("outcome", lambda s: (s == "profit_target").sum()),
        avg_mae=("mae", "mean"),
        avg_mfe=("mfe", "mean"),
    )
    summary["win_rate"] = summary["wins"] / summary["trades"]
    return summary.reset_index()[["model", "trades", "wins", "win_rate", "avg_mae", "avg_mfe"]]


def compute_trade_pnl(results_df: pd.DataFrame) -> pd.DataFrame:
    """Realized short-trade PnL per simulated outcome: entry - exit (positive
    means price fell further and the short covered for a profit)."""
    df = results_df.copy()
    df["pnl"] = df["entry_price"] - df["exit_price"]
    return df


def rank_risk_models(results_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate performance per model, including Net Expectancy (mean realized
    PnL per resolved trade), ranked by highest Net Expectancy then lowest MAE."""
    df = compute_trade_pnl(results_df)
    resolved = df[df["outcome"] != "open"]
    if resolved.empty:
        return pd.DataFrame(columns=["model", "trades", "wins", "win_rate", "avg_mae", "avg_mfe", "net_expectancy"])

    summary = resolved.groupby("model").agg(
        trades=("outcome", "count"),
        wins=("outcome", lambda s: (s == "profit_target").sum()),
        avg_mae=("mae", "mean"),
        avg_mfe=("mfe", "mean"),
        net_expectancy=("pnl", "mean"),
    )
    summary["win_rate"] = summary["wins"] / summary["trades"]
    summary = summary.reset_index()[["model", "trades", "wins", "win_rate", "avg_mae", "avg_mfe", "net_expectancy"]]
    return summary.sort_values(["net_expectancy", "avg_mae"], ascending=[False, True]).reset_index(drop=True)


def select_winning_model(results_df: pd.DataFrame) -> str:
    """The model with the highest Net Expectancy; ties broken by lowest avg MAE."""
    ranked = rank_risk_models(results_df)
    if ranked.empty:
        raise ValueError("No resolved trades to select a winning risk model from.")
    return ranked.iloc[0]["model"]


def run_full_risk_pipeline(chart_path: Union[str, Path], tape_path: Optional[Union[str, Path]] = None) -> Dict[str, pd.DataFrame]:
    vwap_result = run_vwap_vector_analysis(chart_path)
    tape_df = load_tape_fixture(tape_path) if tape_path else None

    results = run_concurrent_risk_simulation(vwap_result["candles"], vwap_result["reversion_entries"], tape_df)
    summary = summarize_risk_models(results)

    logger.info("Risk model summary:\n%s", summary.to_string(index=False))
    return {"results": results, "summary": summary}


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    chart_arg = sys.argv[1] if len(sys.argv) > 1 else "tests/mock_fixtures/RISK_Chart.csv"
    tape_arg = sys.argv[2] if len(sys.argv) > 2 else "tests/mock_fixtures/RISK_Tape.csv"
    run_full_risk_pipeline(chart_arg, tape_arg)
