import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "catalog" / "hooks" / "bento" / "claude" / "scripts"
CORPUS_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "shell_segments_corpus.json"

sys.path.insert(0, str(SCRIPTS_DIR))
from shell_segments import SegmentError, command_segments, command_segments_with_env  # noqa: E402


def _load_corpus() -> list[dict]:
    return json.loads(CORPUS_FIXTURE.read_text(encoding="utf-8"))


class ShellSegmentsCorpusTest(unittest.TestCase):
    def test_corpus(self) -> None:
        rows = _load_corpus()
        self.assertGreaterEqual(len(rows), 39)
        for i, row in enumerate(rows, start=1):
            command = row["command"]
            expected = row["expected"]
            with self.subTest(row=i, command=command):
                if expected == "ERR":
                    with self.assertRaises(SegmentError):
                        command_segments(command)
                else:
                    self.assertEqual(command_segments(command), expected)

    @unittest.skipUnless(shutil.which("bash"), "bash not on PATH")
    def test_corpus_is_valid_bash(self) -> None:
        for i, row in enumerate(_load_corpus(), start=1):
            if row["expected"] == "ERR":
                continue
            command = row["command"]
            with self.subTest(row=i, command=command):
                result = subprocess.run(
                    ["bash", "-n"], input=command, capture_output=True, text=True,
                )
                self.assertEqual(
                    result.returncode, 0,
                    f"row {i} is not valid bash: {result.stderr.strip()}",
                )


class ShellSegmentsAdditionalCasesTest(unittest.TestCase):
    def test_process_substitution_body_is_a_true_positive(self) -> None:
        segments = command_segments("cat <(git merge x)")
        self.assertIn(["git", "merge", "x"], segments)

    def test_unterminated_heredoc_drops_body_to_end_of_input(self) -> None:
        segments = command_segments("cat <<EOF\ngit push --force")
        self.assertEqual(segments, [["cat"]])

    def test_wrapped_git_segments_are_unwrapped(self) -> None:
        self.assertEqual(command_segments("rtk git merge foo"), [["git", "merge", "foo"]])
        self.assertEqual(command_segments("command git merge foo"), [["git", "merge", "foo"]])
        self.assertEqual(
            command_segments("env GIT_X=1 git merge foo"), [["git", "merge", "foo"]],
        )
        self.assertEqual(command_segments("exec git merge foo"), [["git", "merge", "foo"]])

    def test_command_with_flag_is_not_stripped_as_wrapper(self) -> None:
        # 'command' is only the wrapper builtin when the next word does not
        # start with '-'; 'command -v git' is a real (non-mutating) use.
        self.assertEqual(command_segments("command -v git"), [["command", "-v", "git"]])

    def test_command_segments_with_env_exposes_stripped_assignments(self) -> None:
        result = command_segments_with_env("env GIT_CONFIG_COUNT=1 git merge foo")
        self.assertEqual(result, [({"GIT_CONFIG_COUNT": "1"}, ["git", "merge", "foo"])])

    def test_deep_substitution_nesting_raises(self) -> None:
        command = "echo " + "$(" * 9 + "git merge x" + ")" * 9
        with self.assertRaises(SegmentError):
            command_segments(command)

    def test_deep_plain_grouping_nesting_raises_segment_error(self) -> None:
        # Code review: plain grouping '(...)' must count toward the same
        # depth cap as $(...)/${...}, not recurse unboundedly and blow the
        # Python call stack with a raw RecursionError.
        command = "echo " + "(" * 2000 + "git merge x" + ")" * 2000
        with self.assertRaises(SegmentError):
            command_segments(command)

    def test_paren_pattern_inside_double_bracket_test_is_not_a_subshell(self) -> None:
        # Code review: '(...)' inside [[ ... ]] is extended-pattern/grouping
        # syntax (an alternation pattern, e.g. after ==/!=), never a
        # subshell -- nothing inside a [[ ]] test ever runs as a command.
        # A prior version fabricated a ['git', 'merge'] segment here.
        segments = command_segments("[[ $x == (git merge) ]]")
        self.assertEqual(segments, [["[[", "$x", "==", "(git merge)", "]]"]])
        self.assertNotIn(["git", "merge"], segments)

    def test_extglob_pattern_inside_double_bracket_test_is_not_a_subshell(self) -> None:
        segments = command_segments("[[ $x == @(git merge foo) ]]")
        self.assertEqual(
            segments, [["[[", "$x", "==", "@(git merge foo)", "]]"]],
        )


if __name__ == "__main__":
    unittest.main()
