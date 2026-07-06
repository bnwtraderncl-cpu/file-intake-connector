import os
import glob
from lenses.lens_d_mexc_crypto import MexcCryptoLens
# Import Lens A, B, C here as they are developed...

class CorePipelineRouter:
    def __init__(self):
        # Register processing engines
        self.registered_lenses = [
            MexcCryptoLens(),
            # Add instances of Lens A, B, C here
        ]

    def process_staging_directory(self, staging_path="data/raw_staging/", archive_path="data/processed_archive/"):
        target_files = glob.glob(os.path.join(staging_path, "*.*"))

        for file_path in target_files:
            matched = False
            for lens in self.registered_lenses:
                if lens.identify_file_signature(file_path):
                    print(f"[OK] Match Found: processing {os.path.basename(file_path)} with {lens.__class__.__name__}")
                    standardized_df = lens.normalize_to_schema(file_path)

                    # Next step: Aggregate data metrics array and stream via REST API to Airtable
                    # Post-processing command: os.rename(file_path, os.path.join(archive_path, os.path.basename(file_path)))
                    matched = True
                    break
            if not matched:
                print(f"[SKIP] Unknown structure or format ignored: {os.path.basename(file_path)}")

if __name__ == "__main__":
    router = CorePipelineRouter()
    router.process_staging_directory()
