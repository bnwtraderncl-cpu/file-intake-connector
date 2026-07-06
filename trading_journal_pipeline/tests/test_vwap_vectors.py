import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd

from engine.vwap_vectors import (
    add_intraday_vwap_bands,
    add_volume_vector_tags,
    find_reversion_entries,
    flag_short_mean_reversion_context,
    load_chart_fixture,
)

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "mock_fixtures", "SAMPLE_Chart.csv")


def _build_full_pipeline(df: pd.DataFrame) -> pd.DataFrame:
    df = add_volume_vector_tags(df)
    df = add_intraday_vwap_bands(df)
    df = flag_short_mean_reversion_context(df)
    return df


def test_load_chart_fixture_requires_chart_suffix():
    try:
        load_chart_fixture("bad_name.csv")
        assert False, "expected ValueError for non-'_Chart.csv' filename"
    except ValueError:
        pass


def test_vector_tags_cover_all_four_categories():
    df = _build_full_pipeline(load_chart_fixture(FIXTURE_PATH))
    counts = df["vector_tag"].value_counts()
    assert counts.get("Blue") == 1
    assert counts.get("Violet") == 1
    assert counts.get("Green") == 1
    assert counts.get("Red") == 1


def test_high_intensity_takes_priority_over_medium():
    # The Green/Red climax bars clear the 3x threshold, which also clears
    # the 1.5x threshold - they must be tagged High/Green|Red, not Medium.
    df = _build_full_pipeline(load_chart_fixture(FIXTURE_PATH))
    climax_rows = df[df["intensity"] == "High"]
    assert set(climax_rows["vector_tag"]) == {"Green", "Red"}


def test_only_green_climax_flagged_for_short_mean_reversion():
    df = _build_full_pipeline(load_chart_fixture(FIXTURE_PATH))
    flagged = df[df["short_mr_context"]]
    assert len(flagged) == 1
    assert flagged.iloc[0]["vector_tag"] == "Green"
    # The Red climax breaches nothing in the flag column, by design.
    red_row = df[df["vector_tag"] == "Red"].iloc[0]
    assert red_row["short_mr_context"] == False  # noqa: E712


def test_reversion_entries_produce_two_distinct_timestamps():
    df = _build_full_pipeline(load_chart_fixture(FIXTURE_PATH))
    entries = find_reversion_entries(df)
    assert len(entries) == 1
    row = entries.iloc[0]
    assert row["aggressive_entry_timestamp"] is not None
    assert row["conservative_entry_timestamp"] is not None
    assert row["aggressive_entry_timestamp"] < row["conservative_entry_timestamp"]


def test_vwap_resets_at_each_session_boundary():
    df = _build_full_pipeline(load_chart_fixture(FIXTURE_PATH))
    first_bar_day2 = df[df["Datetime"].dt.date == pd.Timestamp("2026-07-02").date()].iloc[0]
    typical_price = (first_bar_day2["High"] + first_bar_day2["Low"] + first_bar_day2["Close"]) / 3.0
    assert abs(first_bar_day2["vwap"] - typical_price) < 1e-9
    assert abs(first_bar_day2["vwap_std"]) < 1e-9  # single-bar session has zero variance


def test_no_lookahead_truncating_future_rows_leaves_history_unchanged():
    """The defining check: every indicator for a historical bar must be
    identical whether or not future bars exist in the dataset at all."""
    full_df = load_chart_fixture(FIXTURE_PATH)
    cutoff = 25  # cut off after the green climax and its reversion sequence

    full_result = _build_full_pipeline(full_df.copy())
    truncated_result = _build_full_pipeline(full_df.iloc[:cutoff].copy())

    compare_cols = [
        "V_avg5", "intensity", "vector_tag", "vwap", "vwap_std",
        "vwap_upper_2sd", "vwap_upper_3sd", "vwap_lower_2sd", "vwap_lower_3sd",
        "short_mr_context", "short_mr_boundary",
    ]
    pd.testing.assert_frame_equal(
        full_result.loc[: cutoff - 1, compare_cols].reset_index(drop=True),
        truncated_result.loc[:, compare_cols].reset_index(drop=True),
    )


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
