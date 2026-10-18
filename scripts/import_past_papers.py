"""Import past papers into papers / questions / mcq_options (placeholder). Owner: Udith.

python scripts/import_past_papers.py --file data/questions/2023_mcq.json
"""

import argparse

import _bootstrap  # noqa: F401


def main() -> None:
    parser = argparse.ArgumentParser(description="Import past papers (placeholder)")
    parser.add_argument("--file", required=True)
    args = parser.parse_args()
    # TODO(Udith): define the JSON format in data/questions/README.md, then create one
    #   `papers` row (paper_type="past_paper", year) + questions + options + paper_questions.
    print(f"TODO: import {args.file}")


if __name__ == "__main__":
    main()
