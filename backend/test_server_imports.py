import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestServerImports(unittest.TestCase):
    def _run_import(self, code: str) -> None:
        with tempfile.TemporaryDirectory(prefix="s2rs_import_test_") as data_dir:
            env = {
                **os.environ,
                "PYTHONPATH": "",
                "S2RS_DATA_DIR": data_dir,
                "TMPDIR": data_dir,
            }
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def test_server_imports_as_flat_backend_module(self):
        self._run_import(
            "import sys; "
            f"sys.path.insert(0, {str(REPO_ROOT / 'backend')!r}); "
            "import server; "
            "assert server.app.title == 'SingleStore Report Sniffer v1'"
        )

    def test_server_imports_as_package_module(self):
        self._run_import(
            "import backend.server as server; "
            "assert server.app.title == 'SingleStore Report Sniffer v1'"
        )


if __name__ == "__main__":
    unittest.main()
