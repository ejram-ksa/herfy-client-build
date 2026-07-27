from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SourceStructureTests(unittest.TestCase):
    def test_version_single_source(self) -> None:
        data = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "2.18.1")
        self.assertEqual(data["app_version"], data["version"])

    def test_obsolete_roots_removed(self) -> None:
        for name in (
            "app",
            "application",
            "bootstrap",
            "core",
            "data",
            "domain",
            "presentation",
            "remote",
            "services",
            "settings",
            "ui",
            "installer",
            "release",
        ):
            self.assertFalse((ROOT / name).exists(), name)

    def test_required_roots_exist(self) -> None:
        for name in ("runtime", "build", "tests"):
            self.assertTrue((ROOT / name).exists(), name)

    def test_no_obsolete_absolute_imports(self) -> None:
        pattern = re.compile(
            r"^\s*(?:from|import)\s+"
            r"(app|application|bootstrap|core|data|domain|presentation|"
            r"remote|services|settings|ui)(?:\.|\s|$)",
            re.MULTILINE,
        )
        offenders = []
        for path in ROOT.rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
