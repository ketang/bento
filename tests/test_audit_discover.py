import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "catalog" / "skills" / "generate-audit" / "scripts" / "audit-discover.py"


def load_audit_discover_module():
    loader = importlib.machinery.SourceFileLoader("audit_discover", str(SCRIPT))
    spec = importlib.util.spec_from_loader("audit_discover", loader)
    if spec is None:
        raise RuntimeError("unable to create spec for audit-discover")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class AuditDiscoverTest(unittest.TestCase):
    def test_demo_walkthrough_signals_detect_demo_surfaces(self) -> None:
        module = load_audit_discover_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_json = {
                "packageManager": "pnpm@10.0.0",
                "scripts": {
                    "demo": "playwright test demo.spec.ts",
                    "demo:headed": "playwright test --headed demo.spec.ts",
                },
            }
            rel_files = [
                "package.json",
                "Makefile",
                "scripts/demo.sh",
                "tests/demo.spec.ts",
                ".demo-warnings.jsonl",
                ".bugshot/baseline/manifest.json",
                "tmp/demo/screenshots/01-home.png",
                "docs/demo-walkthrough.md",
            ]
            (root / "package.json").write_text(json.dumps(package_json), encoding="utf-8")

            signals = module.demo_walkthrough_signals(
                root,
                rel_files,
                package_json,
                {"demo": ["make demo"]},
            )

        self.assertEqual(
            signals["commands"],
            ["make demo", "pnpm run demo", "pnpm run demo:headed"],
        )
        self.assertEqual(signals["scripts"], ["scripts/demo.sh"])
        self.assertEqual(signals["playwright_files"], ["tests/demo.spec.ts"])
        self.assertEqual(signals["warning_queues"], [".demo-warnings.jsonl"])
        self.assertEqual(signals["bugshot_paths"], [".bugshot/baseline/manifest.json"])
        self.assertEqual(signals["docs"], ["docs/demo-walkthrough.md"])

    def test_demo_walkthrough_signals_avoid_skill_and_packaging_false_positives(self) -> None:
        module = load_audit_discover_module()
        signals = module.demo_walkthrough_signals(
            Path("/repo"),
            [
                "catalog/skills/generate-web-demo/SKILL.md",
                "catalog/skills/generate-web-demo/assets/playwright-controller/controller.js",
                "plugins/claude/bento/assets/screenshot-1.png",
                "docs/specs/2026-04-26-bugshot-standalone-plugin-design.md",
            ],
            None,
            {"demo": []},
        )

        self.assertEqual(signals["commands"], [])
        self.assertEqual(signals["playwright_files"], [])
        self.assertEqual(signals["screenshot_paths"], [])
        self.assertEqual(signals["bugshot_paths"], [])
        self.assertEqual(signals["docs"], [])


if __name__ == "__main__":
    unittest.main()
