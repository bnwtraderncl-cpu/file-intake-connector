import logging
import os

import pandas as pd

from .base_lens import BaseBrokerLens

try:
    from ..vwap_vectors import run_vwap_vector_analysis
    from ..risk_models import compute_trade_pnl, load_tape_fixture, run_concurrent_risk_simulation, select_winning_model
except ImportError:
    from vwap_vectors import run_vwap_vector_analysis
    from risk_models import compute_trade_pnl, load_tape_fixture, run_concurrent_risk_simulation, select_winning_model

logger = logging.getLogger(__name__)

STANDARD_COLUMNS = (
    "Trade ID", "Account ID", "Asset", "Direction", "Exec Timestamps",
    "Gross PnL", "Exchange Fees", "Funding Fees Paid",
)

REPLAY_ACCOUNT_ID = "ATAS_REPLAY_BACKTEST"
REQUIRED_CHART_COLUMNS = {"Datetime", "Open", "High", "Low", "Close", "Volume"}


class AtasReplayLens(BaseBrokerLens):
    """Lens A: ATAS Replay backtest chart data.

    Unlike a broker execution export, this lens doesn't parse already-closed
    trades - it drives the vwap_vectors short mean-reversion signal engine
    and the risk_models concurrent stop-loss simulation over historical
    replay candles, then reports the single winning risk model's outcome
    (highest Net Expectancy, ties broken by lowest MAE) as the standardized
    trade row for each flagged entry.
    """

    def identify_file_signature(self, file_path: str) -> bool:
        if not file_path.endswith("_Chart.csv"):
            return False
        try:
            df = pd.read_csv(file_path, nrows=1)
            return REQUIRED_CHART_COLUMNS.issubset(set(df.columns))
        except Exception:
            return False

    def normalize_to_schema(self, file_path: str) -> pd.DataFrame:
        vwap_result = run_vwap_vector_analysis(file_path)
        candles = vwap_result["candles"]
        entries = vwap_result["reversion_entries"]

        if entries.empty:
            logger.info("No flagged short entries in %s; nothing to simulate.", file_path)
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        tape_path = file_path.replace("_Chart.csv", "_Tape.csv")
        tape_df = load_tape_fixture(tape_path) if os.path.exists(tape_path) else None

        risk_results = run_concurrent_risk_simulation(candles, entries, tape_df)
        resolved = risk_results[risk_results["outcome"] != "open"]
        if resolved.empty:
            logger.warning("No resolved simulated trades for %s; nothing to report.", file_path)
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        winning_model = select_winning_model(resolved)
        winning_trades = compute_trade_pnl(resolved[resolved["model"] == winning_model])
        logger.info("Winning risk model for %s: %s", os.path.basename(file_path), winning_model)

        asset = os.path.basename(file_path).replace("_Chart.csv", "")
        records = []
        for _, trade in winning_trades.iterrows():
            entry_ts = pd.Timestamp(trade["entry_timestamp"])
            records.append({
                "Trade ID": f"ATAS_{trade['signal_index']}_{trade['entry_variant']}_{entry_ts:%Y%m%d%H%M%S}",
                "Account ID": REPLAY_ACCOUNT_ID,
                "Asset": asset,
                "Direction": "Short",
                "Exec Timestamps": entry_ts.isoformat(),
                "Gross PnL": float(trade["pnl"]),
                "Exchange Fees": 0.0,
                "Funding Fees Paid": 0.0,
            })

        return pd.DataFrame(records, columns=STANDARD_COLUMNS)
