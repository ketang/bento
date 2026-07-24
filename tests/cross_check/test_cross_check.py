import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "catalog" / "skills" / "cross-check" / "scripts"
COMMON = SCRIPTS / "cross_check_common.py"
DETECT = SCRIPTS / "cross-check-detect.py"
RUN = SCRIPTS / "cross-check-run.py"
BUNDLED_PROMPTS = REPO_ROOT / "catalog" / "skills" / "cross-check" / "references" / "prompts"

sys.path.insert(0, str(REPO_ROOT / "tests"))
from script_test_utils import load_module  # noqa: E402

common = load_module(COMMON)
detect = load_module(DETECT)
run = load_module(RUN)


class CommonMappingTest(unittest.TestCase):
    def test_counterpart_mapping(self) -> None:
        self.assertEqual(common.counterpart_of("claude"), "codex")
        self.assertEqual(common.counterpart_of("codex"), "claude")

    def test_counterpart_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            common.counterpart_of("gemini")

    def test_recursion_active(self) -> None:
        self.assertTrue(common.recursion_active({"CROSS_CHECK_ACTIVE": "1"}))
        self.assertFalse(common.recursion_active({}))
        for falsey in ("0", "false", "no", "", "  "):
            self.assertFalse(
                common.recursion_active({"CROSS_CHECK_ACTIVE": falsey}),
                msg=f"{falsey!r} should not activate the guard",
            )

    def test_infer_runtime(self) -> None:
        self.assertEqual(common.infer_current_runtime({"CODEX_THREAD_ID": "x"}), "codex")
        self.assertEqual(common.infer_current_runtime({"CLAUDE_SESSION_ID": "x"}), "claude")
        self.assertIsNone(
            common.infer_current_runtime({"CODEX_THREAD_ID": "x", "CLAUDECODE": "1"})
        )
        self.assertIsNone(common.infer_current_runtime({}))


class BuildCommandTest(unittest.TestCase):
    def test_codex_command_is_read_only_and_has_no_approval_flag(self) -> None:
        cmd = common.build_counterpart_command("claude", last_message_file="/tmp/x")
        self.assertEqual(cmd[:2], ["codex", "exec"])
        self.assertIn("--sandbox", cmd)
        self.assertIn("read-only", cmd)
        # codex exec has no --ask-for-approval/-a flag in supported versions.
        self.assertNotIn("-a", cmd)
        self.assertNotIn("--ask-for-approval", cmd)
        self.assertIn("/tmp/x", cmd)

    def test_claude_command_is_read_only_toolset(self) -> None:
        cmd = common.build_counterpart_command("codex")
        self.assertEqual(cmd[:2], ["claude", "-p"])
        self.assertIn("--permission-mode", cmd)
        self.assertIn("dontAsk", cmd)
        joined = " ".join(cmd)
        self.assertIn("Read,Grep,Glob", joined)
        for forbidden in ("Write", "Edit", "Bash"):
            self.assertNotIn(forbidden, joined)

    def test_model_override(self) -> None:
        self.assertIn("opus", common.build_counterpart_command("codex", model="opus"))


class PromptResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bundled_default_used_when_no_override(self) -> None:
        resolved = common.resolve_prompt(
            "plan", repo_root=None, xdg_config_home=self.root / "xdg",
            bundled_dir=BUNDLED_PROMPTS,
        )
        self.assertEqual(resolved, BUNDLED_PROMPTS / "review-plan.md")

    def test_repo_scope_override_wins(self) -> None:
        override = (
            self.root / ".agent-plugins" / "bento" / "bento" / "cross-check"
            / "prompts" / "review-code.md"
        )
        override.parent.mkdir(parents=True)
        override.write_text("custom", encoding="utf-8")
        resolved = common.resolve_prompt(
            "code", repo_root=self.root, xdg_config_home=self.root / "xdg",
            bundled_dir=BUNDLED_PROMPTS,
        )
        self.assertEqual(resolved, override)

    def test_unknown_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            common.resolve_prompt(
                "bogus", repo_root=None, xdg_config_home=None, bundled_dir=BUNDLED_PROMPTS
            )


class ComposeAndRenderTest(unittest.TestCase):
    def test_compose_delimits_and_frames_artifact(self) -> None:
        out = common.compose_prompt("INSTRUCTIONS", "DIFF BODY", artifact_type="code")
        self.assertIn("INSTRUCTIONS", out)
        self.assertIn(common.ARTIFACT_OPEN, out)
        self.assertIn(common.ARTIFACT_CLOSE, out)
        self.assertIn("DIFF BODY", out)
        self.assertIn("data to critique", out)
        # No identity id/digest → no identity block requested.
        self.assertNotIn(common.IDENTITY_OPEN, out)

    def test_compose_embeds_identity_when_supplied(self) -> None:
        out = common.compose_prompt(
            "INSTRUCTIONS", "DIFF BODY", artifact_type="code",
            artifact_id="abc123", artifact_digest="d" * 64,
        )
        self.assertIn(common.IDENTITY_OPEN, out)
        self.assertIn(common.IDENTITY_CLOSE, out)
        self.assertIn("artifact_id: abc123", out)
        self.assertIn(f"artifact_sha256: {'d' * 64}", out)
        self.assertIn("VERBATIM", out)

    def test_render_cross_mode(self) -> None:
        body = common.render_review(
            verdict="No blockers.", current_runtime="claude",
            artifact_type="plan", mode="cross",
        )
        self.assertIn("codex (independent runtime)", body)
        self.assertNotIn("DEGRADED", body)
        self.assertIn("No blockers.", body)

    def test_render_degraded_mode_has_banner(self) -> None:
        body = common.render_review(
            verdict="Found a bug.", current_runtime="claude",
            artifact_type="code", mode="degraded", truncated=True,
        )
        self.assertIn("DEGRADED", body)
        self.assertIn("PARTIAL", body)
        self.assertIn("Found a bug.", body)

    def test_render_bad_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            common.render_review(
                verdict="x", current_runtime="claude", artifact_type="plan", mode="bogus"
            )

    def test_output_path_sanitizes_slug(self) -> None:
        path = common.output_path(
            slug="my/slug", now=datetime(2026, 1, 2, 3, 4, 5), tmp_root=Path("/tmp")
        )
        self.assertEqual(path.name, "cross-check-my-slug-20260102-030405.md")

    def test_output_path_token_makes_filename_unique(self) -> None:
        now = datetime(2026, 1, 2, 3, 4, 5)
        a = common.output_path(slug="s", now=now, tmp_root=Path("/tmp"), token="aaaa")
        b = common.output_path(slug="s", now=now, tmp_root=Path("/tmp"), token="bbbb")
        self.assertNotEqual(a, b)
        self.assertEqual(a.name, "cross-check-s-20260102-030405-aaaa.md")

    def test_render_includes_artifact_digest_header(self) -> None:
        body = common.render_review(
            verdict="ok", current_runtime="claude", artifact_type="plan",
            mode="cross", artifact_digest="e" * 64,
        )
        self.assertIn(f"Artifact SHA-256:** {'e' * 64}", body)


class IdentityValidationTest(unittest.TestCase):
    ID = "a" * 32
    DIGEST = "b" * 64

    def _block(self, artifact_id: str, digest: str) -> str:
        return (
            f"{common.IDENTITY_OPEN}\n"
            f"artifact_id: {artifact_id}\n"
            f"artifact_sha256: {digest}\n"
            f"{common.IDENTITY_CLOSE}"
        )

    def test_valid_identity_accepted_and_block_stripped(self) -> None:
        verdict = f"Real findings here.\n\n{self._block(self.ID, self.DIGEST)}\n"
        ok, reason, body = common.validate_identity(
            verdict, expected_id=self.ID, expected_digest=self.DIGEST
        )
        self.assertTrue(ok, msg=reason)
        self.assertEqual(reason, "")
        self.assertEqual(body, "Real findings here.")
        self.assertNotIn(common.IDENTITY_OPEN, body)

    def test_missing_block_rejected(self) -> None:
        ok, reason, _ = common.validate_identity(
            "Some stale answer about git status.",
            expected_id=self.ID, expected_digest=self.DIGEST,
        )
        self.assertFalse(ok)
        self.assertIn("omitted", reason)

    def test_wrong_id_rejected(self) -> None:
        verdict = f"Findings.\n{self._block('f' * 32, self.DIGEST)}"
        ok, reason, _ = common.validate_identity(
            verdict, expected_id=self.ID, expected_digest=self.DIGEST
        )
        self.assertFalse(ok)
        self.assertIn("id mismatch", reason)

    def test_wrong_digest_rejected(self) -> None:
        verdict = f"Findings.\n{self._block(self.ID, 'c' * 64)}"
        ok, reason, _ = common.validate_identity(
            verdict, expected_id=self.ID, expected_digest=self.DIGEST
        )
        self.assertFalse(ok)
        self.assertIn("digest mismatch", reason)

    def test_identity_only_no_findings_rejected(self) -> None:
        verdict = f"{self._block(self.ID, self.DIGEST)}\n"
        ok, reason, _ = common.validate_identity(
            verdict, expected_id=self.ID, expected_digest=self.DIGEST
        )
        self.assertFalse(ok)
        self.assertIn("no findings", reason)

    def test_digest_matches_computed(self) -> None:
        text = "PLAN CONTENT"
        self.assertEqual(
            common.compute_digest(text),
            __import__("hashlib").sha256(text.encode()).hexdigest(),
        )

    def test_new_artifact_id_unguessable_and_unique(self) -> None:
        a, b = common.new_artifact_id(), common.new_artifact_id()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 16)


class DetectAssessTest(unittest.TestCase):
    def test_counterpart_absent_recommends_fallback(self) -> None:
        result = detect.assess(
            "claude", which=lambda _n: None, auth=lambda _r: True
        )
        self.assertFalse(result["counterpart_on_path"])
        self.assertEqual(result["recommended_path"], "fallback")

    def test_present_unauthed_recommends_fallback(self) -> None:
        result = detect.assess(
            "claude", which=lambda _n: "/usr/bin/codex", auth=lambda _r: False
        )
        self.assertTrue(result["counterpart_on_path"])
        self.assertFalse(result["counterpart_authenticated"])
        self.assertEqual(result["recommended_path"], "fallback")

    def test_present_authed_recommends_cross(self) -> None:
        result = detect.assess(
            "codex", which=lambda _n: "/usr/bin/claude", auth=lambda _r: True
        )
        self.assertEqual(result["counterpart"], "claude")
        self.assertEqual(result["recommended_path"], "cross")

    def test_help_exits_zero(self) -> None:
        proc = subprocess.run(
            [str(DETECT), "--help"], capture_output=True, text=True, check=False
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--current-runtime", proc.stdout)


def _clean_env(**overrides) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in (
        "CROSS_CHECK_ACTIVE", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID", "CLAUDECODE"
    )}
    env.update(overrides)
    return env


class RunDryRunTest(unittest.TestCase):
    def _dry_run(self, runtime: str) -> str:
        proc = subprocess.run(
            [str(RUN), "--current-runtime", runtime, "--artifact-type", "plan",
             "--slug", "x", "--dry-run"],
            input="", capture_output=True, text=True, check=False, env=_clean_env(),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return proc.stdout

    def test_dry_run_claude_current_shows_read_only_codex(self) -> None:
        out = self._dry_run("claude")
        self.assertIn("--sandbox", out)
        self.assertIn("read-only", out)
        self.assertNotIn("--ask-for-approval", out)

    def test_dry_run_codex_current_shows_read_only_claude(self) -> None:
        out = self._dry_run("codex")
        self.assertIn("dontAsk", out)
        self.assertIn("Read,Grep,Glob", out)


class RunRenderOnlyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_render_only_writes_degraded_file_from_stdin(self) -> None:
        proc = subprocess.run(
            [str(RUN), "--current-runtime", "claude", "--artifact-type", "code",
             "--slug", "fallback-demo", "--render-only", "--mode", "degraded"],
            input="A finding from the fallback reviewer.",
            capture_output=True, text=True, check=False,
            env=_clean_env(CROSS_CHECK_TMP_ROOT=str(self.out)),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        written = Path(proc.stdout.strip())
        self.assertTrue(written.is_file())
        text = written.read_text(encoding="utf-8")
        self.assertIn("DEGRADED", text)
        self.assertIn("A finding from the fallback reviewer.", text)


class WriteReviewCollisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self._prev = os.environ.get("CROSS_CHECK_TMP_ROOT")
        os.environ["CROSS_CHECK_TMP_ROOT"] = str(self.out)

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("CROSS_CHECK_TMP_ROOT", None)
        else:
            os.environ["CROSS_CHECK_TMP_ROOT"] = self._prev
        self.tmp.cleanup()

    def test_same_second_same_slug_does_not_clobber(self) -> None:
        now = datetime(2026, 1, 2, 3, 4, 5)
        kwargs = dict(
            verdict="x", current_runtime="claude", artifact_type="plan",
            mode="degraded", slug="dup", scope=None, truncated=False, now=now,
        )
        first = run._write_review(**kwargs)
        second = run._write_review(**kwargs)
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file() and second.is_file())
        self.assertEqual(len(list(self.out.glob("cross-check-dup-*.md"))), 2)


class RunArtifactErrorTest(unittest.TestCase):
    def _run(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(RUN), "--current-runtime", "claude", "--artifact-type", "plan",
             "--slug", "x", "--artifact", "/no/such/cross-check/file", *extra],
            capture_output=True, text=True, check=False, env=_clean_env(),
        )

    def test_unreadable_artifact_normal_path_exits_usage(self) -> None:
        proc = self._run()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read artifact", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_unreadable_artifact_render_only_exits_usage(self) -> None:
        proc = self._run("--render-only")
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)


class RunCrossIntegrationTest(unittest.TestCase):
    """Stub the counterpart binary on PATH to exercise run_cross end-to-end."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.out = self.root / "out"
        self.out.mkdir()
        self.systmp = self.root / "systmp"  # TMPDIR for codex -o scratch files
        self.systmp.mkdir()
        self.xdg = self.root / "xdg"  # empty: no home-scope override
        self.cwd = self.root / "work"
        self.cwd.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _install_stub(self, name: str, body: str) -> None:
        stub = self.bin / name
        stub.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        stub.chmod(0o755)

    # Reads the prompt on stdin and extracts this run's identity id + digest so a
    # compliant reviewer stub can echo them back. `_PARSE` leaves `aid`/`sha` set.
    _PARSE = (
        "import re, sys\n"
        "p = sys.stdin.read()\n"
        "aid = re.search(r'artifact_id:\\s*(\\S+)', p).group(1)\n"
        "sha = re.search(r'artifact_sha256:\\s*(\\S+)', p).group(1)\n"
    )

    @staticmethod
    def _identity(aid_expr: str = "aid", sha_expr: str = "sha") -> str:
        return (
            "'\\n\\n<<<CROSS_CHECK_IDENTITY>>>\\n"
            "artifact_id: ' + %s + '\\n"
            "artifact_sha256: ' + %s + '\\n"
            "<<<END_CROSS_CHECK_IDENTITY>>>\\n'" % (aid_expr, sha_expr)
        )

    def _codex_stub(self, verdict: str, aid_expr: str = "aid", sha_expr: str = "sha") -> str:
        return (
            self._PARSE
            + "argv = sys.argv\n"
            + f"open(argv[argv.index('-o') + 1], 'w').write('{verdict}' + "
            + self._identity(aid_expr, sha_expr)
            + ")\nsys.exit(0)\n"
        )

    def _run(self, runtime: str) -> subprocess.CompletedProcess[str]:
        env = _clean_env(
            PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            CROSS_CHECK_TMP_ROOT=str(self.out),
            XDG_CONFIG_HOME=str(self.xdg),
            TMPDIR=str(self.systmp),
        )
        return subprocess.run(
            [str(RUN), "--current-runtime", runtime, "--artifact-type", "plan",
             "--slug", "demo"],
            input="PLAN CONTENT", capture_output=True, text=True, check=False,
            cwd=str(self.cwd), env=env,
        )

    def test_codex_success_writes_review_and_sets_recursion_env(self) -> None:
        # current=claude → counterpart=codex. Stub writes verdict to -o file and
        # asserts CROSS_CHECK_ACTIVE was exported into its environment.
        self._install_stub("codex", (
            "import os\n"
            "assert os.environ.get('CROSS_CHECK_ACTIVE') == '1', 'recursion env not set'\n"
            + self._codex_stub("VERDICT: looks fine")
        ))
        proc = self._run("claude")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        files = list(self.out.glob("cross-check-demo-*.md"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8")
        self.assertIn("VERDICT: looks fine", text)
        self.assertIn("codex (independent runtime)", text)
        # The identity block is protocol scaffolding, stripped from the file; the
        # verified digest is recorded in the header instead.
        self.assertNotIn(common.IDENTITY_OPEN, text)
        self.assertIn("Artifact SHA-256:", text)

    def test_codex_success_cleans_up_last_message_temp_file(self) -> None:
        self._install_stub("codex", self._codex_stub("VERDICT"))
        proc = self._run("claude")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        leftover = list(self.systmp.glob("cross-check-last-*"))
        self.assertEqual(leftover, [], f"temp -o files not cleaned: {leftover}")

    def test_stale_codex_output_rejected_as_fallback(self) -> None:
        # Simulates the filed bug: a stale/unrelated response whose identity does
        # not match this run (wrong id). Must exit fallback-required, not success.
        self._install_stub("codex", self._codex_stub(
            "I do not have a shell tool; send me git log.",
            aid_expr="'deadbeef' * 4",  # wrong, unguessable-length but not ours
        ))
        proc = self._run("claude")
        self.assertEqual(proc.returncode, 4, msg=proc.stdout + proc.stderr)
        self.assertIn("identity", proc.stderr.lower())
        self.assertEqual(list(self.out.glob("cross-check-demo-*.md")), [])

    def test_mismatched_digest_codex_output_rejected(self) -> None:
        # Correct id echoed but a digest for a different artifact → reject.
        self._install_stub("codex", self._codex_stub(
            "Review of some other artifact.", sha_expr="'0' * 64",
        ))
        proc = self._run("claude")
        self.assertEqual(proc.returncode, 4, msg=proc.stdout + proc.stderr)
        self.assertIn("digest mismatch", proc.stderr.lower())

    def test_missing_identity_block_rejected(self) -> None:
        # A reviewer that never echoes the identity block (e.g. cached plain text).
        self._install_stub("codex", (
            "import sys\nargv = sys.argv\n"
            "open(argv[argv.index('-o') + 1], 'w').write('bare answer, no identity')\n"
            "sys.exit(0)\n"
        ))
        proc = self._run("claude")
        self.assertEqual(proc.returncode, 4, msg=proc.stdout + proc.stderr)
        self.assertIn("identity", proc.stderr.lower())

    def test_claude_null_result_requests_fallback(self) -> None:
        # A null/non-string "result" must behave like empty output, not crash.
        self._install_stub("claude", (
            "import json, sys\nsys.stdin.read()\n"
            "print(json.dumps({'result': None}))\nsys.exit(0)\n"
        ))
        proc = self._run("codex")
        self.assertEqual(proc.returncode, 4, msg=proc.stdout + proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_claude_success_parses_json_result(self) -> None:
        # current=codex → counterpart=claude. Stub prints JSON result on stdout,
        # echoing this run's identity so validation accepts it.
        self._install_stub("claude", (
            "import json\n"
            + self._PARSE
            + "result = 'VERDICT: from claude' + "
            + self._identity()
            + "\nprint(json.dumps({'result': result}))\nsys.exit(0)\n"
        ))
        proc = self._run("codex")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        files = list(self.out.glob("cross-check-demo-*.md"))
        self.assertEqual(len(files), 1)
        self.assertIn("VERDICT: from claude", files[0].read_text(encoding="utf-8"))

    def test_nonzero_counterpart_requests_fallback(self) -> None:
        self._install_stub("codex", "import sys\nsys.exit(1)\n")
        proc = self._run("claude")
        self.assertEqual(proc.returncode, 4)
        self.assertIn("fallback", proc.stderr.lower())

    def test_empty_verdict_requests_fallback(self) -> None:
        self._install_stub("codex", (
            "import sys\nargv = sys.argv\n"
            "open(argv[argv.index('-o') + 1], 'w').write('')\nsys.exit(0)\n"
        ))
        proc = self._run("claude")
        self.assertEqual(proc.returncode, 4)

    def test_recursion_guard_skips(self) -> None:
        self._install_stub("codex", "import sys\nsys.exit(0)\n")
        env = _clean_env(
            PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            CROSS_CHECK_TMP_ROOT=str(self.out),
            XDG_CONFIG_HOME=str(self.xdg),
            CROSS_CHECK_ACTIVE="1",
        )
        proc = subprocess.run(
            [str(RUN), "--current-runtime", "claude", "--artifact-type", "plan",
             "--slug", "demo"],
            input="PLAN", capture_output=True, text=True, check=False,
            cwd=str(self.cwd), env=env,
        )
        self.assertEqual(proc.returncode, 3)


if __name__ == "__main__":
    unittest.main()
