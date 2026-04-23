from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from git_state import git, git_stdout, parse_worktrees


EXPEDITIONS_ROOT = Path("docs") / "expeditions"
RESUME_START = "<!-- expedition-resume:start -->"
RESUME_END = "<!-- expedition-resume:end -->"
RESUME_HEADER = "## RESUME HERE"
SCHEMA_VERSION = 2
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ExpeditionStateError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_name(raw: str) -> str:
    candidate = raw.strip()
    if not NAME_RE.fullmatch(candidate):
        raise ExpeditionStateError(
            "names and slugs must be lowercase dash-separated tokens matching [a-z0-9-]"
        )
    return candidate


def expedition_dir(worktree: Path, expedition: str) -> Path:
    return worktree / EXPEDITIONS_ROOT / expedition


def plan_path(worktree: Path, expedition: str) -> Path:
    return expedition_dir(worktree, expedition) / "plan.md"


def log_path(worktree: Path, expedition: str) -> Path:
    return expedition_dir(worktree, expedition) / "log.md"


def handoff_path(worktree: Path, expedition: str) -> Path:
    return expedition_dir(worktree, expedition) / "handoff.md"


def state_path(worktree: Path, expedition: str) -> Path:
    return expedition_dir(worktree, expedition) / "state.json"


def current_head(cwd: Path) -> str:
    return git_stdout("rev-parse", "HEAD", cwd=cwd)


def current_branch(cwd: Path) -> str:
    return git_stdout("branch", "--show-current", cwd=cwd)


def is_clean(cwd: Path) -> bool:
    return git("status", "--short", cwd=cwd).stdout.strip() == ""


def slugify(raw: str) -> str:
    collapsed = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return validate_name(collapsed)


def next_branch_name(state: dict[str, object], kind: str, slug: str) -> str:
    number = int(state["next_task_number"])
    expedition = str(state["expedition"])
    if kind == "perf-experiment":
        return f"{expedition}-perfexp-{number:02d}-{slug}"
    if kind == "experiment":
        return f"{expedition}-exp-{number:02d}-{slug}"
    return f"{expedition}-{number:02d}-{slug}"


def next_worktree_path(state: dict[str, object], branch: str) -> Path:
    base_worktree = Path(str(state["base_worktree"])).resolve()
    return base_worktree.parent / branch


def init_state(expedition: str, primary_branch: str, base_worktree: Path) -> dict[str, object]:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "expedition": expedition,
        "primary_branch": primary_branch,
        "base_branch": expedition,
        "base_worktree": str(base_worktree.resolve()),
        "status": "ready_for_task",
        "next_task_number": 1,
        "active_branches": [],
        "landing_lease": None,
        "last_completed": None,
        "preserved_experiments": [],
        "next_action": "Create the first task branch from the expedition base branch.",
        "created_at": now,
        "updated_at": now,
    }


def migrate_state(payload: dict[str, object]) -> dict[str, object]:
    version = int(payload.get("schema_version", 1) or 1)
    if version >= SCHEMA_VERSION:
        return payload
    if version == 1:
        active_task = payload.pop("active_task", None)
        payload["active_branches"] = [active_task] if active_task else []
        payload["landing_lease"] = None
        payload["schema_version"] = SCHEMA_VERSION
    return payload


def load_state(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return migrate_state(payload)


def write_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_plan(state: dict[str, object]) -> str:
    expedition = state["expedition"]
    return f"""# {expedition} Expedition Plan

## Goal

Document the expedition goal here.

## Success Criteria

- Define what counts as done.
- Record any measurable thresholds.

## Task Sequence

1. Fill in the first serial task.
2. Add more tasks as the expedition becomes clearer.

## Experiment Register

For each planned experiment:

- hypothesis
- success criteria
- discard criteria
- branch slug seed

## Verification Gates

- Add the repo commands that must pass before a kept task merges into the base branch.
- Add the final verification gate for landing the rebased base branch.
"""


def render_log(state: dict[str, object]) -> str:
    expedition = state["expedition"]
    base_branch = state["base_branch"]
    primary_branch = state["primary_branch"]
    base_worktree = state["base_worktree"]
    timestamp = state["created_at"]
    return f"""# {expedition} Expedition Log

## Frozen Header

- Expedition: `{expedition}`
- Base branch: `{base_branch}`
- Primary branch: `{primary_branch}`
- Base worktree: `{base_worktree}`
- State file: `docs/expeditions/{expedition}/state.json`

## Activity Log

### {timestamp} — Expedition initialized
- Base branch `{base_branch}` created from `{primary_branch}`.
- Plan, log, handoff, and state files initialized inside the expedition base branch.
- Next action: create the first serial task branch.

{RESUME_HEADER}
{RESUME_START}
{render_resume_lines(state)}
{RESUME_END}
"""


def render_resume_lines(state: dict[str, object]) -> str:
    last = state.get("last_completed")
    active_list = state.get("active_branches") or []
    if active_list:
        active_branch = ", ".join(item["branch"] for item in active_list)
        active_worktree = ", ".join(item["worktree"] for item in active_list)
    else:
        active_branch = "none"
        active_worktree = "none"
    last_completed = (
        f"{last['branch']} ({last['outcome']})" if last else "none"
    )
    return "\n".join(
        [
            f"- Expedition: `{state['expedition']}`",
            f"- Status: `{state['status']}`",
            f"- Base branch: `{state['base_branch']}`",
            f"- Base worktree: `{state['base_worktree']}`",
            f"- Active task branch: `{active_branch}`",
            f"- Active task worktree: `{active_worktree}`",
            f"- Last completed: `{last_completed}`",
            f"- Next action: {state['next_action']}",
        ]
    )


def render_handoff(state: dict[str, object]) -> str:
    last = state.get("last_completed")
    active_list = state.get("active_branches") or []
    if active_list:
        active_branch = ", ".join(item["branch"] for item in active_list)
        active_worktree = ", ".join(item["worktree"] for item in active_list)
    else:
        active_branch = "none"
        active_worktree = "none"
    last_completed = f"{last['branch']} ({last['outcome']})" if last else "none"
    return f"""# {state['expedition']} Expedition Handoff

- Expedition: `{state['expedition']}`
- Base branch: `{state['base_branch']}`
- Base worktree: `{state['base_worktree']}`
- Status: `{state['status']}`
- Active task branch: `{active_branch}`
- Active task worktree: `{active_worktree}`
- Last completed: `{last_completed}`
- Next action: {state['next_action']}
- Primary branch: `{state['primary_branch']}`
"""


def replace_resume_block(existing: str, state: dict[str, object]) -> str:
    if RESUME_START not in existing or RESUME_END not in existing:
        raise ExpeditionStateError("log file is missing expedition resume markers")
    start = existing.index(RESUME_START) + len(RESUME_START)
    end = existing.index(RESUME_END)
    return existing[:start] + "\n" + render_resume_lines(state) + "\n" + existing[end:]


def append_log_entry(path: Path, title: str, bullets: list[str]) -> None:
    existing = path.read_text(encoding="utf-8")
    marker = f"\n{RESUME_HEADER}\n"
    if marker not in existing:
        raise ExpeditionStateError("log file is missing the resume header")
    entry = "\n".join([f"### {utc_now()} — {title}", *[f"- {bullet}" for bullet in bullets], ""]) + "\n"
    path.write_text(existing.replace(marker, "\n" + entry + marker, 1), encoding="utf-8")


def sync_markdown_views(worktree: Path, state: dict[str, object]) -> None:
    log_file = log_path(worktree, str(state["expedition"]))
    handoff_file = handoff_path(worktree, str(state["expedition"]))
    updated_log = replace_resume_block(log_file.read_text(encoding="utf-8"), state)
    log_file.write_text(updated_log, encoding="utf-8")
    handoff_file.write_text(render_handoff(state), encoding="utf-8")


def commit_expedition_docs(cwd: Path, expedition: str, message: str) -> str:
    relative_docs = str(EXPEDITIONS_ROOT / expedition)
    git("add", "-A", relative_docs, cwd=cwd)
    commit_result = git("commit", "-m", message, cwd=cwd, check=False)
    if commit_result.returncode != 0:
        stderr = commit_result.stderr.strip() or commit_result.stdout.strip() or "git commit failed"
        raise ExpeditionStateError(stderr)
    return current_head(cwd)


def discover_expeditions(checkout_root: Path, expedition: str | None = None) -> list[tuple[Path, dict[str, object]]]:
    matches: list[tuple[Path, dict[str, object]]] = []
    for worktree in parse_worktrees(checkout_root):
        worktree_path = Path(str(worktree["path"])).resolve()
        docs_root = worktree_path / EXPEDITIONS_ROOT
        if not docs_root.exists():
            continue
        candidates = (
            [docs_root / expedition / "state.json"]
            if expedition
            else sorted(docs_root.glob("*/state.json"))
        )
        for candidate in candidates:
            if candidate.exists():
                payload = load_state(candidate)
                if worktree_path != Path(str(payload["base_worktree"])).resolve():
                    continue
                matches.append((candidate, payload))
    return matches


def locate_expedition(checkout_root: Path, expedition: str) -> tuple[Path, dict[str, object]]:
    matches = discover_expeditions(checkout_root, expedition)
    if not matches:
        raise ExpeditionStateError(f"no expedition state found for {expedition}")
    if len(matches) > 1:
        raise ExpeditionStateError(f"multiple expedition states found for {expedition}; clean up stale worktrees first")
    return matches[0]
