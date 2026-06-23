import os
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"


class TestServerImports(unittest.TestCase):
    def _assert_imports_app(self, module_name: str, cwd: Path):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import importlib; mod = importlib.import_module({module_name!r}); assert mod.app.title",
            ],
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_flat_server_import_from_backend_directory(self):
        self._assert_imports_app("server", BACKEND_DIR)

    def test_package_server_import_from_repo_root(self):
        self._assert_imports_app("backend.server", REPO_ROOT)

    def test_package_server_import_from_backend_directory_with_repo_on_pythonpath(self):
        self._assert_imports_app("backend.server", BACKEND_DIR)


if __name__ == "__main__":
    unittest.main()
