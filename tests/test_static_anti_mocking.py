"""Static anti-mocking AST audit and Home Assistant config schema verification."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = REPO_ROOT / "custom_components" / "wine_inventory"

FORBIDDEN_TOKENS = (
    "mock_success",
    "fake_fallback",
    "dummy_wine",
    "MOCK_VIVINO",
    "FAKE_GEMINI_RESPONSE",
)


class _HABlueprintYamlLoader(yaml.SafeLoader):
    """YAML Loader supporting Home Assistant's !input tag in Blueprints."""


_HABlueprintYamlLoader.add_constructor(
    "!input",
    lambda loader, node: f"!input {loader.construct_scalar(node)}",
)


class TestStaticAntiMockingAndSchemas(unittest.TestCase):
    """Verify zero hardcoded mock fallbacks and validate all JSON/YAML schemas."""

    def test_no_hardcoded_mock_fallbacks_in_production_code(self) -> None:
        """Audit production Python modules to enforce Zero-Mocking engineering standard."""
        py_files = list(INTEGRATION_DIR.glob("*.py"))
        self.assertGreaterEqual(len(py_files), 8)

        for py_file in py_files:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
            self.assertIsNotNone(tree)

            lower_source = source.lower()
            for token in FORBIDDEN_TOKENS:
                self.assertNotIn(
                    token.lower(),
                    lower_source,
                    f"Forbidden mock token '{token}' found in {py_file}",
                )

    def test_manifest_and_translations_valid_json(self) -> None:
        """Verify manifest.json, strings.json, and translations/en.json are valid and aligned."""
        manifest = json.loads(
            (INTEGRATION_DIR / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["domain"], "wine_inventory")
        self.assertTrue(manifest["config_flow"])

        strings = json.loads(
            (INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8")
        )
        en_trans = json.loads(
            (INTEGRATION_DIR / "translations" / "en.json").read_text(encoding="utf-8")
        )
        self.assertEqual(strings, en_trans)
        self.assertIn("gemini_model", strings["config"]["step"]["user"]["data"])

    def test_dashboard_blueprint_and_services_valid_yaml(self) -> None:
        """Verify dashboard YAML uses sections view, heading/tile/distribution cards, and blueprint is valid."""
        services_path = INTEGRATION_DIR / "services.yaml"
        services_data = yaml.safe_load(services_path.read_text(encoding="utf-8"))
        self.assertIn("scan_bottle", services_data)
        self.assertIn("add_wine", services_data)
        self.assertIn("adjust_quantity", services_data)
        self.assertIn("update_wine", services_data)

        dashboard_path = REPO_ROOT / "dashboards" / "wine-cellar-dashboard.yaml"
        dashboard_data = yaml.safe_load(dashboard_path.read_text(encoding="utf-8"))
        views = dashboard_data["views"]
        self.assertEqual(views[0]["type"], "sections")
        sections = views[0]["sections"]
        self.assertGreaterEqual(len(sections), 2)

        card_types = [
            card["type"]
            for section in sections
            for card in section.get("cards", [])
        ]
        self.assertIn("heading", card_types)
        self.assertIn("tile", card_types)
        self.assertIn("distribution", card_types)
        self.assertIn("custom:wine-inventory-card", card_types)

        blueprint_path = (
            REPO_ROOT
            / "blueprints"
            / "automation"
            / "wine_inventory"
            / "cellar_alerts.yaml"
        )
        blueprint_data = yaml.load(
            blueprint_path.read_text(encoding="utf-8"),
            Loader=_HABlueprintYamlLoader,
        )
        self.assertEqual(blueprint_data["blueprint"]["domain"], "automation")
        self.assertIn("source_url", blueprint_data["blueprint"])


if __name__ == "__main__":
    unittest.main()
