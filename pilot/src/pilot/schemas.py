"""Data schemas for the measurement framework pilot.

Mirrors the 15-dimension taxonomy (Section 2) and 4-level severity scale
(Section 4.2.1) from the framework specification.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


class Dimension(str, Enum):
    """The 15 review dimensions from Section 2 of the framework.

    Ranked by production-incident correlation across three tiers.
    """

    # Tier 1: High production-incident correlation
    CORRECTNESS = "correctness"
    CONCURRENCY = "concurrency"
    ERROR_HANDLING = "error_handling"
    SECURITY = "security"
    RESOURCE_MANAGEMENT = "resource_management"

    # Tier 2: Moderate production-incident correlation
    CONFIGURATION = "configuration"
    API_DESIGN = "api_design"
    TEST_QUALITY = "test_quality"
    ARCHITECTURE = "architecture"
    DATA_VALIDATION = "data_validation"

    # Tier 3: Code health
    MAINTAINABILITY = "maintainability"
    READABILITY = "readability"
    DOCUMENTATION = "documentation"
    STYLE = "style"
    PERFORMANCE = "performance"


TIER_1 = {
    Dimension.CORRECTNESS,
    Dimension.CONCURRENCY,
    Dimension.ERROR_HANDLING,
    Dimension.SECURITY,
    Dimension.RESOURCE_MANAGEMENT,
}
TIER_2 = {
    Dimension.CONFIGURATION,
    Dimension.API_DESIGN,
    Dimension.TEST_QUALITY,
    Dimension.ARCHITECTURE,
    Dimension.DATA_VALIDATION,
}
TIER_3 = {
    Dimension.MAINTAINABILITY,
    Dimension.READABILITY,
    Dimension.DOCUMENTATION,
    Dimension.STYLE,
    Dimension.PERFORMANCE,
}


def tier_of(dimension: Dimension) -> int:
    """Return the tier (1, 2, or 3) for a given dimension."""
    if dimension in TIER_1:
        return 1
    if dimension in TIER_2:
        return 2
    return 3


class ChangeType(str, Enum):
    """The 6 change types from Section 3 of the framework."""

    CONFIGURATION = "configuration"
    ARCHITECTURAL_REFACTORING = "architectural_refactoring"
    DEPENDENCY_UPDATE = "dependency_update"
    NEW_FEATURE = "new_feature"
    BUG_FIX = "bug_fix"
    SIMPLE_REFACTORING = "simple_refactoring"


class Severity(int, Enum):
    """The 4-level severity scale from Section 4.2.1 of the framework.

    This scale is canonical across metrics, ground truth, and judge output.
    """

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class Location(BaseModel):
    """A location in the code: file path and line range."""

    model_config = ConfigDict(frozen=True)

    file_path: str
    start_line: int
    end_line: int


class GroundTruthIssue(BaseModel):
    """A known issue in a PR, annotated in the ground truth.

    These are the targets an AI reviewer is expected to find.
    """

    issue_id: str
    pr_id: str
    dimension: Dimension
    severity: Severity
    location: Location
    description: str = Field(..., description="What the issue is, in reviewer terms.")
    # Optional: difficulty for sycophancy calibration (Section 6.1.3)
    difficulty: Literal["easy", "medium", "hard"] | None = None


class PullRequest(BaseModel):
    """A PR in the evaluation set.

    Carries the diff, metadata, and ground truth issues.
    """

    pr_id: str
    title: str
    language: str
    change_type: ChangeType
    diff: str
    ground_truth: list[GroundTruthIssue]
    # Truncation metadata — populated by dataset adapters when the diff
    # is clipped at max_diff_chars. Used to compute "visible recall" that
    # excludes GT issues the reviewer could not possibly see.
    truncated: bool = False
    original_diff_length: int | None = None
    excluded_gt_ids: list[str] = Field(
        default_factory=list,
        description=(
            "IDs of GT issues whose location falls past the truncation "
            "point. These are NOT removed from ground_truth — they still "
            "count toward total recall — but are excluded from visible recall."
        ),
    )


class ReviewerFinding(BaseModel):
    """A finding produced by an AI reviewer.

    The reviewer may produce findings that match ground truth (true positives),
    that don't match anything in ground truth (potential false positives or
    confirmed novel findings), or miss ground truth issues entirely.
    """

    finding_id: str
    pr_id: str
    reviewer_model: str
    location: Location
    dimension: Dimension
    severity: Severity
    comment: str = Field(..., description="The actual review comment text.")


class MatchResult(BaseModel):
    """Result of matching an AI finding to a ground truth issue."""

    ground_truth_issue_id: str
    finding_id: str | None = Field(
        None, description="None if no finding matched this issue (a miss)."
    )
    match_confidence: Literal["high", "medium", "low"] | None = None


class AdjudicationCategory(str, Enum):
    """Outcome of the false positive adjudication protocol (Section 4.3)."""

    CFP = "confirmed_false_positive"
    PF = "plausible_finding"
    CNF = "confirmed_novel_finding"


class JudgeOutput(BaseModel):
    """A single judge's assessment of a finding.

    Used for issue-match tasks, validity assessments, and severity judgements
    (Section 8.3).
    """

    judge_model: str
    task: Literal["match", "validity", "severity", "quality"]
    # For match task: is this a match?
    is_match: bool | None = None
    # For validity task: is this finding valid?
    is_valid: bool | None = None
    dimension_classification: Dimension | None = None
    # For severity task: what's the severity?
    severity_assessment: Severity | None = None
    # For adjudication: which category?
    adjudication: AdjudicationCategory | None = None
    justification: str = ""


class DimensionMetrics(BaseModel):
    """Metrics for a single review dimension."""

    dimension: Dimension
    tier: int
    # Counts
    n_ground_truth: int = Field(..., description="Number of ground truth issues in this dimension.")
    true_positives: int
    false_positives: int
    false_negatives: int
    # Proportions
    precision: float | None = Field(
        None, description="None when n_ground_truth + false_positives == 0."
    )
    recall: float | None = Field(None, description="None when n_ground_truth == 0.")
    f1: float | None = None
    # Confidence intervals (Wilson score, 95%)
    precision_ci: tuple[float, float] | None = None
    recall_ci: tuple[float, float] | None = None


class ClaimedDimensionMetrics(BaseModel):
    """Per-dimension metrics from the finding's (claimed) perspective.

    In the GT-perspective table, TPs are attributed to the GT issue's dimension.
    That is good for recall ("what fraction of concurrency bugs were found?")
    but misleading for precision when dimension misclassification is common.

    This model attributes TPs to the finding's claimed dimension instead,
    giving an honest answer to "when the reviewer says concurrency, is it
    right?" Only precision and the counts needed to compute it are tracked
    here — recall is not meaningful from the claim perspective because
    false negatives have no claimed dimension.
    """

    dimension: Dimension
    tier: int
    # Counts from the finding's perspective
    true_positives: int = Field(
        ..., description="Findings claiming this dimension that matched a GT issue."
    )
    false_positives: int = Field(
        ..., description="Findings claiming this dimension that matched nothing."
    )
    total_claims: int = Field(
        ..., description="Total findings claiming this dimension (TP + FP)."
    )
    precision: float | None = Field(
        None, description="TP / (TP + FP) from the claim perspective. None when total_claims == 0."
    )
    precision_ci: tuple[float, float] | None = None


class MetricsReport(BaseModel):
    """Complete metrics report for an evaluation run.

    Conforms to the reporting specification in Section 9.7.
    """

    reviewer_model: str
    judge_panel: list[str]
    evaluation_set: str
    n_prs: int
    per_dimension: list[DimensionMetrics]
    # Finding-perspective per-dimension breakdown (claimed dimension attribution).
    # Answers "when the reviewer claims dimension X, how often is it correct?"
    per_dimension_by_claim: list[ClaimedDimensionMetrics] = Field(default_factory=list)
    # Aggregate totals
    total_true_positives: int
    total_false_positives: int
    total_false_negatives: int
    aggregate_precision: float | None = None
    aggregate_recall: float | None = None
    aggregate_f1: float | None = None
    aggregate_precision_ci: tuple[float, float] | None = None
    aggregate_recall_ci: tuple[float, float] | None = None
    # Dimension classification accuracy (framework Section 4.2.4):
    # When a reviewer finding matches a GT issue, does it also classify the
    # dimension correctly? This distinguishes "found the issue" from "found
    # and correctly classified the issue". The denominator is the number of
    # true positives; the numerator is the subset where finding.dimension
    # equals ground_truth.dimension.
    dimension_classification_tp: int = 0
    dimension_classification_accuracy: float | None = None
    dimension_classification_accuracy_ci: tuple[float, float] | None = None
    # Visible recall — excludes GT issues in truncated diff regions.
    # None when no PRs were truncated (visible recall == total recall).
    visible_recall: float | None = None
    visible_recall_ci: tuple[float, float] | None = None
    truncated_pr_count: int = 0
    excluded_gt_issue_count: int = 0
    # Metadata
    framework_version: str = "1.0"
    run_metadata: dict[str, str] = Field(default_factory=dict)
