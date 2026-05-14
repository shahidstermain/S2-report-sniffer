import importlib.util
import sys
import tempfile
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class TestUiStaticAssets(unittest.TestCase):
    def test_vite_assets_are_served_under_ui_static_base(self):
        backend_dir = Path(__file__).resolve().parent
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))

        with tempfile.TemporaryDirectory(prefix="s2rs_ui_") as ui_tmp, tempfile.TemporaryDirectory(prefix="s2rs_data_") as data_tmp:
            ui_dir = Path(ui_tmp)
            asset_path = ui_dir / "static" / "assets" / "app.js"
            asset_path.parent.mkdir(parents=True)
            asset_path.write_text("console.log('vite asset loaded');", encoding="utf-8")
            (ui_dir / "index.html").write_text(
                '<script type="module" src="/ui/static/assets/app.js"></script>',
                encoding="utf-8",
            )

            module_name = f"server_under_test_{uuid.uuid4().hex}"
            spec = importlib.util.spec_from_file_location(module_name, backend_dir / "server.py")
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            with patch.dict("os.environ", {"S2RS_UI_DIR": str(ui_dir), "S2RS_DATA_DIR": data_tmp}, clear=False):
                spec.loader.exec_module(module)

            client = TestClient(module.app)
            response = client.get("/ui/static/assets/app.js")

            self.assertEqual(response.status_code, 200)
            self.assertIn("vite asset loaded", response.text)


if __name__ == "__main__":
    unittest.main()
