"""Load telco CSVs from the local DataSet folder and join them."""

from __future__ import annotations

from pathlib import Path

from app import config
from app.analysis.loader import column_names, load_directory, sample_preview


def dataset_directory(directory: str | Path | None = None) -> Path:
    if directory is not None:
        path = Path(directory)
    else:
        path = Path(config.DATASET_DIR)
    if not path.is_absolute():
        path = config.ROOT / path
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {path}")
    return path


def load_from_dataset(
    directory: str | Path | None = None,
) -> tuple[list[dict], list[str], dict]:
    path = dataset_directory(directory)
    rows, files = load_directory(path)
    meta = {
        "source": "local",
        "directory": str(path),
        "files": files,
        "row_count": len(rows),
        "columns": column_names(rows),
    }
    return rows, files, meta


def preview_from_rows(rows: list[dict], limit: int = 8) -> dict:
    return {
        "columns": column_names(rows),
        "sample": sample_preview(rows, limit=limit),
        "row_count": len(rows),
    }
