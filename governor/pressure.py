"""Fail-closed host pressure sampling for admission decisions."""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from typing import Mapping


GIB = 1024**3
DEFAULTS: dict[str, float | int] = {
    "unit_bytes": 4 * GIB,
    "min_mem_bytes": 8 * GIB,
    "max_memory_full_avg10": 1.0,
    "max_io_some_avg10": 20.0,
    "max_cpu_some_avg10": 20.0,
    "min_disk_bytes": 10 * GIB,
    "max_load_factor": 1.5,
}


class SignalError(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _positive_number(config: dict, key: str) -> float | int:
    value = config.get(key, DEFAULTS[key])
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SignalError("invalid_override", f"{key} must be a finite positive number")
    if not math.isfinite(value) or value <= 0:
        raise SignalError("invalid_override", f"{key} must be a finite positive number")
    if key.endswith("_bytes") and (not isinstance(value, int) or value < 1):
        raise SignalError("invalid_override", f"{key} must be a positive integer number of bytes")
    return value


def _read(path: Path, *, unsupported: bool = False) -> str:
    try:
        return path.read_text(encoding="ascii")
    except FileNotFoundError as exc:
        raise SignalError("unsupported" if unsupported else "missing", f"{path} does not exist") from exc
    except (OSError, UnicodeError) as exc:
        raise SignalError("unreadable", f"cannot read {path}: {exc}") from exc


def _mem_available(proc_root: Path) -> int:
    for line in _read(proc_root / "meminfo").splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == "MemAvailable:" and fields[2] == "kB":
            try:
                value = int(fields[1]) * 1024
            except ValueError as exc:
                raise SignalError("malformed", "MemAvailable is not an integer") from exc
            if value >= 0:
                return value
            break
    raise SignalError("malformed", "MemAvailable is missing or malformed")


def _psi_avg10(proc_root: Path, source: str, kind: str) -> float:
    path = proc_root / "pressure" / source
    for line in _read(path, unsupported=True).splitlines():
        fields = line.split()
        if fields and fields[0] == kind:
            values = dict(part.split("=", 1) for part in fields[1:] if "=" in part)
            try:
                value = float(values["avg10"])
            except (KeyError, ValueError) as exc:
                raise SignalError("malformed", f"{path}: {kind} avg10 is missing or invalid") from exc
            if math.isfinite(value) and 0 <= value <= 100:
                return value
            raise SignalError("malformed", f"{path}: {kind} avg10 is outside 0..100")
    raise SignalError("malformed", f"{path}: {kind} line is missing")


def _load1(proc_root: Path) -> float:
    try:
        value = float(_read(proc_root / "loadavg").split()[0])
    except (IndexError, ValueError) as exc:
        raise SignalError("malformed", "loadavg has no valid one-minute load") from exc
    if not math.isfinite(value) or value < 0:
        raise SignalError("malformed", "loadavg one-minute load is invalid")
    return value


def _result(name: str, comparison: str, threshold: float | int | None, reader) -> dict:
    signal = {"name": name, "status": "error", "value": None, "threshold": threshold,
              "comparison": comparison, "reason": ""}
    try:
        value = reader()
        signal["value"] = value
        ready = value >= threshold if comparison == "min" else value <= threshold
        signal["status"] = "ready" if ready else "blocked"
        signal["reason"] = "" if ready else ("below_min" if comparison == "min" else "above_max")
    except SignalError as exc:
        signal["reason"] = exc.reason
        signal["detail"] = exc.detail
    return signal


def _threshold_result(name: str, comparison: str, threshold_fn, reader) -> dict:
    try:
        threshold = threshold_fn()
    except SignalError as exc:
        return {"name": name, "status": "error", "value": None, "threshold": None,
                "comparison": comparison, "reason": exc.reason, "detail": exc.detail}
    return _result(name, comparison, threshold, reader)


def _disk_paths(config: dict, cwd: str, environ: Mapping[str, str]) -> list[Path]:
    paths = [cwd, environ.get("TMPDIR") or tempfile.gettempdir(),
             environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache"),
             config.get("state_dir", "/var/lib/bento-governor/v1"),
             config.get("log_dir", "/var/log/bento-governor")]
    for key in ("CARGO_TARGET_DIR", "CMAKE_BUILD_DIR", "BUILD_TARGET_DIR", "TMPDIR", "TMP", "TEMP",
                "XDG_CACHE_HOME", "CARGO_HOME", "SCCACHE_DIR"):
        if environ.get(key):
            paths.append(environ[key])
    extra = config.get("extra_disk_paths", ())
    if not isinstance(extra, (list, tuple)) or any(not isinstance(path, str) or not path for path in extra):
        raise SignalError("invalid_override", "extra_disk_paths must be a list of nonempty paths")
    paths.extend(extra)
    base = Path(cwd).absolute()
    resolved = []
    for path in paths:
        if not isinstance(path, str) or not path:
            raise SignalError("invalid_override", "disk paths must be nonempty strings")
        candidate = Path(path)
        resolved.append(candidate if candidate.is_absolute() else base / candidate)
    return resolved


def _disk_signals(config: dict, cwd: str, environ: Mapping[str, str]) -> list[dict]:
    try:
        threshold = _positive_number(config, "min_disk_bytes")
        paths = _disk_paths(config, cwd, environ)
    except SignalError as exc:
        return [{"name": "disk_free_bytes", "status": "error", "value": None, "threshold": None,
                 "comparison": "min", "reason": exc.reason, "detail": exc.detail}]

    groups: dict[int, dict] = {}
    errors: list[dict] = []
    for index, requested in enumerate(paths):
        try:
            if index == 0 and not requested.is_dir():
                raise SignalError("missing", f"working directory {requested} does not exist")
            existing = requested
            while not existing.exists():
                parent = existing.parent
                if parent == existing:
                    raise SignalError("missing", f"no existing ancestor for {requested}")
                existing = parent
            if not existing.is_dir():
                raise SignalError("missing", f"{existing} is not a directory")
            stat = existing.stat()
            fs = os.statvfs(existing)
            available = fs.f_bavail * fs.f_frsize
            if available < 0:
                raise SignalError("malformed", f"negative available bytes for {existing}")
            group = groups.setdefault(stat.st_dev, {"paths": [], "existing": existing, "value": available})
            group["paths"].append(str(requested))
        except SignalError as exc:
            errors.append({"name": "disk_free_bytes", "status": "error", "value": None,
                           "threshold": threshold, "comparison": "min", "reason": exc.reason,
                           "detail": exc.detail, "paths": [str(requested)]})
        except PermissionError as exc:
            errors.append({"name": "disk_free_bytes", "status": "error", "value": None,
                           "threshold": threshold, "comparison": "min", "reason": "unreadable",
                           "detail": str(exc), "paths": [str(requested)]})
        except OSError as exc:
            errors.append({"name": "disk_free_bytes", "status": "error", "value": None,
                           "threshold": threshold, "comparison": "min", "reason": "unreadable",
                           "detail": str(exc), "paths": [str(requested)]})
    signals = []
    for group in groups.values():
        value = group["value"]
        ready = value >= threshold
        signals.append({"name": "disk_free_bytes", "status": "ready" if ready else "blocked",
                        "value": value, "threshold": threshold, "comparison": "min",
                        "reason": "" if ready else "below_min", "paths": group["paths"]})
    return errors + signals


def sample_signals(
    config: dict,
    cwd: str,
    weight: int,
    capacity: int,
    environ: Mapping[str, str] | None = None,
    proc_root: Path = Path("/proc"),
) -> dict:
    """Return a schema-v1 snapshot; every unavailable required signal is an error."""
    env = os.environ if environ is None else environ
    signals: list[dict] = []
    try:
        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
            raise SignalError("invalid_override", "weight must be a positive integer")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise SignalError("invalid_override", "capacity must be a positive integer")
        unit = _positive_number(config, "unit_bytes")
        min_mem = _positive_number(config, "min_mem_bytes")
        mem_threshold = max(min_mem, weight * unit + 4 * GIB)
    except SignalError as exc:
        signals.append({"name": "mem_available_bytes", "status": "error", "value": None,
                        "threshold": None, "comparison": "min", "reason": exc.reason, "detail": exc.detail})
    else:
        signals.append(_result("mem_available_bytes", "min", mem_threshold,
                               lambda: _mem_available(proc_root)))

    for name, source, kind, key in (
        ("memory_full_avg10", "memory", "full", "max_memory_full_avg10"),
        ("io_some_avg10", "io", "some", "max_io_some_avg10"),
        ("cpu_some_avg10", "cpu", "some", "max_cpu_some_avg10"),
    ):
        signals.append(_threshold_result(name, "max", lambda key=key: _positive_number(config, key),
                                         lambda source=source, kind=kind: _psi_avg10(proc_root, source, kind)))

    signals.extend(_disk_signals(config, cwd, env))

    def load_threshold() -> float:
        cpus = os.cpu_count()
        if cpus is None or cpus < 1:
            raise SignalError("unsupported", "online CPU count is unavailable")
        return cpus * _positive_number(config, "max_load_factor")

    signals.append(_threshold_result("load1", "max", load_threshold, lambda: _load1(proc_root)))
    status = "error" if any(s["status"] == "error" for s in signals) else (
        "blocked" if any(s["status"] == "blocked" for s in signals) else "ready")
    return {"schema_version": 1, "status": status, "signals": signals}
