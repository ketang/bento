import unittest
from pathlib import Path

from tests.script_test_utils import load_module


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = load_module(REPO_ROOT / "catalog/skills/build-vs-buy/scripts/build_vs_buy_catalog.py")


class BuildVsBuyCatalogTest(unittest.TestCase):
    def test_framework_aliases_cover_expected_stacks(self) -> None:
        self.assertIn("next", MODULE.FRAMEWORK_ALIASES["nextjs"])
        self.assertIn("fastapi", MODULE.FRAMEWORK_ALIASES["fastapi"])
        self.assertIn("@sveltejs/kit", MODULE.FRAMEWORK_ALIASES["sveltekit"])

    def test_tool_categories_include_representative_patterns(self) -> None:
        self.assertIn("@aws-sdk/*", MODULE.TOOL_CATEGORIES["cloud_providers"]["aws"])
        self.assertIn("bullmq", MODULE.TOOL_CATEGORIES["job_runtimes"]["bullmq"])
        self.assertIn("github.com/pressly/goose*", MODULE.TOOL_CATEGORIES["migration_tools"]["goose"])

    def test_feature_family_categories_point_to_known_tool_categories(self) -> None:
        for categories in MODULE.FAMILY_TO_TOOL_CATEGORIES.values():
            for category in categories:
                self.assertIn(category, MODULE.TOOL_CATEGORIES)

    def test_feature_patterns_define_keywords_and_comparisons(self) -> None:
        for feature_name, feature in MODULE.FEATURE_PATTERNS.items():
            self.assertTrue(feature["keywords"], feature_name)
            self.assertTrue(feature["comparison_categories"], feature_name)
            self.assertTrue(feature["touchpoints"], feature_name)

    def test_signal_catalogs_cover_multiple_detection_sources(self) -> None:
        self.assertIn("vercel", MODULE.FILE_SIGNAL_PATTERNS["hosting_platforms"])
        self.assertIn("docker", MODULE.TEXT_SIGNAL_PATTERNS["deployment_targets"])
        self.assertIn("AWS_", MODULE.ENV_SIGNAL_PATTERNS["cloud_providers"]["aws"])
        self.assertIn("self-hosted-preferred", MODULE.POLICY_PATTERNS["hosting_bias"])

    def test_general_comparison_categories_include_core_tradeoffs(self) -> None:
        self.assertIn("fit_with_existing_stack", MODULE.GENERAL_COMPARISON_CATEGORIES)
        self.assertIn("integration_cost", MODULE.GENERAL_COMPARISON_CATEGORIES)
        self.assertIn("lock_in_risk", MODULE.GENERAL_COMPARISON_CATEGORIES)


if __name__ == "__main__":
    unittest.main()
