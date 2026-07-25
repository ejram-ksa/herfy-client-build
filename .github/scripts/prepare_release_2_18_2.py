from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("prepare_release_2_18_1.py")
spec = importlib.util.spec_from_file_location("herfy_prepare_base", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load release preparation module: {MODULE_PATH}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

module.VERSION = "2.18.2"
module.SETUP = "HerfyTrackingSystem_2.18.2_Setup.exe"

if __name__ == "__main__":
    raise SystemExit(module.main())
