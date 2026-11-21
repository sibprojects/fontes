"""`python -m fontes.eval`: ask the eval set through a running stack and report the scores."""

import argparse
import asyncio
import json
import sys
import tomllib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

from fontes.eval.cases import (
    DEFAULT_CASES,
    DEFAULT_SAMPLES,
    REPO_ROOT,
    Case,
    CaseError,
    load_cases,
)
from fontes.eval.runner import EvalClient, StackError, run
from fontes.eval.scoring import render, summarize


def main(argv: list[str] | None = None) -> int:
    started = datetime.now(UTC)
    parser = argparse.ArgumentParser(prog="python -m fontes.eval", description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "eval" / "results" / f"{started:%Y%m%d-%H%M%S}.json",
    )
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.cases, args.samples)
    except (OSError, tomllib.TOMLDecodeError, CaseError) as exc:
        print(f"error: {args.cases}: {exc}", file=sys.stderr)
        return 1
    try:
        return asyncio.run(_main(args, cases, started))
    except (StackError, httpx.TransportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


async def _main(args: argparse.Namespace, cases: list[Case], started: datetime) -> int:
    async with EvalClient(args.base_url) as client:
        await client.prepare(args.samples)
        results, provider, model = await run(cases, client)
    summary = summarize(results)
    print(render(summary, results, provider, model))
    report = {
        "provider": provider,
        "model": model,
        "started_at": started.isoformat(),
        "base_url": args.base_url,
        "summary": asdict(summary),
        "results": [
            {
                "id": r.case.id,
                "passed": r.passed,
                "checks": r.checks,
                "label": r.outcome.label,
                "documents": list(r.outcome.documents),
                "error": r.outcome.error,
                "seconds": round(r.outcome.seconds, 2),
                "answer": r.outcome.answer,
            }
            for r in results
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
