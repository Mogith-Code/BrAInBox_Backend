"""Run an offline evaluation (placeholder).

Usage:  python -m ai_service.evals.run_eval --name rag
"""

import argparse
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
EVALS = ["rag", "notes", "mcq", "marking", "moderation"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an offline AI evaluation")
    parser.add_argument("--name", choices=EVALS, required=True)
    args = parser.parse_args()

    # TODO(owner of each eval, see README.md): load DATA_DIR/<name>.jsonl, run the pipeline
    #   with real providers, compute the metric and print/save a JSON report.
    report = {"eval": args.name, "status": "todo", "data_dir": str(DATA_DIR)}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
