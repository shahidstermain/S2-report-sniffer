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
