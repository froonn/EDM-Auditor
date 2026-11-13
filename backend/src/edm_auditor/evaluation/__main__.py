"""Command line: check the corpus, run it with real models, or score a saved run again."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from .corpus import load_corpus
from .scoring import render_markdown, score_run

BACKEND_DIR = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS = BACKEND_DIR / "evaluation" / "corpus"
DEFAULT_RESULTS = BACKEND_DIR / "evaluation" / "results"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m edm_auditor.evaluation")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="check that the labels match the corpus files")
    run_parser = commands.add_parser("run", help="run the corpus with the configured models")
    run_parser.add_argument("--label", required=True, help="name of the run, e.g. baseline")
    run_parser.add_argument("--out", type=Path, default=DEFAULT_RESULTS)
    run_parser.add_argument(
        "--min-interval", type=float, default=4.5,
        help="seconds between model requests; 4.5 keeps under 15 requests a minute",
    )
    score_parser = commands.add_parser("score", help="score a saved run again")
    score_parser.add_argument("result", type=Path)
    args = parser.parse_args(argv)

    corpus = load_corpus(args.corpus)
    if args.command == "check":
        print(
            f"{len(corpus.acts)} legal acts, {len(corpus.documents)} documents, "
            f"{sum(len(item.violations) for item in corpus.documents)} violations: labels are valid"
        )
        return 0

    if args.command == "score":
        saved = json.loads(args.result.read_text(encoding="utf-8"))
        run = saved["run"]
        print(render_markdown(score_run(corpus, run), run))
        return 0

    from .runner import run_corpus

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y%m%d-%H%M}-{args.label}"
    run = run_corpus(
        corpus,
        label=args.label,
        min_interval=args.min_interval,
        log_file=args.out / f"{stem}.log",
    )
    run["preset"] = os.environ.get("EDM_MODEL_PRESET", "")
    metrics = score_run(corpus, run)
    report = render_markdown(metrics, run)
    (args.out / f"{stem}.json").write_text(
        json.dumps({"run": run, "metrics": metrics}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.out / f"{stem}.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved to {args.out / stem}.json and .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
