from abc import ABC, abstractmethod
import pandas as pd

class BaseBrokerLens(ABC):

    @abstractmethod
    def identify_file_signature(self, file_path: str) -> bool:
        """Scan file properties or column structures to match the broker."""
        pass

    @abstractmethod
    def normalize_to_schema(self, file_path: str) -> pd.DataFrame:
        """
        Processes multi-asset transaction rows into a standardized DataFrame layout:
        [Trade_ID, Asset, Direction, Exec_Timestamp, Gross_PnL, Exchange_Fees, Funding_Fees]
        """
        pass
