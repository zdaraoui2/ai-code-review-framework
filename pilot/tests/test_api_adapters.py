"""Tests for real API adapters using mocked clients."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pilot.api_adapters import (
    AnthropicJudge,
    AnthropicReviewer,
    OpenAIJudge,
    UsageRecord,
    _coerce_severity,
    _extract_json,
    parse_judge_match,
    parse_reviewer_findings,
)
from pilot.schemas import (
    ChangeType,
    Dimension,
    GroundTruthIssue,
    Location,
    PullRequest,
    Severity,
)


# --- Helpers ------------------------------------------------------------


def _sample_pr(pr_id: str = "PR1") -> PullRequest:
    return PullRequest(
        pr_id=pr_id,
        title="Test PR",
        language="python",
        change_type=ChangeType.NEW_FEATURE,
        diff="+print('hi')",
        ground_truth=[
            GroundTruthIssue(
                issue_id=f"{pr_id}-GT1",
                pr_id=pr_id,
                dimension=Dimension.SECURITY,
                severity=Severity.HIGH,
                location=Location(file_path="a.py", start_line=1, end_line=1),
                description="A test issue.",
            )
        ],
    )


class _MockAnthropicResponse:
    def __init__(self, text: str, input_tokens: int = 100, output_tokens: int = 50):
        self.content = [SimpleNamespace(text=text)]
        self.usage = SimpleNamespace(
            input_tokens=input_tokens, output_tokens=output_tokens
        )


class _MockAnthropicClient:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.messages = self
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("No more mock responses")
        return _MockAnthropicResponse(self._responses.pop(0))


class _MockOpenAIResponse:
    def __init__(
        self,
        content: str,
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
    ):
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        self.choices = [choice]
        self.usage = SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )


class _MockOpenAICompletions:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("No more mock responses")
        return _MockOpenAIResponse(self._responses.pop(0))


class _MockOpenAIClient:
    def __init__(self, responses: list[str]):
        completions = _MockOpenAICompletions(responses)
        self.chat = SimpleNamespace(completions=completions)
        self._completions = completions

    @property
    def calls(self):
        return self._completions.calls


# --- JSON extraction tests ----------------------------------------------


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_code_fence():
    text = '```json\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_extract_json_with_unmarked_fence():
    text = '```\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_extract_json_with_whitespace():
    text = '   \n  {"a": 1}  \n  '
    assert _extract_json(text) == {"a": 1}


def test_extract_json_invalid_raises():
    with pytest.raises(ValueError):
        _extract_json("not json")


# --- Reviewer response parsing tests ------------------------------------


def test_parse_reviewer_findings_success():
    response = """{
      "findings": [
        {
          "location": {"file_path": "api.py", "start_line": 10, "end_line": 12},
          "dimension": "security",
          "severity": 4,
          "comment": "SQL injection risk."
        }
      ]
    }"""
    findings = parse_reviewer_findings(response, "PR1", "test-model")
    assert len(findings) == 1
    assert findings[0].dimension == Dimension.SECURITY
    assert findings[0].severity == Severity.CRITICAL
    assert findings[0].pr_id == "PR1"


def test_parse_reviewer_findings_skips_malformed():
    response = """{
      "findings": [
        {"location": {"file_path": "a.py", "start_line": 1, "end_line": 1}, "dimension": "security", "severity": 4, "comment": "Good finding."},
        {"dimension": "not_a_real_dim", "severity": 4, "comment": "Bad."}
      ]
    }"""
    findings = parse_reviewer_findings(response, "PR1", "test-model")
    assert len(findings) == 1


def test_parse_reviewer_findings_missing_findings_key():
    with pytest.raises(ValueError):
        parse_reviewer_findings('{"other": []}', "PR1", "test-model")


# --- Judge response parsing tests ---------------------------------------


def test_parse_judge_match_positive():
    response = '{"matched_finding_id": "F1", "match_confidence": "high", "justification": "Matches exactly."}'
    result = parse_judge_match(response, "GT1")
    assert result.ground_truth_issue_id == "GT1"
    assert result.finding_id == "F1"
    assert result.match_confidence == "high"


def test_parse_judge_match_no_match():
    response = '{"matched_finding_id": null, "match_confidence": null, "justification": "No match."}'
    result = parse_judge_match(response, "GT1")
    assert result.finding_id is None
    assert result.match_confidence is None


def test_parse_judge_match_invalid_confidence_becomes_none():
    response = '{"matched_finding_id": "F1", "match_confidence": "super-high"}'
    result = parse_judge_match(response, "GT1")
    assert result.finding_id == "F1"
    assert result.match_confidence is None  # Invalid confidence normalised


# --- Anthropic reviewer tests ------------------------------------------


def test_anthropic_reviewer_happy_path():
    response_text = """{
      "findings": [
        {
          "location": {"file_path": "a.py", "start_line": 1, "end_line": 1},
          "dimension": "security",
          "severity": 4,
          "comment": "Test."
        }
      ]
    }"""
    client = _MockAnthropicClient([response_text])
    reviewer = AnthropicReviewer(client=client, model="claude-test")
    pr = _sample_pr()

    findings = reviewer.review(pr)
    assert len(findings) == 1
    assert findings[0].dimension == Dimension.SECURITY
    assert reviewer.usage.call_count == 1
    assert reviewer.usage.input_tokens == 100
    assert reviewer.usage.output_tokens == 50


def test_anthropic_reviewer_handles_api_error():
    class _FailingClient:
        class _FailingMessages:
            def create(self, **kwargs):
                raise RuntimeError("API down")

        messages = _FailingMessages()

    reviewer = AnthropicReviewer(client=_FailingClient())
    pr = _sample_pr()
    findings = reviewer.review(pr)
    assert findings == []
    assert reviewer.usage.errors == 1


def test_anthropic_reviewer_handles_malformed_response():
    client = _MockAnthropicClient(["not valid json"])
    reviewer = AnthropicReviewer(client=client)
    pr = _sample_pr()
    findings = reviewer.review(pr)
    assert findings == []


# --- Anthropic judge tests ---------------------------------------------


def test_anthropic_judge_happy_path():
    response_text = (
        '{"matched_finding_id": "F001", "match_confidence": "high",'
        ' "justification": "Matches."}'
    )
    client = _MockAnthropicClient([response_text])
    judge = AnthropicJudge(client=client)
    pr = _sample_pr()
    results = judge.match_findings_to_ground_truth(pr, [])
    assert len(results) == 1
    assert results[0].finding_id == "F001"
    assert judge.usage.call_count == 1


def test_anthropic_judge_multiple_gt_issues():
    pr = PullRequest(
        pr_id="PR1",
        title="Test",
        language="python",
        change_type=ChangeType.NEW_FEATURE,
        diff="+x",
        ground_truth=[
            GroundTruthIssue(
                issue_id="GT1",
                pr_id="PR1",
                dimension=Dimension.SECURITY,
                severity=Severity.HIGH,
                location=Location(file_path="a.py", start_line=1, end_line=1),
                description="First issue",
            ),
            GroundTruthIssue(
                issue_id="GT2",
                pr_id="PR1",
                dimension=Dimension.CORRECTNESS,
                severity=Severity.MEDIUM,
                location=Location(file_path="a.py", start_line=2, end_line=2),
                description="Second issue",
            ),
        ],
    )
    client = _MockAnthropicClient(
        [
            '{"matched_finding_id": "F1", "match_confidence": "high"}',
            '{"matched_finding_id": null, "match_confidence": null}',
        ]
    )
    judge = AnthropicJudge(client=client)
    results = judge.match_findings_to_ground_truth(pr, [])
    assert len(results) == 2
    assert results[0].finding_id == "F1"
    assert results[1].finding_id is None
    assert judge.usage.call_count == 2


# --- OpenAI judge tests ------------------------------------------------


def test_openai_judge_happy_path():
    response_text = '{"matched_finding_id": "F1", "match_confidence": "high"}'
    client = _MockOpenAIClient([response_text])
    judge = OpenAIJudge(client=client)
    pr = _sample_pr()
    results = judge.match_findings_to_ground_truth(pr, [])
    assert len(results) == 1
    assert results[0].finding_id == "F1"
    assert judge.usage.call_count == 1
    assert judge.usage.input_tokens == 100
    assert judge.usage.output_tokens == 50


def test_openai_judge_handles_error():
    class _FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("API down")

    class _FailingClient:
        chat = SimpleNamespace(completions=_FailingCompletions())

    judge = OpenAIJudge(client=_FailingClient())
    pr = _sample_pr()
    results = judge.match_findings_to_ground_truth(pr, [])
    assert len(results) == 1
    assert results[0].finding_id is None  # Treated as no-match on error
    assert judge.usage.errors == 1


# --- Severity coercion tests -------------------------------------------


class TestCoerceSeverity:
    """Tests for _coerce_severity covering all coercion paths."""

    def test_int_no_coercion(self):
        """Direct int should pass through without coercion."""
        severity, was_coerced = _coerce_severity(3)
        assert severity == Severity.HIGH
        assert was_coerced is False

    def test_severity_enum_passthrough(self):
        """An existing Severity instance should pass through unchanged."""
        severity, was_coerced = _coerce_severity(Severity.CRITICAL)
        assert severity == Severity.CRITICAL
        assert was_coerced is False

    def test_int_out_of_range_defaults_to_medium(self):
        """An int outside [1-4] should default to MEDIUM."""
        severity, was_coerced = _coerce_severity(99)
        assert severity == Severity.MEDIUM
        assert was_coerced is True

    def test_float_whole_number(self):
        """A whole-number float (3.0) should coerce to the matching int."""
        severity, was_coerced = _coerce_severity(3.0)
        assert severity == Severity.HIGH
        assert was_coerced is True

    def test_float_fractional_defaults_to_medium(self):
        """A non-whole float (3.5) cannot map to an enum value."""
        severity, was_coerced = _coerce_severity(3.5)
        assert severity == Severity.MEDIUM
        assert was_coerced is True

    def test_numeric_string(self):
        """A numeric string like '3' should coerce to the matching int."""
        severity, was_coerced = _coerce_severity("3")
        assert severity == Severity.HIGH
        assert was_coerced is True

    def test_numeric_string_with_whitespace(self):
        """Surrounding whitespace should be stripped before coercion."""
        severity, was_coerced = _coerce_severity("  4  ")
        assert severity == Severity.CRITICAL
        assert was_coerced is True

    def test_name_string_capitalised(self):
        """'High' (title-case) should be looked up by name."""
        severity, was_coerced = _coerce_severity("High")
        assert severity == Severity.HIGH
        assert was_coerced is True

    def test_name_string_lowercase(self):
        """'critical' (lowercase) should be looked up by name."""
        severity, was_coerced = _coerce_severity("critical")
        assert severity == Severity.CRITICAL
        assert was_coerced is True

    def test_name_string_uppercase(self):
        """'MEDIUM' (uppercase) should be looked up by name."""
        severity, was_coerced = _coerce_severity("MEDIUM")
        assert severity == Severity.MEDIUM
        assert was_coerced is True

    def test_name_string_low(self):
        """'low' should map to Severity.LOW."""
        severity, was_coerced = _coerce_severity("low")
        assert severity == Severity.LOW
        assert was_coerced is True

    def test_unrecognised_string_defaults_to_medium(self):
        """An unrecognised string should default to MEDIUM."""
        severity, was_coerced = _coerce_severity("catastrophic")
        assert severity == Severity.MEDIUM
        assert was_coerced is True

    def test_empty_string_defaults_to_medium(self):
        """An empty string should default to MEDIUM."""
        severity, was_coerced = _coerce_severity("")
        assert severity == Severity.MEDIUM
        assert was_coerced is True

    def test_none_defaults_to_medium(self):
        """None should default to MEDIUM."""
        severity, was_coerced = _coerce_severity(None)
        assert severity == Severity.MEDIUM
        assert was_coerced is True

    def test_dict_defaults_to_medium(self):
        """A dict should default to MEDIUM."""
        severity, was_coerced = _coerce_severity({"level": 3})
        assert severity == Severity.MEDIUM
        assert was_coerced is True

    def test_list_defaults_to_medium(self):
        """A list should default to MEDIUM."""
        severity, was_coerced = _coerce_severity([3])
        assert severity == Severity.MEDIUM
        assert was_coerced is True

    def test_bool_defaults_to_medium(self):
        """A bool should not be treated as int; it should default to MEDIUM."""
        severity, was_coerced = _coerce_severity(True)
        assert severity == Severity.MEDIUM
        assert was_coerced is True


class TestSeverityCoercionTracking:
    """Tests that coercion events are recorded on the UsageRecord."""

    def _make_response(self, severity_value) -> str:
        """Build a minimal reviewer JSON response with a given severity value."""
        import json
        return json.dumps({
            "findings": [{
                "location": {"file_path": "a.py", "start_line": 1, "end_line": 1},
                "dimension": "security",
                "severity": severity_value,
                "comment": "Test finding.",
            }]
        })

    def test_int_severity_not_counted_as_coercion(self):
        """A direct int severity should not increment the coercion counter."""
        usage = UsageRecord()
        response = self._make_response(4)
        findings = parse_reviewer_findings(response, "PR1", "test", usage=usage)
        assert len(findings) == 1
        assert usage.severity_coercions == 0
        assert usage.total_findings_parsed == 1

    def test_string_severity_counted_as_coercion(self):
        """A string severity should increment the coercion counter."""
        usage = UsageRecord()
        response = self._make_response("High")
        findings = parse_reviewer_findings(response, "PR1", "test", usage=usage)
        assert len(findings) == 1
        assert findings[0].severity == Severity.HIGH
        assert usage.severity_coercions == 1
        assert usage.severity_coercion_failures == 0

    def test_invalid_string_counted_as_coercion_failure(self):
        """An unrecognised string defaults to MEDIUM and counts as a failure."""
        usage = UsageRecord()
        response = self._make_response("catastrophic")
        findings = parse_reviewer_findings(response, "PR1", "test", usage=usage)
        assert len(findings) == 1
        assert findings[0].severity == Severity.MEDIUM
        assert usage.severity_coercions == 1
        assert usage.severity_coercion_failures == 1

    def test_coercion_rate_calculation(self):
        """The coercion rate should be coercions / total parsed findings."""
        import json
        usage = UsageRecord()
        # Two findings: one int (no coercion), one string (coerced).
        response = json.dumps({
            "findings": [
                {
                    "location": {"file_path": "a.py", "start_line": 1, "end_line": 1},
                    "dimension": "security",
                    "severity": 4,
                    "comment": "Direct int.",
                },
                {
                    "location": {"file_path": "b.py", "start_line": 2, "end_line": 2},
                    "dimension": "correctness",
                    "severity": "High",
                    "comment": "String severity.",
                },
            ]
        })
        findings = parse_reviewer_findings(response, "PR1", "test", usage=usage)
        assert len(findings) == 2
        assert usage.total_findings_parsed == 2
        assert usage.severity_coercions == 1
        assert usage.severity_coercion_rate == pytest.approx(0.5)

    def test_coercion_rate_zero_when_no_findings(self):
        """The rate should be 0.0 when no findings have been parsed."""
        usage = UsageRecord()
        assert usage.severity_coercion_rate == 0.0

    def test_medium_string_not_counted_as_failure(self):
        """'medium' genuinely means MEDIUM, so it's a coercion but not a failure."""
        usage = UsageRecord()
        response = self._make_response("medium")
        findings = parse_reviewer_findings(response, "PR1", "test", usage=usage)
        assert len(findings) == 1
        assert findings[0].severity == Severity.MEDIUM
        assert usage.severity_coercions == 1
        assert usage.severity_coercion_failures == 0


# --- Reporting data quality warning tests ------------------------------


class TestSeverityCoercionReportWarning:
    """Tests that the Markdown report includes a warning when coercion rate is high."""

    def test_warning_emitted_above_threshold(self):
        from pilot.reporting import format_markdown_report
        from pilot.schemas import MetricsReport

        report = MetricsReport(
            reviewer_model="test-model",
            judge_panel=["test-judge"],
            evaluation_set="test",
            n_prs=1,
            per_dimension=[],
            total_true_positives=0,
            total_false_positives=0,
            total_false_negatives=0,
            run_metadata={
                "severity_coercion_rate": "25.00%",
                "severity_coercion_count": "5",
            },
        )
        markdown = format_markdown_report(report)
        assert "Data Quality Warnings" in markdown
        assert "25.00%" in markdown
        assert "5 findings" in markdown

    def test_no_warning_below_threshold(self):
        from pilot.reporting import format_markdown_report
        from pilot.schemas import MetricsReport

        report = MetricsReport(
            reviewer_model="test-model",
            judge_panel=["test-judge"],
            evaluation_set="test",
            n_prs=1,
            per_dimension=[],
            total_true_positives=0,
            total_false_positives=0,
            total_false_negatives=0,
            run_metadata={
                "severity_coercion_rate": "10.00%",
                "severity_coercion_count": "2",
            },
        )
        markdown = format_markdown_report(report)
        assert "Data Quality Warnings" not in markdown

    def test_no_warning_when_no_coercion_metadata(self):
        from pilot.reporting import format_markdown_report
        from pilot.schemas import MetricsReport

        report = MetricsReport(
            reviewer_model="test-model",
            judge_panel=["test-judge"],
            evaluation_set="test",
            n_prs=1,
            per_dimension=[],
            total_true_positives=0,
            total_false_positives=0,
            total_false_negatives=0,
            run_metadata={},
        )
        markdown = format_markdown_report(report)
        assert "Data Quality Warnings" not in markdown
