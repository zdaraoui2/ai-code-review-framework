# AI Code Review Measurement Framework

## What this project is

A measurement framework for evaluating AI code review quality. Contains a 5,100-line framework specification, a reference implementation (Python), dataset adapters for 5 public benchmarks, and a Part 1 research paper.

## Setup

```bash
make install   # Creates venv, installs dependencies
make test      # Runs 78 tests
make data      # Clones and fetches all 5 benchmark datasets
make verify    # Runs the pipeline end-to-end on mock + real data
```

Or manually:
```bash
cd pilot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,benchmarks]"
python -m pytest tests/ -v
```

## Key commands

**Run on mock data (no API needed):**
```bash
python -m pilot.run --dataset fixtures/sample.jsonl
```

**Run on a real benchmark:**
```bash
python -m pilot.run --benchmark ccrab \
    --benchmark-path ../ccrab-dataset/results_preprocessed/preprocess_dataset.jsonl \
    --reviewer anthropic --judge openai \
    --max-prs 10 --name my-run
```

**Classify GT issues by dimension (needed before per-dimension metrics work):**
```bash
python -m pilot.dimension_pipeline classify \
    --benchmark ccrab --benchmark-path /path/to/data \
    --providers claude-code --models claude-opus-4-6 \
    --runs 3 --output classified/ccrab.jsonl
```

**Validate classifications against human spot-check:**
```bash
python -m pilot.dimension_pipeline validate \
    --classified classified/ccrab.jsonl \
    --human-labels spot-check/ccrab-50-labelled.jsonl
```

## Authentication

- `--providers claude-code` — uses the logged-in Claude Code session. No API key needed.
- `--reviewer anthropic` / `--judge openai` — needs `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` env vars.
- Cross-family evaluation: use one family as reviewer, a different family as judge.

## Architecture

All code is in `pilot/src/pilot/`. Key modules:

- `schemas.py` — the 15-dimension taxonomy, severity scale, and all data models
- `run.py` — CLI for running the benchmark (`python -m pilot.run`)
- `dimension_pipeline.py` — CLI for dimension classification (`python -m pilot.dimension_pipeline`)
- `classify.py` — AutoResearch iteration loop for prompt optimisation (`python -m pilot.classify`)
- `datasets/` — adapters for c-CRAB, SWE-PRBench, SWE-CARE, Greptile, Martian
- `api_adapters.py` — real Anthropic/OpenAI API adapters with structured output parsing
- `autoresearch.py` — iteration loop, LLM clients (ClaudeCodeLLM, AnthropicLLM, OpenAILLM, MockLLM)
- `panel.py` — multi-judge panel with majority vote
- `metrics.py` — precision, recall, F1, Wilson CIs, dimension classification accuracy
- `prompts.py` — reviewer and judge prompt templates
- `matching.py` — semantic matching between AI findings and ground truth
- `reporting.py` — JSON and Markdown report generation

## Supported benchmarks

- `--benchmark ccrab` — 410 PRs, Python, test-based GT. Needs `--benchmark-path`.
- `--benchmark swe-prbench` — 350 PRs, 5 languages. Auto-downloads from HuggingFace.
- `--benchmark swe-care` — 671 instances, Python + Java, 9 domains. Auto-downloads.
- `--benchmark greptile` — 50 PRs, 5 languages, real traced bugs. Needs `--benchmark-path` pointing to fetched JSONL.
- `--benchmark martian` — 50 PRs, 5 languages, severity labels. Needs `--benchmark-path`.
- `--benchmark all` — loads all available benchmarks as one evaluation set.

## Testing

```bash
python -m pytest pilot/tests/ -v     # All 78 tests
python -m pytest pilot/tests/test_ccrab.py  # c-CRAB adapter tests (needs dataset cloned)
```

## File conventions

- Framework specification: `framework/measurement_framework.md`
- Research paper: `paper/part1_paper.md`
- Literature review: `research/literature_review.md`
- Benchmark results go in `pilot/results/` (gitignored)
- Classified GT goes in `pilot/classified/` (gitignored)
- Raw benchmark data goes in `pilot/data/` (gitignored)
