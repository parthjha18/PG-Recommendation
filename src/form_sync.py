"""
src/form_sync.py
─────────────────
Keeps the app's "real data" in step with the live Google Form responses, so
nobody has to download and re-send a CSV every time a friend submits.

Where the responses come from (first match wins):
  1. env var FORM_RESPONSES_URL
  2. the first line of data/form_responses_url.txt   (git-ignored)
  3. data/form_responses.csv                          (manual export fallback)

The URL is the response sheet's "Publish to web -> CSV" link. A sync downloads
it, rebuilds the real dataset (new responses only hit the geocoder, thanks to
the lookup cache) and swaps data/raw/real_pgs.csv in atomically — a failed
download or an empty result never clobbers the last good file.
"""

import io
import os

import pandas as pd
import requests

from config import (
    BASE_DIR, FORM_DATES_MONTHFIRST, FORM_RESPONSES_URL_FILE,
    LOCATION_CACHE_PATH, REAL_DATA_PATH,
)
from src.form_import import CachedLocator, build_real_dataset

MANUAL_EXPORT_PATH = os.path.join(BASE_DIR, "data", "form_responses.csv")
FETCH_TIMEOUT_SECONDS = 20


def get_source():
    """The configured responses source (URL or file path), or None."""
    env = os.environ.get("FORM_RESPONSES_URL", "").strip()
    if env:
        return env
    if os.path.exists(FORM_RESPONSES_URL_FILE):
        with open(FORM_RESPONSES_URL_FILE, encoding="utf-8") as f:
            line = f.readline().strip()
        if line:
            return line
    return MANUAL_EXPORT_PATH if os.path.exists(MANUAL_EXPORT_PATH) else None


def is_live_source(source) -> bool:
    return bool(source) and str(source).lower().startswith(("http://", "https://"))


def fetch_responses(source: str) -> pd.DataFrame:
    """Read the responses from a URL or a local CSV path."""
    if is_live_source(source):
        resp = requests.get(source, timeout=FETCH_TIMEOUT_SECONDS)
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig")
        if text.lstrip().lower().startswith(("<!doctype html", "<html")):
            raise ValueError(
                "That link returned a web page, not CSV. In Google Sheets use "
                "File -> Share -> Publish to web -> pick the 'Form Responses' tab and 'CSV'."
            )
        return pd.read_csv(io.StringIO(text), dtype=str)
    return pd.read_csv(source, dtype=str)


def sync_real_data(source=None, output=REAL_DATA_PATH, dayfirst=None, locator=None) -> dict:
    """
    Download -> convert -> atomically write the real dataset.

    Returns {"source", "responses", "rows", "pgs", "warnings", "lookups"}.
    Raises (leaving the existing file untouched) if the source is missing or
    unreachable, or produces no usable rows.
    """
    source = source or get_source()
    if not source:
        raise ValueError("No form-responses source configured.")
    if dayfirst is None:
        dayfirst = not FORM_DATES_MONTHFIRST

    responses = fetch_responses(source)
    locator = locator or CachedLocator(LOCATION_CACHE_PATH)
    rows, warnings = build_real_dataset(
        responses, dayfirst=dayfirst, resolver=locator.resolve, locality_lookup=locator.locality)
    locator.save()

    if rows.empty:
        raise ValueError("The responses produced no usable PG rows; kept the existing real data. "
                         + " ".join(warnings))

    os.makedirs(os.path.dirname(output), exist_ok=True)
    tmp = output + ".tmp"
    rows.to_csv(tmp, index=False)
    os.replace(tmp, output)

    return {
        "source": "live link" if is_live_source(source) else os.path.basename(str(source)),
        "responses": len(responses),
        "rows": len(rows),
        "pgs": int(rows["PG_Name"].nunique()),
        "warnings": warnings,
        "lookups": locator.lookups,
    }
