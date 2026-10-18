"""Compare AI-estimated marks with manual marks (placeholder). Owner: Keshomigha.

python scripts/eval_accuracy.py --file data/knowledge_base/manual_marks.csv
"""

import argparse

import _bootstrap  # noqa: F401


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimated vs manual marks (placeholder)")
    parser.add_argument("--file", required=True, help="CSV: evaluation_id,manual_marks")
    args = parser.parse_args()
    # TODO(Keshomigha): load evaluations.estimated_marks for each id, then print
    #   mean absolute error, % within 1 mark, and the worst 10 cases.
    print(f"TODO: compare marks in {args.file}")


if __name__ == "__main__":
    main()
