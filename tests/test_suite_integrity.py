import os
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent


def _dirs_with_test_modules() -> set[Path]:
    """Directories under tests/ that contain at least one test_*.py file."""
    found = set()
    for root, dirs, files in os.walk(TESTS_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        if any(f.startswith("test_") and f.endswith(".py") for f in files):
            found.add(Path(root))
    return found


def _test_modules_on_disk() -> set[str]:
    """Dotted module names for every test_*.py file under tests/."""
    modules = set()
    for path in TESTS_DIR.rglob("test_*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(REPO_ROOT).with_suffix("")
        modules.add(".".join(rel.parts))
    return modules


class TestSuiteIntegrity(unittest.TestCase):
    def test_every_test_dir_is_a_package(self) -> None:
        """Every directory holding test_*.py must be an importable package.

        Without an __init__.py, unittest discover silently skips the directory,
        hiding its tests from the gate. See bento-6h4.
        """
        missing = [
            str(d.relative_to(REPO_ROOT))
            for d in sorted(_dirs_with_test_modules())
            if not (d / "__init__.py").is_file()
        ]
        self.assertEqual(
            missing,
            [],
            "Test directories missing __init__.py (tests silently skipped by "
            f"unittest discover): {missing}",
        )

    def test_discover_covers_every_test_module_on_disk(self) -> None:
        """unittest discover must load every test_*.py file present on disk."""
        loader = unittest.TestLoader()
        suite = loader.discover(str(TESTS_DIR), top_level_dir=str(REPO_ROOT))

        discovered = set()

        def walk(s: unittest.TestSuite) -> None:
            for item in s:
                if isinstance(item, unittest.TestSuite):
                    walk(item)
                else:
                    discovered.add(type(item).__module__)

        walk(suite)
        self.assertEqual(loader.errors, [], f"discover reported load errors: {loader.errors}")

        on_disk = _test_modules_on_disk()
        # The integrity module itself is on disk and should be discovered too.
        missing = sorted(on_disk - discovered)
        self.assertEqual(
            missing,
            [],
            f"test modules on disk not loaded by unittest discover: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
