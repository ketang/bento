import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_OVERLAY = REPO_ROOT / "catalog/skills/swarm/CODEX.md"
CLAUDE_OVERLAY = REPO_ROOT / "catalog/skills/swarm/CLAUDE.md"


class SwarmPlatformGuidanceTest(unittest.TestCase):
    def test_codex_overlay_documents_teammate_model_policy(self) -> None:
        codex_guidance = CODEX_OVERLAY.read_text(encoding="utf-8")

        expected_fragments = (
            ".agent-plugins/bento/bento/swarm/config.json",
            "teammate_model",
            "teammate_reasoning_effort",
            "teammate_config_path",
            'fork_turns: "none"',
            "explicit user",
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, codex_guidance)

    def test_claude_overlay_has_no_codex_teammate_model_policy(self) -> None:
        claude_guidance = CLAUDE_OVERLAY.read_text(encoding="utf-8")

        self.assertNotIn("teammate_model", claude_guidance)
        self.assertNotIn("teammate_reasoning_effort", claude_guidance)
        self.assertNotIn("teammate_config_path", claude_guidance)
        self.assertNotIn('fork_turns: "none"', claude_guidance)


if __name__ == "__main__":
    unittest.main()
