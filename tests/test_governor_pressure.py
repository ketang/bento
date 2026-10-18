from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from governor.pressure import sample_signals


GIB = 1024**3


def proc_fixture(root: Path, *, cpu: str = "some avg10=0.00 avg60=0.00 total=0\n") -> Path:
    proc = root / "proc"
    (proc / "pressure").mkdir(parents=True)
    (proc / "meminfo").write_text("MemAvailable: 16777216 kB\n")
    (proc / "loadavg").write_text("0.50 0.25 0.10 1/100 1\n")
    (proc / "pressure" / "memory").write_text("full avg10=0.00 avg60=0.00 total=0\n")
    (proc / "pressure" / "io").write_text("some avg10=0.00 avg60=0.00 total=0\n")
    (proc / "pressure" / "cpu").write_text(cpu)
    return proc


def sample(tmp_path: Path, proc: Path, **config: object) -> dict:
    return sample_signals(
        config,
        str(tmp_path),
        weight=1,
        capacity=2,
        environ={"TMPDIR": str(tmp_path)},
        proc_root=proc,
    )


def by_name(result: dict, name: str) -> list[dict]:
    return [item for item in result["signals"] if item["name"] == name]


def test_ready_schema_and_requested_memory_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = proc_fixture(tmp_path)
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    result = sample(tmp_path, proc)
    assert result["schema_version"] == 1
    assert result["status"] == "ready"
    assert by_name(result, "mem_available_bytes")[0]["threshold"] == 8 * GIB
    assert by_name(result, "cpu_some_avg10")[0]["comparison"] == "max"
    assert by_name(result, "disk_free_bytes")
    weighted = sample_signals({}, str(tmp_path), 3, 4, {"TMPDIR": str(tmp_path)}, proc)
    assert by_name(weighted, "mem_available_bytes")[0]["threshold"] == 16 * GIB


def test_cpu_only_pressure_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = proc_fixture(tmp_path, cpu="some avg10=21.50 avg60=0.00 total=0\n")
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    result = sample(tmp_path, proc)
    assert result["status"] == "blocked"
    assert by_name(result, "cpu_some_avg10")[0] == {
        "name": "cpu_some_avg10", "status": "blocked", "value": 21.5,
        "threshold": 20.0, "comparison": "max", "reason": "above_max",
    }


def test_load_only_pressure_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = proc_fixture(tmp_path)
    (proc / "loadavg").write_text("7.00 0.25 0.10 1/100 1\n")
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    result = sample(tmp_path, proc)
    assert result["status"] == "blocked"
    assert by_name(result, "load1")[0]["reason"] == "above_max"
    assert by_name(result, "load1")[0]["threshold"] == 6.0


def test_absent_psi_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = proc_fixture(tmp_path)
    (proc / "pressure" / "cpu").unlink()
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    result = sample(tmp_path, proc)
    assert result["status"] == "error"
    signal = by_name(result, "cpu_some_avg10")[0]
    assert signal["status"] == "error"
    assert signal["reason"] == "unsupported"
    assert signal["detail"]


def test_bad_override_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = proc_fixture(tmp_path)
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    result = sample(tmp_path, proc, max_cpu_some_avg10=float("nan"))
    assert result["status"] == "error"
    assert by_name(result, "cpu_some_avg10")[0]["reason"] == "invalid_override"
    above_percent = sample(tmp_path, proc, max_cpu_some_avg10=101)
    assert by_name(above_percent, "cpu_some_avg10")[0]["reason"] == "invalid_override"
    zero = sample(tmp_path, proc, max_cpu_some_avg10=0)
    assert by_name(zero, "cpu_some_avg10")[0]["status"] == "ready"


def test_disk_paths_deduplicate_device_and_keep_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = proc_fixture(tmp_path)
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    target = tmp_path / "future" / "build"
    cache = tmp_path / "future" / "cache"
    monkeypatch.setattr(os, "statvfs", lambda path: SimpleNamespace(f_bavail=1, f_frsize=4096))
    result = sample_signals(
        {}, str(tmp_path), 1, 2,
        {"CARGO_TARGET_DIR": str(target), "XDG_CACHE_HOME": str(cache), "TMPDIR": str(tmp_path)}, proc,
    )
    disks = by_name(result, "disk_free_bytes")
    assert len(disks) == 1
    assert disks[0]["status"] == "blocked"
    assert disks[0]["reason"] == "below_min"
    assert str(target) in disks[0]["paths"]
    assert str(cache) in disks[0]["paths"]


def test_missing_required_directory_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = proc_fixture(tmp_path)
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    result = sample_signals({}, str(tmp_path / "missing"), 1, 2, {}, proc)
    assert result["status"] == "error"
    assert by_name(result, "disk_free_bytes")[0]["reason"] == "missing"


@pytest.mark.parametrize(
    ("source", "contents", "signal", "reason"),
    [
        ("meminfo", "MemAvailable: 1024 kB\n", "mem_available_bytes", "below_min"),
        ("pressure/io", "some avg10=21.00 avg60=0 total=0\n", "io_some_avg10", "above_max"),
        ("pressure/memory", "full avg10=1.01 avg60=0 total=0\n", "memory_full_avg10", "above_max"),
        ("pressure/cpu", "some avg10=NaN avg60=0 total=0\n", "cpu_some_avg10", "malformed"),
    ],
)
def test_memory_io_and_malformed_pressure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, contents: str,
    signal: str, reason: str,
) -> None:
    proc = proc_fixture(tmp_path)
    (proc / source).write_text(contents)
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    result = sample(tmp_path, proc)
    assert result["status"] == ("error" if reason == "malformed" else "blocked")
    assert by_name(result, signal)[0]["reason"] == reason


def test_relative_target_path_is_resolved_from_request_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = proc_fixture(tmp_path)
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    result = sample_signals({}, str(tmp_path), 1, 2, {"CARGO_TARGET_DIR": "build"}, proc)
    paths = [path for signal in by_name(result, "disk_free_bytes") for path in signal.get("paths", [])]
    assert str(tmp_path / "build") in paths
    assert "/tmp" in paths
