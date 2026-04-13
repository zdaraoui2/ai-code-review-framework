"""Tests for the train/validation split that prevents overfitting.

The original bug: make_dimension_evaluate_fn() evaluated the refined prompt
on the same calibration set used for error analysis and refinement. No
train/validation split existed. The refinement loop could overfit to
calibration data.

The fix: 70/30 train/validation split. Error analysis and refinement
feedback use only the training partition. Accuracy scoring uses only the
validation partition. The refiner never sees validation items.

These tests verify the fix is in place and the overfitting gap is reduced.
"""

from __future__ import annotations

import random

from pilot.autoresearch import (
    DIMENSION_CLASSIFIER_INITIAL,
    DimensionLabel,
    make_dimension_evaluate_fn,
    run_loop,
)
from pilot.schemas import Dimension


# Use a fixed subset of dimensions for controlled testing.
DIMS = [
    Dimension.SECURITY,
    Dimension.CORRECTNESS,
    Dimension.CONCURRENCY,
    Dimension.ERROR_HANDLING,
    Dimension.PERFORMANCE,
]


def _make_unique_marker(prefix: str, idx: int) -> str:
    """Generate a unique marker string that will appear in the LLM user message."""
    return f"MARKER_{prefix}_{idx:04d}"


def _make_calibration_set(prefix: str, count: int, seed: int = 42) -> list[DimensionLabel]:
    """Build a synthetic calibration set with deterministic labels."""
    labels = []
    for idx in range(count):
        dim = DIMS[idx % len(DIMS)]
        marker = _make_unique_marker(prefix, idx)
        labels.append(DimensionLabel(
            issue_id=f"{prefix}-{idx}",
            text=f"{marker} review comment about {dim.value}",
            code_context=f"# {prefix} code context {idx}",
            human_dimension=dim,
        ))
    return labels


class MemorisingLLM:
    """A mock LLM that memorises answers for items mentioned in error analysis.

    On each "refinement" call, it scans the error analysis for markers it
    recognises and embeds the correct answers for those items into the prompt.
    This is realistic: a real refiner can only learn from items the error
    analysis exposes. With the train/validation split, the error analysis
    only contains training items, so the refiner can only memorise training
    markers — not validation markers.

    On classify calls, it looks for memorised rules in the prompt. For items
    without a matching rule, it returns a random dimension.
    """

    def __init__(
        self,
        calibration: list[DimensionLabel],
        prefix: str,
        memorise_per_iteration: int = 4,
        seed: int = 99,
    ):
        self._calibration_by_marker: dict[str, DimensionLabel] = {}
        self._marker_order: list[str] = []
        for idx, label in enumerate(calibration):
            marker = _make_unique_marker(prefix, idx)
            self._calibration_by_marker[marker] = label
            self._marker_order.append(marker)

        self._memorise_per_iteration = memorise_per_iteration
        self._rng = random.Random(seed)
        self._iteration = 0
        self._memorised_markers: set[str] = set()

    def complete(self, system: str, user: str) -> str:
        if "Current accuracy:" in user:
            return self._handle_refinement(system, user)
        else:
            return self._handle_classification(system, user)

    def _handle_refinement(self, system: str, user: str) -> str:
        """Simulate a refiner that memorises items visible in error analysis.

        Only markers that appear in the error analysis (the ``user`` message)
        can be memorised. With the train/validation split, validation markers
        never appear here.
        """
        self._iteration += 1

        # Find markers mentioned in the error analysis. Only these are
        # visible to the refiner — it cannot memorise what it cannot see.
        visible_markers = [
            marker for marker in self._marker_order
            if marker in user and marker not in self._memorised_markers
        ]
        to_add = visible_markers[:self._memorise_per_iteration]
        self._memorised_markers.update(to_add)

        hints = []
        for marker in sorted(self._memorised_markers):
            label = self._calibration_by_marker[marker]
            hints.append(
                f"RULE: when you see '{marker}' classify as '{label.human_dimension.value}'"
            )

        return (
            DIMENSION_CLASSIFIER_INITIAL
            + "\n\n# Learned rules (iteration "
            + str(self._iteration)
            + "):\n"
            + "\n".join(hints)
        )

    def _handle_classification(self, system: str, user: str) -> str:
        """Classify: use memorised hints if present in prompt, otherwise random."""
        for marker, label in self._calibration_by_marker.items():
            rule = f"RULE: when you see '{marker}' classify as '{label.human_dimension.value}'"
            if rule in system and marker in user:
                return label.human_dimension.value

        return self._rng.choice(DIMS).value


def _make_memorising_refine_fn(mock_llm: MemorisingLLM):
    """Create a refine function that delegates to the memorising LLM."""
    def refine(current_prompt: str, score: float, error_analysis: str) -> str:
        user_msg = (
            f"Current accuracy: {score:.1%}\n\n"
            f"Error analysis:\n{error_analysis}\n\n"
            f"Current prompt:\n---\n{current_prompt}\n---"
        )
        return mock_llm.complete("refine system", user_msg)

    return refine


def test_validation_split_exists():
    """Structural test: make_dimension_evaluate_fn splits the calibration set.

    The evaluate function should classify ALL items (training for error
    analysis, validation for scoring), but the split means the number of
    LLM calls equals the full calibration set size, split across two
    partitions.
    """
    calibration = _make_calibration_set("track", 20)

    classified_texts: list[str] = []

    class TrackingLLM:
        def complete(self, system: str, user: str) -> str:
            classified_texts.append(user)
            return "correctness"

    tracking_llm = TrackingLLM()
    evaluate_fn = make_dimension_evaluate_fn(calibration, tracking_llm)
    score, error_analysis = evaluate_fn("test prompt")

    # All 20 items are classified (14 training + 6 validation with default 0.3).
    assert len(classified_texts) == len(calibration), (
        f"Expected {len(calibration)} LLM calls, got {len(classified_texts)}"
    )

    # Reconstruct the split to verify error analysis only has training items.
    rng = random.Random(42)
    shuffled = list(calibration)
    rng.shuffle(shuffled)
    split_index = max(1, len(shuffled) - int(len(shuffled) * 0.3))
    validation_ids = {label.issue_id for label in shuffled[split_index:]}

    # Validation item IDs must NOT appear in the error analysis.
    for issue_id in validation_ids:
        assert issue_id not in error_analysis, (
            f"Validation item {issue_id} leaked into error analysis fed to refiner"
        )


def test_error_analysis_contains_only_training_items():
    """The error analysis fed to the refiner must only reference training
    items, not validation items. This prevents the information leak that
    enabled overfitting.
    """
    calibration = [
        DimensionLabel(f"GT{i}", f"item-{i} about security", f"ctx-{i}", Dimension.SECURITY)
        for i in range(20)
    ]

    class AlwaysWrongLLM:
        def complete(self, system: str, user: str) -> str:
            return "correctness"  # Wrong — all items are security.

    wrong_llm = AlwaysWrongLLM()
    evaluate_fn = make_dimension_evaluate_fn(calibration, wrong_llm)
    _, error_analysis = evaluate_fn("test prompt")

    # Reconstruct the split.
    rng = random.Random(42)
    shuffled = list(calibration)
    rng.shuffle(shuffled)
    split_index = max(1, len(shuffled) - int(len(shuffled) * 0.3))
    training_ids = {label.issue_id for label in shuffled[:split_index]}
    validation_ids = {label.issue_id for label in shuffled[split_index:]}

    # Training items should appear in error analysis (they were misclassified).
    for issue_id in training_ids:
        assert issue_id in error_analysis, (
            f"Training item {issue_id} missing from error analysis"
        )

    # Validation items must NOT appear.
    for issue_id in validation_ids:
        assert issue_id not in error_analysis, (
            f"Validation item {issue_id} leaked into error analysis"
        )


def test_memorising_llm_cannot_inflate_validation_score():
    """With the train/validation split, a memorising LLM that learns
    training-specific rules should NOT achieve high validation accuracy.

    The refiner only sees error analysis from training items. It embeds
    rules keyed on training markers. The validation items have different
    markers, so the memorised rules do not help.
    """
    calibration = _make_calibration_set("cal", 40, seed=42)

    mock_llm = MemorisingLLM(
        calibration, prefix="cal", memorise_per_iteration=8, seed=99,
    )

    evaluate_fn = make_dimension_evaluate_fn(calibration, mock_llm)
    refine_fn = _make_memorising_refine_fn(mock_llm)

    result = run_loop(
        initial_prompt=DIMENSION_CLASSIFIER_INITIAL,
        evaluate_fn=evaluate_fn,
        refine_fn=refine_fn,
        target_score=0.95,
        max_iterations=6,
        patience=20,
    )

    # With the split, the reported score (validation accuracy) should be
    # much lower than what the old unfixed loop would report, because
    # memorised training rules do not generalise to validation items.
    # Random baseline for 5 dimensions is ~20%. Memorisation of training
    # items should not meaningfully boost validation accuracy.
    assert result.best_score < 0.70, (
        f"Validation accuracy {result.best_score:.0%} is suspiciously high — "
        f"memorisation of training data should not help on validation items"
    )
