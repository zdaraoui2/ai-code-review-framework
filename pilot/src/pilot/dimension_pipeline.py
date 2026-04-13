"""Dimension classification pipeline.

Multi-run consensus classification of ground truth issues into the
framework's 15-dimension taxonomy. Classifies each GT issue N times,
takes majority vote, and flags disagreements for human review.

Usage:
    # Classify c-CRAB dataset using Anthropic API (3 runs)
    python -m pilot.dimension_pipeline classify \\
        --benchmark ccrab \\
        --benchmark-path /path/to/ccrab/preprocess_dataset.jsonl \\
        --provider anthropic --model claude-opus-4-6 \\
        --runs 3 \\
        --output classified/ccrab.jsonl

    # Cross-family consensus (Anthropic + OpenAI)
    python -m pilot.dimension_pipeline classify \\
        --benchmark ccrab \\
        --benchmark-path /path/to/ccrab/preprocess_dataset.jsonl \\
        --providers anthropic,openai \\
        --models claude-opus-4-6,gpt-4o \\
        --runs-per-provider 3 \\
        --output classified/ccrab.jsonl

    # Generate a spot-check sample for human validation
    python -m pilot.dimension_pipeline spot-check \\
        --classified classified/ccrab.jsonl \\
        --n 50 \\
        --output spot-check/ccrab-50.jsonl

    # Validate human spot-check against AI labels
    python -m pilot.dimension_pipeline validate \\
        --classified classified/ccrab.jsonl \\
        --human-labels spot-check/ccrab-50-labelled.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pilot.autoresearch import (
    DIMENSION_CLASSIFIER_INITIAL,
    AnthropicLLM,
    ClaudeCodeLLM,
    LLMClient,
    MockLLM,
    OpenAILLM,
    make_dimension_classify_fn,
)
from pilot.schemas import (
    ChangeType,
    Dimension,
    GroundTruthIssue,
    Location,
    PullRequest,
    Severity,
)


logger = logging.getLogger(__name__)


# --- Classification result types ----------------------------------------


@dataclass
class IssueClassification:
    """Classification result for a single GT issue."""

    issue_id: str
    pr_id: str
    text: str
    predictions: list[str]  # Raw dimension predictions from each run
    majority_dimension: Dimension
    agreement_ratio: float  # Fraction of runs that agree with majority
    confident: bool  # True if agreement_ratio >= confidence_threshold
    runner_up: str | None = None  # Second most common prediction (if any)


@dataclass
class ClassificationReport:
    """Summary of a classification run."""

    total_issues: int
    confident_count: int
    flagged_count: int  # Low agreement — needs review
    dimension_distribution: dict[str, int]
    mean_agreement: float
    providers_used: list[str]
    runs_per_provider: int
    confusion_summary: list[str] = field(default_factory=list)

    def print_summary(self) -> None:
        print(f"\n{'='*60}")
        print(f"Dimension Classification Report")
        print(f"{'='*60}")
        print(f"Total GT issues classified: {self.total_issues}")
        print(f"Confident (agreement >= threshold): {self.confident_count} ({self.confident_count/self.total_issues:.0%})")
        print(f"Flagged for review: {self.flagged_count} ({self.flagged_count/self.total_issues:.0%})")
        print(f"Mean agreement ratio: {self.mean_agreement:.2f}")
        print(f"Providers: {', '.join(self.providers_used)}")
        print(f"Runs per provider: {self.runs_per_provider}")
        print(f"\nDimension distribution:")
        for dim, count in sorted(self.dimension_distribution.items(), key=lambda x: -x[1]):
            pct = count / self.total_issues * 100
            print(f"  {dim:25s} {count:4d} ({pct:5.1f}%)")
        if self.confusion_summary:
            print(f"\nMost common disagreements:")
            for line in self.confusion_summary[:10]:
                print(f"  {line}")


# --- Core classification ------------------------------------------------


def classify_issue_multi_run(
    issue: GroundTruthIssue,
    clients: list[tuple[str, LLMClient]],
    prompt: str,
    runs_per_client: int = 3,
    confidence_threshold: float = 0.6,
) -> IssueClassification:
    """Classify a single GT issue multiple times and take majority vote.

    Args:
        issue: The GT issue to classify.
        clients: List of (provider_name, client) pairs.
        prompt: The classification prompt.
        runs_per_client: Number of classification runs per client.
        confidence_threshold: Minimum agreement ratio to be considered confident.

    Returns:
        IssueClassification with majority vote and agreement stats.
    """
    predictions: list[str] = []

    for provider_name, client in clients:
        classify_fn = make_dimension_classify_fn(prompt, client)
        for run in range(runs_per_client):
            try:
                dim = classify_fn(issue.description, "")
                predictions.append(dim.value)
            except Exception as e:
                logger.warning(
                    "Classification failed for %s (provider=%s, run=%d): %s",
                    issue.issue_id, provider_name, run, e,
                )
                predictions.append("correctness")  # Fallback

    # Majority vote
    vote_counts = Counter(predictions)
    majority_dim_str, majority_count = vote_counts.most_common(1)[0]
    total_votes = len(predictions)
    agreement = majority_count / total_votes if total_votes > 0 else 0.0

    # Runner-up
    runner_up = None
    if len(vote_counts) > 1:
        runner_up = vote_counts.most_common(2)[1][0]

    return IssueClassification(
        issue_id=issue.issue_id,
        pr_id=issue.pr_id,
        text=issue.description[:200],
        predictions=predictions,
        majority_dimension=Dimension(majority_dim_str),
        agreement_ratio=agreement,
        confident=agreement >= confidence_threshold,
        runner_up=runner_up,
    )


def classify_dataset(
    prs: list[PullRequest],
    clients: list[tuple[str, LLMClient]],
    prompt: str,
    runs_per_client: int = 3,
    confidence_threshold: float = 0.6,
    log_interval: int = 25,
) -> tuple[list[PullRequest], ClassificationReport, list[IssueClassification]]:
    """Classify all GT issues in a dataset using multi-run consensus.

    Returns:
        (classified_prs, report, all_classifications)
    """
    all_classifications: list[IssueClassification] = []
    classified_prs: list[PullRequest] = []
    total_done = 0

    for pr in prs:
        new_gt: list[GroundTruthIssue] = []
        for gt in pr.ground_truth:
            classification = classify_issue_multi_run(
                gt, clients, prompt, runs_per_client, confidence_threshold,
            )
            all_classifications.append(classification)

            new_gt.append(GroundTruthIssue(
                issue_id=gt.issue_id,
                pr_id=gt.pr_id,
                dimension=classification.majority_dimension,
                severity=gt.severity,
                location=gt.location,
                description=gt.description,
                difficulty=gt.difficulty,
            ))
            total_done += 1

            if total_done % log_interval == 0:
                confident = sum(1 for c in all_classifications if c.confident)
                logger.info(
                    "Classified %d issues (%d confident, %d flagged)",
                    total_done, confident, total_done - confident,
                )

        classified_prs.append(PullRequest(
            pr_id=pr.pr_id,
            title=pr.title,
            language=pr.language,
            change_type=pr.change_type,
            diff=pr.diff,
            ground_truth=new_gt,
        ))

    # Build report
    dim_dist = Counter(c.majority_dimension.value for c in all_classifications)
    confident_count = sum(1 for c in all_classifications if c.confident)
    mean_agreement = (
        sum(c.agreement_ratio for c in all_classifications) / len(all_classifications)
        if all_classifications else 0.0
    )

    # Confusion: most common disagreement pairs
    disagreements: Counter = Counter()
    for c in all_classifications:
        if not c.confident and c.runner_up:
            pair = f"{c.majority_dimension.value} ↔ {c.runner_up}"
            disagreements[pair] += 1

    report = ClassificationReport(
        total_issues=len(all_classifications),
        confident_count=confident_count,
        flagged_count=len(all_classifications) - confident_count,
        dimension_distribution=dict(dim_dist),
        mean_agreement=mean_agreement,
        providers_used=[name for name, _ in clients],
        runs_per_provider=runs_per_client,
        confusion_summary=[
            f"{pair}: {count}" for pair, count in disagreements.most_common(10)
        ],
    )

    return classified_prs, report, all_classifications


# --- Spot-check generation -----------------------------------------------


def generate_spot_check(
    classifications: list[IssueClassification],
    n: int = 50,
    include_flagged_ratio: float = 0.3,
) -> list[dict]:
    """Generate a spot-check sample for human validation.

    Samples a mix of confident and flagged classifications. Over-samples
    flagged cases because those are where the classifier is most likely
    wrong.

    Returns a list of dicts ready to write as JSONL.
    """
    import random

    flagged = [c for c in classifications if not c.confident]
    confident = [c for c in classifications if c.confident]

    n_flagged = min(int(n * include_flagged_ratio), len(flagged))
    n_confident = min(n - n_flagged, len(confident))

    sample = random.sample(flagged, n_flagged) + random.sample(confident, n_confident)
    random.shuffle(sample)

    return [
        {
            "issue_id": c.issue_id,
            "text": c.text,
            "ai_dimension": c.majority_dimension.value,
            "agreement_ratio": round(c.agreement_ratio, 2),
            "runner_up": c.runner_up,
            "human_dimension": "",  # User fills this in
        }
        for c in sample
    ]


# --- Validation ----------------------------------------------------------


def validate_spot_check(
    classified_path: Path,
    human_labels_path: Path,
) -> dict:
    """Compare AI classifications against human spot-check labels.

    Returns agreement statistics including Cohen's kappa.
    """
    # Load AI labels
    ai_labels: dict[str, str] = {}
    with classified_path.open() as f:
        for line in f:
            data = json.loads(line.strip())
            for gt in data.get("ground_truth", []):
                ai_labels[gt["issue_id"]] = gt["dimension"]

    # Load human labels
    human_labels: dict[str, str] = {}
    with human_labels_path.open() as f:
        for line in f:
            data = json.loads(line.strip())
            if data.get("human_dimension"):
                human_labels[data["issue_id"]] = data["human_dimension"]

    # Compute agreement
    common_ids = set(ai_labels) & set(human_labels)
    if not common_ids:
        return {"error": "No overlapping issue IDs found"}

    agree = sum(1 for iid in common_ids if ai_labels[iid] == human_labels[iid])
    total = len(common_ids)
    accuracy = agree / total

    # Compute Cohen's kappa
    all_dims = list(set(list(ai_labels.values()) + list(human_labels.values())))
    n = total
    po = accuracy

    # Expected agreement by chance
    pe = 0.0
    for dim in all_dims:
        ai_rate = sum(1 for iid in common_ids if ai_labels[iid] == dim) / n
        human_rate = sum(1 for iid in common_ids if human_labels[iid] == dim) / n
        pe += ai_rate * human_rate

    kappa = (po - pe) / (1 - pe) if pe < 1.0 else 0.0

    # Per-dimension breakdown
    dim_results: dict[str, dict] = {}
    for dim in all_dims:
        dim_common = [iid for iid in common_ids if human_labels[iid] == dim]
        if dim_common:
            dim_agree = sum(1 for iid in dim_common if ai_labels[iid] == dim)
            dim_results[dim] = {
                "total": len(dim_common),
                "correct": dim_agree,
                "accuracy": dim_agree / len(dim_common),
            }

    # Confusion pairs
    confusions: Counter = Counter()
    for iid in common_ids:
        if ai_labels[iid] != human_labels[iid]:
            confusions[f"{human_labels[iid]}→{ai_labels[iid]}"] += 1

    return {
        "total_compared": total,
        "agreement": agree,
        "accuracy": accuracy,
        "kappa": kappa,
        "per_dimension": dim_results,
        "top_confusions": dict(confusions.most_common(10)),
    }


# --- I/O -----------------------------------------------------------------


def save_classifications(
    prs: list[PullRequest],
    path: Path,
) -> None:
    """Save classified PRs as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for pr in prs:
            f.write(pr.model_dump_json() + "\n")


def save_spot_check(samples: list[dict], path: Path) -> None:
    """Save spot-check samples as JSONL for human labelling."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for sample in samples:
            f.write(json.dumps(sample) + "\n")


def save_report(
    report: ClassificationReport,
    classifications: list[IssueClassification],
    path: Path,
) -> None:
    """Save full classification report as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "total_issues": report.total_issues,
        "confident_count": report.confident_count,
        "flagged_count": report.flagged_count,
        "mean_agreement": report.mean_agreement,
        "providers": report.providers_used,
        "runs_per_provider": report.runs_per_provider,
        "dimension_distribution": report.dimension_distribution,
        "confusion_summary": report.confusion_summary,
        "flagged_issues": [
            {
                "issue_id": c.issue_id,
                "text": c.text[:200],
                "majority": c.majority_dimension.value,
                "runner_up": c.runner_up,
                "agreement": round(c.agreement_ratio, 2),
                "predictions": c.predictions,
            }
            for c in classifications if not c.confident
        ],
    }, indent=2))


# --- Client factory ------------------------------------------------------


def build_clients(args: argparse.Namespace) -> list[tuple[str, LLMClient]]:
    """Build LLM clients from CLI args."""
    providers = [p.strip() for p in args.providers.split(",")]
    models = [m.strip() for m in args.models.split(",")]

    if len(models) == 1 and len(providers) > 1:
        models = models * len(providers)
    if len(models) != len(providers):
        raise ValueError(
            f"Number of models ({len(models)}) must match providers ({len(providers)})"
        )

    clients: list[tuple[str, LLMClient]] = []
    for provider, model in zip(providers, models):
        if provider == "claude-code":
            clients.append((f"claude-code/{model}", ClaudeCodeLLM(model=model)))
        elif provider == "anthropic":
            from anthropic import Anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")
            clients.append((f"anthropic/{model}", AnthropicLLM(Anthropic(api_key=api_key), model=model)))
        elif provider == "openai":
            from openai import OpenAI
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")
            clients.append((f"openai/{model}", OpenAILLM(OpenAI(api_key=api_key), model=model)))
        elif provider == "mock":
            clients.append(("mock", MockLLM()))
        else:
            raise ValueError(f"Unknown provider: {provider}")

    return clients


# --- CLI -----------------------------------------------------------------


def cmd_classify(args: argparse.Namespace) -> int:
    """Run multi-run consensus classification."""
    from pilot.run import load_dataset

    # Load dataset
    ds_args = argparse.Namespace(
        benchmark=args.benchmark,
        benchmark_path=args.benchmark_path,
        max_diff_chars=50_000,
        dataset=None,
    )
    prs, eval_name = load_dataset(ds_args)

    if args.max_prs:
        prs = prs[:args.max_prs]

    total_gt = sum(len(pr.ground_truth) for pr in prs)
    print(f"Loaded {len(prs)} PRs with {total_gt} GT issues from {eval_name}")

    # Build clients
    clients = build_clients(args)
    print(f"Using {len(clients)} provider(s): {[name for name, _ in clients]}")
    print(f"Runs per provider: {args.runs}")
    print(f"Total predictions per issue: {len(clients) * args.runs}")
    print(f"Total API calls: {total_gt * len(clients) * args.runs}")
    print()

    # Load prompt
    prompt = DIMENSION_CLASSIFIER_INITIAL
    if args.prompt_file:
        data = json.loads(Path(args.prompt_file).read_text())
        prompt = data.get("best_prompt", data) if isinstance(data, dict) else data

    # Classify
    classified_prs, report, all_classifications = classify_dataset(
        prs, clients, prompt,
        runs_per_client=args.runs,
        confidence_threshold=args.confidence,
    )

    # Save outputs
    output = Path(args.output)
    save_classifications(classified_prs, output)
    save_report(report, all_classifications, output.with_suffix(".report.json"))

    # Generate spot-check
    spot_check = generate_spot_check(all_classifications, n=args.spot_check_n)
    save_spot_check(spot_check, output.parent / f"spot-check-{args.spot_check_n}.jsonl")

    report.print_summary()
    print(f"\nClassified dataset saved to: {output}")
    print(f"Report saved to: {output.with_suffix('.report.json')}")
    print(f"Spot-check sample ({args.spot_check_n}) saved for human validation")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate AI classifications against human labels."""
    results = validate_spot_check(
        Path(args.classified),
        Path(args.human_labels),
    )

    if "error" in results:
        print(f"Error: {results['error']}")
        return 1

    print(f"\nValidation Results")
    print(f"{'='*50}")
    print(f"Compared: {results['total_compared']} issues")
    print(f"Agreement: {results['agreement']}/{results['total_compared']} ({results['accuracy']:.1%})")
    print(f"Cohen's kappa: {results['kappa']:.3f}")

    if results['kappa'] >= 0.70:
        print(f"\n✓ Kappa >= 0.70 — classifications are reliable")
    elif results['kappa'] >= 0.60:
        print(f"\n~ Kappa 0.60-0.70 — acceptable but could improve")
    else:
        print(f"\n✗ Kappa < 0.60 — classifications need improvement")

    if results.get("top_confusions"):
        print(f"\nTop confusions (human→AI):")
        for pair, count in results["top_confusions"].items():
            print(f"  {pair}: {count}")

    # Save results
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(results, indent=2))
        print(f"\nResults saved to: {args.output}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dimension classification pipeline with multi-run consensus"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- classify ---
    cls_parser = subparsers.add_parser("classify", help="Classify GT issues by dimension")
    cls_parser.add_argument("--benchmark", required=True,
                           choices=["ccrab", "swe-prbench", "swe-care", "greptile", "martian", "all"])
    cls_parser.add_argument("--benchmark-path", type=Path, default=None)
    cls_parser.add_argument("--providers", default="anthropic",
                           help="Comma-separated providers (anthropic, openai, claude-code, mock)")
    cls_parser.add_argument("--models", default="claude-opus-4-6",
                           help="Comma-separated models (one per provider, or one for all)")
    cls_parser.add_argument("--runs", type=int, default=3,
                           help="Runs per provider (default: 3)")
    cls_parser.add_argument("--confidence", type=float, default=0.6,
                           help="Min agreement ratio for confident classification (default: 0.6)")
    cls_parser.add_argument("--max-prs", type=int, default=None,
                           help="Limit number of PRs (for testing)")
    cls_parser.add_argument("--prompt-file", default=None,
                           help="Custom classifier prompt (JSON from autoresearch loop)")
    cls_parser.add_argument("--spot-check-n", type=int, default=50,
                           help="Number of spot-check samples to generate (default: 50)")
    cls_parser.add_argument("--output", required=True,
                           help="Output path for classified dataset JSONL")

    # --- validate ---
    val_parser = subparsers.add_parser("validate", help="Validate AI labels against human spot-check")
    val_parser.add_argument("--classified", required=True,
                           help="Path to classified dataset JSONL")
    val_parser.add_argument("--human-labels", required=True,
                           help="Path to human-labelled spot-check JSONL")
    val_parser.add_argument("--output", default=None,
                           help="Save validation results as JSON")

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.command == "classify":
        return cmd_classify(args)
    elif args.command == "validate":
        return cmd_validate(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
