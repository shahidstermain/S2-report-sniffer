def test_alembic_config_exists():
    import os
    assert os.path.exists("alembic.ini") or os.path.exists("backend/alembic.ini")


def test_mongo_url_redaction_strips_credentials():
    """C-6: migration runners must not log embedded Mongo credentials."""
    import rollback_runner
    import migrations_runner

    url = "mongodb://admin:s3cr3t@db.internal:27017/app"
    for redactor in (rollback_runner._redact_mongo_url, migrations_runner._redact_mongo_url):
        redacted = redactor(url)
        assert "s3cr3t" not in redacted
        assert "admin" not in redacted
        assert "db.internal:27017" in redacted
        # URLs without credentials pass through unchanged.
        assert redactor("mongodb://localhost:27017") == "mongodb://localhost:27017"


def test_rollback_migrations_dir_points_to_migrations_subdir():
    """H-4: rollback runner must resolve migration files under migrations/."""
    import os
    import rollback_runner

    assert os.path.basename(rollback_runner.MIGRATIONS_DIR) == "migrations"
    assert os.path.isdir(rollback_runner.MIGRATIONS_DIR)


def test_delete_report_logs_partial_filesystem_cleanup(tmp_path, caplog, monkeypatch):
    """Data retention failures must be visible rather than silently swallowed."""
    import asyncio
    import logging
    from pathlib import Path
    from storage import LocalReportStore

    store = LocalReportStore(tmp_path)
    report_id = "00000000-0000-0000-0000-000000000099"
    asyncio.run(store.create_report_stub(report_id, "sample", 1, "zip"))
    asyncio.run(store.write_report_payload(report_id, {"nodes": []}))

    original_rmdir = Path.rmdir

    def fail_report_rmdir(path):
        if path.name == report_id:
            raise OSError("simulated cleanup failure")
        return original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", fail_report_rmdir)
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(store.delete_report(report_id))

    assert "Report directory cleanup incomplete" in caplog.text


def test_store_removes_reports_from_retired_demo_feature(tmp_path):
    """Opening an older data directory removes synthetic demo rows and files."""
    import asyncio
    from storage import LocalReportStore

    store = LocalReportStore(tmp_path)
    demo_id = "11111111-2222-4333-8444-555555555501"
    real_id = "00000000-0000-4000-8000-000000000001"
    with store._store_db() as conn:
        conn.execute(
            "ALTER TABLE reports ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"
        )
        conn.executemany(
            """
            INSERT INTO reports (
                id, report_name, uploaded_at, status, file_size, detected_format, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (demo_id, "Retired demo", "2026-01-01T00:00:00Z", "ready", 0, "demo", 1),
                (real_id, "Customer report", "2026-01-01T00:00:00Z", "ready", 1, "zip", 0),
            ],
        )
        conn.commit()

    demo_dir = tmp_path / "reports" / demo_id
    demo_dir.mkdir(parents=True)
    (demo_dir / "report.json").write_text("{}", encoding="utf-8")

    reopened = LocalReportStore(tmp_path)
    rows = asyncio.run(reopened.list_reports())

    assert [row["id"] for row in rows] == [real_id]
    assert not demo_dir.exists()
