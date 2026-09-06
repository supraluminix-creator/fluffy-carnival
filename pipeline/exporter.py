import os
import warnings
from datetime import UTC, datetime

import pandas as pd

warnings.warn(
    "pipeline.exporter.Exporter est déprécié; utiliser pipeline.export_utils.export_latest_and_timestamped",
    DeprecationWarning,
    stacklevel=2,
)


class Exporter:
    """Export CSV consolidé, horodaté, robustesse prod-safe (LEGACY)."""

    def __init__(self, export_dir: str = "exports"):
        self.export_dir = export_dir
        os.makedirs(self.export_dir, exist_ok=True)

    def export(self, rows: list[dict], fieldnames: list[str], timestamp: datetime | None = None) -> str:
        """
        Exporte les données dans latest_export.csv et pipeline_export_<timestamp>.csv
        """
        if not rows:
            raise ValueError("No data to export.")
        if not fieldnames:
            raise ValueError("Fieldnames required.")
        if timestamp is None:
            timestamp = datetime.now(UTC)
        ts_str = timestamp.strftime("%Y%m%d_%H%M%S_UTC")
        latest_path = os.path.join(self.export_dir, "latest_export.csv")
        dated_path = os.path.join(self.export_dir, f"pipeline_export_{ts_str}.csv")

        df = pd.DataFrame(rows, columns=fieldnames)
        df.to_csv(latest_path, index=False, encoding="utf-8")
        df.to_csv(dated_path, index=False, encoding="utf-8")
        return latest_path
