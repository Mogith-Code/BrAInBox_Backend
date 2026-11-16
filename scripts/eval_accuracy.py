"""Compare estimated marks with a teacher's marks and try other similarity thresholds.

Input: a CSV with the columns  question, answer, manual_marks, max_marks, points
where `points` is a JSON list like
    [{"text": "ATP is used", "marks": 1, "keywords": ["ATP"]}]

    python scripts/eval_accuracy.py --file data/knowledge_base/marked_answers.csv
    python scripts/eval_accuracy.py --file ... --sweep        # try other thresholds

It runs the real scoring pipeline (ai_service/pipelines/evaluation), so with USE_FAKE_AI=false
and a GEMINI_API_KEY it uses real embeddings: this is the only place outside production that
calls real models. The report prints the mean absolute error, the share of answers within one
mark, and the worst cases. Use 30 or more marked answers before changing a threshold.
"""

import argparse
import asyncio
import csv
import json
from typing import Any

import _bootstrap  # noqa: F401

from ai_service.config import get_settings
from ai_service.pipelines.evaluation.scorer import score_points, totals
from ai_service.pipelines.evaluation.semantic_match import best_matches


def load(path: str) -> list[dict[str, Any]]:
    samples = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for n, row in enumerate(csv.DictReader(handle), start=1):
            points = [
                {
                    "id": f"{n}-{i}",
                    "text": p["text"],
                    "marks": float(p.get("marks") or 1),
                    "is_required": bool(p.get("is_required")),
                    "keywords": [
                        {"keyword": k, "synonyms": []} if isinstance(k, str) else k
                        for k in p.get("keywords", [])
                    ],
                }
                for i, p in enumerate(json.loads(row["points"]))
            ]
            samples.append(
                {
                    "question": row.get("question", ""),
                    "answer": row["answer"],
                    "manual": float(row["manual_marks"]),
                    "max": float(row.get("max_marks") or sum(p["marks"] for p in points)),
                    "points": points,
                }
            )
    return samples


def report(pairs: list[tuple[float, float]]) -> dict[str, float]:
    errors = [abs(estimated - manual) for estimated, manual in pairs]
    return {
        "mae": sum(errors) / len(errors),
        "within_one": sum(1 for e in errors if e <= 1.0) / len(errors),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--file", required=True, help="CSV of manually marked answers")
    parser.add_argument("--sweep", action="store_true", help="also try other thresholds")
    args = parser.parse_args()

    settings = get_settings()
    samples = load(args.file)
    if not samples:
        raise SystemExit("The file has no rows.")
    # Embeddings are the slow, paid part: compute the matches once, then re-score for free.
    for sample in samples:
        sample["matches"] = await best_matches(
            sample["answer"], [p["text"] for p in sample["points"]]
        )

    def estimate(sample: dict[str, Any], covered: float, partial: float) -> float:
        results = score_points(
            sample["points"],
            sample["matches"],
            sample["answer"],
            covered_at=covered,
            partial_at=partial,
        )
        return totals(results, sample["max"])["estimated_marks"]

    covered, partial = settings.EVAL_COVERED_SIMILARITY, settings.EVAL_PARTIAL_SIMILARITY
    rows = [(estimate(s, covered, partial), s["manual"], s) for s in samples]
    current = report([(e, m) for e, m, _ in rows])
    print(f"Samples: {len(samples)}   fake AI: {settings.use_fakes}")
    if len(samples) < 30:
        print("  (fewer than 30 samples: treat these numbers as a rough guide)")
    print(f"Thresholds: covered >= {covered}, partial >= {partial}")
    print(f"Mean absolute error: {current['mae']:.2f} marks")
    print(f"Within one mark:     {current['within_one']:.0%}")
    print("\nWorst cases (estimated / manual / max):")
    for estimated, manual, sample in sorted(rows, key=lambda r: -abs(r[0] - r[1]))[:10]:
        print(f"  {estimated:>4g} / {manual:>4g} / {sample['max']:>4g}   {sample['answer'][:70]!r}")

    if args.sweep:
        print("\nThreshold sweep (covered, partial -> MAE, within one mark):")
        best = (current["mae"], covered, partial)
        for c in (0.70, 0.75, 0.80, 0.85, 0.90):
            for p in (0.50, 0.55, 0.60, 0.65, 0.70):
                if p >= c:
                    continue
                r = report([(estimate(s, c, p), s["manual"]) for s in samples])
                print(f"  {c:.2f}, {p:.2f} -> {r['mae']:.2f}, {r['within_one']:.0%}")
                best = min(best, (r["mae"], c, p))
        print(
            f"\nLowest error: covered >= {best[1]}, partial >= {best[2]} (MAE {best[0]:.2f}). "
            "Set EVAL_COVERED_SIMILARITY / EVAL_PARTIAL_SIMILARITY to change them."
        )


if __name__ == "__main__":
    asyncio.run(main())
