import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests.script_test_utils import git, run, write


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/wire-land-verifier/scripts/wire-land-verifier.py"

MANIFEST_REL = ".agent-plugins/bento/bento/land-work/verifier.json"


class WireLandVerifierTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Wire Test")
        git(self.repo, "config", "user.email", "wire@example.com")
        write(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def wire(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(SCRIPT), *args], self.repo, check=check)

    def payload(self, result: subprocess.CompletedProcess[str]) -> dict:
        return json.loads(result.stdout)

    def passing_check(self) -> str:
        """A repo-local script that behaves like a real (passing) gate command."""
        gate = self.repo / "gate.sh"
        write(gate, "#!/bin/sh\necho running gate\nexit 0\n")
        gate.chmod(0o755)
        return "unit tests::./gate.sh"

    def failing_check(self) -> str:
        gate = self.repo / "redgate.sh"
        write(gate, "#!/bin/sh\necho broken\nexit 3\n")
        gate.chmod(0o755)
        return "unit tests::./redgate.sh"


class DiscoverTest(WireLandVerifierTestBase):
    def test_ranks_aggregate_make_targets_above_narrow_ones(self) -> None:
        write(self.repo / "Makefile", "fmt:\n\techo fmt\n\nci:\n\techo ci\n")
        payload = self.payload(self.wire("discover"))
        commands = [c["command"] for c in payload["candidates"]]
        self.assertIn("make ci", commands)
        self.assertIn("make fmt", commands)
        self.assertLess(commands.index("make ci"), commands.index("make fmt"))

    def test_reads_package_json_scripts_and_justfile(self) -> None:
        write(
            self.repo / "package.json",
            json.dumps({"scripts": {"test": "vitest run", "dev": "vite"}}),
        )
        write(self.repo / "justfile", "check:\n    echo hi\n")
        payload = self.payload(self.wire("discover"))
        commands = [c["command"] for c in payload["candidates"]]
        self.assertIn("npm run test", commands)
        self.assertIn("just check", commands)

    def test_reads_github_workflow_run_steps(self) -> None:
        write(
            self.repo / ".github/workflows/ci.yml",
            "jobs:\n  build:\n    steps:\n      - run: pytest -q\n",
        )
        payload = self.payload(self.wire("discover"))
        commands = [c["command"] for c in payload["candidates"]]
        self.assertIn("pytest -q", commands)

    def test_quoted_run_step_does_not_crash_discovery(self) -> None:
        """An unpaired-quote strip made shlex raise ValueError as a traceback."""
        write(
            self.repo / ".github/workflows/ci.yml",
            'jobs:\n  build:\n    steps:\n'
            '      - run: npm test -- --grep "smoke"\n'
            "      - run: make check\n",
        )
        payload = self.payload(self.wire("discover"))
        commands = [c["command"] for c in payload["candidates"]]
        self.assertIn('npm test -- --grep "smoke"', commands)
        self.assertIn("make check", commands)

    def test_unparseable_run_step_is_skipped_not_fatal(self) -> None:
        write(
            self.repo / ".github/workflows/ci.yml",
            "jobs:\n  build:\n    steps:\n"
            "      - run: echo it's broken \"\n"
            "      - run: make check\n",
        )
        payload = self.payload(self.wire("discover"))
        self.assertIn("make check", [c["command"] for c in payload["candidates"]])

    def test_discover_never_writes_anything(self) -> None:
        write(self.repo / "Makefile", "ci:\n\techo ci\n")
        before = git(self.repo, "status", "--porcelain").stdout
        self.wire("discover")
        self.assertFalse((self.repo / MANIFEST_REL).exists())
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, before)

    def test_empty_repo_reports_no_candidates_without_failing(self) -> None:
        payload = self.payload(self.wire("discover"))
        self.assertEqual(payload["candidates"], [])


class DraftTest(WireLandVerifierTestBase):
    def test_draft_stages_files_without_installing_them(self) -> None:
        payload = self.payload(self.wire("draft", "--check", self.passing_check()))
        self.assertFalse((self.repo / MANIFEST_REL).exists())
        self.assertFalse((self.repo / "scripts/land-work-verifier.py").exists())
        self.assertIn("wrapper_body", payload)
        self.assertIn("manifest_body", payload)
        manifest = json.loads(payload["manifest_body"])
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["verified_noop"], [])
        self.assertEqual(manifest["command"], ["./scripts/land-work-verifier.py"])

    def test_draft_requires_at_least_one_check(self) -> None:
        result = self.wire("draft", check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_draft_rejects_no_op_commands(self) -> None:
        for command in ("true", ":", "echo ok", "exit 0"):
            with self.subTest(command=command):
                result = self.wire("draft", "--check", f"gate::{command}", check=False)
                self.assertNotEqual(result.returncode, 0, command)
                self.assertIn("no-op", (result.stderr + result.stdout).lower())

    def test_draft_rejects_no_ops_hidden_behind_env_prefixes(self) -> None:
        """`env true` reached a full install before; a prefix is not a gate."""
        for command in (
            "env true",
            "env FOO=1 true",
            "nohup true",
            "nice -n 5 true",
            "command true",
            "time true",
        ):
            with self.subTest(command=command):
                result = self.wire("draft", "--check", f"gate::{command}", check=False)
                self.assertNotEqual(result.returncode, 0, command)
                self.assertIn("no-op", (result.stderr + result.stdout).lower())

    def test_draft_rejects_no_ops_behind_clustered_shell_flags(self) -> None:
        """A bare `"-c" in argv` test missed all of these."""
        for command in (
            "bash -lc true",
            "sh -cx true",
            "bash -ec true",
            "sh -c -- true",
            "sh -c ''",
        ):
            with self.subTest(command=command):
                result = self.wire("draft", "--check", f"gate::{command}", check=False)
                self.assertNotEqual(result.returncode, 0, command)

    def test_draft_rejects_trivial_interpreter_one_liners(self) -> None:
        for command in ("python3 -c pass", "python3 -c ''", "node -e ''"):
            with self.subTest(command=command):
                result = self.wire("draft", "--check", f"gate::{command}", check=False)
                self.assertNotEqual(result.returncode, 0, command)

    def test_draft_reports_that_no_op_screening_is_best_effort(self) -> None:
        """The tool must not claim a completeness no denylist can deliver."""
        payload = self.payload(self.wire("draft", "--check", self.passing_check()))
        self.assertIn("caveat", payload)
        self.assertIn("best-effort", payload["caveat"])

    def test_draft_carries_forward_existing_verified_noop_exemptions(self) -> None:
        write(
            self.repo / MANIFEST_REL,
            json.dumps(
                {
                    "schema_version": 1,
                    "command": ["./scripts/old.sh"],
                    "verified_noop": [
                        {"path": "docs/generated.json", "reason": "producer-verified"},
                    ],
                }
            ),
        )
        payload = self.payload(self.wire("draft", "--check", self.passing_check()))
        manifest = json.loads(payload["manifest_body"])
        expected = [{"path": "docs/generated.json", "reason": "producer-verified"}]
        self.assertEqual(manifest["verified_noop"], expected)
        self.assertEqual(payload["carried_verified_noop"], expected)

    def test_draft_refuses_to_carry_forward_invalid_verified_noop_shapes(self) -> None:
        """bento-ei1p round 4: globs/strings satisfy no real contract land-work checks."""
        write(
            self.repo / MANIFEST_REL,
            json.dumps(
                {
                    "schema_version": 1,
                    "command": ["./scripts/old.sh"],
                    "verified_noop": ["docs/**", "*.md"],
                }
            ),
        )
        result = self.wire("draft", "--check", self.passing_check(), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verified_noop", result.stderr + result.stdout)

    def test_draft_refuses_a_verified_noop_path_that_normalizes_to_empty(self) -> None:
        """bento-ei1p round 5: '.' passes a naive check but land-work rejects it."""
        write(
            self.repo / MANIFEST_REL,
            json.dumps(
                {
                    "schema_version": 1,
                    "command": ["./scripts/old.sh"],
                    "verified_noop": [{"path": ".", "reason": "why"}],
                }
            ),
        )
        result = self.wire("draft", "--check", self.passing_check(), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verified_noop", result.stderr + result.stdout)

    def test_draft_refuses_duplicate_verified_noop_paths_once_normalized(self) -> None:
        write(
            self.repo / MANIFEST_REL,
            json.dumps(
                {
                    "schema_version": 1,
                    "command": ["./scripts/old.sh"],
                    "verified_noop": [
                        {"path": "docs/a.md", "reason": "why"},
                        {"path": "./docs/a.md", "reason": "why again"},
                    ],
                }
            ),
        )
        result = self.wire("draft", "--check", self.passing_check(), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verified_noop", result.stderr + result.stdout)

    def test_draft_refuses_wrapper_path_equal_to_the_manifest_path(self) -> None:
        """bento-ei1p round 5: apply would overwrite the wrapper with the manifest."""
        result = self.wire(
            "draft", "--check", self.passing_check(),
            "--wrapper-path", MANIFEST_REL, check=False,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_draft_refuses_a_directory_like_wrapper_path(self) -> None:
        result = self.wire(
            "draft", "--check", self.passing_check(),
            "--wrapper-path", ".", check=False,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_draft_rejects_unresolvable_executable(self) -> None:
        result = self.wire(
            "draft", "--check", "gate::./definitely-not-here.sh", check=False
        )
        self.assertNotEqual(result.returncode, 0)

    def test_draft_accepts_bare_command_as_its_own_name(self) -> None:
        gate = self.repo / "gate.sh"
        write(gate, "#!/bin/sh\nexit 0\n")
        gate.chmod(0o755)
        payload = self.payload(self.wire("draft", "--check", "./gate.sh"))
        self.assertEqual([c["name"] for c in payload["checks"]], ["./gate.sh"])

    def test_custom_wrapper_path_is_reflected_in_manifest(self) -> None:
        payload = self.payload(
            self.wire(
                "draft",
                "--check",
                self.passing_check(),
                "--wrapper-path",
                "tools/verify.py",
            )
        )
        manifest = json.loads(payload["manifest_body"])
        self.assertEqual(manifest["command"], ["./tools/verify.py"])


class ValidateTest(WireLandVerifierTestBase):
    def test_validate_runs_the_staged_wrapper_and_reports_schema_valid_output(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        payload = self.payload(self.wire("validate"))
        self.assertTrue(payload["schema_valid"])
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["selected_check_count"], 1)

    def test_validate_reports_failed_status_for_a_red_gate_but_stays_schema_valid(self) -> None:
        self.wire("draft", "--check", self.failing_check())
        result = self.wire("validate", check=False)
        payload = self.payload(result)
        self.assertTrue(payload["schema_valid"])
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["selected_check_count"], 1)

    def test_validate_requires_a_draft(self) -> None:
        result = self.wire("validate", check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_validate_does_not_install_anything(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        self.assertFalse((self.repo / MANIFEST_REL).exists())


class ApplyTest(WireLandVerifierTestBase):
    def test_apply_installs_wrapper_and_manifest_after_validation(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        payload = self.payload(self.wire("apply"))
        manifest_path = self.repo / MANIFEST_REL
        wrapper_path = self.repo / "scripts/land-work-verifier.py"
        self.assertTrue(manifest_path.exists())
        self.assertTrue(wrapper_path.exists())
        self.assertTrue(wrapper_path.stat().st_mode & 0o111)
        self.assertEqual(json.loads(manifest_path.read_text())["schema_version"], 1)
        self.assertTrue(payload["applied"])

    def test_apply_refuses_without_a_validation_receipt(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / MANIFEST_REL).exists())

    def test_apply_refuses_when_the_draft_changed_after_validation(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        other = self.repo / "gate2.sh"
        write(other, "#!/bin/sh\nexit 0\n")
        other.chmod(0o755)
        self.wire("draft", "--check", "other::./gate2.sh")
        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / MANIFEST_REL).exists())

    def test_apply_refuses_a_wrapper_swapped_out_after_validation(self) -> None:
        """The fingerprint check compared state.json to itself, so it never fired.

        Tampering with the staged wrapper after a legitimate validate used to
        install the tampered file.
        """
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        staged = self.repo / ".git/bento/wire-land-verifier/wrapper"
        self.assertTrue(staged.is_file())
        write(
            staged,
            '#!/bin/sh\necho \'{"schema_version":1,"status":"passed",'
            '"selected_checks":["fake"]}\'\n',
        )
        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / MANIFEST_REL).exists())
        self.assertFalse((self.repo / "scripts/land-work-verifier.py").exists())

    def test_apply_refuses_a_tampered_staged_manifest(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        staged = self.repo / ".git/bento/wire-land-verifier/verifier.json"
        write(staged, '{"schema_version": 1, "command": ["./evil.sh"]}\n')
        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / MANIFEST_REL).exists())

    def test_apply_refuses_to_clobber_an_existing_manifest_without_force(self) -> None:
        write(self.repo / MANIFEST_REL, '{"schema_version": 1, "command": ["./x"]}\n')
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.wire("apply", "--force")
        manifest = json.loads((self.repo / MANIFEST_REL).read_text())
        self.assertEqual(manifest["command"], ["./scripts/land-work-verifier.py"])

    def test_installed_wrapper_satisfies_the_land_work_verifier_contract(self) -> None:
        """End-to-end: land-work's own runner must accept what we install."""
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        self.wire("apply")
        runner = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-run-verifier.py"
        write(self.repo / "change.txt", "changed\n")
        git(self.repo, "add", "change.txt")
        git(self.repo, "commit", "-m", "change")
        base_sha = git(self.repo, "rev-parse", "HEAD~1").stdout.strip()
        head_sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        result = run(
            [
                str(runner),
                "--repo-root",
                str(self.repo),
                "--candidate",
                str(self.repo),
                "--base-sha",
                base_sha,
                "--head-sha",
                head_sha,
            ],
            self.repo,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        diagnostics = json.loads(result.stdout)
        self.assertEqual(diagnostics["verifier_status"], "passed")
        self.assertGreaterEqual(diagnostics["selected_check_count"], 1)


class RepoRootTest(WireLandVerifierTestBase):
    """land-work reads the manifest from the repo root only (MEDIUM 5)."""

    def wire_from(
        self, cwd: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return run([str(SCRIPT), *args], cwd, check=check)

    def test_running_from_a_subdirectory_is_refused(self) -> None:
        sub = self.repo / "sub"
        sub.mkdir()
        for command in ("discover", "draft", "validate", "apply"):
            with self.subTest(command=command):
                args = ["draft", "--check", "gate::./gate.sh"]
                args = args if command == "draft" else [command]
                result = self.wire_from(sub, *args, check=False)
                self.assertNotEqual(result.returncode, 0, command)
                self.assertIn("root", result.stderr + result.stdout)

    def test_subdirectory_run_installs_nothing_anywhere(self) -> None:
        sub = self.repo / "sub"
        sub.mkdir()
        gate = self.repo / "gate.sh"
        write(gate, "#!/bin/sh\nexit 0\n")
        gate.chmod(0o755)
        self.wire_from(sub, "draft", "--check", "gate::../gate.sh", check=False)
        self.assertFalse((sub / MANIFEST_REL).exists())
        self.assertFalse((self.repo / MANIFEST_REL).exists())


class ValidateStagingSafetyTest(WireLandVerifierTestBase):
    """validate must never read, replace, or restore the user's wrapper path."""

    def existing_wrapper(self, mode: int = 0o600) -> Path:
        target = self.repo / "scripts/land-work-verifier.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        write(target, "#!/usr/bin/env python3\n# hand-written by the user\n")
        target.chmod(mode)
        return target

    def test_validate_leaves_an_existing_wrapper_untouched(self) -> None:
        """MEDIUM 7: re-wiring must not refuse, and must not touch the file."""
        target = self.existing_wrapper(0o600)
        self.wire("draft", "--check", self.passing_check())
        result = self.wire("validate", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("hand-written", target.read_text())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_rewiring_an_applied_repo_validates_again_without_force(self) -> None:
        """MEDIUM 7: the second wiring must not herd the user onto --force."""
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        self.wire("apply")
        self.wire("draft", "--check", self.passing_check())
        result = self.wire("validate", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validate_runs_from_a_scratch_sibling_not_the_target(self) -> None:
        target = self.repo / "scripts/land-work-verifier.py"
        probe = self.repo / "probe.sh"
        write(probe, f"#!/bin/sh\ntest ! -e {target} || exit 7\nexit 0\n")
        probe.chmod(0o755)
        self.wire("draft", "--check", "gate::./probe.sh")
        result = self.wire("validate", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_killed_validate_leaves_the_user_file_intact(self) -> None:
        """HIGH 5: SIGTERM mid-gate must not strand the generated wrapper."""
        target = self.existing_wrapper(0o600)
        slow = self.repo / "slow.sh"
        write(slow, "#!/bin/sh\nsleep 30\n")
        slow.chmod(0o755)
        self.wire("draft", "--check", "gate::./slow.sh")
        process = subprocess.Popen(
            [str(SCRIPT), "validate"],
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not list(
                (self.repo / "scripts").glob(".land-work-verifier.*.tmp.py")
            ):
                time.sleep(0.1)
            process.terminate()
        finally:
            process.wait(timeout=20)
        self.assertIn("hand-written", target.read_text())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_sigterm_to_validate_kills_the_gates_backgrounded_child(self) -> None:
        """bento-ei1p round 7: start_new_session detaches the gate into its own
        process group -- SIGTERM to just the outer CLI process must still
        reach it via the SIGTERM handler, not only a reported --timeout."""
        marker = self.repo / "child.pid"
        script = self.repo / "backgrounder.sh"
        write(
            script,
            "#!/bin/sh\n"
            f"sh -c 'echo $$ > {marker}; sleep 30' &\n"
            "sleep 30\n",
        )
        script.chmod(0o755)
        self.wire("draft", "--check", "gate::./backgrounder.sh")
        process = subprocess.Popen(
            [str(SCRIPT), "validate"],
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not (
                marker.exists() and marker.read_text().strip()
            ):
                time.sleep(0.1)
            child_pid = marker.read_text().strip()
            process.terminate()
        finally:
            process.wait(timeout=20)

        self.assertIsNotNone(child_pid)
        time.sleep(1)
        alive = subprocess.run(["kill", "-0", child_pid]).returncode == 0
        self.assertFalse(alive, "backgrounded child survived SIGTERM to the parent")

    def test_a_later_validate_sweeps_a_dead_runs_scratch_copy(self) -> None:
        stale = self.repo / "scripts/.land-work-verifier.999999999.tmp.py"
        stale.parent.mkdir(parents=True, exist_ok=True)
        write(stale, "#!/bin/sh\nexit 0\n")
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        self.assertFalse(stale.exists())

    def test_validate_cleans_up_directories_it_created(self) -> None:
        self.wire(
            "draft",
            "--check",
            self.passing_check(),
            "--wrapper-path",
            "tools/deep/verify.py",
        )
        self.wire("validate")
        self.assertFalse((self.repo / "tools").exists())


class SymlinkTargetTest(WireLandVerifierTestBase):
    """MEDIUM 6: a symlink at an install path must not be written through."""

    def dangling_symlink(self) -> Path:
        target = self.repo / "scripts/land-work-verifier.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        (self.repo / "tools").mkdir()
        target.symlink_to("../tools/real-verifier.py")
        return target

    def test_validate_does_not_write_through_a_dangling_symlink(self) -> None:
        link = self.dangling_symlink()
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        self.assertTrue(link.is_symlink())
        self.assertEqual(list((self.repo / "tools").iterdir()), [])

    def test_apply_refuses_a_dangling_symlink_without_force(self) -> None:
        link = self.dangling_symlink()
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr + result.stdout)
        self.assertTrue(link.is_symlink())
        self.assertEqual(list((self.repo / "tools").iterdir()), [])

    def test_apply_force_replaces_the_symlink_instead_of_following_it(self) -> None:
        link = self.dangling_symlink()
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        self.wire("apply", "--force")
        self.assertFalse(link.is_symlink())
        self.assertIn("REPO_ROOT", link.read_text())
        self.assertEqual(list((self.repo / "tools").iterdir()), [])


class ValidateReceiptTest(WireLandVerifierTestBase):
    """LOW 4: the receipt must fingerprint the bytes validate actually ran."""

    def staged_wrapper(self) -> Path:
        git_dir = run(["git", "rev-parse", "--absolute-git-dir"], self.repo).stdout
        return Path(git_dir.strip()) / "bento/wire-land-verifier/wrapper"

    def test_apply_accepts_a_draft_edited_before_validation(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        wrapper = self.staged_wrapper()
        wrapper.write_text(wrapper.read_text() + "# user tweak\n")
        payload = self.payload(self.wire("validate"))
        self.assertTrue(payload["draft_edited"])
        self.wire("apply")
        installed = self.repo / "scripts/land-work-verifier.py"
        self.assertIn("# user tweak", installed.read_text())

    def test_apply_still_rejects_a_draft_edited_after_validation(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        wrapper = self.staged_wrapper()
        wrapper.write_text(wrapper.read_text() + "# swapped in later\n")
        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tampered", result.stderr + result.stdout)


class PrefixScreeningTest(WireLandVerifierTestBase):
    """HIGH 1-3, LOW 8: screening must resolve through prefix commands."""

    NO_OPS = (
        "timeout 5 true",
        "sudo true",
        "xargs true",
        "doas true",
        "chronic true",
        "retry true",
        "env -u FOO true",
        "env --unset=FOO true",
        "timeout -k 1 5 true",
        "timeout 5 -- true",
        "sudo -u root timeout 5 true",
        "env env env env env env env env env true",
        "uv run true",
        "npm exec true",
        "bundle exec true",
        "flock /tmp/lock true",
        "flock -c true",
        "watch true",
        "setarch x86_64 true",
        "bash -o pipefail -c true",
        "bash --rcfile /dev/null -c true",
        "bash -eo pipefail -c true",
        "bash -o -c true",
        "bash -s",
        'sh -c " ; "',
    )

    REAL = (
        "make test",
        "nice -5 make test",
        "nice -n -5 make test",
        "timeout 600 make ci",
        "timeout 600 -- make ci",
        "git status",
        "npm test",
        "flock /tmp/lock make test",
        "flock -c 'make test'",
        "watch -n 5 make test",
        "setarch x86_64 make test",
        "xargs -n1 make test",
    )

    def test_no_op_hidden_behind_a_prefix_is_rejected(self) -> None:
        for command in self.NO_OPS:
            with self.subTest(command=command):
                result = self.wire("draft", "--check", f"gate::{command}", check=False)
                self.assertNotEqual(result.returncode, 0, command)
                self.assertIn("no-op", result.stderr + result.stdout, command)

    def test_real_commands_behind_a_prefix_are_accepted(self) -> None:
        for command in self.REAL:
            with self.subTest(command=command):
                result = self.wire("draft", "--check", f"gate::{command}", check=False)
                self.assertEqual(
                    result.returncode, 0, f"{command}: {result.stderr}{result.stdout}"
                )

    def test_executable_is_resolved_past_the_prefix(self) -> None:
        """LOW 8: the executable that must exist is the real command."""
        result = self.wire(
            "draft", "--check", "gate::env FOO=1 ./nope.sh", check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("./nope.sh", result.stderr + result.stdout)


class PathContainmentTest(WireLandVerifierTestBase):
    """bento-ei1p round 4 BLOCKER: wrapper/manifest paths must stay in the worktree."""

    def test_draft_rejects_wrapper_path_under_a_symlinked_ancestor(self) -> None:
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        (self.repo / "scripts").symlink_to(outside, target_is_directory=True)
        result = self.wire(
            "draft", "--check", self.passing_check(),
            "--wrapper-path", "scripts/wrapper.py", check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((outside / "wrapper.py").exists())

    def test_apply_rejects_a_symlinked_ancestor_created_after_draft(self) -> None:
        """The check must be live at every command, not trusted from draft time."""
        self.wire(
            "draft", "--check", self.passing_check(),
            "--wrapper-path", "scripts/wrapper.py",
        )
        self.wire("validate")
        outside = Path(self.temp_dir.name) / "outside2"
        outside.mkdir()
        self.assertFalse((self.repo / "scripts").exists())
        (self.repo / "scripts").symlink_to(outside, target_is_directory=True)
        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_draft_refuses_wrapper_path_inside_dot_git(self) -> None:
        result = self.wire(
            "draft", "--check", self.passing_check(),
            "--wrapper-path", ".git/config", check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".git", result.stderr + result.stdout)


class ShellSyntaxCheckTest(WireLandVerifierTestBase):
    """bento-ei1p round 4: a --check needing a shell must say so, not silently narrow."""

    def test_compound_shell_command_is_rejected(self) -> None:
        result = self.wire(
            "draft", "--check", "gate::./test.sh && ./lint.sh", check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("shell", (result.stderr + result.stdout).lower())

    def test_wrapping_in_an_explicit_shell_is_accepted(self) -> None:
        for name in ("test.sh", "lint.sh"):
            script = self.repo / name
            write(script, "#!/bin/sh\nexit 0\n")
            script.chmod(0o755)
        result = self.wire(
            "draft", "--check", "gate::bash -c './test.sh && ./lint.sh'", check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


class ValidateHonestyTest(WireLandVerifierTestBase):
    """bento-ei1p round 4: validate must cross-check exit code and per-check status."""

    def staged_wrapper(self) -> Path:
        git_dir = run(["git", "rev-parse", "--absolute-git-dir"], self.repo).stdout
        return Path(git_dir.strip()) / "bento/wire-land-verifier/wrapper"

    def test_validate_rejects_a_wrapper_that_exits_nonzero_but_claims_passed(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        write(
            self.staged_wrapper(),
            '#!/bin/sh\necho \'{"schema_version":1,"status":"passed",'
            '"selected_checks":[{"name":"unit tests","status":"passed"}]}\'\n'
            "exit 1\n",
        )
        payload = self.payload(self.wire("validate", check=False))
        self.assertFalse(payload["schema_valid"])

    def test_validate_rejects_a_failed_check_under_a_passed_overall_status(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        write(
            self.staged_wrapper(),
            '#!/bin/sh\necho \'{"schema_version":1,"status":"passed",'
            '"selected_checks":[{"name":"unit tests","status":"failed"}]}\'\n'
            "exit 0\n",
        )
        payload = self.payload(self.wire("validate", check=False))
        self.assertFalse(payload["schema_valid"])


class TimeoutProcessGroupTest(WireLandVerifierTestBase):
    """bento-ei1p round 4: a timeout must reach children the gate backgrounds."""

    def test_validate_timeout_kills_a_backgrounded_child(self) -> None:
        marker = self.repo / "child.pid"
        script = self.repo / "backgrounder.sh"
        write(
            script,
            "#!/bin/sh\n"
            f"sh -c 'echo $$ > {marker}; sleep 20' &\n"
            "sleep 20\n",
        )
        script.chmod(0o755)
        self.wire("draft", "--check", "gate::./backgrounder.sh")
        result = self.wire("validate", "--timeout", "2", check=False)
        self.assertNotEqual(result.returncode, 0)

        deadline = time.monotonic() + 5
        child_pid = None
        while time.monotonic() < deadline:
            if marker.exists() and marker.read_text().strip():
                child_pid = marker.read_text().strip()
                break
            time.sleep(0.1)
        self.assertIsNotNone(child_pid, "backgrounded child never started")

        time.sleep(1)
        alive = subprocess.run(["kill", "-0", child_pid]).returncode == 0
        self.assertFalse(alive, "backgrounded child survived the reported timeout")


class ManagedRuntimeLauncherTest(WireLandVerifierTestBase):
    """bento-ei1p round 4: a managed launcher's own resolution shouldn't be second-guessed."""

    def test_uv_run_of_a_tool_not_on_host_path_is_accepted(self) -> None:
        result = self.wire(
            "draft", "--check", "gate::uv run definitely-not-on-host-path-xyz",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


class ManifestCommandConsistencyTest(WireLandVerifierTestBase):
    """bento-ei1p round 5 BLOCKER: validate must prove the manifest points at
    the wrapper it actually executed, not just that its bytes are unchanged."""

    def staged_manifest(self) -> Path:
        git_dir = run(["git", "rev-parse", "--absolute-git-dir"], self.repo).stdout
        return Path(git_dir.strip()) / "bento/wire-land-verifier/verifier.json"

    def test_validate_refuses_a_manifest_pointed_at_a_different_command(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        write(
            self.staged_manifest(),
            json.dumps(
                {
                    "schema_version": 1,
                    "command": ["./other-unvalidated.sh"],
                    "verified_noop": [],
                }
            ),
        )
        result = self.wire("validate", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("command", result.stderr + result.stdout)


class ApplyAtomicityTest(WireLandVerifierTestBase):
    """bento-ei1p round 5 MAJOR: apply must not leave a half-installed pair."""

    def test_apply_restores_the_wrapper_if_the_manifest_write_fails(self) -> None:
        existing_wrapper = self.repo / "scripts/land-work-verifier.py"
        existing_wrapper.parent.mkdir(parents=True, exist_ok=True)
        write(existing_wrapper, "#!/usr/bin/env python3\n# pre-existing\n")
        manifest_path = self.repo / MANIFEST_REL
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        # A directory sitting where the manifest FILE must go: the wrapper
        # install (a normal file replace) succeeds first, then the manifest
        # install hits this and fails -- exactly the partial-apply scenario.
        manifest_path.mkdir()

        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        result = self.wire("apply", "--force", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pre-existing", existing_wrapper.read_text())

    def test_apply_rollback_restores_a_symlinked_wrapper_as_a_symlink(self) -> None:
        """bento-ei1p round 7: rollback must not turn a symlink into a plain-
        file copy of whatever it used to point at."""
        real_target = self.repo / "real-gate.py"
        write(real_target, "# the real target\n")
        wrapper_path = self.repo / "scripts/land-work-verifier.py"
        wrapper_path.parent.mkdir(parents=True, exist_ok=True)
        wrapper_path.symlink_to("../real-gate.py")

        manifest_path = self.repo / MANIFEST_REL
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.mkdir()

        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        result = self.wire("apply", "--force", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(wrapper_path.is_symlink())
        self.assertEqual(os.readlink(wrapper_path), "../real-gate.py")
        self.assertEqual(real_target.read_text(), "# the real target\n")


class BareCommandColonTest(WireLandVerifierTestBase):
    """bento-ei1p round 5 MINOR: a bare command's own '::' (pytest/cargo node
    ids) must not be misparsed as an explicit NAME::COMMAND split."""

    def test_bare_command_with_path_like_node_id_is_not_misparsed(self) -> None:
        gate = self.repo / "gate.sh"
        write(gate, "#!/bin/sh\nexit 0\n")
        gate.chmod(0o755)
        payload = self.payload(
            self.wire("draft", "--check", "./gate.sh subtest::case_a")
        )
        self.assertEqual(payload["checks"][0]["command"], "./gate.sh subtest::case_a")

    def test_a_slashless_bare_node_id_still_needs_an_explicit_name(self) -> None:
        """bento-ei1p round 6: NAME::COMMAND vs. a bare command's own '::' is
        fundamentally ambiguous once neither has a distinguishing marker like a
        path separator -- `cargo test module::case` looks exactly like an
        explicit NAME `cargo test module` with COMMAND `case`. This is not
        solvable by a better heuristic without either false positives on real
        NAME::COMMAND usage or a breaking delimiter change, so the documented
        escape hatch is an explicit NAME:: prefix, which already disambiguates
        correctly because only the FIRST '::' is ever treated as the split."""
        gate = self.repo / "cargo"
        write(gate, "#!/bin/sh\nexit 0\n")
        gate.chmod(0o755)
        payload = self.payload(
            self.wire("draft", "--check", "citest::./cargo test module::case")
        )
        self.assertEqual(
            payload["checks"][0]["command"], "./cargo test module::case"
        )


class CompoundShellNoOpScreeningTest(WireLandVerifierTestBase):
    """bento-ei1p round 7 MINOR: a compound shell script must be screened
    statement by statement, not judged by its first word alone."""

    def test_a_real_command_after_a_trivial_prefix_statement_is_accepted(self) -> None:
        for command in (
            "bash -c 'echo preparing; make test'",
            "bash -c 'true && make test'",
        ):
            with self.subTest(command=command):
                result = self.wire("draft", "--check", f"gate::{command}", check=False)
                self.assertEqual(
                    result.returncode, 0, f"{command}: {result.stderr}{result.stdout}"
                )

    def test_a_compound_script_of_only_no_ops_is_still_rejected(self) -> None:
        result = self.wire(
            "draft", "--check", "gate::bash -c 'echo hi; true'", check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no-op", (result.stderr + result.stdout).lower())


class SessionEscapeTest(WireLandVerifierTestBase):
    """bento-ei1p round 8 MAJOR: setsid escapes the process-group containment
    validate() and land-work's own landing-time timeout both rely on."""

    def test_setsid_is_refused_outright(self) -> None:
        for command in ("setsid make test", "timeout 5 setsid make test"):
            with self.subTest(command=command):
                result = self.wire("draft", "--check", f"gate::{command}", check=False)
                self.assertNotEqual(result.returncode, 0, command)
                self.assertIn("setsid", result.stderr + result.stdout)


class StaleReceiptTest(WireLandVerifierTestBase):
    """bento-ei1p round 8 MINOR: a failed re-validation must invalidate an
    earlier successful receipt, not leave it usable by apply."""

    def test_apply_refuses_after_a_later_validate_fails_even_with_unchanged_bytes(
        self,
    ) -> None:
        slow = self.repo / "slow.sh"
        write(slow, "#!/bin/sh\nsleep 2\nexit 0\n")
        slow.chmod(0o755)
        self.wire("draft", "--check", "gate::./slow.sh")
        payload = self.payload(self.wire("validate", "--timeout", "10"))
        self.assertTrue(payload["schema_valid"])

        # Re-validate the SAME staged bytes with a timeout too tight to
        # finish -- the only thing that changed is that the latest
        # validate() attempt failed.
        result = self.wire("validate", "--timeout", "1", check=False)
        self.assertNotEqual(result.returncode, 0)

        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / MANIFEST_REL).exists())


class MalformedExistingManifestTest(WireLandVerifierTestBase):
    """bento-ei1p round 8 MINOR: a broken existing manifest must be refused,
    not silently treated as having no exemptions to carry forward."""

    def test_draft_refuses_when_the_existing_manifest_is_not_valid_json(self) -> None:
        write(self.repo / MANIFEST_REL, "{not valid json")
        result = self.wire("draft", "--check", self.passing_check(), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(MANIFEST_REL, result.stderr + result.stdout)

    def test_draft_refuses_when_verified_noop_is_not_a_list(self) -> None:
        write(
            self.repo / MANIFEST_REL,
            json.dumps(
                {
                    "schema_version": 1,
                    "command": ["./scripts/old.sh"],
                    "verified_noop": "docs/a.md",
                }
            ),
        )
        result = self.wire("draft", "--check", self.passing_check(), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verified_noop", result.stderr + result.stdout)


class ReverseHonestyCheckTest(WireLandVerifierTestBase):
    """bento-ei1p round 8 MINOR: the honesty check must be symmetric."""

    def staged_wrapper(self) -> Path:
        git_dir = run(["git", "rev-parse", "--absolute-git-dir"], self.repo).stdout
        return Path(git_dir.strip()) / "bento/wire-land-verifier/wrapper"

    def test_validate_rejects_failed_status_when_every_check_actually_passed(
        self,
    ) -> None:
        self.wire("draft", "--check", self.passing_check())
        write(
            self.staged_wrapper(),
            '#!/bin/sh\necho \'{"schema_version":1,"status":"failed",'
            '"selected_checks":[{"name":"unit tests","status":"passed"}]}\'\n'
            "exit 0\n",
        )
        payload = self.payload(self.wire("validate", check=False))
        self.assertFalse(payload["schema_valid"])


if __name__ == "__main__":
    unittest.main()
