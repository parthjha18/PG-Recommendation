"""
src/data_loader.py
──────────────────
Responsible for:
  - Reading the CSV dataset from disk
  - Validating that all required columns exist
  - Removing duplicates
  - Returning a clean raw DataFrame (no encoding yet)
"""

import os
import pandas as pd
import sys
from sqlalchemy import create_engine

# Add project root to path so config can be imported from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE_URL, REQUIRED_COLUMNS, REAL_DATA_PATH


def load_raw_data() -> pd.DataFrame:
    """
    Load the PG dataset from PostgreSQL.

    Returns:
        Raw DataFrame with duplicates removed.

    Raises:
        ValueError: If any required column is missing from the dataset.
    """
    engine = create_engine(DATABASE_URL)
    
    try:
        df = pd.read_sql("SELECT * FROM pg_dataset", engine)
    except Exception as e:
        raise RuntimeError(f"Failed to read from database: {e}")

    # Check all required columns are present
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        raise ValueError(
            f"The following required columns are missing from the dataset:\n"
            f"  {missing_cols}"
        )

    # Remove exact duplicate rows
    original_len = len(df)
    df = df.drop_duplicates()
    removed = original_len - len(df)

    print(f"✅  Loaded {len(df)} PG records  ({removed} duplicates removed)")
    return df


def load_real_data(path: str = REAL_DATA_PATH):
    """
    Load the real, form-collected PGs (see scripts/import_form_responses.py).

    Returns the raw DataFrame, or None when no real data has been imported yet
    (a normal state, not an error).
    """
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        raise ValueError(f"{path} is missing required columns: {missing_cols}")
    print(f"✅  Loaded {len(df)} REAL PG rows from {os.path.basename(path)}")
    return df


def get_unique_locations(df: pd.DataFrame) -> list:
    """Return a sorted list of unique location names (title-cased) for UI autocomplete."""
    return sorted(df["Location"].str.title().unique().tolist())
