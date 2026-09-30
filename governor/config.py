"""Administrator configuration (/etc/bento-governor/v1.toml) and capacity policy."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

GIB = 1024**3
KNOWN = {
    "capacity", "unit_bytes", "poll_seconds", "allowed_uids", "allowed_gids", "operator_uids",
    "state_dir", "extra_disk_paths", "min_mem_bytes", "max_memory_full_avg10", "max_io_some_avg10",
    "max_cpu_some_avg10", "min_disk_bytes", "max_load_factor",
}


class ConfigError(Exception):
    pass


def default_capacity(online_cpus: int, mem_total_bytes: int) -> int:
    """min(floor(cpus / 4), floor((MemTotal - 8 GiB) / 4 GiB)), minimum 1 only if MemTotal >= 12 GiB."""
    if mem_total_bytes < 12 * GIB:
        raise ConfigError("MemTotal < 12 GiB: set an explicit reviewed capacity")
    return max(1, min(online_cpus // 4, (mem_total_bytes - 8 * GIB) // (4 * GIB)))


def _mem_total() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    raise ConfigError("MemTotal not found in /proc/meminfo")


def load(path: Path | str) -> dict:
    try:
        config = tomllib.loads(Path(path).read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    unknown = set(config) - KNOWN
    if unknown:
        raise ConfigError(f"unknown config keys: {sorted(unknown)}")
    if "capacity" not in config:
        config["capacity"] = default_capacity(os.cpu_count() or 1, _mem_total())
    if isinstance(config["capacity"], bool) or not isinstance(config["capacity"], int) or config["capacity"] < 1:
        raise ConfigError("capacity must be a positive integer")
    for key in ("allowed_uids", "allowed_gids", "operator_uids"):
        values = config.setdefault(key, [])
        if not isinstance(values, list) or any(isinstance(v, bool) or not isinstance(v, int) for v in values):
            raise ConfigError(f"{key} must be a list of integers")
    if not config["allowed_uids"] and not config["allowed_gids"]:
        raise ConfigError("configure allowed_uids or allowed_gids; default is deny")
    config.setdefault("unit_bytes", 4 * GIB)
    config.setdefault("poll_seconds", 10)
    config.setdefault("state_dir", "/var/lib/bento-governor/v1")
    return config
