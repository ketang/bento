import importlib.util
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, check=check)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def load_module(path: Path):
    module_name = "test_module_" + "_".join(path.with_suffix("").parts[-4:])
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_script_module_with_git_state(module_name: str, script_path: Path):
    """Import a hyphenated-filename script directly (so not a normal
    import), swapping *that script's own* git_state.py into
    sys.modules["git_state"] for the duration of the import.

    Several skills ship their own same-named git_state.py; another test in
    the suite may already have cached a *different* one under
    sys.modules["git_state"], which would make the target script's
    `from git_state import (...)` resolve to the wrong module (or fail with
    ImportError for a name it doesn't define). Restore whatever was cached
    before once the target module is loaded.
    """
    scripts_dir = script_path.parent
    original_git_state = sys.modules.get("git_state")
    try:
        gs_spec = importlib.util.spec_from_file_location("git_state", scripts_dir / "git_state.py")
        gs_module = importlib.util.module_from_spec(gs_spec)
        gs_spec.loader.exec_module(gs_module)
        sys.modules["git_state"] = gs_module

        spec = importlib.util.spec_from_file_location(module_name, script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if original_git_state is not None:
            sys.modules["git_state"] = original_git_state
        else:
            sys.modules.pop("git_state", None)
    return module
