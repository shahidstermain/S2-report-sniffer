def test_alembic_config_exists():
    import os
    assert os.path.exists("alembic.ini") or os.path.exists("backend/alembic.ini")
