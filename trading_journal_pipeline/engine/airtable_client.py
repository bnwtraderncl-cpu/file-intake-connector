import os
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

import requests
from dotenv import load_dotenv

AIRTABLE_API_URL = "https://api.airtable.com/v0"
MASTER_TRADE_LOG_TABLE = "Table 2: Master Trade Log"
BULK_BATCH_SIZE = 10  # Airtable's bulk-create limit per request
RATE_LIMIT_DELAY_SECONDS = 0.2  # stay under Airtable's 5 requests/sec cap

# Fields that only apply to crypto trades processed by Lens D (MEXC).
CRYPTO_ONLY_FIELDS = ("Exchange Fees", "Funding Fees Paid")


class AirtableConfigError(RuntimeError):
    pass


def load_airtable_config(env_path: Optional[str] = None) -> Dict[str, str]:
    """Load AIRTABLE_PAT and AIRTABLE_BASE_ID from the environment/.env file."""
    load_dotenv(dotenv_path=env_path)
    pat = os.getenv("AIRTABLE_PAT")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    if not pat or not base_id:
        raise AirtableConfigError(
            "AIRTABLE_PAT and AIRTABLE_BASE_ID must be set (via .env or the environment)."
        )
    return {"pat": pat, "base_id": base_id}


def build_trade_fields(trade: Dict[str, Any], is_crypto: bool) -> Dict[str, Any]:
    """Safety-check map: crypto-only fields (Exchange Fees, Funding Fees Paid)
    are only appended when the record comes from a crypto (Lens D) source."""
    fields = {key: value for key, value in trade.items() if key not in CRYPTO_ONLY_FIELDS}
    if is_crypto:
        for key in CRYPTO_ONLY_FIELDS:
            if key in trade:
                fields[key] = trade[key]
    return fields


def build_airtable_payload(trades: Iterable[Dict[str, Any]], is_crypto: bool) -> List[Dict[str, Any]]:
    """Turn normalized trade records into Airtable bulk-create record objects."""
    return [{"fields": build_trade_fields(trade, is_crypto)} for trade in trades]


def _chunk(records: List[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
    for i in range(0, len(records), size):
        yield records[i:i + size]


class AirtableClient:
    def __init__(self, pat: Optional[str] = None, base_id: Optional[str] = None,
                 env_path: Optional[str] = None):
        if not pat or not base_id:
            config = load_airtable_config(env_path)
            pat = pat or config["pat"]
            base_id = base_id or config["base_id"]
        self.base_id = base_id
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {pat}",
            "Content-Type": "application/json",
        })

    def push_trades(self, trades: List[Dict[str, Any]], is_crypto: bool = False,
                     table: str = MASTER_TRADE_LOG_TABLE,
                     dry_run: bool = False) -> List[Dict[str, Any]]:
        """Bulk-create normalized trade records in Airtable.

        When dry_run=True, no network call is made and the composed record
        payloads are returned as-is for inspection/verification.
        """
        records = build_airtable_payload(trades, is_crypto)
        if dry_run:
            return records

        url = f"{AIRTABLE_API_URL}/{self.base_id}/{quote(table, safe='')}"
        responses = []
        for i, batch in enumerate(_chunk(records, BULK_BATCH_SIZE)):
            if i > 0:
                time.sleep(RATE_LIMIT_DELAY_SECONDS)
            response = self.session.post(url, json={"records": batch, "typecast": True})
            response.raise_for_status()
            responses.append(response.json())
        return responses
