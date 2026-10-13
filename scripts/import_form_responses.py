"""
scripts/import_form_responses.py
────────────────────────────────
Build data/raw/real_pgs.csv (the app's "Real data") from the Google Form responses.

Usage:
    python scripts/import_form_responses.py                 # uses the configured source
    python scripts/import_form_responses.py --input FILE_OR_URL
    python scripts/import_form_responses.py --monthfirst    # export dates are MM/DD/YYYY

Source, in order: env FORM_RESPONSES_URL, first line of data/form_responses_url.txt
(the sheet's "Publish to web -> CSV" link), or data/form_responses.csv (manual export).
The app can also re-sync on demand from its "Refresh" button, so this script is
only needed for a manual run.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from config import REAL_DATA_PATH  # noqa: E402
from src.form_sync import get_source, sync_real_data  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="CSV file path or published-CSV URL (default: configured source)")
    ap.add_argument("--output", default=REAL_DATA_PATH)
    ap.add_argument("--monthfirst", action="store_true", help="dates in the export are MM/DD/YYYY")
    args = ap.parse_args()

    source = args.input or get_source()
    if not source:
        sys.exit("No responses source found. Put the sheet's published-CSV link in "
                 "data/form_responses_url.txt, or save an export as data/form_responses.csv.")
    try:
        result = sync_real_data(source, output=args.output, dayfirst=not args.monthfirst)
    except Exception as exc:  # report cleanly instead of a traceback
        sys.exit(f"Import failed: {exc}")

    print(f"Read {result['responses']} form response(s) from {result['source']}")
    for w in result["warnings"]:
        print("  ⚠️ ", w)
    print(f"\n✅ Wrote {result['rows']} dataset row(s) for {result['pgs']} PG(s) -> {args.output}")
    print("Restart the ML service, or press Refresh in the app, to load it.")


if __name__ == "__main__":
    main()
