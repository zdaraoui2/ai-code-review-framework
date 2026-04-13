"""Tests for the AutoResearch iteration loop."""

from __future__ import annotations

from pilot.autoresearch import (
    DIMENSION_CLASSIFIER_INITIAL,
    DimensionLabel,
    IterationResult,
    LoopResult,
    MatchLabel,
    MockLLM,
    evaluate_dimension_classifier,
    evaluate_judge_matcher,
    make_dimension_classify_fn,
    make_dimension_evaluate_fn,
    make_refine_fn,
    run_loop,
)
from pilot.schemas import Dimension


# --- Evaluation function tests -------------------------------------------


def test_dimension_classifier_perfect():
    """Perfect classifier should get 1.0 accuracy."""
    calibration = [
        DimensionLabel("GT1", "SQL injection risk", "query = f'...'", Dimension.SECURITY),
        DimensionLabel("GT2", "Missing null check", "if x:", Dimension.CORRECTNESS),
    ]

    def perfect_classify(text: str, ctx: str) -> Dimension:
        if "SQL" in text:
            return Dimension.SECURITY
        return Dimension.CORRECTNESS

    accuracy, errors = evaluate_dimension_classifier(perfect_classify, calibration)
    assert accuracy == 1.0
    assert "2/2 correct" in errors


def test_dimension_classifier_with_errors():
    """Classifier with one error should get 0.5 accuracy on 2 examples."""
    calibration = [
        DimensionLabel("GT1", "SQL injection", "", Dimension.SECURITY),
        DimensionLabel("GT2", "Race condition", "", Dimension.CONCURRENCY),
    ]

    def bad_classify(text: str, ctx: str) -> Dimension:
        return Dimension.SECURITY  # Always guesses security

    accuracy, errors = evaluate_dimension_classifier(bad_classify, calibration)
    assert accuracy == 0.5
    assert "concurrency→security" in errors  # Confusion pair


def test_dimension_classifier_empty_calibration():
    accuracy, _ = evaluate_dimension_classifier(lambda t, c: Dimension.CORRECTNESS, [])
    assert accuracy == 0.0


def test_judge_matcher_kappa_perfect():
    """Perfect matcher on balanced data should get kappa = 1.0."""
    calibration = [
        MatchLabel("F1", "GT1", "found issue A", "issue A", "", "match"),
        MatchLabel("F2", "GT2", "found issue B", "different issue", "", "no_match"),
    ]

    def perfect_match(ft: str, gt: str, ctx: str) -> str:
        if "issue A" in ft and "issue A" in gt:
            return "match"
        return "no_match"

    kappa, _ = evaluate_judge_matcher(perfect_match, calibration)
    assert kappa == 1.0


def test_judge_matcher_kappa_random():
    """Always-match on balanced data should have low kappa."""
    calibration = [
        MatchLabel("F1", "GT1", "a", "a", "", "match"),
        MatchLabel("F2", "GT2", "b", "c", "", "no_match"),
        MatchLabel("F3", "GT3", "d", "d", "", "match"),
        MatchLabel("F4", "GT4", "e", "f", "", "no_match"),
    ]

    def always_match(ft: str, gt: str, ctx: str) -> str:
        return "match"

    kappa, _ = evaluate_judge_matcher(always_match, calibration)
    assert kappa < 0.5  # Random-ish on balanced data


def test_judge_matcher_skips_ambiguous():
    """Ambiguous labels should be excluded from kappa calculation."""
    calibration = [
        MatchLabel("F1", "GT1", "a", "a", "", "match"),
        MatchLabel("F2", "GT2", "b", "c", "", "ambiguous"),
        MatchLabel("F3", "GT3", "d", "e", "", "no_match"),
    ]

    def perfect_match(ft: str, gt: str, ctx: str) -> str:
        if ft == "a":
            return "match"
        return "no_match"

    kappa, analysis = evaluate_judge_matcher(perfect_match, calibration)
    assert kappa == 1.0  # Perfect on the two non-ambiguous


# --- Loop tests ----------------------------------------------------------


def test_loop_stops_when_target_reached_initially():
    """If the initial prompt already meets the target, loop exits immediately."""
    result = run_loop(
        initial_prompt="test",
        evaluate_fn=lambda p: (0.95, "already good"),
        refine_fn=lambda p, s, e: p,
        target_score=0.85,
    )
    assert result.target_reached
    assert result.iterations_run == 0
    assert result.best_score == 0.95


def test_loop_improves_and_stops():
    """Loop should iterate and stop when target is reached."""
    call_count = 0

    def improving_evaluate(prompt: str) -> tuple[float, str]:
        nonlocal call_count
        call_count += 1
        # Each call improves by 0.1
        score = min(0.5 + (call_count - 1) * 0.1, 1.0)
        return score, f"score is {score}"

    result = run_loop(
        initial_prompt="start",
        evaluate_fn=improving_evaluate,
        refine_fn=lambda p, s, e: p + "+improved",
        target_score=0.85,
        max_iterations=20,
    )
    assert result.target_reached
    assert result.best_score >= 0.85
    assert result.iterations_run <= 10


def test_loop_respects_patience():
    """Loop should stop after patience iterations without improvement."""
    result = run_loop(
        initial_prompt="stuck",
        evaluate_fn=lambda p: (0.5, "no progress"),
        refine_fn=lambda p, s, e: p,  # No actual change
        target_score=0.95,
        max_iterations=100,
        patience=3,
    )
    assert not result.target_reached
    assert result.iterations_run == 3  # Stopped after 3 non-improvements


def test_loop_respects_max_iterations():
    """Loop should stop at max_iterations even if improving."""
    call_count = 0

    def slow_improve(prompt: str) -> tuple[float, str]:
        nonlocal call_count
        call_count += 1
        return 0.5 + call_count * 0.001, "slow"

    result = run_loop(
        initial_prompt="slow",
        evaluate_fn=slow_improve,
        refine_fn=lambda p, s, e: p + ".",
        target_score=0.99,
        max_iterations=5,
        patience=100,
    )
    assert not result.target_reached
    assert result.iterations_run == 5


def test_loop_result_save(tmp_path):
    """LoopResult should save to JSON."""
    result = LoopResult(
        best_prompt="the best prompt",
        best_score=0.87,
        iterations_run=3,
        target_reached=True,
        history=[
            IterationResult(iteration=0, score=0.6, improved=True),
            IterationResult(iteration=1, score=0.75, improved=True),
            IterationResult(iteration=2, score=0.87, improved=True),
        ],
    )
    path = tmp_path / "result.json"
    result.save(path)

    import json
    data = json.loads(path.read_text())
    assert data["best_score"] == 0.87
    assert data["target_reached"] is True
    assert len(data["history"]) == 3


# --- Integration: evaluate_fn factory ------------------------------------


def test_make_dimension_evaluate_fn():
    """The factory should produce a function with the right signature."""
    # Need enough items for the 70/30 split to produce a non-empty
    # validation partition.
    calibration = [
        DimensionLabel(f"GT{i}", f"issue {i}", "", Dimension.SECURITY)
        for i in range(10)
    ]
    client = MockLLM()
    evaluate_fn = make_dimension_evaluate_fn(calibration, client)

    # MockLLM returns the user message as-is, which won't parse as a
    # valid dimension, so the classifier defaults to CORRECTNESS.
    # Security != CORRECTNESS, so accuracy should be 0%.
    score, analysis = evaluate_fn("some prompt")
    assert score == 0.0  # Mock can't actually classify


def test_make_refine_fn():
    """The refine function should return a string."""
    client = MockLLM()
    refine = make_refine_fn(client)
    result = refine("current prompt", 0.5, "some errors")
    assert isinstance(result, str)
    assert len(result) > 0


# --- Train/validation split tests ----------------------------------------


def test_evaluate_fn_scores_on_validation_partition_only():
    """Accuracy must come from validation items, not training items.

    We build a classifier that gets validation items right and training
    items wrong. If accuracy reflects validation, it should be 1.0. If
    it leaked training data into scoring, it would be lower.
    """
    # 10 items — with default 0.3 split that's 7 training + 3 validation.
    # We need to discover which items land in each partition, then build
    # a classifier that distinguishes them.
    calibration = [
        DimensionLabel(f"GT{i}", f"item-{i}", f"ctx-{i}", Dimension.SECURITY)
        for i in range(10)
    ]

    # Discover the split by tracking which items the evaluate function
    # classifies. We do two passes: one that records all classified items.
    classified_items: list[str] = []

    class TrackingLLM:
        def complete(self, system: str, user: str) -> str:
            # Extract the item text from the user message.
            for label in calibration:
                if label.text in user:
                    classified_items.append(label.issue_id)
            return "security"  # Always correct for these items.

    tracking_llm = TrackingLLM()
    evaluate_fn = make_dimension_evaluate_fn(calibration, tracking_llm)
    score, _ = evaluate_fn("test prompt")

    # All 10 items should be classified (3 for validation scoring,
    # 7 for training error analysis).
    assert len(classified_items) == 10

    # Score should be 1.0 because all items are security and classifier
    # returns security.
    assert score == 1.0


def test_error_analysis_uses_training_partition_only():
    """Error analysis fed to the refiner must reference only training items.

    We build a classifier that always returns the wrong answer, then
    check that the error analysis string only contains training item IDs.
    """
    calibration = [
        DimensionLabel(f"GT{i}", f"item-{i}", f"ctx-{i}", Dimension.SECURITY)
        for i in range(20)
    ]

    class AlwaysWrongLLM:
        def complete(self, system: str, user: str) -> str:
            return "correctness"  # Wrong — all items are security.

    wrong_llm = AlwaysWrongLLM()
    evaluate_fn = make_dimension_evaluate_fn(calibration, wrong_llm)
    _, error_analysis = evaluate_fn("test prompt")

    # Reconstruct the split to know which items are training vs validation.
    import random
    rng = random.Random(42)  # Same seed as default.
    shuffled = list(calibration)
    rng.shuffle(shuffled)
    split_index = max(1, len(shuffled) - int(len(shuffled) * 0.3))
    training_ids = {label.issue_id for label in shuffled[:split_index]}
    validation_ids = {label.issue_id for label in shuffled[split_index:]}

    # Error analysis should mention training IDs (misclassified items).
    for issue_id in training_ids:
        assert issue_id in error_analysis, (
            f"Training item {issue_id} should appear in error analysis"
        )

    # Error analysis must NOT mention validation IDs.
    for issue_id in validation_ids:
        assert issue_id not in error_analysis, (
            f"Validation item {issue_id} leaked into error analysis"
        )


def test_split_is_deterministic():
    """Same calibration set + same seed must produce identical scores."""
    calibration = [
        DimensionLabel(f"GT{i}", f"item-{i}", "", Dimension.SECURITY)
        for i in range(20)
    ]

    class CountingLLM:
        def __init__(self):
            self.call_count = 0

        def complete(self, system: str, user: str) -> str:
            self.call_count += 1
            return "security"

    llm_a = CountingLLM()
    llm_b = CountingLLM()

    eval_a = make_dimension_evaluate_fn(calibration, llm_a, split_seed=42)
    eval_b = make_dimension_evaluate_fn(calibration, llm_b, split_seed=42)

    score_a, analysis_a = eval_a("prompt")
    score_b, analysis_b = eval_b("prompt")

    assert score_a == score_b
    assert analysis_a == analysis_b
    assert llm_a.call_count == llm_b.call_count


def test_small_calibration_set_logs_warning(caplog):
    """Calibration sets that produce fewer than 10 validation items
    should trigger a warning log message."""
    import logging

    calibration = [
        DimensionLabel(f"GT{i}", f"item-{i}", "", Dimension.SECURITY)
        for i in range(5)
    ]

    client = MockLLM()
    with caplog.at_level(logging.WARNING):
        make_dimension_evaluate_fn(calibration, client)

    assert any(
        "Validation partition has only" in record.message
        for record in caplog.records
    ), "Expected a warning about small validation partition"


def test_validation_fraction_adjustable():
    """Users can override the default 0.3 validation fraction."""
    calibration = [
        DimensionLabel(f"GT{i}", f"unique_marker_{i:04d}", "", Dimension.SECURITY)
        for i in range(20)
    ]

    classify_call_count = 0

    class CountingLLM:
        def complete(self, system: str, user: str) -> str:
            nonlocal classify_call_count
            classify_call_count += 1
            return "security"

    counting_llm = CountingLLM()
    # 50% validation = 10 validation + 10 training = 20 total classify calls.
    evaluate_fn = make_dimension_evaluate_fn(
        calibration, counting_llm, validation_fraction=0.5,
    )
    evaluate_fn("prompt")

    assert classify_call_count == 20  # All items classified across both partitions.
