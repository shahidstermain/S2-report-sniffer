import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestServerImportPaths(unittest.TestCase):
    def test_server_imports_as_backend_package_from_repo_root(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="s2rs_import_test_") as data_dir:
            env = {
                **os.environ,
                "S2RS_DATA_DIR": data_dir,
                "PYTHONPATH": str(repo_root),
            }
            result = subprocess.run(
                [sys.executable, "-c", "import backend.server; print('package import ok')"],
                cwd=repo_root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("package import ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
