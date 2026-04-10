"""Prompt templates for reviewer and judge tasks.

These prompts are derived from the framework specification (Section 8.5 for
judge tasks) and adapted for the reviewer task. The goal is to produce
structured JSON output that conforms to the pydantic schemas.
"""

from __future__ import annotations

from pilot.schemas import Dimension, GroundTruthIssue, PullRequest, ReviewerFinding


# --- Reviewer prompt ------------------------------------------------------

REVIEWER_SYSTEM = """You are an expert code reviewer. Given a pull request \
diff, identify all genuine issues in the code. Be precise: only flag issues \
that are supported by the code itself. Do not invent problems. Do not flag \
style preferences that a linter would handle.

Classify each finding into exactly one of these 15 dimensions:

Tier 1 (high production-incident correlation):
- correctness: logic errors, off-by-one, null handling, wrong return values
- concurrency: race conditions, deadlocks, atomicity violations
- error_handling: missing error checks, swallowed exceptions, incorrect propagation
- security: vulnerabilities, auth/crypto issues, info disclosure
- resource_management: memory/handle leaks, unbounded growth

Tier 2 (moderate correlation, high long-term impact):
- configuration: config errors, environment assumptions
- api_design: breaking changes, inconsistent interfaces
- test_quality: missing coverage, weak assertions
- architecture: separation of concerns, dependency direction
- data_validation: missing trust-boundary checks (distinct from security)

Tier 3 (code health):
- maintainability: duplication, dead code, complex logic
- readability: naming, expression clarity within a function
- documentation: missing or misleading docs
- style: formatting, convention violations
- performance: algorithmic complexity, wasteful patterns

Assign severity on a 4-level scale:
1 = Low (cosmetic, no functional impact)
2 = Medium (code quality issue, maintenance burden)
3 = High (functional defect under specific conditions)
4 = Critical (security, data loss, production incident risk)

Respond with a single JSON object containing a "findings" array. Each finding must \
have: location (file_path, start_line, end_line), dimension (exact enum value), \
severity (1-4), comment (concrete and actionable)."""

REVIEWER_USER_TEMPLATE = """Review the following pull request and identify all genuine issues.

Title: {title}
Language: {language}
Change type: {change_type}

Diff:
```
{diff}
```

Respond with JSON only. No prose before or after."""


def build_reviewer_prompt(pr: PullRequest) -> tuple[str, str]:
    """Build the system and user prompts for the reviewer task.

    Returns:
        (system_prompt, user_prompt)
    """
    user = REVIEWER_USER_TEMPLATE.format(
        title=pr.title,
        language=pr.language,
        change_type=pr.change_type.value,
        diff=pr.diff,
    )
    return REVIEWER_SYSTEM, user


# --- Judge issue-match prompt (S8.5.1) -----------------------------------

JUDGE_MATCH_SYSTEM = """You are an expert code review judge evaluating whether \
an AI-generated review comment correctly identifies a specific known issue.

You will be given:
1. A code diff
2. A known ground truth issue in the code (the issue description, location, and dimension)
3. A set of AI-generated review comments on the same code

Your task: for the ground truth issue, determine which (if any) of the AI comments \
identifies the same underlying issue. Two comments identify the same issue when they \
describe the same problem in the same code location, even if the wording differs.

Respond with a single JSON object:
{
  "matched_finding_id": "F001" or null,
  "match_confidence": "high" or "medium" or "low" or null,
  "justification": "one sentence explaining the decision"
}

Rules:
- If multiple findings describe the same ground truth issue, pick the most specific one.
- "high" confidence = unambiguous match with precise location and description.
- "medium" confidence = clearly the same issue but with different framing or slightly different location.
- "low" confidence = arguably the same issue but with meaningful ambiguity.
- null = no finding matches this ground truth issue.
- A finding about a different line that happens to mention similar concepts does NOT match.
- Dimension labels do not need to match exactly — a finding labelled "concurrency" that describes a thread safety issue matching a "correctness" GT issue is still a match if the underlying problem is the same.
"""

JUDGE_MATCH_USER_TEMPLATE = """Code diff:
```
{diff}
```

Ground truth issue:
- ID: {gt_id}
- Dimension: {gt_dimension}
- Severity: {gt_severity}
- Location: {gt_location}
- Description: {gt_description}

AI-generated findings:
{findings_block}

Which AI finding (if any) identifies the same issue as the ground truth?
Respond with JSON only. No prose before or after."""


def build_judge_match_prompt(
    pr: PullRequest,
    gt_issue: GroundTruthIssue,
    findings: list[ReviewerFinding],
) -> tuple[str, str]:
    """Build the system and user prompts for the judge issue-match task.

    Returns:
        (system_prompt, user_prompt)
    """
    if not findings:
        findings_block = "(no findings from this reviewer)"
    else:
        lines = []
        for f in findings:
            lines.append(
                f"- ID: {f.finding_id}\n"
                f"  Dimension: {f.dimension.value}\n"
                f"  Severity: {f.severity.value}\n"
                f"  Location: {f.location.file_path}:{f.location.start_line}-{f.location.end_line}\n"
                f"  Comment: {f.comment}"
            )
        findings_block = "\n".join(lines)

    user = JUDGE_MATCH_USER_TEMPLATE.format(
        diff=pr.diff,
        gt_id=gt_issue.issue_id,
        gt_dimension=gt_issue.dimension.value,
        gt_severity=gt_issue.severity.value,
        gt_location=f"{gt_issue.location.file_path}:{gt_issue.location.start_line}-{gt_issue.location.end_line}",
        gt_description=gt_issue.description,
        findings_block=findings_block,
    )
    return JUDGE_MATCH_SYSTEM, user
