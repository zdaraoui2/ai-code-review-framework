"""AutoResearch-style iteration loop for prompt optimisation.

Inspired by Karpathy's autoresearch pattern: define a prompt to iterate
on, an evaluation metric, and a target threshold. An LLM refines the
prompt based on error analysis, the new prompt is evaluated against a
calibration set, and changes are kept or discarded based on performance.

Primary use case: the dimension classifier. The framework's 15 dimensions
have subtle boundaries (Security vs Data Validation, Correctness vs Error
Handling) that benefit from iterative refinement of the classification
prompt and few-shot examples.

Secondary use case: judge prompt calibration if the S8.5 prompts don't
pass on the first try.

Usage:
    # With real API
    python -m pilot.classify --calibration calibration/dimensions.jsonl \\
        --dataset ccrab --benchmark-path /path/to/ccrab/preprocess_dataset.jsonl \\
        --target 0.85 --model claude-sonnet-4-6

    # Dry run (test the loop with mock refinement)
    python -m pilot.classify --calibration calibration/dimensions.jsonl \\
        --dry-run
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from pilot.schemas import (
    Dimension,
    GroundTruthIssue,
    Location,
    PullRequest,
    Severity,
)

logger = logging.getLogger(__name__)


# --- Protocols -----------------------------------------------------------


class LLMClient(Protocol):
    """Minimal interface for an LLM client used by the refinement engine."""

    def complete(self, system: str, user: str) -> str:
        """Send a system + user prompt and return the text response."""
        ...


# --- Result types --------------------------------------------------------


@dataclass
class IterationResult:
    """Result of a single iteration."""

    iteration: int
    score: float
    improved: bool
    error_analysis: str = ""
    prompt_hash: str = ""


@dataclass
class LoopResult:
    """Result of a complete iteration loop."""

    best_prompt: str
    best_score: float
    iterations_run: int
    target_reached: bool
    history: list[IterationResult] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "best_score": self.best_score,
            "iterations_run": self.iterations_run,
            "target_reached": self.target_reached,
            "best_prompt": self.best_prompt,
            "history": [
                {
                    "iteration": r.iteration,
                    "score": r.score,
                    "improved": r.improved,
                    "error_analysis": r.error_analysis[:500],
                }
                for r in self.history
            ],
        }, indent=2))


# --- Calibration data ----------------------------------------------------


@dataclass(frozen=True)
class DimensionLabel:
    """A single human-labelled dimension classification."""

    issue_id: str
    text: str
    code_context: str
    human_dimension: Dimension


@dataclass(frozen=True)
class MatchLabel:
    """A single human-labelled match decision."""

    finding_id: str
    gt_issue_id: str
    finding_text: str
    gt_text: str
    code_context: str
    human_label: str  # "match", "no_match", "ambiguous"


def load_dimension_calibration(path: Path) -> list[DimensionLabel]:
    """Load a hand-labelled dimension calibration set.

    Expected JSONL format:
    {"issue_id": "...", "text": "review comment", "code_context": "...",
     "human_dimension": "security"}
    """
    labels: list[DimensionLabel] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            labels.append(DimensionLabel(
                issue_id=data["issue_id"],
                text=data["text"],
                code_context=data.get("code_context", ""),
                human_dimension=Dimension(data["human_dimension"]),
            ))
    return labels


def load_match_calibration(path: Path) -> list[MatchLabel]:
    """Load a hand-labelled judge match calibration set."""
    labels: list[MatchLabel] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            labels.append(MatchLabel(
                finding_id=data["finding_id"],
                gt_issue_id=data["gt_issue_id"],
                finding_text=data["finding_text"],
                gt_text=data["gt_text"],
                code_context=data.get("code_context", ""),
                human_label=data["human_label"],
            ))
    return labels


# --- LLM client wrappers ------------------------------------------------


class ClaudeCodeLLM:
    """Uses the claude CLI in print mode — authenticates via OAuth token.

    No API key needed. Uses whatever auth the local claude CLI has
    (typically OAuth from `claude login`). This is the simplest way to
    use Claude from code when you have Claude Code installed but no
    separate API key.
    """

    def __init__(self, model: str = "claude-opus-4-6"):
        self._model = model

    def complete(self, system: str, user: str) -> str:
        import subprocess
        combined = f"{system}\n\n{user}"
        result = subprocess.run(
            ["claude", "-p", "--model", self._model],
            input=combined,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {result.stderr[:500]}")
        return result.stdout.strip()


class AnthropicLLM:
    """Wraps the Anthropic SDK to satisfy the LLMClient protocol."""

    def __init__(self, client: Any, model: str = "claude-sonnet-4-6", max_tokens: int = 4096):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=0.7,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text


class OpenAILLM:
    """Wraps the OpenAI SDK to satisfy the LLMClient protocol."""

    def __init__(self, client: Any, model: str = "gpt-4o", max_tokens: int = 4096):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=0.7,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content


class MockLLM:
    """Returns the input prompt unchanged. For testing the loop structure."""

    def complete(self, system: str, user: str) -> str:
        return user


# --- Dimension classifier ------------------------------------------------


DIMENSION_CLASSIFIER_INITIAL = """You are a code review dimension classifier. Given a review comment
and its code context, classify it into exactly ONE of these 15 dimensions.

TIER 1 (high production-incident correlation):
- correctness: Logic errors, off-by-one, null handling, wrong return values, type errors
- concurrency: Race conditions, deadlocks, atomicity violations, thread safety
- error_handling: Missing error checks, swallowed exceptions, incorrect propagation
- security: Input validation with security consequence, auth, crypto, info disclosure
- resource_management: Memory leaks, handle leaks, unbounded growth

TIER 2 (moderate correlation, high long-term impact):
- configuration: Config errors, environment assumptions, deployment settings
- api_design: Breaking changes, inconsistent interfaces, missing boundary validation
- test_quality: Missing test coverage, weak assertions, tests that always pass
- architecture: Separation of concerns, dependency direction, abstraction mismatches
- data_validation: Missing checks at trust boundaries WITHOUT security consequence

TIER 3 (code health):
- maintainability: Duplication, dead code, complex logic, structural issues
- readability: Naming, expression clarity within a function
- documentation: Missing or misleading docs, comments
- style: Convention violations, formatting (should be automated)
- performance: Algorithmic complexity, wasteful patterns, N+1 queries

OVERLAP RULES:
- If missing validation enables a known attack (injection, traversal): security, NOT data_validation
- If bug manifests only under concurrent execution: concurrency, NOT correctness
- If issue is purely about naming/clarity: readability, NOT maintainability
- If issue is about code structure (duplication, dead code): maintainability, NOT readability

Respond with ONLY the dimension name (e.g., "security"). No explanation."""


def make_dimension_classify_fn(
    prompt: str,
    client: LLMClient,
) -> Callable[[str, str], Dimension]:
    """Create a dimension classifier function from a prompt and LLM client.

    Returns a callable that takes (review_text, code_context) and returns
    a Dimension enum value.
    """
    def classify(text: str, code_context: str) -> Dimension:
        user_msg = f"Review comment:\n{text}\n\nCode context:\n{code_context}"
        response = client.complete(prompt, user_msg).strip().lower()
        # Handle potential wrapping in quotes or extra whitespace
        response = response.strip('"').strip("'").strip()
        try:
            return Dimension(response)
        except ValueError:
            # Try matching partial dimension names
            for dim in Dimension:
                if dim.value in response or response in dim.value:
                    return dim
            logger.warning("Could not parse dimension '%s', defaulting to correctness", response)
            return Dimension.CORRECTNESS

    return classify


def make_dimension_evaluate_fn(
    calibration: list[DimensionLabel],
    client: LLMClient,
) -> Callable[[str], tuple[float, str]]:
    """Create an evaluation function for the dimension classifier loop.

    Returns a callable with signature (prompt_str) -> (accuracy, error_analysis)
    that the run_loop function expects.
    """
    def evaluate(prompt: str) -> tuple[float, str]:
        classify_fn = make_dimension_classify_fn(prompt, client)
        return evaluate_dimension_classifier(classify_fn, calibration)

    return evaluate


def evaluate_dimension_classifier(
    classify_fn: Callable[[str, str], Dimension],
    calibration: list[DimensionLabel],
) -> tuple[float, str]:
    """Evaluate a dimension classifier against a calibration set.

    Returns:
        (accuracy, error_analysis_string)
    """
    correct = 0
    errors: list[str] = []
    confusion: dict[str, dict[str, int]] = {}

    for label in calibration:
        predicted = classify_fn(label.text, label.code_context)
        if predicted == label.human_dimension:
            correct += 1
        else:
            errors.append(
                f"  {label.issue_id}: predicted={predicted.value}, "
                f"actual={label.human_dimension.value}, "
                f"text={label.text[:80]}..."
            )
            # Track confusion pairs
            key = f"{label.human_dimension.value}→{predicted.value}"
            confusion[key] = confusion.get(key, 0) + 1

    accuracy = correct / len(calibration) if calibration else 0.0

    # Build error summary with confusion analysis
    confused_pairs = sorted(confusion.items(), key=lambda x: -x[1])
    confusion_summary = "\n".join(
        f"  {pair}: {count} times" for pair, count in confused_pairs[:10]
    )

    error_summary = (
        f"{correct}/{len(calibration)} correct ({accuracy:.1%})\n"
        f"\nMost confused pairs:\n{confusion_summary}\n"
        f"\nSample errors:\n" + "\n".join(errors[:15])
    )
    return accuracy, error_summary


def evaluate_judge_matcher(
    match_fn: Callable[[str, str, str], str],
    calibration: list[MatchLabel],
) -> tuple[float, str]:
    """Evaluate a judge matcher against a calibration set.

    Computes Cohen's kappa, not raw agreement, because the framework's
    target is kappa >= 0.70 and raw agreement can be misleading with
    unbalanced classes.

    Returns:
        (kappa, error_analysis_string)
    """
    # Build contingency counts
    # Categories: match, no_match (skip ambiguous)
    non_ambiguous = [l for l in calibration if l.human_label != "ambiguous"]
    if not non_ambiguous:
        return 0.0, "No non-ambiguous labels to evaluate"

    tp = fp = fn = tn = 0
    errors: list[str] = []

    for label in non_ambiguous:
        predicted = match_fn(label.finding_text, label.gt_text, label.code_context)
        human = label.human_label

        if human == "match" and predicted == "match":
            tp += 1
        elif human == "match" and predicted == "no_match":
            fn += 1
            errors.append(f"  MISS: {label.finding_id}↔{label.gt_issue_id}")
        elif human == "no_match" and predicted == "match":
            fp += 1
            errors.append(f"  FALSE: {label.finding_id}↔{label.gt_issue_id}")
        elif human == "no_match" and predicted == "no_match":
            tn += 1

    n = tp + fp + fn + tn
    if n == 0:
        return 0.0, "No predictions to evaluate"

    # Cohen's kappa
    po = (tp + tn) / n  # observed agreement
    pe_match = ((tp + fp) / n) * ((tp + fn) / n)
    pe_nomatch = ((fn + tn) / n) * ((fp + tn) / n)
    pe = pe_match + pe_nomatch  # expected agreement by chance

    kappa = (po - pe) / (1 - pe) if pe < 1.0 else 0.0

    error_summary = (
        f"Kappa: {kappa:.3f} (observed agreement: {po:.3f}, chance: {pe:.3f})\n"
        f"TP={tp}, FP={fp}, FN={fn}, TN={tn}\n"
        f"\nErrors:\n" + "\n".join(errors[:20])
    )
    return kappa, error_summary


# --- The refinement engine (the "brain") ---------------------------------


REFINE_SYSTEM = """You are a prompt engineer. Your job is to improve a classification prompt
based on the errors it made.

You will receive:
1. The current classification prompt
2. Its accuracy score
3. An error analysis showing which classifications were wrong and which
   dimension pairs are most commonly confused

Your task: return an IMPROVED version of the classification prompt. Changes
you can make:
- Sharpen dimension definitions to reduce confusion between commonly
  confused pairs
- Add or modify the overlap resolution rules
- Add brief examples for ambiguous cases
- Restructure the prompt for clarity
- Adjust the instruction framing

Rules:
- Return ONLY the new prompt text, nothing else
- Keep the same output format instruction (respond with dimension name only)
- Do not remove any of the 15 dimensions
- Focus improvements on the most confused pairs first
- Keep the prompt under 2000 words"""


def make_refine_fn(client: LLMClient) -> Callable[[str, float, str], str]:
    """Create a refinement function that uses an LLM to improve prompts.

    Returns a callable with signature (current_prompt, score, errors) -> new_prompt.
    """
    def refine(current_prompt: str, score: float, error_analysis: str) -> str:
        user_msg = (
            f"Current accuracy: {score:.1%}\n\n"
            f"Error analysis:\n{error_analysis}\n\n"
            f"Current prompt:\n---\n{current_prompt}\n---\n\n"
            f"Return an improved prompt that reduces the errors above. "
            f"Focus on the most confused dimension pairs first."
        )
        response = client.complete(REFINE_SYSTEM, user_msg)
        # Strip any markdown wrapping the response might have
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            response = "\n".join(lines).strip()
        return response

    return refine


# --- Apply classifier to full dataset ------------------------------------


def classify_ground_truth(
    prs: list[PullRequest],
    prompt: str,
    client: LLMClient,
    batch_log_interval: int = 50,
) -> list[PullRequest]:
    """Apply a dimension classifier prompt to all GT issues in a dataset.

    Returns new PullRequest objects with updated dimension labels on their
    ground truth issues. The original objects are not modified.
    """
    classify_fn = make_dimension_classify_fn(prompt, client)
    classified_prs: list[PullRequest] = []
    total_classified = 0

    for pr in prs:
        new_gt: list[GroundTruthIssue] = []
        for gt in pr.ground_truth:
            dimension = classify_fn(gt.description, "")
            new_gt.append(GroundTruthIssue(
                issue_id=gt.issue_id,
                pr_id=gt.pr_id,
                dimension=dimension,
                severity=gt.severity,
                location=gt.location,
                description=gt.description,
                difficulty=gt.difficulty,
            ))
            total_classified += 1

        classified_prs.append(PullRequest(
            pr_id=pr.pr_id,
            title=pr.title,
            language=pr.language,
            change_type=pr.change_type,
            diff=pr.diff,
            ground_truth=new_gt,
        ))

        if total_classified % batch_log_interval == 0:
            logger.info("Classified %d GT issues so far...", total_classified)

    logger.info("Classification complete: %d GT issues across %d PRs",
                total_classified, len(classified_prs))
    return classified_prs


def save_classified_dataset(prs: list[PullRequest], path: Path) -> None:
    """Save classified PRs as JSONL for reuse without re-running the classifier."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for pr in prs:
            f.write(pr.model_dump_json() + "\n")
    logger.info("Saved classified dataset to %s (%d PRs)", path, len(prs))


# --- The iteration loop --------------------------------------------------


def run_loop(
    initial_prompt: str,
    evaluate_fn: Callable[[str], tuple[float, str]],
    refine_fn: Callable[[str, float, str], str],
    target_score: float,
    max_iterations: int = 50,
    patience: int = 10,
) -> LoopResult:
    """Run an AutoResearch-style iteration loop.

    Args:
        initial_prompt: The starting prompt to iterate on.
        evaluate_fn: Takes a prompt string, returns (score, error_analysis).
        refine_fn: Takes (current_prompt, score, error_analysis), returns
            a new prompt variant.
        target_score: Stop when this score is reached.
        max_iterations: Maximum iterations before stopping.
        patience: Stop after this many iterations without improvement.

    Returns:
        LoopResult with the best prompt and iteration history.
    """
    best_prompt = initial_prompt
    best_score, best_errors = evaluate_fn(initial_prompt)

    history: list[IterationResult] = [
        IterationResult(
            iteration=0,
            score=best_score,
            improved=True,
            error_analysis=best_errors[:500],
            prompt_hash=str(hash(initial_prompt))[-8:],
        )
    ]

    logger.info(
        "AutoResearch loop starting. Initial score: %.3f, target: %.3f",
        best_score, target_score,
    )

    if best_score >= target_score:
        logger.info("Target reached on initial prompt. No iteration needed.")
        return LoopResult(
            best_prompt=best_prompt,
            best_score=best_score,
            iterations_run=0,
            target_reached=True,
            history=history,
        )

    no_improvement_count = 0

    for i in range(1, max_iterations + 1):
        new_prompt = refine_fn(best_prompt, best_score, best_errors)
        new_score, new_errors = evaluate_fn(new_prompt)

        improved = new_score > best_score
        history.append(IterationResult(
            iteration=i,
            score=new_score,
            improved=improved,
            error_analysis=new_errors[:500],
            prompt_hash=str(hash(new_prompt))[-8:],
        ))

        if improved:
            logger.info("Iteration %d: %.3f → %.3f ✓", i, best_score, new_score)
            best_prompt = new_prompt
            best_score = new_score
            best_errors = new_errors
            no_improvement_count = 0
        else:
            logger.info("Iteration %d: %.3f (best: %.3f) ✗", i, new_score, best_score)
            no_improvement_count += 1

        if best_score >= target_score:
            logger.info("Target %.3f reached at iteration %d.", target_score, i)
            return LoopResult(
                best_prompt=best_prompt,
                best_score=best_score,
                iterations_run=i,
                target_reached=True,
                history=history,
            )

        if no_improvement_count >= patience:
            logger.info("Patience exhausted after %d iterations without improvement.", patience)
            break

    return LoopResult(
        best_prompt=best_prompt,
        best_score=best_score,
        iterations_run=len(history) - 1,
        target_reached=False,
        history=history,
    )
