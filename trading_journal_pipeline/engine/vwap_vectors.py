import logging
from pathlib import Path
from typing import Dict, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("Datetime", "Open", "High", "Low", "Close", "Volume")

VOLUME_LOOKBACK = 5
MEDIUM_INTENSITY_MULTIPLIER = 1.5
HIGH_INTENSITY_MULTIPLIER = 3.0
BAND_MULTIPLIERS = (2, 3)


def load_chart_fixture(file_path: Union[str, Path]) -> pd.DataFrame:
    """Load OHLCV candle rows from a '*_Chart.csv' fixture file."""
    file_path = Path(file_path)
    if not file_path.name.endswith("_Chart.csv"):
        raise ValueError(f"Expected a '*_Chart.csv' fixture, got: {file_path.name}")

    df = pd.read_csv(file_path)
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Chart fixture missing required columns: {missing}")

    df["Datetime"] = pd.to_datetime(df["Datetime"])
    df = df.sort_values("Datetime").reset_index(drop=True)
    return df


def add_volume_vector_tags(df: pd.DataFrame) -> pd.DataFrame:
    """Tag each bar using only its own OHLCV and the 5 bars strictly before it.

    V_avg5[t] = mean(Volume[t-5 .. t-1]) — the current bar's own volume is
    excluded from its own baseline via shift(1) before the rolling window.
    """
    df = df.copy()
    df["V_avg5"] = (
        df["Volume"].shift(1).rolling(window=VOLUME_LOOKBACK, min_periods=VOLUME_LOOKBACK).mean()
    )

    is_bullish = df["Close"] > df["Open"]
    is_bearish = df["Close"] < df["Open"]
    is_high = df["Volume"] >= HIGH_INTENSITY_MULTIPLIER * df["V_avg5"]
    is_medium = df["Volume"] >= MEDIUM_INTENSITY_MULTIPLIER * df["V_avg5"]

    df["intensity"] = np.select([is_high, is_medium], ["High", "Medium"], default=None)
    df["vector_tag"] = np.select(
        [is_high & is_bullish, is_high & is_bearish, is_medium & is_bullish, is_medium & is_bearish],
        ["Green", "Red", "Blue", "Violet"],
        default=None,
    )
    return df


def add_intraday_vwap_bands(df: pd.DataFrame) -> pd.DataFrame:
    """Cumulative intraday VWAP (reset per session date) with +-2/+-3 SD bands.

    Every cumulative sum at row t only includes rows up to and including t,
    so no bar's VWAP/band depends on bars that come after it.
    """
    df = df.copy()
    session_date = df["Datetime"].dt.date
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3.0
    pv = typical_price * df["Volume"]
    pv2 = typical_price.pow(2) * df["Volume"]

    cum_vol = df["Volume"].groupby(session_date).cumsum()
    cum_pv = pv.groupby(session_date).cumsum()
    cum_pv2 = pv2.groupby(session_date).cumsum()

    df["vwap"] = cum_pv / cum_vol
    variance = (cum_pv2 / cum_vol) - df["vwap"] ** 2
    variance = variance.clip(lower=0)  # guard against floating-point noise
    df["vwap_std"] = np.sqrt(variance)

    for n in BAND_MULTIPLIERS:
        df[f"vwap_upper_{n}sd"] = df["vwap"] + n * df["vwap_std"]
        df[f"vwap_lower_{n}sd"] = df["vwap"] - n * df["vwap_std"]

    return df


def flag_short_mean_reversion_context(df: pd.DataFrame) -> pd.DataFrame:
    """Flag a High Intensity Green Climax candle whose High extends past
    the +2SD or +3SD VWAP boundary as a short mean-reversion entry context."""
    df = df.copy()
    is_green_climax = df["vector_tag"] == "Green"
    breached_3sd = df["High"] >= df["vwap_upper_3sd"]
    breached_2sd = df["High"] >= df["vwap_upper_2sd"]

    df["short_mr_context"] = is_green_climax & breached_2sd
    df["short_mr_boundary"] = np.select(
        [is_green_climax & breached_3sd, is_green_climax & breached_2sd],
        ["3sd", "2sd"],
        default=None,
    )
    return df


def find_reversion_entries(df: pd.DataFrame) -> pd.DataFrame:
    """For each flagged Green climax candle, scan FORWARD for the first bar
    confirming each entry variant.

    This is a deliberate forward scan from the signal candle's own index —
    it answers "when would a later bar trigger the entry", which is
    different from letting future data leak into the signal candle's own
    indicators (V_avg5, vwap, bands, vector_tag) computed above.
    """
    records = []
    for i in df.index[df["short_mr_context"]]:
        signal_close = df.at[i, "Close"]
        signal_low = df.at[i, "Low"]
        aggressive_entry_timestamp = None
        conservative_entry_timestamp = None

        for j in range(i + 1, len(df)):
            bar_close = df.at[j, "Close"]
            if aggressive_entry_timestamp is None and bar_close < signal_close:
                aggressive_entry_timestamp = df.at[j, "Datetime"]
            if conservative_entry_timestamp is None and bar_close < signal_low:
                conservative_entry_timestamp = df.at[j, "Datetime"]
            if aggressive_entry_timestamp is not None and conservative_entry_timestamp is not None:
                break

        records.append({
            "signal_index": i,
            "signal_timestamp": df.at[i, "Datetime"],
            "sd_boundary": df.at[i, "short_mr_boundary"],
            "green_close": signal_close,
            "green_low": signal_low,
            "aggressive_entry_timestamp": aggressive_entry_timestamp,
            "conservative_entry_timestamp": conservative_entry_timestamp,
        })

    return pd.DataFrame.from_records(
        records,
        columns=[
            "signal_index", "signal_timestamp", "sd_boundary", "green_close", "green_low",
            "aggressive_entry_timestamp", "conservative_entry_timestamp",
        ],
    )


def run_vwap_vector_analysis(file_path: Union[str, Path]) -> Dict[str, pd.DataFrame]:
    df = load_chart_fixture(file_path)
    df = add_volume_vector_tags(df)
    df = add_intraday_vwap_bands(df)
    df = flag_short_mean_reversion_context(df)
    entries = find_reversion_entries(df)

    tag_counts = df["vector_tag"].value_counts(dropna=True).to_dict()
    logger.info("Vector tags computed: %s", tag_counts)
    logger.info("Short mean-reversion contexts flagged: %d", int(df["short_mr_context"].sum()))
    for _, row in entries.iterrows():
        logger.info(
            "Green climax @ %s (%s boundary) -> aggressive=%s conservative=%s",
            row["signal_timestamp"], row["sd_boundary"],
            row["aggressive_entry_timestamp"], row["conservative_entry_timestamp"],
        )

    return {"candles": df, "reversion_entries": entries}


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    fixture_path = sys.argv[1] if len(sys.argv) > 1 else "tests/mock_fixtures/SAMPLE_Chart.csv"
    run_vwap_vector_analysis(fixture_path)
