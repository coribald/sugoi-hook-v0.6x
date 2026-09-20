import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPTS = ("build.bat", "build_debug_standalone.bat")


class BuildScriptTests(unittest.TestCase):
    def test_builds_use_an_isolated_python_environment(self):
        for script_name in BUILD_SCRIPTS:
            with self.subTest(script=script_name):
                script = (PROJECT_ROOT / script_name).read_text(encoding="utf-8")

                self.assertIn('set "BUILD_VENV=%CD%\\.build-venv"', script)
                self.assertIn('set "BUILD_PYTHON=%BUILD_VENV%\\Scripts\\python.exe"', script)
                self.assertIn('python -m venv "%BUILD_VENV%"', script)
                self.assertIn('"%BUILD_PYTHON%" -m pip install', script)
                self.assertIn('"%BUILD_PYTHON%" -m nuitka', script)
                self.assertIsNone(
                    re.search(r"(?im)^python -m (?:pip|nuitka)\b", script),
                    "build dependencies must not be installed or run globally",
                )


if __name__ == "__main__":
    unittest.main()
