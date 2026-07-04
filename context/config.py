"""Default configuration constants for context compaction."""

from pathlib import Path

WORKDIR = Path.cwd()
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"

CONTEXT_LIMIT = 50_000
KEEP_RECENT_TOOL_RESULTS = 3
KEEP_RECENT_MESSAGES = 50
PERSIST_THRESHOLD = 30_000
TOOL_RESULT_BUDGET = 200_000
MAX_REACTIVE_RETRIES = 1
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3
