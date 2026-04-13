"""Pilot orchestration: end-to-end evaluation pipeline.

Usage:
    # Mock mode (no API costs)
    python -m pilot.run --dataset fixtures/sample.jsonl

    # c-CRAB benchmark (real data, no API cost for loading)
    python -m pilot.run --benchmark ccrab \\
        --benchmark-path /path/to/ccrab/results_preprocessed/preprocess_dataset.jsonl \\
        --reviewer anthropic --judge anthropic

    # Real mode on fixtures
    python -m pilot.run --dataset fixtures/sample.jsonl \\
        --reviewer anthropic --judge anthropic,openai

The pilot runs in mock mode by default. Real mode uses the AnthropicReviewer,
AnthropicJudge, and OpenAIJudge adapters (see api_adapters.py).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from pilot.data import load_pull_requests
from pilot.judge import Judge, MockJudge
from pilot.matching import MatchingOutcome, match_pr
from pilot.metrics import compute_metrics
from pilot.panel import JudgePanel
from pilot.reporting import write_json_report, write_markdown_report
from pilot.reviewer import MockReviewer, Reviewer
from pilot.schemas import MetricsReport


def build_reviewer(args: argparse.Namespace) -> Reviewer:
    """Select and instantiate the reviewer based on CLI args."""
    if args.reviewer == "mock":
        fixture = Path(args.reviewer_fixture)
        return MockReviewer(fixture)
    if args.reviewer == "anthropic":
        from anthropic import Anthropic  # Lazy import — only needed in real mode

        from pilot.api_adapters import AnthropicReviewer

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is required for --reviewer anthropic"
            )
        client = Anthropic(api_key=api_key)
        return AnthropicReviewer(client=client, model=args.reviewer_model)
    raise ValueError(f"Unknown reviewer: {args.reviewer}")


def build_judge(args: argparse.Namespace) -> Judge:
    """Select and instantiate the judge (or judge panel) based on CLI args.

    The --judge flag accepts a comma-separated list of backends. If more than
    one is given, they are wrapped in a JudgePanel with majority vote.
    """
    backends = [b.strip() for b in args.judge.split(",") if b.strip()]
    judges: list[Judge] = []

    for i, backend in enumerate(backends):
        if backend == "mock":
            fixture = Path(args.judge_fixture)
            judges.append(MockJudge(fixture, model_name=f"mock-judge-{i+1}"))
        elif backend == "anthropic":
            from anthropic import Anthropic

            from pilot.api_adapters import AnthropicJudge

            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY environment variable is required for anthropic judge"
                )
            client = Anthropic(api_key=api_key)
            model = args.judge_models.split(",")[i] if args.judge_models else "claude-opus-4-6"
            judges.append(AnthropicJudge(client=client, model=model))
        elif backend == "openai":
            from openai import OpenAI

            from pilot.api_adapters import OpenAIJudge

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY environment variable is required for openai judge"
                )
            client = OpenAI(api_key=api_key)
            model = args.judge_models.split(",")[i] if args.judge_models else "gpt-4o"
            judges.append(OpenAIJudge(client=client, model=model))
        else:
            raise ValueError(f"Unknown judge backend: {backend}")

    if len(judges) == 1:
        return judges[0]
    return JudgePanel(judges)


def load_dataset(args: argparse.Namespace) -> tuple[list, str]:
    """Load PRs from either a fixture file or a named benchmark.

    Returns:
        (list of PullRequest, evaluation set name)
    """
    if args.benchmark:
        if args.benchmark == "ccrab":
            from pilot.datasets.ccrab import load_ccrab, get_dataset_stats

            benchmark_path = Path(args.benchmark_path)
            prs = load_ccrab(
                benchmark_path,
                max_diff_chars=args.max_diff_chars,
            )
            stats = get_dataset_stats(prs)
            print(f"Loaded c-CRAB: {stats['n_prs']} PRs, "
                  f"{stats['n_ground_truth_issues']} GT issues, "
                  f"median diff {stats['diff_length_median']} chars")
            print(f"Change types: {stats['change_type_distribution']}")
            return prs, f"ccrab-{stats['n_prs']}prs"
        raise ValueError(f"Unknown benchmark: {args.benchmark}")
    return load_pull_requests(args.dataset), args.dataset.name


def run_pipeline(
    prs: list,
    reviewer: Reviewer,
    judge: Judge,
    evaluation_set_name: str,
) -> MetricsReport:
    """Run the full evaluation pipeline.

    Steps:
    1. For each PR, run the reviewer to produce findings.
    2. For each PR, use the judge to match findings to ground truth.
    3. Compute precision, recall, F1 per dimension and aggregate.
    4. Return the metrics report.
    """
    findings_by_pr: dict[str, list] = {}
    outcomes: list[MatchingOutcome] = []

    for pr in prs:
        findings = reviewer.review(pr)
        findings_by_pr[pr.pr_id] = findings
        outcome = match_pr(pr, findings, judge)
        outcomes.append(outcome)

    # If judge is a panel, record each judge's name; else record the single judge.
    if isinstance(judge, JudgePanel):
        judge_panel = [j.model_name for j in judge.judges]
    else:
        judge_panel = [judge.model_name]

    # Capture usage metadata if adapters expose it
    usage_metadata: dict[str, str] = {}
    if hasattr(reviewer, "usage"):
        usage_metadata["reviewer_input_tokens"] = str(reviewer.usage.input_tokens)
        usage_metadata["reviewer_output_tokens"] = str(reviewer.usage.output_tokens)
        usage_metadata["reviewer_calls"] = str(reviewer.usage.call_count)
        if reviewer.usage.errors:
            usage_metadata["reviewer_errors"] = str(reviewer.usage.errors)

    if isinstance(judge, JudgePanel):
        for i, j in enumerate(judge.judges):
            if hasattr(j, "usage"):
                usage_metadata[f"judge{i+1}_input_tokens"] = str(j.usage.input_tokens)
                usage_metadata[f"judge{i+1}_output_tokens"] = str(j.usage.output_tokens)
                usage_metadata[f"judge{i+1}_calls"] = str(j.usage.call_count)
    elif hasattr(judge, "usage"):
        usage_metadata["judge_input_tokens"] = str(judge.usage.input_tokens)
        usage_metadata["judge_output_tokens"] = str(judge.usage.output_tokens)
        usage_metadata["judge_calls"] = str(judge.usage.call_count)

    report = compute_metrics(
        prs=prs,
        findings_by_pr=findings_by_pr,
        outcomes=outcomes,
        reviewer_model=reviewer.model_name,
        judge_panel=judge_panel,
        evaluation_set=evaluation_set_name,
        run_metadata={
            "pilot_version": "0.3.0",
            **usage_metadata,
        },
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the pilot evaluation pipeline.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("fixtures/sample.jsonl"),
        help="Path to the PR dataset JSONL file.",
    )
    parser.add_argument(
        "--reviewer",
        choices=["mock", "anthropic"],
        default="mock",
        help="Reviewer backend.",
    )
    parser.add_argument(
        "--reviewer-model",
        default="claude-sonnet-4-6",
        help="Model identifier for the reviewer (when using a real backend).",
    )
    parser.add_argument(
        "--judge",
        default="mock",
        help="Judge backend(s), comma-separated. Examples: 'mock', 'anthropic', 'anthropic,openai'.",
    )
    parser.add_argument(
        "--judge-models",
        default=None,
        help="Comma-separated model identifiers for judge backends, in the same order as --judge.",
    )
    parser.add_argument(
        "--reviewer-fixture",
        type=Path,
        default=Path("fixtures/mock_reviews.jsonl"),
        help="Fixture file for mock reviewer.",
    )
    parser.add_argument(
        "--judge-fixture",
        type=Path,
        default=Path("fixtures/mock_judge_matches.jsonl"),
        help="Fixture file for mock judge.",
    )
    # Benchmark loading
    parser.add_argument(
        "--benchmark",
        choices=["ccrab"],
        default=None,
        help="Named benchmark to load. If set, --dataset is ignored.",
    )
    parser.add_argument(
        "--benchmark-path",
        type=Path,
        default=None,
        help="Path to the benchmark data file (required when --benchmark is set).",
    )
    parser.add_argument(
        "--max-diff-chars",
        type=int,
        default=50_000,
        help="Truncate diffs longer than this many characters (default: 50000).",
    )
    parser.add_argument(
        "--max-prs",
        type=int,
        default=None,
        help="Limit the number of PRs to evaluate (for cost control).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results"),
        help="Directory to write report files into.",
    )
    parser.add_argument(
        "--name",
        default="pilot-run",
        help="Name of this evaluation run (used in report filenames).",
    )
    args = parser.parse_args(argv)

    prs, eval_set_name = load_dataset(args)
    if args.max_prs is not None:
        prs = prs[:args.max_prs]
        print(f"Limited to first {args.max_prs} PRs")

    reviewer = build_reviewer(args)
    judge = build_judge(args)

    report = run_pipeline(
        prs=prs,
        reviewer=reviewer,
        judge=judge,
        evaluation_set_name=eval_set_name,
    )

    json_path = args.output_dir / f"{args.name}.json"
    md_path = args.output_dir / f"{args.name}.md"
    write_json_report(report, json_path)
    write_markdown_report(report, md_path)

    print(f"Report written to {json_path} and {md_path}")
    print()
    print(f"PRs evaluated: {report.n_prs}")
    print(
        f"TP / FP / FN: {report.total_true_positives} / "
        f"{report.total_false_positives} / {report.total_false_negatives}"
    )
    if report.aggregate_precision is not None:
        print(f"Precision: {report.aggregate_precision:.1%}")
    if report.aggregate_recall is not None:
        print(f"Recall: {report.aggregate_recall:.1%}")
    if report.aggregate_f1 is not None:
        print(f"F1: {report.aggregate_f1:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
