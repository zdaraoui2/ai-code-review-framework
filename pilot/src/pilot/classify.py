"""CLI for the dimension classifier loop and GT classification.

Usage:
    # Run the AutoResearch loop to find the best classifier prompt
    python -m pilot.classify loop \\
        --calibration calibration/dimensions.jsonl \\
        --target 0.85 \\
        --model claude-sonnet-4-6

    # Apply a winning prompt to a full dataset
    python -m pilot.classify apply \\
        --prompt-file results/classifier-loop.json \\
        --benchmark ccrab \\
        --benchmark-path /path/to/ccrab/preprocess_dataset.jsonl \\
        --output classified/ccrab.jsonl

    # Dry run (test loop structure with mock LLM)
    python -m pilot.classify loop \\
        --calibration calibration/dimensions.jsonl \\
        --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from pilot.autoresearch import (
    DIMENSION_CLASSIFIER_INITIAL,
    AnthropicLLM,
    ClaudeCodeLLM,
    LoopResult,
    MockLLM,
    OpenAILLM,
    classify_ground_truth,
    load_dimension_calibration,
    make_dimension_evaluate_fn,
    make_refine_fn,
    run_loop,
    save_classified_dataset,
)


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def cmd_loop(args: argparse.Namespace) -> int:
    """Run the AutoResearch dimension classifier loop."""
    calibration = load_dimension_calibration(Path(args.calibration))
    print(f"Loaded {len(calibration)} calibration examples")

    # Build LLM client
    if args.dry_run:
        client = MockLLM()
        print("Dry run mode — using mock LLM (no API calls)")
    elif args.provider == "claude-code":
        client = ClaudeCodeLLM(model=args.model)
        print(f"Using claude CLI (OAuth auth, model: {args.model})")
    elif args.provider == "anthropic":
        from anthropic import Anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("Error: ANTHROPIC_API_KEY not set", file=sys.stderr)
            return 1
        client = AnthropicLLM(Anthropic(api_key=api_key), model=args.model)
    elif args.provider == "openai":
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("Error: OPENAI_API_KEY not set", file=sys.stderr)
            return 1
        client = OpenAILLM(OpenAI(api_key=api_key), model=args.model)
    else:
        print(f"Unknown provider: {args.provider}", file=sys.stderr)
        return 1

    evaluate_fn = make_dimension_evaluate_fn(calibration, client)
    refine_fn = make_refine_fn(client)

    initial_prompt = DIMENSION_CLASSIFIER_INITIAL
    if args.initial_prompt:
        initial_prompt = Path(args.initial_prompt).read_text()

    result = run_loop(
        initial_prompt=initial_prompt,
        evaluate_fn=evaluate_fn,
        refine_fn=refine_fn,
        target_score=args.target,
        max_iterations=args.max_iterations,
        patience=args.patience,
    )

    output_path = Path(args.output)
    result.save(output_path)
    print(f"\nLoop complete.")
    print(f"  Best score: {result.best_score:.3f}")
    print(f"  Iterations: {result.iterations_run}")
    print(f"  Target reached: {result.target_reached}")
    print(f"  Saved to: {output_path}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Apply a winning classifier prompt to a full dataset."""
    # Load the winning prompt
    loop_data = json.loads(Path(args.prompt_file).read_text())
    prompt = loop_data["best_prompt"]
    print(f"Loaded prompt (score: {loop_data['best_score']:.3f})")

    # Build LLM client
    if args.provider == "claude-code":
        client = ClaudeCodeLLM(model=args.model)
    elif args.provider == "anthropic":
        from anthropic import Anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("Error: ANTHROPIC_API_KEY not set", file=sys.stderr)
            return 1
        client = AnthropicLLM(Anthropic(api_key=api_key), model=args.model)
    elif args.provider == "openai":
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("Error: OPENAI_API_KEY not set", file=sys.stderr)
            return 1
        client = OpenAILLM(OpenAI(api_key=api_key), model=args.model)
    else:
        print(f"Unknown provider: {args.provider}", file=sys.stderr)
        return 1

    # Load dataset
    from pilot.run import load_dataset
    prs_args = argparse.Namespace(
        benchmark=args.benchmark,
        benchmark_path=args.benchmark_path,
        max_diff_chars=50_000,
        dataset=None,
    )
    prs, eval_name = load_dataset(prs_args)
    print(f"Loaded {len(prs)} PRs from {eval_name}")

    # Classify
    classified = classify_ground_truth(prs, prompt, client)

    # Save
    output = Path(args.output)
    save_classified_dataset(classified, output)

    # Stats
    from collections import Counter
    dims = Counter()
    for pr in classified:
        for gt in pr.ground_truth:
            dims[gt.dimension.value] += 1
    print(f"\nDimension distribution:")
    for dim, count in sorted(dims.items(), key=lambda x: -x[1]):
        print(f"  {dim}: {count}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dimension classifier: AutoResearch loop and dataset classification"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- loop subcommand ---
    loop_parser = subparsers.add_parser("loop", help="Run the classifier optimisation loop")
    loop_parser.add_argument(
        "--calibration", required=True,
        help="Path to the hand-labelled calibration JSONL file",
    )
    loop_parser.add_argument(
        "--target", type=float, default=0.85,
        help="Target accuracy to reach (default: 0.85)",
    )
    loop_parser.add_argument(
        "--max-iterations", type=int, default=50,
        help="Maximum iterations (default: 50)",
    )
    loop_parser.add_argument(
        "--patience", type=int, default=10,
        help="Stop after N iterations without improvement (default: 10)",
    )
    loop_parser.add_argument(
        "--provider", choices=["claude-code", "anthropic", "openai"], default="claude-code",
        help="LLM provider. claude-code uses local CLI with OAuth (no API key needed).",
    )
    loop_parser.add_argument(
        "--model", default="claude-sonnet-4-6",
        help="Model to use for classification and refinement",
    )
    loop_parser.add_argument(
        "--initial-prompt", default=None,
        help="Path to a custom initial prompt (default: built-in)",
    )
    loop_parser.add_argument(
        "--output", default="results/classifier-loop.json",
        help="Path to save the loop result",
    )
    loop_parser.add_argument(
        "--dry-run", action="store_true",
        help="Test loop structure with mock LLM (no API calls)",
    )

    # --- apply subcommand ---
    apply_parser = subparsers.add_parser("apply", help="Apply a winning prompt to a dataset")
    apply_parser.add_argument(
        "--prompt-file", required=True,
        help="Path to the classifier-loop.json with the winning prompt",
    )
    apply_parser.add_argument(
        "--benchmark", required=True,
        choices=["ccrab", "swe-prbench", "swe-care", "greptile", "martian", "all"],
        help="Benchmark to classify",
    )
    apply_parser.add_argument(
        "--benchmark-path", type=Path, default=None,
        help="Path to the benchmark data",
    )
    apply_parser.add_argument(
        "--provider", choices=["claude-code", "anthropic", "openai"], default="claude-code",
        help="LLM provider. claude-code uses local CLI with OAuth (no API key needed).",
    )
    apply_parser.add_argument(
        "--model", default="claude-sonnet-4-6",
        help="Model to use for classification",
    )
    apply_parser.add_argument(
        "--output", required=True,
        help="Path to save the classified dataset JSONL",
    )

    args = parser.parse_args(argv)

    if args.command == "loop":
        return cmd_loop(args)
    elif args.command == "apply":
        return cmd_apply(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
