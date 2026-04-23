#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path


def load_input(path: Path) -> dict:
    with path.open() as fh:
        data = json.load(fh)
    if "tasks" not in data or not isinstance(data["tasks"], list):
        raise ValueError("input must contain a top-level 'tasks' list")
    return data


def task_sort_key(task: dict) -> tuple:
    return (
        task.get("priority", 1000),
        task.get("id", ""),
    )


def normalize_paths(values: list[str] | None) -> set[str]:
    return {value for value in (values or []) if value}


def conflicts(task: dict, occupied_paths: set[str], hotspots: set[str]) -> bool:
    paths = normalize_paths(task.get("paths"))
    return bool(paths & occupied_paths) or bool(paths & hotspots)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="path to triage JSON")
    args = parser.parse_args()

    data = load_input(Path(args.input))
    max_parallel = int(data.get("max_parallel", 8))
    batch_limit = int(data.get("batch_limit", 20))
    landed_task_ids = set(data.get("landed_task_ids") or [])
    active_paths = normalize_paths(data.get("active_paths"))
    hotspots = normalize_paths(data.get("hotspots"))

    skipped = []
    dependency_deferred = []
    active_overlap_deferred = []
    eligible = []

    for task in sorted(data["tasks"], key=task_sort_key):
        task_id = task.get("id", "<missing-id>")
        if task.get("in_progress"):
            skipped.append({"id": task_id, "reason": "already_in_progress"})
            continue
        if task.get("too_large"):
            skipped.append({"id": task_id, "reason": "too_large"})
            continue
        if task.get("ambiguous"):
            skipped.append({"id": task_id, "reason": "ambiguous"})
            continue
        unresolved_dependencies = sorted(set(task.get("dependencies") or []) - landed_task_ids)
        if unresolved_dependencies:
            dependency_deferred.append({"id": task_id, "dependencies": unresolved_dependencies})
            continue
        if conflicts(task, active_paths, hotspots):
            active_overlap_deferred.append(task)
            continue
        eligible.append(task)

    overflow = eligible[batch_limit:]
    candidate_batch = eligible[:batch_limit]

    parallel_batch = []
    wait_queue = []
    occupied_paths = set(active_paths)

    for task in candidate_batch:
        task_paths = normalize_paths(task.get("paths"))
        if task_paths & occupied_paths:
            record = {"id": task.get("id"), "reason": "path_overlap_with_batch"}
            wait_queue.append(record)
            continue
        if len(parallel_batch) >= max_parallel:
            wait_queue.append({"id": task.get("id"), "reason": "max_parallel_limit"})
            continue
        parallel_batch.append(task.get("id"))
        occupied_paths |= task_paths

    output = {
        "parallel_batch": parallel_batch,
        "wait_queue": wait_queue,
        "overflow": [task.get("id") for task in overflow],
        "skipped": skipped,
        "deferred_due_to_active_overlap": [
            {"id": task.get("id"), "reason": "path_overlap_with_active_or_hotspot"}
            for task in active_overlap_deferred
        ],
        "deferred_due_to_dependencies": dependency_deferred,
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
