"""Parity pins for vendored duplicate scripts (bento-ly4).

Several helper scripts are physically copied into more than one skill or
platform hook directory. There is no build-time step that regenerates the
copies from a single canonical source, so the copies can silently drift. This
test pins the copies that are *meant* to stay in lockstep, and records the
copies that have *intentionally* forked with a reason, so that:

  * accidental drift in a lockstep group fails the gate, and
  * an intentional fork is documented in one place rather than being lost.

Generating the copies from one canonical source at build time is a possible
longer-term direction, but is deliberately out of scope here (see bento-ly4):
this test only pins parity and documents fork intent.

To reconverge a documented fork later, delete its entry below and add its path
back into the relevant lockstep group.
"""

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


# --- Lockstep groups: every path in a group must be byte-for-byte identical ---
#
# Each entry: (label, [repo-relative paths]).
IDENTICAL_GROUPS = [
    (
        "git_state.py canonical (worktree-enumerating variant)",
        [
            "catalog/skills/launch-work/scripts/git_state.py",
            "catalog/skills/handoff/scripts/git_state.py",
            "catalog/skills/expedition/scripts/git_state.py",
        ],
    ),
    (
        "telemetry bento_telemetry.py (claude/codex)",
        [
            "catalog/hooks/telemetry/claude/scripts/bento_telemetry.py",
            "catalog/hooks/telemetry/codex/scripts/bento_telemetry.py",
        ],
    ),
    (
        "telemetry bento-telemetry.py entrypoint (claude/codex)",
        [
            "catalog/hooks/telemetry/claude/scripts/bento-telemetry.py",
            "catalog/hooks/telemetry/codex/scripts/bento-telemetry.py",
        ],
    ),
    (
        "seed-agent-plugins.py (claude/codex)",
        [
            "catalog/hooks/bento/claude/scripts/seed-agent-plugins.py",
            "catalog/hooks/bento/codex/scripts/seed-agent-plugins.py",
        ],
    ),
]


# --- Modulo-docstring groups: identical once the module docstring is stripped ---
#
# The claude and codex copies differ only in the first-line module docstring
# ("Claude ..." vs "Codex ..."). Everything below the docstring must match.
IDENTICAL_MODULO_DOCSTRING_GROUPS = [
    (
        "telemetry record-bash.py PostToolUse hook (claude/codex)",
        [
            "catalog/hooks/telemetry/claude/scripts/record-bash.py",
            "catalog/hooks/telemetry/codex/scripts/record-bash.py",
        ],
    ),
]


# --- Documented intentional forks: NOT asserted against the canonical copy ---
#
# Each entry: (repo-relative path, reason). These are copies of a shared helper
# that have deliberately diverged. They are listed here so the divergence is a
# recorded decision, and so the manifest fails if the file is deleted/moved.
DOCUMENTED_FORKS = [
    (
        "catalog/skills/land-work/scripts/git_state.py",
        "Intentional fork: land-work carries a landing-specific helper set "
        "(rev_exists, ahead_behind, working_tree_dirty, current_branch, "
        "rev_parse, tree_for_ref) consumed by land-work-{verify-landing,"
        "create-preview,prepare}.py, and drops parse_worktrees, which land-work "
        "does not use. Not expected to match the canonical variant.",
    ),
    (
        "catalog/skills/swarm/scripts/git_state.py",
        "Fork: byte-identical to the canonical variant except the trailing "
        "parse_worktrees function is absent; swarm's consumers (swarm-state, "
        "swarm-discover, swarm-worktree-verify) do not use it. Divergence is "
        "harmless (canonical is a strict superset) and is a candidate for "
        "reconvergence to the canonical copy, but is left as-is here to avoid "
        "expanding this parity-only change's scope.",
    ),
]


def _read(rel_path: str) -> bytes:
    return (REPO_ROOT / rel_path).read_bytes()


def _strip_module_docstring(text: str) -> str:
    """Remove the first triple-quoted module docstring block."""
    return re.sub(r'"""(?:.|\n)*?"""', "", text, count=1)


class TestVendoredParity(unittest.TestCase):
    def test_all_manifest_paths_exist(self) -> None:
        """Every path named in the manifest must exist, so it cannot rot."""
        paths = []
        for _, group in IDENTICAL_GROUPS + IDENTICAL_MODULO_DOCSTRING_GROUPS:
            paths.extend(group)
        paths.extend(path for path, _ in DOCUMENTED_FORKS)

        missing = [p for p in paths if not (REPO_ROOT / p).is_file()]
        self.assertEqual(missing, [], f"manifest paths missing on disk: {missing}")

    def test_identical_groups_are_byte_identical(self) -> None:
        for label, group in IDENTICAL_GROUPS:
            with self.subTest(group=label):
                first = group[0]
                first_bytes = _read(first)
                for other in group[1:]:
                    self.assertEqual(
                        _read(other),
                        first_bytes,
                        f"{other} drifted from {first} ({label}); vendored "
                        "copies must stay byte-identical. Reconcile the copies, "
                        "or if the fork is intentional move it to DOCUMENTED_FORKS.",
                    )

    def test_modulo_docstring_groups_match_below_docstring(self) -> None:
        for label, group in IDENTICAL_MODULO_DOCSTRING_GROUPS:
            with self.subTest(group=label):
                first = group[0]
                first_norm = _strip_module_docstring(_read(first).decode())
                for other in group[1:]:
                    self.assertEqual(
                        _strip_module_docstring(_read(other).decode()),
                        first_norm,
                        f"{other} drifted from {first} below the module "
                        f"docstring ({label}); only the docstring may differ.",
                    )

    def test_documented_forks_still_diverge(self) -> None:
        """A documented fork that has re-converged should be reclassified.

        If a fork becomes byte-identical to the canonical git_state variant, it
        is no longer a fork and should move into the lockstep group instead of
        lingering here with a stale reason.
        """
        canonical = _read("catalog/skills/launch-work/scripts/git_state.py")
        for path, reason in DOCUMENTED_FORKS:
            with self.subTest(path=path):
                self.assertTrue(reason.strip(), f"{path} needs a fork reason")
                if _read(path) == canonical:
                    self.fail(
                        f"{path} is now byte-identical to the canonical "
                        "git_state.py; remove it from DOCUMENTED_FORKS and add "
                        "it to the canonical IDENTICAL_GROUPS group."
                    )


if __name__ == "__main__":
    unittest.main()
