from pathlib import Path


def test_pyinstaller_backend_datas_are_file_allowlist():
    spec_path = Path(__file__).resolve().parents[1] / "s2rs-backend.spec"
    spec_text = spec_path.read_text(encoding="utf-8")
    helper_source = spec_text.split("\na = Analysis(", 1)[0]
    namespace = {"__file__": str(spec_path)}

    exec(compile(helper_source, str(spec_path), "exec"), namespace)
    datas = namespace["_collect_backend_datas"]()

    assert datas
    assert ("backend", "backend") not in datas
    for source, destination in datas:
        source_path = Path(source)
        assert source_path.is_file()
        assert source_path.suffix == ".py"
        assert "local_data" not in source_path.parts
        assert destination in {"backend", "backend/migrations"}
