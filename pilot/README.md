# Pilot: Framework Implementation

A reference implementation of the measurement framework. The pilot is deliberately small — 10 sample pull requests, one reviewer, one or two judges. Its purpose is to demonstrate that the framework specification is executable end-to-end and to expose any protocol gaps that only surface when the specification meets an actual engineering implementation.

## Quick start

```bash
cd pilot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,benchmarks]"

# Run in mock mode (uses fixtures, no API calls)
python -m pilot.run --dataset fixtures/sample.jsonl

# Run tests
python -m pytest tests/ -v
```

Outputs are written to `results/` as both JSON and Markdown.

For the full workflow — getting benchmark data, classifying dimensions, and running benchmarks — see the [main README](../README.md#quick-start).

## Authentication

Three options, no configuration files needed:

**Claude Code (no API key needed):**
```bash
python -m pilot.run --benchmark ccrab \
    --benchmark-path /path/to/data \
    --reviewer claude-code --judge claude-code
```

**Anthropic API key:**
```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
python -m pilot.run --reviewer anthropic --judge anthropic
```

**OpenAI API key:**
```bash
export OPENAI_API_KEY=sk-proj-...
python -m pilot.run --judge openai
```

For cross-family evaluation (recommended — judge with a different model family than the reviewer):

```bash
python -m pilot.run --dataset fixtures/sample.jsonl \
    --reviewer anthropic --judge openai
```

### Running with a judge panel

```bash
# Multi-family judge panel (complies with the model family exclusion rule)
python -m pilot.run --dataset fixtures/sample.jsonl \
    --reviewer anthropic \
    --judge anthropic,openai \
    --judge-models claude-opus-4-6,gpt-4o

# Custom reviewer model
python -m pilot.run --dataset fixtures/sample.jsonl \
    --reviewer anthropic --reviewer-model claude-sonnet-4-6 \
    --judge mock
```

## Module overview

| Module | Purpose |
|---|---|
| `schemas.py` | Pydantic models for the 15-dimension taxonomy, 4-level severity, change types, and metrics report |
| `data.py` | JSONL loaders for pull requests, mock reviewer findings, and mock judge matches |
| `prompts.py` | System and user prompt templates for reviewer and judge tasks |
| `reviewer.py` | Abstract `Reviewer` interface with `MockReviewer` |
| `judge.py` | Abstract `Judge` interface with `MockJudge` |
| `api_adapters.py` | Real API implementations: `AnthropicReviewer`, `AnthropicJudge`, `OpenAIJudge` |
| `panel.py` | `JudgePanel` with majority vote aggregation |
| `matching.py` | Semantic matching between findings and ground truth |
| `metrics.py` | Precision, recall, F1 per dimension with Wilson score confidence intervals, and dimension classification accuracy |
| `reporting.py` | JSON and Markdown report generators |
| `run.py` | Command-line orchestration |
| `autoresearch.py` | AutoResearch iteration loop for prompt optimisation |
| `classify.py` | Dimension classifier CLI (AutoResearch-powered) |
| `dimension_pipeline.py` | Multi-run consensus classification pipeline |
| `datasets/` | Public benchmark adapters (c-CRAB, SWE-PRBench, SWE-CARE, Greptile, Martian) |

## Framework mapping

| Framework section | Implementation |
|---|---|
| S2 Dimensions (15) | `schemas.Dimension` enum with `TIER_1/2/3` sets |
| S3 Change types (6) | `schemas.ChangeType` enum |
| S4.1 Core metrics | `metrics.compute_metrics` — precision, recall, F1 per dimension |
| S4.2.1 Severity (1-4) | `schemas.Severity` enum |
| S4.2.4 Dimension classification accuracy | Computed by `compute_metrics`, reported by `format_markdown_report` |
| S4.3 False positive adjudication | Unmatched findings tracked in `MatchingOutcome`; full adjudication protocol is future work |
| S6 Sycophancy testing | Future work; requires adversarial test case construction and human difficulty calibration |
| S8.1 Judge panel | `panel.JudgePanel` with majority vote |
| S8.3.1 Issue-match task | `api_adapters.AnthropicJudge.match_findings_to_ground_truth` |
| S8.5 Prompt templates | `prompts.build_reviewer_prompt`, `prompts.build_judge_match_prompt` |
| S9.1 Wilson CIs | `metrics.wilson_interval` |
| S9.6 Reproducibility | Temperature 0, pinned model versions via CLI arguments |
| S9.7 Reporting template | `reporting.format_markdown_report` |
| S10 Multi-model experiment | Future work; requires running multiple reviewers under controlled conditions |

## Scope and non-goals

**In scope.** The end-to-end data path from pull requests through to the final report: loading, reviewer invocation, judge panel invocation, semantic matching, per-dimension metrics with confidence intervals, and the reporting template.

**Not in scope.** The false positive adjudication protocol, the sycophancy testing protocol, and the multi-model experiment protocol. These are larger components of the framework and are scoped separately from the reference implementation.

The pilot does not validate the judge against human assessments and does not evaluate real-world tool performance. Those are empirical studies that build on the framework; the pilot only demonstrates the framework's executability.
