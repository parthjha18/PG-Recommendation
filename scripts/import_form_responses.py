"""
scripts/import_form_responses.py
────────────────────────────────
Convert the exported Google Form responses CSV into data/raw/real_pgs.csv,
the file the app loads as its "Real data" dataset.

Usage:
    1. In the response sheet: File -> Download -> Comma-separated values (.csv)
    2. Save it as  data/form_responses.csv
    3. python scripts/import_form_responses.py
    4. Restart the ML service so it picks up the new file

Options:
    --input  PATH     responses CSV   (default data/form_responses.csv)
    --output PATH     dataset CSV     (default data/raw/real_pgs.csv)
    --monthfirst      dates in the export are MM/DD/YYYY (default is DD/MM/YYYY)
"""

import argparse
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from config import REAL_DATA_PATH  # noqa: E402
from src.form_import import build_real_dataset  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=os.path.join(ROOT, "data", "form_responses.csv"))
    ap.add_argument("--output", default=REAL_DATA_PATH)
    ap.add_argument("--monthfirst", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"Input file not found: {args.input}\n"
                 "Download the response sheet as CSV and save it there first.")

    responses = pd.read_csv(args.input, dtype=str)
    print(f"Read {len(responses)} form response(s) from {args.input}")

    rows, warnings = build_real_dataset(responses, dayfirst=not args.monthfirst)

    for w in warnings:
        print("  ⚠️ ", w)
    if rows.empty:
        sys.exit("No usable rows produced; nothing written.")

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    rows.to_csv(args.output, index=False)

    pgs = rows.groupby(["PG_Name", "Location"]).size().reset_index(name="rows")
    print(f"\n✅ Wrote {len(rows)} dataset row(s) for {len(pgs)} PG(s) -> {args.output}")
    for _, p in pgs.iterrows():
        print(f"   • {p.PG_Name}  [{p.Location}]  {p.rows} sharing type(s)")
    print("\nRestart the ML service to load the new data.")


if __name__ == "__main__":
    main()
