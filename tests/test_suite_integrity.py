"""Meta-tests guarding the test suite's own discoverability.

The build gate runs ``python3 -m unittest discover -s tests -t .``. Unittest
discovery only recurses into directories that are Python packages (i.e. contain
``__init__.py``). A new test directory without ``__init__.py`` is silently
skipped, so its tests never run even though they appear to exist. These tests
make that failure mode loud.
"""

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"


def _dirs_with_test_files() -> list[Path]:
    """Directories under tests/ (including tests/) that hold test_*.py files."""
    dirs = set()
    for test_file in TESTS_DIR.rglob("test_*.py"):
        dirs.add(test_file.parent)
    return sorted(dirs)


def _disk_test_modules() -> set[str]:
    """Dotted module names for every test_*.py file on disk."""
    modules = set()
    for test_file in TESTS_DIR.rglob("test_*.py"):
        rel = test_file.relative_to(REPO_ROOT).with_suffix("")
        modules.add(".".join(rel.parts))
    return modules


def _iter_tests(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def _discovered_modules() -> set[str]:
    """Module names unittest discovery actually loads from tests/.

    Modules that fail to import are wrapped in ``_FailedTest``; their dotted
    name is recovered from the failing method name so an import error still
    counts as "discovered" rather than masquerading as a missing module.
    """
    suite = unittest.defaultTestLoader.discover(
        str(TESTS_DIR), top_level_dir=str(REPO_ROOT)
    )
    modules = set()
    for test in _iter_tests(suite):
        if type(test).__name__ == "_FailedTest":
            modules.add(test._testMethodName)
        else:
            modules.add(type(test).__module__)
    return modules


class TestSuiteIntegrityTest(unittest.TestCase):
    def test_every_test_dir_is_a_package(self) -> None:
        offenders = [
            str(d.relative_to(REPO_ROOT))
            for d in _dirs_with_test_files()
            if not (d / "__init__.py").exists()
        ]
        self.assertEqual(
            offenders,
            [],
            "Test directories contain test_*.py files but lack __init__.py, so "
            "`unittest discover` silently skips them: " + ", ".join(offenders),
        )

    def test_discovery_covers_every_test_file(self) -> None:
        disk = _disk_test_modules()
        discovered = _discovered_modules()
        missing = sorted(disk - discovered)
        self.assertEqual(
            missing,
            [],
            "test_*.py files on disk that `unittest discover` does not load: "
            + ", ".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
