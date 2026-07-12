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
