"""Split DataSynth journal_entries CSV into body and document-level labels."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.export.label_splitter import split_label_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_csv", type=Path, help="source journal_entries CSV")
    parser.add_argument(
        "--body-output",
        type=Path,
        required=True,
        help="output CSV path for ledger body without label columns",
    )
    parser.add_argument(
        "--labels-output",
        type=Path,
        required=True,
        help="output CSV path for document-level labels",
    )
    args = parser.parse_args()

    body_path, labels_path = split_label_csv(
        args.source_csv,
        body_output_csv=args.body_output,
        labels_output_csv=args.labels_output,
    )
    print(f"body csv written: {body_path}")
    print(f"labels csv written: {labels_path}")


if __name__ == "__main__":
    main()
