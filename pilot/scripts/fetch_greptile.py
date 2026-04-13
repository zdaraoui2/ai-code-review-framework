#!/usr/bin/env python3
"""Fetch Greptile benchmark data and assemble into JSONL for the pilot framework.

This script produces a JSONL file matching the schema expected by the Greptile
adapter at pilot/src/pilot/datasets/greptile.py.

Data sources:
    1. Bug descriptions: from the withmartian/code-review-benchmark golden
       comments (which are expanded annotations of the same 50 Greptile PRs).
    2. PR diffs: fetched from the ai-code-review-evaluation GitHub org forks
       (same diffs across all tool forks).
    3. Severity levels: Greptile's original severity labels from their
       benchmark page, hardcoded below. The Martian annotations use slightly
       different severity assessments; we prefer Greptile's originals since
       this is the Greptile benchmark.

The 50 PRs are spread across 5 repos (10 each):
    - Sentry (Python), Cal.com (TypeScript), Grafana (Go),
      Keycloak (Java), Discourse (Ruby)

Usage:
    # Let the script clone the Martian repo for golden comments:
    python fetch_greptile.py --clone-to /tmp/martian-bench \\
                             --output greptile_benchmark.jsonl

    # Or use an existing clone:
    python fetch_greptile.py --repo-path /path/to/code-review-benchmark \\
                             --output greptile_benchmark.jsonl

Requirements:
    - gh CLI authenticated at /opt/homebrew/bin/gh
    - Network access to GitHub API

JSONL output schema (per line, matching greptile.py adapter):
    {
        "pr_id": "sentry-1",
        "repo": "sentry",
        "language": "python",
        "title": "Enhanced Pagination Performance for High-Volume Audit Logs",
        "diff": "--- a/file.py\\n+++ b/file.py\\n...",
        "bugs": [
            {
                "description": "Django querysets do not support negative slicing",
                "file_path": "unknown",
                "start_line": 1,
                "end_line": 1,
                "severity": "high"
            }
        ]
    }

Note on file_path / line numbers:
    The Greptile benchmark does not publish per-bug file paths or line
    numbers. Neither do the Martian golden comments. The adapter handles
    missing locations gracefully (defaults file_path to "unknown",
    start_line to 1). If you have file-level annotations, add them to the
    output JSONL manually or with a separate enrichment script.
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

# ── Repository metadata ──────────────────────────────────────────────

REPO_LANGUAGE: dict[str, str] = {
    "sentry": "python",
    "grafana": "go",
    "keycloak": "java",
    "discourse": "ruby",
    "calcom": "typescript",
}

# Maps golden comment filenames to canonical repo short names.
GOLDEN_COMMENT_FILES: dict[str, str] = {
    "sentry.json": "sentry",
    "grafana.json": "grafana",
    "keycloak.json": "keycloak",
    "discourse.json": "discourse",
    "cal_dot_com.json": "calcom",
}

# Canonical fork org for fetching diffs. All forks under
# ai-code-review-evaluation have identical PRs/diffs.
FORK_ORG = "ai-code-review-evaluation"

# Fork repo names per canonical repo. We use the copilot forks because
# their PRs are open (easier to fetch diffs).
FORK_REPOS: dict[str, str] = {
    "sentry": "sentry-copilot",
    "grafana": "grafana-copilot",
    "keycloak": "keycloak-copilot",
    "discourse": "discourse-copilot",
    "calcom": "cal.com-copilot",
}

# ── Greptile severity labels ──────────────────────────────────────────
#
# These are the severity levels published on greptile.com/benchmarks.
# They assign ONE primary bug per PR. The Martian golden comments have
# richer multi-bug annotations; we use Martian for descriptions but
# override the primary bug's severity with Greptile's label.
#
# Format: GREPTILE_SEVERITIES[repo_name][fork_pr_number] = severity
# These were scraped from the benchmark page (sentry tab visible,
# other tabs loaded dynamically).

GREPTILE_PRIMARY_BUGS: dict[str, dict[int, dict]] = {
    "sentry": {
        1: {"description": "Importing non-existent OptimizedCursorPaginator", "severity": "high"},
        2: {"description": "Negative offset cursor manipulation bypasses pagination boundaries", "severity": "critical"},
        3: {"description": "sample_rate = 0.0 is falsy and skipped", "severity": "low"},
        4: {"description": "Null reference if github_authenticated_user state is missing", "severity": "critical"},
        5: {"description": "Breaking changes in error response format", "severity": "critical"},
        6: {"description": "Inconsistent metric tagging with 'shard' and 'shards'", "severity": "medium"},
        7: {"description": "Shared mutable default in dataclass timestamp", "severity": "medium"},
        8: {"description": "Using stale config variable instead of updated one", "severity": "high"},
        9: {"description": "Invalid queue.ShutDown exception handling", "severity": "high"},
        10: {"description": "Incomplete implementation (only contains pass)", "severity": "high"},
    },
    # Cal.com, Grafana, Keycloak, Discourse: Greptile's page loads these
    # dynamically via JS. The descriptions below are from the benchmark
    # page (cross-referenced with the Martian golden comments).
    # Severities are from Greptile's published results.
    #
    # If you have access to the rendered page data, update these.
    # Otherwise the Martian golden comment severities are used as
    # fallback (see _build_bugs()).
}

# Seconds to wait between GitHub API calls.
API_DELAY_SECONDS = 1.0

# Maximum retries on transient errors.
MAX_RETRIES = 3


# ── GitHub API helpers ────────────────────────────────────────────────


def gh_api(endpoint: str, *, accept: str | None = None) -> str:
    """Call the GitHub REST API via gh CLI. Returns raw response body.

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

        # Rate limit.
        if "rate limit" in stderr.lower() or "403" in stderr:
            wait = 30 * attempt
            log.warning(
                "Rate limited on %s. Waiting %ds before retry.", endpoint, wait
            )
            time.sleep(wait)
            continue

        # 404 -- not retryable.
        if "404" in stderr or "Not Found" in stderr:
            log.warning("404 for %s -- resource not found.", endpoint)
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

        log.error(
            "gh api failed after %d attempts for %s: %s",
            MAX_RETRIES,
            endpoint,
            stderr[:300],
        )
        return ""

    return ""


def fetch_pr_diff(owner: str, repo: str, pr_number: int) -> str:
    """Fetch the unified diff for a pull request."""
    endpoint = f"/repos/{owner}/{repo}/pulls/{pr_number}"
    return gh_api(endpoint, accept="application/vnd.github.v3.diff")


def fetch_commit_diff(owner: str, repo: str, sha: str) -> str:
    """Fetch the unified diff for a single commit."""
    endpoint = f"/repos/{owner}/{repo}/commits/{sha}"
    return gh_api(endpoint, accept="application/vnd.github.v3.diff")


# ── URL parsing ──────────────────────────────────────────────────────

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


# ── Golden comment loading ────────────────────────────────────────────


def load_golden_comments(golden_dir: Path) -> dict[str, list[dict]]:
    """Load golden comments from the Martian repo, grouped by repo name.

    Returns {repo_name: [list of PR entry dicts]}.
    """
    result: dict[str, list[dict]] = {}
    for filename, repo_name in GOLDEN_COMMENT_FILES.items():
        filepath = golden_dir / filename
        if not filepath.exists():
            log.warning("Golden comments file missing: %s", filepath)
            continue

        with filepath.open() as f:
            data = json.load(f)

        log.info("Loaded %d entries from %s", len(data), filename)
        result[repo_name] = data

    return result


# ── Fork PR mapping ──────────────────────────────────────────────────

# Cache of {fork_repo: {title: pr_number}} populated lazily.
_fork_pr_map: dict[str, dict[str, int]] = {}


def _fetch_fork_pr_list(fork_repo: str) -> dict[str, int]:
    """Fetch the list of PRs for a fork repo, returning {title: number}.

    Cached to avoid repeated API calls.
    """
    if fork_repo in _fork_pr_map:
        return _fork_pr_map[fork_repo]

    endpoint = f"/repos/{FORK_ORG}/{fork_repo}/pulls?state=all&per_page=30"
    log.info("Fetching PR list for %s/%s", FORK_ORG, fork_repo)
    raw = gh_api(endpoint)
    if not raw:
        log.warning("Could not fetch PR list for %s", fork_repo)
        _fork_pr_map[fork_repo] = {}
        return {}

    try:
        prs = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Invalid JSON from PR list for %s", fork_repo)
        _fork_pr_map[fork_repo] = {}
        return {}

    title_map = {pr["title"]: pr["number"] for pr in prs}
    _fork_pr_map[fork_repo] = title_map
    log.info("Found %d PRs in %s/%s", len(title_map), FORK_ORG, fork_repo)
    return title_map


def _determine_fork_pr_number(entry: dict, repo_name: str, index: int) -> int | None:
    """Determine the PR number on the ai-code-review-evaluation fork.

    The golden comments have inconsistent URL structures:
    - Some point to the fork (ai-code-review-evaluation/*-greptile/pull/N)
    - Some point to the upstream repo (getsentry/sentry/pull/NNNNN)
    - Discourse entries sometimes use commit URLs

    Strategy:
    1. If the golden comment URL points to the fork org, use that number.
    2. Match by title against the fork repo's PR list.
    3. Fall back to 1-based index (unreliable -- logs a warning).
    """
    url = entry.get("url", "")

    # 1. Direct fork URL.
    parsed = parse_pr_url(url)
    if parsed and parsed[0] == "ai-code-review-evaluation":
        return parsed[2]

    # 2. Title match against the fork repo's PR list.
    fork_repo = FORK_REPOS.get(repo_name)
    if fork_repo:
        title = entry.get("pr_title", "")
        pr_map = _fetch_fork_pr_list(fork_repo)
        if title in pr_map:
            return pr_map[title]

    # 3. Fallback (may be wrong if PRs aren't perfectly ordered).
    log.warning(
        "Could not determine fork PR number for %s entry %d (%s). "
        "Falling back to index+1=%d.",
        repo_name,
        index,
        entry.get("pr_title", "?")[:40],
        index + 1,
    )
    return index + 1


def fetch_diff_for_entry(
    entry: dict,
    repo_name: str,
    index: int,
    diff_cache: dict[str, str],
) -> str:
    """Fetch the diff for a golden comment entry.

    Strategy:
    1. Try the canonical fork (ai-code-review-evaluation/*-copilot).
       These are the actual benchmark PRs and always have the right diff.
    2. If the fork doesn't have the PR, try the upstream URL (original_url
       or url) as a fallback.
    3. If original_url is a commit URL, fetch the commit diff.
    """
    fork_repo = FORK_REPOS.get(repo_name)
    fork_pr = _determine_fork_pr_number(entry, repo_name, index)

    # 1. Try the canonical fork.
    if fork_repo and fork_pr is not None:
        cache_key = f"{FORK_ORG}/{fork_repo}/pull/{fork_pr}"
        if cache_key in diff_cache:
            log.debug("Cache hit: %s", cache_key)
            return diff_cache[cache_key]

        log.info("Fetching diff: %s/%s#%d", FORK_ORG, fork_repo, fork_pr)
        diff = fetch_pr_diff(FORK_ORG, fork_repo, fork_pr)
        diff_cache[cache_key] = diff
        if diff:
            return diff
        log.warning("Empty diff from fork %s#%d, trying upstream.", fork_repo, fork_pr)

    # 2. Try upstream PR URL.
    for url_key in ("original_url", "url"):
        url = entry.get(url_key, "")
        if not url:
            continue

        parsed = parse_pr_url(url)
        if parsed and parsed[0] != "ai-code-review-evaluation":
            cache_key = f"{parsed[0]}/{parsed[1]}/pull/{parsed[2]}"
            if cache_key in diff_cache:
                return diff_cache[cache_key]

            log.info("Fetching upstream diff: %s/%s#%d", *parsed)
            diff = fetch_pr_diff(*parsed)
            diff_cache[cache_key] = diff
            if diff:
                return diff

    # 3. Try commit URL.
    original_url = entry.get("original_url", "")
    if original_url:
        parsed = parse_commit_url(original_url)
        if parsed:
            cache_key = f"{parsed[0]}/{parsed[1]}/commit/{parsed[2]}"
            if cache_key in diff_cache:
                return diff_cache[cache_key]

            log.info("Fetching commit diff: %s/%s@%s", parsed[0], parsed[1], parsed[2][:12])
            diff = fetch_commit_diff(*parsed)
            diff_cache[cache_key] = diff
            if diff:
                return diff

    log.warning("Could not fetch diff for %s entry %d", repo_name, index)
    return ""


# ── Bug construction ─────────────────────────────────────────────────


def _build_bugs(
    comments: list[dict],
    repo_name: str,
    fork_pr: int | None,
) -> list[dict]:
    """Convert Martian golden comments into the Greptile adapter's bug schema.

    The Greptile adapter expects:
        {
            "description": str,
            "file_path": str,
            "start_line": int,
            "end_line": int,
            "severity": str  (critical/high/medium/low)
        }

    Since neither Greptile nor Martian publish file paths or line numbers,
    we set file_path to "unknown" and lines to 1. The adapter handles this
    gracefully.

    Severity: if we have a Greptile primary bug label for this PR, the
    first matching comment gets that severity. All others use the Martian
    severity (lowercased).
    """
    greptile_primary = None
    if repo_name in GREPTILE_PRIMARY_BUGS and fork_pr is not None:
        greptile_primary = GREPTILE_PRIMARY_BUGS[repo_name].get(fork_pr)

    bugs: list[dict] = []
    primary_matched = False

    for c in comments:
        comment_text = c.get("comment", "").strip()
        if not comment_text:
            continue

        severity = c.get("severity", "Medium").lower()

        # Check if this comment matches the Greptile primary bug.
        if greptile_primary and not primary_matched:
            # Fuzzy match: check if the Greptile description appears in or
            # substantially overlaps with the Martian comment.
            greptile_desc = greptile_primary["description"].lower()
            if (
                greptile_desc in comment_text.lower()
                or comment_text.lower() in greptile_desc
                or _fuzzy_overlap(greptile_desc, comment_text.lower())
            ):
                severity = greptile_primary["severity"]
                primary_matched = True

        bugs.append({
            "description": comment_text,
            "file_path": "unknown",
            "start_line": 1,
            "end_line": 1,
            "severity": severity,
        })

    return bugs


def _fuzzy_overlap(a: str, b: str, threshold: float = 0.6) -> bool:
    """Check whether two strings share enough words to be considered a match."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b)
    return overlap / min(len(words_a), len(words_b)) >= threshold


# ── PR ID derivation ─────────────────────────────────────────────────


def derive_pr_id(repo_name: str, fork_pr: int | None, index: int) -> str:
    """Build a pr_id for the Greptile adapter.

    Uses the fork PR number (1-10) which is the natural Greptile
    benchmark identifier.
    """
    if fork_pr is not None:
        return f"{repo_name}-{fork_pr}"
    return f"{repo_name}-{index + 1}"


# ── Assembly ─────────────────────────────────────────────────────────


def assemble_entry(
    entry: dict,
    repo_name: str,
    index: int,
    diff_cache: dict[str, str],
) -> dict | None:
    """Convert a golden comment entry into a Greptile JSONL record."""
    comments = entry.get("comments", [])
    if not comments:
        log.debug("Skipping %s entry %d: no comments", repo_name, index)
        return None

    fork_pr = _determine_fork_pr_number(entry, repo_name, index)
    pr_id = derive_pr_id(repo_name, fork_pr, index)
    title = entry.get("pr_title", f"PR {pr_id}")
    language = REPO_LANGUAGE.get(repo_name, "unknown")

    # Fetch the diff.
    diff = fetch_diff_for_entry(entry, repo_name, index, diff_cache)
    time.sleep(API_DELAY_SECONDS)

    if not diff:
        log.warning("Empty diff for %s -- will include entry without diff", pr_id)

    # Build bugs array.
    bugs = _build_bugs(comments, repo_name, fork_pr)
    if not bugs:
        log.warning("No bugs extracted for %s", pr_id)
        return None

    return {
        "pr_id": pr_id,
        "repo": repo_name,
        "language": language,
        "title": title,
        "diff": diff,
        "bugs": bugs,
    }


# ── Clone helper ─────────────────────────────────────────────────────


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


# ── Main pipeline ────────────────────────────────────────────────────


def run(
    repo_path: Path,
    output_path: Path,
    *,
    skip_existing: bool = True,
) -> None:
    """Main pipeline: load golden comments, fetch diffs, write JSONL."""
    golden_dir = repo_path / "offline" / "golden_comments"

    if not golden_dir.is_dir():
        log.error("Golden comments directory not found: %s", golden_dir)
        sys.exit(1)

    # Load golden comments grouped by repo.
    all_comments = load_golden_comments(golden_dir)
    total_entries = sum(len(entries) for entries in all_comments.values())
    log.info("Loaded %d total entries across %d repos", total_entries, len(all_comments))

    # Load already-fetched pr_ids for resume support.
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

    diff_cache: dict[str, str] = {}
    mode = "a" if done_ids else "w"
    succeeded = 0
    failed = 0
    entry_num = 0

    with output_path.open(mode) as out:
        for repo_name in ("sentry", "calcom", "grafana", "keycloak", "discourse"):
            entries = all_comments.get(repo_name, [])
            if not entries:
                log.warning("No entries for %s", repo_name)
                continue

            log.info("--- Processing %s (%d entries) ---", repo_name, len(entries))

            for i, entry in enumerate(entries):
                entry_num += 1
                fork_pr = _determine_fork_pr_number(entry, repo_name, i)
                pr_id = derive_pr_id(repo_name, fork_pr, i)

                if pr_id in done_ids:
                    log.debug("Skipping %s -- already fetched", pr_id)
                    succeeded += 1
                    continue

                log.info(
                    "[%d/%d] %s: %s",
                    entry_num,
                    total_entries,
                    pr_id,
                    entry.get("pr_title", "?")[:60],
                )

                record = assemble_entry(entry, repo_name, i, diff_cache)
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

    _print_summary(output_path)


def _print_summary(output_path: Path) -> None:
    """Print a summary of the assembled JSONL file."""
    if not output_path.exists():
        return

    total = 0
    with_diff = 0
    by_repo: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    total_bugs = 0

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
            for b in rec.get("bugs", []):
                total_bugs += 1
                sev = b.get("severity", "unknown")
                by_severity[sev] = by_severity.get(sev, 0) + 1

    print("\n--- Greptile benchmark summary ---")
    print(f"Total PRs:           {total}")
    print(f"PRs with diff:       {with_diff}")
    print(f"PRs without diff:    {total - with_diff}")
    print(f"Total bugs:          {total_bugs}")
    print(f"By repo:             {json.dumps(by_repo, indent=2)}")
    print(f"By severity:         {json.dumps(by_severity, indent=2)}")
    print("---")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Greptile benchmark data and assemble into JSONL.",
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
        default=Path("greptile_benchmark.jsonl"),
        help="Output JSONL file path (default: greptile_benchmark.jsonl).",
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
