import pandas as pd
from .base_lens import BaseBrokerLens

class MexcCryptoLens(BaseBrokerLens):

    def identify_file_signature(self, file_path: str) -> bool:
        try:
            # Look for explicit MEXC structural layout signatures
            df = pd.read_excel(file_path, nrows=1) if file_path.endswith(('.xls', '.xlsx')) else pd.read_csv(file_path, nrows=1)
            headers = df.columns.tolist()
            return "Fee Currency" in headers or "Funding Fee" in headers or "Realized PnL" in headers
        except Exception:
            return False

    def normalize_to_schema(self, file_path: str) -> pd.DataFrame:
        df = pd.read_excel(file_path) if file_path.endswith(('.xls', '.xlsx')) else pd.read_csv(file_path)
        normalized_records = []

        # Group raw execution history steps into closed-loop completed trade summaries
        group_key = 'Position ID' if 'Position ID' in df.columns else 'Order ID'

        for trade_id, group in df.groupby(group_key):
            gross_pnl = group['Realized PnL'].sum() if 'Realized PnL' in group.columns else group['Total Amount'].sum()
            exchange_fees = group['Trading Fee'].sum() if 'Trading Fee' in group.columns else 0.0
            funding_fees = group['Funding Fee'].sum() if 'Funding Fee' in group.columns else 0.0

            normalized_records.append({
                "Trade ID": f"MEXC_{trade_id}",
                "Account ID": "MEXC_DUAL_01",
                "Asset": group['Symbol'].iloc[0],
                "Direction": "Long" if "Buy" in str(group['Side'].iloc[0]) else "Short",
                "Exec Timestamps": pd.to_datetime(group['Time'].iloc[0]).isoformat(),
                "Gross PnL": float(gross_pnl),
                "Exchange Fees": float(exchange_fees),
                "Funding Fees Paid": float(funding_fees)
            })

        return pd.DataFrame(normalized_records)
