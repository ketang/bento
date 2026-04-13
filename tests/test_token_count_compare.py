import importlib.machinery
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "token-count-compare.py"
FAKE_CHARS_PER_TIKTOKEN = 5  # fake encoder: 1 token per 5 chars


class _FakeEncoding:
    def encode(self, text: str) -> list[int]:
        count = max(1, len(text) // FAKE_CHARS_PER_TIKTOKEN) if text else 0
        return list(range(count))


class _FakeTiktoken:
    def get_encoding(self, name: str) -> _FakeEncoding:
        return _FakeEncoding()


def load_script_module():
    loader = importlib.machinery.SourceFileLoader("token_count_compare", str(SCRIPT))
    spec = importlib.util.spec_from_loader("token_count_compare", loader)
    if spec is None:
        raise RuntimeError("unable to create spec for token-count-compare.py")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TokenCountCompareTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_script_module()
        self.module.load_tiktoken = lambda: _FakeTiktoken()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

    def tearDown(self) -> None:
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        self.temp_dir.cleanup()

    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        code = self.module.main(argv)
        return code, sys.stdout.getvalue(), sys.stderr.getvalue()

    def write(self, name: str, content: str) -> Path:
        path = self.tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_no_args_prints_usage_to_stderr(self) -> None:
        code, stdout, stderr = self.run_main([])
        self.assertEqual(code, self.module.NO_ARGS_EXIT_CODE)
        self.assertIn("Usage", stderr)
        self.assertEqual(stdout, "")

    def test_single_file_reports_metrics_without_totals(self) -> None:
        path = self.write("a.md", "x" * 400)
        code, stdout, _ = self.run_main([str(path)])
        self.assertEqual(code, 0)
        lines = [line for line in stdout.splitlines() if line.strip()]
        # header + separator + 1 data row, no totals
        self.assertEqual(len(lines), 3)
        self.assertIn("char/4", lines[0])
        self.assertIn(str(path), lines[2])
        self.assertNotIn("total", stdout)

    def test_multiple_files_are_sorted_by_char4_ascending(self) -> None:
        small = self.write("small.md", "x" * 80)
        medium = self.write("medium.md", "x" * 400)
        large = self.write("large.md", "x" * 2000)
        code, stdout, _ = self.run_main([str(large), str(small), str(medium)])
        self.assertEqual(code, 0)
        data_lines = [
            line
            for line in stdout.splitlines()
            if line.strip() and not line.startswith("-") and "char/4" not in line
        ]
        # 3 data rows + 1 totals row
        self.assertEqual(len(data_lines), 4)
        file_rows = data_lines[:3]
        char4_values = [int(row.split()[0]) for row in file_rows]
        self.assertEqual(char4_values, sorted(char4_values))
        row_names = [row.split()[-1] for row in file_rows]
        self.assertEqual(row_names, [str(small), str(medium), str(large)])

    def test_multiple_files_emit_totals_row(self) -> None:
        a = self.write("a.md", "x" * 400)
        b = self.write("b.md", "y" * 200)
        code, stdout, _ = self.run_main([str(a), str(b)])
        self.assertEqual(code, 0)
        totals_line = next(
            (line for line in stdout.splitlines() if "total" in line), None
        )
        self.assertIsNotNone(totals_line)
        self.assertIn("2 files", totals_line)
        totals_char4 = int(totals_line.split()[0])
        self.assertEqual(totals_char4, 150)

    def test_missing_files_emit_stderr_warning_and_are_skipped(self) -> None:
        real = self.write("real.md", "x" * 400)
        missing = self.tmp_path / "does-not-exist.md"
        code, stdout, stderr = self.run_main([str(missing), str(real)])
        self.assertEqual(code, 0)
        self.assertIn("skip:", stderr)
        self.assertIn(str(missing), stderr)
        data_lines = [
            line
            for line in stdout.splitlines()
            if line.strip() and not line.startswith("-") and "char/4" not in line
        ]
        self.assertEqual(len(data_lines), 1)
        self.assertIn(str(real), data_lines[0])

    def test_missing_tiktoken_exits_with_clear_error(self) -> None:
        def fake_load() -> _FakeTiktoken:
            sys.stderr.write(
                "error: tiktoken not installed\n"
                "  install with: pip install tiktoken\n"
            )
            sys.exit(self.module.TIKTOKEN_MISSING_EXIT_CODE)

        self.module.load_tiktoken = fake_load
        path = self.write("a.md", "x" * 100)
        with self.assertRaises(SystemExit) as cm:
            self.module.main([str(path)])
        self.assertEqual(cm.exception.code, self.module.TIKTOKEN_MISSING_EXIT_CODE)
        self.assertIn("tiktoken not installed", sys.stderr.getvalue())

    def test_measure_uses_char4_and_fake_encoder(self) -> None:
        path = self.write("a.md", "x" * 400)
        enc = _FakeEncoding()
        char4, tik = self.module.measure(path, enc)
        self.assertEqual(char4, 100)  # 400 chars // 4
        self.assertEqual(tik, 80)  # 400 chars // 5

    def test_measure_returns_sentinel_on_missing_file(self) -> None:
        enc = _FakeEncoding()
        char4, tik = self.module.measure(self.tmp_path / "nope.md", enc)
        self.assertEqual((char4, tik), (-1, -1))
        self.assertIn("skip:", sys.stderr.getvalue())

    def test_fmt_row_shape(self) -> None:
        row = self.module.fmt_row(100, 120, "foo.md")
        parts = row.split()
        self.assertEqual(parts[0], "100")
        self.assertEqual(parts[1], "120")
        self.assertEqual(parts[2], "+20")
        self.assertTrue(parts[3].endswith("%"))
        self.assertEqual(parts[4], "foo.md")


if __name__ == "__main__":
    unittest.main()
