"""Real API adapters for Anthropic and OpenAI.

These implement the Reviewer and Judge interfaces using actual LLM APIs.
The adapters accept a client object as a dependency, which allows tests to
inject mocked clients without touching real APIs.

Wire up:
    from anthropic import Anthropic
    from openai import OpenAI

    reviewer = AnthropicReviewer(client=Anthropic(api_key=...))
    judge = AnthropicJudge(client=Anthropic(api_key=...))
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from pilot.judge import Judge
from pilot.prompts import build_judge_match_prompt, build_reviewer_prompt
from pilot.reviewer import Reviewer
from pilot.schemas import (
    Dimension,
    GroundTruthIssue,
    Location,
    MatchResult,
    PullRequest,
    ReviewerFinding,
    Severity,
)


logger = logging.getLogger(__name__)


# --- Severity coercion -------------------------------------------------


# Mapping from case-insensitive name strings to Severity enum values.
_SEVERITY_NAME_MAP: dict[str, Severity] = {
    member.name.lower(): member for member in Severity
}


def _coerce_severity(raw_value: Any) -> tuple[Severity, bool]:
    """Coerce a raw severity value from LLM output into a Severity enum.

    LLMs commonly return severity as strings ("3", "High", "critical")
    rather than the expected integer. This function handles all reasonable
    representations gracefully.

    Returns:
        A tuple of (severity, was_coerced). was_coerced is True if the
        value required any transformation beyond a direct int lookup.
        If all coercion fails, defaults to Severity.MEDIUM with a warning.
    """
    # Already a Severity instance — pass through.
    if isinstance(raw_value, Severity):
        return raw_value, False

    # Integer — direct enum construction.
    if isinstance(raw_value, int) and not isinstance(raw_value, bool):
        try:
            return Severity(raw_value), False
        except ValueError:
            logger.warning(
                "Severity integer %d out of range [1-4], defaulting to MEDIUM",
                raw_value,
            )
            return Severity.MEDIUM, True

    # Float — accept if it's a whole number (e.g. 3.0 from JSON).
    if isinstance(raw_value, float):
        if raw_value == int(raw_value) and not (raw_value != raw_value):  # guard NaN
            try:
                return Severity(int(raw_value)), True
            except ValueError:
                pass
        logger.warning(
            "Severity float %r cannot be coerced, defaulting to MEDIUM",
            raw_value,
        )
        return Severity.MEDIUM, True

    # String — try numeric parse first, then name lookup.
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            logger.warning("Empty severity string, defaulting to MEDIUM")
            return Severity.MEDIUM, True

        # Numeric string ("3", "4").
        try:
            return Severity(int(stripped)), True
        except (ValueError, KeyError):
            pass

        # Name string ("High", "critical", "MEDIUM").
        normalised = stripped.lower()
        if normalised in _SEVERITY_NAME_MAP:
            return _SEVERITY_NAME_MAP[normalised], True

        logger.warning(
            "Unrecognised severity string %r, defaulting to MEDIUM",
            raw_value,
        )
        return Severity.MEDIUM, True

    # Anything else (None, dict, list, bool, etc.) — default.
    logger.warning(
        "Unexpected severity type %s (%r), defaulting to MEDIUM",
        type(raw_value).__name__,
        raw_value,
    )
    return Severity.MEDIUM, True


# --- Protocols for dependency injection ---------------------------------


class AnthropicClient(Protocol):
    """Minimum interface required from anthropic.Anthropic for the adapters.

    Used to allow test mocks. In production, pass an actual Anthropic instance.
    """

    messages: Any


class OpenAIClient(Protocol):
    """Minimum interface required from openai.OpenAI for the adapters."""

    chat: Any


# --- Cost tracking ------------------------------------------------------


@dataclass
class UsageRecord:
    """Tracks token consumption and call counts for a single adapter."""

    input_tokens: int = 0
    output_tokens: int = 0
    call_count: int = 0
    errors: int = 0
    severity_coercions: int = 0
    severity_coercion_failures: int = 0
    total_findings_parsed: int = 0

    def record(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.call_count += 1

    def record_error(self) -> None:
        self.errors += 1
        self.call_count += 1

    @property
    def severity_coercion_rate(self) -> float:
        """Proportion of parsed findings that required severity coercion."""
        if self.total_findings_parsed == 0:
            return 0.0
        return self.severity_coercions / self.total_findings_parsed


# --- Response parsing ---------------------------------------------------


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from model output.

    Handles cases where the model wraps the JSON in markdown code fences or
    includes leading/trailing whitespace. Raises ValueError on failure.
    """
    text = text.strip()
    if text.startswith("```"):
        # Strip markdown code fences.
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model output is not valid JSON: {e}. Text: {text[:200]}") from e


def parse_reviewer_findings(
    response_text: str,
    pr_id: str,
    reviewer_model: str,
    usage: UsageRecord | None = None,
) -> list[ReviewerFinding]:
    """Parse a reviewer API response into ReviewerFinding objects.

    Expected format: {"findings": [{"location": {...}, "dimension": "...", "severity": N, "comment": "..."}, ...]}

    When a UsageRecord is provided, severity coercion events are tracked
    on it so callers can monitor data quality.
    """
    data = _extract_json(response_text)
    if "findings" not in data:
        raise ValueError("Reviewer response missing 'findings' array")
    findings: list[ReviewerFinding] = []
    for i, item in enumerate(data["findings"]):
        try:
            severity, was_coerced = _coerce_severity(item.get("severity"))
            if usage is not None:
                usage.total_findings_parsed += 1
                if was_coerced:
                    usage.severity_coercions += 1
                    # Track whether the coercion fell back to the default.
                    original = item.get("severity")
                    coerced_to_default = (
                        severity == Severity.MEDIUM
                        and not _is_intentional_medium(original)
                    )
                    if coerced_to_default:
                        usage.severity_coercion_failures += 1

            finding = ReviewerFinding(
                finding_id=f"{pr_id}-F{i+1:03d}",
                pr_id=pr_id,
                reviewer_model=reviewer_model,
                location=Location.model_validate(item["location"]),
                dimension=Dimension(item["dimension"]),
                severity=severity,
                comment=item["comment"],
            )
            findings.append(finding)
        except (KeyError, ValueError, ValidationError) as e:
            logger.warning(
                "Skipping malformed finding %d for PR %s: %s", i, pr_id, e
            )
            continue
    return findings


def _is_intentional_medium(raw_value: Any) -> bool:
    """Check whether the raw value genuinely represents MEDIUM.

    Used to distinguish "coerced to default" from "legitimately MEDIUM".
    """
    if isinstance(raw_value, int) and not isinstance(raw_value, bool):
        return raw_value == Severity.MEDIUM.value
    if isinstance(raw_value, float):
        return raw_value == float(Severity.MEDIUM.value)
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if stripped == str(Severity.MEDIUM.value):
            return True
        if stripped.lower() == "medium":
            return True
    return False


def parse_judge_match(
    response_text: str,
    gt_issue_id: str,
) -> MatchResult:
    """Parse a judge API response into a MatchResult.

    Expected format: {"matched_finding_id": "F001" or null, "match_confidence": "high"/"medium"/"low" or null, "justification": "..."}
    """
    data = _extract_json(response_text)
    matched_id = data.get("matched_finding_id")
    confidence = data.get("match_confidence")
    # Normalise "null" string to None.
    if isinstance(matched_id, str) and matched_id.lower() == "null":
        matched_id = None
    return MatchResult(
        ground_truth_issue_id=gt_issue_id,
        finding_id=matched_id,
        match_confidence=confidence if confidence in ("high", "medium", "low") else None,
    )


# --- Anthropic adapters --------------------------------------------------


class AnthropicReviewer(Reviewer):
    """Reviewer using the Anthropic API.

    Pass a configured Anthropic client. The adapter builds prompts, calls
    the API, parses structured JSON output, and records token usage.

    Malformed findings are logged and skipped rather than failing the whole
    review — this matches c-CRAB's approach of treating reviewer quality as
    the thing being measured, not as a precondition.
    """

    def __init__(
        self,
        client: AnthropicClient,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
    ):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self.usage = UsageRecord()

    @property
    def model_name(self) -> str:
        return f"anthropic/{self._model}"

    def review(self, pr: PullRequest) -> list[ReviewerFinding]:
        system, user = build_reviewer_prompt(pr)
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=0,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            logger.error("Anthropic API call failed for PR %s: %s", pr.pr_id, e)
            self.usage.record_error()
            return []

        # Extract usage
        if hasattr(response, "usage"):
            self.usage.record(
                input_tokens=getattr(response.usage, "input_tokens", 0),
                output_tokens=getattr(response.usage, "output_tokens", 0),
            )
        else:
            self.usage.record(0, 0)

        # Extract content
        content_blocks = getattr(response, "content", [])
        if not content_blocks:
            return []
        text = content_blocks[0].text if hasattr(content_blocks[0], "text") else ""

        try:
            return parse_reviewer_findings(text, pr.pr_id, self.model_name, usage=self.usage)
        except ValueError as e:
            logger.error("Failed to parse reviewer response for PR %s: %s", pr.pr_id, e)
            return []


class AnthropicJudge(Judge):
    """Judge using the Anthropic API for the issue-match task (S8.3.1)."""

    def __init__(
        self,
        client: AnthropicClient,
        model: str = "claude-opus-4-6",
        max_tokens: int = 1024,
    ):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self.usage = UsageRecord()

    @property
    def model_name(self) -> str:
        return f"anthropic/{self._model}"

    @property
    def family(self) -> str:
        return "anthropic"

    def match_findings_to_ground_truth(
        self,
        pr: PullRequest,
        findings: list[ReviewerFinding],
    ) -> list[MatchResult]:
        results: list[MatchResult] = []
        for gt_issue in pr.ground_truth:
            system, user = build_judge_match_prompt(pr, gt_issue, findings)
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    temperature=0,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
            except Exception as e:
                logger.error(
                    "Anthropic judge call failed for GT %s: %s", gt_issue.issue_id, e
                )
                self.usage.record_error()
                results.append(
                    MatchResult(ground_truth_issue_id=gt_issue.issue_id, finding_id=None)
                )
                continue

            if hasattr(response, "usage"):
                self.usage.record(
                    input_tokens=getattr(response.usage, "input_tokens", 0),
                    output_tokens=getattr(response.usage, "output_tokens", 0),
                )
            else:
                self.usage.record(0, 0)

            content_blocks = getattr(response, "content", [])
            text = content_blocks[0].text if content_blocks and hasattr(content_blocks[0], "text") else ""
            try:
                results.append(parse_judge_match(text, gt_issue.issue_id))
            except ValueError as e:
                logger.error(
                    "Failed to parse judge response for GT %s: %s", gt_issue.issue_id, e
                )
                results.append(
                    MatchResult(ground_truth_issue_id=gt_issue.issue_id, finding_id=None)
                )
        return results


# --- OpenAI adapters -----------------------------------------------------


class OpenAIJudge(Judge):
    """Judge using the OpenAI API. Used for multi-family judge panels.

    Note: only the judge is implemented for OpenAI in the pilot. A
    corresponding reviewer adapter could be added when needed for cross-
    family reviewer comparisons.
    """

    def __init__(
        self,
        client: OpenAIClient,
        model: str = "gpt-4o",
        max_tokens: int = 1024,
    ):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self.usage = UsageRecord()

    @property
    def model_name(self) -> str:
        return f"openai/{self._model}"

    @property
    def family(self) -> str:
        return "openai"

    def match_findings_to_ground_truth(
        self,
        pr: PullRequest,
        findings: list[ReviewerFinding],
    ) -> list[MatchResult]:
        results: list[MatchResult] = []
        for gt_issue in pr.ground_truth:
            system, user = build_judge_match_prompt(pr, gt_issue, findings)
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                )
            except Exception as e:
                logger.error(
                    "OpenAI judge call failed for GT %s: %s", gt_issue.issue_id, e
                )
                self.usage.record_error()
                results.append(
                    MatchResult(ground_truth_issue_id=gt_issue.issue_id, finding_id=None)
                )
                continue

            if hasattr(response, "usage") and response.usage is not None:
                self.usage.record(
                    input_tokens=getattr(response.usage, "prompt_tokens", 0),
                    output_tokens=getattr(response.usage, "completion_tokens", 0),
                )
            else:
                self.usage.record(0, 0)

            choices = getattr(response, "choices", [])
            if not choices:
                results.append(
                    MatchResult(ground_truth_issue_id=gt_issue.issue_id, finding_id=None)
                )
                continue
            text = choices[0].message.content or ""
            try:
                results.append(parse_judge_match(text, gt_issue.issue_id))
            except ValueError as e:
                logger.error(
                    "Failed to parse OpenAI judge response for GT %s: %s",
                    gt_issue.issue_id,
                    e,
                )
                results.append(
                    MatchResult(ground_truth_issue_id=gt_issue.issue_id, finding_id=None)
                )
        return results
