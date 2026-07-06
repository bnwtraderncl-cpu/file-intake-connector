import logging
import os
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

AIRTABLE_API_URL = "https://api.airtable.com/v0"
MASTER_TRADE_LOG_TABLE = "Table 2: Master Trade Log"
BULK_BATCH_SIZE = 10  # Airtable's bulk-create limit per request
RATE_LIMIT_DELAY_SECONDS = 0.2  # stay under Airtable's 5 requests/sec cap
MAX_RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF_SECONDS = 1.0

# Fields that only apply to crypto trades processed by Lens D (MEXC).
CRYPTO_ONLY_FIELDS = ("Exchange Fees", "Funding Fees Paid")


class AirtableConfigError(RuntimeError):
    pass


class AirtableAuthError(RuntimeError):
    """Raised when Airtable rejects the request as unauthorized (401)."""
    pass


class AirtableRateLimitError(RuntimeError):
    """Raised when Airtable's rate limit (429) persists past all retries."""
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

    def _post_batch(self, url: str, batch: List[Dict[str, Any]]) -> Dict[str, Any]:
        """POST a single batch, retrying on 429 and raising a clear error on 401."""
        payload = {"records": batch, "typecast": True}
        attempt = 0
        while True:
            attempt += 1
            response = self.session.post(url, json=payload)

            if response.status_code == 401:
                raise AirtableAuthError(
                    "Airtable rejected the request as unauthorized (401) - "
                    "check that AIRTABLE_PAT is valid and has access to this base."
                )

            if response.status_code == 429:
                if attempt > MAX_RATE_LIMIT_RETRIES:
                    raise AirtableRateLimitError(
                        f"Airtable rate limit (429) persisted after {MAX_RATE_LIMIT_RETRIES} retries."
                    )
                retry_after = float(response.headers.get("Retry-After", RATE_LIMIT_BACKOFF_SECONDS * attempt))
                logger.warning("Airtable rate limit hit, retrying in %.1fs (attempt %d)", retry_after, attempt)
                time.sleep(retry_after)
                continue

            response.raise_for_status()
            return response.json()

    def push_trades(self, trades: List[Dict[str, Any]], is_crypto: bool = False,
                     table: str = MASTER_TRADE_LOG_TABLE,
                     dry_run: bool = False) -> List[Dict[str, Any]]:
        """Bulk-create normalized trade records in Airtable.

        When dry_run=True, no network call is made and the composed record
        payloads are returned as-is for inspection/verification.

        Otherwise, returns one result dict per batch:
        {"status": "success", "batch_index": i, "response": {...}} or
        {"status": "error", "batch_index": i, "error": "..."}.
        A 401 or an exhausted 429 retry budget stops the run early (since
        every subsequent batch would fail the same way); other per-batch
        HTTP errors are logged and the run continues with the next batch.
        """
        records = build_airtable_payload(trades, is_crypto)
        if dry_run:
            return records

        url = f"{AIRTABLE_API_URL}/{self.base_id}/{quote(table, safe='')}"
        results = []
        for i, batch in enumerate(_chunk(records, BULK_BATCH_SIZE)):
            if i > 0:
                time.sleep(RATE_LIMIT_DELAY_SECONDS)
            try:
                response_json = self._post_batch(url, batch)
                results.append({"status": "success", "batch_index": i, "response": response_json})
            except (AirtableAuthError, AirtableRateLimitError) as exc:
                logger.error("Aborting bulk push at batch %d: %s", i, exc)
                results.append({"status": "error", "batch_index": i, "error": str(exc)})
                break
            except requests.HTTPError as exc:
                logger.warning("Batch %d failed, continuing with remaining batches: %s", i, exc)
                results.append({"status": "error", "batch_index": i, "error": str(exc)})
        return results
