#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path


APPLY_DELETE_LOCAL_MERGED = "delete-local-merged-branches"
APPLY_DELETE_LOCAL_PATCH_EQUIVALENT = "delete-local-patch-equivalent-branches"
WORKTREE_SAFE_TO_REMOVE_LIVENESS = {"stale", "unknown"}

# Hours during which agents are expected to be active.
# Outside this window (11pm–8am) elapsed time is not counted toward recency.
ACTIVE_HOUR_START = 8   # 8:00am
ACTIVE_HOUR_END   = 23  # 11:00pm

# A worktree whose last activity falls within this many active-hours seconds
# is considered recently active and warrants user confirmation before any action.
RECENTLY_ACTIVE_THRESHOLD_S = 2 * 3600  # 2 active hours

# How many calendar days back to scan for session logs.
SESSION_SCAN_DAYS = 4

LAUNCH_WORK_LOG_REL = Path("launch-work") / "log.md"
LAUNCH_WORK_LEGACY_LOG_REL = Path(".launch-work") / "log.md"
LAUNCH_WORK_HEADER_RE = re.compile(
    r"<!--\s*launch-work-log\s*\n"
    r"last-updated:\s*(?P<last_updated>[^\n]+)\n"
    r"checkpoint:\s*(?P<checkpoint>[^\n]+)\n"
    r"-->",
    re.MULTILINE,
)


def _launch_work_log_path(worktree_path: Path) -> Path | None:
    """Locate the launch-work log under the worktree's git-dir, falling back
    to the legacy in-tree path. Returns None if neither exists."""
    if not worktree_path.is_dir():
        return None
    git_dir_proc = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if git_dir_proc.returncode == 0:
        primary = Path(git_dir_proc.stdout.strip()) / LAUNCH_WORK_LOG_REL
        if primary.is_file():
            return primary
    legacy = worktree_path / LAUNCH_WORK_LEGACY_LOG_REL
    if legacy.is_file():
        return legacy
    return None


def scan_launch_work_log(worktree_path: Path) -> dict[str, object] | None:
    log_path = _launch_work_log_path(worktree_path)
    if log_path is None:
        return None
    try:
        body = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = LAUNCH_WORK_HEADER_RE.search(body)
    if not match:
        return {"present": True, "last_updated": "", "checkpoint": ""}
    return {
        "present": True,
        "last_updated": match.group("last_updated").strip(),
        "checkpoint": match.group("checkpoint").strip(),
    }


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def git_stdout(*args: str, cwd: Path) -> str:
    return git(*args, cwd=cwd).stdout.strip()


def try_git_stdout(*args: str, cwd: Path) -> str | None:
    result = git(*args, cwd=cwd, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def ref_exists(ref: str, cwd: Path) -> bool:
    return git("show-ref", "--verify", ref, cwd=cwd, check=False).returncode == 0


def detect_repo_root(cwd: Path) -> Path:
    return Path(git_stdout("rev-parse", "--show-toplevel", cwd=cwd)).resolve()


def detect_primary_branch(cwd: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    origin_head = try_git_stdout(
        "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD",
        cwd=cwd,
    )
    if origin_head:
        return origin_head.removeprefix("origin/"), warnings

    warnings.append("origin/HEAD unavailable; primary branch detected from local refs")
    for candidate in ("main", "master"):
        if ref_exists(f"refs/heads/{candidate}", cwd) or ref_exists(
            f"refs/remotes/origin/{candidate}", cwd,
        ):
            return candidate, warnings

    current_branch = git_stdout("branch", "--show-current", cwd=cwd)
    if current_branch:
        warnings.append("fell back to the current branch because no primary branch ref was found")
        return current_branch, warnings

    raise RuntimeError("unable to detect primary branch")


def prune_missing_worktrees(cwd: Path) -> list[str]:
    """Run `git worktree prune --verbose` and return its reported lines.

    Worktree directories left over from interrupted runs (e.g. land-work
    previews under /tmp) cause every per-worktree probe to crash with
    FileNotFoundError when subprocess.run is given a missing cwd. Pruning
    once at scan start removes these registrations before any probe runs.
    """
    result = git("worktree", "prune", "--verbose", cwd=cwd, check=False)
    if result.returncode != 0:
        return []
    # `git worktree prune --verbose` reports prunes on stderr in git >= 2.20.
    output = (result.stdout or "") + (result.stderr or "")
    return [line.strip() for line in output.splitlines() if line.strip()]


def parse_worktrees_raw(cwd: Path) -> list[dict[str, object]]:
    raw = git_stdout("worktree", "list", "--porcelain", cwd=cwd)
    worktrees: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for line in raw.splitlines():
        if not line:
            if current:
                worktrees.append(current)
                current = None
            continue

        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.removeprefix("worktree ")}
            continue

        if current is None:
            continue

        key, _, value = line.partition(" ")
        if key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif key == "HEAD":
            current["head"] = value
        elif key == "detached":
            current["detached"] = True
        elif key == "locked":
            current["locked"] = value or True
        elif key == "prunable":
            current["prunable"] = value or True

    if current:
        worktrees.append(current)

    return worktrees


def local_branches(cwd: Path) -> list[str]:
    raw = git_stdout("for-each-ref", "--format=%(refname:short)", "refs/heads", cwd=cwd)
    return [line for line in raw.splitlines() if line]


def branch_merged_into_primary(branch: str, primary_branch: str, cwd: Path) -> bool:
    if branch == primary_branch:
        return True
    result = git("merge-base", "--is-ancestor", branch, primary_branch, cwd=cwd, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or f"merge-base failed for branch {branch}")
    return result.returncode == 0


def branch_unique_patch_count(branch: str, primary_branch: str, cwd: Path) -> int:
    if branch == primary_branch:
        return 0
    raw = git_stdout("cherry", primary_branch, branch, cwd=cwd)
    return sum(1 for line in raw.splitlines() if line.startswith("+"))


def ahead_behind(branch: str, primary_branch: str, cwd: Path) -> tuple[int, int]:
    raw = git_stdout("rev-list", "--left-right", "--count", f"{primary_branch}...{branch}", cwd=cwd)
    behind_str, ahead_str = raw.split()
    return int(behind_str), int(ahead_str)


def working_tree_entries(cwd: Path) -> list[dict[str, str]]:
    raw = git_stdout("status", "--porcelain=v1", "--untracked-files=all", cwd=cwd)
    entries: list[dict[str, str]] = []
    for line in raw.splitlines():
        path = line[3:] if len(line) > 2 and line[2] == " " else line[2:]
        entries.append({"status": line[:2], "path": path, "raw": line})
    return entries


def stash_entries(cwd: Path) -> list[dict[str, str]]:
    raw = git_stdout("stash", "list", cwd=cwd)
    entries: list[dict[str, str]] = []
    for line in raw.splitlines():
        ref, _, summary = line.partition(":")
        entries.append({"ref": ref, "summary": summary.strip()})
    return entries


# ---------------------------------------------------------------------------
# Overnight-aware activity timing
# ---------------------------------------------------------------------------

def active_seconds_elapsed(
    last_ts: float,
    now_ts: float | None = None,
    inactive_start_hour: int = ACTIVE_HOUR_END,
    inactive_end_hour: int = ACTIVE_HOUR_START,
) -> float:
    """
    Elapsed seconds since last_ts, counting only active hours (8am–11pm local
    time by default).  The overnight window (11pm–8am) is excluded so that
    activity at 10:45pm and a check at 8:15am produces ~30 active minutes, not
    ~9.5 hours.

    Example: last_ts = 10:45pm, now = 8:15am next morning
      - 10:45pm → 11:00pm = 15 active minutes
      - 11:00pm → 8:00am = inactive, not counted
      - 8:00am  → 8:15am = 15 active minutes
      - total = 30 active minutes
    """
    if now_ts is None:
        now_ts = time.time()

    last = datetime.fromtimestamp(last_ts).astimezone()
    now  = datetime.fromtimestamp(now_ts).astimezone()

    if last >= now:
        return 0.0

    total = 0.0
    cursor = last

    while cursor < now:
        h = cursor.hour + cursor.minute / 60.0 + cursor.second / 3600.0

        if h < inactive_end_hour:
            # Before active window — jump to start of active window today
            cursor = cursor.replace(
                hour=inactive_end_hour, minute=0, second=0, microsecond=0
            )
            continue

        if h >= inactive_start_hour:
            # Past active window — jump to start of active window tomorrow
            tomorrow = (cursor + timedelta(days=1)).date()
            cursor = datetime(
                tomorrow.year, tomorrow.month, tomorrow.day,
                inactive_end_hour, 0, 0, tzinfo=cursor.tzinfo,
            )
            continue

        # Within active window — accumulate to min(now, end of active window today)
        end_of_active = cursor.replace(
            hour=inactive_start_hour, minute=0, second=0, microsecond=0
        )
        segment_end = min(now, end_of_active)
        total += (segment_end - cursor).total_seconds()
        cursor = segment_end

    return total


# ---------------------------------------------------------------------------
# Per-worktree last-activity timestamp
# ---------------------------------------------------------------------------

def worktree_activity_ts(
    worktree_path: Path,
    dirty_entries: list[dict[str, str]],
) -> tuple[float, str]:
    """
    Return (timestamp, source) for the most recent known activity in the
    worktree.  Checks:
      - HEAD commit timestamp (git log -1 --format=%ct)
      - mtime of each tracked file with uncommitted changes

    Untracked files (status '??') are excluded — they add noise and may
    predate the current agent run.  Note: on WSL, file mtimes can be
    unreliable for files written from the Windows side.

    source is one of: 'commit', 'file_mtime', 'missing'
    """
    if not worktree_path.is_dir():
        return 0.0, "missing"
    raw_ts = try_git_stdout("log", "-1", "--format=%ct", "HEAD", cwd=worktree_path)
    commit_ts = float(raw_ts) if raw_ts else 0.0
    best_ts = commit_ts
    best_source = "commit"

    for entry in dirty_entries:
        status = entry.get("status", "")
        if status.startswith("??"):
            continue  # untracked
        file_path = worktree_path / entry["path"]
        try:
            mtime = file_path.stat().st_mtime
            if mtime > best_ts:
                best_ts = mtime
                best_source = "file_mtime"
        except OSError:
            pass

    return best_ts, best_source


# ---------------------------------------------------------------------------
# Session log scanning — Codex
# ---------------------------------------------------------------------------

def _codex_session_dir() -> Path:
    return Path.home() / ".codex" / "sessions"


def scan_codex_sessions(worktree_path: Path) -> dict[str, object] | None:
    """
    Scan ~/.codex/sessions/YYYY/MM/DD/*.jsonl for sessions whose cwd matches
    worktree_path (exact match or subdirectory).  Returns metadata for the most
    recently active matching session, or None.
    """
    base = _codex_session_dir()
    if not base.exists():
        return None

    target = str(worktree_path.resolve())
    best: dict[str, object] | None = None
    best_ts: float = 0.0

    today = datetime.now()
    for delta in range(SESSION_SCAN_DAYS):
        day = today - timedelta(days=delta)
        day_dir = base / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        if not day_dir.is_dir():
            continue

        for jsonl_file in day_dir.glob("*.jsonl"):
            try:
                meta = _codex_session_meta(jsonl_file)
            except Exception:
                continue
            if meta is None:
                continue

            cwd = meta.get("cwd", "")
            if not (cwd == target or cwd.startswith(target + "/")):
                continue

            last_ts = _jsonl_last_timestamp(jsonl_file)
            if last_ts > best_ts:
                best_ts = last_ts
                best = {
                    "session_log": str(jsonl_file),
                    "session_id": meta.get("id"),
                    "session_start_iso": meta.get("timestamp"),
                    "session_cwd": cwd,
                    "last_event_ts": last_ts,
                    "last_event_iso": datetime.fromtimestamp(last_ts).isoformat()
                    if last_ts else None,
                }

    return best


def _codex_session_meta(jsonl_file: Path) -> dict[str, object] | None:
    with jsonl_file.open() as f:
        first_line = f.readline().strip()
    if not first_line:
        return None
    obj = json.loads(first_line)
    if obj.get("type") != "session_meta":
        return None
    return obj.get("payload", {})


def _jsonl_last_timestamp(jsonl_file: Path) -> float:
    """Return the most recent ISO timestamp found in any line of a JSONL file."""
    last_ts = 0.0
    with jsonl_file.open(errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                for key in ("timestamp", "createdAt"):
                    ts_str = obj.get(key)
                    if ts_str and isinstance(ts_str, str):
                        try:
                            ts = datetime.fromisoformat(
                                ts_str.replace("Z", "+00:00")
                            ).timestamp()
                            if ts > last_ts:
                                last_ts = ts
                        except ValueError:
                            pass
                snap = obj.get("snapshot", {})
                if isinstance(snap, dict):
                    ts_str = snap.get("timestamp")
                    if ts_str and isinstance(ts_str, str):
                        try:
                            ts = datetime.fromisoformat(
                                ts_str.replace("Z", "+00:00")
                            ).timestamp()
                            if ts > last_ts:
                                last_ts = ts
                        except ValueError:
                            pass
            except Exception:
                pass
    return last_ts


# ---------------------------------------------------------------------------
# Session log scanning — Claude Code
# ---------------------------------------------------------------------------

def _encode_claude_project_path(path: Path) -> str:
    """
    Encode an absolute path into the directory name used by Claude Code under
    ~/.claude/projects/.  Example: /home/user/project/foo → -home-user-project-foo
    """
    return str(path).replace("/", "-")


def scan_claude_sessions(worktree_path: Path) -> dict[str, object] | None:
    """
    Scan ~/.claude/projects/<encoded-path>/*.jsonl for Claude Code sessions
    associated with this worktree.  Returns metadata for the most recently
    modified JSONL, or None.

    Claude Code session files do not carry a cwd field; the project directory
    name encodes the path.  Whether the session is still open cannot be
    determined from file content alone — session_still_open is always null.
    """
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return None

    encoded = _encode_claude_project_path(worktree_path.resolve())
    project_dir = base / encoded
    if not project_dir.is_dir():
        return None

    best_file: Path | None = None
    best_mtime: float = 0.0

    for jsonl_file in project_dir.glob("*.jsonl"):
        try:
            mtime = jsonl_file.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best_file = jsonl_file
        except OSError:
            pass

    if best_file is None:
        return None

    last_ts = _jsonl_last_timestamp(best_file) or best_mtime

    return {
        "session_log": str(best_file),
        "project_dir": str(project_dir),
        "last_event_ts": last_ts,
        "last_event_iso": datetime.fromtimestamp(last_ts).isoformat(),
        # Claude Code JSONL format has no terminal-event marker; cannot determine
        # whether the session process is still running from file content alone.
        "session_still_open": None,
    }


# ---------------------------------------------------------------------------
# Self-invocation detection
# ---------------------------------------------------------------------------

# Defensive bound on the PPID walk; init is pid 1.
ANCESTOR_WALK_LIMIT = 64


def caller_ancestor_cwds() -> list[Path]:
    """
    Return the resolved cwd of every ancestor process up the PPID chain.

    Used to detect when the agent driving this helper is living inside one
    of the scanned worktrees — e.g. a Claude/Codex process whose cwd is the
    worktree, with a bash subshell and the helper as descendants. /proc is
    Linux-specific; returns an empty list elsewhere or on permission errors.
    """
    proc = Path("/proc")
    if not proc.exists():
        return []

    cwds: list[Path] = []
    pid = os.getppid()
    seen: set[int] = set()
    for _ in range(ANCESTOR_WALK_LIMIT):
        if pid <= 1 or pid in seen:
            break
        seen.add(pid)
        pid_dir = proc / str(pid)
        try:
            cwds.append((pid_dir / "cwd").resolve())
        except (PermissionError, FileNotFoundError, OSError):
            pass
        try:
            status = (pid_dir / "status").read_text(errors="replace")
        except (PermissionError, FileNotFoundError, OSError):
            break
        next_pid: int | None = None
        for line in status.splitlines():
            if line.startswith("PPid:"):
                try:
                    next_pid = int(line.split()[1])
                except (IndexError, ValueError):
                    next_pid = None
                break
        if next_pid is None:
            break
        pid = next_pid
    return cwds


def detect_self_invocation(worktree_path: Path, caller_cwds: list[Path]) -> bool:
    target = worktree_path.resolve()
    target_str = str(target)
    for caller in caller_cwds:
        caller_str = str(caller)
        if caller_str == target_str or caller_str.startswith(target_str + "/"):
            return True
    return False


# ---------------------------------------------------------------------------
# Process liveness detection
# ---------------------------------------------------------------------------

def scan_process_liveness(worktree_path: Path) -> list[dict[str, object]]:
    """
    Check /proc/*/cwd for running processes whose working directory is inside
    worktree_path.  Returns a list of {pid, cmdline, cwd} entries.
    Returns an empty list if /proc is unavailable or no matches are found.
    """
    results: list[dict[str, object]] = []
    proc = Path("/proc")
    if not proc.exists():
        return results

    target = str(worktree_path.resolve())

    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            cwd = (pid_dir / "cwd").resolve()
            cwd_str = str(cwd)
            if not (cwd_str == target or cwd_str.startswith(target + "/")):
                continue
            cmdline_raw = (pid_dir / "cmdline").read_bytes()
            cmdline = cmdline_raw.replace(b"\x00", b" ").decode(errors="replace").strip()
            results.append({"pid": int(pid_dir.name), "cmdline": cmdline, "cwd": cwd_str})
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            pass

    return results


# ---------------------------------------------------------------------------
# Liveness assessment synthesis
# ---------------------------------------------------------------------------

def assess_liveness(
    worktree_path: Path,
    last_activity_ts: float,
    activity_source: str,
    codex_session: dict[str, object] | None,
    claude_session: dict[str, object] | None,
    live_processes: list[dict[str, object]],
    now_ts: float | None = None,
) -> dict[str, object]:
    """
    Synthesise all available signals into a structured liveness assessment.

    Verdict values:
      confirmed_live   — a process with this worktree as CWD is running right now
      possibly_live    — recent activity (< threshold) AND a session log exists,
                         suggesting an agent may be mid-run or waiting for input
      recently_active  — activity within threshold but no corroborating session log
      stale            — session log exists but activity is old; no live process
      unknown          — no session evidence, no process; only git/file timestamps

    Important limitation: an agent blocked waiting for user input may show no
    file or commit activity for many hours while still running.  confirmed_live
    (live process) is the only signal that reliably distinguishes this case.
    All other verdicts are probabilistic and should be presented as such.
    """
    if now_ts is None:
        now_ts = time.time()

    active_secs = active_seconds_elapsed(last_activity_ts, now_ts)

    signals: dict[str, object] = {
        "active_seconds_since_activity": round(active_secs),
        "last_activity_source": activity_source,
        "last_activity_ts": round(last_activity_ts) if last_activity_ts else None,
        "last_activity_iso": datetime.fromtimestamp(last_activity_ts).isoformat()
        if last_activity_ts else None,
        "codex_session_last_event_ts": codex_session.get("last_event_ts")
        if codex_session else None,
        "claude_session_last_event_ts": claude_session.get("last_event_ts")
        if claude_session else None,
        "live_process_count": len(live_processes),
    }

    has_session = bool(codex_session or claude_session)
    is_recent = active_secs < RECENTLY_ACTIVE_THRESHOLD_S

    if live_processes:
        verdict = "confirmed_live"
    elif is_recent and has_session:
        verdict = "possibly_live"
    elif is_recent:
        verdict = "recently_active"
    elif has_session:
        verdict = "stale"
    else:
        verdict = "unknown"

    return {
        "verdict": verdict,
        "signals": signals,
        "codex_session": codex_session,
        "claude_session": claude_session,
        "live_processes": live_processes,
    }


# ---------------------------------------------------------------------------
# Branch classification
# ---------------------------------------------------------------------------

def classify_branches(
    branch_names: list[str],
    primary_branch: str,
    current_branch: str,
    checked_out_in_worktrees: set[str],
    cwd: Path,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for branch in branch_names:
        merged_into_primary = branch_merged_into_primary(branch, primary_branch, cwd)
        unique_patch_count = branch_unique_patch_count(branch, primary_branch, cwd)
        behind_primary, ahead_primary = ahead_behind(branch, primary_branch, cwd)
        checked_out_elsewhere = branch in checked_out_in_worktrees
        current = branch == current_branch

        # Merge status is evaluated before worktree-checkout status so that a
        # branch that is both merged AND checked out appears as merged_checked_out
        # rather than being hidden inside checked_out_in_worktree.  The agent
        # needs to see "work is landed; worktree is a cleanup candidate" as a
        # distinct signal from "work is in progress in a worktree".
        if branch == primary_branch:
            classification = "primary"
        elif current:
            classification = "review_required"
        elif merged_into_primary:
            classification = "merged_checked_out" if checked_out_elsewhere else "safe_to_delete"
        elif unique_patch_count == 0:
            classification = (
                "checked_out_in_worktree"
                if checked_out_elsewhere
                else "patch_equivalent_review"
            )
        elif checked_out_elsewhere:
            classification = "checked_out_in_worktree"
        else:
            classification = "review_required"

        reasons: list[str] = []
        if merged_into_primary and branch != primary_branch:
            reasons.append("fully_merged_into_primary")
        if unique_patch_count == 0 and branch != primary_branch:
            reasons.append("no_unique_patches_vs_primary")
        if checked_out_elsewhere:
            reasons.append("checked_out_in_worktree")
        if current:
            reasons.append("current_branch")

        records.append(
            {
                "name": branch,
                "current": current,
                "checked_out_in_worktree": checked_out_elsewhere,
                "merged_into_primary": merged_into_primary,
                "unique_patch_count": unique_patch_count,
                "ahead_of_primary": ahead_primary,
                "behind_primary": behind_primary,
                "classification": classification,
                "reasons": reasons,
            }
        )

    return records


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def build_summary(
    branches: list[dict[str, object]],
    worktrees: list[dict[str, object]],
    stashes: list[dict[str, str]],
    working_tree: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "safe_to_delete_local_branches": [
            b["name"] for b in branches if b["classification"] == "safe_to_delete"
        ],
        "merged_checked_out_local_branches": [
            b["name"] for b in branches if b["classification"] == "merged_checked_out"
        ],
        "patch_equivalent_local_branches": [
            b["name"] for b in branches if b["classification"] == "patch_equivalent_review"
        ],
        "checked_out_local_branches": [
            b["name"] for b in branches if b["classification"] == "checked_out_in_worktree"
        ],
        "local_branches_requiring_review": [
            b["name"] for b in branches if b["classification"] == "review_required"
        ],
        "worktree_count": len(worktrees),
        "stash_count": len(stashes),
        "working_tree_dirty": bool(working_tree),
    }


# ---------------------------------------------------------------------------
# Apply mode
# ---------------------------------------------------------------------------

def removable_merged_worktree_reason(worktree: dict[str, object], current_checkout: Path) -> str | None:
    path = Path(str(worktree["path"])).resolve()
    if worktree.get("self_invocation"):
        return (
            "self-invocation: helper invoked from inside this worktree; "
            "use land-work for own-work cleanup, not closure"
        )
    if path == current_checkout.resolve():
        return "worktree is the current checkout"
    if worktree.get("detached"):
        return "worktree is detached"
    if worktree.get("working_tree_dirty"):
        return "worktree has uncommitted changes"
    launch_work = worktree.get("launch_work")
    if isinstance(launch_work, dict):
        checkpoint = str(launch_work.get("checkpoint") or "")
        if checkpoint and checkpoint != "ready-to-land":
            return f"launch-work log in flight (checkpoint={checkpoint})"
    liveness = worktree.get("liveness")
    if not isinstance(liveness, dict):
        return "liveness assessment unavailable"
    verdict = liveness.get("verdict")
    if verdict not in WORKTREE_SAFE_TO_REMOVE_LIVENESS:
        return f"worktree liveness is {verdict}"
    return None


def apply_delete_merged_checked_out_worktrees(
    branches: list[dict[str, object]],
    worktrees: list[dict[str, object]],
    cwd: Path,
    target_branch: str | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    applied: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    branch_worktrees: dict[str, list[dict[str, object]]] = {}

    for worktree in worktrees:
        branch = worktree.get("branch")
        if branch:
            branch_worktrees.setdefault(str(branch), []).append(worktree)

    for branch in branches:
        if branch["classification"] != "merged_checked_out":
            continue
        if target_branch is not None and str(branch["name"]) != target_branch:
            continue

        branch_name = str(branch["name"])
        checkout_records = branch_worktrees.get(branch_name, [])
        if not checkout_records:
            skipped.append(
                {
                    "action": "delete_local_branch",
                    "branch": branch_name,
                    "reason": "no registered worktree found for merged_checked_out branch",
                }
            )
            continue

        blocked = False
        for worktree in checkout_records:
            reason = removable_merged_worktree_reason(worktree, cwd)
            if reason is None:
                continue
            blocked = True
            skipped.append(
                {
                    "action": "delete_worktree",
                    "branch": branch_name,
                    "worktree": str(worktree["path"]),
                    "reason": reason,
                }
            )

        if blocked:
            skipped.append(
                {
                    "action": "delete_local_branch",
                    "branch": branch_name,
                    "reason": "branch still checked out in a retained worktree",
                }
            )
            continue

        remove_failed = False
        for worktree in checkout_records:
            worktree_path = str(worktree["path"])
            result = git("worktree", "remove", worktree_path, cwd=cwd, check=False)
            if result.returncode == 0:
                applied.append(
                    {
                        "action": "delete_worktree",
                        "branch": branch_name,
                        "worktree": worktree_path,
                    }
                )
                continue

            remove_failed = True
            skipped.append(
                {
                    "action": "delete_worktree",
                    "branch": branch_name,
                    "worktree": worktree_path,
                    "reason": result.stderr.strip() or "git worktree remove failed",
                }
            )

        if remove_failed:
            skipped.append(
                {
                    "action": "delete_local_branch",
                    "branch": branch_name,
                    "reason": "worktree removal failed",
                }
            )
            continue

        result = git("branch", "-d", branch_name, cwd=cwd, check=False)
        if result.returncode == 0:
            applied.append({"action": "delete_local_branch", "branch": branch_name})
            continue

        skipped.append(
            {
                "action": "delete_local_branch",
                "branch": branch_name,
                "reason": result.stderr.strip() or "git branch -d failed",
            }
        )

    return applied, skipped

def apply_delete_local_merged_branches(
    branches: list[dict[str, object]],
    worktrees: list[dict[str, object]],
    cwd: Path,
    target_branch: str | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    applied: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for branch in branches:
        if branch["classification"] != "safe_to_delete":
            continue
        branch_name = str(branch["name"])
        if target_branch is not None and branch_name != target_branch:
            continue

        result = git("branch", "-d", branch_name, cwd=cwd, check=False)
        if result.returncode == 0:
            applied.append({"action": "delete_local_branch", "branch": branch_name})
            continue

        skipped.append(
            {
                "action": "delete_local_branch",
                "branch": branch_name,
                "reason": result.stderr.strip() or "git branch -d failed",
            }
        )

    merged_applied, merged_skipped = apply_delete_merged_checked_out_worktrees(
        branches, worktrees, cwd, target_branch=target_branch
    )
    applied.extend(merged_applied)
    skipped.extend(merged_skipped)

    if target_branch is not None and not applied and not skipped:
        target_record = next(
            (b for b in branches if str(b["name"]) == target_branch), None
        )
        classification = (
            str(target_record["classification"]) if target_record else "missing"
        )
        skipped.append(
            {
                "action": "delete_local_branch",
                "branch": target_branch,
                "reason": (
                    f"target branch classification {classification!r} is not eligible "
                    "for delete-local-merged-branches"
                ),
            }
        )

    return applied, skipped


def apply_delete_patch_equivalent_branches(
    branches: list[dict[str, object]],
    cwd: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """
    Force-delete local branches classified as patch_equivalent_review.

    These branches have no unique patches relative to primary but were not
    merged via a merge commit (rebased or squash-merged), so git's ancestry
    check returns false and `git branch -d` would refuse them.  `git branch -D`
    is safe here because unique_patch_count == 0 guarantees all content is
    already on the primary branch.
    """
    applied: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for branch in branches:
        if branch["classification"] != "patch_equivalent_review":
            continue

        branch_name = str(branch["name"])
        result = git("branch", "-D", branch_name, cwd=cwd, check=False)
        if result.returncode == 0:
            applied.append({"action": "delete_local_branch", "branch": branch_name})
            continue

        skipped.append(
            {
                "action": "delete_local_branch",
                "branch": branch_name,
                "reason": result.stderr.strip() or "git branch -D failed",
            }
        )

    return applied, skipped


# ---------------------------------------------------------------------------
# Branch correlation (review_required triage signals)
# ---------------------------------------------------------------------------

TRACKER_BEADS = "beads"
TRACKER_GH = "gh"
TRACKER_JIRA = "jira"
TRACKER_NONE = "none"
TRACKER_CHOICES = (TRACKER_BEADS, TRACKER_GH, TRACKER_JIRA, TRACKER_NONE, "auto")

DEFAULT_PATTERNS = {
    TRACKER_BEADS: r"([a-z]+-[a-z0-9]+)",
    TRACKER_JIRA:  r"([A-Z]+-[0-9]+)",
    TRACKER_GH:    r"#?([0-9]+)",
}


def default_issue_pattern(tracker: str) -> str | None:
    return DEFAULT_PATTERNS.get(tracker)


def extract_issue_id(branch_name: str, pattern: str) -> str | None:
    if not pattern:
        return None
    match = re.search(pattern, branch_name)
    if not match:
        return None
    if match.groups():
        return match.group(1)
    return match.group(0)


def gh_cli_available() -> bool:
    return shutil.which("gh") is not None


def detect_tracker(
    repo_root: Path,
    env: dict[str, str] | None = None,
    gh_available: bool | None = None,
) -> str:
    env = os.environ if env is None else env
    if (repo_root / ".beads").is_dir():
        return TRACKER_BEADS
    if all(env.get(k) for k in ("JIRA_BASE_URL", "JIRA_API_TOKEN", "JIRA_USER_EMAIL")):
        return TRACKER_JIRA
    if (repo_root / ".github").is_dir():
        if gh_cli_available() if gh_available is None else gh_available:
            return TRACKER_GH
    return TRACKER_NONE


def parse_cherry(branch: str, primary: str, cwd: Path) -> tuple[int, int]:
    """Return (unique_count, equivalent_count) from `git cherry primary branch`."""
    if branch == primary:
        return 0, 0
    raw = git_stdout("cherry", primary, branch, cwd=cwd)
    unique = 0
    equivalent = 0
    for line in raw.splitlines():
        if line.startswith("+"):
            unique += 1
        elif line.startswith("-"):
            equivalent += 1
    return unique, equivalent


def merge_base_age_days(branch: str, primary: str, cwd: Path) -> int:
    base = try_git_stdout("merge-base", primary, branch, cwd=cwd)
    if not base:
        return 0
    raw = try_git_stdout("log", "-1", "--format=%ct", base, cwd=cwd)
    if not raw:
        return 0
    age_seconds = max(0, time.time() - float(raw))
    return int(age_seconds // 86400)


def merge_base_iso_date(branch: str, primary: str, cwd: Path) -> str | None:
    base = try_git_stdout("merge-base", primary, branch, cwd=cwd)
    if not base:
        return None
    raw = try_git_stdout("log", "-1", "--format=%cI", base, cwd=cwd)
    return raw or None


def commits_referencing_issue_on_main(
    issue_id: str,
    primary: str,
    since_iso: str | None,
    cwd: Path,
) -> list[str]:
    args = ["log", primary, "--format=%h", f"--grep={issue_id}", "--fixed-strings"]
    if since_iso:
        args.append(f"--since={since_iso}")
    raw = try_git_stdout(*args, cwd=cwd)
    if not raw:
        return []
    return [line for line in raw.splitlines() if line]


def lookup_beads_status(issue_id: str) -> str | None:
    if not shutil.which("bd"):
        return None
    result = subprocess.run(
        ["bd", "show", issue_id, "--json"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    try:
        obj = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    status = obj.get("status") if isinstance(obj, dict) else None
    return str(status) if status else None


def lookup_gh_status(issue_id: str) -> str | None:
    if not shutil.which("gh"):
        return None
    number = issue_id.lstrip("#")
    result = subprocess.run(
        ["gh", "issue", "view", number, "--json", "state"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    try:
        obj = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    state = obj.get("state") if isinstance(obj, dict) else None
    return str(state).lower() if state else None


def lookup_jira_status(
    issue_id: str,
    env: dict[str, str] | None = None,
) -> str | None:
    env = os.environ if env is None else env
    base = env.get("JIRA_BASE_URL")
    token = env.get("JIRA_API_TOKEN")
    email = env.get("JIRA_USER_EMAIL")
    if not (base and token and email):
        return None

    import base64
    auth_raw = f"{email}:{token}".encode()
    auth_header = "Basic " + base64.b64encode(auth_raw).decode()
    url = f"{base.rstrip('/')}/rest/api/3/issue/{issue_id}?fields=status"
    request = urllib.request.Request(
        url,
        headers={"Authorization": auth_header, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            obj = json.loads(response.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return None
    fields = obj.get("fields") if isinstance(obj, dict) else None
    status = fields.get("status") if isinstance(fields, dict) else None
    name = status.get("name") if isinstance(status, dict) else None
    return str(name) if name else None


def tracker_lookup_for(tracker: str):
    if tracker == TRACKER_BEADS:
        return lookup_beads_status
    if tracker == TRACKER_GH:
        return lookup_gh_status
    if tracker == TRACKER_JIRA:
        return lookup_jira_status
    return lambda _id: None


def correlate_branch(
    branch: dict[str, object],
    primary_branch: str,
    tracker: str,
    issue_pattern: str | None,
    cwd: Path,
    tracker_lookup=None,
) -> dict[str, object]:
    branch_name = str(branch["name"])
    issue_id: str | None = None
    if issue_pattern:
        issue_id = extract_issue_id(branch_name, issue_pattern)

    unique_count, equivalent_count = parse_cherry(branch_name, primary_branch, cwd)
    behind, ahead = ahead_behind(branch_name, primary_branch, cwd)
    age_days = merge_base_age_days(branch_name, primary_branch, cwd)
    since_iso = merge_base_iso_date(branch_name, primary_branch, cwd)

    referencing: list[str] = []
    tracker_status: str | None = None
    if issue_id:
        referencing = commits_referencing_issue_on_main(
            issue_id, primary_branch, since_iso, cwd,
        )
        if tracker != TRACKER_NONE:
            lookup = tracker_lookup or tracker_lookup_for(tracker)
            tracker_status = lookup(issue_id)
            # Only retain issue_id if the tracker recognizes it (i.e. status
            # was returned). Otherwise the regex matched noise.
            if tracker_status is None:
                issue_id = None
                referencing = []

    return {
        "issue_id": issue_id,
        "cherry_unique_count": unique_count,
        "cherry_equivalent_count": equivalent_count,
        "main_commits_referencing_issue": referencing,
        "tracker_status": tracker_status,
        "merge_base_age_days": age_days,
        "divergence_ahead": ahead,
        "divergence_behind": behind,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        choices=[APPLY_DELETE_LOCAL_MERGED, APPLY_DELETE_LOCAL_PATCH_EQUIVALENT],
        help="apply the supported cleanup action after the dry-run scan",
    )
    parser.add_argument(
        "--no-liveness",
        action="store_true",
        help="skip per-worktree liveness assessment (faster, git-state only)",
    )
    parser.add_argument(
        "--target-branch",
        help=(
            "scope --apply delete-local-merged-branches to a single branch "
            "(used by skills like land-work that already know what to clean)"
        ),
    )
    parser.add_argument(
        "--correlate-branches",
        action="store_true",
        help=(
            "emit a 'correlation' block on each review_required branch with "
            "raw triage signals (cherry, grep on primary, tracker status). "
            "Off by default; opt-in because git cherry across many branches "
            "is slow."
        ),
    )
    parser.add_argument(
        "--tracker",
        choices=TRACKER_CHOICES,
        default="auto",
        help="tracker source for issue-status lookups (default: auto-detect)",
    )
    parser.add_argument(
        "--issue-pattern",
        help=(
            "regex for extracting an issue id from branch names. The first "
            "capture group (or the full match) becomes the candidate id. "
            "Defaults to the detected tracker's convention."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now_ts = time.time()

    try:
        cwd = Path.cwd().resolve()
        repo_root = detect_repo_root(cwd)
        primary_branch, warnings = detect_primary_branch(repo_root)
        current_branch = git_stdout("branch", "--show-current", cwd=repo_root)
        pruned = prune_missing_worktrees(repo_root)
        if pruned:
            warnings.append(
                f"pruned {len(pruned)} worktree registration(s) whose directories were missing"
            )
        raw_worktrees = parse_worktrees_raw(repo_root)
        checked_out_in_worktrees = {
            str(wt["branch"])
            for wt in raw_worktrees
            if wt.get("branch") and str(wt["branch"]) != current_branch
        }
        branches = classify_branches(
            local_branches(repo_root),
            primary_branch,
            current_branch,
            checked_out_in_worktrees,
            repo_root,
        )
        working_tree = working_tree_entries(repo_root)
        stashes = stash_entries(repo_root)

        ancestor_cwds = caller_ancestor_cwds()
        invocation_cwds = [cwd, *ancestor_cwds]

        # Enrich each worktree with its own dirty state and liveness assessment
        enriched_worktrees: list[dict[str, object]] = []
        for wt in raw_worktrees:
            wt_path = Path(str(wt["path"])).resolve()
            wt_entry: dict[str, object] = dict(wt)
            wt_entry["path_missing"] = not wt_path.is_dir()
            if wt_entry["path_missing"]:
                warnings.append(
                    f"worktree path missing on disk after prune: {wt_path}"
                )

            try:
                wt_dirty = working_tree_entries(wt_path)
            except Exception:
                wt_dirty = []

            wt_entry["working_tree_dirty"] = bool(wt_dirty)
            wt_entry["working_tree_entries"] = wt_dirty
            wt_entry["self_invocation"] = detect_self_invocation(wt_path, invocation_cwds)

            launch_work = scan_launch_work_log(wt_path)
            if launch_work is not None:
                wt_entry["launch_work"] = launch_work

            if not args.no_liveness:
                activity_ts, activity_source = worktree_activity_ts(wt_path, wt_dirty)
                codex_session = scan_codex_sessions(wt_path)
                claude_session = scan_claude_sessions(wt_path)
                live_processes = scan_process_liveness(wt_path)
                wt_entry["liveness"] = assess_liveness(
                    wt_path,
                    activity_ts,
                    activity_source,
                    codex_session,
                    claude_session,
                    live_processes,
                    now_ts=now_ts,
                )

            enriched_worktrees.append(wt_entry)

        if args.correlate_branches:
            tracker = args.tracker
            if tracker == "auto":
                tracker = detect_tracker(repo_root)
            issue_pattern = args.issue_pattern or default_issue_pattern(tracker)
            for branch in branches:
                if branch["classification"] != "review_required":
                    continue
                branch["correlation"] = correlate_branch(
                    branch, primary_branch, tracker, issue_pattern, repo_root,
                )

        summary = build_summary(branches, enriched_worktrees, stashes, working_tree)
        applied_actions: list[dict[str, str]] = []
        skipped_actions: list[dict[str, str]] = []

        if args.target_branch is not None:
            if args.apply != APPLY_DELETE_LOCAL_MERGED:
                print(
                    "--target-branch is only supported with --apply "
                    f"{APPLY_DELETE_LOCAL_MERGED}",
                    file=sys.stderr,
                )
                return 2
            known_branch_names = {str(b["name"]) for b in branches}
            if args.target_branch not in known_branch_names:
                print(
                    f"target branch {args.target_branch!r} not found in local branches",
                    file=sys.stderr,
                )
                return 2

        if args.apply == APPLY_DELETE_LOCAL_MERGED:
            applied_actions, skipped_actions = apply_delete_local_merged_branches(
                branches,
                enriched_worktrees,
                repo_root,
                target_branch=args.target_branch,
            )
        elif args.apply == APPLY_DELETE_LOCAL_PATCH_EQUIVALENT:
            applied_actions, skipped_actions = apply_delete_patch_equivalent_branches(
                branches,
                repo_root,
            )

        output = {
            "repo_root": str(repo_root),
            "primary_branch": primary_branch,
            "current_branch": current_branch,
            "worktrees": enriched_worktrees,
            "working_tree": working_tree,
            "stashes": stashes,
            "local_branches": branches,
            "summary": summary,
            "apply_mode": args.apply,
            "applied_actions": applied_actions,
            "skipped_actions": skipped_actions,
            "warnings": warnings,
        }
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
