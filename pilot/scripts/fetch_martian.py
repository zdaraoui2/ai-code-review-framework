#!/usr/bin/env python3
"""Fetch Martian benchmark data and assemble into JSONL for the pilot framework.

This script reads golden comments from the withmartian/code-review-benchmark
repository, fetches PR diffs from GitHub, and writes a JSONL file matching
the schema expected by the Martian adapter's jsonl_path mode.

Usage:
    # Clone the Martian repo first, then run:
    python fetch_martian.py --repo-path /path/to/code-review-benchmark \
                            --output martian_benchmark.jsonl

    # Or let the script clone it for you:
    python fetch_martian.py --clone-to /tmp/martian-bench \
                            --output martian_benchmark.jsonl

Requirements:
    - gh CLI authenticated at /opt/homebrew/bin/gh
    - Network access to GitHub API

JSONL output schema (per line):
    {
        "pr_id": "keycloak-37429",
        "repo": "keycloak",
        "language": "java",
        "title": "Add HTML sanitizer for translated message resources",
        "diff": "--- a/file.java\\n+++ b/file.java\\n...",
        "original_url": "https://github.com/keycloak/keycloak/pull/37429",
        "change_type": "feature",
        "comments": [
            {"comment": "Description of the issue", "severity": "High"}
        ]
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

GH = os.environ.get("GH_CLI", "/opt/homebrew/bin/gh")

# Maps golden comment filenames to canonical repo short names.
REPO_FILENAMES: dict[str, str] = {
    "sentry.json": "sentry",
    "grafana.json": "grafana",
    "keycloak.json": "keycloak",
    "discourse.json": "discourse",
    "cal_dot_com.json": "calcom",
}

REPO_LANGUAGE: dict[str, str] = {
    "sentry": "python",
    "grafana": "go",
    "keycloak": "java",
    "discourse": "ruby",
    "calcom": "typescript",
}

# Seconds to wait between GitHub API calls to stay well under rate limits.
API_DELAY_SECONDS = 1.0

# Maximum retries on transient errors (rate limit, server error).
MAX_RETRIES = 3


# ── GitHub API helpers ──────────────────────────────────────────────


def gh_api(endpoint: str, *, accept: str | None = None) -> str:
    """Call the GitHub REST API via gh cli. Returns raw response body.

    Retries on 403 (rate limit) and 5xx with exponential backoff.
    """
    cmd = [GH, "api", endpoint]
    if accept:
        cmd.extend(["-H", f"Accept: {accept}"])

    for attempt in range(1, MAX_RETRIES + 1):
        log.debug("gh api %s (attempt %d)", endpoint, attempt)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return result.stdout

        stderr = result.stderr.strip()

        # Rate limit -- look for 403 or "rate limit" in the error message.
        if "rate limit" in stderr.lower() or "403" in stderr:
            wait = 30 * attempt
            log.warning(
                "Rate limited on %s. Waiting %ds before retry.", endpoint, wait
            )
            time.sleep(wait)
            continue

        # 404 -- not retryable.
        if "404" in stderr or "Not Found" in stderr:
            log.warning("404 for %s — resource not found.", endpoint)
            return ""

        # 5xx or other transient -- retry with backoff.
        if attempt < MAX_RETRIES:
            wait = 5 * attempt
            log.warning(
                "gh api error (attempt %d/%d) for %s: %s. Retrying in %ds.",
                attempt,
                MAX_RETRIES,
                endpoint,
                stderr[:200],
                wait,
            )
            time.sleep(wait)
            continue

        log.error("gh api failed after %d attempts for %s: %s", MAX_RETRIES, endpoint, stderr[:300])
        return ""

    return ""


def fetch_pr_diff(owner: str, repo: str, pr_number: int) -> str:
    """Fetch the unified diff for a pull request."""
    endpoint = f"/repos/{owner}/{repo}/pulls/{pr_number}"
    diff = gh_api(endpoint, accept="application/vnd.github.v3.diff")
    return diff


def fetch_commit_diff(owner: str, repo: str, sha: str) -> str:
    """Fetch the unified diff for a single commit."""
    endpoint = f"/repos/{owner}/{repo}/commits/{sha}"
    diff = gh_api(endpoint, accept="application/vnd.github.v3.diff")
    return diff


# ── URL parsing ─────────────────────────────────────────────────────


_PR_URL_RE = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)"
)
_COMMIT_URL_RE = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/commit/(?P<sha>[0-9a-f]+)"
)


def parse_pr_url(url: str) -> tuple[str, str, int] | None:
    """Extract (owner, repo, pr_number) from a GitHub PR URL."""
    m = _PR_URL_RE.search(url)
    if m:
        return m.group("owner"), m.group("repo"), int(m.group("number"))
    return None


def parse_commit_url(url: str) -> tuple[str, str, str] | None:
    """Extract (owner, repo, sha) from a GitHub commit URL."""
    m = _COMMIT_URL_RE.search(url)
    if m:
        return m.group("owner"), m.group("repo"), m.group("sha")
    return None


# ── Diff resolution strategy ───────────────────────────────────────


def resolve_diff_source(entry: dict) -> dict:
    """Determine the best URL to fetch the diff from.

    The golden comment files have inconsistent URL structures:
    - Some entries have both `url` (fork) and `original_url` (upstream).
    - Some have only `url` pointing directly at the upstream repo.
    - Discourse entries use commit URLs in `original_url`.

    Strategy:
    1. If original_url is a PR URL, use that (upstream is preferred).
    2. If url is a PR URL on the real repo (not ai-code-review-evaluation), use it.
    3. If original_url is a commit URL, fetch the commit diff.
    4. If url is a PR URL on ai-code-review-evaluation fork, try that.
    5. Otherwise, give up.

    Returns dict with keys: type ("pr"|"commit"|"none"), owner, repo,
    number/sha, source_url.
    """
    original_url = entry.get("original_url", "")
    url = entry.get("url", "")

    # 1. original_url as PR
    if original_url:
        parsed = parse_pr_url(original_url)
        if parsed:
            return {
                "type": "pr",
                "owner": parsed[0],
                "repo": parsed[1],
                "number": parsed[2],
                "source_url": original_url,
            }

    # 2. url on a real (non-fork) repo
    if url:
        parsed = parse_pr_url(url)
        if parsed and parsed[0] != "ai-code-review-evaluation":
            return {
                "type": "pr",
                "owner": parsed[0],
                "repo": parsed[1],
                "number": parsed[2],
                "source_url": url,
            }

    # 3. original_url as commit
    if original_url:
        parsed = parse_commit_url(original_url)
        if parsed:
            return {
                "type": "commit",
                "owner": parsed[0],
                "repo": parsed[1],
                "sha": parsed[2],
                "source_url": original_url,
            }

    # 4. url on ai-code-review-evaluation fork (last resort)
    if url:
        parsed = parse_pr_url(url)
        if parsed:
            return {
                "type": "pr",
                "owner": parsed[0],
                "repo": parsed[1],
                "number": parsed[2],
                "source_url": url,
            }

    return {"type": "none", "source_url": url or original_url}


# ── PR ID derivation ───────────────────────────────────────────────


def derive_pr_id(entry: dict, repo_name: str, index: int) -> str:
    """Build a stable pr_id from the entry's URL.

    Priority:
    1. original_url PR number (upstream is most stable).
    2. url PR number on a non-fork repo.
    3. Commit sha from original_url (discourse uses these).
    4. url PR number on a fork repo (last resort).
    5. repo-index fallback.
    """
    original_url = entry.get("original_url", "")
    url = entry.get("url", "")

    # 1. original_url as upstream PR.
    if original_url:
        parsed = parse_pr_url(original_url)
        if parsed:
            return f"{repo_name}-{parsed[2]}"

    # 2. url on a non-fork repo.
    if url:
        parsed = parse_pr_url(url)
        if parsed and parsed[0] != "ai-code-review-evaluation":
            return f"{repo_name}-{parsed[2]}"

    # 3. Commit-based entries (discourse): use short sha.
    if original_url:
        parsed = parse_commit_url(original_url)
        if parsed:
            return f"{repo_name}-{parsed[2][:8]}"

    # 4. Fork PR number -- use the fork's PR number as suffix.
    #    These are small sequential numbers (1-10) so prefix with "fork"
    #    to avoid collisions with upstream PR numbers.
    if url:
        parsed = parse_pr_url(url)
        if parsed:
            return f"{repo_name}-f{parsed[2]}"

    return f"{repo_name}-{index}"


# ── Golden comment loading ──────────────────────────────────────────


def load_golden_comments(golden_dir: Path) -> list[dict]:
    """Load all golden comment entries from the Martian repo.

    Returns a flat list of dicts, each representing one PR with its
    repo_name attached.
    """
    entries = []
    for filename, repo_name in REPO_FILENAMES.items():
        filepath = golden_dir / filename
        if not filepath.exists():
            log.warning("Golden comments file missing: %s", filepath)
            continue

        with filepath.open() as f:
            data = json.load(f)

        log.info("Loaded %d entries from %s", len(data), filename)
        for entry in data:
            entry["_repo_name"] = repo_name
        entries.extend(data)

    return entries


def load_pr_labels(results_dir: Path) -> dict:
    """Load pr_labels.json for metadata enrichment."""
    labels_path = results_dir / "pr_labels.json"
    if not labels_path.exists():
        log.warning("pr_labels.json not found at %s", labels_path)
        return {}

    with labels_path.open() as f:
        return json.load(f)


# ── Assembly ────────────────────────────────────────────────────────


def assemble_entry(
    entry: dict,
    index: int,
    pr_labels: dict,
    diff_cache: dict[str, str],
) -> dict | None:
    """Convert a golden comment entry into a JSONL record.

    Fetches the diff from GitHub if not already cached.
    Returns None if the entry has no comments.
    """
    repo_name = entry["_repo_name"]
    comments = entry.get("comments", [])
    if not comments:
        log.debug("Skipping entry %d (%s): no comments", index, repo_name)
        return None

    pr_id = derive_pr_id(entry, repo_name, index)
    title = entry.get("pr_title", f"PR from {repo_name}")
    language = REPO_LANGUAGE.get(repo_name, "unknown")

    # Resolve where to fetch the diff from.
    source = resolve_diff_source(entry)

    # Fetch diff (with caching to avoid re-fetching duplicates).
    cache_key = source.get("source_url", "")
    diff = ""
    if cache_key and cache_key in diff_cache:
        diff = diff_cache[cache_key]
        log.debug("Cache hit for %s", cache_key)
    elif source["type"] == "pr":
        log.info(
            "Fetching PR diff: %s/%s#%d",
            source["owner"],
            source["repo"],
            source["number"],
        )
        diff = fetch_pr_diff(source["owner"], source["repo"], source["number"])
        if cache_key:
            diff_cache[cache_key] = diff
        time.sleep(API_DELAY_SECONDS)
    elif source["type"] == "commit":
        log.info(
            "Fetching commit diff: %s/%s@%s",
            source["owner"],
            source["repo"],
            source["sha"][:12],
        )
        diff = fetch_commit_diff(source["owner"], source["repo"], source["sha"])
        if cache_key:
            diff_cache[cache_key] = diff
        time.sleep(API_DELAY_SECONDS)
    else:
        log.warning("No fetchable URL for %s (entry %d)", pr_id, index)

    if not diff:
        log.warning("Empty diff for %s — PR may be closed/deleted", pr_id)

    # Look up metadata from pr_labels.json.
    # Labels are keyed by the `url` field in golden comments.
    url = entry.get("url", "")
    original_url = entry.get("original_url", "")
    labels = pr_labels.get(url, {}) or pr_labels.get(original_url, {})
    llm_labels = labels.get("llm_pr_labels", {})
    derived = labels.get("derived", {})

    # Use language from pr_labels if available (more reliable).
    if derived.get("language"):
        language = derived["language"].lower()

    change_type = llm_labels.get("change_type", "")

    # Build the JSONL record matching the adapter's expected schema.
    record = {
        "pr_id": pr_id,
        "repo": repo_name,
        "language": language,
        "title": title,
        "diff": diff,
        "original_url": original_url or url,
        "change_type": change_type,
        "comments": [
            {
                "comment": c.get("comment", ""),
                "severity": c.get("severity", "Medium"),
            }
            for c in comments
            if c.get("comment", "").strip()
        ],
    }

    return record


# ── Main ────────────────────────────────────────────────────────────


def clone_martian_repo(dest: Path) -> Path:
    """Clone the Martian benchmark repo if not already present."""
    if (dest / "offline" / "golden_comments").is_dir():
        log.info("Martian repo already present at %s", dest)
        return dest

    log.info("Cloning withmartian/code-review-benchmark to %s ...", dest)
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "https://github.com/withmartian/code-review-benchmark.git",
            str(dest),
        ],
        check=True,
        timeout=120,
    )
    return dest


def run(
    repo_path: Path,
    output_path: Path,
    *,
    skip_existing: bool = True,
) -> None:
    """Main pipeline: load golden comments, fetch diffs, write JSONL."""
    golden_dir = repo_path / "offline" / "golden_comments"
    results_dir = repo_path / "offline" / "results"

    if not golden_dir.is_dir():
        log.error("Golden comments directory not found: %s", golden_dir)
        sys.exit(1)

    # Load golden comments and metadata.
    entries = load_golden_comments(golden_dir)
    pr_labels = load_pr_labels(results_dir)
    log.info(
        "Loaded %d golden comment entries, %d pr_labels keys",
        len(entries),
        len(pr_labels),
    )

    # If output file already exists and skip_existing is set, load
    # already-fetched pr_ids to avoid re-fetching.
    done_ids: set[str] = set()
    if skip_existing and output_path.exists():
        with output_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("diff"):
                        done_ids.add(rec["pr_id"])
                except json.JSONDecodeError:
                    continue
        log.info("Resuming: %d entries already fetched", len(done_ids))

    # Diff cache avoids re-fetching the same URL within a single run
    # (relevant when both url and original_url might reference the same PR).
    diff_cache: dict[str, str] = {}

    # Open output file in append mode for resume support.
    mode = "a" if done_ids else "w"
    succeeded = 0
    failed = 0

    with output_path.open(mode) as out:
        for i, entry in enumerate(entries):
            repo_name = entry["_repo_name"]
            pr_id = derive_pr_id(entry, repo_name, i)

            if pr_id in done_ids:
                log.debug("Skipping %s — already fetched", pr_id)
                succeeded += 1
                continue

            log.info(
                "[%d/%d] Processing %s: %s",
                i + 1,
                len(entries),
                pr_id,
                entry.get("pr_title", "?")[:60],
            )

            record = assemble_entry(entry, i, pr_labels, diff_cache)
            if record is None:
                failed += 1
                continue

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            succeeded += 1

    log.info(
        "Done. %d entries written to %s (%d skipped/failed)",
        succeeded,
        output_path,
        failed,
    )

    # Print summary statistics.
    _print_summary(output_path)


def _print_summary(output_path: Path) -> None:
    """Print a quick summary of the assembled JSONL file."""
    if not output_path.exists():
        return

    total = 0
    with_diff = 0
    by_repo: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    total_comments = 0

    with output_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            total += 1
            if rec.get("diff"):
                with_diff += 1
            repo = rec.get("repo", "unknown")
            by_repo[repo] = by_repo.get(repo, 0) + 1
            for c in rec.get("comments", []):
                total_comments += 1
                sev = c.get("severity", "Unknown")
                by_severity[sev] = by_severity.get(sev, 0) + 1

    print("\n--- Martian benchmark summary ---")
    print(f"Total PRs:           {total}")
    print(f"PRs with diff:       {with_diff}")
    print(f"PRs without diff:    {total - with_diff}")
    print(f"Total comments:      {total_comments}")
    print(f"By repo:             {json.dumps(by_repo, indent=2)}")
    print(f"By severity:         {json.dumps(by_severity, indent=2)}")
    print("---")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Martian benchmark data and assemble into JSONL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--repo-path",
        type=Path,
        help="Path to an existing clone of withmartian/code-review-benchmark.",
    )
    source.add_argument(
        "--clone-to",
        type=Path,
        help="Clone the Martian repo to this directory (shallow clone).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("martian_benchmark.jsonl"),
        help="Output JSONL file path (default: martian_benchmark.jsonl).",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Don't skip already-fetched entries; overwrite the output file.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=API_DELAY_SECONDS,
        help=f"Seconds between API calls (default: {API_DELAY_SECONDS}).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    global API_DELAY_SECONDS
    API_DELAY_SECONDS = args.delay

    if args.clone_to:
        repo_path = clone_martian_repo(args.clone_to)
    else:
        repo_path = args.repo_path
        if not (repo_path / "offline" / "golden_comments").is_dir():
            log.error(
                "%s does not look like the Martian repo "
                "(missing offline/golden_comments/).",
                repo_path,
            )
            sys.exit(1)

    run(repo_path, args.output, skip_existing=not args.no_resume)


if __name__ == "__main__":
    main()
