import os
import glob
import logging
from lenses.lens_a_atas_replay import AtasReplayLens
from lenses.lens_d_mexc_crypto import MexcCryptoLens
from airtable_client import AirtableClient
# Import Lens B, C here as they are developed...

logger = logging.getLogger(__name__)

# Which registered lenses produce crypto-native records (Exchange Fees /
# Funding Fees Paid) - keyed by class name, matching airtable_client's
# is_crypto safety-check map.
CRYPTO_LENS_CLASS_NAMES = {"MexcCryptoLens"}


class CorePipelineRouter:
    def __init__(self, airtable_client=None):
        # Register processing engines
        self.registered_lenses = [
            AtasReplayLens(),
            MexcCryptoLens(),
            # Add instances of Lens B, C here
        ]
        self.airtable_client = airtable_client

    def process_staging_directory(self, staging_path="data/raw_staging/", archive_path="data/processed_archive/"):
        target_files = glob.glob(os.path.join(staging_path, "*.*"))

        for file_path in target_files:
            if file_path.endswith("_Tape.csv"):
                # Side-file consumed directly by a lens (e.g. AtasReplayLens); not routed on its own.
                continue

            matched = False
            for lens in self.registered_lenses:
                if lens.identify_file_signature(file_path):
                    print(f"[OK] Match Found: processing {os.path.basename(file_path)} with {lens.__class__.__name__}")
                    standardized_df = lens.normalize_to_schema(file_path)
                    is_crypto = lens.__class__.__name__ in CRYPTO_LENS_CLASS_NAMES

                    self._transmit_and_archive(standardized_df, file_path, archive_path, is_crypto)
                    matched = True
                    break
            if not matched:
                print(f"[SKIP] Unknown structure or format ignored: {os.path.basename(file_path)}")

    def _transmit_and_archive(self, standardized_df, file_path, archive_path, is_crypto):
        """Push the finalized trade rows to Airtable, then apply the
        Post-Transfer Rule: only archive the raw file out of raw_staging/
        once the network transmission has fully succeeded."""
        filename = os.path.basename(file_path)

        if standardized_df is None or standardized_df.empty:
            print(f"[SKIP] No trade rows produced for {filename}; nothing to transmit.")
            return False

        client = self.airtable_client or AirtableClient()
        trade_records = standardized_df.to_dict(orient="records")
        push_results = client.push_trades(trade_records, is_crypto=is_crypto)

        failed_batches = [r for r in push_results if r.get("status") == "error"]
        if failed_batches:
            print(f"[FAIL] {len(failed_batches)} batch(es) failed transmitting {filename}; leaving file in staging.")
            return False

        os.rename(file_path, os.path.join(archive_path, filename))

        tape_path = file_path.replace("_Chart.csv", "_Tape.csv")
        if os.path.exists(tape_path):
            os.rename(tape_path, os.path.join(archive_path, os.path.basename(tape_path)))

        print(f"[OK] Transmitted {len(trade_records)} trade row(s) and archived {filename}")
        return True


if __name__ == "__main__":
    router = CorePipelineRouter()
    router.process_staging_directory()
