from pathlib import Path


def _load_spec_helpers(spec_path: Path) -> dict:
    spec_text = spec_path.read_text(encoding="utf-8")
    helper_source = spec_text.split("\na = Analysis(", 1)[0]
    namespace = {"__file__": str(spec_path), "SPEC": str(spec_path)}

    exec(compile(helper_source, str(spec_path), "exec"), namespace)  # nosec B102
    return namespace


def test_pyinstaller_backend_datas_are_file_allowlist():
    spec_path = Path(__file__).resolve().parents[1] / "s2rs-backend.spec"
    namespace = _load_spec_helpers(spec_path)
    datas = namespace["_collect_backend_datas"]()

    assert datas
    assert ("backend", "backend") not in datas
    for source, destination in datas:
        source_path = Path(source)
        assert source_path.is_file()
        assert source_path.suffix == ".py"
        assert "local_data" not in source_path.parts
        assert destination in {"backend", "backend/migrations"}


def test_desktop_pyinstaller_spec_excludes_non_runtime_files(tmp_path):
    spec_path = Path(__file__).resolve().parent / "s2rs-backend.spec"
    namespace = _load_spec_helpers(spec_path)
    namespace["_SOURCE_DIR"] = tmp_path

    (tmp_path / "server.py").write_text("app = object()\n", encoding="utf-8")
    (tmp_path / "customer_investigation.py").write_text(
        "CUSTOMER_TOKEN = 'private'\n",
        encoding="utf-8",
    )
    (tmp_path / "test_server.py").write_text("def test_app(): pass\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=customer-token\n", encoding="utf-8")
    (tmp_path / "customer-report.zip").write_bytes(b"private support data")
    (tmp_path / "reports.sqlite").write_bytes(b"customer database")
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_add_recommendations_metadata.py").write_text(
        "revision = '001'\n",
        encoding="utf-8",
    )

    datas = namespace["_collect_backend_datas"]()
    bundled = {(Path(source).relative_to(tmp_path).as_posix(), destination) for source, destination in datas}

    assert bundled == {
        ("server.py", "backend"),
        ("migrations/001_add_recommendations_metadata.py", "backend/migrations"),
    }
