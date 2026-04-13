.PHONY: install test data verify classify benchmark clean help

VENV = pilot/.venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
CCRAB_PATH = ccrab-dataset/results_preprocessed/preprocess_dataset.jsonl
MARTIAN_REPO = martian-repo

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: $(VENV) ## Set up Python environment and install dependencies
$(VENV):
	cd pilot && python3 -m venv .venv
	$(PIP) install -e "pilot/.[dev,benchmarks]"

test: install ## Run all tests
	$(PYTHON) -m pytest pilot/tests/ -v

data: data-ccrab data-martian data-greptile ## Fetch all benchmark datasets

data-ccrab: ## Clone c-CRAB dataset
	@if [ ! -d ccrab-dataset ]; then \
		git clone --depth 1 https://github.com/c-CRAB-Benchmark/dataset.git ccrab-dataset; \
	else \
		echo "c-CRAB already cloned"; \
	fi

data-martian: ## Fetch Martian benchmark data
	@if [ ! -d $(MARTIAN_REPO) ]; then \
		git clone --depth 1 https://github.com/withmartian/code-review-benchmark.git $(MARTIAN_REPO); \
	fi
	@if [ ! -f pilot/data/martian.jsonl ]; then \
		mkdir -p pilot/data && \
		$(PYTHON) pilot/scripts/fetch_martian.py --repo $(MARTIAN_REPO) --output pilot/data/martian.jsonl; \
	else \
		echo "Martian data already fetched"; \
	fi

data-greptile: data-martian ## Fetch Greptile benchmark data (depends on Martian repo)
	@if [ ! -f pilot/data/greptile.jsonl ]; then \
		mkdir -p pilot/data && \
		$(PYTHON) pilot/scripts/fetch_greptile.py --martian-repo $(MARTIAN_REPO) --output pilot/data/greptile.jsonl; \
	else \
		echo "Greptile data already fetched"; \
	fi

verify: install data-ccrab ## Verify the pipeline works end-to-end
	$(PYTHON) -m pilot.run --dataset pilot/fixtures/sample.jsonl
	$(PYTHON) -m pilot.run --benchmark ccrab \
		--benchmark-path $(CCRAB_PATH) --max-prs 3

classify: install data-ccrab ## Run dimension classifier on c-CRAB (small test)
	$(PYTHON) -m pilot.dimension_pipeline classify \
		--benchmark ccrab \
		--benchmark-path $(CCRAB_PATH) \
		--providers claude-code --models claude-opus-4-6 \
		--runs 3 --max-prs 5 \
		--output pilot/classified/ccrab-test.jsonl

classify-full: install data-ccrab ## Run dimension classifier on full c-CRAB
	$(PYTHON) -m pilot.dimension_pipeline classify \
		--benchmark ccrab \
		--benchmark-path $(CCRAB_PATH) \
		--providers claude-code --models claude-opus-4-6 \
		--runs 3 \
		--output pilot/classified/ccrab.jsonl

benchmark: install data-ccrab ## Run the benchmark (requires API keys or Claude Code)
	$(PYTHON) -m pilot.run --benchmark ccrab \
		--benchmark-path $(CCRAB_PATH) \
		--reviewer anthropic --reviewer-model claude-opus-4-6 \
		--judge openai --judge-models gpt-4o \
		--name ccrab-opus

clean: ## Remove virtual environment and generated data
	rm -rf $(VENV) pilot/results/ pilot/classified/
