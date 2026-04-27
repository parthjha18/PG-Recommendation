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

# Add project root to path so config can be imported from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_RAW_PATH, REQUIRED_COLUMNS


def load_raw_data(filepath: str = DATA_RAW_PATH) -> pd.DataFrame:
    """
    Load the PG dataset from a CSV file.

    Args:
        filepath: Path to the CSV file (defaults to config.DATA_RAW_PATH)

    Returns:
        Raw DataFrame with duplicates removed.

    Raises:
        FileNotFoundError: If the CSV file does not exist.
        ValueError: If any required column is missing from the dataset.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(
            f"Dataset not found at: {filepath}\n"
            f"Please make sure the CSV is placed in: data/raw/"
        )

    df = pd.read_csv(filepath)

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


def get_unique_locations(df: pd.DataFrame) -> list:
    """Return a sorted list of unique location names (title-cased) for UI autocomplete."""
    return sorted(df["Location"].str.title().unique().tolist())
